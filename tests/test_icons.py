"""Offline tests for real-icon support (no iPhone needed).

Run with:  py -3.12 -m unittest discover -s tests -v
"""
from __future__ import annotations

import re
import struct
import sys
import threading
import time
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from iphone_app_manager import app_icons, icon_helper  # noqa: E402


def _png(width, height, rows, color_type, depth, filters):
    """Build a PNG from already-filtered rows (filters[i] is row i's filter byte)."""
    raw = b"".join(bytes([f]) + r for f, r in zip(filters, rows))

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color_type, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _filter_row(ftype, line, prev, bpp):
    out = bytearray(len(line))
    for i in range(len(line)):
        a = line[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        if ftype == 0:
            pred = 0
        elif ftype == 1:
            pred = a
        elif ftype == 2:
            pred = b
        elif ftype == 3:
            pred = (a + b) >> 1
        else:
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
        out[i] = (line[i] - pred) & 0xFF
    return bytes(out)


class PngDecodeTests(unittest.TestCase):
    def test_all_filter_types_rgb8(self):
        w, h, bpp = 5, 5, 3
        lines = [bytes((x * 40 + y * 7) & 0xFF for x in range(w * bpp)) for y in range(h)]
        prev, rows = bytes(w * bpp), []
        for ftype, line in zip(range(5), lines):
            rows.append(_filter_row(ftype, line, prev, bpp))
            prev = line
        width, height, rgba = icon_helper.decode_png(_png(w, h, rows, 2, 8, list(range(5))))
        self.assertEqual((width, height), (w, h))
        for y in range(h):
            for x in range(w):
                px = rgba[(y * w + x) * 4:(y * w + x) * 4 + 4]
                self.assertEqual(tuple(px), (*lines[y][x * 3:x * 3 + 3], 255))

    def test_rgba16_keeps_high_byte(self):
        row = struct.pack(">HHHH", 0x1234, 0xABCD, 0x00FF, 0xFF00)
        _, _, rgba = icon_helper.decode_png(_png(1, 1, [row], 6, 16, [0]))
        self.assertEqual(tuple(rgba), (0x12, 0xAB, 0x00, 0xFF))

    def test_rejects_garbage(self):
        with self.assertRaises(icon_helper.PngError):
            icon_helper.decode_png(b"not a png at all")


class ResizeTests(unittest.TestCase):
    def test_exact_output_size_and_colour(self):
        size = 42
        src = bytes((200, 100, 50, 255)) * (192 * 192)
        png = icon_helper.encode_png(192, 192, src)
        w, h, rgba = icon_helper.decode_png(icon_helper.thumbnail(png, size))
        self.assertEqual((w, h), (size, size))
        self.assertEqual(tuple(rgba[:4]), (200, 100, 50, 255))
        self.assertEqual(tuple(rgba[-4:]), (200, 100, 50, 255))

    def test_transparent_corners_stay_transparent_and_colour_does_not_darken(self):
        # Opaque red square in the middle of a transparent 20x20 image.
        px = []
        for y in range(20):
            for x in range(20):
                inside = 5 <= x < 15 and 5 <= y < 15
                px.append((255, 0, 0, 255) if inside else (0, 0, 0, 0))
        out = icon_helper.resize_rgba(20, 20, bytes(c for p in px for c in p), 10)
        self.assertEqual(out[3], 0)                              # corner transparent
        centre = (5 * 10 + 5) * 4
        self.assertEqual(tuple(out[centre:centre + 4]), (255, 0, 0, 255))


class HelperSafetyTests(unittest.TestCase):
    def test_only_read_only_springboard_call(self):
        source = (ROOT / "iphone_app_manager" / "icon_helper.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        code = re.sub(r'"""[\s\S]*?"""', "", code)  # ignore docstrings
        sb_calls = set(re.findall(r"sbservices_\w+", code))
        self.assertEqual(sb_calls, {"sbservices_client_start_service", "sbservices_get_icon_pngdata",
                                    "sbservices_client_free"})
        for forbidden in ("set_icon_state", "wallpaper", "afc_", "house_arrest", "installation_proxy"):
            self.assertNotIn(forbidden, code)


def _fake_helper(script: str) -> list[str]:
    return [sys.executable, "-I", "-c", script]


class FetchProtocolTests(unittest.TestCase):
    def fetch(self, script, ids=("a.b", "c.d"), **kw):
        got = []
        result = app_icons.fetch_icons(list(ids), 42, lambda bid, png: got.append((bid, png)),
                                       threading.Event(), command=_fake_helper(script), **kw)
        return got, result

    def test_icons_and_failures_stream(self):
        script = (
            "import sys,struct\n"
            "ids=sys.stdin.read().split()\n"
            "o=sys.stdout.buffer\n"
            "o.write(b'I'+struct.pack('>HI',len(ids[0]),3)+ids[0].encode()+b'PNG')\n"
            "o.write(b'F'+struct.pack('>Hi',len(ids[1]),-1)+ids[1].encode())\n"
            "o.write(b'E')\n"
        )
        got, result = self.fetch(script)
        self.assertEqual(got, [("a.b", b"PNG")])
        self.assertEqual((result.received, result.failed, result.error), (1, ["c.d"], None))

    def test_no_device_exit_code(self):
        _, result = self.fetch("import sys; sys.stdin.read(); sys.exit(2)")
        self.assertEqual(result.error, "iPhone not connected")

    def test_not_trusted_exit_code(self):
        _, result = self.fetch("import sys; sys.stdin.read(); sys.exit(3)")
        self.assertEqual(result.error, "iPhone locked or not trusted")

    def test_crash_is_contained(self):
        _, result = self.fetch("import sys,os; sys.stdin.read(); os._exit(-1073741819)")  # access violation
        self.assertIn("icon helper stopped", result.error)

    def test_hang_is_killed_by_idle_timeout(self):
        start = time.monotonic()
        _, result = self.fetch("import sys,time; sys.stdin.read(); time.sleep(60)", idle_timeout=1.0)
        self.assertEqual(result.error, "timed out")
        self.assertLess(time.monotonic() - start, 10)

    def test_cancel_stops_helper(self):
        cancel = threading.Event()
        threading.Timer(0.5, cancel.set).start()
        start = time.monotonic()
        result = app_icons.fetch_icons(["x"], 42, lambda *_: None, cancel,
                                       command=_fake_helper("import time; time.sleep(60)"))
        self.assertTrue(result.cancelled)
        self.assertLess(time.monotonic() - start, 10)


if __name__ == "__main__":
    unittest.main()
