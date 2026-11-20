"""How the app reaches an iPhone: connection types, explicit device targets and device discovery.

The iPhone is managed through the Apple Mobile Device Service ("usbmuxd"), which the Apple
Devices app installs. That service lists every iPhone it can reach and says whether it is
reached over USB or over the network (Wi-Fi sync). The libimobiledevice tools use the same
list, so this module reads it the same way (a read-only ``ListDevices`` request on the local
loopback port) and never talks to an iPhone itself.

Facts about the bundled tools (libimobiledevice 1.4.0, ideviceinstaller 1.1.1) that the rest of
the app relies on - checked in their source, not assumed (and unchanged between libimobiledevice
1.3.0 and 1.4.0; the release uses 1.4.0 because 1.3.0 cannot connect to a Wi-Fi device on Windows):

* Without ``-n`` a tool only considers USB devices. With ``-n`` it considers ONLY network
  (Wi-Fi) devices: ``-n`` replaces the USB lookup, it does not add to it. So a tool started
  with ``-n`` can never fall back to USB, and one started without it can never use Wi-Fi.
* Without ``-u <UDID>`` a tool takes the first device it finds, whichever that is. Every command
  therefore carries an explicit ``-u`` once a device has been chosen.

Bluetooth is not involved: the iPhone does not offer its app-management services over Bluetooth.
"""
from __future__ import annotations

import os
import plistlib
import re
import socket
import struct
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

#: Where the Apple Mobile Device Service listens on Windows (the same default as libusbmuxd).
DEFAULT_SERVICE_ADDRESS = ("127.0.0.1", 27015)
DISCOVERY_TIMEOUT_SECONDS = 4.0


class ConnectionType(Enum):
    USB = "usb"
    WIFI = "wifi"

    @property
    def label(self) -> str:
        return "USB" if self is ConnectionType.USB else "Wi-Fi"


# A UDID is hexadecimal with at most one hyphen in the modern form (00008110-001234567890801E).
# The first character is always alphanumeric, so a UDID can never be read as a command-line option.
_UDID_RE = re.compile(r"[0-9A-Fa-f][0-9A-Fa-f-]{7,62}")


def is_valid_udid(udid: object) -> bool:
    return isinstance(udid, str) and _UDID_RE.fullmatch(udid) is not None


def short_udid(udid: str) -> str:
    """The last characters of a UDID, enough for a person to tell two iPhones apart."""
    return "…" + udid[-6:] if len(udid) > 10 else udid


@dataclass(frozen=True)
class DeviceTarget:
    """One explicitly chosen iPhone and the connection to use for it."""

    udid: str
    connection: ConnectionType = ConnectionType.USB
    name: str = ""

    def __post_init__(self) -> None:
        if not is_valid_udid(self.udid):
            raise ValueError(f"Invalid device identifier: {self.udid!r}")

    @property
    def label(self) -> str:
        return f"{self.name or 'iPhone'} ({self.connection.label})"

    def tool_args(self) -> list[str]:
        """Arguments that make ``ideviceinfo`` / ``ideviceinstaller`` use exactly this device.

        ``-n`` (network only) is added for Wi-Fi and NEVER for USB.
        """
        args = ["-u", self.udid]
        if self.connection is ConnectionType.WIFI:
            args.append("-n")
        return args

    def helper_args(self) -> list[str]:
        """Arguments for the icon / inventory helper processes (same device, same connection)."""
        return ["--udid", self.udid, "--connection", self.connection.value]


@dataclass(frozen=True)
class DiscoveredDevice:
    """One entry of the Apple service's device list."""

    udid: str
    connection: ConnectionType
    device_id: int = 0          # the service's own handle for this connection
    product_id: int = 0
    name: str = ""              # filled in later, only when the user has to choose between several

    def target(self) -> DeviceTarget:
        return DeviceTarget(self.udid, self.connection, self.name)

    @property
    def label(self) -> str:
        return f"{self.name or 'iPhone'}  ·  {self.connection.label}  ·  {short_udid(self.udid)}"


class DiscoveryError(Exception):
    """The Apple device service could not be asked (not running, refused, bad reply)."""


# ---------------------------------------------------------------------- parsing (mirrors libusbmuxd)
def normalize_udid(serial: str, device_id: int = 0) -> str:
    """The UDID exactly as libusbmuxd presents it to the tools (so ``-u`` matches).

    The service reports some UDIDs as 24 plain characters; libusbmuxd inserts a hyphen after the
    eighth. An all-'f' placeholder gets the device handle appended, as libusbmuxd does.
    """
    udid = serial
    if len(udid) == 24:
        udid = udid[:8] + "-" + udid[8:]
    if udid.lower() == "f" * 40:
        udid = udid[:32] + f"{device_id & 0xFFFFFFFF:08x}"
    return udid


def parse_device_list(reply: object) -> list[DiscoveredDevice]:
    """Devices from a ``ListDevices`` reply. Entries the tools could not use are skipped.

    This follows libusbmuxd: an entry needs a SerialNumber and a ConnectionType of "USB" or
    "Network"; a network entry also needs its NetworkAddress, otherwise the tools cannot connect.
    """
    if not isinstance(reply, dict) or not isinstance(reply.get("DeviceList"), list):
        raise DiscoveryError("The Apple device service sent a reply that could not be understood.")
    found: list[DiscoveredDevice] = []
    for entry in reply["DeviceList"]:
        props = entry.get("Properties") if isinstance(entry, dict) else None
        if not isinstance(props, dict):
            continue
        serial, kind = props.get("SerialNumber"), props.get("ConnectionType")
        device_id = props.get("DeviceID") if isinstance(props.get("DeviceID"), int) else 0
        if not isinstance(serial, str) or not serial:
            continue
        if kind == "USB":
            connection = ConnectionType.USB
        elif kind == "Network":
            address = props.get("NetworkAddress")
            if not isinstance(address, (bytes, bytearray)) or not address:
                continue
            connection = ConnectionType.WIFI
        else:
            continue
        udid = normalize_udid(serial, device_id)
        if not is_valid_udid(udid):
            continue
        product = props.get("ProductID") if isinstance(props.get("ProductID"), int) else 0
        found.append(DiscoveredDevice(udid, connection, device_id, product))
    return found


# ---------------------------------------------------------------------- talking to the service
def service_address(environ: Optional[dict] = None) -> tuple[str, int]:
    """Host and port of the Apple service. ``USBMUXD_SOCKET_ADDRESS`` ("host:port") overrides the
    default, exactly as it does for the libimobiledevice tools."""
    env = os.environ if environ is None else environ
    text = env.get("USBMUXD_SOCKET_ADDRESS", "")
    if text and not text.startswith("UNIX:"):
        host, sep, port = text.rpartition(":")
        if sep and port.isdigit() and 0 < int(port) < 65536 and host:
            return host.strip("[]"), int(port)
    return DEFAULT_SERVICE_ADDRESS


def _read_exact(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise DiscoveryError("The Apple device service closed the connection unexpectedly.")
        data += chunk
    return data


def query_device_list(address: Optional[tuple[str, int]] = None,
                      timeout: float = DISCOVERY_TIMEOUT_SECONDS,
                      connect: Callable[..., socket.socket] = socket.create_connection
                      ) -> list[DiscoveredDevice]:
    """Ask the Apple Mobile Device Service which iPhones it can reach, and how.

    Read-only. Raises DiscoveryError when the service is not running or does not answer.
    """
    host, port = address or service_address()
    body = plistlib.dumps({"MessageType": "ListDevices", "ClientVersionString": "iPhone App Manager",
                           "ProgName": "iPhone App Manager", "kLibUSBMuxVersion": 3})
    try:
        with connect((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(struct.pack("<IIII", 16 + len(body), 1, 8, 1) + body)   # version 1, plist, tag 1
            length, _version, _kind, _tag = struct.unpack("<IIII", _read_exact(sock, 16))
            if not 16 <= length <= 4 * 1024 * 1024:
                raise DiscoveryError("The Apple device service sent a reply of an unexpected size.")
            payload = _read_exact(sock, length - 16)
    except DiscoveryError:
        raise
    except socket.timeout as exc:
        raise DiscoveryError(f"The Apple device service did not answer within {timeout:.0f} seconds.") from exc
    except OSError as exc:
        raise DiscoveryError(f"Could not reach the Apple device service at {host}:{port} ({exc}).") from exc
    try:
        reply = plistlib.loads(payload)
    except Exception as exc:        # a malformed plist can raise several different exception types
        raise DiscoveryError(f"The Apple device service sent unreadable data ({exc}).") from exc
    return parse_device_list(reply)
