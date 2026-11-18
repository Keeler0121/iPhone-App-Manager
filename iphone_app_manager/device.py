"""Access to a connected iPhone through libimobiledevice command-line tools.

Everything here only *reads* information, except ``DeviceService.uninstall_app``, which
removes one validated, user-installed app and is only ever called after the user has
confirmed the removal in the UI.
"""
from __future__ import annotations

import plistlib
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Sequence
from xml.parsers.expat import ExpatError

from . import config
from .models import AppInfo, DeviceInfo, DeviceStorage


class ErrorKind(Enum):
    TOOL_MISSING = "tool_missing"
    NO_DEVICE = "no_device"
    NOT_TRUSTED = "not_trusted"
    LOCKED = "locked"
    TIMEOUT = "timeout"
    PARSE = "parse"
    UNKNOWN = "unknown"


_FRIENDLY_TEXT = {
    ErrorKind.TOOL_MISSING: (
        "libimobiledevice tools not found",
        f"Couldn't find ideviceinstaller.exe / ideviceinfo.exe in {config.LIBIMOBILEDEVICE_BIN}. "
        "Check that MSYS2 and libimobiledevice are installed there.",
    ),
    ErrorKind.NO_DEVICE: (
        "No iPhone connected",
        "Connect your iPhone with a USB cable, unlock it, then click Refresh. "
        "If it's already plugged in, check that the Apple Devices app can see it.",
    ),
    ErrorKind.NOT_TRUSTED: (
        "iPhone doesn't trust this computer",
        "Unlock your iPhone. When the “Trust This Computer?” prompt appears, tap Trust "
        "and enter your passcode, then click Refresh.",
    ),
    ErrorKind.LOCKED: (
        "iPhone is locked",
        "Unlock your iPhone with your passcode, then click Refresh.",
    ),
    ErrorKind.TIMEOUT: (
        "iPhone isn't responding",
        "The iPhone took too long to respond. Unplug it, plug it back in, unlock it, then click Refresh.",
    ),
    ErrorKind.PARSE: (
        "Couldn't read the app list",
        "The iPhone returned data that couldn't be understood. Click Refresh to try again.",
    ),
    ErrorKind.UNKNOWN: (
        "Something went wrong",
        "An unexpected error occurred while talking to the iPhone. Click Refresh to try again.",
    ),
}


class DeviceError(Exception):
    """A problem talking to the iPhone, with a user-friendly title and message."""

    def __init__(self, kind: ErrorKind, details: str = "") -> None:
        title, message = _FRIENDLY_TEXT[kind]
        super().__init__(f"{title}: {details or message}")
        self.kind = kind
        self.title = title
        self.message = message
        self.details = details.strip()


@dataclass(frozen=True)
class ToolResult:
    returncode: int
    stdout: bytes
    stderr: bytes


# A runner executes a tool and returns its raw output. Swappable for testing.
Runner = Callable[[Path, Sequence[str], float], ToolResult]


def run_tool(exe: Path, args: Sequence[str], timeout: float) -> ToolResult:
    """Run a command-line tool without showing a console window."""
    if not exe.is_file():
        raise DeviceError(ErrorKind.TOOL_MISSING, f"Expected executable at: {exe}")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            [str(exe), *args],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=flags,
        )
    except FileNotFoundError as exc:
        raise DeviceError(ErrorKind.TOOL_MISSING, str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise DeviceError(
            ErrorKind.TIMEOUT, f"{exe.name} did not finish within {timeout:.0f} seconds."
        ) from exc
    except OSError as exc:
        raise DeviceError(ErrorKind.UNKNOWN, f"Could not start {exe.name}: {exc}") from exc
    return ToolResult(proc.returncode, proc.stdout, proc.stderr)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def classify_failure(text: str) -> ErrorKind:
    """Map libimobiledevice error output to an ErrorKind."""
    t = text.lower()
    if "no device found" in t or "device not found" in t or "no device" in t:
        return ErrorKind.NO_DEVICE
    if "passwordprotected" in t or "password protected" in t or "passcode" in t:
        return ErrorKind.LOCKED
    trust_markers = (
        "pairing dialog response pending",
        "user denied pairing",
        "invalid hostid",
        "invalid host id",
        "not paired",
        "pairing",
        "trust",
        "lockdownd",
        "ssl",
    )
    if any(marker in t for marker in trust_markers):
        return ErrorKind.NOT_TRUSTED
    return ErrorKind.UNKNOWN


def _first_text(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def app_from_plist(entry: dict) -> Optional[AppInfo]:
    """Build an AppInfo from one app's Info.plist dictionary."""
    bundle_id = _first_text(entry, "CFBundleIdentifier")
    if not bundle_id:
        return None
    family = entry.get("UIDeviceFamily")
    if isinstance(family, int):
        family = [family]
    # Only these documented, non-personal keys are kept. Account identifiers present in the
    # raw listing (e.g. ApplicationDSID) are never read or stored.
    return AppInfo(
        bundle_id=bundle_id,
        name=_first_text(entry, "CFBundleDisplayName", "CFBundleName", "CFBundleExecutable") or bundle_id,
        version=_first_text(entry, "CFBundleShortVersionString", "CFBundleVersion"),
        build=_first_text(entry, "CFBundleVersion"),
        app_type=_first_text(entry, "ApplicationType"),
        min_os=_first_text(entry, "MinimumOSVersion"),
        device_family=tuple(sorted(f for f in family if isinstance(f, int))) if isinstance(family, list) else (),
        is_app_clip=entry.get("IsAppClip") is True,
        signer=_first_text(entry, "SignerIdentity"),
        offloaded=entry.get("IsDemotedApp") is True,   # explicit flag, if this iOS version sets it
    )


# ---------------------------------------------------------------------- overall storage
def parse_disk_usage(text: str) -> Optional[DeviceStorage]:
    """Parse `ideviceinfo -q com.apple.disk_usage`. Returns None unless the figures are consistent.

    Uses AmountDataAvailable (space free right now). TotalDataAvailable is deliberately NOT used:
    it includes far more reclaimable space than iOS Settings reports and overstates free space.
    """
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in ("TotalDiskCapacity", "AmountDataAvailable", "TotalDataCapacity",
                                   "TotalSystemCapacity"):
            try:
                values[key.strip()] = int(value.strip())
            except ValueError:
                return None
    capacity, free = values.get("TotalDiskCapacity"), values.get("AmountDataAvailable")
    if not capacity or capacity <= 0 or free is None or not 0 <= free <= capacity:
        return None
    data_cap = values.get("TotalDataCapacity", 0)
    if data_cap and free > data_cap:
        return None
    return DeviceStorage(capacity=capacity, free_now=free, data_capacity=data_cap,
                         system_capacity=values.get("TotalSystemCapacity", 0))


def parse_app_list(raw: bytes) -> list[AppInfo]:
    """Parse the XML plist produced by `ideviceinstaller --list-apps -o xml`."""
    start = raw.find(b"<?xml")
    if start == -1:
        start = raw.find(b"<plist")
    if start == -1:
        text = _decode(raw).strip()
        kind = classify_failure(text)
        raise DeviceError(kind if kind is not ErrorKind.UNKNOWN else ErrorKind.PARSE,
                          text or "ideviceinstaller produced no output.")
    try:
        data = plistlib.loads(raw[start:], fmt=plistlib.FMT_XML)
    except (plistlib.InvalidFileException, ExpatError, ValueError) as exc:
        raise DeviceError(ErrorKind.PARSE, f"Invalid XML from ideviceinstaller: {exc}") from exc
    if not isinstance(data, list):
        raise DeviceError(ErrorKind.PARSE, f"Expected a list of apps, got {type(data).__name__}.")
    apps = [app for entry in data if isinstance(entry, dict) and (app := app_from_plist(entry))]
    return apps


# ---------------------------------------------------------------------- uninstall safety
# Apple: bundle IDs use letters, digits, hyphens and periods (underscores appear in some
# older apps). The first character must be alphanumeric, so an ID can never be mistaken
# for a command-line option. A dot is NOT required (real apps such as "ScoreBoard" have none).
_BUNDLE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")
PROTECTED_PREFIXES = ("com.apple.",)


def is_valid_bundle_id(bundle_id: str) -> bool:
    return isinstance(bundle_id, str) and _BUNDLE_ID_RE.fullmatch(bundle_id) is not None


def removal_block_reason(app: AppInfo) -> Optional[str]:
    """Why this app must not be uninstalled, or None if it is a removable user app."""
    if not is_valid_bundle_id(app.bundle_id):
        return "Invalid bundle identifier"
    if app.offloaded and not config.OFFLOADED_REMOVAL_ENABLED:
        return "Removing offloaded apps isn't verified yet"
    if app.app_type != "User":
        return "Not a user-installed app"
    if app.bundle_id.lower().startswith(PROTECTED_PREFIXES):
        return "Apple app (protected)"
    return None


class UninstallFailure(Exception):
    """One app could not be removed. ``fatal_kind`` is set when the device itself is unavailable."""

    def __init__(self, message: str, fatal_kind: Optional[ErrorKind] = None) -> None:
        super().__init__(message)
        self.message = message
        self.fatal_kind = fatal_kind

    @property
    def fatal(self) -> bool:
        return self.fatal_kind is not None


_FATAL_KINDS = {ErrorKind.NO_DEVICE, ErrorKind.NOT_TRUSTED, ErrorKind.LOCKED,
                ErrorKind.TIMEOUT, ErrorKind.TOOL_MISSING}
_ERROR_LINE = re.compile(r"^\s*ERROR\b.*$", re.MULTILINE | re.IGNORECASE)
_COMPLETE_LINE = re.compile(r":\s*Complete\s*$", re.MULTILINE)
_GOT_ERROR = re.compile(r'Got error "([^"]+)"')


def interpret_uninstall_output(returncode: int, output: str) -> None:
    """Raise UninstallFailure unless ideviceinstaller clearly reported a completed uninstall."""
    errors = _ERROR_LINE.findall(output)
    if returncode == 0 and _COMPLETE_LINE.search(output) and not errors:
        return
    kind = classify_failure(output)
    lowered = output.lower()
    if kind in _FATAL_KINDS:
        raise UninstallFailure(DeviceError(kind).title, kind)
    if "installation_proxy" in lowered and ("could not start" in lowered or "could not connect" in lowered):
        raise UninstallFailure("The iPhone's installation service is unavailable", ErrorKind.UNKNOWN)
    if errors:
        code = _GOT_ERROR.search(errors[0])
        detail = f"iPhone reported: {code.group(1)}" if code else errors[0].strip()
        raise UninstallFailure(detail[:200])
    if returncode != 0:
        raise UninstallFailure(f"ideviceinstaller exited with code {returncode}")
    raise UninstallFailure("The iPhone did not confirm the removal")


class DeviceService:
    """High-level operations on the connected iPhone."""

    def __init__(
        self,
        runner: Runner = run_tool,
        installer: Path = config.IDEVICEINSTALLER,
        info_tool: Path = config.IDEVICEINFO,
        timeout: float = config.COMMAND_TIMEOUT_SECONDS,
        uninstall_timeout: float = config.UNINSTALL_TIMEOUT_SECONDS,
    ) -> None:
        self._runner = runner
        self._installer = installer
        self._info_tool = info_tool
        self._timeout = timeout
        self._uninstall_timeout = uninstall_timeout

    def uninstall_app(self, bundle_id: str) -> None:
        """Remove ONE app with `ideviceinstaller --uninstall <bundle id>`.

        Returns only when ideviceinstaller confirmed completion; raises UninstallFailure
        otherwise. The ID is validated and passed as a separate argument (no shell).
        """
        if not is_valid_bundle_id(bundle_id):
            raise UninstallFailure("Invalid bundle identifier")
        try:
            result = self._runner(self._installer, ["--uninstall", bundle_id], self._uninstall_timeout)
        except DeviceError as exc:
            raise UninstallFailure(exc.title, exc.kind) from exc
        output = (_decode(result.stdout) + "\n" + _decode(result.stderr)).strip()
        interpret_uninstall_output(result.returncode, output)

    def _run_checked(self, exe: Path, args: Sequence[str]) -> bytes:
        result = self._runner(exe, args, self._timeout)
        if result.returncode != 0:
            output = (_decode(result.stderr) + "\n" + _decode(result.stdout)).strip()
            raise DeviceError(
                classify_failure(output),
                output or f"{exe.name} exited with code {result.returncode}.",
            )
        return result.stdout

    def get_device_info(self) -> DeviceInfo:
        """Read the iPhone's name and iOS version (also confirms it's connected and trusted)."""
        name = _decode(self._run_checked(self._info_tool, ["-k", "DeviceName"])).strip()
        version = _decode(self._run_checked(self._info_tool, ["-k", "ProductVersion"])).strip()
        return DeviceInfo(name=name or "iPhone", ios_version=version or "unknown")

    def list_apps(self) -> list[AppInfo]:
        """Return the user-installed apps on the iPhone."""
        raw = self._run_checked(self._installer, ["--list-apps", "-o", "xml"])
        return parse_app_list(raw)

    def load_snapshot(
        self, progress: Optional[Callable[[str], None]] = None
    ) -> tuple[DeviceInfo, list[AppInfo]]:
        """Fetch device details and the app list. Safe to call from a worker thread."""
        report = progress or (lambda _msg: None)
        report("Connecting to iPhone…")
        device = self.get_device_info()
        report("Reading installed apps…")
        apps = self.list_apps()
        report("Reading storage…")
        storage = self.get_storage()
        return DeviceInfo(device.name, device.ios_version, storage), apps

    def get_storage(self) -> Optional[DeviceStorage]:
        """Overall storage via `ideviceinfo -q com.apple.disk_usage` (read-only). None if unavailable."""
        try:
            raw = self._run_checked(self._info_tool, ["-q", "com.apple.disk_usage"])
        except DeviceError:
            return None
        return parse_disk_usage(_decode(raw))
