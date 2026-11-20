"""Inventory helper process: offloaded-app detection and per-app storage (READ-ONLY).

Runs as a *separate process* (``python -I inventory_helper.py <bin-dir>``) so a fault in the
native libimobiledevice / libplist DLLs can never crash the main application.
Uses only the Python standard library.

Usage:  inventory_helper.py <bin-dir> [--udid <UDID> --connection usb|wifi]
Without --udid the original behaviour is kept (the first USB iPhone). With it the helper uses exactly
that iPhone: over USB (USB devices only) or over Wi-Fi (network devices only, never USB).

Read-only by construction - the only device calls declared are:
  * instproxy_browse          - list apps. With ShowPlaceholders=True iOS also lists offloaded
                                apps and marks them IsDemotedApp=True (the authoritative source).
  * sbservices_get_icon_state - READ the Home Screen layout (used only to double-check removals)
plus connect / free functions. Nothing that installs, removes or rearranges anything is
declared or called. Account identifiers (e.g. ApplicationDSID) are never requested.

Protocol (stdout, one JSON object per line):
  {"type": "offloaded", "apps": [{"bundle_id", "name", "version", "build"}, ...]}
  {"type": "offloaded_error", "message": ...}
  {"type": "home_screen", "placeholders": [bundle_id, ...]}
  {"type": "home_screen_error", "message": ...}
  {"type": "sizes", "sizes": {bundle_id: [app_bytes, data_bytes], ...}}   (installed + offloaded)
  {"type": "sizes_error", "message": ...}
  {"type": "end"}
Exit codes: 0 ok, 2 no device, 3 service unavailable (locked / not trusted),
            4 library could not be loaded, 1 unexpected error.
"""
from __future__ import annotations

import ctypes
import json
import os
import plistlib
import sys
from typing import Any, Optional

EXIT_NO_DEVICE = 2
EXIT_SERVICE = 3
EXIT_LIBRARY = 4

# libimobiledevice idevice_options. USB and Wi-Fi are used one at a time, never combined, so a
# helper started for one connection can never end up on the other.
LOOKUP_USBMUX = 1 << 1
LOOKUP_NETWORK = 1 << 2
_UDID_CHARS = set("0123456789abcdefABCDEF-")


def parse_target(extra: list[str]) -> tuple[Optional[str], int]:
    """(udid, lookup option) from the optional ``--udid U --connection usb|wifi`` arguments."""
    udid, connection = None, "usb"
    it = iter(extra)
    for flag in it:
        value = next(it, None)
        if flag == "--udid" and value is not None:
            udid = value
        elif flag == "--connection" and value in ("usb", "wifi"):
            connection = value
        else:
            raise ValueError(f"unexpected argument: {flag}")
    if udid is None and connection != "usb":
        raise ValueError("--connection needs --udid")
    if udid is not None and not (8 <= len(udid) <= 63 and udid[0] != "-" and set(udid) <= _UDID_CHARS):
        raise ValueError("invalid device identifier")
    return udid, LOOKUP_NETWORK if connection == "wifi" else LOOKUP_USBMUX

_WIDGET_OR_CONTAINER_KEYS = {"iconLists", "webClipURL", "widgetIdentifier", "elementType", "elements"}


# ====================================================================== pure logic (unit-tested)
def home_screen_app_entries(state: Any) -> list[dict]:
    """All app icons in a Home Screen layout (folders, widgets, stacks and web clips excluded)."""
    found: list[dict] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("displayIdentifier"), str) and not (_WIDGET_OR_CONTAINER_KEYS & set(node)):
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(state)
    return found


def home_screen_placeholder_ids(state: Any) -> list[str]:
    """Bundle IDs of Home Screen app icons that are placeholders (no installed bundle version)."""
    seen: list[str] = []
    for entry in home_screen_app_entries(state):
        bundle_id = entry["displayIdentifier"]
        if "bundleVersion" not in entry and bundle_id not in seen:
            seen.append(bundle_id)
    return seen


def _text(entry: dict, *keys: str) -> str:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def parse_offloaded(apps: Any) -> list[dict]:
    """Offloaded apps from a ShowPlaceholders listing: only entries iOS marks IsDemotedApp=True.

    This is iOS's own classification - nothing is inferred from missing icons or listings.
    """
    result, seen = [], set()
    for app in apps if isinstance(apps, list) else []:
        if not isinstance(app, dict) or app.get("IsDemotedApp") is not True:
            continue
        bundle_id = app.get("CFBundleIdentifier")
        if not isinstance(bundle_id, str) or not bundle_id or bundle_id in seen or app.get("ApplicationType") != "User":
            continue
        seen.add(bundle_id)
        result.append({"bundle_id": bundle_id,
                       "name": _text(app, "CFBundleDisplayName", "CFBundleName") or bundle_id,
                       "version": _text(app, "CFBundleShortVersionString", "CFBundleVersion"),
                       "build": _text(app, "CFBundleVersion")})
    return result


def parse_sizes(apps: Any) -> dict[str, list[int]]:
    """{bundle_id: [StaticDiskUsage, DynamicDiskUsage]} for entries with valid, non-negative sizes."""
    sizes = {}
    for app in apps if isinstance(apps, list) else []:
        if not isinstance(app, dict):
            continue
        bid, static, dynamic = app.get("CFBundleIdentifier"), app.get("StaticDiskUsage"), app.get("DynamicDiskUsage")
        if (isinstance(bid, str) and isinstance(static, int) and isinstance(dynamic, int)
                and not isinstance(static, bool) and static >= 0 and dynamic >= 0):
            sizes[bid] = [static, dynamic]
    return sizes


# ====================================================================== native (read-only) binding
class ServiceError(Exception):
    pass


class Device:
    def __init__(self, bin_dir: str, udid: Optional[str] = None, lookup: int = LOOKUP_USBMUX) -> None:
        self._udid = udid
        self._lookup = lookup
        os.add_dll_directory(bin_dir)
        imd = ctypes.CDLL(os.path.join(bin_dir, "libimobiledevice-1.0.dll"))
        pl = ctypes.CDLL(os.path.join(bin_dir, "libplist-2.0.dll"))
        vp, cp, i = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
        for func, args, res in (
            (pl.plist_new_dict, [], vp), (pl.plist_new_array, [], vp), (pl.plist_new_string, [cp], vp),
            (pl.plist_new_bool, [ctypes.c_uint8], vp),
            (pl.plist_array_append_item, [vp, vp], None), (pl.plist_dict_set_item, [vp, cp, vp], None),
            (pl.plist_to_xml, [vp, ctypes.POINTER(vp), ctypes.POINTER(ctypes.c_uint32)], i),
            (pl.plist_mem_free, [vp], None), (pl.plist_free, [vp], None),
            (imd.idevice_new, [ctypes.POINTER(vp), cp], i), (imd.idevice_free, [vp], i),
            (imd.idevice_new_with_options, [ctypes.POINTER(vp), cp, i], i),
            (imd.instproxy_client_start_service, [vp, ctypes.POINTER(vp), cp], i),
            (imd.instproxy_browse, [vp, vp, ctypes.POINTER(vp)], i),
            (imd.instproxy_client_free, [vp], i),
            (imd.sbservices_client_start_service, [vp, ctypes.POINTER(vp), cp], i),
            (imd.sbservices_get_icon_state, [vp, ctypes.POINTER(vp), cp], i),
            (imd.sbservices_client_free, [vp], i),
        ):
            func.argtypes, func.restype = args, res
        self.imd, self.pl = imd, pl
        self.device = vp()

    def connect(self) -> None:
        if self._udid is None:           # original behaviour: the first USB iPhone
            err = self.imd.idevice_new(ctypes.byref(self.device), None)
        else:                            # exactly this iPhone, over exactly this connection
            err = self.imd.idevice_new_with_options(ctypes.byref(self.device), self._udid.encode("ascii"),
                                                    self._lookup)
        if err != 0:
            raise ConnectionError(EXIT_NO_DEVICE, f"No iPhone found (idevice error {err}).")

    def _to_python(self, node: ctypes.c_void_p) -> Any:
        xml, length = ctypes.c_void_p(), ctypes.c_uint32()
        self.pl.plist_to_xml(node, ctypes.byref(xml), ctypes.byref(length))
        try:
            return plistlib.loads(ctypes.string_at(xml.value, length.value))
        finally:
            self.pl.plist_mem_free(xml)

    def browse(self, app_type: str, attributes: list[str], show_placeholders: bool = False) -> list:
        client = ctypes.c_void_p()
        err = self.imd.instproxy_client_start_service(self.device, ctypes.byref(client), b"iPhoneAppManager")
        if err != 0:
            raise ConnectionError(EXIT_SERVICE, f"Installation service unavailable (error {err}).")
        options = self.pl.plist_new_dict()
        try:
            self.pl.plist_dict_set_item(options, b"ApplicationType", self.pl.plist_new_string(app_type.encode()))
            if show_placeholders:   # also list offloaded apps (option used by Apple's own sync agent)
                self.pl.plist_dict_set_item(options, b"ShowPlaceholders", self.pl.plist_new_bool(1))
            attrs = self.pl.plist_new_array()
            for name in attributes:
                self.pl.plist_array_append_item(attrs, self.pl.plist_new_string(name.encode()))
            self.pl.plist_dict_set_item(options, b"ReturnAttributes", attrs)
            result = ctypes.c_void_p()
            err = self.imd.instproxy_browse(client, options, ctypes.byref(result))
            try:
                if err != 0 or not result.value:
                    raise ServiceError(f"app listing failed (error {err})")
                data = self._to_python(result)
            finally:
                if result.value:
                    self.pl.plist_free(result)
            return data if isinstance(data, list) else []
        finally:
            self.pl.plist_free(options)
            self.imd.instproxy_client_free(client)

    def home_screen_layout(self) -> Any:
        client = ctypes.c_void_p()
        err = self.imd.sbservices_client_start_service(self.device, ctypes.byref(client), b"iPhoneAppManager")
        if err != 0:
            raise ServiceError(f"SpringBoard service unavailable (error {err})")
        try:
            state = ctypes.c_void_p()
            err = self.imd.sbservices_get_icon_state(client, ctypes.byref(state), b"2")
            try:
                if err != 0 or not state.value:
                    raise ServiceError(f"Home Screen layout unavailable (error {err})")
                return self._to_python(state)
            finally:
                if state.value:
                    self.pl.plist_free(state)
        finally:
            self.imd.sbservices_client_free(client)

    def close(self) -> None:
        if self.device.value:
            self.imd.idevice_free(self.device)
            self.device = ctypes.c_void_p()


# ====================================================================== main
def _report(message: str) -> None:
    """Write a diagnostic to stderr - and never raise.

    The packaged app is a windowed (no-console) program. Started without a stderr handle (for example by hand,
    outside the app, which always pipes it), ``sys.stderr`` is None. Reporting an error must not itself fail,
    or the second exception hides the real cause.
    """
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(message)
    except (OSError, ValueError):
        pass


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        _report("usage: inventory_helper.py <libimobiledevice-bin-dir> "
                "[--udid UDID --connection usb|wifi]\n")
        return 1
    try:
        udid, lookup = parse_target(argv[2:])
    except ValueError as exc:
        _report(f"inventory_helper.py: {exc}\n")
        return 1
    try:
        device = Device(argv[1], udid, lookup)
    except OSError as exc:                  # includes FileNotFoundError for a missing folder
        _report(f"Could not load libimobiledevice: {exc}\n")
        return EXIT_LIBRARY
    try:
        if sys.stdout is None:              # no-console build started without a stdout handle: nowhere to send results
            _report("inventory_helper.py: there is no standard output to write the results to\n")
            return 1
        device.connect()
        # 1) Offloaded apps - iOS's own IsDemotedApp flag, including App Library-only apps (fast).
        try:
            listing = device.browse("User", ["CFBundleIdentifier", "CFBundleDisplayName", "CFBundleName",
                                             "CFBundleShortVersionString", "CFBundleVersion", "ApplicationType",
                                             "IsDemotedApp"], show_placeholders=True)
            if listing:
                _emit({"type": "offloaded", "apps": parse_offloaded(listing)})
            else:
                _emit({"type": "offloaded_error", "message": "app listing was empty"})
        except ServiceError as exc:
            _emit({"type": "offloaded_error", "message": str(exc)})
        # 2) Home Screen placeholders - used only to double-check that removed apps are gone.
        try:
            _emit({"type": "home_screen", "placeholders": home_screen_placeholder_ids(device.home_screen_layout())})
        except ServiceError as exc:
            _emit({"type": "home_screen_error", "message": str(exc)})
        # 3) Per-app storage for installed AND offloaded apps (iOS calculates sizes on request -
        #    takes several seconds). For offloaded apps DynamicDiskUsage is the retained data.
        try:
            apps = device.browse("User", ["CFBundleIdentifier", "StaticDiskUsage", "DynamicDiskUsage"],
                                 show_placeholders=True)
            _emit({"type": "sizes", "sizes": parse_sizes(apps)})
        except ServiceError as exc:
            _emit({"type": "sizes_error", "message": str(exc)})
        _emit({"type": "end"})
        return 0
    except ConnectionError as exc:
        code, message = exc.args
        _report(message + "\n")
        return code
    except OSError:
        return 0  # the app stopped listening (broken pipe)
    finally:
        device.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
