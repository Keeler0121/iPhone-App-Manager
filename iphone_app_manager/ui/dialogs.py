"""Modal dialogs for reviewing, confirming and tracking app removal.

All dialogs are non-blocking (callback based) so the main event loop keeps running.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable, Optional, Sequence

from ..device import removal_block_reason
from ..models import AppInfo, AppSize
from ..uninstall import Outcome, UninstallResult
from .icons import IconFactory
from .theme import Colors, Fonts, Glyph
from .widgets import IconBadge, RoundedButton, _Scaled, format_bytes


def fit_text(text: str, font: tkfont.Font, width: int) -> str:
    if width <= 0:
        return ""
    if font.measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + "…") <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def describe_app(app: AppInfo, size_for: Optional[Callable[[AppInfo], object]] = None) -> str:
    """'bundle.id  ·  Installed  ·  App 711.5 MB + data 161.0 MB' (sizes only when known)."""
    parts = [app.bundle_id, app.status]
    size = size_for(app) if size_for else None
    if isinstance(size, AppSize) and app.offloaded:
        parts.append(f"placeholder {format_bytes(size.app_bytes)} + retained data {format_bytes(size.data_bytes)}")
    elif isinstance(size, AppSize):
        parts.append(f"App {format_bytes(size.app_bytes)} + data {format_bytes(size.data_bytes)}")
    return "  ·  ".join(parts)


# ====================================================================== scrollable app rows
class AppRows(tk.Frame, _Scaled):
    """Compact scrollable list: icon, name, subtitle and an optional status on the right."""

    STATUS_STYLE = {
        "waiting": ("Waiting", Colors.SLATE_400, None),
        "working": ("Removing…", Colors.ORANGE, None),
        Outcome.REMOVED: ("Removed", Colors.ORANGE, Glyph.CHECK),
        Outcome.FAILED: ("Failed", Colors.SLATE_900, Glyph.CANCEL),
        Outcome.NOT_ATTEMPTED: ("Not attempted", Colors.SLATE_500, None),
        Outcome.BLOCKED: ("Can't remove", Colors.SLATE_500, None),
        Outcome.UNVERIFIED: ("Not verified", Colors.SLATE_700, None),
    }

    def __init__(self, master: tk.Misc, *, apps: Sequence[AppInfo], icons: IconFactory, fonts: Fonts,
                 scale: float, width: int, max_visible: int = 6,
                 size_for: Optional[Callable[[AppInfo], object]] = None) -> None:
        tk.Frame.__init__(self, master, bg=Colors.WHITE, highlightthickness=1,
                          highlightbackground=Colors.SLATE_200, bd=0)
        self.scale, self.icons, self.fonts = scale, icons, fonts
        self.apps = list(apps)
        self.row_h = self.p(48)
        self.width_px = self.p(width)
        self.subtitles = [describe_app(a, size_for) for a in self.apps]
        self.statuses: list[object] = [None] * len(self.apps)
        # Keep each app's icon as it was when the dialog opened (removed apps keep their real icon).
        self.images = [icons.app_icon(a.bundle_id) for a in self.apps]
        visible = max(1, min(len(self.apps), max_visible))
        self.canvas = tk.Canvas(self, width=self.width_px, height=visible * self.row_h, bg=Colors.WHITE,
                                highlightthickness=0, bd=0, yscrollincrement=self.row_h)
        self.canvas.pack(side="left", fill="both", expand=True)
        if len(self.apps) > max_visible:
            bar = ttk.Scrollbar(self, orient="vertical", style="Slim.Vertical.TScrollbar",
                                command=self.canvas.yview)
            bar.pack(side="right", fill="y", padx=(0, self.p(2)), pady=self.p(2))
            self.canvas.configure(yscrollcommand=bar.set)
            self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
            self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))
        self._draw()

    def _on_wheel(self, e: tk.Event) -> None:
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def set_status(self, index: int, status: object, subtitle: Optional[str] = None) -> None:
        self.statuses[index] = status
        if subtitle is not None:
            self.subtitles[index] = subtitle
        self._draw()
        self.see(index)

    def see(self, index: int) -> None:
        total = len(self.apps) * self.row_h
        top = self.canvas.canvasy(0)
        view = int(self.canvas.cget("height"))
        y0, y1 = index * self.row_h, (index + 1) * self.row_h
        if y0 < top:
            self.canvas.yview_moveto(y0 / total)
        elif y1 > top + view:
            self.canvas.yview_moveto((y1 - view) / total)

    def _draw(self) -> None:
        c, f, p, rh = self.canvas, self.fonts, self.p, self.row_h
        w = self.width_px
        c.delete("all")
        text_x = p(14) + self.icons.tile_size + p(12)
        for i, app in enumerate(self.apps):
            y0 = i * rh
            ym = y0 + rh / 2
            if i:
                c.create_line(p(14), y0, w - p(14), y0, fill=Colors.SLATE_100)
            c.create_image(p(14), ym, anchor="w", image=self.images[i])
            right = w - p(14)
            status = self.statuses[i]
            if status is not None:
                label, color, glyph = self.STATUS_STYLE[status]
                t = c.create_text(right, ym, anchor="e", text=label, font=f.small_bold, fill=color)
                right = c.bbox(t)[0] - p(6)
                if glyph and f.has_icons:
                    g = c.create_text(right, ym + 1, anchor="e", text=glyph, font=f.icon_small, fill=color)
                    right = c.bbox(g)[0]
                right -= p(12)
            avail = right - text_x
            c.create_text(text_x, ym - p(8), anchor="w", font=f.body_bold, fill=Colors.SLATE_900,
                          text=fit_text(app.name, f.body_bold, avail))
            c.create_text(text_x, ym + p(10), anchor="w", font=f.small, fill=Colors.SLATE_500,
                          text=fit_text(self.subtitles[i], f.small, avail))
        c.configure(scrollregion=(0, 0, w, len(self.apps) * rh))


# ====================================================================== base dialog
class _Dialog(tk.Toplevel, _Scaled):
    WIDTH = 560

    def __init__(self, parent: tk.Misc, *, title: str, fonts: Fonts, scale: float) -> None:
        tk.Toplevel.__init__(self, parent, bg=Colors.WHITE)
        self.withdraw()
        self.scale, self.fonts = scale, fonts
        self.parent = parent
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.body = tk.Frame(self, bg=Colors.WHITE)
        self.body.pack(fill="both", expand=True, padx=self.p(28), pady=(self.p(24), self.p(22)))
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.bind("<Escape>", lambda _e: self._on_close_request())
        self.closed = False

    def _header(self, glyph: str, title: str, message: str, accent: bool = True) -> None:
        row = tk.Frame(self.body, bg=Colors.WHITE)
        row.pack(fill="x")
        self.badge = IconBadge(row, fonts=self.fonts, scale=self.scale, bg=Colors.WHITE, size=52)
        self.badge.set(glyph, accent)
        self.badge.pack(side="left", anchor="n", padx=(0, self.p(16)))
        text = tk.Frame(row, bg=Colors.WHITE)
        text.pack(side="left", fill="x", expand=True)
        self.title_label = tk.Label(text, text=title, font=self.fonts.heading, fg=Colors.SLATE_900,
                                    bg=Colors.WHITE, anchor="w", justify="left")
        self.title_label.pack(fill="x")
        self.message_label = tk.Label(text, text=message, font=self.fonts.body, fg=Colors.SLATE_500,
                                      bg=Colors.WHITE, anchor="w", justify="left",
                                      wraplength=self.p(self.WIDTH - 68))
        self.message_label.pack(fill="x", pady=(self.p(4), 0))

    def _buttons(self) -> tk.Frame:
        row = tk.Frame(self.body, bg=Colors.WHITE)
        row.pack(fill="x", pady=(self.p(20), 0))
        return row

    def show(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        px = self.parent.winfo_rootx() + (self.parent.winfo_width() - w) // 2
        py = self.parent.winfo_rooty() + max(0, (self.parent.winfo_height() - h) // 3)
        self.geometry(f"+{max(0, px)}+{max(0, py)}")
        self.deiconify()
        self.lift()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_set()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def _on_close_request(self) -> None:
        self.close()


# ====================================================================== review
class ReviewDialog(_Dialog):
    """Shows every selected app; lets the user continue to the uninstall confirmation."""

    def __init__(self, parent: tk.Misc, *, apps: Sequence[AppInfo], icons: IconFactory, fonts: Fonts,
                 scale: float, on_uninstall: Callable[[], None],
                 size_for: Optional[Callable[[AppInfo], object]] = None) -> None:
        super().__init__(parent, title="Selected apps", fonts=fonts, scale=scale)
        removable = [a for a in apps if removal_block_reason(a) is None]
        blocked = len(apps) - len(removable)
        n_off = sum(1 for a in apps if a.offloaded)
        message = "These apps are currently selected"
        message += f" ({len(apps) - n_off} installed, {n_off} offloaded)." if n_off else "."
        if blocked:
            message += f" {plural(blocked, 'app')} can't be removed and would be skipped."
        self._header(Glyph.CHECK, f"{plural(len(apps), 'app')} selected", message, accent=True)
        rows = AppRows(self.body, apps=apps, icons=icons, fonts=fonts, scale=scale, width=self.WIDTH - 56,
                       max_visible=7, size_for=size_for)
        rows.pack(fill="x", pady=(self.p(18), 0))
        for i, app in enumerate(apps):
            reason = removal_block_reason(app)
            if reason:
                rows.set_status(i, Outcome.BLOCKED, f"{app.bundle_id}  ·  {app.status}  ·  {reason}")
        rows.see(0)
        buttons = self._buttons()
        self.uninstall_button = RoundedButton(buttons, text="Uninstall Selected", variant="primary",
                                              glyph=Glyph.DELETE, fonts=fonts, scale=scale,
                                              command=lambda: (self.close(), on_uninstall()))
        self.uninstall_button.set_enabled(bool(removable))
        self.uninstall_button.pack(side="right")
        self.close_button = RoundedButton(buttons, text="Close", command=self.close, fonts=fonts, scale=scale,
                                          min_width=100)
        self.close_button.pack(side="right", padx=(0, self.p(10)))
        self.show()
        self.close_button.focus_set()


# ====================================================================== confirmation
class ConfirmUninstallDialog(_Dialog):
    """The ONLY path to an uninstall: nothing happens unless 'Uninstall' is pressed here."""

    def __init__(self, parent: tk.Misc, *, apps: Sequence[AppInfo], skipped: int, device_name: str,
                 icons: IconFactory, fonts: Fonts, scale: float,
                 on_confirm: Callable[[list[AppInfo]], None],
                 on_cancel: Optional[Callable[[], None]] = None,
                 skip_reasons: Optional[dict[str, int]] = None,
                 size_for: Optional[Callable[[AppInfo], object]] = None) -> None:
        super().__init__(parent, title="Uninstall apps", fonts=fonts, scale=scale)
        self.apps = list(apps)
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self.result: Optional[str] = None   # "uninstall" / "cancel"
        n = len(self.apps)
        n_off = sum(1 for a in self.apps if a.offloaded)
        self.installed_count, self.offloaded_count = n - n_off, n_off
        what = f" ({n - n_off} installed, {n_off} offloaded)" if n_off else ""
        self._header(Glyph.DELETE, f"Uninstall {plural(n, 'app')}?",
                     f"The following {plural(n, 'app')}{what} will be removed from {device_name}:", accent=True)
        AppRows(self.body, apps=self.apps, icons=icons, fonts=fonts, scale=scale,
                width=self.WIDTH - 56, max_visible=5, size_for=size_for).pack(fill="x", pady=(self.p(16), 0))
        self.skipped_text = ""
        if skipped:
            self.skipped_text = f"{plural(skipped, 'other selected app')} can't be removed and will be skipped"
            if skip_reasons:
                self.skipped_text += " (" + "; ".join(f"{reason}: {n}" for reason, n in skip_reasons.items()) + ")"
            self.skipped_text += "."
            tk.Label(self.body, text=self.skipped_text, font=fonts.small, fg=Colors.SLATE_500, bg=Colors.WHITE,
                     anchor="w", justify="left", wraplength=self.p(self.WIDTH - 56)).pack(
                fill="x", pady=(self.p(8), 0))

        # Data notice: local data vs. accounts / cloud data.
        notice = tk.Frame(self.body, bg=Colors.ORANGE_TINT)
        notice.pack(fill="x", pady=(self.p(16), 0))
        tk.Frame(notice, bg=Colors.ORANGE, width=self.p(3)).pack(side="left", fill="y")
        inner = tk.Frame(notice, bg=Colors.ORANGE_TINT)
        inner.pack(side="left", fill="both", expand=True, padx=self.p(14), pady=self.p(12))
        wrap = self.p(self.WIDTH - 90)
        tk.Label(inner, text="Data stored on this iPhone may be permanently deleted",
                 font=fonts.body_bold, fg=Colors.SLATE_900, bg=Colors.ORANGE_TINT, anchor="w",
                 justify="left", wraplength=wrap).pack(fill="x")
        tk.Label(inner, text=("Uninstalling removes each app together with the data it keeps locally on "
                              "the iPhone, such as documents, settings, downloads and saved sign-ins. "
                              "This can't be undone."),
                 font=fonts.small, fg=Colors.SLATE_700, bg=Colors.ORANGE_TINT, anchor="w",
                 justify="left", wraplength=wrap).pack(fill="x", pady=(self.p(4), 0))
        tk.Label(inner, text=("It does not delete your accounts or anything stored online or in iCloud, "
                              "and it does not cancel subscriptions. Reinstalling an app and signing in "
                              "usually restores cloud-stored information."),
                 font=fonts.small, fg=Colors.SLATE_700, bg=Colors.ORANGE_TINT, anchor="w",
                 justify="left", wraplength=wrap).pack(fill="x", pady=(self.p(6), 0))
        self.offloaded_notice = None
        if n_off:
            self.offloaded_notice = tk.Label(
                inner, text=(f"Offloaded apps ({n_off}): the app itself is already gone, but its documents and "
                             "data are still kept on the iPhone. Removing it permanently deletes that retained "
                             "data and removes its Home Screen icon."),
                font=fonts.small_bold, fg=Colors.SLATE_900, bg=Colors.ORANGE_TINT, anchor="w", justify="left",
                wraplength=wrap)
            self.offloaded_notice.pack(fill="x", pady=(self.p(6), 0))

        buttons = self._buttons()
        self.uninstall_button = RoundedButton(buttons, text="Uninstall", variant="primary", glyph=Glyph.DELETE,
                                              command=self.confirm, fonts=fonts, scale=scale, min_width=130)
        self.uninstall_button.pack(side="right")
        self.cancel_button = RoundedButton(buttons, text="Cancel", command=self.cancel, fonts=fonts,
                                           scale=scale, min_width=110)
        self.cancel_button.pack(side="right", padx=(0, self.p(10)))
        self.show()
        self.cancel_button.focus_set()   # the safe choice has the keyboard focus

    def confirm(self) -> None:
        if self.result is not None:
            return
        self.result = "uninstall"
        self.close()
        self._on_confirm(self.apps)

    def cancel(self) -> None:
        if self.result is not None:
            return
        self.result = "cancel"
        self.close()
        if self._on_cancel:
            self._on_cancel()

    def _on_close_request(self) -> None:
        self.cancel()


# ====================================================================== progress + summary
class UninstallProgressDialog(_Dialog):
    """Live progress of the batch, then the final summary. Can't be closed while running."""

    def __init__(self, parent: tk.Misc, *, apps: Sequence[AppInfo], icons: IconFactory, fonts: Fonts,
                 scale: float, on_done: Callable[[], None]) -> None:
        super().__init__(parent, title="Uninstalling apps", fonts=fonts, scale=scale)
        self.apps = list(apps)
        self.total = len(self.apps)
        self.running = True
        self._on_done = on_done
        self._header(Glyph.DELETE, "Uninstalling apps…",
                     f"0 of {self.total} processed. Keep your iPhone connected and unlocked.", accent=True)
        self.bar = ttk.Progressbar(self.body, style="Uninstall.Horizontal.TProgressbar", mode="determinate",
                                   maximum=self.total, value=0)
        self.bar.pack(fill="x", pady=(self.p(16), 0))
        self.rows = AppRows(self.body, apps=self.apps, icons=icons, fonts=fonts, scale=scale,
                            width=self.WIDTH - 56, max_visible=6)
        self.rows.pack(fill="x", pady=(self.p(14), 0))
        for i in range(self.total):
            self.rows.statuses[i] = "waiting"
        self.rows._draw()
        self.note = tk.Label(self.body, text="", font=fonts.small, fg=Colors.SLATE_500, bg=Colors.WHITE,
                             anchor="w", justify="left", wraplength=self.p(self.WIDTH - 56))
        self.note.pack(fill="x", pady=(self.p(10), 0))
        buttons = self._buttons()
        self.done_button = RoundedButton(buttons, text="Done", variant="primary", command=self._done,
                                         fonts=fonts, scale=scale, min_width=110)
        self.done_button.set_enabled(False)
        self.done_button.pack(side="right")
        self.processed = 0
        self.show()

    def _on_close_request(self) -> None:
        if not self.running:
            self._done()   # closing is only possible once finished

    def _done(self) -> None:
        if self.running:
            return
        self.close()
        self._on_done()

    def mark_started(self, index: int) -> None:
        self.rows.set_status(index, "working")
        self.message_label.configure(text=f"Removing {self.apps[index].name}…  "
                                          f"({self.processed} of {self.total} processed)")

    def mark_done(self, index: int, result: UninstallResult) -> None:
        self.processed += 1
        subtitle = None
        if result.outcome is not Outcome.REMOVED and result.message:
            subtitle = f"{result.app.bundle_id}  ·  {result.message}"
        self.rows.set_status(index, result.outcome, subtitle)
        self.bar.configure(value=self.processed)
        self.message_label.configure(text=f"{self.processed} of {self.total} processed.")

    def set_phase(self, text: str) -> None:
        self.message_label.configure(text=text)

    def finish(self, results: Sequence[UninstallResult], verified: bool, removed: int, failed: int,
               not_attempted: int, blocked: int, offloaded_checked: bool = True, unverified: int = 0) -> None:
        """Show the final (verified) outcome of every app."""
        self.running = False
        for i, r in enumerate(results):
            subtitle = r.app.bundle_id if not r.message else f"{r.app.bundle_id}  ·  {r.message}"
            self.rows.statuses[i] = r.outcome
            self.rows.subtitles[i] = subtitle
        self.rows._draw()
        self.rows.see(0)
        problems = failed + not_attempted + blocked + unverified
        self.title("Uninstall complete" if not problems else "Uninstall finished")
        self.title_label.configure(text="Uninstall complete" if not problems else "Uninstall finished with problems")
        parts = [f"{removed} removed"]
        if unverified:
            parts.append(f"{unverified} not verified")
        if failed:
            parts.append(f"{failed} failed")
        if not_attempted:
            parts.append(f"{not_attempted} not attempted")
        if blocked:
            parts.append(f"{blocked} skipped")
        self.message_label.configure(text="  ·  ".join(parts))
        self.badge.set(Glyph.CHECK if not problems else Glyph.WARNING, True)
        notes = []
        if verified and not offloaded_checked:
            notes.append("Results were checked against the refreshed app list, but the offloaded-app list or "
                         "the Home Screen couldn't be read, so leftover offloaded entries couldn't be ruled out.")
        elif verified:
            notes.append("Results were checked against the installed apps, the offloaded apps and the Home Screen.")
        else:
            notes.append("The app list couldn't be refreshed, so these results could not be double-checked. "
                         "Reconnect your iPhone and click Refresh.")
        if failed or not_attempted or unverified:
            notes.append("Apps that weren't confirmed as removed are still selected. "
                         "Nothing is retried automatically.")
        self.note.configure(text=" ".join(notes))
        self.done_button.set_enabled(True)
        self.done_button.focus_set()
        self.bind("<Return>", lambda _e: self._done())


# ====================================================================== choose an iPhone
class DevicePickerDialog(_Dialog):
    """Lets the user pick which iPhone to manage when more than one is available.

    Nothing is done to any iPhone until one is chosen here; closing the dialog chooses nothing.
    """

    def __init__(self, parent: tk.Misc, *, candidates: Sequence, connection_label: str, fonts: Fonts,
                 scale: float, on_choose: Callable[[str], None],
                 on_cancel: Optional[Callable[[], None]] = None, note: str = "") -> None:
        super().__init__(parent, title="Choose an iPhone", fonts=fonts, scale=scale)
        self.candidates = list(candidates)
        self._on_choose = on_choose
        self._on_cancel = on_cancel
        self.result: Optional[str] = None      # the chosen UDID, or "cancel"
        message = (f"More than one iPhone is available over {connection_label}. Choose the one you want to "
                   "manage. Nothing is changed on any iPhone until you do.")
        if note:
            message = note + " " + message
        self._header(Glyph.PHONE, "Choose an iPhone", message, accent=False)
        self.choice_buttons: list[RoundedButton] = []
        column = tk.Frame(self.body, bg=Colors.WHITE)
        column.pack(fill="x", pady=(self.p(16), 0))
        for device in self.candidates:
            button = RoundedButton(column, text=device.label, command=lambda d=device: self.choose(d.udid),
                                   fonts=fonts, scale=scale, glyph=Glyph.PHONE, min_width=self.WIDTH - 56)
            button.pack(fill="x", pady=(0, self.p(8)))
            self.choice_buttons.append(button)
        buttons = self._buttons()
        self.cancel_button = RoundedButton(buttons, text="Cancel", command=self.cancel, fonts=fonts,
                                           scale=scale, min_width=110)
        self.cancel_button.pack(side="right")
        self.show()
        self.cancel_button.focus_set()

    def choose(self, udid: str) -> None:
        if self.result is not None:
            return
        self.result = udid
        self.close()
        self._on_choose(udid)

    def cancel(self) -> None:
        if self.result is not None:
            return
        self.result = "cancel"
        self.close()
        if self._on_cancel:
            self._on_cancel()

    def _on_close_request(self) -> None:
        self.cancel()
