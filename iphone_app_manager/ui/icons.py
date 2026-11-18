"""Checkbox and placeholder app-icon images for the app list."""
from __future__ import annotations

import base64
import hashlib
import tkinter as tk

from .graphics import Raster, polyline, round_rect
from .theme import Colors

# Placeholder tiles use slate tones; each app gets a stable tone from its bundle ID.
TILE_PALETTE = ["#334155", "#475569", "#64748B", "#526079", "#3B4A60", "#6B7A90"]


def draw_checkbox(size: int, checked: bool) -> Raster:
    s = float(size)
    img = Raster(size, size)
    radius = s * 0.26
    outer = round_rect(0.5, 0.5, s - 0.5, s - 0.5, radius)
    if checked:
        img.fill(outer, Colors.ORANGE)
        tick = [(s * 0.27, s * 0.52), (s * 0.44, s * 0.69), (s * 0.75, s * 0.33)]
        img.fill(polyline(tick, s * 0.13), Colors.WHITE)
    else:
        img.fill(outer, Colors.SLATE_300)
        inset = max(1.2, s * 0.075)
        img.fill(round_rect(0.5 + inset, 0.5 + inset, s - 0.5 - inset, s - 0.5 - inset,
                            max(0.5, radius - inset)), Colors.WHITE)
    return img


def draw_tile(size: int, color: str) -> Raster:
    """A rounded app-icon placeholder with a simple 2x2 'apps' glyph."""
    s = float(size)
    img = Raster(size, size)
    img.fill(round_rect(0, 0, s, s, s * 0.24), color)
    cell, gap = s * 0.19, s * 0.08
    start = (s - (2 * cell + gap)) / 2
    for row in range(2):
        for col in range(2):
            x0 = start + col * (cell + gap)
            y0 = start + row * (cell + gap)
            img.fill(round_rect(x0, y0, x0 + cell, y0 + cell, cell * 0.3), Colors.WHITE,
                     alpha=0.92, bbox=(x0 - 1, y0 - 1, x0 + cell + 1, y0 + cell + 1))
    return img


class IconFactory:
    """Creates and caches the images used in the app list."""

    def __init__(self, master: tk.Misc, scale: float) -> None:
        self.master = master
        # Sizes are unchanged from the original design.
        self.checkbox_size = max(14, round(18 * scale))
        self.tile_size = max(20, round(28 * scale))
        self.gap = round(14 * scale)
        self.row_image_width = self.checkbox_size + self.gap + self.tile_size
        self._images: dict[tuple, tk.PhotoImage] = {}
        # Real icons from the iPhone, already resized to tile_size by the helper.
        # Held in memory only for the current session; cleared on Refresh.
        self._real_icons: dict[str, tk.PhotoImage] = {}

    @staticmethod
    def color_index(key: str) -> int:
        return hashlib.md5(key.encode("utf-8")).digest()[0] % len(TILE_PALETTE)

    def checkbox_image(self, checked: bool) -> tk.PhotoImage:
        key = ("checkbox", checked)
        if key not in self._images:
            self._images[key] = draw_checkbox(self.checkbox_size, checked).photo(self.master)
        return self._images[key]

    def placeholder_image(self, bundle_id: str) -> tk.PhotoImage:
        idx = self.color_index(bundle_id)
        key = ("tile", idx)
        if key not in self._images:
            self._images[key] = draw_tile(self.tile_size, TILE_PALETTE[idx]).photo(self.master)
        return self._images[key]

    def app_icon(self, bundle_id: str) -> tk.PhotoImage:
        """The real icon if it has been retrieved, otherwise the placeholder tile."""
        return self._real_icons.get(bundle_id) or self.placeholder_image(bundle_id)

    def set_real_icon(self, bundle_id: str, png: bytes) -> bool:
        """Store a real icon. Rejects anything not exactly tile_size square (keeps the placeholder)."""
        try:
            image = tk.PhotoImage(master=self.master, data=base64.b64encode(png))
        except tk.TclError:
            return False
        if image.width() != self.tile_size or image.height() != self.tile_size:
            return False
        self._real_icons[bundle_id] = image
        return True

    def has_real_icon(self, bundle_id: str) -> bool:
        return bundle_id in self._real_icons

    def clear_real_icons(self) -> None:
        self._real_icons.clear()

    def prune_real_icons(self, keep: set[str]) -> None:
        """Drop icons of apps that are no longer installed; keep the rest."""
        for bundle_id in list(self._real_icons):
            if bundle_id not in keep:
                del self._real_icons[bundle_id]

    def brand_icon(self, size: int) -> tk.PhotoImage:
        """Orange app tile used for the window icon and the header logo."""
        key = ("brand", size)
        if key not in self._images:
            self._images[key] = draw_tile(size, Colors.ORANGE).photo(self.master)
        return self._images[key]
