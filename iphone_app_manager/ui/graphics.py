"""A tiny anti-aliased rasteriser that produces Tk images (no extra packages).

Shapes are described as signed-distance functions; edge pixels get partial
coverage, which gives smooth rounded corners at any display scale. Results are
encoded as PNG and loaded into ``tk.PhotoImage``.
"""
from __future__ import annotations

import base64
import math
import struct
import tkinter as tk
import zlib
from typing import Callable, Optional, Sequence

SDF = Callable[[float, float], float]


def hex_rgb(color: str) -> tuple[float, float, float]:
    h = color.lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


# ---------------------------------------------------------------- shapes (signed distance)
def round_rect(x0: float, y0: float, x1: float, y1: float, r: float) -> SDF:
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hw, hh = (x1 - x0) / 2, (y1 - y0) / 2
    r = max(0.0, min(r, hw, hh))

    def d(x: float, y: float) -> float:
        qx = abs(x - cx) - hw + r
        qy = abs(y - cy) - hh + r
        return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r
    return d


def circle(cx: float, cy: float, r: float) -> SDF:
    return lambda x, y: math.hypot(x - cx, y - cy) - r


def ring(shape: SDF, width: float) -> SDF:
    """Inner stroke of a shape."""
    return lambda x, y: abs(shape(x, y) + width / 2) - width / 2


def polyline(points: Sequence[tuple[float, float]], width: float) -> SDF:
    half = width / 2
    segments = list(zip(points, points[1:]))

    def d(x: float, y: float) -> float:
        best = math.inf
        for (ax, ay), (bx, by) in segments:
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
            best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
        return best - half
    return d


# ---------------------------------------------------------------- raster
class Raster:
    """RGBA canvas with premultiplied alpha."""

    def __init__(self, width: int, height: int) -> None:
        self.w, self.h = max(1, int(width)), max(1, int(height))
        self.buf = [0.0] * (self.w * self.h * 4)

    def fill(self, shape: SDF, color: str, alpha: float = 1.0,
             bbox: Optional[tuple[float, float, float, float]] = None) -> None:
        r, g, b = hex_rgb(color)
        w, buf = self.w, self.buf
        if bbox:
            x0, y0 = max(0, int(bbox[0])), max(0, int(bbox[1]))
            x1, y1 = min(w, math.ceil(bbox[2])), min(self.h, math.ceil(bbox[3]))
        else:
            x0, y0, x1, y1 = 0, 0, w, self.h
        for py in range(y0, y1):
            cy = py + 0.5
            for px in range(x0, x1):
                d = shape(px + 0.5, cy)
                if d >= 0.5:
                    continue
                a = alpha if d <= -0.5 else alpha * (0.5 - d)
                i = (py * w + px) * 4
                k = 1.0 - a
                buf[i] = r * a + buf[i] * k
                buf[i + 1] = g * a + buf[i + 1] * k
                buf[i + 2] = b * a + buf[i + 2] * k
                buf[i + 3] = a + buf[i + 3] * k

    def blit(self, other: "Raster", ox: int, oy: int) -> None:
        """Composite another raster on top (source-over)."""
        for y in range(other.h):
            ty = y + oy
            if not 0 <= ty < self.h:
                continue
            for x in range(other.w):
                tx = x + ox
                if not 0 <= tx < self.w:
                    continue
                s = (y * other.w + x) * 4
                a = other.buf[s + 3]
                if a <= 0:
                    continue
                t = (ty * self.w + tx) * 4
                k = 1.0 - a
                for c in range(4):
                    self.buf[t + c] = other.buf[s + c] + self.buf[t + c] * k

    def to_png(self) -> bytes:
        raw = bytearray()
        buf = self.buf
        for y in range(self.h):
            raw.append(0)
            for x in range(self.w):
                i = (y * self.w + x) * 4
                a = buf[i + 3]
                if a > 0:
                    raw += bytes((min(255, round(buf[i] / a * 255)), min(255, round(buf[i + 1] / a * 255)),
                                  min(255, round(buf[i + 2] / a * 255)), min(255, round(a * 255))))
                else:
                    raw += b"\x00\x00\x00\x00"

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        header = struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))

    def photo(self, master: tk.Misc) -> tk.PhotoImage:
        return tk.PhotoImage(master=master, data=base64.b64encode(self.to_png()))


# ---------------------------------------------------------------- cached UI images
_cache: dict[tuple, tk.PhotoImage] = {}


def cached(master: tk.Misc, key: tuple, build: Callable[[], Raster]) -> tk.PhotoImage:
    image = _cache.get(key)
    if image is None or image.tk is not master.tk:   # images belong to one Tk interpreter
        image = _cache[key] = build().photo(master)
    return image


def rounded_box(master: tk.Misc, w: int, h: int, radius: float, fill: str,
                border: Optional[str] = None, border_width: float = 1.0,
                glow: Optional[str] = None, glow_width: float = 0.0) -> tk.PhotoImage:
    """Rounded rectangle with optional border and soft outer glow (glow_width is reserved either way)."""
    key = ("box", w, h, round(radius, 2), fill, border, round(border_width, 2), glow, round(glow_width, 2))

    def build() -> Raster:
        img = Raster(w, h)
        g = glow_width
        if glow and g > 0:
            img.fill(round_rect(0, 0, w, h, radius + g), glow, alpha=0.22)
        outer = round_rect(g, g, w - g, h - g, radius)
        if border and border != fill:
            img.fill(outer, border)
            bw = border_width
            img.fill(round_rect(g + bw, g + bw, w - g - bw, h - g - bw, max(0.0, radius - bw)), fill)
        else:
            img.fill(outer, fill)
        return img
    return cached(master, key, build)


def dot(master: tk.Misc, size: int, color: str, style: str = "solid", alpha: float = 1.0) -> tk.PhotoImage:
    """Status dot: 'solid', 'halo' (dot with soft ring) or 'ring' (hollow)."""
    key = ("dot", size, color, style, round(alpha, 2))

    def build() -> Raster:
        img = Raster(size, size)
        c = size / 2
        if style == "halo":
            img.fill(circle(c, c, c - 0.5), color, alpha=alpha * 0.28)
            img.fill(circle(c, c, size * 0.27), color, alpha=alpha)
        elif style == "ring":
            img.fill(ring(circle(c, c, size * 0.32), max(1.5, size * 0.12)), color, alpha=alpha)
        else:
            img.fill(circle(c, c, size * 0.32), color, alpha=alpha)
        return img
    return cached(master, key, build)
