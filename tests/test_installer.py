"""Stage 5.1 tests: the Inno Setup installer definition and build.

These tests only read files - they never run the installer or uninstaller (that has system-wide
side effects and is done manually; see the Stage 5.1 report).
"""
from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from iphone_app_manager import config  # noqa: E402

ISS = ROOT / "packaging" / "installer.iss"
INSTALLER = ROOT / "dist" / "installer" / f"iPhone App Manager Setup {config.APP_VERSION}.exe"


def load_build_script():
    spec = importlib.util.spec_from_file_location("build_script", ROOT / "packaging" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def section(text: str, name: str) -> str:
    match = re.search(rf"^\[{name}\]\s*$(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def setting(text: str, key: str) -> str:
    match = re.search(rf"^{key}=(.*)$", section(text, "Setup"), re.MULTILINE)
    return match.group(1).strip() if match else ""


class InstallerScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = ISS.read_text(encoding="utf-8")
        # join Inno's line continuations ("\" at end of line)
        cls.joined = re.sub(r"\\\s*\n\s*", " ", cls.text)

    def test_per_user_install_without_admin(self):
        self.assertEqual(setting(self.text, "PrivilegesRequired"), "lowest")
        self.assertEqual(setting(self.text, "PrivilegesRequiredOverridesAllowed"), "dialog")
        self.assertEqual(setting(self.text, "DefaultDirName"), r"{autopf}\{#AppName}")

    def test_permanent_app_id(self):
        self.assertRegex(setting(self.text, "AppId"),
                         r"^\{\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}$")

    def test_output_name_and_icon(self):
        self.assertEqual(setting(self.text, "OutputBaseFilename"), "{#AppName} Setup {#AppVersion}")
        self.assertEqual(setting(self.text, "SetupIconFile"), "app.ico")
        self.assertTrue((ROOT / "packaging" / "app.ico").is_file())
        self.assertEqual(setting(self.text, "UninstallDisplayIcon"), r"{app}\{#AppExe}")
        self.assertIn('#define AppName "iPhone App Manager"', self.text)
        self.assertIn('#define AppExe "iPhone App Manager.exe"', self.text)

    def test_installs_the_whole_release_folder(self):
        files = section(self.joined, "Files")
        self.assertIn(r'Source: "{#SourceDir}\*"; DestDir: "{app}"', files)
        self.assertIn("recursesubdirs", files)
        self.assertIn("createallsubdirs", files)

    def test_shortcuts_point_at_installed_exe(self):
        icons = [l for l in section(self.joined, "Icons").splitlines() if l.strip().startswith("Name:")]
        names = [re.search(r'Name: "([^"]+)"', l).group(1) for l in icons]
        self.assertEqual(names, [r"{autoprograms}\{#AppName}", r"{autodesktop}\{#AppName}"])
        for line in icons:
            self.assertIn(r'Filename: "{app}\{#AppExe}"', line)
            self.assertIn(r'WorkingDir: "{app}"', line)
            self.assertIn('AppUserModelID: "{#AppUserModelID}"', line)
        self.assertNotIn("Tasks:", icons[0])                 # Start Menu: always
        self.assertIn('Tasks: desktopicon', icons[1])         # Desktop: offered as an option
        tasks = section(self.joined, "Tasks")
        self.assertIn('Name: "desktopicon"', tasks)
        self.assertNotIn("unchecked", tasks)                  # ticked by default

    def test_taskbar_identity_matches_the_app(self):
        aumid = re.search(r'#define AppUserModelID "([^"]+)"', self.text).group(1)
        self.assertIn(f'SetCurrentProcessExplicitAppUserModelID("{aumid}")', (ROOT / "main.py").read_text())

    def test_uninstaller_only_removes_what_it_installed(self):
        self.assertEqual(section(self.text, "UninstallDelete").strip(), "")
        self.assertEqual(section(self.text, "InstallDelete").strip(), "")
        self.assertEqual(setting(self.text, "CloseApplications"), "yes")

    def test_launch_after_install_is_optional_and_skipped_when_silent(self):
        run = section(self.joined, "Run")
        self.assertIn("postinstall", run)
        self.assertIn("skipifsilent", run)


class InstallerBuildTests(unittest.TestCase):
    def test_build_script_names_the_installer(self):
        build = load_build_script()
        self.assertEqual(build.installer_name(), f"iPhone App Manager Setup {config.APP_VERSION}.exe")
        self.assertEqual(build.INSTALLER_SCRIPT, ISS)

    @unittest.skipUnless(INSTALLER.is_file(), "installer not built")
    def test_built_installer(self):
        data = INSTALLER.read_bytes()
        self.assertEqual(data[:2], b"MZ")                      # Windows executable
        self.assertGreater(len(data), 5_000_000)               # contains the compressed release
        self.assertIn("Inno Setup".encode("utf-16-le"), data)


if __name__ == "__main__":
    unittest.main()
