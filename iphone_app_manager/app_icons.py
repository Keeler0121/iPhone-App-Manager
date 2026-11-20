"""Fetch real app icons from the iPhone through the isolated helper process.

The helper (icon_helper.py) talks to the native libimobiledevice DLL. Running it as a
separate process means a crash or hang there can only end the helper - the app keeps
its placeholder icons. Icons stay in memory; nothing is written to disk and nothing is
sent over the network.
"""
from __future__ import annotations

import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Optional, Sequence

from . import config
from .connection import ConnectionType, DeviceTarget

HELPER_SCRIPT = Path(__file__).with_name("icon_helper.py")

_EXIT_MESSAGES = {
    2: "iPhone not connected",
    3: "iPhone locked or not trusted",
    4: "libimobiledevice could not be loaded",
}


def exit_message(code: Optional[int], target: Optional[DeviceTarget], default: str) -> str:
    """Why a helper stopped, worded for the connection it was using."""
    if code == 2 and target is not None and target.connection is ConnectionType.WIFI:
        return "iPhone not reachable over Wi-Fi"
    return _EXIT_MESSAGES.get(code, default) if code is not None else default


@dataclass
class IconFetchResult:
    requested: int = 0
    received: int = 0
    failed: list[str] = field(default_factory=list)
    error: Optional[str] = None      # set when the whole fetch stopped early
    cancelled: bool = False


def _python_executable() -> str:
    """Prefer python.exe over pythonw.exe so the helper has proper standard streams."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        return str(exe.with_name("python.exe"))
    return str(exe)


ICON_HELPER_FLAG = "--icon-helper"


def helper_command(size: int, frozen: bool = config.IS_FROZEN, *,
                   target: Optional[DeviceTarget] = None) -> list[str]:
    """Command for the icon helper process.

    Packaged app: the .exe re-launches itself in helper mode (there is no Python interpreter).
    From source: run icon_helper.py with Python in isolated mode. With a ``target`` the helper
    is told exactly which iPhone and connection to use.
    """
    extra = target.helper_args() if target is not None else []
    if frozen:
        return [sys.executable, ICON_HELPER_FLAG, str(config.LIBIMOBILEDEVICE_BIN), str(size), *extra]
    return [_python_executable(), "-I", str(HELPER_SCRIPT), str(config.LIBIMOBILEDEVICE_BIN), str(size), *extra]


def _read_exact(stream: BinaryIO, n: int) -> Optional[bytes]:
    buf = b""
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def fetch_icons(
    bundle_ids: Sequence[str],
    size: int,
    on_icon: Callable[[str, bytes], None],
    cancel: threading.Event,
    *,
    target: Optional[DeviceTarget] = None,
    command: Optional[list[str]] = None,
    total_timeout: Optional[float] = None,
    idle_timeout: float = config.ICON_IDLE_TIMEOUT_SECONDS,
) -> IconFetchResult:
    """Run the helper and call on_icon(bundle_id, png_bytes) for every icon as it arrives.

    Blocking - call from a worker thread. Never raises for device/helper problems;
    they are reported in the returned IconFetchResult.
    """
    result = IconFetchResult(requested=len(bundle_ids))
    if not bundle_ids:
        return result
    if total_timeout is None:
        total_timeout = config.ICON_BASE_TIMEOUT_SECONDS + config.ICON_PER_APP_TIMEOUT_SECONDS * len(bundle_ids)

    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.Popen(command or helper_command(size, target=target), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    except OSError as exc:
        result.error = f"Could not start icon helper: {exc}"
        return result

    stderr_text: list[bytes] = []
    drain = threading.Thread(target=lambda: stderr_text.append(proc.stderr.read()), daemon=True)
    drain.start()

    # Watchdog: kills the helper on cancel, overall timeout, or no progress for idle_timeout.
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

    finished = False
    try:
        try:
            proc.stdin.write("\n".join(bundle_ids).encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass  # helper already exited; reported below
        out = proc.stdout
        while True:
            tag = out.read(1)
            if tag == b"I":
                header = _read_exact(out, 6)
                if header is None:
                    break
                id_len, png_len = struct.unpack(">HI", header)
                ident, png = _read_exact(out, id_len), _read_exact(out, png_len)
                if ident is None or png is None:
                    break
                last_progress[0] = time.monotonic()
                result.received += 1
                on_icon(ident.decode("utf-8", errors="replace"), png)
            elif tag == b"F":
                header = _read_exact(out, 6)
                if header is None:
                    break
                id_len, _err = struct.unpack(">Hi", header)
                ident = _read_exact(out, id_len)
                if ident is None:
                    break
                last_progress[0] = time.monotonic()
                result.failed.append(ident.decode("utf-8", errors="replace"))
            elif tag == b"E":
                finished = True
                break
            else:
                break  # EOF or unexpected data
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
    elif timed_out[0]:
        result.error = "timed out"
    elif not finished:
        result.error = exit_message(proc.returncode, target, "icon helper stopped unexpectedly")
    return result
