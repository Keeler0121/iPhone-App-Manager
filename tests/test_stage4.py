"""Stage 4 tests: storage, app details, offloaded apps. NOTHING here talks to a real iPhone.

Run with:  py -3.12 -m unittest discover -s tests -v
"""
from __future__ import annotations

import re
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

from iphone_app_manager import app_inventory, config, inventory_helper  # noqa: E402
from iphone_app_manager.device import (  # noqa: E402
    DeviceService, ToolResult, UninstallFailure, app_from_plist, parse_disk_usage, removal_block_reason,
)
from iphone_app_manager.models import AppInfo, AppSize  # noqa: E402
from iphone_app_manager.uninstall import Outcome  # noqa: E402
from iphone_app_manager.ui.main_window import format_gb  # noqa: E402
from iphone_app_manager.ui.widgets import format_bytes  # noqa: E402
from test_uninstall import FakeService, app, fake_fetch_icons  # noqa: E402

DISK_USAGE = """AmountDataAvailable: 9910415360
AmountDataReserved: 209715200
AmountRestoreAvailable: 19354951680
CalculateDiskUsage: OkilyDokily
NANDInfo: AQAAAAEAAAABAAAAAAAAgKUCAAABAAAACAAAvc78agCmAgAAAQAAAAEGBwgGCggApwIAAAEAAAAABIGHuLYAAKgCAAAD
TotalDataAvailable: 61575532544
TotalDataCapacity: 105350762496
TotalDiskCapacity: 128000000000
TotalSystemAvailable: 0
TotalSystemCapacity: 9234821120
"""


# ====================================================================== overall storage
class DiskUsageTests(unittest.TestCase):
    def test_parse_uses_free_now_not_total_data_available(self):
        s = parse_disk_usage(DISK_USAGE)
        self.assertEqual(s.capacity, 128_000_000_000)
        self.assertEqual(s.free_now, 9_910_415_360)          # AmountDataAvailable
        self.assertNotEqual(s.free_now, 61_575_532_544)      # TotalDataAvailable deliberately ignored
        self.assertEqual(s.used, 128_000_000_000 - 9_910_415_360)
        self.assertEqual((format_gb(s.capacity, whole=True), format_gb(s.used), format_gb(s.free_now)),
                         ("128 GB", "118.1 GB", "9.9 GB"))

    def test_inconsistent_or_missing_values_are_unavailable(self):
        for text in ("", "TotalDiskCapacity: 128000000000",                         # no free figure
                     "AmountDataAvailable: 5", "TotalDiskCapacity: 0\nAmountDataAvailable: 0",
                     "TotalDiskCapacity: 100\nAmountDataAvailable: 200",            # free > capacity
                     "TotalDiskCapacity: 100\nAmountDataAvailable: -1",
                     "TotalDiskCapacity: 1000\nAmountDataAvailable: 900\nTotalDataCapacity: 800",
                     "TotalDiskCapacity: abc\nAmountDataAvailable: 1"):
            with self.subTest(text=text):
                self.assertIsNone(parse_disk_usage(text))

    def test_service_storage_is_optional(self):
        def runner(exe, args, timeout):
            if args == ["-q", "com.apple.disk_usage"]:
                return ToolResult(255, b"", b"ERROR: Could not connect to lockdownd")
            return ToolResult(0, b"x\n", b"")
        self.assertIsNone(DeviceService(runner=runner).get_storage())

    def test_snapshot_includes_storage(self):
        import plistlib
        listing = plistlib.dumps([{"CFBundleIdentifier": "com.a.b", "CFBundleDisplayName": "A",
                                   "ApplicationType": "User"}])

        def runner(exe, args, timeout):
            if "-q" in args:
                return ToolResult(0, DISK_USAGE.encode(), b"")
            if "-k" in args:
                return ToolResult(0, b"Test\n", b"")
            return ToolResult(0, listing, b"")
        device, apps = DeviceService(runner=runner).load_snapshot()
        self.assertEqual(device.storage.free_now, 9_910_415_360)
        self.assertEqual(len(apps), 1)


class FormatTests(unittest.TestCase):
    def test_decimal_units_like_ios_settings(self):
        self.assertEqual(format_bytes(711_540_736), "711.5 MB")
        self.assertEqual(format_bytes(34_400_000), "34.4 MB")
        self.assertEqual(format_bytes(1_060_000_000), "1.06 GB")
        self.assertEqual(format_bytes(4_096), "4 KB")
        self.assertEqual(format_bytes(0), "0 KB")

    def test_app_size_total(self):
        self.assertEqual(AppSize(711_540_736, 160_993_280).total_bytes, 872_534_016)


# ====================================================================== metadata
class MetadataTests(unittest.TestCase):
    ENTRY = {"CFBundleIdentifier": "com.example.Mailbox", "CFBundleDisplayName": "Mailbox",
             "CFBundleShortVersionString": "6.0.261109", "CFBundleVersion": "6.0.261109.1",
             "ApplicationType": "User", "MinimumOSVersion": "18.0", "UIDeviceFamily": [2, 1],
             "IsAppClip": False, "IsDemotedApp": False, "SignerIdentity": "Apple iPhone OS Application Signing",
             "ApplicationDSID": 1234567890123}

    def test_fields(self):
        a = app_from_plist(self.ENTRY)
        self.assertEqual((a.build, a.min_os, a.device_family, a.is_app_clip, a.signer, a.offloaded),
                         ("6.0.261109.1", "18.0", (1, 2), False, "Apple iPhone OS Application Signing", False))
        self.assertEqual(a.status, "Installed")

    def test_account_identifier_never_stored(self):
        a = app_from_plist(self.ENTRY)
        self.assertNotIn("1234567890123", repr(a))
        self.assertFalse(any("dsid" in f.lower() for f in AppInfo.__dataclass_fields__))

    def test_explicit_demoted_flag(self):
        self.assertTrue(app_from_plist({**self.ENTRY, "IsDemotedApp": True}).offloaded)
        self.assertFalse(app_from_plist({**self.ENTRY, "IsDemotedApp": "yes"}).offloaded)


# ====================================================================== offloaded detection
HOME_SCREEN = {
    "buttonBar": [{"displayIdentifier": "com.apple.mobilesafari", "bundleIdentifier": "com.apple.mobilesafari",
                   "bundleVersion": "1", "iconModDate": "x"}],
    "iconLists": [[
        {"displayIdentifier": "com.example.Mailbox", "bundleIdentifier": "com.example.Mailbox",
         "bundleVersion": "6", "iconModDate": "x", "displayName": "Mailbox"},
        {"displayIdentifier": "tv.tiger", "displayName": "Tiger"},                       # placeholder
        {"displayIdentifier": "ABCDEF0123456789ABCDEF0123456789", "webClipURL": "https://example.invalid",
         "displayName": "Web clip"},
        {"displayIdentifier": "com.x.widget", "bundleIdentifier": "com.x.widget", "widgetIdentifier": "w",
         "elementType": "widget", "containerBundleIdentifier": "com.x"},
        {"displayIdentifier": "Folder", "iconLists": [[{"displayIdentifier": "com.willow.phone",
                                                        "displayName": "Willow"},
                                                       {"displayIdentifier": "tv.tiger", "displayName": "Tiger"}]]},
    ]],
}

SHOW_PLACEHOLDERS_LISTING = [
    {"CFBundleIdentifier": "com.example.Mailbox", "CFBundleDisplayName": "Mailbox", "ApplicationType": "User",
     "IsDemotedApp": False},
    {"CFBundleIdentifier": "tv.tiger", "CFBundleDisplayName": "Tiger", "ApplicationType": "User",
     "IsDemotedApp": True, "CFBundleShortVersionString": "31.9", "CFBundleVersion": "3190"},
    {"CFBundleIdentifier": "com.fern.fern", "CFBundleName": "Fern", "ApplicationType": "User",
     "IsDemotedApp": True},                                         # App Library only, no display name
    {"CFBundleIdentifier": "com.apple.Pages", "CFBundleDisplayName": "Pages", "ApplicationType": "User",
     "IsDemotedApp": True},
    {"CFBundleIdentifier": "com.sys.thing", "ApplicationType": "System", "IsDemotedApp": True},
    {"CFBundleIdentifier": "odd.flag", "ApplicationType": "User", "IsDemotedApp": "true"},   # not a real bool
    {"CFBundleIdentifier": "tv.tiger", "ApplicationType": "User", "IsDemotedApp": True},    # duplicate
    "junk",
]


class OffloadedDetectionTests(unittest.TestCase):
    def test_only_ios_demoted_flag_counts(self):
        found = inventory_helper.parse_offloaded(SHOW_PLACEHOLDERS_LISTING)
        self.assertEqual([a["bundle_id"] for a in found], ["tv.tiger", "com.fern.fern", "com.apple.Pages"])
        self.assertEqual(found[0], {"bundle_id": "tv.tiger", "name": "Tiger", "version": "31.9", "build": "3190"})
        self.assertEqual(found[1]["name"], "Fern")

    def test_nothing_without_a_listing(self):
        self.assertEqual(inventory_helper.parse_offloaded([]), [])
        self.assertEqual(inventory_helper.parse_offloaded(None), [])

    def test_home_screen_placeholders(self):
        # Installed entries (bundleVersion), widgets, web clips and folders are never placeholders.
        self.assertEqual(inventory_helper.home_screen_placeholder_ids(HOME_SCREEN), ["tv.tiger", "com.willow.phone"])

    def test_parse_sizes(self):
        sizes = inventory_helper.parse_sizes([
            {"CFBundleIdentifier": "a", "StaticDiskUsage": 10, "DynamicDiskUsage": 5},
            {"CFBundleIdentifier": "b", "StaticDiskUsage": -1, "DynamicDiskUsage": 5},
            {"CFBundleIdentifier": "c", "StaticDiskUsage": True, "DynamicDiskUsage": 5},
            {"CFBundleIdentifier": "d", "StaticDiskUsage": 10},
            "junk"])
        self.assertEqual(sizes, {"a": [10, 5]})


class InventoryHelperSafetyTests(unittest.TestCase):
    def test_only_read_only_device_calls(self):
        src = (ROOT / "iphone_app_manager" / "inventory_helper.py").read_text(encoding="utf-8")
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        code = "\n".join(l for l in code.splitlines() if not l.lstrip().startswith("#"))
        device_calls = set(re.findall(r"\bimd\.(\w+)", code))
        self.assertEqual(device_calls, {"idevice_new", "idevice_free", "instproxy_client_start_service",
                                        "instproxy_browse", "instproxy_client_free",
                                        "sbservices_client_start_service", "sbservices_get_icon_state",
                                        "sbservices_client_free"})
        for forbidden in ("uninstall", "instproxy_install", "upgrade", "archive", "restore", "set_icon_state",
                          "ApplicationDSID", "afc_", "house_arrest", "Container"):
            self.assertNotIn(forbidden, code, forbidden)
        self.assertIn("ShowPlaceholders", code)

    def test_no_account_identifiers_requested_anywhere(self):
        pkg = ROOT / "iphone_app_manager"
        for path in pkg.rglob("*.py"):
            code = re.sub(r'"""[\s\S]*?"""', "", path.read_text(encoding="utf-8"))
            code = "\n".join(l.split("#")[0] for l in code.splitlines())
            self.assertNotIn("DSID", code, path.name)


def _helper(script: str) -> list[str]:
    return [sys.executable, "-I", "-c", script]


class InventoryProtocolTests(unittest.TestCase):
    def run_fetch(self, script, **kw):
        off, sizes, home = [], [], []
        result = app_inventory.fetch_inventory(off.append, sizes.append, threading.Event(),
                                               on_home_screen=home.append, command=_helper(script), **kw)
        return off, sizes, home, result

    def test_stream(self):
        script = ("import json\n"
                  "print(json.dumps({'type':'offloaded','apps':[{'bundle_id':'tv.tiger','name':'Tiger',"
                  "'version':'31.9','build':'3190'},{'bundle_id':5}]}))\n"
                  "print(json.dumps({'type':'home_screen','placeholders':['tv.tiger',7]}))\n"
                  "print(json.dumps({'type':'sizes','sizes':{'a':[10,5],'bad':[-1,2]}}))\n"
                  "print(json.dumps({'type':'end'}))\n")
        off, sizes, home, r = self.run_fetch(script)
        self.assertEqual(off, [[AppInfo("tv.tiger", "Tiger", "31.9", build="3190", app_type="User",
                                        offloaded=True)]])
        self.assertEqual(home, [{"tv.tiger"}])
        self.assertEqual(sizes, [{"a": AppSize(10, 5)}])
        self.assertEqual((r.error, r.offloaded_error, r.home_screen_error), (None, None, None))

    def test_partial_errors(self):
        script = ("import json\n"
                  "print(json.dumps({'type':'offloaded_error','message':'app listing failed (error -5)'}))\n"
                  "print(json.dumps({'type':'home_screen_error','message':'Home Screen layout unavailable'}))\n"
                  "print(json.dumps({'type':'sizes','sizes':{}}))\n"
                  "print(json.dumps({'type':'end'}))\n")
        off, _sizes, home, r = self.run_fetch(script)
        self.assertEqual((off, home), ([], []))
        self.assertEqual(r.offloaded_error, "app listing failed (error -5)")
        self.assertEqual(r.home_screen_error, "Home Screen layout unavailable")

    def test_disconnected_and_crash(self):
        *_rest, r = self.run_fetch("import sys; sys.exit(2)")
        self.assertEqual((r.error, r.offloaded_error, r.home_screen_error, r.sizes_error), ("iPhone not connected",) * 4)
        *_rest, r = self.run_fetch("import os; os._exit(-1073741819)")
        self.assertEqual(r.error, "inventory helper stopped unexpectedly")

    def test_hang_times_out(self):
        start = time.monotonic()
        *_rest, r = self.run_fetch("import time; time.sleep(60)", idle_timeout=1.0)
        self.assertEqual(r.error, "timed out")
        self.assertLess(time.monotonic() - start, 10)


# ====================================================================== removal rules
class OffloadedRemovalRuleTests(unittest.TestCase):
    def test_enabled_after_verified_test_and_apple_apps_protected(self):
        off = AppInfo("tv.tiger", "Tiger", "", app_type="User", offloaded=True)
        self.assertTrue(config.OFFLOADED_REMOVAL_ENABLED)
        self.assertIsNone(removal_block_reason(off))
        apple = AppInfo("com.apple.Pages", "Pages", "", app_type="User", offloaded=True)
        self.assertEqual(removal_block_reason(apple), "Apple app (protected)")
        self.assertEqual(removal_block_reason(AppInfo("COM.APPLE.x", "x", "", app_type="User", offloaded=True)),
                         "Apple app (protected)")

    def test_switch_still_disables_offloaded_removal(self):
        off = AppInfo("tv.tiger", "Tiger", "", app_type="User", offloaded=True)
        with mock.patch.object(config, "OFFLOADED_REMOVAL_ENABLED", False):
            self.assertIn("offloaded", removal_block_reason(off))
            self.assertIsNone(removal_block_reason(AppInfo("com.a.b", "A", "1", app_type="User")))


class VerificationTests(unittest.TestCase):
    def test_offloaded_needs_listing(self):
        from iphone_app_manager.uninstall import UninstallResult, verify_results
        off = AppInfo("tv.tiger", "Tiger", "", app_type="User", offloaded=True)
        inst = AppInfo("com.a.b", "A", "1", app_type="User")
        reported = [UninstallResult(off, Outcome.REMOVED), UninstallResult(inst, Outcome.REMOVED)]
        ok = verify_results(reported, set(), offloaded_listing_ok=True)
        self.assertEqual([r.outcome for r in ok], [Outcome.REMOVED, Outcome.REMOVED])
        blind = verify_results(reported, set(), offloaded_listing_ok=False)
        self.assertEqual([r.outcome for r in blind], [Outcome.UNVERIFIED, Outcome.REMOVED])
        still = verify_results(reported, {"tv.tiger"}, offloaded_listing_ok=True)
        self.assertEqual(still[0].outcome, Outcome.FAILED)


# ====================================================================== UI (fake device)
def offloaded(bid, name, version=""):
    return AppInfo(bid, name, version, app_type="User", offloaded=True)


class FakeInventory:
    """Fake iPhone inventory: iOS's offloaded list (ShowPlaceholders), Home Screen placeholders, sizes."""

    def __init__(self):
        self.offloaded = [offloaded("tv.tiger", "Tiger", "31.9"), offloaded("com.willow.phone", "Willow"),
                          offloaded("com.fern.fern", "Fern"),            # App Library only
                          offloaded("com.apple.Pages", "Pages")]            # offloaded Apple app
        self.home = {"tv.tiger", "com.willow.phone", "com.apple.Pages"}
        self.sizes = {"com.alpha.app": AppSize(100_000_000, 50_000_000),     # total 150 MB
                      "com.bravo.app": AppSize(300_000_000, 10_000_000),     # total 310 MB
                      "com.charlie.app": AppSize(20_000_000, 900_000_000),   # total 920 MB
                      "com.delta.app": AppSize(5_000_000, 1_000_000),        # total 6 MB
                      "tv.tiger": AppSize(667_648, 7_700_480),              # placeholder + retained data
                      "com.willow.phone": AppSize(70_000, 2_000_000),
                      "com.fern.fern": AppSize(30_000, 8_000)}
        self.offloaded_error = None
        self.home_error = None
        self.calls = 0
        self.hold = threading.Event()
        self.hold.set()

    def remove(self, bid, behaviour):
        if behaviour == "ok":
            self.offloaded = [a for a in self.offloaded if a.bundle_id != bid]
            self.home.discard(bid)
            self.sizes.pop(bid, None)
        elif behaviour == "lie_home":            # gone from iOS's list, placeholder left on Home Screen
            self.offloaded = [a for a in self.offloaded if a.bundle_id != bid]

    def fetch(self, on_offloaded, on_sizes, cancel, on_home_screen=None, **_kw):
        self.calls += 1
        r = app_inventory.InventoryResult()
        if self.offloaded_error:
            r.offloaded_error = self.offloaded_error
        else:
            on_offloaded(list(self.offloaded))
        if self.home_error:
            r.home_screen_error = self.home_error
        elif on_home_screen:
            on_home_screen(set(self.home))
        self.hold.wait(10)
        on_sizes(dict(self.sizes))
        return r


APPS = [app("com.alpha.app", "Alpha"), app("com.bravo.app", "Bravo"), app("com.charlie.app", "Charlie"),
        app("com.delta.app", "Delta"), app("ScoreBoard", "ScoreBoard"), app("com.echo.app", "Echo")]


class Stage4UiTests(unittest.TestCase):
    def setUp(self):
        from test_uninstall import isolate_from_device
        from iphone_app_manager.models import DeviceInfo
        from iphone_app_manager.ui import MainWindow
        isolate_from_device(self)
        self.inv = FakeInventory()
        p = mock.patch("iphone_app_manager.ui.main_window.fetch_inventory", self.inv.fetch)
        p.start()
        self.addCleanup(p.stop)
        self.icon_requests: list[list[str]] = []

        def recording_icons(ids, size, on_icon, cancel, **kw):
            self.icon_requests.append(list(ids))
            return fake_fetch_icons(ids, size, on_icon, cancel, **kw)
        p2 = mock.patch("iphone_app_manager.ui.main_window.fetch_icons", recording_icons)
        p2.start()
        self.addCleanup(p2.stop)

        self.service = FakeService(APPS)
        self.service.device = DeviceInfo("Test iPhone", "26.0", parse_disk_usage(DISK_USAGE))
        inv = self.inv
        original_uninstall = self.service.uninstall_app

        def uninstall(bid):        # mocked removal - never touches a real iPhone
            original_uninstall(bid)
            behaviour = self.service.behaviour.get(bid, "ok")
            if isinstance(behaviour, str):
                inv.remove(bid, behaviour)
        self.service.uninstall_app = uninstall
        self.root = tk.Tk()
        self.w = MainWindow(self.root, self.service)
        self.settle()

    def tearDown(self):
        self.inv.hold.set()
        self.w.uninstalling = False
        self.w._on_close()

    def settle(self, timeout=15.0):
        end = time.monotonic() + timeout
        w = self.w
        while w.loading or w.inventory_running or w.icon_fetching or w.uninstalling or w.device is None:
            if time.monotonic() > end:
                self.fail("UI did not settle")
            self.root.update()
            time.sleep(0.01)
        self.root.update()

    def ids(self):
        return [a.bundle_id for a in self.w.app_list.rows]

    def get(self, bid):
        return next(a for a in self.w.apps if a.bundle_id == bid)

    # ---------------------------------------------------------- storage + sizes
    def test_header_storage(self):
        self.assertEqual(self.w.storage_label.cget("text"), "118.1 GB used  ·  9.9 GB free now  ·  128 GB")
        self.service.device = type(self.service.device)("Test iPhone", "26.0", None)
        self.w.refresh()
        self.settle()
        self.assertEqual(self.w.storage_label.cget("text"), "Storage information unavailable")

    def test_sizes_columns_and_states(self):
        w = self.w
        alpha = self.get("com.alpha.app")
        self.assertEqual(w.size_for(alpha), AppSize(100_000_000, 50_000_000))
        self.assertEqual(w.size_for(self.get("com.echo.app")), "Not available")      # no figure reported
        tiger = self.get("tv.tiger")
        self.assertEqual(w.size_for(tiger), AppSize(667_648, 7_700_480))            # retained data shown
        self.assertEqual([c[0] for c in w.app_list._size_cells(tiger)], ["668 KB", "7.7 MB", "8.4 MB"])
        self.assertEqual(w.size_for(self.get("com.apple.Pages")), "Not available")
        cells = [c[0] for c in w.app_list._size_cells(alpha)]
        self.assertEqual(cells, ["100.0 MB", "50.0 MB", "150.0 MB"])
        self.inv.hold.clear()
        w.refresh()
        end = time.monotonic() + 5
        while w.sizes_state != "loading" or w.loading:
            self.root.update()
            if time.monotonic() > end:
                self.fail("never started calculating")
        self.assertEqual(w.size_for(alpha), "Calculating…")
        self.inv.hold.set()
        self.settle()
        self.assertEqual(w.size_for(alpha), AppSize(100_000_000, 50_000_000))
        self.assertEqual(self.inv.calls, 2)                                # sizes reloaded on refresh

    def test_sorting_by_storage(self):
        w = self.w
        w.set_sort("total_desc")
        self.assertEqual(self.ids()[:7], ["com.charlie.app", "com.bravo.app", "com.alpha.app", "tv.tiger",
                                          "com.delta.app", "com.willow.phone", "com.fern.fern"])
        self.assertEqual(set(self.ids()[7:]), {"com.echo.app", "ScoreBoard", "com.apple.Pages"})
        w.set_sort("total_asc")
        self.assertEqual(self.ids()[:3], ["com.fern.fern", "com.willow.phone", "com.delta.app"])
        w.set_sort("app_desc")
        self.assertEqual(self.ids()[0], "com.bravo.app")
        w.set_sort("data_desc")
        self.assertEqual(self.ids()[0], "com.charlie.app")
        w._on_header_sort("data")                                         # header click flips the order
        self.assertEqual(w.sort_mode, "data_asc")
        w._on_header_sort("name")
        self.assertEqual(w.sort_mode, "name_asc")
        self.assertEqual(self.ids()[0], "com.alpha.app")
        w.toggle_sort()
        self.assertEqual(w.sort_mode, "name_desc")
        w.set_sort("total_desc")
        w.search_var.set("a.app")                                         # search still works with size sort
        self.assertEqual(self.ids(), ["com.alpha.app", "com.delta.app"])  # 150 MB, then 6 MB

    # ---------------------------------------------------------- offloaded apps
    def test_offloaded_from_ios_listing_including_app_library(self):
        w = self.w
        off = {a.bundle_id: a for a in w.apps if a.offloaded}
        self.assertEqual(set(off), {"tv.tiger", "com.willow.phone", "com.fern.fern", "com.apple.Pages"})
        self.assertEqual((off["tv.tiger"].name, off["tv.tiger"].version, off["tv.tiger"].status),
                         ("Tiger", "31.9", "Offloaded"))
        self.assertIn("6 installed  ·  4 offloaded", w.summary_label.cget("text"))
        self.assertTrue(any("com.fern.fern" in req for req in self.icon_requests))   # icons for them too
        self.assertTrue(w.icons.has_real_icon("tv.tiger"))
        details = dict(w.details_for(off["tv.tiger"]))
        self.assertTrue(details["Status"].startswith("Offloaded"))
        self.assertEqual((details["Retained data*"], details["Location"]), ("7.7 MB", "Home Screen"))
        self.assertEqual(dict(w.details_for(off["com.fern.fern"]))["Location"], "App Library only")

    def test_detection_failure_shows_no_offloaded_apps(self):
        self.inv.offloaded_error = "app listing failed (error -5)"
        self.w.refresh()
        self.settle()
        self.assertFalse(any(a.offloaded for a in self.w.apps))
        self.assertIn("Offloaded apps couldn't be checked", self.w.summary_label.cget("text"))

    def test_selection_of_installed_and_offloaded(self):
        w = self.w
        w.select_all()
        self.assertEqual(len(w.checked), 10)
        self.assertEqual(w.count_pill._spec["text"], "10 selected")
        w.deselect_all()
        w.checked = {"tv.tiger", "com.fern.fern"}
        w._render()
        self.assertTrue(w.uninstall_button.enabled)            # offloaded removal is enabled
        w.checked = {"com.apple.Pages"}
        w._render()
        self.assertFalse(w.uninstall_button.enabled)           # offloaded Apple app stays protected
        self.assertIsNone(w.open_uninstall_confirmation())
        w.checked = {"tv.tiger", "com.willow.phone"}
        w.refresh()                                            # selection of offloaded apps survives refresh
        self.settle()
        self.assertEqual(w.checked, {"tv.tiger", "com.willow.phone"})

    def test_confirmation_identifies_installed_and_offloaded(self):
        w = self.w
        w.checked = {"com.alpha.app", "tv.tiger", "com.fern.fern", "com.apple.Pages"}
        w._render()
        dialog = w.open_uninstall_confirmation()
        self.assertEqual([a.bundle_id for a in dialog.apps], ["com.alpha.app", "com.fern.fern", "tv.tiger"])
        self.assertEqual((dialog.installed_count, dialog.offloaded_count), (1, 2))
        self.assertIn("(1 installed, 2 offloaded)", dialog.message_label.cget("text"))
        self.assertIn("permanently deletes that retained data", dialog.offloaded_notice.cget("text"))
        self.assertIn("Apple app (protected): 1", dialog.skipped_text)
        dialog.cancel()
        self.assertEqual(self.service.calls, [])

    def test_mixed_selection_skips_offloaded_when_switched_off(self):
        w = self.w
        with mock.patch.object(config, "OFFLOADED_REMOVAL_ENABLED", False):
            w.checked = {"com.alpha.app", "tv.tiger"}
            w._render()
            dialog = w.open_uninstall_confirmation()
            self.assertEqual([a.bundle_id for a in dialog.apps], ["com.alpha.app"])
            self.assertIn("Removing offloaded apps isn't verified yet: 1", dialog.skipped_text)
            dialog.confirm()
            self.settle()
        self.assertEqual(self.service.calls, ["com.alpha.app"])          # Tiger never attempted
        self.assertEqual(w.checked, {"tv.tiger"})
        w.progress_dialog._done()

    def test_mocked_offloaded_removal_is_verified_everywhere(self):
        w = self.w
        kept_icon = w.icons._real_icons["com.bravo.app"]
        # Willow: reports success but stays in iOS's offloaded list.
        # Fern: leaves iOS's list but (hypothetically) keeps a Home Screen placeholder.
        self.service.behaviour = {"com.willow.phone": "lie", "com.fern.fern": "lie_home"}
        self.inv.home.add("com.fern.fern")
        w.checked = {"com.alpha.app", "tv.tiger", "com.willow.phone", "com.fern.fern"}
        w._render()
        w.open_uninstall_confirmation().confirm()
        self.settle()
        self.assertEqual(self.service.calls, ["com.alpha.app", "com.fern.fern", "tv.tiger", "com.willow.phone"])
        self.assertEqual(self.service.peak, 1)                                     # strictly sequential
        outcomes = {r.app.bundle_id: r.outcome for r in w.last_uninstall_results}
        self.assertEqual(outcomes, {"com.alpha.app": Outcome.REMOVED, "tv.tiger": Outcome.REMOVED,
                                    "com.willow.phone": Outcome.FAILED,              # still offloaded
                                    "com.fern.fern": Outcome.FAILED})             # Home Screen leftover
        self.assertNotIn("tv.tiger", [a.bundle_id for a in w.apps])
        self.assertIn("com.willow.phone", [a.bundle_id for a in w.apps])
        self.assertEqual(w.checked, {"com.willow.phone"})   # Fern is no longer listed by iOS, so it is not shown
        self.assertIs(w.icons._real_icons["com.bravo.app"], kept_icon)            # icons preserved
        self.assertEqual(self.inv.calls, 2)                                        # storage refreshed after removal
        self.assertIn("installed apps, the offloaded apps and the Home Screen", w.progress_dialog.note.cget("text"))
        w.progress_dialog._done()

    def test_offloaded_removal_unverified_when_listing_unavailable(self):
        w = self.w
        w.checked = {"tv.tiger"}
        w._render()
        self.inv.offloaded_error = "app listing failed (error -5)"   # the post-removal check can't read it
        w.open_uninstall_confirmation().confirm()
        self.settle()
        self.assertEqual([r.outcome for r in w.last_uninstall_results], [Outcome.UNVERIFIED])
        self.assertEqual(w.checked, set())       # tv.tiger is no longer listed at all (listing failed)
        self.assertIn("1 not verified", w.progress_dialog.message_label.cget("text"))
        w.progress_dialog._done()

    def test_failed_removal(self):
        w = self.w
        self.service.behaviour = {"com.bravo.app": UninstallFailure("iPhone reported: APIInternalError")}
        w.checked = {"com.alpha.app", "com.bravo.app"}
        w._render()
        w.open_uninstall_confirmation().confirm()
        self.settle()
        self.assertEqual([r.outcome for r in w.last_uninstall_results], [Outcome.REMOVED, Outcome.FAILED])
        w.progress_dialog._done()

    def test_header_click_sorts_by_storage(self):
        L = self.w.app_list
        cols = L._cols
        L._on_header_click(type("E", (), {"x": cols.total_x + 5})())
        self.assertEqual(self.w.sort_mode, "total_desc")
        L._on_header_click(type("E", (), {"x": cols.total_x + 5})())
        self.assertEqual(self.w.sort_mode, "total_asc")

    def test_toolbar_controls_stay_visible_at_minimum_width(self):
        w = self.w
        bar = w._toolbar
        controls = [w.search, w.sort_button, w.count_pill, w.select_button, w.deselect_button,
                    w.uninstall_button, w.refresh_button]
        for geometry in ("2000x700", "200x700"):      # 200 is clamped to the minimum window size
            self.root.geometry(geometry)
            for _ in range(30):
                self.root.update()
            for c in controls:
                self.assertTrue(c.winfo_ismapped(), c)
                self.assertGreaterEqual(c.winfo_x(), 0)
                self.assertLessEqual(c.winfo_x() + c.winfo_width(), bar.winfo_width() + 1, c)
        self.assertTrue(w.select_button.compact)       # labels collapsed only when needed
        self.root.geometry("2000x700")
        for _ in range(30):
            self.root.update()
        self.assertFalse(any(b.compact for b in (w.select_button, w.deselect_button, w.sort_button)))

    def test_narrow_window_scrolls_horizontally(self):
        L = self.w.app_list
        self.root.geometry("700x600")
        self.settle()
        for _ in range(10):
            self.root.update()
        self.assertTrue(L._hscroll_shown)
        self.root.geometry("1400x700")
        for _ in range(10):
            self.root.update()
        self.assertFalse(L._hscroll_shown)


if __name__ == "__main__":
    unittest.main()
