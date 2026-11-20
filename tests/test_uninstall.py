"""Stage 3 tests: bulk uninstall. NOTHING here talks to a real iPhone.

* Device-layer tests use a fake command runner (ideviceinstaller is never executed).
* UI tests use a FakeService and a fake icon fetcher (no helper process, no device).

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
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from iphone_app_manager import icon_helper  # noqa: E402
from iphone_app_manager.connection import ConnectionType  # noqa: E402
from iphone_app_manager.device import (  # noqa: E402
    DeviceError, DeviceService, ErrorKind, ToolResult, UninstallFailure, interpret_uninstall_output,
    is_valid_bundle_id, removal_block_reason,
)
from iphone_app_manager.models import AppInfo, DeviceInfo  # noqa: E402
from iphone_app_manager.uninstall import Outcome, run_uninstall_batch, verify_results  # noqa: E402

OK_OUTPUT = (b"Uninstalling 'com.example.a'\n"
             b"Uninstall: RemovingApplication (50%)\n"
             b"Uninstall: GeneratingApplicationMap (90%)\n"
             b"Uninstall: Complete\n")


def app(bid: str, name: str = "", app_type: str = "User") -> AppInfo:
    return AppInfo(bundle_id=bid, name=name or bid.split(".")[-1].title(), version="1.0", app_type=app_type)


# ====================================================================== device layer
class ValidationTests(unittest.TestCase):
    def test_bundle_ids(self):
        for good in ("com.example.app", "ScoreBoard", "uk.co.example.sport", "com.x-y.z_1"):
            self.assertTrue(is_valid_bundle_id(good), good)
        for bad in ("", "-rf", "--uninstall", ".com.x", "com example", "com.x;rm", "com.x\nfoo",
                    "com/x", "x" * 300, None):
            self.assertFalse(is_valid_bundle_id(bad), repr(bad))

    def test_only_user_apps_are_removable(self):
        self.assertIsNone(removal_block_reason(app("com.example.a")))
        self.assertEqual(removal_block_reason(app("com.example.a", app_type="System")), "Not a user-installed app")
        self.assertEqual(removal_block_reason(app("com.example.a", app_type="")), "Not a user-installed app")
        self.assertEqual(removal_block_reason(app("com.apple.Pages")), "Apple app (protected)")
        self.assertEqual(removal_block_reason(app("-bad")), "Invalid bundle identifier")


class InterpretOutputTests(unittest.TestCase):
    def test_success_requires_complete_and_no_error(self):
        interpret_uninstall_output(0, OK_OUTPUT.decode())  # does not raise

    def test_failures(self):
        cases = {
            (0, "Uninstalling 'x'\nUninstall: RemovingApplication (50%)\n"): "did not confirm",
            (0, "Uninstall: Complete\nERROR: Uninstall failed. Got error \"APIInternalError\"."): "APIInternalError",
            (255, "Uninstalling 'x'\n"): "exited with code 255",
            (1, "ERROR: Uninstall failed. Got error \"ApplicationNotFound\" with code 0x1: x"): "ApplicationNotFound",
        }
        for (rc, out), expected in cases.items():
            with self.subTest(out=out):
                with self.assertRaises(UninstallFailure) as ctx:
                    interpret_uninstall_output(rc, out)
                self.assertIn(expected, ctx.exception.message)
                self.assertFalse(ctx.exception.fatal)

    def test_device_problems_are_fatal(self):
        for out, kind in (("No device found.", ErrorKind.NO_DEVICE),
                          ("Could not connect to lockdownd: Invalid HostID (-21)", ErrorKind.NOT_TRUSTED),
                          ("Could not connect to lockdownd: Password protected (-17)", ErrorKind.LOCKED)):
            with self.assertRaises(UninstallFailure) as ctx:
                interpret_uninstall_output(255, out)
            self.assertIs(ctx.exception.fatal_kind, kind)


class UninstallCommandTests(unittest.TestCase):
    def service(self, result=None, exc=None):
        calls = []

        def runner(exe, args, timeout):
            calls.append((Path(exe).name, list(args), timeout))
            if exc:
                raise exc
            return result
        return DeviceService(runner=runner, installer=Path("ideviceinstaller.exe")), calls

    def test_exact_command(self):
        svc, calls = self.service(ToolResult(0, OK_OUTPUT, b""))
        svc.uninstall_app("com.example.a")
        self.assertEqual(calls, [("ideviceinstaller.exe", ["--uninstall", "com.example.a"], 180)])

    def test_invalid_id_never_reaches_the_command(self):
        svc, calls = self.service(ToolResult(0, OK_OUTPUT, b""))
        for bad in ("-U", "com.x y", ""):
            with self.assertRaises(UninstallFailure):
                svc.uninstall_app(bad)
        self.assertEqual(calls, [])

    def test_timeout_is_fatal(self):
        svc, _ = self.service(exc=DeviceError(ErrorKind.TIMEOUT, "slow"))
        with self.assertRaises(UninstallFailure) as ctx:
            svc.uninstall_app("com.example.a")
        self.assertIs(ctx.exception.fatal_kind, ErrorKind.TIMEOUT)


class BatchTests(unittest.TestCase):
    def test_sequential_skip_blocked_and_stop_on_disconnect(self):
        apps = [app("com.a.one"), app("com.apple.Pages"), app("com.a.two"), app("com.a.three"), app("com.a.four")]
        calls, active, peak = [], [0], [0]

        class Svc:
            def uninstall_app(self, bid):
                active[0] += 1
                peak[0] = max(peak[0], active[0])
                calls.append(bid)
                time.sleep(0.01)
                active[0] -= 1
                if bid == "com.a.three":
                    raise UninstallFailure("No iPhone connected", ErrorKind.NO_DEVICE)

        events = []
        results = run_uninstall_batch(Svc(), apps, lambda *e: events.append(e[0]))
        self.assertEqual(calls, ["com.a.one", "com.a.two", "com.a.three"])   # Pages never attempted
        self.assertEqual(peak[0], 1)
        self.assertEqual([r.outcome for r in results],
                         [Outcome.REMOVED, Outcome.BLOCKED, Outcome.REMOVED, Outcome.FAILED, Outcome.NOT_ATTEMPTED])
        self.assertEqual(events.count("done"), 5)

    def test_individual_failure_continues_and_unexpected_errors_are_failures(self):
        apps = [app("com.a.one"), app("com.a.two"), app("com.a.three")]

        class Svc:
            def uninstall_app(self, bid):
                if bid == "com.a.one":
                    raise UninstallFailure("iPhone reported: APIInternalError")
                if bid == "com.a.two":
                    raise RuntimeError("boom")

        results = run_uninstall_batch(Svc(), apps, lambda *e: None)
        self.assertEqual([r.outcome for r in results], [Outcome.FAILED, Outcome.FAILED, Outcome.REMOVED])

    def test_verification(self):
        a, b = app("com.a.one"), app("com.a.two")
        results = run_uninstall_batch(SimpleNamespace(uninstall_app=lambda bid: None), [a, b], lambda *e: None)
        verified = verify_results(results, present_ids={"com.a.two"})   # b reported removed but still there
        self.assertEqual([r.outcome for r in verified], [Outcome.REMOVED, Outcome.FAILED])
        self.assertIn("Still on the iPhone", verified[1].message)


class SourceSafetyTests(unittest.TestCase):
    def test_uninstall_paths(self):
        pkg = ROOT / "iphone_app_manager"
        sources = {p.relative_to(pkg).as_posix(): p.read_text(encoding="utf-8") for p in pkg.rglob("*.py")}
        callers = sorted(name for name, src in sources.items() if re.search(r"\.uninstall_app\(", src))
        self.assertEqual(callers, ["uninstall.py"])                    # only the batch runner calls it
        self.assertEqual(sorted(n for n, s in sources.items() if '"--uninstall"' in s), ["device.py"])
        batch_callers = sorted(n for n, s in sources.items() if "run_uninstall_batch(" in s and n != "uninstall.py")
        self.assertEqual(batch_callers, ["ui/main_window.py"])
        main = sources["ui/main_window.py"]
        self.assertEqual(len(re.findall(r"run_uninstall_batch\(", main)), 1)
        self.assertIn("on_confirm=self._start_uninstall", main)        # started only by the dialog
        self.assertEqual(len(re.findall(r"self\._start_uninstall\b", main)), 1)
        for name, src in sources.items():
            self.assertNotIn("set_icon_state", src, name)   # Home Screen layout is never touched


# ====================================================================== UI (fake device)
def _png(size: int, rgba=(30, 120, 200, 255)) -> bytes:
    return icon_helper.encode_png(size, size, bytes(rgba) * (size * size))


def fake_fetch_icons(bundle_ids, size, on_icon, cancel, **_kw):
    from iphone_app_manager.app_icons import IconFetchResult
    result = IconFetchResult(requested=len(bundle_ids))
    for bid in bundle_ids:
        if cancel.is_set():
            result.cancelled = True
            break
        on_icon(bid, _png(size))
        result.received += 1
    return result


def fake_fetch_inventory(on_offloaded, on_sizes, cancel, **_kw):
    """No device access: no offloaded apps, no sizes."""
    from iphone_app_manager.app_inventory import InventoryResult
    on_offloaded([])
    on_sizes({})
    return InventoryResult()


class FakeService:
    def __init__(self, apps):
        self.apps = list(apps)
        self.device = DeviceInfo("Test iPhone", "26.0")
        self.calls: list[str] = []
        self.behaviour: dict[str, object] = {}
        self.delay = 0.0
        self.fail_load: DeviceError | None = None
        self.connection = ConnectionType.USB      # the original, USB-only behaviour
        self.target = None
        self.loads = 0
        self._active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def set_connection(self, connection):
        self.connection, self.target = connection, None

    def choose_device(self, udid):
        self.target = None

    def load_snapshot(self, progress=None):
        self.loads += 1
        if self.fail_load:
            raise self.fail_load
        return self.device, list(self.apps)

    def uninstall_app(self, bid):
        with self._lock:
            self._active += 1
            self.peak = max(self.peak, self._active)
        try:
            self.calls.append(bid)
            time.sleep(self.delay)
            behaviour = self.behaviour.get(bid, "ok")
            if isinstance(behaviour, Exception):
                if getattr(behaviour, "fatal", False):
                    self.fail_load = DeviceError(ErrorKind.NO_DEVICE)
                raise behaviour
            if behaviour == "ok":
                self.apps = [a for a in self.apps if a.bundle_id != bid]
            # "lie": reports success but the app stays installed
        finally:
            with self._lock:
                self._active -= 1


APPS = [app("com.alpha.app", "Alpha"), app("com.bravo.app", "Bravo"), app("com.charlie.app", "Charlie"),
        app("com.delta.app", "Delta"), app("ScoreBoard", "ScoreBoard"), app("com.echo.app", "Echo")]


def isolate_from_device(test: unittest.TestCase) -> None:
    """Fake the background fetchers and make ANY helper-process launch fail loudly.

    Patches are started in setUp (a class decorator would not cover setUp, where the window
    and its first background fetches are created).
    """
    def no_helper_processes(*_a, **_k):
        raise AssertionError("a test tried to start a helper process (would contact the real iPhone)")

    for target, replacement in (
        ("iphone_app_manager.ui.main_window.fetch_icons", fake_fetch_icons),
        ("iphone_app_manager.ui.main_window.fetch_inventory", fake_fetch_inventory),
        ("iphone_app_manager.app_icons.subprocess.Popen", no_helper_processes),
        ("iphone_app_manager.app_inventory.subprocess.Popen", no_helper_processes),
    ):
        patcher = mock.patch(target, replacement)
        patcher.start()
        test.addCleanup(patcher.stop)


class UiTests(unittest.TestCase):
    def setUp(self):
        from iphone_app_manager.ui import MainWindow
        isolate_from_device(self)
        self.root = tk.Tk()
        self.service = FakeService(APPS)
        self.w = MainWindow(self.root, self.service)
        self.pump(lambda: self.w.device is not None and not self.w.loading and not self.w.icon_fetching
                  and not self.w.inventory_running)

    def tearDown(self):
        self.w.uninstalling = False
        self.w._on_close()

    def pump(self, condition, timeout=15.0):
        end = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > end:
                self.fail("timed out waiting for UI condition")
            self.root.update()
            time.sleep(0.01)
        self.root.update()

    def ids(self):
        return [a.bundle_id for a in self.w.apps]

    def click_checkbox(self, row: int):
        L = self.w.app_list
        L._on_click(SimpleNamespace(x=L.icons.checkbox_size // 2 + L.p(16), y=row * L.row_h + L.row_h // 2,
                                    state=0))

    def pill_text(self):
        return self.w.count_pill._spec["text"]

    # ---------------------------------------------------------- selection
    def test_individual_and_multiple_selection(self):
        self.assertFalse(self.w.uninstall_button.enabled)
        self.click_checkbox(0)
        self.assertEqual(self.w.checked, {"com.alpha.app"})
        self.assertEqual(self.pill_text(), "1 selected")
        self.assertTrue(self.w.uninstall_button.enabled)
        self.click_checkbox(2)
        self.click_checkbox(3)
        self.assertEqual(self.pill_text(), "3 selected")
        self.click_checkbox(0)
        self.assertEqual(self.w.checked, {"com.charlie.app", "com.delta.app"})

    def test_select_all_deselect_all_and_persistence(self):
        self.w.search_var.set("a")                 # Alpha, Bravo, Charlie, Delta, ScoreBoard (+ ids)
        self.w.select_all()
        selected = set(self.w.checked)
        self.w.search_var.set("")
        self.w.toggle_sort()
        self.assertEqual(self.w.checked, selected)   # search + sort keep selection
        self.w.refresh()
        self.pump(lambda: not self.w.loading)
        self.assertEqual(self.w.checked, selected)   # refresh keeps selection
        self.w.deselect_all()
        self.assertEqual(self.w.checked, set())
        self.assertFalse(self.w.uninstall_button.enabled)

    def test_blocked_apps_cannot_be_uninstalled(self):
        self.service.apps = APPS + [app("com.apple.Pages", "Pages"), app("com.sys.thing", "Thing", "System")]
        self.w.refresh()
        self.pump(lambda: not self.w.loading)
        self.w.checked = {"com.apple.Pages", "com.sys.thing"}
        self.w._render()
        self.assertEqual(self.pill_text(), "2 selected")
        self.assertFalse(self.w.uninstall_button.enabled)
        self.assertIsNone(self.w.open_uninstall_confirmation())

    def test_review_lists_all_selected_even_hidden_by_search(self):
        self.w.checked = {"com.alpha.app", "com.echo.app"}
        self.w.search_var.set("alpha")
        dialog = self.w.open_review()
        self.assertEqual([a.bundle_id for a in self.w.selected_apps()], ["com.alpha.app", "com.echo.app"])
        self.assertEqual(dialog.title_label.cget("text"), "2 apps selected")
        dialog.close()

    # ---------------------------------------------------------- confirmation
    def test_cancel_uninstalls_nothing(self):
        self.w.checked = {"com.alpha.app", "com.bravo.app"}
        self.w._render()
        dialog = self.w.open_uninstall_confirmation()
        self.assertEqual(dialog.title_label.cget("text"), "Uninstall 2 apps?")
        self.assertEqual([a.name for a in dialog.apps], ["Alpha", "Bravo"])
        dialog.cancel()
        for _ in range(20):
            self.root.update()
            time.sleep(0.01)
        self.assertEqual(self.service.calls, [])
        self.assertFalse(self.w.uninstalling)
        # Escape / window close also cancel
        dialog = self.w.open_uninstall_confirmation()
        dialog._on_close_request()
        self.assertEqual((dialog.result, self.service.calls), ("cancel", []))

    def test_launch_and_refresh_never_uninstall(self):
        self.w.checked = {a.bundle_id for a in APPS}
        for _ in range(3):
            self.w.refresh()
            self.pump(lambda: not self.w.loading)
        self.assertEqual(self.service.calls, [])

    # ---------------------------------------------------------- uninstall runs
    def run_uninstall(self, ids):
        self.w.checked = set(ids)
        self.w._render()
        dialog = self.w.open_uninstall_confirmation()
        dialog.confirm()
        self.pump(lambda: not self.w.uninstalling and not self.w.loading)
        return self.w.progress_dialog

    def test_successful_bulk_uninstall(self):
        self.service.delay = 0.05
        kept_icon = self.w.icons._real_icons["com.charlie.app"]
        progress = self.run_uninstall(["com.alpha.app", "com.bravo.app", "ScoreBoard"])
        self.assertEqual(self.service.calls, ["com.alpha.app", "com.bravo.app", "ScoreBoard"])
        self.assertEqual(self.service.peak, 1)                                   # strictly sequential
        self.assertEqual(self.ids(), ["com.charlie.app", "com.delta.app", "com.echo.app"])
        self.assertEqual(self.w.checked, set())
        self.assertEqual(self.pill_text(), "0 selected")
        self.assertIs(self.w.icons._real_icons["com.charlie.app"], kept_icon)    # icons preserved
        self.assertNotIn("com.alpha.app", self.w.icons._real_icons)
        self.assertEqual(progress.title_label.cget("text"), "Uninstall complete")
        self.assertEqual(progress.message_label.cget("text"), "3 removed")
        self.assertEqual(progress.processed, 3)
        progress._done()

    def test_failures_are_reported_and_stay_selected(self):
        self.service.behaviour = {"com.bravo.app": UninstallFailure("iPhone reported: APIInternalError"),
                                  "com.charlie.app": "lie"}
        progress = self.run_uninstall(["com.alpha.app", "com.bravo.app", "com.charlie.app"])
        outcomes = {r.app.bundle_id: r.outcome for r in self.w.last_uninstall_results}
        self.assertEqual(outcomes, {"com.alpha.app": Outcome.REMOVED, "com.bravo.app": Outcome.FAILED,
                                    "com.charlie.app": Outcome.FAILED})   # "lie" caught by verification
        self.assertEqual(self.w.checked, {"com.bravo.app", "com.charlie.app"})
        self.assertIn("com.bravo.app", self.ids())
        self.assertEqual(progress.title_label.cget("text"), "Uninstall finished with problems")
        self.assertEqual(progress.message_label.cget("text"), "1 removed  ·  2 failed")

    def test_disconnection_during_uninstall(self):
        self.service.behaviour = {"com.bravo.app": UninstallFailure("No iPhone connected", ErrorKind.NO_DEVICE)}
        progress = self.run_uninstall(["com.alpha.app", "com.bravo.app", "com.charlie.app", "com.delta.app"])
        self.assertEqual(self.service.calls, ["com.alpha.app", "com.bravo.app"])   # stopped, no retries
        outcomes = [r.outcome for r in self.w.last_uninstall_results]
        self.assertEqual(outcomes, [Outcome.REMOVED, Outcome.FAILED, Outcome.NOT_ATTEMPTED, Outcome.NOT_ATTEMPTED])
        self.assertIsNotNone(self.w.error)                       # refresh failed: device gone
        self.assertEqual(self.w.status_pill._spec["text"], "Not connected")
        self.assertIn("couldn't be refreshed", progress.note.cget("text"))
        self.assertEqual(self.w.checked, {"com.bravo.app", "com.charlie.app", "com.delta.app"})
        progress._done()
        self.assertIsNone(self.w.progress_dialog)

    def test_ui_stays_responsive_and_refresh_is_blocked_while_uninstalling(self):
        self.service.delay = 0.4
        self.w.checked = {"com.alpha.app", "com.bravo.app", "com.charlie.app", "com.delta.app"}
        self.w._render()
        self.w.open_uninstall_confirmation().confirm()
        gaps, last = [], time.perf_counter()
        loads_before = self.service.loads
        while self.w.uninstalling:
            self.w.refresh()                 # must be ignored while uninstalling
            self.root.update()
            now = time.perf_counter()
            gaps.append(now - last)
            last = now
            time.sleep(0.01)
        self.assertLess(max(gaps), 0.25, f"UI blocked for {max(gaps):.2f}s")
        self.assertEqual(self.service.loads, loads_before + 1)   # only the automatic post-uninstall refresh
        self.assertFalse(self.w.progress_dialog.running)


if __name__ == "__main__":
    unittest.main()
