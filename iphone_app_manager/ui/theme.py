"""Design tokens (colours, fonts, icon glyphs) and the few remaining ttk styles.

Palette: orange (accent), slate grey (secondary surfaces, headings, toolbar
elements) and white (main background and content).
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk


class Colors:
    WHITE = "#FFFFFF"

    SLATE_50 = "#F8FAFC"
    SLATE_100 = "#F1F5F9"
    SLATE_200 = "#E2E8F0"
    SLATE_300 = "#CBD5E1"
    SLATE_400 = "#94A3B8"
    SLATE_500 = "#64748B"
    SLATE_600 = "#475569"
    SLATE_700 = "#334155"
    SLATE_800 = "#1E293B"
    SLATE_900 = "#0F172A"

    ORANGE = "#EA580C"
    ORANGE_HOVER = "#DC4E07"
    ORANGE_PRESSED = "#C2410C"
    ORANGE_SOFT = "#FB923C"
    ORANGE_DISABLED = "#F9C6A5"
    ORANGE_TINT = "#FFF6F0"
    ORANGE_TINT_HOVER = "#FFEFE4"
    ORANGE_TINT_STRONG = "#FFE4D1"


class Glyph:
    """Segoe Fluent Icons / Segoe MDL2 Assets code points."""

    SEARCH = ""
    REFRESH = ""
    SORT = ""
    SELECT_ALL = ""
    CLEAR_SELECTION = ""
    CHECK = ""
    PHONE = ""
    LOCK = ""
    WARNING = ""
    CHEVRON_UP = ""
    CHEVRON_DOWN = ""
    DELETE = ""
    CANCEL = ""


@dataclass
class Fonts:
    body: tkfont.Font
    body_bold: tkfont.Font
    small: tkfont.Font
    small_bold: tkfont.Font
    caption: tkfont.Font
    title: tkfont.Font
    heading: tkfont.Font
    icon: tkfont.Font
    icon_small: tkfont.Font
    icon_tiny: tkfont.Font
    icon_large: tkfont.Font
    has_icons: bool


def _pick(available: set[str], *names: str) -> str:
    for name in names:
        if name in available:
            return name
    return names[-1]


def apply_theme(root: tk.Tk, scale: float) -> Fonts:
    """Create fonts and configure ttk styles. Keep the returned Fonts referenced."""
    def px(n: float) -> int:
        return int(round(n * scale))

    available = set(tkfont.families(root))
    text = _pick(available, "Segoe UI Variable Text", "Segoe UI")
    text_semi = _pick(available, "Segoe UI Variable Text Semibold", "Segoe UI Semibold")
    small_semi = _pick(available, "Segoe UI Variable Small Semibol", "Segoe UI Semibold")
    display_semi = _pick(available, "Segoe UI Variable Display Semib", "Segoe UI Semibold")
    icon_family = _pick(available, "Segoe Fluent Icons", "Segoe MDL2 Assets", "")
    has_icons = icon_family in available

    fonts = Fonts(
        body=tkfont.Font(root, family=text, size=10),
        body_bold=tkfont.Font(root, family=text_semi, size=10),
        small=tkfont.Font(root, family=text, size=9),
        small_bold=tkfont.Font(root, family=text_semi, size=9),
        caption=tkfont.Font(root, family=small_semi, size=8),
        title=tkfont.Font(root, family=display_semi, size=17),
        heading=tkfont.Font(root, family=display_semi, size=14),
        icon=tkfont.Font(root, family=icon_family or text, size=10),
        icon_small=tkfont.Font(root, family=icon_family or text, size=9),
        icon_tiny=tkfont.Font(root, family=icon_family or text, size=7),
        icon_large=tkfont.Font(root, family=icon_family or text, size=22),
        has_icons=has_icons,
    )
    for name in ("TkDefaultFont", "TkTextFont"):
        tkfont.nametofont(name).configure(family=text, size=10)

    root.configure(background=Colors.WHITE)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=Colors.WHITE, foreground=Colors.SLATE_900, font=fonts.body)

    # Slim scrollbar without arrows.
    style.layout("Slim.Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"}),
        ]}),
    ])
    style.configure("Slim.Vertical.TScrollbar", troughcolor=Colors.WHITE, background=Colors.SLATE_300,
                    bordercolor=Colors.WHITE, lightcolor=Colors.SLATE_300, darkcolor=Colors.SLATE_300,
                    arrowsize=px(10), width=px(10), relief="flat", gripcount=0)
    thumb = [("pressed", Colors.SLATE_500), ("active", Colors.SLATE_400)]
    style.map("Slim.Vertical.TScrollbar", background=thumb, lightcolor=thumb, darkcolor=thumb)
    style.layout("Slim.Horizontal.TScrollbar", [
        ("Horizontal.Scrollbar.trough", {"sticky": "ew", "children": [
            ("Horizontal.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"}),
        ]}),
    ])
    style.configure("Slim.Horizontal.TScrollbar", troughcolor=Colors.WHITE, background=Colors.SLATE_300,
                    bordercolor=Colors.WHITE, lightcolor=Colors.SLATE_300, darkcolor=Colors.SLATE_300,
                    arrowsize=px(10), width=px(10), relief="flat", gripcount=0)
    style.map("Slim.Horizontal.TScrollbar", background=thumb, lightcolor=thumb, darkcolor=thumb)

    # Thin orange loading bar that sits on the slate header.
    style.configure("Accent.Horizontal.TProgressbar", troughcolor=Colors.SLATE_800,
                    background=Colors.ORANGE, bordercolor=Colors.SLATE_800,
                    lightcolor=Colors.ORANGE, darkcolor=Colors.ORANGE, thickness=px(3))
    # Uninstall progress bar (in the progress dialog).
    style.configure("Uninstall.Horizontal.TProgressbar", troughcolor=Colors.SLATE_100,
                    background=Colors.ORANGE, bordercolor=Colors.SLATE_100,
                    lightcolor=Colors.ORANGE, darkcolor=Colors.ORANGE, thickness=px(6))
    return fonts
