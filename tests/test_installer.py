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


def code_section(text: str) -> str:
    return section(text, "Code")


class InstallerPrerequisiteTests(unittest.TestCase):
    """The Visual C++ Redistributable (x64) check in the installer's [Code] section (read from the script;
    the compiled installer's behaviour was exercised in the Sandbox runs recorded in the Task 5 report)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "packaging"))
        import runtime_policy
        cls.policy = runtime_policy
        cls.text = ISS.read_text(encoding="utf-8")
        cls.code = code_section(cls.text)

    def define(self, name: str) -> str:
        match = re.search(rf'^\s*#define {name} (?:"([^"]*)"|(\S+))\s*$', self.text, re.MULTILINE)
        self.assertIsNotNone(match, name)
        return match.group(1) if match.group(1) is not None else match.group(2)

    def test_script_has_a_code_section(self):
        self.assertTrue(self.code.strip())
        self.assertIn("function InitializeSetup(): Boolean;", self.code)

    def test_minimum_version_matches_the_policy(self):
        major, minor, bld, rbld = self.policy.VC_MINIMUM
        self.assertEqual((int(self.define("VcMinMajor")), int(self.define("VcMinMinor")),
                          int(self.define("VcMinBld")), int(self.define("VcMinRbld"))), (major, minor, bld, rbld))
        # every default is overridable from build.py (so the two can never silently diverge)
        for name in ("VcMinMajor", "VcMinMinor", "VcMinBld", "VcMinRbld"):
            self.assertIn(f"#ifndef {name}", self.text)
        build_source = (ROOT / "packaging" / "build.py").read_text(encoding="utf-8")
        for name in ("VcMinMajor", "VcMinMinor", "VcMinBld", "VcMinRbld"):
            self.assertIn(f"/D{name}=", build_source)

    def test_registry_location_download_page_and_values(self):
        self.assertEqual(self.define("VcRuntimeKey"), self.policy.VC_RUNTIME_REGISTRY_KEY)
        self.assertEqual(self.define("VcDownloadUrl"), self.policy.VC_DOWNLOAD_PAGE)
        self.assertIn("VcRuntimeKey = '{#VcRuntimeKey}'", self.code)
        for value in self.policy.VC_RUNTIME_VALUES:
            self.assertIn(f"'{value}'", self.code, value)

    def test_reads_the_64_bit_registry_view_only(self):
        reads = re.findall(r"RegQueryDWordValue\((\w+),", self.code)
        self.assertGreaterEqual(len(reads), 5)
        self.assertEqual(set(reads), {"HKLM64"})
        self.assertNotIn("HKCU", self.code)
        self.assertNotIn("HKLM32", self.code)

    def test_check_is_not_installed_equals_one_alone(self):
        self.assertIn("if Installed <> 1 then Exit;", self.code)                 # requires Installed = 1 ...
        self.assertIn("PackVersionComponents(Major, Minor, Bld, Rbld)", self.code)     # ... and compares the version
        self.assertIn("ComparePackedVersion(Have, Need) >= 0", self.code)
        self.assertIn("Need := PackVersionComponents({#VcMinMajor}, {#VcMinMinor}, {#VcMinBld}, {#VcMinRbld});",
                      self.code)
        self.assertIn("if Major <> {#VcMinMajor} then Exit;", self.code)          # only the v14 family

    def test_three_outcomes_are_distinguished(self):
        for outcome in ("'missing'", "'older'", "'ok'"):
            self.assertIn(f"Result := {outcome};", self.code)
        # a missing key/value leaves the result at 'missing'; a readable-but-low version ends at 'older'
        self.assertLess(self.code.index("Result := 'missing';"), self.code.index("Result := 'older';"))
        self.assertLess(self.code.index("Result := 'older';"), self.code.index("Result := 'ok';"))

    def test_warning_explains_what_to_install(self):
        for fragment in ("was not found on this PC", "is too old (version", "or newer", "is not included in this installer",
                         "will not start until you install it", "{#VcDownloadUrl}", "administrator rights",
                         "Do you want to continue installing iPhone App Manager anyway?"):
            self.assertIn(fragment, self.code, fragment)
        self.assertIn("Microsoft Visual C++ Redistributable (x64)", self.code)
        self.assertIn("{#VcMinMajor}.{#VcMinMinor}.{#VcMinBld}", self.code)

    def test_user_may_continue_and_silent_installs_continue(self):
        # Yes/No question, default answer Yes (also what /SUPPRESSMSGBOXES answers), only "No" stops setup.
        self.assertIn("SuppressibleMsgBox(Msg, mbError, MB_YESNO, IDYES) = IDNO", self.code)
        self.assertIn("Result := True;", self.code)
        self.assertIn("Result := False;", self.code)
        self.assertEqual(self.code.count("Result := False;"), 1)
        self.assertNotIn("Abort", self.code)
        self.assertNotIn("RaiseException", self.code)
        self.assertNotIn("MsgBox(Msg, mbError, MB_OK", self.code)

    def test_ok_runtime_shows_no_warning(self):
        self.assertIn("if Status = 'ok' then Exit;", self.code)
        self.assertLess(self.code.index("if Status = 'ok' then Exit;"), self.code.index("SuppressibleMsgBox("))

    def test_decision_is_logged(self):
        self.assertIn("Log('Visual C++ x64 runtime check: '", self.code)

    def test_prerequisite_is_not_bundled(self):
        files = section(self.joined(), "Files")
        self.assertNotRegex(files, r"(?i)vc_redist|vcredist|VCRUNTIME")
        self.assertNotIn("[Run]\nFilename: \"{tmp}", self.text)       # nothing downloads/launches a redistributable
        self.assertNotRegex(self.text, r"(?i)vc_redist|vcredist")

    def joined(self) -> str:
        return re.sub(r"\\\s*\n\s*", " ", self.text)


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
