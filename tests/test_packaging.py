"""Stage 5 tests: packaging. NOTHING here talks to an iPhone or uninstalls anything.

The checks on the built release (dist\\iPhone App Manager) are skipped until it has been built
with:  .venv-build\\Scripts\\python.exe packaging\\build.py
"""
from __future__ import annotations

import importlib.util
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from iphone_app_manager import app_icons, app_inventory, config  # noqa: E402

APP_DIR = ROOT / "dist" / "iPhone App Manager"
EXE = APP_DIR / "iPhone App Manager.exe"


def load_build_script():
    spec = importlib.util.spec_from_file_location("build_script", ROOT / "packaging" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ToolLocationTests(unittest.TestCase):
    def test_source_run_uses_msys2(self):
        self.assertEqual(config.resolve_tools_dir(frozen=False), config.MSYS2_BIN)

    def test_packaged_run_uses_only_bundled_tools(self):
        exe = r"D:\Apps\iPhone App Manager\iPhone App Manager.exe"
        self.assertEqual(config.resolve_tools_dir(frozen=True, executable=exe),
                         Path(r"D:\Apps\iPhone App Manager\tools\libimobiledevice"))


class HelperLaunchTests(unittest.TestCase):
    def test_source_run_uses_python_isolated(self):
        cmd = app_icons.helper_command(42, frozen=False)
        self.assertEqual(cmd[1:3], ["-I", str(app_icons.HELPER_SCRIPT)])
        cmd = app_inventory.helper_command(frozen=False)
        self.assertEqual(cmd[1:3], ["-I", str(app_inventory.HELPER_SCRIPT)])

    def test_packaged_run_relaunches_the_exe(self):
        self.assertEqual(app_icons.helper_command(42, frozen=True),
                         [sys.executable, "--icon-helper", str(config.LIBIMOBILEDEVICE_BIN), "42"])
        self.assertEqual(app_inventory.helper_command(frozen=True),
                         [sys.executable, "--inventory-helper", str(config.LIBIMOBILEDEVICE_BIN)])

    def test_helper_dispatch(self):
        import main
        self.assertIsNone(main.run_helper_mode(["main.py"]))
        self.assertIsNone(main.run_helper_mode(["main.py", "--something-else"]))
        self.assertEqual(main.run_helper_mode(["main.py", "--icon-helper"]), 1)              # bad arguments
        self.assertEqual(main.run_helper_mode(["main.py", "--inventory-helper", r"C:\no\such\dir"]), 4)

    def test_only_two_helper_modes_exist(self):
        import main
        self.assertEqual(main.HELPER_MODES, {"--icon-helper": "icon_helper", "--inventory-helper": "inventory_helper"})


class BuildScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = load_build_script()

    def test_every_bundled_file_has_a_licence_entry(self):
        import third_party
        provided = list(third_party.MSYS2_FIVE_FILES) + [f for entry in third_party.MSYS2_OTHER for f in entry[5]]
        self.assertEqual(sorted(provided), sorted(self.build.TOOLS + self.build.DLLS))

    @unittest.skipUnless(config.MSYS2_BIN.is_dir(), "MSYS2 not installed")
    def test_bundle_list_exists_in_msys2(self):
        for name in self.build.TOOLS + self.build.DLLS:
            self.assertTrue((config.MSYS2_BIN / name).is_file(), name)

    def test_icon_file_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.ico"
            self.build.make_icon(path)
            data = path.read_bytes()
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind), (0, 1))
        sizes = [data[6 + 16 * i] or 256 for i in range(count)]
        self.assertIn(256, sizes)
        self.assertIn(16, sizes)
        first_offset = struct.unpack("<I", data[6 + 12:6 + 16])[0]
        self.assertEqual(data[first_offset:first_offset + 8], b"\x89PNG\r\n\x1a\n")


@unittest.skipUnless(EXE.is_file(), "release not built")
class BuiltReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = load_build_script()

    def test_layout(self):
        tools = APP_DIR / config.BUNDLED_TOOLS_SUBDIR
        for name in self.build.TOOLS + self.build.DLLS:
            self.assertTrue((tools / name).is_file(), name)
        licenses = APP_DIR / "licenses"
        if (licenses / "python-3.12.10-LICENSE.txt").is_file():              # built with the corrected notices
            names = ("THIRD-PARTY-NOTICES.txt", "python-3.12.10-LICENSE.txt", "tcltk-8.6.15-license.terms.txt",
                     "ideviceinstaller-1.1.1-COPYING.txt", "libimobiledevice-1.3.0-COPYING.LESSER.txt",
                     "openssl-LICENSE.txt")
        else:                                                              # release built before that change
            names = ("THIRD-PARTY-NOTICES.txt", "python-LICENSE.txt", "tcltk-license.terms.txt",
                     "ideviceinstaller-COPYING.GPLv2.txt", "libimobiledevice-COPYING.LGPLv2.1.txt",
                     "openssl-LICENSE.txt")
        for name in names:
            self.assertTrue((licenses / name).is_file(), name)
        self.assertTrue((APP_DIR / "README.txt").is_file())
        self.assertTrue((APP_DIR / "_internal").is_dir())

    def test_bundled_tools_are_byte_identical_to_msys2(self):
        if not config.MSYS2_BIN.is_dir():
            self.skipTest("MSYS2 not installed")
        tools = APP_DIR / config.BUNDLED_TOOLS_SUBDIR
        for name in self.build.TOOLS + self.build.DLLS:
            self.assertEqual((tools / name).read_bytes(), (config.MSYS2_BIN / name).read_bytes(), name)

    def test_packaged_exe_helper_modes(self):
        flags = subprocess.CREATE_NO_WINDOW
        r = subprocess.run([str(EXE), "--inventory-helper", r"C:\no\such\dir"], capture_output=True,
                           timeout=60, creationflags=flags, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 4)                                    # library missing -> exit 4
        self.assertIn(b"Could not load libimobiledevice", r.stderr)
        r = subprocess.run([str(EXE), "--icon-helper"], capture_output=True, timeout=60, creationflags=flags,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 1)

    def test_bundled_tool_runs(self):
        tools = APP_DIR / config.BUNDLED_TOOLS_SUBDIR
        r = subprocess.run([str(tools / "ideviceinstaller.exe"), "--version"], capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(r.returncode, 0)
        self.assertIn(b"ideviceinstaller 1.1.1", r.stdout)


if __name__ == "__main__":
    unittest.main()
