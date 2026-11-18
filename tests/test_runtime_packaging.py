"""Microsoft runtime packaging tests: which runtime files are left out of the build, the cleaned build
environment, the PyInstaller spec, and the Visual C++ Redistributable (x64) prerequisite rules.

Nothing here builds the release, runs an installer, touches the registry or talks to an iPhone. The checks that
look at the built release folder are skipped until it has been rebuilt with the runtime exclusions.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PACKAGING))

import runtime_policy as rp  # noqa: E402

APP_DIR = ROOT / "dist" / "iPhone App Manager"
SPEC = PACKAGING / "iphone_app_manager.spec"
ISS = PACKAGING / "installer.iss"
RECORD = ROOT / "build" / "runtime-exclusions.json"

# Dependencies that must never be filtered out (names as collected by PyInstaller).
KEPT = ["python312.dll", "libcrypto-3.dll", "libssl-3.dll", "libffi-8.dll", "tcl86t.dll", "tk86t.dll",
        "zlib1.dll", "_ssl.pyd", "_ctypes.pyd", "_tkinter.pyd", "_decimal.pyd", "pyexpat.pyd", "unicodedata.pyd",
        "base_library.zip", "iPhone App Manager.exe", "libssl-4-x64.dll", "libcrypto-4-x64.dll",
        "libimobiledevice-1.0.dll", "ideviceinfo.exe", "ideviceinstaller.exe", "libplist-2.0.dll",
        "msvcp_win.dll", "ucrtbased.dll", "api-ms-win-power-l1-1-0.txt"]


def load_build_script():
    spec = importlib.util.spec_from_file_location("build_script", PACKAGING / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExcludedFileListTests(unittest.TestCase):
    def test_exactly_42_distinct_files(self):
        self.assertEqual(len(rp.EXCLUDED_RUNTIME_FILES), 42)
        self.assertEqual(len(set(rp.EXCLUDED_RUNTIME_FILES)), 42)
        self.assertEqual(len({f.lower() for f in rp.EXCLUDED_RUNTIME_FILES}), 42)

    def test_the_42_files_break_down_as_identified(self):
        self.assertEqual(rp.UCRT_CORE, ("ucrtbase.dll", "ucrtbase"))
        self.assertEqual(len(rp.UCRT_API_SET_CRT), 13)
        self.assertEqual(len(rp.UCRT_API_SET_CORE), 26)
        self.assertEqual(rp.VC_RUNTIME, ("VCRUNTIME140.dll",))
        self.assertTrue(all(f.startswith("api-ms-win-crt-") for f in rp.UCRT_API_SET_CRT))
        self.assertTrue(all(f.startswith("api-ms-win-core-") for f in rp.UCRT_API_SET_CORE))
        self.assertTrue(all(f.endswith(".dll") for f in rp.UCRT_API_SET_CRT + rp.UCRT_API_SET_CORE))

    def test_every_one_of_the_42_is_excluded(self):
        for name in rp.EXCLUDED_RUNTIME_FILES:
            self.assertTrue(rp.is_excluded_runtime_file(name), name)

    def test_matching_ignores_case_and_folders(self):
        for name in (r"_internal\UCRTBASE.DLL", "_internal/vcruntime140.dll", r"C:\x\API-MS-WIN-CRT-STDIO-L1-1-0.DLL",
                     "Api-Ms-Win-Core-File-L1-1-0.dll"):
            self.assertTrue(rp.is_excluded_runtime_file(name), name)

    def test_no_unrelated_dependency_is_excluded(self):
        for name in KEPT:
            self.assertFalse(rp.is_excluded_runtime_file(name), name)

    def test_only_scoped_runtime_files_are_matched(self):
        """Other Visual C++ runtime names are NOT matched (they are not collected today); a future change
        to that would be a deliberate decision, not an accident of a loose pattern."""
        for name in ("vcruntime140_1.dll", "msvcp140.dll", "concrt140.dll", "vcomp140.dll", "ucrtbased.dll",
                     "api-ms-win-core-path-l1-1-0.exe", "xapi-ms-win-core-file-l1-1-0.dll"):
            self.assertFalse(rp.is_excluded_runtime_file(name), name)

    def test_filter_binaries_drops_exactly_the_excluded_entries(self):
        toc = [(n, rf"C:\somewhere\{n}", "BINARY") for n in rp.EXCLUDED_RUNTIME_FILES]
        toc += [(n, rf"C:\py\{n}", "BINARY") for n in KEPT]
        kept = rp.filter_binaries(toc)
        self.assertEqual([e[0] for e in kept], KEPT)
        self.assertEqual(rp.filter_binaries([]), [])

    def test_find_excluded_files_walks_a_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "_internal").mkdir()
            for n in ("python312.dll", "libffi-8.dll"):
                (base / "_internal" / n).write_bytes(b"x")
            self.assertEqual(rp.find_excluded_files(base), [])
            (base / "_internal" / "VCRUNTIME140.dll").write_bytes(b"x")
            (base / "_internal" / "api-ms-win-crt-runtime-l1-1-0.dll").write_bytes(b"x")
            self.assertEqual(rp.find_excluded_files(base),
                             sorted([r"_internal\VCRUNTIME140.dll", r"_internal\api-ms-win-crt-runtime-l1-1-0.dll"]))

    @unittest.skipUnless((APP_DIR / "_internal").is_dir(), "release not built")
    def test_filter_applied_to_the_real_release_listing_removes_only_the_42(self):
        names = [p.name for p in (APP_DIR / "_internal").iterdir() if p.is_file()]
        removed = {n for n in names if rp.is_excluded_runtime_file(n)}
        self.assertLessEqual(removed, set(rp.EXCLUDED_RUNTIME_FILES))        # never anything unrelated
        for needed in ("python312.dll", "libffi-8.dll", "libcrypto-3.dll", "tcl86t.dll", "tk86t.dll", "zlib1.dll"):
            self.assertIn(needed, names)
            self.assertNotIn(needed, removed)


class CleanBuildEnvironmentTests(unittest.TestCase):
    ENV = {"PATH": r"C:\Program Files\Microsoft\jdk-21\bin;C:\Program Files\Microsoft\jdk-17\bin;C:\tools",
           "JAVA_HOME": r"C:\Program Files\Microsoft\jdk-21", "CLASSPATH": "x", "java_tool_options": "-Xmx1g",
           "TEMP": r"C:\Temp", "USERNAME": "someone"}

    def clean(self):
        return rp.clean_build_environment(self.ENV, base_prefix=r"C:\Python312", system_root=r"C:\Windows")

    def test_path_is_only_python_and_windows(self):
        self.assertEqual(self.clean()["PATH"].split(";"),
                         [r"C:\Python312", r"C:\Python312\DLLs", r"C:\Windows\System32", r"C:\Windows"])

    def test_no_jdk_or_java_variables_survive(self):
        env = self.clean()
        self.assertNotIn("jdk", env["PATH"].lower())
        for key in env:
            self.assertNotIn(key.upper(), ("JAVA_HOME", "CLASSPATH", "JAVA_TOOL_OPTIONS"))

    def test_other_variables_are_kept_and_the_input_is_not_changed(self):
        before = dict(self.ENV)
        env = self.clean()
        self.assertEqual(env["TEMP"], r"C:\Temp")
        self.assertEqual(env["USERNAME"], "someone")
        self.assertEqual(self.ENV, before)

    def test_build_environment_restores_os_environ(self):
        import os
        build = load_build_script()
        before = dict(os.environ)
        with build.build_environment():
            self.assertNotIn("jdk", os.environ["PATH"].lower())
            self.assertEqual(os.environ["PATH"].split(os.pathsep)[0], sys.base_prefix)
        self.assertEqual(dict(os.environ), before)


class SpecFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SPEC.read_text(encoding="utf-8")

    def test_spec_applies_the_runtime_policy_before_collecting(self):
        self.assertIn("import runtime_policy", self.text)
        self.assertIn("a.binaries = runtime_policy.filter_binaries(a.binaries)", self.text)
        self.assertLess(self.text.index("filter_binaries"), self.text.index("coll = COLLECT("))
        self.assertRegex(self.text, r"COLLECT\(\s*exe,\s*a\.binaries,\s*a\.datas")

    def test_spec_keeps_the_previous_build_options(self):
        for fragment in ("name='iPhone App Manager'", "console=False", "excludes=['unittest', 'pydoc']",
                         "'iphone_app_manager.icon_helper'", "'iphone_app_manager.inventory_helper'",
                         "app.ico", "IPHONE_APP_MANAGER_VERSION_FILE", "exclude_binaries=True"):
            self.assertIn(fragment, self.text, fragment)

    def test_build_script_uses_the_spec_in_a_cleaned_environment(self):
        build = load_build_script()
        self.assertEqual(build.SPEC_FILE, SPEC)
        source = (PACKAGING / "build.py").read_text(encoding="utf-8")
        self.assertIn("pyinstaller.run([str(SPEC_FILE)", source)
        self.assertIn("with build_environment():", source)
        self.assertIn("verify_runtime_exclusions(app_dir)", source)
        self.assertNotIn('"--exclude-module"', source)       # options now live in the spec

    def test_verify_runtime_exclusions(self):
        build = load_build_script()
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            internal = app / "_internal"
            internal.mkdir()
            with self.assertRaises(SystemExit):               # required files missing
                build.verify_runtime_exclusions(app)
            for name in build.required_runtime_files():
                (internal / name).write_bytes(b"x")
            build.verify_runtime_exclusions(app)              # clean folder passes
            (internal / "ucrtbase.dll").write_bytes(b"x")
            with self.assertRaises(SystemExit):               # a leaked runtime file fails the build
                build.verify_runtime_exclusions(app)

    def test_release_readme_states_the_prerequisite(self):
        build = load_build_script()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "README.txt"
            build.write_readme(path)
            text = path.read_text(encoding="utf-8")
        self.assertIn("Visual C++ Redistributable", text)
        self.assertIn("NOT included", text)
        self.assertIn(rp.VC_DOWNLOAD_PAGE, text)
        self.assertIn("administrator", text)
        self.assertIn("14.43.34808", text)


@unittest.skipUnless(RECORD.is_file() and (APP_DIR / "_internal").is_dir(),
                     "release not yet built with the runtime exclusions")
class BuiltReleaseRuntimeTests(unittest.TestCase):
    def test_built_release_contains_none_of_the_42_files(self):
        self.assertEqual(rp.find_excluded_files(APP_DIR), [])
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        self.assertEqual(record["found_in_release"], [])
        self.assertEqual(len(record["excluded_files"]), 42)

    def test_built_release_still_has_the_python_runtime(self):
        for name in load_build_script().required_runtime_files():
            self.assertTrue((APP_DIR / "_internal" / name).is_file(), name)


class VcRuntimeRuleTests(unittest.TestCase):
    """The installer repeats this rule in Pascal Script; the structure tests in test_installer.py tie the two
    together, and the Sandbox runs recorded in the Task 5 report exercise the compiled installer."""

    MINIMUM = (14, 43, 34808, 0)

    def test_minimum_is_the_toolset_python_was_built_with(self):
        self.assertEqual(rp.VC_MINIMUM, self.MINIMUM)

    def test_missing_runtime(self):
        self.assertEqual(rp.vc_runtime_status(None), rp.MISSING)                         # no key at all
        self.assertEqual(rp.vc_runtime_status(0, 14, 44, 35211, 0), rp.MISSING)         # key present, Installed=0
        self.assertEqual(rp.vc_runtime_status(2, 14, 44, 35211, 0), rp.MISSING)         # Installed must be exactly 1
        self.assertEqual(rp.vc_runtime_status(1, None, None, None, None), rp.MISSING)   # values unreadable
        self.assertEqual(rp.vc_runtime_status(1, 14, 44, None, 0), rp.MISSING)

    def test_installed_but_older(self):
        self.assertEqual(rp.vc_runtime_status(1, 14, 42, 34438, 0), rp.OLDER)           # what Python 3.12.10 ships
        self.assertEqual(rp.vc_runtime_status(1, 14, 43, 34807, 0), rp.OLDER)           # one build below the minimum
        self.assertEqual(rp.vc_runtime_status(1, 14, 29, 30133, 0), rp.OLDER)
        self.assertEqual(rp.vc_runtime_status(1, 14, 0, 24215, 1), rp.OLDER)            # Visual Studio 2015
        self.assertEqual(rp.vc_runtime_status(1, 12, 99, 99999, 0), rp.OLDER)           # not the v14 family
        self.assertEqual(rp.vc_runtime_status(1, 15, 0, 1, 0), rp.OLDER)                # unknown major: not accepted

    def test_exact_minimum_is_accepted(self):
        self.assertEqual(rp.vc_runtime_status(1, 14, 43, 34808, 0), rp.OK)
        self.assertEqual(rp.vc_runtime_status(1, 14, 43, 34808, None), rp.OK)          # Rbld optional

    def test_newer_v14_runtimes_are_accepted(self):
        self.assertEqual(rp.vc_runtime_status(1, 14, 43, 34808, 1), rp.OK)
        self.assertEqual(rp.vc_runtime_status(1, 14, 43, 34810, 0), rp.OK)
        self.assertEqual(rp.vc_runtime_status(1, 14, 44, 35211, 0), rp.OK)              # installed on the dev PC
        self.assertEqual(rp.vc_runtime_status(1, 14, 52, 37029, 0), rp.OK)              # latest tested (Sandbox)
        self.assertEqual(rp.vc_runtime_status(1, 14, 99, 1, 0), rp.OK)

    def test_comparison_is_numeric_not_textual(self):
        self.assertEqual(rp.vc_runtime_status(1, 14, 100, 1, 0), rp.OK)                 # "100" > "43" numerically
        self.assertEqual(rp.vc_runtime_status(1, 14, 43, 9999, 0), rp.OLDER)            # "9999" < "34808" numerically

    def test_registry_location_and_values(self):
        self.assertEqual(rp.VC_RUNTIME_REGISTRY_KEY, r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64")
        self.assertEqual(rp.VC_RUNTIME_VALUES, ("Installed", "Major", "Minor", "Bld", "Rbld"))
        self.assertEqual(rp.VC_DOWNLOAD_PAGE,
                         "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist")

    def test_policy_module_documents_its_evidence(self):
        doc = rp.__doc__
        for fragment in ("14.43.34808", "linker 14.43", "build 34808", "at least as new"):
            self.assertIn(fragment, doc)


class DocumentationTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def check_prerequisite_text(self, text, where):
        self.assertIn("Visual C++ Redistributable", text, where)
        self.assertIn(rp.VC_DOWNLOAD_PAGE, text, where)
        self.assertRegex(text, r"(?i)not included", where)
        self.assertRegex(text, r"(?i)administrator", where)
        self.assertIn("14.43.34808", text, where)

    def test_readme_states_the_prerequisite(self):
        self.check_prerequisite_text(self.read("README.md"), "README.md")

    def test_release_notes_state_the_prerequisite(self):
        self.check_prerequisite_text(self.read("RELEASE_NOTES.md"), "RELEASE_NOTES.md")

    def test_docs_do_not_claim_windows_10_was_verified(self):
        for name in ("README.md", "RELEASE_NOTES.md"):
            text = self.read(name)
            self.assertNotRegex(text, r"(?i)windows 10[^.\n]*(verified|has been tested|were tested|tested and)", name)
            self.assertNotRegex(text, r"(?i)tested on windows 10", name)

    def test_docs_no_longer_claim_python_and_runtimes_are_all_included(self):
        for name in ("README.md", "RELEASE_NOTES.md"):
            text = self.read(name)
            self.assertNotRegex(text, r"(?i)everything else is included", name)
            self.assertNotRegex(text, r"(?i)no need for (any )?(visual c\+\+|redistributable)", name)


if __name__ == "__main__":
    unittest.main()
