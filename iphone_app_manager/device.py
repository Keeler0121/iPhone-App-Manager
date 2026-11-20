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
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Sequence
from xml.parsers.expat import ExpatError

from . import config
from .connection import ConnectionType, DeviceTarget, DiscoveredDevice, DiscoveryError
from .models import AppInfo, DeviceInfo, DeviceStorage


class ErrorKind(Enum):
    TOOL_MISSING = "tool_missing"
    NO_DEVICE = "no_device"
    NOT_TRUSTED = "not_trusted"
    LOCKED = "locked"
    TIMEOUT = "timeout"
    PARSE = "parse"
    UNKNOWN = "unknown"
    SERVICE_UNAVAILABLE = "service_unavailable"     # the Apple device service isn't running / answering
    WIFI_SYNC_OFF = "wifi_sync_off"                 # the iPhone is known to have Wi-Fi sync switched off
    MULTIPLE_DEVICES = "multiple_devices"           # several iPhones (or a missing choice): the user must pick
    INSTALL_SERVICE = "install_service"             # the iPhone's installation service can't be started


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


_FRIENDLY_TEXT.update({
    ErrorKind.SERVICE_UNAVAILABLE: (
        "Apple device service unavailable",
        "The Apple Mobile Device Service isn't responding. Install or repair the Apple Devices app from the "
        "Microsoft Store, make sure it is running, then click Refresh.",
    ),
    ErrorKind.WIFI_SYNC_OFF: (
        "Wi-Fi sync isn't turned on for this iPhone",
        "Connect the iPhone by USB, open Apple Devices, select the iPhone, choose General and tick "
        "“Show this iPhone when on Wi-Fi”, then click Apply. After that, unplug it and click Refresh.",
    ),
    ErrorKind.MULTIPLE_DEVICES: (
        "Choose an iPhone",
        "More than one iPhone is available. Choose the one you want to manage; nothing is done until you do.",
    ),
    ErrorKind.INSTALL_SERVICE: (
        "The iPhone's installation service is unavailable",
        "The iPhone didn't start its app-management service. Unlock the iPhone and keep it awake, then click "
        "Refresh. If it keeps happening, reconnect the iPhone or restart it.",
    ),
})

# Wording that differs when the iPhone is reached over Wi-Fi instead of USB.
_WIFI_TEXT = {
    ErrorKind.NO_DEVICE: (
        "iPhone not available over Wi-Fi",
        "Check that Wi-Fi sync is turned on for this iPhone (Apple Devices > General > “Show this iPhone when "
        "on Wi-Fi”, set up once over USB; if the box un-ticks itself after you click Apply, it did not turn on), "
        "that the iPhone is awake and on the same Wi-Fi network as this PC, then click Refresh. You can also "
        "switch to USB.",
    ),
    ErrorKind.NOT_TRUSTED: (
        "iPhone isn't set up for this PC",
        "Trust can only be given over USB. Connect the iPhone by USB, unlock it and tap Trust, turn on Wi-Fi "
        "sync in Apple Devices, then switch back to Wi-Fi and click Refresh.",
    ),
    ErrorKind.TIMEOUT: (
        "iPhone isn't responding over Wi-Fi",
        "The iPhone took too long to respond. Make sure it is awake, unlocked and on the same Wi-Fi network, "
        "then click Refresh. You can also switch to USB.",
    ),
}


def friendly_text(kind: ErrorKind, connection: Optional[ConnectionType] = None) -> tuple[str, str]:
    """(title, message) for an error, worded for the connection in use (USB wording by default)."""
    if connection is ConnectionType.WIFI and kind in _WIFI_TEXT:
        return _WIFI_TEXT[kind]
    return _FRIENDLY_TEXT[kind]


class DeviceError(Exception):
    """A problem talking to the iPhone, with a user-friendly title and message."""

    def __init__(self, kind: ErrorKind, details: str = "", connection: Optional[ConnectionType] = None,
                 candidates: Sequence[DiscoveredDevice] = ()) -> None:
        title, message = friendly_text(kind, connection)
        super().__init__(f"{title}: {details or message}")
        self.kind = kind
        self.title = title
        self.message = message
        self.details = details.strip()
        self.connection = connection
        self.candidates = tuple(candidates)      # the iPhones to choose from (MULTIPLE_DEVICES)


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
    # "No device found!" (no -u given), "No device found with udid X." (ideviceinstaller -u) and
    # "ERROR: Device X not found!" (ideviceinfo -u): the real wording of the bundled tools.
    if ("no device found" in t or "device not found" in t or "no device" in t
            or re.search(r"device\s+[0-9a-f-]{8,}\s+not found", t)):
        return ErrorKind.NO_DEVICE
    if "passwordprotected" in t or "password protected" in t or "passcode" in t:
        return ErrorKind.LOCKED
    if "installation_proxy" in t and ("could not start" in t or "could not connect" in t):
        return ErrorKind.INSTALL_SERVICE
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
                ErrorKind.TIMEOUT, ErrorKind.TOOL_MISSING, ErrorKind.INSTALL_SERVICE,
                ErrorKind.SERVICE_UNAVAILABLE}
_ERROR_LINE = re.compile(r"^\s*ERROR\b.*$", re.MULTILINE | re.IGNORECASE)
_COMPLETE_LINE = re.compile(r":\s*Complete\s*$", re.MULTILINE)
_GOT_ERROR = re.compile(r'Got error "([^"]+)"')


def interpret_uninstall_output(returncode: int, output: str,
                               connection: Optional[ConnectionType] = None) -> None:
    """Raise UninstallFailure unless ideviceinstaller clearly reported a completed uninstall."""
    errors = _ERROR_LINE.findall(output)
    if returncode == 0 and _COMPLETE_LINE.search(output) and not errors:
        return
    kind = classify_failure(output)
    lowered = output.lower()
    if kind in _FATAL_KINDS:
        raise UninstallFailure(DeviceError(kind, connection=connection).title, kind)
    if "installation_proxy" in lowered and ("could not start" in lowered or "could not connect" in lowered):
        raise UninstallFailure("The iPhone's installation service is unavailable", ErrorKind.UNKNOWN)
    if errors:
        code = _GOT_ERROR.search(errors[0])
        detail = f"iPhone reported: {code.group(1)}" if code else errors[0].strip()
        raise UninstallFailure(detail[:200])
    if returncode != 0:
        raise UninstallFailure(f"ideviceinstaller exited with code {returncode}")
    raise UninstallFailure("The iPhone did not confirm the removal")


# The iPhone's wireless settings (readable over USB). Observed on a real iPhone, with Wi-Fi sync ticked in
# Apple Devices, the domain held only: BonjourFullServiceName, EnableWifiDebugging, SupportsWifi and
# SupportsWifiSyncing. EnableWifiConnections - the key that would say whether wireless sync is on - was
# not reported at all. So a missing key means "unknown", never "off".
_WIFI_SYNC_DOMAIN = "com.apple.mobile.wireless_lockdown"
_WIFI_SYNC_KEY = "EnableWifiConnections"
_WIFI_SYNC_LINE = re.compile(rf"^\s*{_WIFI_SYNC_KEY}\s*:\s*(true|false)\s*$", re.IGNORECASE | re.MULTILINE)
_NAME_LOOKUP_TIMEOUT_SECONDS = 10


def parse_wifi_sync_state(text: str) -> Optional[bool]:
    """True/False only when the iPhone EXPLICITLY reports EnableWifiConnections; None otherwise."""
    match = _WIFI_SYNC_LINE.search(text)
    return None if match is None else match.group(1).lower() == "true"

Discoverer = Callable[[], "list[DiscoveredDevice]"]


class DeviceService:
    """High-level operations on the iPhone the user has chosen.

    Which iPhone, and over which connection (USB or Wi-Fi), is explicit state here:

    * ``set_connection`` picks USB (the default) or Wi-Fi.
    * ``resolve_target`` asks the Apple device service which iPhones are reachable over that
      connection and settles on exactly one. It never picks one arbitrarily when several are
      available, and it never switches to another iPhone (or to the other connection) by itself.
    * Every later command carries ``-u <UDID>``, plus ``-n`` for Wi-Fi only. ``-n`` makes the
      tools look at network devices only, so a Wi-Fi command cannot end up on USB, and a USB
      command (no ``-n``) cannot end up on Wi-Fi.

    A service built without a ``discoverer`` keeps the original behaviour: no discovery, no
    ``-u``, USB only.
    """

    def __init__(
        self,
        runner: Runner = run_tool,
        installer: Path = config.IDEVICEINSTALLER,
        info_tool: Path = config.IDEVICEINFO,
        timeout: float = config.COMMAND_TIMEOUT_SECONDS,
        uninstall_timeout: float = config.UNINSTALL_TIMEOUT_SECONDS,
        discoverer: Optional[Discoverer] = None,
    ) -> None:
        self._runner = runner
        self._installer = installer
        self._info_tool = info_tool
        self._timeout = timeout
        self._uninstall_timeout = uninstall_timeout
        self._discoverer = discoverer
        self._connection = ConnectionType.USB
        self._chosen_udid: Optional[str] = None
        self._target: Optional[DeviceTarget] = None
        self._names: dict[str, str] = {}        # UDID -> iPhone name, learned from the normal device-info read

    # ------------------------------------------------------------------ connection and target
    @property
    def connection(self) -> ConnectionType:
        return self._connection

    @property
    def target(self) -> Optional[DeviceTarget]:
        """The iPhone every command is sent to (None only for a service without discovery)."""
        return self._target

    def set_connection(self, connection: ConnectionType) -> None:
        """Switch between USB and Wi-Fi. Forgets the previously chosen iPhone and target."""
        self._connection = connection
        self._chosen_udid = None
        self._target = None

    def choose_device(self, udid: Optional[str]) -> None:
        """Remember which iPhone the user picked (None clears the choice)."""
        self._chosen_udid = udid
        self._target = None

    def _with_target(self, args: Sequence[str]) -> list[str]:
        """Prefix the command's arguments with the explicit device selection."""
        return (self._target.tool_args() if self._target else []) + list(args)

    def discover(self) -> list[DiscoveredDevice]:
        """iPhones the Apple device service can reach over the CURRENT connection type."""
        if self._discoverer is None:
            raise DeviceError(ErrorKind.SERVICE_UNAVAILABLE, "Device discovery isn't available.",
                              self._connection)
        try:
            listed = self._discoverer()
        except DiscoveryError as exc:
            raise DeviceError(ErrorKind.SERVICE_UNAVAILABLE, str(exc), self._connection) from exc
        return [d for d in listed if d.connection is self._connection]

    def resolve_target(self) -> Optional[DeviceTarget]:
        """Settle on exactly one iPhone and connection, or raise a DeviceError saying why not.

        Returns None only for a service without discovery (the original USB-only behaviour).
        """
        if self._discoverer is None:
            if self._connection is ConnectionType.WIFI:
                raise DeviceError(ErrorKind.SERVICE_UNAVAILABLE, "Device discovery isn't available.",
                                  self._connection)
            self._target = None
            return None
        devices = self.discover()
        if not devices:
            raise self._no_device_error()
        chosen = [d for d in devices if d.udid == self._chosen_udid]
        if chosen:
            device = chosen[0]
        elif len(devices) == 1 and self._chosen_udid is None:
            device = devices[0]
        else:
            # Several iPhones, or the one the user chose has gone and another has appeared:
            # never carry on with a different iPhone without being told to.
            named = [self._with_name(d) for d in devices]
            why = "The iPhone you chose isn't available any more." if self._chosen_udid else ""
            raise DeviceError(ErrorKind.MULTIPLE_DEVICES, why, self._connection, candidates=named)
        self._chosen_udid = device.udid
        self._target = DeviceTarget(device.udid, device.connection, self._names.get(device.udid, ""))
        return self._target

    def _with_name(self, device: DiscoveredDevice) -> DiscoveredDevice:
        name = self._lookup_name(device)
        return DiscoveredDevice(device.udid, device.connection, device.device_id, device.product_id, name)

    def _lookup_name(self, device: DiscoveredDevice) -> str:
        """The iPhone's name, if it can be read without pairing (a 'simple' lockdown connection)."""
        try:
            result = self._runner(self._info_tool, [*device.target().tool_args(), "-s", "-k", "DeviceName"],
                                  _NAME_LOOKUP_TIMEOUT_SECONDS)
        except DeviceError:
            return ""
        return _decode(result.stdout).strip() if result.returncode == 0 else ""

    def _wifi_sync_state(self, udid: str) -> Optional[bool]:
        """Whether a USB-connected iPhone says Wi-Fi sync is on: True/False only if it reports it
        explicitly; None (unknown) if the setting isn't reported or can't be read."""
        try:
            result = self._runner(self._info_tool, ["-u", udid, "-q", _WIFI_SYNC_DOMAIN],
                                  _NAME_LOOKUP_TIMEOUT_SECONDS)
        except DeviceError:
            return None
        if result.returncode != 0:
            return None
        return parse_wifi_sync_state(_decode(result.stdout))

    def _no_device_error(self) -> DeviceError:
        """No iPhone reachable over the chosen connection: say why as precisely as possible."""
        if self._connection is not ConnectionType.WIFI:
            return DeviceError(ErrorKind.NO_DEVICE, connection=self._connection)
        # Wi-Fi: if an iPhone is plugged in we can ask it whether Wi-Fi sync is switched on. "Sync is off" is
        # shown only when EVERY plugged-in iPhone explicitly reports it as off; otherwise it is unknown.
        try:
            on_usb = [d for d in (self._discoverer() if self._discoverer else [])
                      if d.connection is ConnectionType.USB]
        except DiscoveryError:
            on_usb = []
        states = [self._wifi_sync_state(d.udid) for d in on_usb]
        if states and all(state is False for state in states):
            return DeviceError(ErrorKind.WIFI_SYNC_OFF, connection=self._connection)
        return DeviceError(ErrorKind.NO_DEVICE, connection=self._connection)

    def _refine_loss(self, kind: ErrorKind) -> tuple[ErrorKind, str]:
        """After a device-lost failure during a command, say whether the Apple service is gone or just
        this iPhone. Uses a fresh device list and never changes the target."""
        conn = self._connection
        if kind is ErrorKind.NO_DEVICE and self._target is not None and self._discoverer is not None:
            try:
                listed = self._discoverer()
            except DiscoveryError:
                return (ErrorKind.SERVICE_UNAVAILABLE,
                        DeviceError(ErrorKind.SERVICE_UNAVAILABLE, connection=conn).title)
            target = self._target
            if any(d.udid == target.udid and d.connection is target.connection for d in listed):
                return kind, DeviceError(kind, connection=conn).title
            other = ConnectionType.USB if conn is ConnectionType.WIFI else ConnectionType.WIFI
            note = ""
            if any(d.udid == target.udid and d.connection is other for d in listed):
                note = f" (it is available over {other.label}, but {conn.label} was chosen)"
            return kind, DeviceError(kind, connection=conn).title + note
        return kind, DeviceError(kind, connection=conn).title

    # ------------------------------------------------------------------ operations
    def uninstall_app(self, bundle_id: str) -> None:
        """Remove ONE app with `ideviceinstaller --uninstall <bundle id>` on the chosen iPhone.

        Returns only when ideviceinstaller confirmed completion; raises UninstallFailure
        otherwise. The ID is validated and passed as a separate argument (no shell).
        """
        if not is_valid_bundle_id(bundle_id):
            raise UninstallFailure("Invalid bundle identifier")
        try:
            result = self._runner(self._installer, self._with_target(["--uninstall", bundle_id]),
                                  self._uninstall_timeout)
        except DeviceError as exc:
            raise UninstallFailure(exc.title, exc.kind) from exc
        output = (_decode(result.stdout) + "\n" + _decode(result.stderr)).strip()
        try:
            interpret_uninstall_output(result.returncode, output, self._connection)
        except UninstallFailure as failure:
            if failure.fatal_kind is ErrorKind.NO_DEVICE:
                kind, message = self._refine_loss(failure.fatal_kind)
                raise UninstallFailure(message, kind) from failure
            raise

    def _run_checked(self, exe: Path, args: Sequence[str]) -> bytes:
        result = self._runner(exe, self._with_target(args), self._timeout)
        if result.returncode != 0:
            output = (_decode(result.stderr) + "\n" + _decode(result.stdout)).strip()
            kind = classify_failure(output)
            if kind is ErrorKind.NO_DEVICE and self._target is not None:
                kind, _title = self._refine_loss(kind)
            raise DeviceError(
                kind,
                output or f"{exe.name} exited with code {result.returncode}.",
                self._connection,
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
        report("Connecting to iPhone…" if self._connection is ConnectionType.USB
               else "Looking for your iPhone over Wi-Fi…")
        self.resolve_target()          # explicit iPhone + connection (or a precise error)
        device = self.get_device_info()
        if self._target is not None:
            self._names[self._target.udid] = device.name
            self._target = replace(self._target, name=device.name)
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
