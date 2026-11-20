"""Custom Canvas-based widgets: rounded buttons, pills, search box and the app list."""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable, Iterable, Optional, Sequence

from .. import config
from ..models import AppInfo, AppSize
from . import graphics
from .icons import IconFactory
from .theme import Colors, Fonts, Glyph


class _Scaled:
    scale: float

    def p(self, n: float) -> int:
        return int(round(n * self.scale))


# ====================================================================== buttons
class RoundedButton(tk.Canvas, _Scaled):
    """Rounded button with hover, pressed, disabled and keyboard-focus states."""

    # state -> (fill, border, text)
    STYLES = {
        "primary": {
            "normal": (Colors.ORANGE, Colors.ORANGE, Colors.WHITE),
            "hover": (Colors.ORANGE_HOVER, Colors.ORANGE_HOVER, Colors.WHITE),
            "pressed": (Colors.ORANGE_PRESSED, Colors.ORANGE_PRESSED, Colors.WHITE),
            "disabled": (Colors.ORANGE_DISABLED, Colors.ORANGE_DISABLED, Colors.WHITE),
        },
        "secondary": {
            "normal": (Colors.WHITE, Colors.SLATE_200, Colors.SLATE_700),
            "hover": (Colors.SLATE_50, Colors.SLATE_300, Colors.SLATE_900),
            "pressed": (Colors.SLATE_100, Colors.SLATE_300, Colors.SLATE_900),
            "disabled": (Colors.WHITE, Colors.SLATE_100, Colors.SLATE_300),
        },
    }

    def __init__(self, master: tk.Misc, *, text: str, command: Optional[Callable[[], None]],
                 fonts: Fonts, scale: float, variant: str = "secondary", glyph: Optional[str] = None,
                 min_width: int = 0, height: int = 36, bg: str = Colors.WHITE) -> None:
        tk.Canvas.__init__(self, master, bg=bg, highlightthickness=0, bd=0, takefocus=1)
        self.scale = scale
        self._fonts = fonts
        self._text = text
        self._command = command
        self._variant = variant
        self._glyph = glyph if fonts.has_icons else None
        self._min_width = self.p(min_width)
        self._height_px = self.p(height)
        self._enabled = True
        self._hover = self._pressed = self._focus = False
        self.bind("<Enter>", lambda _e: self._set(_hover=True))
        self.bind("<Leave>", lambda _e: self._set(_hover=False))
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<FocusIn>", lambda _e: self._set(_focus=True))
        self.bind("<FocusOut>", lambda _e: self._set(_focus=False))
        self.bind("<Return>", self._on_key)
        self.bind("<space>", self._on_key)
        self._draw()

    # public API
    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self._draw()

    def set_command(self, command: Optional[Callable[[], None]]) -> None:
        self._command = command

    def set_enabled(self, enabled: bool) -> None:
        if enabled != self._enabled:
            self._enabled = enabled
            self.configure(takefocus=1 if enabled else 0)
            self._draw()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def compact(self) -> bool:
        return getattr(self, "_compact", False)

    def set_compact(self, compact: bool) -> None:
        """Icon-only (square) form, used when the toolbar is too narrow for the full labels."""
        compact = compact and bool(self._glyph)
        if compact != self.compact:
            self._compact = compact
            self._draw()

    def natural_width(self, compact: bool = False) -> int:
        if compact and self._glyph:
            return self._height_px
        f = self._fonts
        icon_w = f.icon.measure(self._glyph) + self.p(8) if self._glyph else 0
        return max(self._min_width, f.body_bold.measure(self._text) + icon_w + self.p(32))

    def invoke(self) -> None:
        if self._enabled and self._command:
            self._command()

    # events
    def _set(self, **changes: bool) -> None:
        for name, value in changes.items():
            setattr(self, name, value)
        self._draw()

    def _on_press(self, _e: tk.Event) -> None:
        if self._enabled:
            self._set(_pressed=True)

    def _on_release(self, e: tk.Event) -> None:
        was_pressed = self._pressed
        inside = 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
        self._set(_pressed=False)
        if was_pressed and inside:
            self.invoke()

    def _on_key(self, _e: tk.Event) -> str:
        self.invoke()
        return "break"

    def _draw(self) -> None:
        f = self._fonts
        if self.compact:
            text_w, icon_w = 0, f.icon.measure(self._glyph)
            w = self._height_px
        else:
            text_w = f.body_bold.measure(self._text)
            icon_w = f.icon.measure(self._glyph) + self.p(8) if self._glyph else 0
            w = max(self._min_width, text_w + icon_w + self.p(32))
        h = self._height_px
        if not self._enabled:
            state = "disabled"
        elif self._pressed and self._hover:
            state = "pressed"
        elif self._hover:
            state = "hover"
        else:
            state = "normal"
        fill, border, fg = self.STYLES[self._variant][state]
        border_w = max(1.0, self.scale)
        if self._focus and self._enabled:
            border, border_w = (Colors.ORANGE_PRESSED if self._variant == "primary" else Colors.ORANGE,
                                1.6 * self.scale)
        image = graphics.rounded_box(self, w, h, self.p(8), fill, border, border_w)
        self.configure(width=w, height=h, cursor="hand2" if self._enabled else "arrow")
        self.delete("all")
        self._image = image
        self.create_image(0, 0, anchor="nw", image=image)
        x = (w - text_w - icon_w) / 2
        if self._glyph:
            self.create_text(x, h / 2 + 1, text=self._glyph, font=f.icon, fill=fg, anchor="w")
            x += icon_w
        if not self.compact:
            self.create_text(x, h / 2, text=self._text, font=f.body_bold, fill=fg, anchor="w")


# ====================================================================== pills
class Pill(tk.Canvas, _Scaled):
    """Rounded label with an optional status dot or icon. Supports a pulsing dot."""

    def __init__(self, master: tk.Misc, *, fonts: Fonts, scale: float, bg: str,
                 height: int = 28, font: Optional[tkfont.Font] = None, padx: int = 12) -> None:
        tk.Canvas.__init__(self, master, bg=bg, highlightthickness=0, bd=0)
        self.scale = scale
        self._fonts = fonts
        self._font = font or fonts.small_bold
        self._height_px = self.p(height)
        self._padx = self.p(padx)
        self._spec: dict = {}
        self._dim = False
        self._job: Optional[str] = None
        self._command: Optional[Callable[[], None]] = None
        self._hover = False
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Button-1>", lambda _e: self._command() if self._command else None)

    def set_command(self, command: Optional[Callable[[], None]]) -> None:
        """Make the pill clickable (or not)."""
        self._command = command
        self.configure(cursor="hand2" if command else "")
        if self._spec:
            self._draw()

    def _set_hover(self, hover: bool) -> None:
        self._hover = hover
        if self._spec and self._command:
            self._draw()

    def set(self, text: str, *, fill: str, fg: str, border: Optional[str] = None,
            dot: Optional[str] = None, dot_style: str = "solid", glyph: Optional[str] = None,
            pulse: bool = False) -> None:
        self._spec = dict(text=text, fill=fill, fg=fg, border=border, dot=dot,
                          dot_style=dot_style, glyph=glyph if self._fonts.has_icons else None)
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self._dim = False
        self._draw()
        if pulse:
            self._job = self.after(600, self._pulse)

    def _pulse(self) -> None:
        self._dim = not self._dim
        self._draw()
        self._job = self.after(600, self._pulse)

    def _draw(self) -> None:
        s = self._spec
        h, padx = self._height_px, self._padx
        text_w = self._font.measure(s["text"])
        dot_d = int(h * 0.55)
        if s["dot"]:
            lead = dot_d + self.p(4)
        elif s["glyph"]:
            lead = self._fonts.icon_small.measure(s["glyph"]) + self.p(6)
        else:
            lead = 0
        lead_pad = padx - self.p(4) if s["dot"] else padx
        w = lead_pad + lead + text_w + padx
        border = s["border"]
        if self._command and self._hover:   # clickable pill: subtle hover outline
            border = Colors.ORANGE_PRESSED if s["fill"] == Colors.ORANGE else Colors.SLATE_300
        bg = graphics.rounded_box(self, w, h, h / 2, s["fill"], border, max(1.0, self.scale))
        self.delete("all")
        self._images = [bg]
        self.configure(width=w, height=h)
        self.create_image(0, 0, anchor="nw", image=bg)
        x = lead_pad
        if s["dot"]:
            dot_img = graphics.dot(self, dot_d, s["dot"], s["dot_style"], alpha=0.35 if self._dim else 1.0)
            self._images.append(dot_img)
            self.create_image(x, h / 2, anchor="w", image=dot_img)
        elif s["glyph"]:
            self.create_text(x, h / 2 + 1, text=s["glyph"], font=self._fonts.icon_small, fill=s["fg"], anchor="w")
        self.create_text(x + lead, h / 2, text=s["text"], font=self._font, fill=s["fg"], anchor="w")


class SegmentedControl(tk.Canvas, _Scaled):
    """A small bar of mutually exclusive options (the chosen one in orange), for the slate header."""

    def __init__(self, master: tk.Misc, *, options: Sequence[tuple[str, object]], value: object,
                 command: Optional[Callable[[object], None]], fonts: Fonts, scale: float, bg: str,
                 height: int = 30) -> None:
        tk.Canvas.__init__(self, master, bg=bg, highlightthickness=0, bd=0, takefocus=1)
        self.scale = scale
        self._fonts = fonts
        self._segments = list(options)
        self._value = value
        self._command = command
        self._height_px = self.p(height)
        self._enabled = True
        self._focus = False
        self._hover: Optional[int] = None
        self._edges: list[tuple[int, int]] = []
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda _e: self._set_hover(None))
        self.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.bind("<FocusOut>", lambda _e: self._set_focus(False))
        self.bind("<Left>", lambda _e: self._step(-1))
        self.bind("<Right>", lambda _e: self._step(1))
        self._draw()

    @property
    def value(self) -> object:
        return self._value

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_value(self, value: object) -> None:
        """Show ``value`` as chosen without calling the command (used to undo a refused change)."""
        if value != self._value:
            self._value = value
            self._draw()

    def set_enabled(self, enabled: bool) -> None:
        if enabled != self._enabled:
            self._enabled = enabled
            self.configure(takefocus=1 if enabled else 0)
            self._draw()

    def select(self, value: object) -> None:
        """The user chose ``value``. Does nothing while disabled or when it is already chosen."""
        if not self._enabled or value == self._value or value not in [v for _t, v in self._segments]:
            return
        self._value = value
        self._draw()
        if self._command:
            self._command(value)

    # events
    def _index_at(self, x: int) -> Optional[int]:
        for i, (left, right) in enumerate(self._edges):
            if left <= x < right:
                return i
        return None

    def _on_click(self, e: tk.Event) -> None:
        self.focus_set()
        i = self._index_at(e.x)
        if i is not None:
            self.select(self._segments[i][1])

    def _on_motion(self, e: tk.Event) -> None:
        self._set_hover(self._index_at(e.x) if self._enabled else None)

    def _set_hover(self, index: Optional[int]) -> None:
        if index != self._hover:
            self._hover = index
            self._draw()

    def _set_focus(self, focus: bool) -> None:
        self._focus = focus
        self._draw()

    def _step(self, step: int) -> str:
        values = [v for _t, v in self._segments]
        i = values.index(self._value) + step
        if 0 <= i < len(values):
            self.select(values[i])
        return "break"

    def _draw(self) -> None:
        f, h = self._fonts, self._height_px
        pad, inset = self.p(14), self.p(3)
        widths = [f.small_bold.measure(text) + 2 * pad for text, _v in self._segments]
        total = sum(widths) + 2 * inset
        border = Colors.ORANGE if self._focus and self._enabled else Colors.SLATE_600
        frame = graphics.rounded_box(self, total, h, h / 2, Colors.SLATE_700, border, max(1.0, self.scale))
        self.delete("all")
        self._images = [frame]
        self.configure(width=total, height=h, cursor="hand2" if self._enabled else "arrow")
        self.create_image(0, 0, anchor="nw", image=frame)
        x = inset
        self._edges = []
        for i, ((text, value), w) in enumerate(zip(self._segments, widths)):
            chosen = value == self._value
            if chosen:
                fill = Colors.ORANGE if self._enabled else Colors.SLATE_500
                seg = graphics.rounded_box(self, w, h - 2 * inset, (h - 2 * inset) / 2, fill)
                self._images.append(seg)
                self.create_image(x, inset, anchor="nw", image=seg)
                fg = Colors.WHITE
            else:
                fg = (Colors.WHITE if self._hover == i else Colors.SLATE_300) if self._enabled else Colors.SLATE_500
            self.create_text(x + w / 2, h / 2, text=text, font=f.small_bold, fill=fg, anchor="center")
            self._edges.append((x, x + w))
            x += w


class IconBadge(tk.Canvas, _Scaled):
    """Large circular icon used in the empty / error states."""

    def __init__(self, master: tk.Misc, *, fonts: Fonts, scale: float, bg: str, size: int = 72) -> None:
        tk.Canvas.__init__(self, master, bg=bg, highlightthickness=0, bd=0)
        self.scale = scale
        self._fonts = fonts
        self._d = self.p(size)
        self.configure(width=self._d, height=self._d)

    def set(self, glyph: str, accent: bool) -> None:
        d = self._d
        fill, fg = (Colors.ORANGE_TINT_STRONG, Colors.ORANGE) if accent else (Colors.SLATE_100, Colors.SLATE_500)
        self._image = graphics.rounded_box(self, d, d, d / 2, fill)
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=self._image)
        if self._fonts.has_icons:
            self.create_text(d / 2, d / 2, text=glyph, font=self._fonts.icon_large, fill=fg)


# ====================================================================== search box
class SearchBox(tk.Canvas, _Scaled):
    """Rounded search field with icon, placeholder and an orange focus ring."""

    def __init__(self, master: tk.Misc, *, variable: tk.StringVar, fonts: Fonts, scale: float,
                 width: int, placeholder: str, bg: str = Colors.WHITE,
                 min_width: Optional[int] = None, short_placeholder: Optional[str] = None) -> None:
        tk.Canvas.__init__(self, master, bg=bg, highlightthickness=0, bd=0)
        self.scale = scale
        self._fonts = fonts
        self._var = variable
        self._glow = self.p(3)
        self.max_width = self.p(width)
        self.min_width = self.p(min_width) if min_width else self.max_width
        self._width_px, self._height_px = self.max_width, self.p(38) + 2 * self._glow
        self._focus = self._hover = False
        self.configure(width=self._width_px, height=self._height_px, cursor="xterm")

        self._text_x = self._glow + (self.p(38) if fonts.has_icons else self.p(14))
        self.entry = tk.Entry(self, textvariable=variable, bd=0, relief="flat", highlightthickness=0,
                              font=fonts.body, fg=Colors.SLATE_900, insertbackground=Colors.SLATE_900,
                              selectbackground=Colors.ORANGE_TINT_STRONG, selectforeground=Colors.SLATE_900)
        self._full_placeholder = placeholder
        self._short_placeholder = short_placeholder or placeholder
        self._placeholder = tk.Label(self, text=placeholder, bd=0, padx=0, font=fonts.body,
                                     fg=Colors.SLATE_400, cursor="xterm")
        self._placeholder_x = self._text_x + 1
        self._place_entry()

        for widget in (self, self.entry, self._placeholder):
            widget.bind("<Enter>", self._on_enter, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")
        self.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self._placeholder.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.entry.bind("<FocusIn>", lambda _e: self._set_focus(True), add="+")
        self.entry.bind("<FocusOut>", lambda _e: self._set_focus(False), add="+")
        variable.trace_add("write", lambda *_: self._update_placeholder())
        self._draw()
        self._update_placeholder()

    def _place_entry(self) -> None:
        entry_w = self._width_px - self._text_x - self._glow - self.p(12)
        self.entry.place(x=self._text_x, rely=0.5, anchor="w", width=entry_w)
        full = self._fonts.body.measure(self._full_placeholder) <= entry_w
        self._placeholder.configure(text=self._full_placeholder if full else self._short_placeholder)

    def set_width(self, width_px: int) -> None:
        """Resize between min_width and max_width (rounded to limit image re-rendering)."""
        step = self.p(20)
        width_px = max(self.min_width, min(self.max_width, width_px))
        if width_px < self.max_width:
            width_px = max(self.min_width, width_px // step * step)
        if width_px == self._width_px:
            return
        self._width_px = width_px
        self.configure(width=width_px)
        self._place_entry()
        self._draw()

    def _on_enter(self, _e: tk.Event) -> None:
        if not self._hover:
            self._hover = True
            self._draw()

    def _on_leave(self, e: tk.Event) -> None:
        inside = self.winfo_containing(e.x_root, e.y_root) in (self, self.entry, self._placeholder)
        if self._hover and not inside:
            self._hover = False
            self._draw()

    def _set_focus(self, focus: bool) -> None:
        self._focus = focus
        self._draw()

    def _update_placeholder(self) -> None:
        if self._var.get():
            self._placeholder.place_forget()
        else:
            self._placeholder.place(x=self._placeholder_x, rely=0.5, anchor="w")

    def _draw(self) -> None:
        if self._focus:
            fill, border, glow, icon = Colors.WHITE, Colors.ORANGE, Colors.ORANGE, Colors.ORANGE
        elif self._hover:
            fill, border, glow, icon = Colors.SLATE_50, Colors.SLATE_300, None, Colors.SLATE_500
        else:
            fill, border, glow, icon = Colors.SLATE_50, Colors.SLATE_200, None, Colors.SLATE_400
        bw = 1.6 * self.scale if self._focus else max(1.0, self.scale)
        self._image = graphics.rounded_box(self, self._width_px, self._height_px, self.p(9), fill, border, bw,
                                           glow=glow, glow_width=self._glow)
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=self._image)
        if self._fonts.has_icons:
            self.create_text(self._glow + self.p(14), self._height_px / 2 + 1, text=Glyph.SEARCH,
                             font=self._fonts.icon, fill=icon, anchor="w")
        self.entry.configure(bg=fill)
        self._placeholder.configure(bg=fill)


# ====================================================================== storage formatting
def format_bytes(n: int) -> str:
    """Decimal units, matching iOS Settings (1 GB = 1,000,000,000 bytes)."""
    if n >= 1_000_000_000:
        return f"{n / 1e9:.2f} GB"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f} MB"
    if n >= 1_000:
        return f"{n / 1e3:.0f} KB"
    return "0 KB" if n == 0 else f"{n} bytes"


# ====================================================================== hover details card
class DetailsCard(tk.Toplevel, _Scaled):
    """Small slate card with an app's details, shown when hovering over its name."""

    def __init__(self, master: tk.Misc, *, fonts: Fonts, scale: float, title: str,
                 rows: Sequence[tuple[str, str]], x_root: int, y_root: int) -> None:
        tk.Toplevel.__init__(self, master, bg=Colors.SLATE_800)
        self.scale = scale
        self.withdraw()
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        box = tk.Frame(self, bg=Colors.SLATE_800)
        box.pack(padx=self.p(14), pady=(self.p(10), self.p(12)))
        tk.Label(box, text=title, font=fonts.body_bold, fg=Colors.WHITE, bg=Colors.SLATE_800,
                 anchor="w").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, self.p(6)))
        for r, (label, value) in enumerate(rows, start=1):
            tk.Label(box, text=label, font=fonts.small, fg=Colors.SLATE_400, bg=Colors.SLATE_800,
                     anchor="w").grid(row=r, column=0, sticky="nw", padx=(0, self.p(14)))
            muted = value in ("Not available", "Calculating…")
            tk.Label(box, text=value, font=fonts.small, fg=Colors.SLATE_400 if muted else Colors.WHITE,
                     bg=Colors.SLATE_800, anchor="w", justify="left",
                     wraplength=self.p(300)).grid(row=r, column=1, sticky="w")
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = min(x_root + self.p(16), self.winfo_screenwidth() - w - self.p(8))
        y = y_root + self.p(18)
        if y + h > self.winfo_screenheight() - self.p(48):
            y = y_root - h - self.p(12)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deiconify()


# ====================================================================== app list
@dataclass
class _Columns:
    icon_x: int
    check_limit: int
    name_x: int
    name_w: int
    bundle_x: int
    bundle_w: int
    status_x: int
    status_w: int
    version_x: int
    version_w: int
    app_x: int
    app_w: int
    data_x: int
    data_w: int
    total_x: int
    total_w: int
    content_w: int


# Sortable header columns (key -> header label)
SORT_COLUMNS = {"name": "APP NAME", "status": "STATUS", "app": "APP SIZE", "data": "DOCS & DATA*",
                "total": "TOTAL*"}


class AppList(tk.Frame, _Scaled):
    """Scrollable list of apps with checkboxes, hover, separators and a sortable header.

    Interaction (unchanged from earlier stages):
      * click the checkbox/icon to tick an app; double-click elsewhere on a row to tick it
      * click / Ctrl+click / Shift+click / arrow keys highlight rows; Space ticks highlighted rows
      * Ctrl+A ticks all visible apps; click a sortable header to change the sort order
      * hover over an app's name for a moment to see its details
    The list scrolls horizontally when the window is too narrow for every column.
    """

    def __init__(self, master: tk.Misc, *, icons: IconFactory, fonts: Fonts, scale: float,
                 is_checked: Callable[[str], bool], on_toggle: Callable[[list[str]], None],
                 on_select_all: Callable[[], None], on_sort: Callable[[str], None],
                 size_for: Callable[[AppInfo], object] = lambda app: "Not available",
                 details_for: Optional[Callable[[AppInfo], list[tuple[str, str]]]] = None) -> None:
        tk.Frame.__init__(self, master, bg=Colors.WHITE, bd=0, highlightthickness=0)
        self.scale = scale
        self.icons = icons
        self.fonts = fonts
        self._is_checked = is_checked
        self._on_toggle = on_toggle
        self._on_select_all = on_select_all
        self._on_sort = on_sort
        self._size_for = size_for
        self._details_for = details_for

        self.row_h = self.p(40)
        self.head_h = self.p(40)
        self.rows: list[AppInfo] = []
        self.sort_column = "name"
        self.sort_descending = False
        self.highlight: set[str] = set()
        self._items: dict[str, tuple[int, int, int, int, int]] = {}  # id -> (index, bg, bar, check, icon)
        self._anchor: Optional[int] = None
        self._cursor: Optional[int] = None
        self._hover: Optional[int] = None
        self._head_hover: Optional[str] = None
        self._job: Optional[str] = None
        self._fit_cache: dict[tuple, str] = {}
        self._cols: Optional[_Columns] = None
        self._card: Optional[DetailsCard] = None
        self._card_job: Optional[str] = None
        self._card_index: Optional[int] = None

        self.header = tk.Canvas(self, height=self.head_h, bg=Colors.SLATE_50, highlightthickness=0, bd=0)
        self.body = tk.Canvas(self, bg=Colors.WHITE, highlightthickness=0, bd=0, takefocus=1,
                              yscrollincrement=self.row_h, xscrollincrement=self.p(20))
        self.scroll = ttk.Scrollbar(self, orient="vertical", style="Slim.Vertical.TScrollbar",
                                    command=self.body.yview)
        self.hscroll = ttk.Scrollbar(self, orient="horizontal", style="Slim.Horizontal.TScrollbar",
                                     command=self.body.xview)
        self.body.configure(yscrollcommand=self.scroll.set, xscrollcommand=self._on_xscroll)
        self.header.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.body.grid(row=1, column=0, sticky="nsew")
        self.scroll.grid(row=1, column=1, sticky="ns", padx=(0, self.p(3)), pady=self.p(3))
        self._hscroll_shown = False
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.body.bind("<Configure>", lambda _e: self._schedule_redraw())
        self.header.bind("<Configure>", lambda _e: self._draw_header())
        self.header.bind("<Motion>", self._on_header_motion)
        self.header.bind("<Leave>", lambda _e: self._set_head_hover(None))
        self.header.bind("<Button-1>", self._on_header_click)
        b = self.body
        b.bind("<Button-1>", self._on_click)
        b.bind("<Double-Button-1>", self._on_double_click)
        b.bind("<Motion>", self._on_motion)
        b.bind("<Leave>", lambda _e: self._on_leave())
        b.bind("<Enter>", lambda _e: (b.bind_all("<MouseWheel>", self._on_wheel),
                                      b.bind_all("<Shift-MouseWheel>", self._on_shift_wheel)))
        b.bind("<space>", lambda _e: (self._toggle_highlighted(), "break")[1])
        b.bind("<Control-a>", lambda _e: (self._on_select_all(), "break")[1])
        for key, step in (("<Up>", -1), ("<Down>", 1)):
            b.bind(key, lambda _e, s=step: self._move_cursor(s, extend=False))
            b.bind(f"<Shift-{key[1:]}", lambda _e, s=step: self._move_cursor(s, extend=True))
        b.bind("<Home>", lambda _e: self._move_to(0))
        b.bind("<End>", lambda _e: self._move_to(len(self.rows) - 1))

    # ------------------------------------------------------------ public API
    def set_rows(self, apps: Sequence[AppInfo], sort_column: str, sort_descending: bool) -> None:
        self.rows = list(apps)
        self.sort_column = sort_column
        self.sort_descending = sort_descending
        ids = {a.bundle_id for a in self.rows}
        self.highlight &= ids
        self._anchor = self._cursor = None
        self._hover = None
        self._hide_card()
        self._redraw()
        self._draw_header()

    def selection(self) -> list[str]:
        return [a.bundle_id for a in self.rows if a.bundle_id in self.highlight]

    def refresh_checks(self, ids: Iterable[str]) -> None:
        for bid in ids:
            self._paint(bid)

    def refresh_icons(self, ids: Iterable[str]) -> None:
        """Show the current icon (real or placeholder) for these apps."""
        for bid in ids:
            item = self._items.get(bid)
            if item:
                self.body.itemconfigure(item[4], image=self.icons.app_icon(bid))

    def refresh_sizes(self) -> None:
        self._redraw()

    # ------------------------------------------------------------ layout & drawing
    def _layout(self, width: int) -> _Columns:
        p = self.p
        icon_x = p(16)
        name_x = icon_x + self.icons.row_image_width + p(16)
        status_w, version_w, app_w, data_w, total_w, right = p(92), p(92), p(92), p(108), p(88), p(16)
        fixed = status_w + version_w + app_w + data_w + total_w
        flex = max(p(300), width - name_x - right - fixed)
        name_w = int(flex * 0.5)
        bundle_x = name_x + name_w
        status_x = bundle_x + (flex - name_w)
        version_x = status_x + status_w
        app_x = version_x + version_w
        data_x = app_x + app_w
        total_x = data_x + data_w
        return _Columns(icon_x, name_x - p(8), name_x, name_w, bundle_x, flex - name_w,
                        status_x, status_w, version_x, version_w, app_x, app_w, data_x, data_w,
                        total_x, total_w, total_x + total_w + right)

    def _fit(self, text: str, font: tkfont.Font, width: int) -> str:
        key = (text, str(font), width)
        if key in self._fit_cache:
            return self._fit_cache[key]
        result = text
        if font.measure(text) > width:
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if font.measure(text[:mid] + "…") <= width:
                    lo = mid
                else:
                    hi = mid - 1
            result = text[:lo].rstrip() + "…"
        self._fit_cache[key] = result
        return result

    def _schedule_redraw(self) -> None:
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after_idle(self._redraw)

    def _size_cells(self, app: AppInfo) -> list[tuple[str, str, tkfont.Font]]:
        """(text, colour, font) for the App Size, Docs & Data and Total cells."""
        f = self.fonts
        value = self._size_for(app)
        if isinstance(value, AppSize):
            return [(format_bytes(value.app_bytes), Colors.SLATE_700, f.body),
                    (format_bytes(value.data_bytes), Colors.SLATE_700, f.body),
                    (format_bytes(value.total_bytes), Colors.SLATE_900, f.body_bold)]
        return [(str(value), Colors.SLATE_400, f.small)] * 3

    def _redraw(self) -> None:
        self._job = None
        c, f, p = self.body, self.fonts, self.p
        view_w = max(c.winfo_width(), 1)
        cols = self._cols = self._layout(view_w)
        width = max(view_w, cols.content_w)
        gap = p(14)
        c.delete("all")
        self._items.clear()
        rh = self.row_h
        for i, app in enumerate(self.rows):
            bid = app.bundle_id
            checked = self._is_checked(bid)
            y0, y1 = i * rh, (i + 1) * rh
            ym = y0 + rh / 2
            bg = c.create_rectangle(0, y0, width, y1, fill=self._row_bg(bid, i), outline="")
            bar = c.create_rectangle(0, y0, p(3), y1, fill=Colors.ORANGE, outline="",
                                     state="normal" if checked else "hidden")
            c.create_line(p(16), y1 - 1, width - p(16), y1 - 1, fill=Colors.SLATE_100)
            # Checkbox and icon sit exactly where the former combined image placed them.
            ic = self.icons
            check = c.create_image(cols.icon_x, ym - ic.tile_size / 2 + (ic.tile_size - ic.checkbox_size) // 2,
                                   anchor="nw", image=ic.checkbox_image(checked))
            icon = c.create_image(cols.icon_x + ic.checkbox_size + ic.gap, ym, anchor="w",
                                  image=ic.app_icon(bid))
            c.create_text(cols.name_x, ym, anchor="w", font=f.body_bold, fill=Colors.SLATE_900,
                          text=self._fit(app.name, f.body_bold, cols.name_w - gap))
            c.create_text(cols.bundle_x, ym, anchor="w", font=f.body, fill=Colors.SLATE_500,
                          text=self._fit(app.bundle_id, f.body, cols.bundle_w - gap))
            if app.offloaded:
                c.create_text(cols.status_x, ym, anchor="w", font=f.small_bold, fill=Colors.ORANGE,
                              text="Offloaded")
            else:
                c.create_text(cols.status_x, ym, anchor="w", font=f.small, fill=Colors.SLATE_500,
                              text="Installed")
            c.create_text(cols.version_x, ym, anchor="w", font=f.body, fill=Colors.SLATE_700,
                          text=self._fit(app.version or "—", f.body, cols.version_w - gap))
            for (text, color, font), x, w in zip(self._size_cells(app), (cols.app_x, cols.data_x, cols.total_x),
                                                 (cols.app_w, cols.data_w, cols.total_w)):
                c.create_text(x, ym, anchor="w", font=font, fill=color, text=self._fit(text, font, w - p(8)))
            self._items[bid] = (i, bg, bar, check, icon)
        c.configure(scrollregion=(0, 0, width, len(self.rows) * rh))
        self._update_hscroll(view_w < cols.content_w)
        self._draw_header()

    def _update_hscroll(self, needed: bool) -> None:
        if needed and not self._hscroll_shown:
            self.hscroll.grid(row=2, column=0, sticky="ew", padx=self.p(3), pady=(0, self.p(3)))
            self._hscroll_shown = True
        elif not needed and self._hscroll_shown:
            self.hscroll.grid_remove()
            self._hscroll_shown = False
            self.body.xview_moveto(0)

    def _on_xscroll(self, first: str, last: str) -> None:
        self.hscroll.set(first, last)
        self.header.xview_moveto(first)   # keep the column headings aligned with the rows

    def _draw_header(self) -> None:
        h, c, f, p = self.head_h, self.header, self.fonts, self.p
        cols = self._cols or self._layout(max(self.body.winfo_width(), 1))
        width = max(c.winfo_width(), cols.content_w + p(20))
        # Same horizontal extent as the body so xview fractions line up.
        body_w = max(self.body.winfo_width(), cols.content_w)
        c.configure(scrollregion=(0, 0, body_w, h))
        c.delete("all")
        c.create_line(0, h - 1, width, h - 1, fill=Colors.SLATE_200)
        y = h / 2
        columns = [("name", cols.name_x, None), (None, cols.bundle_x, "BUNDLE IDENTIFIER"),
                   ("status", cols.status_x, None), (None, cols.version_x, "VERSION"),
                   ("app", cols.app_x, None), ("data", cols.data_x, None), ("total", cols.total_x, None)]
        for key, x, plain in columns:
            text = SORT_COLUMNS[key] if key else plain
            active = key is not None and key == self.sort_column
            if key is not None and self._head_hover == key:
                color = Colors.ORANGE
            elif active:
                color = Colors.SLATE_700
            else:
                color = Colors.SLATE_500
            label = c.create_text(x, y, anchor="w", text=text, font=f.caption, fill=color)
            if active:
                ax = c.bbox(label)[2] + p(6)
                if f.has_icons:
                    arrow = Glyph.CHEVRON_DOWN if self.sort_descending else Glyph.CHEVRON_UP
                    c.create_text(ax, y + 1, anchor="w", text=arrow, font=f.icon_tiny, fill=Colors.ORANGE)
                else:
                    c.create_text(ax, y, anchor="w", text="▼" if self.sort_descending else "▲",
                                  font=f.caption, fill=Colors.ORANGE)

    def _row_bg(self, bid: str, index: int) -> str:
        highlighted = bid in self.highlight
        hovered = index == self._hover
        if self._is_checked(bid):
            if highlighted:
                return Colors.ORANGE_TINT_STRONG
            return Colors.ORANGE_TINT_HOVER if hovered else Colors.ORANGE_TINT
        if highlighted:
            return Colors.SLATE_100
        return Colors.SLATE_50 if hovered else Colors.WHITE

    def _paint(self, bid: str) -> None:
        item = self._items.get(bid)
        if not item:
            return
        index, bg, bar, check, _icon = item
        checked = self._is_checked(bid)
        self.body.itemconfigure(bg, fill=self._row_bg(bid, index))
        self.body.itemconfigure(bar, state="normal" if checked else "hidden")
        self.body.itemconfigure(check, image=self.icons.checkbox_image(checked))

    def _paint_index(self, index: Optional[int]) -> None:
        if index is not None and 0 <= index < len(self.rows):
            self._paint(self.rows[index].bundle_id)

    # ------------------------------------------------------------ details card (hover)
    def _on_motion(self, e: tk.Event) -> None:
        index = self._index_at(e.y)
        self._set_hover(index, e.x)
        x = self.body.canvasx(e.x)
        over_name = (index is not None and self._cols is not None
                     and self._cols.name_x <= x < self._cols.status_x)
        if not over_name:
            self._hide_card()
            return
        if index != self._card_index:
            self._hide_card()
            self._card_index = index
            self._card_job = self.after(650, lambda: self._show_card(index))

    def _on_leave(self) -> None:
        self._set_hover(None)
        self._hide_card()
        self.body.unbind_all("<MouseWheel>")
        self.body.unbind_all("<Shift-MouseWheel>")

    def _show_card(self, index: int) -> None:
        self._card_job = None
        if self._details_for is None or not 0 <= index < len(self.rows) or index != self._hover:
            return
        app = self.rows[index]
        px, py = self.winfo_pointerxy()
        self._card = DetailsCard(self, fonts=self.fonts, scale=self.scale, title=app.name,
                                 rows=self._details_for(app), x_root=px, y_root=py)

    def _hide_card(self) -> None:
        if self._card_job:
            self.after_cancel(self._card_job)
            self._card_job = None
        if self._card is not None:
            self._card.destroy()
            self._card = None
        self._card_index = None

    # ------------------------------------------------------------ interaction
    def _index_at(self, y: int) -> Optional[int]:
        index = int(self.body.canvasy(y) // self.row_h)
        return index if 0 <= index < len(self.rows) else None

    def _set_hover(self, index: Optional[int], x: Optional[int] = None) -> None:
        if x is not None and self._cols is not None:
            over_check = index is not None and self.body.canvasx(x) < self._cols.check_limit
            self.body.configure(cursor="hand2" if over_check else "")
        if index != self._hover:
            old, self._hover = self._hover, index
            self._paint_index(old)
            self._paint_index(index)

    def _on_wheel(self, e: tk.Event) -> None:
        self._hide_card()
        if self.body.yview() == (0.0, 1.0):
            return
        steps = -int(e.delta / 120 * 3) or (-1 if e.delta > 0 else 1)
        self.body.yview_scroll(steps, "units")
        local_y = e.y_root - self.body.winfo_rooty()
        self._set_hover(self._index_at(local_y))

    def _on_shift_wheel(self, e: tk.Event) -> None:
        self._hide_card()
        if self._hscroll_shown:
            self.body.xview_scroll(-int(e.delta / 120 * 3) or (-1 if e.delta > 0 else 1), "units")

    def _on_click(self, e: tk.Event) -> Optional[str]:
        self._hide_card()
        self.body.focus_set()
        index = self._index_at(e.y)
        if index is None or self._cols is None:
            return None
        bid = self.rows[index].bundle_id
        if self.body.canvasx(e.x) < self._cols.check_limit:
            self._on_toggle([bid])
            return "break"
        before = set(self.highlight)
        if e.state & 0x0004:           # Ctrl
            self.highlight ^= {bid}
            self._anchor = index
        elif e.state & 0x0001 and self._anchor is not None:   # Shift
            lo, hi = sorted((self._anchor, index))
            self.highlight = {a.bundle_id for a in self.rows[lo:hi + 1]}
        else:
            self.highlight = {bid}
            self._anchor = index
        self._cursor = index
        for changed in before ^ self.highlight | {bid}:
            self._paint(changed)
        return "break"

    def _on_double_click(self, e: tk.Event) -> str:
        index = self._index_at(e.y)
        if index is not None and self._cols is not None and self.body.canvasx(e.x) >= self._cols.check_limit:
            self._on_toggle([self.rows[index].bundle_id])
        return "break"

    def _toggle_highlighted(self) -> None:
        ids = self.selection()
        if ids:
            self._on_toggle(ids)

    def _move_cursor(self, step: int, extend: bool) -> str:
        if not self.rows:
            return "break"
        start = self._cursor if self._cursor is not None else (-1 if step > 0 else len(self.rows))
        self._move_to(max(0, min(len(self.rows) - 1, start + step)), extend)
        return "break"

    def _move_to(self, index: int, extend: bool = False) -> str:
        if not self.rows:
            return "break"
        before = set(self.highlight)
        if extend and self._anchor is not None:
            lo, hi = sorted((self._anchor, index))
            self.highlight = {a.bundle_id for a in self.rows[lo:hi + 1]}
        else:
            self.highlight = {self.rows[index].bundle_id}
            self._anchor = index
        self._cursor = index
        for changed in before ^ self.highlight:
            self._paint(changed)
        self._ensure_visible(index)
        return "break"

    def _ensure_visible(self, index: int) -> None:
        total = len(self.rows) * self.row_h
        if total <= 0:
            return
        top = self.body.canvasy(0)
        view_h = self.body.winfo_height()
        y0, y1 = index * self.row_h, (index + 1) * self.row_h
        if y0 < top:
            self.body.yview_moveto(y0 / total)
        elif y1 > top + view_h:
            self.body.yview_moveto((y1 - view_h) / total)

    def _header_column_at(self, x: int) -> Optional[str]:
        cols = self._cols
        if cols is None:
            return None
        x = self.header.canvasx(x)
        spans = {"name": (cols.name_x - self.p(8), cols.bundle_x),
                 "status": (cols.status_x - self.p(8), cols.version_x),
                 "app": (cols.app_x - self.p(8), cols.data_x),
                 "data": (cols.data_x - self.p(8), cols.total_x),
                 "total": (cols.total_x - self.p(8), cols.total_x + cols.total_w)}
        for key, (a, b) in spans.items():
            if a <= x < b:
                return key
        return None

    def _set_head_hover(self, key: Optional[str]) -> None:
        if key != self._head_hover:
            self._head_hover = key
            self.header.configure(cursor="hand2" if key else "")
            self._draw_header()

    def _on_header_motion(self, e: tk.Event) -> None:
        self._set_head_hover(self._header_column_at(e.x))

    def _on_header_click(self, e: tk.Event) -> None:
        key = self._header_column_at(e.x)
        if key:
            self._on_sort(key)
