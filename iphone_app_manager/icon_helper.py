"""Icon helper process: reads app icons from the connected iPhone (read-only).

Runs as a *separate process* (``python -I icon_helper.py <bin-dir> <size>``) so that a
fault inside the native libimobiledevice DLL can never crash the main application.
Uses only the Python standard library.

Safety: the ONLY SpringBoard function used is ``sbservices_get_icon_pngdata``, which
reads an app's Home Screen icon. Nothing that changes the iPhone (for example the Home
Screen layout) is declared or called. No files are written; icons go to stdout only.

Protocol
  stdin : bundle identifiers, one per line (UTF-8), then EOF.
  stdout: a stream of binary records:
            b"I" + >H id_len + >I png_len + id + png      icon resized to <size> px
            b"F" + >H id_len + >i error   + id            icon unavailable
            b"E"                                          finished
  exit  : 0 ok, 2 no device, 3 SpringBoard service unavailable (not trusted / locked),
          4 library could not be loaded, 1 unexpected error. Details on stderr.
"""
from __future__ import annotations

import ctypes
import os
import struct
import sys
import zlib

EXIT_NO_DEVICE = 2
EXIT_SERVICE = 3
EXIT_LIBRARY = 4


# ====================================================================== PNG decode / resize / encode
class PngError(Exception):
    pass


def _unfilter(raw: bytes, height: int, stride: int, bpp: int) -> bytearray:
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += stride + 1
        if ftype == 0:
            pass
        elif ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        else:
            raise PngError(f"bad filter type {ftype}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def decode_png(data: bytes) -> tuple[int, int, bytes]:
    """Decode an 8/16-bit RGB(A) or greyscale(+alpha) PNG to 8-bit RGBA."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PngError("not a PNG")
    pos, idat, header = 8, [], None
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if not header or not idat:
        raise PngError("missing IHDR/IDAT")
    width, height, depth, color, _comp, _filt, interlace = header
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color)
    if channels is None or depth not in (8, 16) or interlace:
        raise PngError(f"unsupported PNG (colour {color}, depth {depth}, interlace {interlace})")
    bpp = channels * depth // 8
    stride = width * bpp
    pixels = _unfilter(zlib.decompress(b"".join(idat)), height, stride, bpp)
    if depth == 16:
        pixels = pixels[0::2]  # keep the high byte of each sample
    n = width * height
    if color == 6:
        rgba = bytes(pixels)
    else:
        rgba_buf = bytearray(n * 4)
        if color == 2:
            for c in range(3):
                rgba_buf[c::4] = pixels[c::3]
            rgba_buf[3::4] = b"\xff" * n
        elif color == 0:
            for c in range(3):
                rgba_buf[c::4] = pixels
            rgba_buf[3::4] = b"\xff" * n
        else:  # 4: grey + alpha
            for c in range(3):
                rgba_buf[c::4] = pixels[0::2]
            rgba_buf[3::4] = pixels[1::2]
        rgba = bytes(rgba_buf)
    return width, height, rgba


def _weights(src: int, dst: int) -> list[list[tuple[int, float]]]:
    """Area-averaging weights for resampling one axis from src to dst samples."""
    scale = src / dst
    table = []
    for o in range(dst):
        start, end = o * scale, (o + 1) * scale
        taps = []
        i = int(start)
        while i < end and i < src:
            cover = min(end, i + 1) - max(start, i)
            if cover > 0:
                taps.append((i, cover / scale))
            i += 1
        table.append(taps)
    return table


def resize_rgba(width: int, height: int, rgba: bytes, size: int) -> bytes:
    """High-quality downscale (area average on premultiplied alpha) to size x size."""
    n = width * height
    r, g, b, a = rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4]
    # premultiply
    pr = [r[i] * a[i] / 255 for i in range(n)]
    pg = [g[i] * a[i] / 255 for i in range(n)]
    pb = [b[i] * a[i] / 255 for i in range(n)]
    pa = list(a)
    wx, wy = _weights(width, size), _weights(height, size)

    def horizontal(chan: list[float]) -> list[list[float]]:
        rows = []
        for y in range(height):
            base = y * width
            rows.append([sum(chan[base + i] * w for i, w in taps) for taps in wx])
        return rows

    planes = [horizontal(c) for c in (pr, pg, pb, pa)]
    out = bytearray(size * size * 4)
    for oy, taps in enumerate(wy):
        for ox in range(size):
            vals = [sum(plane[i][ox] * w for i, w in taps) for plane in planes]
            alpha = vals[3]
            o = (oy * size + ox) * 4
            if alpha > 0.5:
                k = 255.0 / alpha
                out[o] = min(255, int(vals[0] * k + 0.5))
                out[o + 1] = min(255, int(vals[1] * k + 0.5))
                out[o + 2] = min(255, int(vals[2] * k + 0.5))
                out[o + 3] = min(255, int(alpha + 0.5))
    return bytes(out)


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def thumbnail(png: bytes, size: int) -> bytes:
    width, height, rgba = decode_png(png)
    return encode_png(size, size, resize_rgba(width, height, rgba, size))


# ====================================================================== libimobiledevice (read-only)
class SpringBoardIcons:
    """Minimal ctypes binding: connect, read icon PNGs, disconnect. Nothing else."""

    def __init__(self, bin_dir: str) -> None:
        os.add_dll_directory(bin_dir)
        lib = ctypes.CDLL(os.path.join(bin_dir, "libimobiledevice-1.0.dll"))
        self._crt = ctypes.CDLL("ucrtbase")  # the MSYS2 UCRT64 build allocates with the UCRT heap
        vp = ctypes.c_void_p
        lib.idevice_new.argtypes = [ctypes.POINTER(vp), ctypes.c_char_p]
        lib.idevice_free.argtypes = [vp]
        lib.sbservices_client_start_service.argtypes = [vp, ctypes.POINTER(vp), ctypes.c_char_p]
        lib.sbservices_client_free.argtypes = [vp]
        lib.sbservices_get_icon_pngdata.argtypes = [vp, ctypes.c_char_p, ctypes.POINTER(vp),
                                                    ctypes.POINTER(ctypes.c_uint64)]
        self._crt.free.argtypes = [vp]
        self._lib = lib
        self._device = vp()
        self._client = vp()

    def connect(self) -> None:
        err = self._lib.idevice_new(ctypes.byref(self._device), None)
        if err != 0:
            raise ConnectionError(EXIT_NO_DEVICE, f"No iPhone found (idevice error {err}).")
        err = self._lib.sbservices_client_start_service(self._device, ctypes.byref(self._client),
                                                        b"iPhoneAppManager")
        if err != 0:
            raise ConnectionError(EXIT_SERVICE, f"Could not start SpringBoard service (error {err}). "
                                                "The iPhone may be locked or not trusted.")

    def icon_png(self, bundle_id: str) -> tuple[int, bytes]:
        data, size = ctypes.c_void_p(), ctypes.c_uint64()
        err = self._lib.sbservices_get_icon_pngdata(self._client, bundle_id.encode("utf-8"),
                                                     ctypes.byref(data), ctypes.byref(size))
        try:
            if err != 0 or not data.value or not size.value:
                return (err or -1), b""
            return 0, ctypes.string_at(data.value, size.value)
        finally:
            if data.value:
                self._crt.free(data)

    def close(self) -> None:
        if self._client.value:
            self._lib.sbservices_client_free(self._client)
            self._client = ctypes.c_void_p()
        if self._device.value:
            self._lib.idevice_free(self._device)
            self._device = ctypes.c_void_p()


# ====================================================================== main
def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("usage: icon_helper.py <libimobiledevice-bin-dir> <size>\n")
        return 1
    bin_dir, size = argv[1], int(argv[2])
    out = sys.stdout.buffer
    bundle_ids = [line.strip() for line in sys.stdin.buffer.read().decode("utf-8").splitlines() if line.strip()]

    try:
        springboard = SpringBoardIcons(bin_dir)
    except OSError as exc:
        sys.stderr.write(f"Could not load libimobiledevice: {exc}\n")
        return EXIT_LIBRARY
    try:
        springboard.connect()
        for bundle_id in bundle_ids:
            ident = bundle_id.encode("utf-8")
            err, png = springboard.icon_png(bundle_id)
            if not err:
                try:
                    png = thumbnail(png, size)
                except (PngError, zlib.error, struct.error, ValueError) as exc:
                    sys.stderr.write(f"{bundle_id}: {exc}\n")
                    err = -100
            if err:
                out.write(b"F" + struct.pack(">Hi", len(ident), err) + ident)
            else:
                out.write(b"I" + struct.pack(">HI", len(ident), len(png)) + ident + png)
            out.flush()
        out.write(b"E")
        out.flush()
        return 0
    except ConnectionError as exc:
        code, message = exc.args
        sys.stderr.write(message + "\n")
        return code
    except OSError:
        return 0  # the app stopped listening (e.g. Refresh or exit) - broken pipe
    finally:
        springboard.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
