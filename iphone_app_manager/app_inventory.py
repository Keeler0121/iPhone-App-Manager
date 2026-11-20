"""Run the read-only inventory helper (offloaded apps + per-app storage) in its own process."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import config
from .app_icons import _python_executable, exit_message
from .connection import DeviceTarget
from .models import AppInfo, AppSize

HELPER_SCRIPT = Path(__file__).with_name("inventory_helper.py")

_EXIT_MESSAGES = {
    2: "iPhone not connected",
    3: "iPhone locked or not trusted",
    4: "libimobiledevice could not be loaded",
}


@dataclass
class InventoryResult:
    offloaded_error: Optional[str] = None
    home_screen_error: Optional[str] = None
    sizes_error: Optional[str] = None
    error: Optional[str] = None        # the whole helper failed / timed out
    cancelled: bool = False


INVENTORY_HELPER_FLAG = "--inventory-helper"


def helper_command(frozen: bool = config.IS_FROZEN, *, target: Optional[DeviceTarget] = None) -> list[str]:
    """Command for the inventory helper process (packaged app: the .exe in helper mode).

    With a ``target`` the helper is told exactly which iPhone and connection to use."""
    extra = target.helper_args() if target is not None else []
    if frozen:
        return [sys.executable, INVENTORY_HELPER_FLAG, str(config.LIBIMOBILEDEVICE_BIN), *extra]
    return [_python_executable(), "-I", str(HELPER_SCRIPT), str(config.LIBIMOBILEDEVICE_BIN), *extra]


def _offloaded_app(entry: object) -> Optional[AppInfo]:
    """AppInfo for one offloaded app reported by the helper (iOS: IsDemotedApp=True, User app)."""
    if not isinstance(entry, dict):
        return None
    bid, name = entry.get("bundle_id"), entry.get("name")
    if not isinstance(bid, str) or not bid or not isinstance(name, str):
        return None
    version = entry.get("version") if isinstance(entry.get("version"), str) else ""
    build = entry.get("build") if isinstance(entry.get("build"), str) else ""
    return AppInfo(bundle_id=bid, name=name or bid, version=version, build=build, app_type="User", offloaded=True)


def fetch_inventory(
    on_offloaded: Callable[[list[AppInfo]], None],
    on_sizes: Callable[[dict[str, AppSize]], None],
    cancel: threading.Event,
    *,
    on_home_screen: Optional[Callable[[set[str]], None]] = None,
    target: Optional[DeviceTarget] = None,
    command: Optional[list[str]] = None,
    total_timeout: float = config.INVENTORY_TOTAL_TIMEOUT_SECONDS,
    idle_timeout: float = config.INVENTORY_IDLE_TIMEOUT_SECONDS,
) -> InventoryResult:
    """Blocking (call from a worker thread). Device/helper problems are reported, never raised."""
    result = InventoryResult()
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.Popen(command or helper_command(target=target), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=flags)
    except OSError as exc:
        result.error = f"could not start inventory helper: {exc}"
        result.offloaded_error = result.sizes_error = result.error
        return result

    drain = threading.Thread(target=proc.stderr.read, daemon=True)
    drain.start()
    done = threading.Event()
    last_progress = [time.monotonic()]
    timed_out = [False]
    start = time.monotonic()

    def watchdog() -> None:
        while not done.is_set():
            now = time.monotonic()
            if cancel.is_set() or now - start > total_timeout or now - last_progress[0] > idle_timeout:
                timed_out[0] = not cancel.is_set()
                proc.kill()
                return
            done.wait(0.2)

    threading.Thread(target=watchdog, daemon=True).start()
    got_offloaded = got_home = got_sizes = finished = False
    try:
        for raw in proc.stdout:
            last_progress[0] = time.monotonic()
            try:
                msg = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                break
            kind = msg.get("type")
            if kind == "offloaded":
                apps = [a for a in map(_offloaded_app, msg.get("apps", [])) if a is not None]
                got_offloaded = True
                on_offloaded(apps)
            elif kind == "offloaded_error":
                got_offloaded = True
                result.offloaded_error = str(msg.get("message", "unavailable"))
            elif kind == "home_screen":
                got_home = True
                ids = {b for b in msg.get("placeholders", []) if isinstance(b, str)}
                if on_home_screen:
                    on_home_screen(ids)
            elif kind == "home_screen_error":
                got_home = True
                result.home_screen_error = str(msg.get("message", "unavailable"))
            elif kind == "sizes":
                sizes = {}
                for bid, pair in (msg.get("sizes") or {}).items():
                    if (isinstance(pair, list) and len(pair) == 2 and all(isinstance(v, int) and v >= 0 for v in pair)):
                        sizes[bid] = AppSize(pair[0], pair[1])
                got_sizes = True
                on_sizes(sizes)
            elif kind == "sizes_error":
                got_sizes = True
                result.sizes_error = str(msg.get("message", "unavailable"))
            elif kind == "end":
                finished = True
                break
    finally:
        done.set()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        drain.join(timeout=2)
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass

    if cancel.is_set():
        result.cancelled = True
    elif not finished:
        result.error = "timed out" if timed_out[0] else exit_message(
            proc.returncode, target, "inventory helper stopped unexpectedly")
    if not got_offloaded and not result.cancelled:
        result.offloaded_error = result.offloaded_error or result.error or "unavailable"
    if not got_home and not result.cancelled:
        result.home_screen_error = result.home_screen_error or result.error or "unavailable"
    if not got_sizes and not result.cancelled:
        result.sizes_error = result.sizes_error or result.error or "unavailable"
    return result
