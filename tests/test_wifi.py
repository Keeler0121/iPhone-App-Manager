"""Tests for Wi-Fi support (USB or Wi-Fi, an explicit device for every command).

NOTHING here touches a real iPhone, the Apple device service or the network (apart from a throw-away
server on the loopback interface in the discovery test). Real-device Wi-Fi behaviour has NOT been
tested by these tests: they check the app's own logic against a fake that follows the device-selection
rules found in the libimobiledevice / ideviceinstaller source:

* a tool run without ``-n`` only considers USB devices;
* a tool run with ``-n`` only considers network (Wi-Fi) devices;
* without ``-u <UDID>`` a tool takes the first device of that kind.

Run with:  py -3.12 -m unittest discover -s tests -v
"""
from __future__ import annotations

import plistlib
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from iphone_app_manager import app_icons, app_inventory, config, icon_helper, inventory_helper  # noqa: E402
from iphone_app_manager.connection import (  # noqa: E402
    ConnectionType, DeviceTarget, DiscoveredDevice, DiscoveryError, normalize_udid, parse_device_list,
    query_device_list, service_address,
)
from iphone_app_manager.device import (  # noqa: E402
    DeviceError, DeviceService, ErrorKind, ToolResult, UninstallFailure, classify_failure,
)
from iphone_app_manager.models import AppInfo  # noqa: E402
from iphone_app_manager.uninstall import Outcome, run_uninstall_batch  # noqa: E402

UDID_A = "00008110-001234567890801E"
UDID_B = "00008101-000A1B2C3D4E5F67"
OK_UNINSTALL = b"Uninstall: RemovingApplication (50%)\nUninstall: Complete\n"
DISK = (b"TotalDiskCapacity: 128000000000\nAmountDataAvailable: 10000000000\n"
        b"TotalDataCapacity: 120000000000\nTotalSystemCapacity: 8000000000\n")


# ====================================================================== a fake fleet of iPhones
class Phone:
    def __init__(self, udid: str, name: str, apps: dict[str, str], usb: bool = True, wifi: bool = False,
                 wifi_sync: bool | None = False) -> None:
        self.udid, self.name, self.ios = udid, name, "26.1"
        self.apps = dict(apps)              # bundle id -> display name
        self.usb, self.wifi = usb, wifi
        # True / False: the iPhone explicitly reports EnableWifiConnections. None: it does not report the key at
        # all, exactly like the real iPhone this was observed on.
        self.wifi_sync = wifi_sync
        self.trusted = True
        self.install_service_ok = True


class FakeFleet:
    """Stands in for the Apple device service plus the two command-line tools."""

    def __init__(self, *phones: Phone) -> None:
        self.phones = list(phones)
        self.calls: list[tuple[str, list[str]]] = []
        self.service_down = False
        self.uninstalled: list[tuple[str, str]] = []          # (udid, bundle id)
        self.on_uninstall = None                                # callback(fleet, count) after each removal
        self._lock = threading.Lock()

    # the Apple device service's device list
    def listing(self) -> list[DiscoveredDevice]:
        if self.service_down:
            raise DiscoveryError("Could not reach the Apple device service.")
        found = []
        for i, p in enumerate(self.phones):
            if p.usb:
                found.append(DiscoveredDevice(p.udid, ConnectionType.USB, device_id=10 + i))
            if p.wifi:
                found.append(DiscoveredDevice(p.udid, ConnectionType.WIFI, device_id=20 + i))
        return found

    # ideviceinfo.exe / ideviceinstaller.exe
    def runner(self, exe, args, timeout) -> ToolResult:
        name, args = Path(exe).name, list(args)
        with self._lock:
            self.calls.append((name, args))
        udid = args[args.index("-u") + 1] if "-u" in args else None
        network = "-n" in args
        if udid is None:                       # tools without -u take the first device of that kind
            pool = [p for p in self.phones if (p.wifi if network else p.usb)]
            phone = pool[0] if pool else None
        else:
            phone = next((p for p in self.phones if p.udid == udid and (p.wifi if network else p.usb)), None)
        if phone is None or self.service_down:
            # the real wording of the bundled tools (checked against the real binaries)
            if name == "ideviceinfo.exe":
                text = f"ERROR: Device {udid} not found!\n" if udid else "ERROR: No device found!\n"
            else:
                text = f"No device found with udid {udid}.\n" if udid else "No device found.\n"
            return ToolResult(127, b"", text.encode())
        if name == "ideviceinfo.exe":
            if not phone.trusted and "-s" not in args:
                return ToolResult(255, b"", b"ERROR: Could not connect to lockdownd: Pairing dialog response pending (-19)\n")
            if "-q" in args and "com.apple.mobile.wireless_lockdown" in args:
                return ToolResult(0, wireless_lockdown_text(phone.wifi_sync), b"")
            if "-q" in args and "com.apple.disk_usage" in args:
                return ToolResult(0, DISK, b"")
            if "DeviceName" in args:
                return ToolResult(0, phone.name.encode() + b"\n", b"")
            if "ProductVersion" in args:
                return ToolResult(0, phone.ios.encode() + b"\n", b"")
            return ToolResult(1, b"", b"unexpected ideviceinfo query\n")
        # ideviceinstaller.exe
        if not phone.install_service_ok:
            return ToolResult(255, b"", b"ERROR: Could not start com.apple.mobile.installation_proxy service!\n")
        if "--list-apps" in args:
            data = [{"CFBundleIdentifier": b, "CFBundleDisplayName": n, "CFBundleShortVersionString": "1.0",
                     "ApplicationType": "User"} for b, n in phone.apps.items()]
            return ToolResult(0, plistlib.dumps(data, fmt=plistlib.FMT_XML), b"")
        if "--uninstall" in args:
            bundle_id = args[args.index("--uninstall") + 1]
            phone.apps.pop(bundle_id, None)
            self.uninstalled.append((phone.udid, bundle_id))
            if self.on_uninstall:
                self.on_uninstall(self, len(self.uninstalled))
            return ToolResult(0, OK_UNINSTALL, b"")
        return ToolResult(1, b"", b"unexpected ideviceinstaller command\n")

    def service(self, discoverer=True) -> DeviceService:
        return DeviceService(runner=self.runner, installer=Path("ideviceinstaller.exe"),
                             info_tool=Path("ideviceinfo.exe"), discoverer=self.listing if discoverer else None)

    def installer_calls(self):
        return [a for n, a in self.calls if n == "ideviceinstaller.exe"]

    def info_calls(self):
        return [a for n, a in self.calls if n == "ideviceinfo.exe"]


def wireless_lockdown_text(wifi_sync) -> bytes:
    """`ideviceinfo -q com.apple.mobile.wireless_lockdown` output. The first four lines are what a real iPhone
    reported (with Wi-Fi sync ticked in Apple Devices): no EnableWifiConnections key."""
    text = ("BonjourFullServiceName: aa:bb:cc:dd:ee:ff@fe80::a8bb:ccff:fedd:eeff-supportsRP-26._apple-mobdev2._tcp.local.\n"
            "EnableWifiDebugging: false\nSupportsWifi: true\nSupportsWifiSyncing: true\n")
    if wifi_sync is not None:
        text += f"EnableWifiConnections: {'true' if wifi_sync else 'false'}\n"
    return text.encode()


def apps_of(*ids: str) -> dict[str, str]:
    return {i: i.split(".")[-1].title() for i in ids}


def user_app(bid: str) -> AppInfo:
    return AppInfo(bundle_id=bid, name=bid.split(".")[-1].title(), version="1.0", app_type="User")


# ====================================================================== targets and discovery parsing
class TargetTests(unittest.TestCase):
    def test_usb_arguments_never_contain_the_network_flag(self):
        self.assertEqual(DeviceTarget(UDID_A, ConnectionType.USB).tool_args(), ["-u", UDID_A])
        self.assertNotIn("-n", DeviceTarget(UDID_A).tool_args())            # USB is the default connection

    def test_wifi_arguments_use_network_flag_and_the_device_id(self):
        args = DeviceTarget(UDID_A, ConnectionType.WIFI).tool_args()
        self.assertEqual(args, ["-u", UDID_A, "-n"])

    def test_helper_arguments_name_the_connection(self):
        self.assertEqual(DeviceTarget(UDID_A, ConnectionType.WIFI).helper_args(),
                         ["--udid", UDID_A, "--connection", "wifi"])
        self.assertEqual(DeviceTarget(UDID_A, ConnectionType.USB).helper_args(),
                         ["--udid", UDID_A, "--connection", "usb"])

    def test_a_device_id_can_never_look_like_an_option_or_contain_odd_characters(self):
        for bad in ("-n1234567890", "--udid", "abc", "", "zzzzzzzzzzzz", "0000 8110", UDID_A + ";calc"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    DeviceTarget(bad)

    def test_connection_labels(self):
        self.assertEqual((ConnectionType.USB.label, ConnectionType.WIFI.label), ("USB", "Wi-Fi"))


def entry(serial, kind, device_id=1, address=b"\x10\x02\x00\x00\xc0\xa8\x01\x05" + bytes(8)):
    props = {"SerialNumber": serial, "ConnectionType": kind, "DeviceID": device_id, "ProductID": 4776}
    if kind == "Network":
        props["NetworkAddress"] = address
    return {"MessageType": "Attached", "DeviceID": device_id, "Properties": props}


class ParseDeviceListTests(unittest.TestCase):
    def test_usb_and_network_entries(self):
        found = parse_device_list({"DeviceList": [entry(UDID_A, "USB", 1), entry(UDID_B, "Network", 2)]})
        self.assertEqual([(d.udid, d.connection) for d in found],
                         [(UDID_A, ConnectionType.USB), (UDID_B, ConnectionType.WIFI)])

    def test_same_iphone_over_both_connections_is_two_entries(self):
        found = parse_device_list({"DeviceList": [entry(UDID_A, "USB", 1), entry(UDID_A, "Network", 2)]})
        self.assertEqual({d.connection for d in found}, {ConnectionType.USB, ConnectionType.WIFI})

    def test_udid_is_normalised_like_libusbmuxd(self):
        self.assertEqual(normalize_udid("00008110001234567890801E"), "00008110-001234567890801E")
        found = parse_device_list({"DeviceList": [entry("00008110001234567890801E", "USB")]})
        self.assertEqual(found[0].udid, UDID_A)                                # so `-u` matches the tools' own view

    def test_entries_the_tools_could_not_use_are_skipped(self):
        reply = {"DeviceList": [
            entry(UDID_A, "Network", address=b""),             # network entry without an address
            entry(UDID_A, "Bluetooth"),                        # not a connection the tools know
            {"Properties": {"ConnectionType": "USB"}},         # no serial number
            {"Properties": "garbage"}, "garbage",
            entry(UDID_B, "USB")]}
        self.assertEqual([d.udid for d in parse_device_list(reply)], [UDID_B])

    def test_unreadable_reply(self):
        for bad in (None, "x", {}, {"DeviceList": "x"}):
            with self.assertRaises(DiscoveryError):
                parse_device_list(bad)

    def test_service_address_default_and_override(self):
        self.assertEqual(service_address({}), ("127.0.0.1", 27015))
        self.assertEqual(service_address({"USBMUXD_SOCKET_ADDRESS": "127.0.0.1:5555"}), ("127.0.0.1", 5555))
        self.assertEqual(service_address({"USBMUXD_SOCKET_ADDRESS": "UNIX:/var/run/usbmuxd"}), ("127.0.0.1", 27015))
        self.assertEqual(service_address({"USBMUXD_SOCKET_ADDRESS": "nonsense"}), ("127.0.0.1", 27015))


class QueryDeviceListTests(unittest.TestCase):
    """The real socket code, against a throw-away server on the loopback interface."""

    def serve(self, reply_bytes=None, header_length=None, hang=False):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        self.addCleanup(server.close)
        seen = {}

        def run():
            conn, _ = server.accept()
            with conn:
                head = conn.recv(16)
                length, version, kind, tag = struct.unpack("<IIII", head)
                body = b""
                while len(body) < length - 16:
                    body += conn.recv(length - 16 - len(body))
                seen.update(version=version, kind=kind, message=plistlib.loads(body))
                if hang:
                    time.sleep(2)
                    return
                payload = reply_bytes
                conn.sendall(struct.pack("<IIII", header_length or 16 + len(payload), 1, 8, tag) + payload)
        threading.Thread(target=run, daemon=True).start()
        return server.getsockname(), seen

    def test_reads_devices_and_sends_a_read_only_list_request(self):
        reply = plistlib.dumps({"DeviceList": [entry(UDID_A, "USB", 1), entry(UDID_B, "Network", 2)]})
        address, seen = self.serve(reply)
        found = query_device_list(address, timeout=3)
        self.assertEqual([(d.udid, d.connection) for d in found],
                         [(UDID_A, ConnectionType.USB), (UDID_B, ConnectionType.WIFI)])
        self.assertEqual(seen["message"]["MessageType"], "ListDevices")      # the only request ever sent
        self.assertEqual((seen["version"], seen["kind"]), (1, 8))

    def test_service_not_running(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        address = probe.getsockname()
        probe.close()                                                          # nothing is listening there now
        with self.assertRaises(DiscoveryError):
            query_device_list(address, timeout=1)

    def test_no_answer(self):
        address, _ = self.serve(hang=True)
        with self.assertRaises(DiscoveryError) as ctx:
            query_device_list(address, timeout=0.3)
        self.assertIn("did not answer", str(ctx.exception))

    def test_garbage_and_oversized_replies(self):
        address, _ = self.serve(b"not a plist")
        with self.assertRaises(DiscoveryError):
            query_device_list(address, timeout=2)
        address, _ = self.serve(plistlib.dumps({"DeviceList": []}), header_length=900_000_000)
        with self.assertRaises(DiscoveryError):
            query_device_list(address, timeout=2)


# ====================================================================== the service: USB
class UsbServiceTests(unittest.TestCase):
    def test_usb_is_the_default_connection(self):
        self.assertIs(DeviceService().connection, ConnectionType.USB)

    def test_usb_detection_and_snapshot(self):
        fleet = FakeFleet(Phone(UDID_A, "Sam's phone", apps_of("com.a.one", "com.a.two")))
        service = fleet.service()
        device, apps = service.load_snapshot()
        self.assertEqual((device.name, device.ios_version), ("Sam's phone", "26.1"))
        self.assertEqual(sorted(a.bundle_id for a in apps), ["com.a.one", "com.a.two"])
        self.assertEqual(service.target, DeviceTarget(UDID_A, ConnectionType.USB, "Sam's phone"))

    def test_every_usb_command_names_the_device_and_never_gets_the_network_flag(self):
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.a.one")))
        service = fleet.service()
        service.load_snapshot()
        service.uninstall_app("com.a.one")
        self.assertTrue(fleet.calls)
        for name, args in fleet.calls:
            with self.subTest(name=name, args=args):
                self.assertEqual(args[:2], ["-u", UDID_A])
                self.assertNotIn("-n", args)

    def test_usb_mode_ignores_wifi_only_iphones(self):
        fleet = FakeFleet(Phone(UDID_A, "A", {}, usb=False, wifi=True))
        with self.assertRaises(DeviceError) as ctx:
            fleet.service().load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.NO_DEVICE)
        self.assertEqual(fleet.installer_calls(), [])                     # nothing was sent to the iPhone

    def test_service_without_discovery_behaves_exactly_as_before(self):
        """No discoverer: no -u, no -n, original USB-only command lines."""
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.a.one")))
        service = fleet.service(discoverer=False)
        service.load_snapshot()
        service.uninstall_app("com.a.one")
        self.assertEqual(fleet.installer_calls(), [["--list-apps", "-o", "xml"], ["--uninstall", "com.a.one"]])
        self.assertEqual(fleet.info_calls(), [["-k", "DeviceName"], ["-k", "ProductVersion"],
                                              ["-q", "com.apple.disk_usage"]])
        self.assertIsNone(service.target)

    def test_service_without_discovery_cannot_do_wifi(self):
        service = FakeFleet().service(discoverer=False)
        service.set_connection(ConnectionType.WIFI)
        with self.assertRaises(DeviceError) as ctx:
            service.load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.SERVICE_UNAVAILABLE)


# ====================================================================== the service: Wi-Fi
class WifiServiceTests(unittest.TestCase):
    def wifi_service(self, fleet):
        service = fleet.service()
        service.set_connection(ConnectionType.WIFI)
        return service

    def test_wifi_detection_and_snapshot(self):
        fleet = FakeFleet(Phone(UDID_A, "Wireless phone", apps_of("com.w.one"), usb=False, wifi=True))
        service = self.wifi_service(fleet)
        device, apps = service.load_snapshot()
        self.assertEqual(device.name, "Wireless phone")
        self.assertEqual([a.bundle_id for a in apps], ["com.w.one"])
        self.assertEqual(service.target.connection, ConnectionType.WIFI)

    def test_every_wifi_command_uses_the_network_flag_and_the_device_id(self):
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.w.one"), usb=False, wifi=True))
        service = self.wifi_service(fleet)
        service.load_snapshot()
        service.uninstall_app("com.w.one")
        for name, args in fleet.calls:
            with self.subTest(name=name, args=args):
                self.assertEqual(args[:3], ["-u", UDID_A, "-n"])

    def test_wifi_mode_never_falls_back_to_usb_for_the_same_iphone(self):
        """An iPhone that is on USB only is not 'available over Wi-Fi': nothing is sent over USB."""
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.a.one"), usb=True, wifi=False, wifi_sync=True))
        service = self.wifi_service(fleet)
        with self.assertRaises(DeviceError) as ctx:
            service.load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.NO_DEVICE)
        self.assertIs(ctx.exception.connection, ConnectionType.WIFI)
        self.assertEqual(fleet.installer_calls(), [])
        for _name, args in fleet.calls:
            self.assertNotIn("--list-apps", args)

    def test_iphone_on_both_connections_is_used_over_wifi_when_wifi_is_chosen(self):
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.a.one"), usb=True, wifi=True))
        service = self.wifi_service(fleet)
        service.load_snapshot()
        self.assertTrue(all("-n" in args for _n, args in fleet.calls))

    def test_switching_connection_forgets_the_chosen_iphone(self):
        fleet = FakeFleet(Phone(UDID_A, "A", {}, usb=True, wifi=True))
        service = fleet.service()
        service.load_snapshot()
        service.set_connection(ConnectionType.WIFI)
        self.assertIsNone(service.target)
        service.load_snapshot()
        self.assertEqual(service.target.connection, ConnectionType.WIFI)

    def test_wifi_sync_known_to_be_off(self):
        """Wi-Fi mode, nothing on the network, but an iPhone on USB reports Wi-Fi sync is off."""
        fleet = FakeFleet(Phone(UDID_A, "A", {}, usb=True, wifi=False, wifi_sync=False))
        with self.assertRaises(DeviceError) as ctx:
            self.wifi_service(fleet).load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.WIFI_SYNC_OFF)
        self.assertIn("Show this iPhone when on Wi-Fi", ctx.exception.message)

    def test_wifi_sync_state_is_not_reported_so_the_generic_message_is_used(self):
        """The real iPhone case: no EnableWifiConnections key. 'Sync is off' must NOT be claimed."""
        fleet = FakeFleet(Phone(UDID_A, "A", {}, usb=True, wifi=False, wifi_sync=None))
        with self.assertRaises(DeviceError) as ctx:
            self.wifi_service(fleet).load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.NO_DEVICE)
        self.assertIsNot(ctx.exception.kind, ErrorKind.WIFI_SYNC_OFF)
        self.assertIs(ctx.exception.connection, ConnectionType.WIFI)
        text = ctx.exception.title + " " + ctx.exception.message
        self.assertIn("un-ticks itself", text)                      # the observed 'box resets' problem is mentioned
        self.assertIn("same Wi-Fi network", text)

    def test_sync_off_needs_every_plugged_in_iphone_to_report_it(self):
        """One iPhone says off, another does not say: that is not confirmed, so the generic message."""
        fleet = FakeFleet(Phone(UDID_A, "A", {}, usb=True, wifi_sync=False),
                          Phone(UDID_B, "B", {}, usb=True, wifi_sync=None))
        with self.assertRaises(DeviceError) as ctx:
            self.wifi_service(fleet).resolve_target()
        self.assertIs(ctx.exception.kind, ErrorKind.NO_DEVICE)
        both_off = FakeFleet(Phone(UDID_A, "A", {}, usb=True, wifi_sync=False),
                             Phone(UDID_B, "B", {}, usb=True, wifi_sync=False))
        with self.assertRaises(DeviceError) as ctx2:
            self.wifi_service(both_off).resolve_target()
        self.assertIs(ctx2.exception.kind, ErrorKind.WIFI_SYNC_OFF)

    def test_unreadable_wifi_setting_is_unknown_not_off(self):
        fleet = FakeFleet(Phone(UDID_A, "A", {}, usb=True, wifi_sync=False))
        real_runner = fleet.runner

        def failing(exe, args, timeout):
            if "com.apple.mobile.wireless_lockdown" in args:
                return ToolResult(255, b"", b"ERROR: Could not connect to lockdownd\n")
            return real_runner(exe, args, timeout)
        service = DeviceService(runner=failing, installer=Path("ideviceinstaller.exe"),
                                info_tool=Path("ideviceinfo.exe"), discoverer=fleet.listing)
        service.set_connection(ConnectionType.WIFI)
        with self.assertRaises(DeviceError) as ctx:
            service.resolve_target()
        self.assertIs(ctx.exception.kind, ErrorKind.NO_DEVICE)

    def test_wifi_sync_setting_is_read_from_the_whole_domain(self):
        fleet = FakeFleet(Phone(UDID_A, "A", {}, usb=True, wifi_sync=False))
        with self.assertRaises(DeviceError):
            self.wifi_service(fleet).resolve_target()
        queries = [a for a in fleet.info_calls() if "com.apple.mobile.wireless_lockdown" in a]
        self.assertEqual(queries, [["-u", UDID_A, "-q", "com.apple.mobile.wireless_lockdown"]])   # USB: no -n

    def test_wifi_sync_on_but_iphone_not_on_the_network(self):
        fleet = FakeFleet(Phone(UDID_A, "A", {}, usb=True, wifi=False, wifi_sync=True))
        with self.assertRaises(DeviceError) as ctx:
            self.wifi_service(fleet).load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.NO_DEVICE)
        self.assertIn("same Wi-Fi network", ctx.exception.message)

    def test_nothing_visible_at_all_explains_both_possibilities(self):
        with self.assertRaises(DeviceError) as ctx:
            self.wifi_service(FakeFleet()).load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.NO_DEVICE)
        text = ctx.exception.title + " " + ctx.exception.message
        self.assertIn("Wi-Fi sync", text)
        self.assertIn("same Wi-Fi network", text)

    def test_apple_service_unavailable(self):
        fleet = FakeFleet(Phone(UDID_A, "A", {}, usb=False, wifi=True))
        fleet.service_down = True
        for connection in (ConnectionType.USB, ConnectionType.WIFI):
            service = fleet.service()
            service.set_connection(connection)
            with self.subTest(connection=connection):
                with self.assertRaises(DeviceError) as ctx:
                    service.load_snapshot()
                self.assertIs(ctx.exception.kind, ErrorKind.SERVICE_UNAVAILABLE)
                self.assertIn("Apple Devices", ctx.exception.message)

    def test_pairing_or_trust_required_is_reported_with_wifi_specific_advice(self):
        phone = Phone(UDID_A, "A", {}, usb=False, wifi=True)
        phone.trusted = False
        service = self.wifi_service(FakeFleet(phone))
        with self.assertRaises(DeviceError) as ctx:
            service.load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.NOT_TRUSTED)
        self.assertIn("USB", ctx.exception.message)                       # trust can only be given over USB

    def test_usb_trust_message_is_unchanged(self):
        phone = Phone(UDID_A, "A", {})
        phone.trusted = False
        with self.assertRaises(DeviceError) as ctx:
            FakeFleet(phone).service().load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.NOT_TRUSTED)
        self.assertIn("Trust This Computer", ctx.exception.message)

    def test_installation_service_unavailable(self):
        phone = Phone(UDID_A, "A", apps_of("com.a.one"))
        phone.install_service_ok = False
        service = FakeFleet(phone).service()
        with self.assertRaises(DeviceError) as ctx:
            service.load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.INSTALL_SERVICE)
        with self.assertRaises(UninstallFailure) as ctx2:
            service.uninstall_app("com.a.one")
        self.assertIs(ctx2.exception.fatal_kind, ErrorKind.INSTALL_SERVICE)
        self.assertIn("installation service", ctx2.exception.message)

    def test_classify_the_real_device_not_found_messages(self):
        """Text printed by the real ideviceinfo / ideviceinstaller when the named device is missing."""
        for text in ("ERROR: No device found!", "No device found.", f"No device found with udid {UDID_A}.",
                     f"ERROR: Device {UDID_A} not found!", "ERROR: Device 00008110001234567890801E not found!"):
            with self.subTest(text=text):
                self.assertIs(classify_failure(text), ErrorKind.NO_DEVICE)

    def test_classify_installation_proxy_failure(self):
        self.assertIs(classify_failure("ERROR: Could not start com.apple.mobile.installation_proxy service!"),
                      ErrorKind.INSTALL_SERVICE)
        self.assertIs(classify_failure("No device found."), ErrorKind.NO_DEVICE)         # unchanged


# ====================================================================== choosing between several iPhones
class WifiSyncParsingTests(unittest.TestCase):
    def test_only_an_explicit_value_counts(self):
        from iphone_app_manager.device import parse_wifi_sync_state
        real = wireless_lockdown_text(None).decode()                      # what a real iPhone reported
        self.assertIsNone(parse_wifi_sync_state(real))
        self.assertIs(parse_wifi_sync_state(real + "EnableWifiConnections: false\n"), False)
        self.assertIs(parse_wifi_sync_state(real + "EnableWifiConnections: true\n"), True)
        self.assertIs(parse_wifi_sync_state("EnableWifiConnections: TRUE\r\n"), True)
        for unknown in ("", "\n", "true\n", "false\n", "1\n", "EnableWifiDebugging: false\n",
                        "SupportsWifiSyncing: false\n", "EnableWifiConnections: maybe\n",
                        "XEnableWifiConnections: false\n", "ERROR: Could not connect to lockdownd\n"):
            with self.subTest(text=unknown):
                self.assertIsNone(parse_wifi_sync_state(unknown))


class MultipleDeviceTests(unittest.TestCase):
    def two_usb(self):
        return FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one")), Phone(UDID_B, "Bravo", apps_of("com.b.one")))

    def test_two_iphones_are_never_guessed(self):
        fleet = self.two_usb()
        service = fleet.service()
        with self.assertRaises(DeviceError) as ctx:
            service.load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.MULTIPLE_DEVICES)
        self.assertEqual([d.udid for d in ctx.exception.candidates], [UDID_A, UDID_B])
        self.assertEqual([d.name for d in ctx.exception.candidates], ["Alpha", "Bravo"])
        self.assertEqual(fleet.installer_calls(), [])            # no app list was read from either phone
        self.assertIsNone(service.target)

    def test_choosing_an_iphone_targets_exactly_that_one(self):
        fleet = self.two_usb()
        service = fleet.service()
        service.choose_device(UDID_B)
        device, apps = service.load_snapshot()
        self.assertEqual((device.name, [a.bundle_id for a in apps]), ("Bravo", ["com.b.one"]))
        service.uninstall_app("com.b.one")
        self.assertEqual(fleet.uninstalled, [(UDID_B, "com.b.one")])
        for args in fleet.installer_calls():
            self.assertEqual(args[:2], ["-u", UDID_B])
        # nothing except the two 'simple' name lookups ever mentioned the other iPhone
        self.assertTrue(all(UDID_A not in " ".join(a) for a in fleet.installer_calls()))
        self.assertTrue(all(UDID_A not in " ".join(a) for a in fleet.info_calls() if "-s" not in a))

    def test_a_single_iphone_is_selected_automatically_and_remembered(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one")))
        service = fleet.service()
        service.load_snapshot()
        fleet.phones.append(Phone(UDID_B, "Bravo", apps_of("com.b.one")))      # a second iPhone is plugged in
        _device, apps = service.load_snapshot()
        self.assertEqual([a.bundle_id for a in apps], ["com.a.one"])            # still the first one: no surprise switch
        self.assertEqual(service.target.udid, UDID_A)

    def test_if_the_chosen_iphone_leaves_another_is_not_used_silently(self):
        fleet = self.two_usb()
        service = fleet.service()
        service.choose_device(UDID_A)
        service.load_snapshot()
        fleet.phones[0].usb = False                                              # Alpha unplugged, Bravo still there
        calls_before = len(fleet.installer_calls())
        with self.assertRaises(DeviceError) as ctx:
            service.load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.MULTIPLE_DEVICES)
        self.assertIn("isn't available any more", ctx.exception.details)
        self.assertEqual([d.udid for d in ctx.exception.candidates], [UDID_B])
        self.assertEqual(len(fleet.installer_calls()), calls_before)             # nothing was read from Bravo

    def test_wifi_choice_between_two_wireless_iphones(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one"), usb=False, wifi=True),
                          Phone(UDID_B, "Bravo", apps_of("com.b.one"), usb=False, wifi=True))
        service = fleet.service()
        service.set_connection(ConnectionType.WIFI)
        with self.assertRaises(DeviceError) as ctx:
            service.load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.MULTIPLE_DEVICES)
        self.assertTrue(all(d.connection is ConnectionType.WIFI for d in ctx.exception.candidates))
        # names were read with a "simple" (non-pairing) connection, still bound to that iPhone and to Wi-Fi
        for args in fleet.info_calls():
            self.assertIn("-n", args)
            self.assertIn("-s", args)
        service.choose_device(UDID_A)
        service.load_snapshot()
        self.assertEqual(service.target.udid, UDID_A)

    def test_candidates_are_labelled_with_name_connection_and_end_of_id(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", {}, usb=False, wifi=True), Phone(UDID_B, "Bravo", {}, usb=False, wifi=True))
        service = fleet.service()
        service.set_connection(ConnectionType.WIFI)
        with self.assertRaises(DeviceError) as ctx:
            service.resolve_target()
        label = ctx.exception.candidates[0].label
        self.assertIn("Alpha", label)
        self.assertIn("Wi-Fi", label)
        self.assertIn(UDID_A[-6:], label)


# ====================================================================== operations on the chosen iPhone
class OperationTests(unittest.TestCase):
    def test_app_listing_over_wifi(self):
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.w.one", "com.w.two"), usb=False, wifi=True))
        service = fleet.service()
        service.set_connection(ConnectionType.WIFI)
        service.resolve_target()
        self.assertEqual(sorted(a.bundle_id for a in service.list_apps()), ["com.w.one", "com.w.two"])
        self.assertEqual(fleet.installer_calls(), [["-u", UDID_A, "-n", "--list-apps", "-o", "xml"]])

    def test_individual_removal_over_wifi(self):
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.w.one", "com.w.two"), usb=False, wifi=True))
        service = fleet.service()
        service.set_connection(ConnectionType.WIFI)
        service.resolve_target()
        service.uninstall_app("com.w.one")
        self.assertEqual(fleet.installer_calls(), [["-u", UDID_A, "-n", "--uninstall", "com.w.one"]])
        self.assertEqual(fleet.uninstalled, [(UDID_A, "com.w.one")])

    def test_bulk_removal_is_sequential_and_stays_on_the_chosen_iphone(self):
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.a.one", "com.a.two", "com.a.three"), usb=False, wifi=True),
                          Phone(UDID_B, "B", apps_of("com.a.one", "com.b.two"), usb=False, wifi=True))
        service = fleet.service()
        service.set_connection(ConnectionType.WIFI)
        service.choose_device(UDID_A)
        _device, apps = service.load_snapshot()
        results = run_uninstall_batch(service, apps, lambda *_a: None)
        self.assertTrue(all(r.outcome is Outcome.REMOVED for r in results))
        self.assertEqual({u for u, _b in fleet.uninstalled}, {UDID_A})            # the other iPhone was never touched
        self.assertEqual(len(fleet.uninstalled), 3)
        for args in fleet.installer_calls():
            self.assertEqual(args[:3], ["-u", UDID_A, "-n"])
        self.assertIn("com.a.one", fleet.phones[1].apps)                           # same bundle id on the other iPhone survives

    def test_post_removal_verification_uses_the_same_iphone_and_connection(self):
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.a.one", "com.a.two"), usb=True, wifi=True),
                          Phone(UDID_B, "B", apps_of("com.a.one"), usb=True, wifi=True))
        service = fleet.service()
        service.set_connection(ConnectionType.WIFI)
        service.choose_device(UDID_A)
        service.load_snapshot()
        service.uninstall_app("com.a.one")
        before = len(fleet.calls)
        _device, apps_after = service.load_snapshot()                              # what the UI does to verify
        self.assertEqual([a.bundle_id for a in apps_after], ["com.a.two"])
        for name, args in fleet.calls[before:]:
            with self.subTest(name=name, args=args):
                self.assertEqual(args[:3], ["-u", UDID_A, "-n"])                   # same iPhone, still Wi-Fi

    def test_wifi_disconnection_during_a_batch_stops_safely(self):
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.a.one", "com.a.two", "com.a.three"), usb=False, wifi=True))

        def drop_after_first(f, count):
            if count == 1:
                f.phones[0].wifi = False                                            # the iPhone leaves the network
        fleet.on_uninstall = drop_after_first
        service = fleet.service()
        service.set_connection(ConnectionType.WIFI)
        _device, apps = service.load_snapshot()
        results = run_uninstall_batch(service, apps, lambda *_a: None)
        outcomes = [r.outcome for r in results]
        self.assertEqual(outcomes[0], Outcome.REMOVED)
        self.assertEqual(outcomes[1], Outcome.FAILED)
        self.assertEqual(outcomes[2], Outcome.NOT_ATTEMPTED)                        # nothing further is attempted
        self.assertEqual(len(fleet.uninstalled), 1)
        self.assertIn("Wi-Fi", results[1].message)
        self.assertNotIn("USB cable", results[1].message)

    def test_loss_message_when_the_apple_service_itself_stops(self):
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.a.one"), usb=False, wifi=True))
        service = fleet.service()
        service.set_connection(ConnectionType.WIFI)
        service.load_snapshot()
        fleet.service_down = True
        with self.assertRaises(UninstallFailure) as ctx:
            service.uninstall_app("com.a.one")
        self.assertIs(ctx.exception.fatal_kind, ErrorKind.SERVICE_UNAVAILABLE)

    def test_loss_message_says_when_the_iphone_is_only_on_the_other_connection(self):
        fleet = FakeFleet(Phone(UDID_A, "A", apps_of("com.a.one"), usb=False, wifi=True))
        service = fleet.service()
        service.set_connection(ConnectionType.WIFI)
        service.load_snapshot()
        fleet.phones[0].wifi, fleet.phones[0].usb = False, True                     # now cabled instead
        with self.assertRaises(UninstallFailure) as ctx:
            service.uninstall_app("com.a.one")
        self.assertIn("available over USB", ctx.exception.message)
        self.assertEqual(fleet.uninstalled, [])                                      # and nothing was sent over USB

    def test_invalid_bundle_ids_are_still_rejected(self):
        service = FakeFleet(Phone(UDID_A, "A", {})).service()
        service.resolve_target()
        for bad in ("-n", "--udid", "", "a b", "x;y"):
            with self.assertRaises(UninstallFailure):
                service.uninstall_app(bad)


# ====================================================================== helper processes
class HelperCommandTests(unittest.TestCase):
    wifi = DeviceTarget(UDID_A, ConnectionType.WIFI)
    usb = DeviceTarget(UDID_A, ConnectionType.USB)

    def test_without_a_target_the_commands_are_unchanged(self):
        self.assertEqual(app_icons.helper_command(64, frozen=False)[-2:], [str(config.LIBIMOBILEDEVICE_BIN), "64"])
        self.assertEqual(app_inventory.helper_command(frozen=False)[-1], str(config.LIBIMOBILEDEVICE_BIN))
        self.assertEqual(app_icons.helper_command(64, frozen=True)[-3:],
                         [app_icons.ICON_HELPER_FLAG, str(config.LIBIMOBILEDEVICE_BIN), "64"][-3:])

    def test_target_is_appended_for_both_helpers_and_both_modes(self):
        for frozen in (False, True):
            self.assertEqual(app_icons.helper_command(64, frozen, target=self.wifi)[-4:],
                             ["--udid", UDID_A, "--connection", "wifi"])
            self.assertEqual(app_inventory.helper_command(frozen, target=self.usb)[-4:],
                             ["--udid", UDID_A, "--connection", "usb"])

    def test_fetchers_pass_the_target_to_the_helper_process(self):
        captured = []

        def fake_popen(cmd, **_kw):
            captured.append(cmd)
            raise OSError("not starting a real helper in a test")
        with mock.patch.object(app_icons.subprocess, "Popen", fake_popen):
            app_icons.fetch_icons(["com.a.one"], 32, lambda *_: None, threading.Event(), target=self.wifi)
        with mock.patch.object(app_inventory.subprocess, "Popen", fake_popen):
            app_inventory.fetch_inventory(lambda _a: None, lambda _s: None, threading.Event(), target=self.wifi)
        self.assertEqual(len(captured), 2)
        for cmd in captured:
            self.assertEqual(cmd[-4:], ["--udid", UDID_A, "--connection", "wifi"])

    def test_exit_message_for_an_unreachable_wifi_iphone(self):
        self.assertEqual(app_icons.exit_message(2, self.wifi, "x"), "iPhone not reachable over Wi-Fi")
        self.assertEqual(app_icons.exit_message(2, self.usb, "x"), "iPhone not connected")
        self.assertEqual(app_icons.exit_message(2, None, "x"), "iPhone not connected")
        self.assertEqual(app_icons.exit_message(None, None, "stopped"), "stopped")

    def test_argument_parsing_in_both_helpers(self):
        for module in (icon_helper, inventory_helper):
            with self.subTest(module=module.__name__):
                self.assertEqual(module.parse_target([]), (None, module.LOOKUP_USBMUX))
                self.assertEqual(module.parse_target(["--udid", UDID_A, "--connection", "usb"]),
                                 (UDID_A, module.LOOKUP_USBMUX))
                self.assertEqual(module.parse_target(["--udid", UDID_A, "--connection", "wifi"]),
                                 (UDID_A, module.LOOKUP_NETWORK))
                for bad in (["--connection", "wifi"], ["--udid", "-n12345678"], ["--udid", "short"],
                            ["--udid", UDID_A, "--connection", "bluetooth"], ["--bogus"], ["--udid"]):
                    with self.assertRaises(ValueError, msg=str(bad)):
                        module.parse_target(bad)

    def test_usb_and_network_lookups_are_never_combined(self):
        """A helper must look at ONE kind of device, so it cannot end up on the other connection."""
        self.assertEqual(icon_helper.LOOKUP_USBMUX, 2)
        self.assertEqual(icon_helper.LOOKUP_NETWORK, 4)
        for name in ("icon_helper.py", "inventory_helper.py"):
            source = (ROOT / "iphone_app_manager" / name).read_text(encoding="utf-8")
            self.assertNotRegex(source, r"LOOKUP_USBMUX\s*\|\s*LOOKUP_NETWORK")
            self.assertNotRegex(source, r"LOOKUP_NETWORK\s*\|\s*LOOKUP_USBMUX")
            self.assertNotIn("PREFER_NETWORK", source)

    def test_helpers_refuse_bad_arguments_before_touching_any_device(self):
        for script, base in (("icon_helper.py", ["bin", "32"]), ("inventory_helper.py", ["bin"])):
            for extra in (["--connection", "wifi"], ["--udid", "-n12345678"], ["--bogus"]):
                proc = subprocess.run([sys.executable, "-I", str(ROOT / "iphone_app_manager" / script), *base, *extra],
                                      capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
                with self.subTest(script=script, extra=extra):
                    self.assertEqual(proc.returncode, 1)
                    self.assertIn(b"icon_helper.py" if "icon" in script else b"inventory_helper.py", proc.stderr)


# ====================================================================== the window
def _recording_fetchers(test: unittest.TestCase, seen: dict):
    from test_uninstall import fake_fetch_icons, fake_fetch_inventory

    def icons(ids, size, on_icon, cancel, **kw):
        seen.setdefault("icons", []).append(kw.get("target"))
        return fake_fetch_icons(ids, size, on_icon, cancel, **kw)

    def inventory(on_offloaded, on_sizes, cancel, **kw):
        seen.setdefault("inventory", []).append(kw.get("target"))
        return fake_fetch_inventory(on_offloaded, on_sizes, cancel, **kw)
    for target, replacement in (("iphone_app_manager.ui.main_window.fetch_icons", icons),
                                ("iphone_app_manager.ui.main_window.fetch_inventory", inventory)):
        patcher = mock.patch(target, replacement)
        patcher.start()
        test.addCleanup(patcher.stop)


class WindowTests(unittest.TestCase):
    def build(self, fleet: FakeFleet):
        from test_uninstall import isolate_from_device
        from iphone_app_manager.ui import MainWindow
        isolate_from_device(self)
        self.seen: dict = {}
        _recording_fetchers(self, self.seen)
        self.fleet = fleet
        self.service = fleet.service()
        self.root = tk.Tk()
        self.w = MainWindow(self.root, self.service)
        self.addCleanup(self.close)
        # the window starts its first refresh shortly after it is created
        self.wait_for(lambda: self.w.device is not None or self.w.error is not None)
        self.settle()
        return self.w

    def close(self):
        if getattr(self, "w", None) is not None:
            self.w.uninstalling = False
            if self.w.picker_dialog is not None:
                self.w.picker_dialog.close()
            self.w._on_close()
            self.w = None

    def settle(self, timeout=15.0):
        end = time.monotonic() + timeout
        while self.w.loading or self.w.icon_fetching or self.w.inventory_running:
            if time.monotonic() > end:
                self.fail("timed out waiting for the window to settle")
            self.root.update()
            time.sleep(0.01)
        self.root.update()

    def wait_for(self, condition, timeout=15.0):
        end = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > end:
                self.fail("timed out waiting for a UI condition")
            self.root.update()
            time.sleep(0.01)
        self.root.update()

    def select_connection(self, connection):
        self.w.connection_selector.select(connection)
        self.settle()

    # ---------------------------------------------------------------- selector and status
    def test_usb_is_the_default_and_is_shown(self):
        self.build(FakeFleet(Phone(UDID_A, "Test phone", apps_of("com.a.one"))))
        self.assertIs(self.w.connection_selector.value, ConnectionType.USB)
        self.assertIs(self.service.connection, ConnectionType.USB)
        self.assertIn("Test phone", self.w.status_detail.cget("text"))
        self.assertIn("USB", self.w.status_detail.cget("text"))
        self.assertEqual(self.w.status_pill._spec["text"], "Connected")
        self.assertEqual([a.bundle_id for a in self.w.apps], ["com.a.one"])

    def test_helpers_receive_the_usb_target(self):
        self.build(FakeFleet(Phone(UDID_A, "Test phone", apps_of("com.a.one"))))
        expected = DeviceTarget(UDID_A, ConnectionType.USB, "Test phone")
        self.assertEqual(self.seen["icons"][-1], expected)
        self.assertEqual(self.seen["inventory"][-1], expected)

    def test_switching_to_wifi_loads_the_iphone_over_wifi(self):
        self.build(FakeFleet(Phone(UDID_A, "Test phone", apps_of("com.a.one", "com.a.two"), usb=True, wifi=True)))
        self.select_connection(ConnectionType.WIFI)
        self.assertIs(self.service.connection, ConnectionType.WIFI)
        self.assertIs(self.w.connection_selector.value, ConnectionType.WIFI)
        self.assertIn("Wi-Fi", self.w.status_detail.cget("text"))
        self.assertEqual(self.w.target.connection, ConnectionType.WIFI)
        self.assertEqual(self.seen["icons"][-1].connection, ConnectionType.WIFI)         # helpers follow
        self.assertEqual(self.seen["inventory"][-1].connection, ConnectionType.WIFI)
        self.assertEqual(sorted(a.bundle_id for a in self.w.apps), ["com.a.one", "com.a.two"])

    def test_switching_back_to_usb(self):
        self.build(FakeFleet(Phone(UDID_A, "Test phone", apps_of("com.a.one"), usb=True, wifi=True)))
        self.select_connection(ConnectionType.WIFI)
        self.select_connection(ConnectionType.USB)
        self.assertIn("USB", self.w.status_detail.cget("text"))
        self.assertEqual(self.w.target.connection, ConnectionType.USB)

    def test_wifi_not_available_message(self):
        self.build(FakeFleet(Phone(UDID_A, "Test phone", apps_of("com.a.one"), usb=True, wifi=False, wifi_sync=False)))
        self.select_connection(ConnectionType.WIFI)
        self.assertIsNotNone(self.w.error)
        self.assertIs(self.w.error.kind, ErrorKind.WIFI_SYNC_OFF)
        self.assertEqual(self.w.status_pill._spec["text"], "Wi-Fi sync off")
        self.assertEqual(self.w.apps, [])                                                    # nothing from USB shown
        self.assertEqual(self.w.overlay_title.cget("text"), "Wi-Fi sync isn't turned on for this iPhone")
        self.assertIn("Show this iPhone when on Wi-Fi", self.w.overlay_message.cget("text"))

    def test_iphone_unreachable_message_and_retry(self):
        fleet = FakeFleet(Phone(UDID_A, "Test phone", apps_of("com.a.one"), usb=False, wifi=False))
        self.build(fleet)
        self.select_connection(ConnectionType.WIFI)
        self.assertIs(self.w.error.kind, ErrorKind.NO_DEVICE)
        self.assertEqual(self.w.overlay_title.cget("text"), "iPhone not available over Wi-Fi")
        self.assertEqual(self.w.overlay_button._text, "Try again")                          # retry is offered
        fleet.phones[0].wifi = True                                                          # the iPhone joins the network
        self.w.refresh()
        self.settle()
        self.assertIsNone(self.w.error)
        self.assertEqual([a.bundle_id for a in self.w.apps], ["com.a.one"])

    def test_usb_no_device_message_is_unchanged(self):
        self.build(FakeFleet())
        self.assertIs(self.w.error.kind, ErrorKind.NO_DEVICE)
        self.assertEqual(self.w.overlay_title.cget("text"), "No iPhone connected")
        self.assertIn("USB cable", self.w.overlay_message.cget("text"))
        self.assertEqual(self.w.status_pill._spec["text"], "Not connected")

    def test_apple_service_unavailable_message(self):
        fleet = FakeFleet(Phone(UDID_A, "Test phone", apps_of("com.a.one")))
        fleet.service_down = True
        self.build(fleet)
        self.assertIs(self.w.error.kind, ErrorKind.SERVICE_UNAVAILABLE)
        self.assertEqual(self.w.status_pill._spec["text"], "Service unavailable")

    # ---------------------------------------------------------------- several iPhones
    def test_two_iphones_ask_the_user_and_touch_neither_until_chosen(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one")), Phone(UDID_B, "Bravo", apps_of("com.b.one")))
        self.build(fleet)
        self.assertIs(self.w.error.kind, ErrorKind.MULTIPLE_DEVICES)
        self.assertEqual(self.w.overlay_button._text, "Choose iPhone…")
        self.wait_for(lambda: self.w.picker_dialog is not None)
        self.assertEqual([d.udid for d in self.w.picker_dialog.candidates], [UDID_A, UDID_B])
        self.assertEqual(fleet.installer_calls(), [])
        self.assertEqual(self.w.apps, [])

    def test_choosing_an_iphone_loads_that_one_only(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one")), Phone(UDID_B, "Bravo", apps_of("com.b.one")))
        self.build(fleet)
        self.wait_for(lambda: self.w.picker_dialog is not None)
        self.w.picker_dialog.choose(UDID_B)
        self.assertIsNone(self.w.picker_dialog)
        self.settle()
        self.assertEqual([a.bundle_id for a in self.w.apps], ["com.b.one"])
        self.assertIn("Bravo", self.w.status_detail.cget("text"))
        self.assertEqual(self.seen["icons"][-1].udid, UDID_B)
        self.assertEqual(self.seen["inventory"][-1].udid, UDID_B)
        self.assertTrue(all(args[:2] == ["-u", UDID_B] for args in fleet.installer_calls()))

    def test_cancelling_the_picker_chooses_nothing(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one")), Phone(UDID_B, "Bravo", apps_of("com.b.one")))
        self.build(fleet)
        self.wait_for(lambda: self.w.picker_dialog is not None)
        self.w.picker_dialog.cancel()
        self.assertIsNone(self.w.picker_dialog)
        self.assertEqual(fleet.installer_calls(), [])
        self.assertIsNone(self.service.target)

    def test_ticked_apps_never_carry_over_to_a_different_iphone(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.shared.app")), Phone(UDID_B, "Bravo", apps_of("com.shared.app")))
        self.build(fleet)
        self.wait_for(lambda: self.w.picker_dialog is not None)
        self.w.picker_dialog.choose(UDID_A)
        self.settle()
        self.w.select_all()
        self.assertEqual(self.w.checked, {"com.shared.app"})
        self.service.choose_device(UDID_B)                  # the service now points at the other iPhone
        self.w.refresh()
        self.settle()
        self.assertEqual(self.w.checked, set())              # the tick made for Alpha is gone
        self.assertEqual(self.w.target.udid, UDID_B)

    def test_switching_connection_clears_the_selection(self):
        self.build(FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one"), usb=True, wifi=True)))
        self.w.select_all()
        self.assertTrue(self.w.checked)
        self.select_connection(ConnectionType.WIFI)
        self.assertEqual(self.w.checked, set())

    # ---------------------------------------------------------------- removal over each connection
    def remove_everything(self):
        self.w.select_all()
        dialog = self.w.open_uninstall_confirmation()
        self.assertIsNotNone(dialog)
        dialog.confirm()
        self.wait_for(lambda: not self.w.uninstalling and not self.w.loading)
        self.settle()

    def test_removal_and_verification_over_wifi_use_the_same_iphone_and_connection(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one", "com.a.two"), usb=True, wifi=True),
                          Phone(UDID_B, "Bravo", apps_of("com.a.one"), usb=True, wifi=True))
        self.build(fleet)
        self.wait_for(lambda: self.w.picker_dialog is not None)
        self.w.picker_dialog.choose(UDID_A)
        self.settle()
        self.select_connection(ConnectionType.WIFI)
        self.wait_for(lambda: self.w.picker_dialog is not None)
        self.w.picker_dialog.choose(UDID_A)
        self.settle()
        calls_before = len(fleet.calls)
        self.remove_everything()
        self.assertEqual(sorted(fleet.uninstalled), [(UDID_A, "com.a.one"), (UDID_A, "com.a.two")])
        for name, args in fleet.calls[calls_before:]:
            with self.subTest(name=name, args=args):
                self.assertEqual(args[:3], ["-u", UDID_A, "-n"])                  # removal AND the verification reload
        # the post-removal helpers also targeted the same iPhone and connection
        self.assertEqual(self.seen["icons"][-1], DeviceTarget(UDID_A, ConnectionType.WIFI, "Alpha"))
        self.assertEqual(self.seen["inventory"][-1], DeviceTarget(UDID_A, ConnectionType.WIFI, "Alpha"))
        results = self.w.last_uninstall_results
        self.assertEqual([r.outcome for r in results], [Outcome.REMOVED, Outcome.REMOVED])
        self.assertEqual(self.w.apps, [])

    def test_removal_over_usb_still_works_and_stays_on_usb(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one", "com.a.two"), usb=True, wifi=True))
        self.build(fleet)
        calls_before = len(fleet.calls)
        self.remove_everything()
        self.assertEqual(len(fleet.uninstalled), 2)
        for name, args in fleet.calls[calls_before:]:
            self.assertEqual(args[:2], ["-u", UDID_A])
            self.assertNotIn("-n", args)                                             # never drifts onto Wi-Fi
        self.assertEqual([r.outcome for r in self.w.last_uninstall_results], [Outcome.REMOVED] * 2)

    def test_wifi_drop_during_removal_is_reported_and_nothing_is_sent_over_usb(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one", "com.a.two", "com.a.three"), usb=True, wifi=True))

        def drop(f, count):
            if count == 1:
                f.phones[0].wifi = False                                              # still plugged in by USB!
        fleet.on_uninstall = drop
        self.build(fleet)
        self.select_connection(ConnectionType.WIFI)
        self.remove_everything()
        self.assertEqual(len(fleet.uninstalled), 1)                                    # only the first, over Wi-Fi
        outcomes = [r.outcome for r in self.w.last_uninstall_results]
        self.assertEqual(sorted(o.value for o in outcomes), sorted(["removed", "failed", "not_attempted"]))
        for args in fleet.installer_calls():
            if "--uninstall" in args:
                self.assertIn("-n", args)

    def test_removal_is_refused_if_the_service_no_longer_points_at_the_shown_iphone(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one")), Phone(UDID_B, "Bravo", apps_of("com.a.one")))
        self.build(fleet)
        self.wait_for(lambda: self.w.picker_dialog is not None)
        self.w.picker_dialog.choose(UDID_A)
        self.settle()
        self.w.select_all()
        dialog = self.w.open_uninstall_confirmation()
        self.service.choose_device(UDID_B)
        self.service.resolve_target()                                                  # now aimed at Bravo
        dialog.confirm()
        self.root.update()
        self.assertFalse(self.w.uninstalling)
        self.assertEqual(fleet.uninstalled, [])

    def test_confirmation_names_the_connection_only_for_wifi(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one"), usb=True, wifi=True))
        self.build(fleet)
        self.w.select_all()
        usb_dialog = self.w.open_uninstall_confirmation()
        self.assertIn("removed from Alpha:", usb_dialog.message_label.cget("text"))
        usb_dialog.cancel()
        self.select_connection(ConnectionType.WIFI)
        self.w.select_all()
        wifi_dialog = self.w.open_uninstall_confirmation()
        self.assertIn("removed from Alpha (over Wi-Fi):", wifi_dialog.message_label.cget("text"))
        wifi_dialog.cancel()

    # ---------------------------------------------------------------- the connection cannot change mid-operation
    def test_selector_is_locked_while_removing_and_a_change_is_refused(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one"), usb=True, wifi=True))
        self.build(fleet)
        self.w.uninstalling = True                                                      # as during a removal
        self.w._sync_connection_controls()
        self.assertFalse(self.w.connection_selector.enabled)
        self.w.connection_selector.select(ConnectionType.WIFI)                          # ignored by the control itself
        self.assertIs(self.service.connection, ConnectionType.USB)
        self.w._on_connection_selected(ConnectionType.WIFI)                             # and refused by the window
        self.assertIs(self.service.connection, ConnectionType.USB)
        self.assertIs(self.w.connection_selector.value, ConnectionType.USB)
        self.w.uninstalling = False
        self.w._sync_connection_controls()
        self.assertTrue(self.w.connection_selector.enabled)

    def test_selector_is_locked_while_loading(self):
        fleet = FakeFleet(Phone(UDID_A, "Alpha", apps_of("com.a.one"), usb=True, wifi=True))
        self.build(fleet)
        self.w.loading = True
        self.w._sync_connection_controls()
        self.assertFalse(self.w.connection_selector.enabled)
        self.w.loading = False
        self.w._sync_connection_controls()


class SegmentedControlTests(unittest.TestCase):
    def test_click_and_keyboard_change_the_value_and_call_back(self):
        from iphone_app_manager.ui.theme import apply_theme
        from iphone_app_manager.ui.widgets import SegmentedControl
        root = tk.Tk()
        self.addCleanup(root.destroy)
        fonts = apply_theme(root, 1.0)
        chosen = []
        control = SegmentedControl(root, options=[("USB", "usb"), ("Wi-Fi", "wifi")], value="usb",
                                   command=chosen.append, fonts=fonts, scale=1.0, bg="#1E293B")
        control.pack()
        root.update()
        self.assertEqual(control.value, "usb")
        left, right = control._edges
        control._on_click(type("E", (), {"x": right[0] + 4})())
        self.assertEqual((control.value, chosen), ("wifi", ["wifi"]))
        control.select("wifi")                                       # already chosen: no second callback
        self.assertEqual(chosen, ["wifi"])
        control._step(-1)
        self.assertEqual((control.value, chosen), ("usb", ["wifi", "usb"]))
        control.set_enabled(False)
        control.select("wifi")
        self.assertEqual(control.value, "usb")                       # disabled: ignored
        control.set_enabled(True)
        control.set_value("wifi")                                    # show-only, no callback
        self.assertEqual(chosen, ["wifi", "usb"])


# ====================================================================== documentation
class DocumentationTests(unittest.TestCase):
    def read(self, name):
        return " ".join((ROOT / name).read_text(encoding="utf-8").split())

    def test_readme_explains_usb_and_wifi_and_that_it_is_not_bluetooth(self):
        text = self.read("README.md")
        for needle in ("USB or Wi-Fi", "Show this iPhone when on Wi-Fi", "same Wi-Fi network", "not Bluetooth",
                       "Apple Devices", "USB is the default"):
            self.assertIn(needle, text, needle)
        self.assertRegex(text, r"(?i)Wi-Fi.{0,200}has not been tested|not (yet )?been tested.{0,200}Wi-Fi")

    def test_readme_no_longer_claims_usb_only_or_no_networking(self):
        text = self.read("README.md")
        self.assertNotIn("Designed and tested for USB connections only", text)
        self.assertNotIn("It contains no networking code of its own", text)

    def test_the_package_has_no_bluetooth_code(self):
        for path in (ROOT / "iphone_app_manager").rglob("*.py"):
            code = re.sub(r'"""[\s\S]*?"""', "", path.read_text(encoding="utf-8"))
            code = "\n".join(line.split("#")[0] for line in code.splitlines())
            self.assertNotRegex(code, r"(?i)bluetooth", path.name)


if __name__ == "__main__":
    unittest.main()
