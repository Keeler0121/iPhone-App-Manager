"""Main application window."""
from __future__ import annotations

import ctypes
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Callable, Iterable, Optional, Union

from .. import config
from ..app_icons import IconFetchResult, fetch_icons
from ..app_inventory import InventoryResult, fetch_inventory
from ..connection import ConnectionType, DeviceTarget
from ..device import DeviceError, DeviceService, ErrorKind, removal_block_reason
from ..models import AppInfo, AppSize, DeviceInfo
from ..uninstall import Outcome, UninstallResult, count, run_uninstall_batch, verify_results
from .dialogs import ConfirmUninstallDialog, DevicePickerDialog, ReviewDialog, UninstallProgressDialog
from .icons import IconFactory
from .theme import Colors, Glyph, apply_theme
from .widgets import (AppList, DetailsCard, IconBadge, Pill, RoundedButton, SearchBox, SegmentedControl,
                      format_bytes)

_STATUS_FOR_ERROR = {
    ErrorKind.NO_DEVICE: ("disconnected", "Not connected"),
    ErrorKind.NOT_TRUSTED: ("warning", "Not trusted"),
    ErrorKind.LOCKED: ("warning", "Locked"),
    ErrorKind.TOOL_MISSING: ("error", "Tools missing"),
    ErrorKind.TIMEOUT: ("error", "Not responding"),
    ErrorKind.PARSE: ("error", "Read error"),
    ErrorKind.UNKNOWN: ("error", "Error"),
    ErrorKind.SERVICE_UNAVAILABLE: ("error", "Service unavailable"),
    ErrorKind.WIFI_SYNC_OFF: ("warning", "Wi-Fi sync off"),
    ErrorKind.MULTIPLE_DEVICES: ("warning", "Choose an iPhone"),
    ErrorKind.INSTALL_SERVICE: ("error", "Service unavailable"),
}

# Connection-status pill appearance (on the slate header).
_STATUS_STYLE = {
    "connected": dict(fill=Colors.SLATE_700, border=Colors.SLATE_600, fg=Colors.WHITE,
                      dot=Colors.ORANGE, dot_style="halo"),
    "loading": dict(fill=Colors.SLATE_700, border=Colors.SLATE_600, fg=Colors.SLATE_200,
                    dot=Colors.ORANGE_SOFT, dot_style="solid", pulse=True),
    "warning": dict(fill=Colors.SLATE_700, border=Colors.ORANGE, fg=Colors.WHITE,
                    dot=Colors.ORANGE, dot_style="ring"),
    "disconnected": dict(fill=Colors.SLATE_700, border=Colors.SLATE_600, fg=Colors.SLATE_300,
                         dot=Colors.SLATE_400, dot_style="solid"),
    "error": dict(fill=Colors.ORANGE, border=Colors.ORANGE, fg=Colors.WHITE,
                  dot=Colors.WHITE, dot_style="solid"),
}

_ERROR_GLYPH = {
    ErrorKind.NO_DEVICE: (Glyph.PHONE, False),
    ErrorKind.NOT_TRUSTED: (Glyph.LOCK, True),
    ErrorKind.LOCKED: (Glyph.LOCK, True),
    ErrorKind.MULTIPLE_DEVICES: (Glyph.PHONE, False),
}

# Sort modes: key -> (label, column, descending). Apps without a size always sort last.
# The status modes (reached by clicking the STATUS header) only reorder the two groups: Offloaded then Installed
# ("ascending") or Installed then Offloaded ("descending"). Names stay A → Z inside each group in both directions.
SORT_MODES = {
    "name_asc": ("Name A → Z", "name", False),
    "name_desc": ("Name Z → A", "name", True),
    "status_asc": ("Offloaded first", "status", False),
    "status_desc": ("Installed first", "status", True),
    "total_desc": ("Largest total", "total", True),
    "total_asc": ("Smallest total", "total", False),
    "app_desc": ("Largest app size", "app", True),
    "app_asc": ("Smallest app size", "app", False),
    "data_desc": ("Largest docs & data", "data", True),
    "data_asc": ("Smallest docs & data", "data", False),
}
SORT_MENU = ["name_asc", "name_desc", None, "total_desc", "total_asc", "app_desc", "data_desc"]

_DEVICE_FAMILY = {1: "iPhone", 2: "iPad", 3: "Apple TV", 4: "Apple Watch", 6: "Mac", 7: "Apple Vision"}

DATA_FOOTNOTE = ("* Docs & Data is the app's own data as reported by iOS; iPhone Settings can show more "
                 "because it also counts data shared with the app's extensions")


def _usable_screen_area(root: tk.Misc) -> tuple[int, int, int, int]:
    """(left, top, width, height) of the screen excluding the Windows taskbar."""
    if sys.platform == "win32":
        try:
            class _Rect(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            rect = _Rect()
            SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except Exception:
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def _window_frame_size(root: tk.Misc) -> tuple[int, int]:
    """Extra width/height Windows adds around the window contents (borders + title bar)."""
    if sys.platform == "win32":
        try:
            metric = ctypes.windll.user32.GetSystemMetrics
            SM_CXFRAME, SM_CYFRAME, SM_CYCAPTION, SM_CXPADDEDBORDER = 32, 33, 4, 92
            padded = metric(SM_CXPADDEDBORDER)
            return (2 * (metric(SM_CXFRAME) + padded),
                    metric(SM_CYCAPTION) + 2 * (metric(SM_CYFRAME) + padded))
        except Exception:
            pass
    scale = root.winfo_fpixels("1i") / 96.0
    return int(16 * scale), int(40 * scale)


def format_gb(n: int, whole: bool = False) -> str:
    """Decimal GB as iOS uses (1 GB = 10^9 bytes): '118.1 GB'; whole=True for capacity ('128 GB')."""
    return f"{n / 1e9:.0f} GB" if whole else f"{n / 1e9:.1f} GB"


class MainWindow:
    def __init__(self, root: tk.Tk, service: DeviceService) -> None:
        self.root = root
        self.service = service
        self.scale = root.winfo_fpixels("1i") / 96.0
        self.fonts = apply_theme(root, self.scale)
        self.icons = IconFactory(root, self.scale)

        # State
        self.apps: list[AppInfo] = []           # installed + offloaded
        self.installed_apps: list[AppInfo] = []
        self.offloaded_apps: list[AppInfo] = []
        self.checked: set[str] = set()          # bundle IDs ticked by the user
        self.visible_ids: list[str] = []        # bundle IDs currently shown (after search)
        self.sort_mode = "name_asc"
        self.device: Optional[DeviceInfo] = None
        self.target: Optional[DeviceTarget] = None      # the iPhone + connection the data on screen came from
        self._loaded_udid: Optional[str] = None
        self.picker_dialog: Optional[DevicePickerDialog] = None
        self.error: Optional[DeviceError] = None
        self.loading = False
        self._events: "queue.Queue[tuple]" = queue.Queue()
        self._polling = False
        self.search_var = tk.StringVar()

        # Real icon retrieval (background helper process)
        self._icon_generation = 0                       # ignores results from superseded fetches
        self._icon_cancel: Optional[threading.Event] = None
        self.icon_fetching = False
        self.icon_received = 0
        self.icon_requested = 0
        self.icon_note = ""                             # footer text about icon status
        self.last_icon_result: Optional[IconFetchResult] = None
        self._icon_refetch_pending = False

        # Inventory (offloaded apps + per-app storage) - background helper process
        self._inv_generation = 0
        self._inv_cancel: Optional[threading.Event] = None
        self.inventory_running = False
        self.offloaded_state = "idle"                  # idle / loading / ready / error
        self.sizes_state = "idle"                      # idle / loading / ready / error
        self.sizes: dict[str, AppSize] = {}
        self.inventory_note = ""
        self.last_inventory_result: Optional[InventoryResult] = None
        self._known_offloaded: set[str] = set()
        self.home_state = "idle"                       # Home Screen read (for verifying removals)
        self.home_screen_placeholders: set[str] = set()

        # Uninstall (Stage 3). Only ever started from the confirmation dialog.
        self.uninstalling = False
        self._after_refresh: Optional[Callable[[bool], None]] = None
        self._preserve_icons = False
        self._uninstall_results: list[UninstallResult] = []
        self._awaiting_verification = False
        self.last_uninstall_results: list[UninstallResult] = []
        self.review_dialog: Optional[ReviewDialog] = None
        self.confirm_dialog: Optional[ConfirmUninstallDialog] = None
        self.progress_dialog: Optional[UninstallProgressDialog] = None
        self._fit_job: Optional[str] = None
        self._footnote_job: Optional[str] = None
        self._storage_card: Optional[DetailsCard] = None

        self._configure_root()
        self._build_header()
        self._build_toolbar()
        self._build_footer()
        self._build_table()
        self._bind_keys()
        self.search_var.trace_add("write", lambda *_: self._render())
        self._render()
        root.after(150, self.refresh)

    # ------------------------------------------------------------------ helpers
    def px(self, n: float) -> int:
        return int(round(n * self.scale))

    @property
    def sort_descending(self) -> bool:
        return SORT_MODES[self.sort_mode][2]

    # ------------------------------------------------------------------ layout
    def _configure_root(self) -> None:
        self.root.title(config.APP_NAME)
        left, top, avail_w, avail_h = _usable_screen_area(self.root)
        frame_w, frame_h = _window_frame_size(self.root)
        # Preferred size, shrunk if needed so the whole window (incl. title bar) fits above the
        # taskbar. Keep a small margin: a window exactly filling the work area is shown maximised.
        margin = self.px(24)
        w = min(self.px(1080), avail_w - frame_w - margin)
        h = min(self.px(700), avail_h - frame_h - margin)
        x = left + max(0, (avail_w - (w + frame_w)) // 2)
        y = top + max(0, (avail_h - (h + frame_h)) // 3)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(min(self.px(820), w), min(self.px(480), h))
        self.root.iconphoto(True, self.icons.brand_icon(64))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        if self.uninstalling:
            from tkinter import messagebox
            if not messagebox.askyesno(
                    "Uninstall in progress",
                    "Apps are still being removed. The app currently being removed may still finish, "
                    "but the remaining apps will not be removed.\n\nClose anyway?",
                    icon="warning", default="no", parent=self.progress_dialog or self.root):
                return
        self._cancel_icon_fetch()       # stops the helper processes
        self._cancel_inventory()
        if self.picker_dialog is not None:
            self.picker_dialog.close()
            self.picker_dialog = None
        for job in (self._fit_job, self._footnote_job):
            if job is not None:
                self.root.after_cancel(job)
        self._fit_job = self._footnote_job = None
        self.root.destroy()

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=Colors.SLATE_800)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=Colors.SLATE_800)
        inner.pack(fill="x", padx=self.px(24), pady=(self.px(16), self.px(15)))

        left = tk.Frame(inner, bg=Colors.SLATE_800)
        left.pack(side="left")
        tk.Label(left, image=self.icons.brand_icon(self.px(40)), bg=Colors.SLATE_800,
                 bd=0).pack(side="left", padx=(0, self.px(14)))
        titles = tk.Frame(left, bg=Colors.SLATE_800)
        titles.pack(side="left")
        tk.Label(titles, text=config.APP_NAME, font=self.fonts.title, fg=Colors.WHITE,
                 bg=Colors.SLATE_800, bd=0).pack(anchor="w")
        tk.Label(titles, text="View and remove the apps installed on your iPhone",
                 font=self.fonts.small, fg=Colors.SLATE_400, bg=Colors.SLATE_800,
                 bd=0).pack(anchor="w", pady=(self.px(1), 0))

        right = tk.Frame(inner, bg=Colors.SLATE_800)
        right.pack(side="right")
        status_row = tk.Frame(right, bg=Colors.SLATE_800)
        status_row.pack(anchor="e")
        # USB (the default) or Wi-Fi. Locked while the app is loading or removing apps.
        self.connection_selector = SegmentedControl(
            status_row, options=[(ConnectionType.USB.label, ConnectionType.USB),
                                 (ConnectionType.WIFI.label, ConnectionType.WIFI)],
            value=self.service.connection, command=self._on_connection_selected, fonts=self.fonts,
            scale=self.scale, bg=Colors.SLATE_800, height=30)
        self.connection_selector.pack(side="left", padx=(0, self.px(10)))
        self.status_pill = Pill(status_row, fonts=self.fonts, scale=self.scale, bg=Colors.SLATE_800,
                                height=30, padx=14)
        self.status_pill.pack(side="left")
        self.status_detail = tk.Label(right, font=self.fonts.small, fg=Colors.SLATE_300,
                                      bg=Colors.SLATE_800, bd=0)
        self.status_detail.pack(anchor="e", pady=(self.px(6), 0))

        # Storage summary: "118.1 GB used · 9.9 GB free now · 128 GB" with a slim bar.
        storage = tk.Frame(right, bg=Colors.SLATE_800)
        storage.pack(anchor="e", pady=(self.px(6), 0))
        self.storage_label = tk.Label(storage, font=self.fonts.small, fg=Colors.SLATE_300,
                                      bg=Colors.SLATE_800, bd=0)
        self.storage_label.pack(side="right")
        self.storage_bar = tk.Canvas(storage, width=self.px(120), height=self.px(6), bg=Colors.SLATE_800,
                                     highlightthickness=0, bd=0)
        self.storage_bar.pack(side="right", padx=(0, self.px(10)))
        for widget in (storage, self.storage_label, self.storage_bar):
            widget.bind("<Enter>", lambda _e: self._show_storage_card(), add="+")
            widget.bind("<Leave>", lambda _e: self._hide_storage_card(), add="+")
        self._draw_storage()

        # Thin loading strip under the header (fixed height so the layout never jumps).
        strip = tk.Frame(self.root, height=self.px(3), bg=Colors.SLATE_800, bd=0)
        strip.pack(fill="x")
        strip.pack_propagate(False)
        self.progress = ttk.Progressbar(strip, mode="indeterminate", style="Accent.Horizontal.TProgressbar")

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self.root, bg=Colors.WHITE)
        bar.pack(fill="x", padx=self.px(21), pady=(self.px(17), self.px(11)))
        self._toolbar = bar
        common = dict(fonts=self.fonts, scale=self.scale, bg=Colors.WHITE)

        # The search box gives up width (down to min_width) so every toolbar control fits.
        self.search = SearchBox(bar, variable=self.search_var, width=340, min_width=180,
                                placeholder="Search by app name or bundle ID",
                                short_placeholder="Search apps", **common)
        self.search.pack(side="left")
        self.search_entry = self.search.entry
        self.sort_button = RoundedButton(bar, text=SORT_MODES[self.sort_mode][0], command=self.open_sort_menu,
                                         glyph=Glyph.SORT, min_width=136, **common)
        self.sort_button.pack(side="left", padx=(self.px(10), 0))
        self._sort_var = tk.StringVar(value=self.sort_mode)
        self.sort_menu = tk.Menu(self.root, tearoff=0, bg=Colors.WHITE, fg=Colors.SLATE_800, bd=0,
                                 activebackground=Colors.ORANGE_TINT_STRONG, activeforeground=Colors.SLATE_900,
                                 selectcolor=Colors.ORANGE, font=self.fonts.body, relief="flat")
        for mode in SORT_MENU:
            if mode is None:
                self.sort_menu.add_separator()
            else:
                self.sort_menu.add_radiobutton(label=SORT_MODES[mode][0], value=mode, variable=self._sort_var,
                                               command=lambda m=mode: self.set_sort(m))

        # Right-hand actions (packed right-to-left)
        self.refresh_button = RoundedButton(bar, text="Refresh", command=self.refresh, variant="primary",
                                            glyph=Glyph.REFRESH, min_width=124, **common)
        self.refresh_button.pack(side="right", padx=(0, self.px(3)))
        tk.Frame(bar, bg=Colors.SLATE_200, width=1, height=self.px(24)).pack(
            side="right", padx=self.px(12))
        self.uninstall_button = RoundedButton(bar, text="Uninstall Selected", variant="primary",
                                              command=self.open_uninstall_confirmation,
                                              glyph=Glyph.DELETE, **common)
        self.uninstall_button.set_enabled(False)
        self.uninstall_button.pack(side="right")
        self.deselect_button = RoundedButton(bar, text="Deselect All", command=self.deselect_all,
                                             glyph=Glyph.CLEAR_SELECTION, **common)
        self.deselect_button.pack(side="right", padx=(0, self.px(10)))
        self.select_button = RoundedButton(bar, text="Select All", command=self.select_all,
                                           glyph=Glyph.SELECT_ALL, **common)
        self.select_button.pack(side="right", padx=(0, self.px(8)))
        # Clicking the count opens a review of every selected app.
        self.count_pill = Pill(bar, height=30, padx=13, **common)
        self.count_pill.pack(side="right", padx=(0, self.px(14)))
        bar.bind("<Configure>", lambda _e: self._schedule_fit_search())

    def _schedule_fit_search(self) -> None:
        if self._fit_job is None:
            self._fit_job = self.root.after_idle(self._fit_search)

    def _fit_search(self) -> None:
        """Give the search box whatever width the other toolbar controls leave free."""
        self._fit_job = None
        bar = self._toolbar
        available = bar.winfo_width()
        if available <= 1:
            return
        # Buttons that may shrink to icon-only, in the order they give up their labels.
        compactable = [self.select_button, self.deselect_button, self.sort_button]
        widths: dict = {}
        used_fixed = 0
        for child in bar.pack_slaves():
            if child is self.search:
                continue
            padx = child.pack_info().get("padx", 0)
            parts = padx if isinstance(padx, (tuple, list)) else str(padx).split()
            pad = sum(int(float(v)) for v in parts) if len(parts) > 1 else 2 * int(float(parts[0] if parts else 0))
            if child in compactable:
                widths[child] = pad
            else:
                used_fixed += child.winfo_reqwidth() + pad
        spare = self.px(12)
        compact = {b: False for b in compactable}

        def needed() -> int:
            return used_fixed + sum(pad + b.natural_width(compact[b]) for b, pad in widths.items()) \
                + self.search.min_width + spare

        for button in compactable:
            if needed() <= available:
                break
            compact[button] = True
        for button, value in compact.items():
            button.set_compact(value)
        used = used_fixed + sum(pad + b.natural_width(compact[b]) for b, pad in widths.items())
        self.search.set_width(available - used - spare)

    def _build_footer(self) -> None:
        # Packed before the list (side=bottom) so it stays visible at any window height.
        foot = tk.Frame(self.root, bg=Colors.SLATE_50)
        foot.pack(side="bottom", fill="x")
        tk.Frame(foot, bg=Colors.SLATE_200, height=1).pack(fill="x", side="top")
        inner = tk.Frame(foot, bg=Colors.SLATE_50)
        inner.pack(fill="x", padx=self.px(24), pady=self.px(9))
        self.summary_label = tk.Label(inner, font=self.fonts.small, fg=Colors.SLATE_500,
                                      bg=Colors.SLATE_50, bd=0)
        self.summary_label.pack(side="left")
        self.updated_label = tk.Label(inner, font=self.fonts.small, fg=Colors.SLATE_500,
                                      bg=Colors.SLATE_50, bd=0)
        self.updated_label.pack(side="right")
        # Explains the asterisk on the Docs & Data / Total columns.
        self.footnote_label = tk.Label(inner, text=DATA_FOOTNOTE, font=self.fonts.small, fg=Colors.SLATE_400,
                                       bg=Colors.SLATE_50, bd=0, anchor="e")
        self.footnote_label.pack(side="right", padx=(self.px(16), self.px(16)), fill="x", expand=True)
        inner.bind("<Configure>", lambda _e: self._fit_footnote())

    def _fit_footnote(self) -> None:
        """Shorten the footnote when the footer is narrow (never hide that values may differ)."""
        self._footnote_job = None
        inner = self.footnote_label.master
        free = inner.winfo_width() - self.summary_label.winfo_reqwidth() - self.updated_label.winfo_reqwidth() \
            - self.px(48)
        short = "* Docs & Data may be lower than iPhone Settings"
        text = DATA_FOOTNOTE if self.fonts.small.measure(DATA_FOOTNOTE) <= free else short
        if self.footnote_label.cget("text") != text:
            self.footnote_label.configure(text=text)

    def _build_table(self) -> None:
        card = tk.Frame(self.root, bg=Colors.WHITE, highlightthickness=1,
                        highlightbackground=Colors.SLATE_200, highlightcolor=Colors.SLATE_200, bd=0)
        card.pack(fill="both", expand=True, padx=self.px(24), pady=(0, self.px(16)))

        self.app_list = AppList(card, icons=self.icons, fonts=self.fonts, scale=self.scale,
                                is_checked=lambda bid: bid in self.checked, on_toggle=self._toggle,
                                on_select_all=self.select_all, on_sort=self._on_header_sort,
                                size_for=self.size_for, details_for=self.details_for)
        self.app_list.pack(fill="both", expand=True)

        # Overlay used for loading / empty / error states.
        self.overlay = tk.Frame(card, bg=Colors.WHITE)
        inner = tk.Frame(self.overlay, bg=Colors.WHITE)
        inner.place(relx=0.5, rely=0.42, anchor="center")
        wrap = self.px(520)
        self.overlay_badge = IconBadge(inner, fonts=self.fonts, scale=self.scale, bg=Colors.WHITE)
        self.overlay_badge.pack(pady=(0, self.px(16)))
        self.overlay_title = tk.Label(inner, bg=Colors.WHITE, fg=Colors.SLATE_800, font=self.fonts.heading)
        self.overlay_title.pack()
        self.overlay_message = tk.Label(inner, bg=Colors.WHITE, fg=Colors.SLATE_500, font=self.fonts.body,
                                        wraplength=wrap, justify="center")
        self.overlay_message.pack(pady=(self.px(8), 0))
        self.overlay_details = tk.Label(inner, bg=Colors.WHITE, fg=Colors.SLATE_400,
                                        font=self.fonts.small, wraplength=wrap, justify="center")
        self.overlay_button = RoundedButton(inner, text="Try again", command=None, variant="primary",
                                            fonts=self.fonts, scale=self.scale, min_width=140)

    def _bind_keys(self) -> None:
        self.root.bind("<F5>", lambda _e: self.refresh())
        self.root.bind("<Control-f>", lambda _e: (self.search_entry.focus_set(),
                                                  self.search_entry.select_range(0, "end")))
        self.search_entry.bind("<Escape>", lambda _e: self.search_var.set(""))

    # ------------------------------------------------------------------ status, storage & overlay
    def _set_status(self, state: str, label: str, detail: str = "") -> None:
        self.status_pill.set(label, **_STATUS_STYLE[state])
        self.status_detail.configure(text=detail)

    def _draw_storage(self) -> None:
        """Header storage summary. Shows 'unavailable' rather than a doubtful figure."""
        storage = self.device.storage if self.device else None
        c = self.storage_bar
        c.delete("all")
        w, h = int(c.cget("width")), int(c.cget("height"))
        if storage is None:
            text = "Storage information unavailable" if self.device else ""
            self.storage_label.configure(text=text, fg=Colors.SLATE_400)
            c.pack_forget()
            return
        if not c.winfo_ismapped():
            c.pack(side="right", padx=(0, self.px(10)))
        frac = max(0.0, min(1.0, storage.used / storage.capacity))
        c.create_rectangle(0, 0, w, h, fill=Colors.SLATE_600, outline="")
        c.create_rectangle(0, 0, max(2, int(w * frac)), h, fill=Colors.ORANGE, outline="")
        self.storage_label.configure(
            fg=Colors.SLATE_300,
            text=f"{format_gb(storage.used)} used  ·  {format_gb(storage.free_now)} free now  "
                 f"·  {format_gb(storage.capacity, whole=True)}")

    def _show_storage_card(self) -> None:
        self._hide_storage_card()
        storage = self.device.storage if self.device else None
        if storage is None:
            rows = [("Status", "Not available"),
                    ("Why", "The iPhone did not report consistent storage figures.")]
        else:
            rows = [("Capacity", format_gb(storage.capacity, whole=True)),
                    ("Used", f"{format_gb(storage.used)} (capacity minus free space now)"),
                    ("Free now", format_gb(storage.free_now)),
                    ("Note", "iPhone Settings may show more space available, because it also counts "
                             "space iOS can reclaim by clearing caches. That figure is not available "
                             "to this app, so the guaranteed free space is shown here.")]
        x, y = self.root.winfo_pointerxy()
        self._storage_card = DetailsCard(self.root, fonts=self.fonts, scale=self.scale, title="iPhone storage",
                                         rows=rows, x_root=x - self.px(320), y_root=y)

    def _hide_storage_card(self) -> None:
        if self._storage_card is not None:
            self._storage_card.destroy()
            self._storage_card = None

    def _show_overlay(self, title: str, message: str = "", details: str = "",
                      action: Optional[tuple[str, Callable[[], None]]] = None,
                      glyph: str = Glyph.PHONE, accent: bool = False) -> None:
        self.overlay_badge.set(glyph, accent)
        self.overlay_title.configure(text=title)
        self.overlay_message.configure(text=message)
        self.overlay_details.configure(text=details[:600])
        self.overlay_details.pack_forget()
        self.overlay_button.pack_forget()
        if details:
            self.overlay_details.pack(pady=(self.px(10), 0))
        if action:
            label, command = action
            self.overlay_button.set_text(label)
            self.overlay_button.set_command(command)
            self.overlay_button.pack(pady=(self.px(20), 0))
        self.overlay.place(x=0, y=0, relwidth=1, relheight=1)
        self.overlay.lift()

    def _hide_overlay(self) -> None:
        self.overlay.place_forget()

    # ------------------------------------------------------------------ loading
    def refresh(self) -> None:
        """Reload device info and the app list in a background thread (never uninstalls anything)."""
        if self.loading or self.uninstalling:
            return
        self._begin_refresh()

    def _begin_refresh(self, preserve_icons: bool = False,
                       after: Optional[Callable[[bool], None]] = None) -> None:
        """Start a reload. ``after(ok)`` runs once the reload succeeds or fails."""
        self.loading = True
        self._after_refresh = after
        self._preserve_icons = preserve_icons
        self._cancel_icon_fetch()
        self._cancel_inventory()
        if not preserve_icons:
            # Icons are retrieved again after the list reloads; show placeholders meanwhile.
            self.icons.clear_real_icons()
        self.icon_note = ""
        self._set_status("loading", "Connecting…",
                         "Looking for your iPhone" if self.service.connection is ConnectionType.USB
                         else "Looking for your iPhone over Wi-Fi")
        self._sync_connection_controls()
        self.refresh_button.set_enabled(False)
        self.refresh_button.set_text("Loading…")
        self.progress.place(x=0, y=0, relwidth=1, relheight=1)
        self.progress.start(12)
        self._render()
        threading.Thread(target=self._load_worker, name="device-loader", daemon=True).start()
        self._ensure_polling()

    def _ensure_polling(self) -> None:
        if not self._polling:
            self._polling = True
            self.root.after(80, self._poll_events)

    def _load_worker(self) -> None:
        """Runs off the UI thread. Communicates only through the queue."""
        try:
            snapshot = self.service.load_snapshot(progress=lambda msg: self._events.put(("progress", msg)))
            self._events.put(("done", snapshot))
        except DeviceError as exc:
            self._events.put(("error", exc))
        except Exception as exc:  # never let the worker die silently
            self._events.put(("error", DeviceError(ErrorKind.UNKNOWN, f"{type(exc).__name__}: {exc}")))

    def _poll_events(self) -> None:
        """Handle worker-thread messages on the UI thread (the only place Tk is touched)."""
        new_icons: list[str] = []
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "progress":
                self._set_status("loading", "Connecting…", str(event[1]))
            elif kind == "done":
                device, apps = event[1]
                self._on_loaded(device, apps)
            elif kind == "error":
                self._on_error(event[1])
            elif kind == "icon" and event[1] == self._icon_generation:
                _kind, _gen, bundle_id, png = event
                if self.icons.set_real_icon(bundle_id, png):
                    new_icons.append(bundle_id)
                    self.icon_received += 1
            elif kind == "icons_done" and event[1] == self._icon_generation:
                self._on_icons_done(event[2])
            elif kind == "inv_offloaded" and event[1] == self._inv_generation:
                self._on_offloaded(event[2])
            elif kind == "inv_home" and event[1] == self._inv_generation:
                self._on_home_screen(event[2])
            elif kind == "inv_sizes" and event[1] == self._inv_generation:
                self._on_sizes(event[2])
            elif kind == "inv_done" and event[1] == self._inv_generation:
                self._on_inventory_done(event[2])
            elif kind == "uninstall_progress" and self.progress_dialog is not None:
                _kind, stage, index, result = event
                if stage == "start":
                    self.progress_dialog.mark_started(index)
                else:
                    self.progress_dialog.mark_done(index, result)
            elif kind == "uninstall_done":
                self._on_uninstall_finished(event[1])
        if new_icons:
            self.app_list.refresh_icons(new_icons)
            if self.icon_fetching:
                self.icon_note = f"Loading icons {self.icon_received} of {self.icon_requested}"
            self._update_counts()
        if self.loading or self.icon_fetching or self.uninstalling or self.inventory_running:
            self.root.after(80, self._poll_events)
        else:
            self._polling = False

    # ------------------------------------------------------------------ real icons
    def _start_icon_fetch(self, only_missing: bool = False) -> None:
        self._cancel_icon_fetch()
        self._icon_refetch_pending = False
        if not self.apps:
            return
        # Fetch in on-screen order so the visible rows fill in first.
        shown = self._filtered_sorted_apps()
        shown_ids = {a.bundle_id for a in shown}
        order = [a.bundle_id for a in shown] + [a.bundle_id for a in self.apps if a.bundle_id not in shown_ids]
        if only_missing:
            order = [bid for bid in order if not self.icons.has_real_icon(bid)]
            if not order:
                self.icon_note = ""
                self._update_counts()
                return
        self._icon_generation += 1
        cancel = threading.Event()
        self._icon_cancel = cancel
        self.icon_fetching = True
        self.icon_received = 0
        self.icon_requested = len(order)
        self.icon_note = f"Loading icons 0 of {len(order)}"
        threading.Thread(target=self._icon_worker,
                         args=(self._icon_generation, order, cancel, self.service.target),
                         name="icon-fetch", daemon=True).start()
        self._update_counts()
        self._ensure_polling()

    def _icon_worker(self, generation: int, bundle_ids: list[str], cancel: threading.Event,
                     target: Optional[DeviceTarget] = None) -> None:
        """Runs off the UI thread; the helper process does the device work (on ``target``)."""
        try:
            result = fetch_icons(bundle_ids, self.icons.tile_size,
                                 on_icon=lambda bid, png: self._events.put(("icon", generation, bid, png)),
                                 cancel=cancel, target=target)
        except Exception as exc:  # never let the worker die silently
            result = IconFetchResult(requested=len(bundle_ids), error=f"{type(exc).__name__}: {exc}")
        self._events.put(("icons_done", generation, result))

    def _cancel_icon_fetch(self) -> None:
        if self._icon_cancel is not None:
            self._icon_cancel.set()
            self._icon_cancel = None
        self._icon_generation += 1
        self.icon_fetching = False

    def _on_icons_done(self, result: IconFetchResult) -> None:
        self.icon_fetching = False
        self._icon_cancel = None
        self.last_icon_result = result
        if self._icon_refetch_pending and not self.uninstalling:
            self._start_icon_fetch(only_missing=True)    # icons for offloaded apps found meanwhile
            return
        missing = len(self.apps) - sum(1 for a in self.apps if self.icons.has_real_icon(a.bundle_id))
        if result.error and self.icon_received == 0:
            self.icon_note = f"App icons unavailable ({result.error})"
        elif result.error:
            self.icon_note = f"{missing} icon{'s' if missing != 1 else ''} unavailable ({result.error})"
        elif missing:
            self.icon_note = f"{missing} icon{'s' if missing != 1 else ''} unavailable"
        else:
            self.icon_note = ""
        self._update_counts()

    # ------------------------------------------------------------------ inventory (offloaded + sizes)
    def _start_inventory(self) -> None:
        self._cancel_inventory()
        self._inv_generation += 1
        cancel = threading.Event()
        self._inv_cancel = cancel
        self.inventory_running = True
        self.offloaded_state = "loading"
        self.home_state = "loading"
        self.home_screen_placeholders = set()
        self.sizes_state = "loading"
        self.sizes = {}
        self.inventory_note = ""
        threading.Thread(target=self._inventory_worker, args=(self._inv_generation, cancel, self.service.target),
                         name="inventory", daemon=True).start()
        self._ensure_polling()

    def _inventory_worker(self, generation: int, cancel: threading.Event,
                          target: Optional[DeviceTarget] = None) -> None:
        try:
            result = fetch_inventory(
                on_offloaded=lambda apps: self._events.put(("inv_offloaded", generation, apps)),
                on_sizes=lambda sizes: self._events.put(("inv_sizes", generation, sizes)),
                on_home_screen=lambda ids: self._events.put(("inv_home", generation, ids)),
                cancel=cancel, target=target)
        except Exception as exc:  # never let the worker die silently
            result = InventoryResult(error=f"{type(exc).__name__}: {exc}")
            result.offloaded_error = result.home_screen_error = result.sizes_error = result.error
        self._events.put(("inv_done", generation, result))

    def _cancel_inventory(self) -> None:
        if self._inv_cancel is not None:
            self._inv_cancel.set()
            self._inv_cancel = None
        self._inv_generation += 1
        self.inventory_running = False
        if self.sizes_state == "loading":
            self.sizes_state = "idle"
        if self.offloaded_state == "loading":
            self.offloaded_state = "idle"
        if self.home_state == "loading":
            self.home_state = "idle"

    def _on_offloaded(self, found: list[AppInfo]) -> None:
        """Offloaded apps exactly as iOS reports them (ShowPlaceholders + IsDemotedApp)."""
        installed = {a.bundle_id for a in self.installed_apps}
        self.offloaded_apps = [a for a in found if a.offloaded and a.bundle_id not in installed]
        self._known_offloaded = {a.bundle_id for a in self.offloaded_apps}
        self.offloaded_state = "ready"
        self._merge_apps()
        if self.icon_fetching:
            self._icon_refetch_pending = True
        elif not self.uninstalling:
            self._start_icon_fetch(only_missing=True)
        self._render()
        self._maybe_complete_verification()

    def _on_home_screen(self, placeholder_ids: set[str]) -> None:
        self.home_screen_placeholders = set(placeholder_ids)
        self.home_state = "ready"
        self._maybe_complete_verification()

    def _on_sizes(self, sizes: dict[str, AppSize]) -> None:
        self.sizes = dict(sizes)
        self.sizes_state = "ready"
        if SORT_MODES[self.sort_mode][1] not in ("name", "status"):      # only size sorts depend on the sizes
            self._render()
        else:
            self.app_list.refresh_sizes()

    def _on_inventory_done(self, result: InventoryResult) -> None:
        self.inventory_running = False
        self._inv_cancel = None
        self.last_inventory_result = result
        notes = []
        if self.offloaded_state == "loading" or result.offloaded_error:
            self.offloaded_state = "error"
            # Without a successful check nothing is shown as offloaded.
            self.offloaded_apps = []
            self._known_offloaded = set()
            self._merge_apps()
            notes.append(f"Offloaded apps couldn't be checked ({result.offloaded_error or 'unavailable'})")
        if self.home_state == "loading" or result.home_screen_error:
            self.home_state = "error"      # only affects double-checking removals
        if self.sizes_state == "loading" or result.sizes_error:
            self.sizes_state = "error"
            notes.append(f"App sizes unavailable ({result.sizes_error or 'unavailable'})")
        self.inventory_note = "  ·  ".join(notes)
        self._render()
        self._maybe_complete_verification()

    def _merge_apps(self) -> None:
        self.apps = self.installed_apps + self.offloaded_apps
        ids = {a.bundle_id for a in self.apps}
        self.checked &= ids

    def size_for(self, app: AppInfo) -> Union[AppSize, str]:
        """iOS-reported sizes. For offloaded apps: placeholder size + retained documents & data."""
        size = self.sizes.get(app.bundle_id)
        if size is not None:
            return size
        return "Calculating…" if self.sizes_state == "loading" else "Not available"

    def details_for(self, app: AppInfo) -> list[tuple[str, str]]:
        size = self.size_for(app)
        rows = [("Status", "Offloaded (app removed, documents & data kept)" if app.offloaded else "Installed"),
                ("Bundle ID", app.bundle_id)]
        if app.offloaded:
            version = app.version or "Not available"
            if app.build and app.build != app.version:
                version += f" (build {app.build})"
            rows.append(("Version", version))
            if isinstance(size, AppSize):
                rows += [("Retained data*", format_bytes(size.data_bytes)),
                         ("Placeholder", format_bytes(size.app_bytes)),
                         ("Total*", format_bytes(size.total_bytes))]
            else:
                rows.append(("Retained data", size))
            if self.home_state == "ready":
                rows.append(("Location", "Home Screen" if app.bundle_id in self.home_screen_placeholders
                             else "App Library only"))
            rows.append(("Type", "User-installed"))
        else:
            version = app.version or "—"
            if app.build and app.build != app.version:
                version += f" (build {app.build})"
            rows.append(("Version", version))
            if isinstance(size, AppSize):
                rows += [("App size", format_bytes(size.app_bytes)),
                         ("Docs & Data*", format_bytes(size.data_bytes)),
                         ("Total*", format_bytes(size.total_bytes))]
            else:
                rows.append(("Storage", size))
            families = [_DEVICE_FAMILY.get(f, f"Family {f}") for f in app.device_family]
            rows += [("Minimum iOS", app.min_os or "—"),
                     ("Devices", " & ".join(families) if families else "—"),
                     ("Type", "User-installed" if app.app_type == "User" else (app.app_type or "—")),
                     ("App Clip", "Yes" if app.is_app_clip else "No"),
                     ("Signed by", app.signer or "—")]
        return rows

    # ------------------------------------------------------------------ load results
    def _finish_loading(self) -> None:
        self.loading = False
        self.progress.stop()
        self.progress.place_forget()
        self.refresh_button.set_enabled(True)
        self.refresh_button.set_text("Refresh")
        self._sync_connection_controls()
        self.updated_label.configure(text=f"Last checked {datetime.now():%H:%M:%S}")

    def _on_loaded(self, device: DeviceInfo, apps: list[AppInfo]) -> None:
        self._finish_loading()
        self.device, self.error = device, None
        self.target = self.service.target
        udid = self.target.udid if self.target else None
        if udid != self._loaded_udid:
            # A different iPhone: ticks made for another device must never carry over to this one.
            self.checked.clear()
            self._known_offloaded = set()
            self._loaded_udid = udid
        self.installed_apps = list(apps)
        installed_ids = {a.bundle_id for a in apps}
        # Offloaded apps are re-detected by the inventory helper; keep their selection meanwhile.
        self.offloaded_apps = []
        self.apps = list(apps)
        self.checked &= installed_ids | self._known_offloaded   # forget apps that are gone
        preserve = getattr(self, "_preserve_icons", False)
        if preserve:
            self.icons.prune_real_icons(installed_ids | self._known_offloaded)   # keep icons of remaining apps
        self._set_status("connected", "Connected",
                         f"{device.name}  ·  iOS {device.ios_version}  ·  {self.service.connection.label}")
        self._draw_storage()
        self._render()
        self._start_icon_fetch(only_missing=preserve)
        self._start_inventory()
        self._run_after_refresh(True)

    def _on_error(self, error: DeviceError) -> None:
        self._finish_loading()
        self._cancel_icon_fetch()
        self._cancel_inventory()
        self.icon_note = ""
        self.inventory_note = ""
        self.device, self.error = None, error
        self.target = None
        self.apps, self.installed_apps, self.offloaded_apps = [], [], []
        self.sizes, self.sizes_state, self.offloaded_state = {}, "idle", "idle"
        state, label = _STATUS_FOR_ERROR.get(error.kind, ("error", "Error"))
        self._set_status(state, label, error.title)
        self._draw_storage()
        self._render()
        if error.kind is ErrorKind.MULTIPLE_DEVICES and not self.uninstalling:
            self.root.after(60, self._open_device_picker)     # the user must choose; nothing is guessed
        self._run_after_refresh(False)

    # ------------------------------------------------------------------ connection and device choice
    def _sync_connection_controls(self) -> None:
        """The connection can only be changed when nothing is loading or being removed."""
        self.connection_selector.set_enabled(not (self.loading or self.uninstalling))

    def _on_connection_selected(self, connection: ConnectionType) -> None:
        """The user switched between USB and Wi-Fi: forget the old iPhone and look again."""
        if self.loading or self.uninstalling or connection is self.service.connection:
            self.connection_selector.set_value(self.service.connection)     # refused: undo the highlight
            return
        self.service.set_connection(connection)
        self._cancel_icon_fetch()
        self._cancel_inventory()
        self.device, self.target, self.error = None, None, None
        self._loaded_udid = None
        self.checked.clear()
        self._known_offloaded = set()
        self.apps, self.installed_apps, self.offloaded_apps = [], [], []
        self.sizes, self.sizes_state, self.offloaded_state = {}, "idle", "idle"
        self.icon_note = self.inventory_note = ""
        self._draw_storage()
        self.refresh()

    def _open_device_picker(self) -> None:
        """Ask which iPhone to use (only when the Apple service reports more than one, or the chosen one left)."""
        error = self.error
        if error is None or error.kind is not ErrorKind.MULTIPLE_DEVICES or self.picker_dialog is not None:
            return
        if self.loading or self.uninstalling:
            return
        self.picker_dialog = DevicePickerDialog(
            self.root, candidates=error.candidates, connection_label=self.service.connection.label,
            fonts=self.fonts, scale=self.scale, note=error.details,
            on_choose=self._on_device_chosen, on_cancel=self._on_picker_cancelled)

    def _on_picker_cancelled(self) -> None:
        self.picker_dialog = None

    def _on_device_chosen(self, udid: str) -> None:
        self.picker_dialog = None
        self.service.choose_device(udid)
        self.refresh()

    def _run_after_refresh(self, ok: bool) -> None:
        callback, self._after_refresh = self._after_refresh, None
        self._preserve_icons = False
        if callback is not None:
            callback(ok)

    # ------------------------------------------------------------------ list rendering
    def _sort_key(self, column: str, descending: bool) -> Callable[[AppInfo], tuple]:
        def key(app: AppInfo) -> tuple:
            name = (app.name.casefold(), app.bundle_id.casefold())
            if column == "name":
                return name
            if column == "status":
                offloaded_first = not descending
                return (0 if app.offloaded == offloaded_first else 1, name)
            size = self.sizes.get(app.bundle_id)
            if size is None:
                return (1, 0, name)            # no size: always after apps with sizes
            value = {"app": size.app_bytes, "data": size.data_bytes, "total": size.total_bytes}[column]
            return (0, -value if descending else value, name)
        return key

    def _filtered_sorted_apps(self) -> list[AppInfo]:
        query = self.search_var.get().strip().casefold()
        apps = [a for a in self.apps
                if not query or query in a.name.casefold() or query in a.bundle_id.casefold()]
        _label, column, descending = SORT_MODES[self.sort_mode]
        if column == "name":
            apps.sort(key=self._sort_key("name", False), reverse=descending)
        else:
            apps.sort(key=self._sort_key(column, descending))
        return apps

    def _render(self) -> None:
        apps = self._filtered_sorted_apps()
        self.visible_ids = [a.bundle_id for a in apps]
        _label, column, descending = SORT_MODES[self.sort_mode]
        self.app_list.set_rows(apps, column, descending)
        self.sort_button.set_text(SORT_MODES[self.sort_mode][0])
        self._sort_var.set(self.sort_mode)
        self._update_overlay(apps)
        self._update_counts()

    def _update_overlay(self, visible: list[AppInfo]) -> None:
        if self.apps and visible:
            self._hide_overlay()
        elif self.loading and not self.apps:
            if self.service.connection is ConnectionType.WIFI:
                self._show_overlay("Reading apps from your iPhone over Wi-Fi…",
                                   "Keep your iPhone awake, unlocked and on the same Wi-Fi network. This can "
                                   "take a little longer than USB.", glyph=Glyph.PHONE)
            else:
                self._show_overlay("Reading apps from your iPhone…",
                                   "Keep your iPhone connected and unlocked. This usually takes a few seconds.",
                                   glyph=Glyph.PHONE)
        elif self.error is not None:
            glyph, accent = _ERROR_GLYPH.get(self.error.kind, (Glyph.WARNING, True))
            action = (("Choose iPhone…", self._open_device_picker)
                      if self.error.kind is ErrorKind.MULTIPLE_DEVICES else ("Try again", self.refresh))
            self._show_overlay(self.error.title, self.error.message, self.error.details,
                               action=action, glyph=glyph, accent=accent)
        elif not self.apps and self.device is not None:
            self._show_overlay("No apps found",
                               "Your iPhone didn't report any user-installed apps.",
                               action=("Refresh", self.refresh), glyph=Glyph.PHONE)
        elif self.apps and not visible:
            query = self.search_var.get().strip()
            self._show_overlay("No matching apps",
                               f"Nothing matches “{query}”. Try a different name or bundle ID.",
                               action=("Clear search", lambda: self.search_var.set("")),
                               glyph=Glyph.SEARCH)
        else:
            self._hide_overlay()

    def _update_counts(self) -> None:
        selected = sum(1 for a in self.apps if a.bundle_id in self.checked)
        total = len(self.apps)
        if selected:
            self.count_pill.set(f"{selected} selected", fill=Colors.ORANGE, fg=Colors.WHITE, glyph=Glyph.CHECK)
        else:
            self.count_pill.set("0 selected", fill=Colors.SLATE_100, fg=Colors.SLATE_500)
        if self.search_var.get().strip():
            summary = f"Showing {len(self.visible_ids)} of {total} apps"
        elif total or self.device:
            n_off = len(self.offloaded_apps)
            summary = f"{len(self.installed_apps)} installed"
            if n_off:
                summary += f"  ·  {n_off} offloaded"
            elif self.offloaded_state == "loading":
                summary += "  ·  checking for offloaded apps…"
        else:
            summary = ""
        if summary and self.sizes_state == "loading":
            summary += "  ·  Calculating app sizes…"
        for note in (self.inventory_note, self.icon_note):
            if summary and note:
                summary += f"  ·  {note}"
        self.summary_label.configure(text=summary)
        self.select_button.set_enabled(bool(self.visible_ids))
        self.deselect_button.set_enabled(bool(selected))
        busy = self.loading or self.uninstalling
        self.uninstall_button.set_enabled(not busy and bool(self.removable_selected_apps()))
        self.count_pill.set_command(self.open_review if selected and not self.uninstalling else None)
        self._schedule_fit_search()
        if hasattr(self, "footnote_label") and self._footnote_job is None:
            self._footnote_job = self.root.after_idle(self._fit_footnote)

    # ------------------------------------------------------------------ user actions
    def _toggle(self, iids: Iterable[str]) -> None:
        iids = [i for i in iids if i]
        if not iids:
            return
        if all(i in self.checked for i in iids):
            self.checked.difference_update(iids)
        else:
            self.checked.update(iids)
        self.app_list.refresh_checks(iids)
        self._update_counts()

    def select_all(self) -> None:
        """Tick every app currently shown (respects the search filter)."""
        self.checked.update(self.visible_ids)
        self.app_list.refresh_checks(self.visible_ids)
        self._update_counts()

    def deselect_all(self) -> None:
        """Untick every app, including ones hidden by the search filter."""
        previously = list(self.checked)
        self.checked.clear()
        self.app_list.refresh_checks(previously)
        self._update_counts()

    def set_sort(self, mode: str) -> None:
        if mode in SORT_MODES and mode != self.sort_mode:
            self.sort_mode = mode
            self._render()

    def toggle_sort(self) -> None:
        """Switch between name A→Z and Z→A (kept for the keyboard/header behaviour)."""
        self.set_sort("name_desc" if self.sort_mode == "name_asc" else "name_asc")

    def _on_header_sort(self, column: str) -> None:
        _label, current, descending = SORT_MODES[self.sort_mode]
        if column == "name":
            self.set_sort("name_desc" if current == "name" and not descending else "name_asc")
        elif column == "status":
            # First click: Offloaded apps first. Every further click reverses the order.
            self.set_sort("status_desc" if current == "status" and not descending else "status_asc")
        else:
            # First click: largest first. Clicking again flips the order.
            self.set_sort(f"{column}_asc" if current == column and descending else f"{column}_desc")

    def open_sort_menu(self) -> None:
        b = self.sort_button
        self._sort_var.set(self.sort_mode)
        try:
            self.sort_menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height() + self.px(4))
        finally:
            self.sort_menu.grab_release()

    # ------------------------------------------------------------------ uninstall (Stage 3)
    def selected_apps(self) -> list[AppInfo]:
        """Every selected app (including ones hidden by the search), in the current sort order."""
        apps = [a for a in self.apps if a.bundle_id in self.checked]
        apps.sort(key=lambda a: (a.name.casefold(), a.bundle_id.casefold()), reverse=self.sort_descending
                  if SORT_MODES[self.sort_mode][1] == "name" else False)
        return apps

    def removable_selected_apps(self) -> list[AppInfo]:
        return [a for a in self.selected_apps() if removal_block_reason(a) is None]

    def open_review(self) -> Optional[ReviewDialog]:
        apps = self.selected_apps()
        if not apps or self.uninstalling:
            return None
        self.review_dialog = ReviewDialog(self.root, apps=apps, icons=self.icons, fonts=self.fonts,
                                          scale=self.scale, on_uninstall=self.open_uninstall_confirmation,
                                          size_for=self.size_for)
        return self.review_dialog

    def open_uninstall_confirmation(self) -> Optional[ConfirmUninstallDialog]:
        """Show the confirmation dialog. Nothing is removed unless 'Uninstall' is pressed there."""
        if self.loading or self.uninstalling or self.device is None:
            return None
        selected = self.selected_apps()
        removable = [a for a in selected if removal_block_reason(a) is None]
        if not removable:
            return None
        reasons: dict[str, int] = {}
        for a in selected:
            reason = removal_block_reason(a)
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
        self.confirm_dialog = ConfirmUninstallDialog(
            self.root, apps=removable, skipped=len(selected) - len(removable), skip_reasons=reasons,
            device_name=(self.device.name if self.service.connection is ConnectionType.USB
                         else f"{self.device.name} (over Wi-Fi)"),
            icons=self.icons, fonts=self.fonts, scale=self.scale,
            on_confirm=self._start_uninstall, size_for=self.size_for)
        return self.confirm_dialog

    def _start_uninstall(self, confirmed: list[AppInfo]) -> None:
        """Called only by the confirmation dialog's Uninstall button."""
        if self.loading or self.uninstalling:
            return
        # The apps were confirmed for the iPhone and connection shown on screen: refuse if the
        # service is now pointed at anything else.
        shown, now = self.target, self.service.target
        if (shown is None) != (now is None) or (
                shown is not None and now is not None
                and (shown.udid, shown.connection) != (now.udid, now.connection)):
            return
        # Re-validate against the current list: still present, still selected, still removable.
        current = {a.bundle_id: a for a in self.apps}
        apps = [current[a.bundle_id] for a in confirmed
                if a.bundle_id in current and a.bundle_id in self.checked
                and removal_block_reason(current[a.bundle_id]) is None]
        if not apps:
            return
        self.uninstalling = True
        self._sync_connection_controls()
        self._cancel_icon_fetch()            # one device operation at a time; real icons are kept
        self._cancel_inventory()
        self.icon_note = ""
        self.refresh_button.set_enabled(False)
        self._update_counts()
        self.progress_dialog = UninstallProgressDialog(self.root, apps=apps, icons=self.icons, fonts=self.fonts,
                                                       scale=self.scale, on_done=self._on_progress_closed)
        threading.Thread(target=self._uninstall_worker, args=(apps,), name="uninstaller", daemon=True).start()
        self._ensure_polling()

    def _uninstall_worker(self, apps: list[AppInfo]) -> None:
        """Runs off the UI thread. Apps are removed strictly one after another."""
        try:
            results = run_uninstall_batch(
                self.service, apps,
                progress=lambda stage, i, _total, _app, result: self._events.put(
                    ("uninstall_progress", stage, i, result)))
        except Exception as exc:  # never let the worker die silently - nothing counts as removed
            results = [UninstallResult(a, Outcome.FAILED, f"Unexpected error: {exc}") for a in apps]
        self._events.put(("uninstall_done", results))

    def _on_uninstall_finished(self, results: list[UninstallResult]) -> None:
        self._uninstall_results = results
        if self.progress_dialog is not None:
            self.progress_dialog.set_phase("Refreshing the app list to confirm the results…")
        # Reload the list (keeping real icons of the remaining apps), then verify every result.
        self._begin_refresh(preserve_icons=True, after=self._after_uninstall_refresh)

    def _after_uninstall_refresh(self, ok: bool) -> None:
        if not ok:
            self._finish_uninstall(self._uninstall_results, verified=False)
            return
        # Wait for the offloaded-app check too, so an app left behind as a Home Screen
        # placeholder is never reported as removed.
        self._awaiting_verification = True
        self._maybe_complete_verification()

    def _maybe_complete_verification(self) -> None:
        """Verify every result against ALL sources: installed list, iOS's offloaded list
        (ShowPlaceholders) and the Home Screen placeholders."""
        if not self._awaiting_verification or "loading" in (self.offloaded_state, self.home_state):
            return
        self._awaiting_verification = False
        present = {a.bundle_id for a in self.installed_apps} | {a.bundle_id for a in self.offloaded_apps}
        if self.home_state == "ready":
            present |= self.home_screen_placeholders
        results = verify_results(self._uninstall_results, present,
                                 offloaded_listing_ok=self.offloaded_state == "ready")
        self._finish_uninstall(results, verified=True,
                               offloaded_checked=self.offloaded_state == "ready" and self.home_state == "ready")

    def _finish_uninstall(self, results: list[UninstallResult], verified: bool,
                          offloaded_checked: bool = True) -> None:
        removed_ids = {r.app.bundle_id for r in results if r.outcome is Outcome.REMOVED}
        self.checked -= removed_ids          # failed / not attempted apps stay selected
        self.last_uninstall_results = results
        self.uninstalling = False
        self._sync_connection_controls()
        self.refresh_button.set_enabled(not self.loading)
        if self.progress_dialog is not None:
            self.progress_dialog.finish(results, verified=verified, removed=count(results, Outcome.REMOVED),
                                        failed=count(results, Outcome.FAILED),
                                        not_attempted=count(results, Outcome.NOT_ATTEMPTED),
                                        blocked=count(results, Outcome.BLOCKED),
                                        unverified=count(results, Outcome.UNVERIFIED),
                                        offloaded_checked=offloaded_checked)
        self._render()
        if not self.icon_fetching and self.device is not None:
            self._start_icon_fetch(only_missing=True)    # e.g. icons for newly found offloaded apps

    def _on_progress_closed(self) -> None:
        self.progress_dialog = None
        self.root.focus_set()
