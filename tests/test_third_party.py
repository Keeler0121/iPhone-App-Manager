"""Third-party licensing tests: the generated THIRD-PARTY-NOTICES.txt, the verbatim licence files, the source
bundle that accompanies the release and the hashes that tie them to the verified originals.

Nothing here builds the installer or the portable ZIP, runs an installer, or talks to an iPhone. These tests are
checks on the repository's licence data; they are not a statement that the release is legally compliant.
"""
from __future__ import annotations

import getpass
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PACKAGING))

import runtime_policy as rp  # noqa: E402
import third_party as tp  # noqa: E402
from iphone_app_manager import config  # noqa: E402

APP_DIR = ROOT / "dist" / "iPhone App Manager"
ZSTD = Path(r"C:\msys64\usr\bin\zstd.exe")

# SHA-256 of the four MSYS2 source archives and their signatures as verified when they were obtained from
# https://repo.msys2.org/mingw/sources/ (the audit's SHA256SUMS.txt). Kept here independently of third_party.py.
# (The MSYS2 libimobiledevice 1.3.0-18 package is no longer bundled: the release builds 1.4.0 from upstream.)
VERIFIED_SOURCE_HASHES = {
    "mingw-w64-ideviceinstaller-1.1.1-2.src.tar.zst": "8998367b0bdfdaf06cb8987a7db77dba231c2e6e6f87e24c6c0da6209df38a5b",
    "mingw-w64-libimobiledevice-glue-1.3.2-1.src.tar.zst": "ee156ff49a69840c1e919d50de5d06d935765882bd24fe74ff496f535f0fcdc3",
    "mingw-w64-libplist-2.7.0-4.src.tar.zst": "0170254ac2a3e4fa0c88ec974a4e6d6a1e1b91d3da14d91b9b147a336c09a015",
    "mingw-w64-libusbmuxd-2.1.1-1.src.tar.zst": "d5d11d66e65e3926892b9f1301b8c75a4472f68184f86b21874026bcd4c28797",
    "mingw-w64-ideviceinstaller-1.1.1-2.src.tar.zst.sig": "decdc5acb55e115fa9e8470a713823e3279a77447677f47627788041badef299",
    "mingw-w64-libimobiledevice-glue-1.3.2-1.src.tar.zst.sig": "6efd5d988c150a858823f8d4f67080e8eee4354babfe222b3b6a1d262ef3ed38",
    "mingw-w64-libplist-2.7.0-4.src.tar.zst.sig": "b4b269ff6460c77bd2848a824d21f1b2804d9b5a8ff57028aedd9107f383550d",
    "mingw-w64-libusbmuxd-2.1.1-1.src.tar.zst.sig": "8bdbb6b1bf4bc3a4d940391fb50a8036f3f8a1440f949336ea1c5d7201237565",
}
# Upstream release tarballs (no signature is published): hashes computed from the files downloaded from the
# project's GitHub release pages, and matching the "digest" GitHub reports for the libimobiledevice asset.
VERIFIED_UPSTREAM_HASHES = {
    "libimobiledevice-1.4.0.tar.bz2": "23cc0077e221c7d991bd0eb02150a0d49199bcca1ddf059edccee9ffd914939d",
    "libtatsu-1.0.5.tar.bz2": "536fa228b14f156258e801a7f4d25a3a9dd91bb936bf6344e23171403c57e440",
}
BUILD_SCRIPT = PACKAGING / "build_libimobiledevice.sh"


def expected_sha256sums() -> str:
    script = hashlib.sha256(BUILD_SCRIPT.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    rows = (sorted((n, h) for n, h in VERIFIED_SOURCE_HASHES.items() if n.endswith(".zst")) +
            sorted(VERIFIED_UPSTREAM_HASHES.items()) + [(BUILD_SCRIPT.name, script)] +
            sorted((n, h) for n, h in VERIFIED_SOURCE_HASHES.items() if n.endswith(".sig")))
    return "".join(f"{h} *{n}\n" for n, h in rows)

# Third-party e-mail addresses that appear inside verbatim upstream licence texts (not personal data of ours).
UPSTREAM_EMAILS = {"info@libzip.org", "jloup@gzip.org", "jseward@acm.org", "madler@alumni.caltech.edu",
                   "tomstdenis@gmail.com"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

ENTRY_HEADINGS = [
    "ideviceinstaller 1.1.1-2", "libimobiledevice 1.4.0", "libimobiledevice-glue 1.3.2-1", "libusbmuxd 2.1.1-1",
    "libplist 2.7.0-4", "openssl 4.1.0-1", "libzip 1.12.1-1", "zlib 1.4-2", "bzip2 1.0.8-4", "xz 5.8.4-1",
    "zstd 1.5.7-2", "Python 3.12.10", "OpenSSL 3.0.16", "Tcl/Tk 8.6.15", "libffi 3.4.4", "Expat 2.7.1",
    "zlib 1.3.1", "libmpdec 2.5.1", "PyInstaller 6.22.3", "Inno Setup 6.7.3",
]
EXPECTED_LICENCE_FILES = {
    # project-specific texts from the exact upstream tarballs (in the MSYS2 source packages, or the libimobiledevice
    # 1.4.0 tarball kept in packaging/third-party-sources)
    "ideviceinstaller-1.1.1-COPYING.txt", "ideviceinstaller-1.1.1-AUTHORS.txt",
    "libimobiledevice-1.4.0-COPYING.LESSER.txt", "libimobiledevice-1.4.0-AUTHORS.txt",
    "libplist-2.7.0-COPYING.LESSER.txt", "libplist-2.7.0-COPYING-GPLv2.txt", "libplist-2.7.0-AUTHORS.txt",
    "libplist-2.7.0-MIT-time64.txt", "libplist-2.7.0-MIT-jsmn.txt",
    "libimobiledevice-glue-1.3.2-COPYING.txt", "libimobiledevice-glue-1.3.2-LibTomCrypt-notice.txt",
    "libusbmuxd-2.1.1-COPYING.txt", "libusbmuxd-2.1.1-AUTHORS.txt",
    # Python 3.12.10 components, PyInstaller, Tcl/Tk, Inno Setup
    "python-3.12.10-LICENSE.txt", "python-openssl-3.0.16-LICENSE.txt", "python-expat-2.7.1-COPYING.txt",
    "python-libffi-3.4.4-LICENSE.txt", "python-zlib-1.3.1-LICENSE.txt", "python-libmpdec-2.5.1-LICENSE.txt",
    "tcltk-8.6.15-license.terms.txt", "pyinstaller-6.22.3-COPYING.txt", "innosetup-6.7.3-license.txt",
}
MSYS2_OTHER_LICENCE_FILES = {"openssl-LICENSE.txt", "libzip-LICENSE.txt", "zlib-LICENSE.txt", "bzip2-LICENSE.txt",
                             "xz-COPYING.txt", "xz-COPYING.0BSD.txt", "zstd-LICENSE.txt"}
OBSOLETE_GENERIC_NAMES = {
    "ideviceinstaller-COPYING.GPLv2.txt", "libimobiledevice-COPYING.GPLv2.txt", "libimobiledevice-COPYING.LGPLv2.1.txt",
    "libimobiledevice-glue-COPYING.LGPLv2.1.txt", "libplist-COPYING.GPLv2.txt", "libplist-COPYING.LGPLv2.1.txt",
    "libusbmuxd-COPYING.LGPLv2.1.txt", "python-LICENSE.txt", "tcltk-license.terms.txt",
    # the libimobiledevice 1.3.0 texts: that version is no longer bundled
    "libimobiledevice-1.3.0-COPYING.LESSER.txt", "libimobiledevice-1.3.0-AUTHORS.txt",
}


def load_build_script():
    spec = importlib.util.spec_from_file_location("build_script", PACKAGING / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def block(text: str, heading: str) -> str:
    """The notice entry that starts with ``heading`` (up to the next blank line that precedes a non-indented line)."""
    match = re.search(rf"(?m)^{re.escape(heading)}[^\n]*\n(?:(?:[ ]+[^\n]*|)\n)*?(?=^\S)", text + "\nEND\n")
    assert match, heading
    return " ".join(match.group(0).split())          # whitespace-normalised (entries wrap across lines)


MSYS2_AVAILABLE = config.MSYS2_BIN.is_dir() and (Path(r"C:\msys64\usr\bin\pacman.exe")).is_file()


class NoticesContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = tp.build_notices("iPhone App Manager", "1.0.0")

    def test_all_expected_entries_are_present(self):
        for heading in ENTRY_HEADINGS:
            self.assertRegex(self.text, rf"(?m)^{re.escape(heading)}", heading)
        self.assertRegex(self.text, r"(?m)^Microsoft Visual C\+\+ Redistributable for Visual Studio 2015-2022 \(x64\)")

    def test_msys2_versions_match_the_source_packages(self):
        for key, pkg in tp.SOURCE_PACKAGE_BY_NAME.items():
            self.assertRegex(self.text, rf"(?m)^{re.escape(key)} {re.escape(pkg.version)}$")
            self.assertIn(f"SHA-256 {pkg.sha256}", self.text)
            self.assertIn(pkg.archive, self.text)
        # libimobiledevice is no longer an MSYS2 package: it is built from the upstream 1.4.0 tarball
        self.assertEqual(sorted(tp.SOURCE_PACKAGE_BY_NAME), sorted(
            ["ideviceinstaller", "libplist", "libimobiledevice-glue", "libusbmuxd"]))

    def test_libimobiledevice_1_4_0_is_documented_as_built_from_upstream_not_as_an_msys2_binary(self):
        lm = tp.UPSTREAM_SOURCE_BY_NAME["libimobiledevice"]
        self.assertEqual((lm.version, lm.archive, lm.shipped), ("1.4.0", "libimobiledevice-1.4.0.tar.bz2", True))
        entry = block(self.text, "libimobiledevice 1.4.0")
        self.assertIn("NOT an MSYS2 binary", entry)
        self.assertIn("a172604", entry)
        self.assertIn("unmodified upstream release tarball libimobiledevice-1.4.0.tar.bz2", entry)
        self.assertIn("build_libimobiledevice.sh", entry)
        self.assertIn("No patches are applied", entry)
        self.assertIn(f"SHA-256 {lm.sha256}", entry)
        self.assertIn("publishes no signature", entry)
        self.assertIn("64 source and header files", entry)
        self.assertNotIn("1.3.0-18", self.text)
        self.assertNotIn("libimobiledevice-1.3.0", self.text)
        intro = " ".join(self.text.split())
        self.assertIn("EXCEPT libimobiledevice-1.0.dll and ideviceinfo.exe", intro)
        self.assertNotIn("These are unmodified binaries from the MSYS2 project", intro)

    def test_libtatsu_is_documented_as_a_build_time_prerequisite_only(self):
        lt = tp.UPSTREAM_SOURCE_BY_NAME["libtatsu"]
        self.assertEqual((lt.version, lt.shipped), ("1.0.5", False))
        entry = block(self.text, "libimobiledevice 1.4.0")
        self.assertIn(f"libtatsu {lt.version}", entry)
        self.assertIn(f"SHA-256 {lt.sha256}", entry)
        self.assertIn("NOT part of this release", entry)
        self.assertIn("Neither file imports libtatsu.dll or libcurl", entry)
        self.assertNotRegex(self.text, r"(?m)^libtatsu ")                  # no component entry: nothing of it ships
        self.assertNotRegex(self.text, r"(?m)^curl ")

    def test_licence_identifiers_per_component(self):
        t = self.text
        self.assertIn("GPL-2.0-or-later", block(t, "ideviceinstaller 1.1.1-2"))
        for heading in ("libimobiledevice 1.4.0", "libimobiledevice-glue 1.3.2-1", "libusbmuxd 2.1.1-1"):
            self.assertIn("LGPL-2.1-or-later", block(t, heading), heading)
        plist = block(t, "libplist 2.7.0-4")
        self.assertIn("LGPL-2.1-or-later", plist)
        self.assertIn("MIT", plist)
        self.assertIn("Apache-2.0", block(t, "OpenSSL 3.0.16"))
        self.assertIn("Apache-2.0", block(t, "openssl 4.1.0-1"))
        self.assertIn("MIT", block(t, "libffi 3.4.4"))
        self.assertIn("MIT", block(t, "Expat 2.7.1"))
        self.assertIn("Zlib", block(t, "zlib 1.3.1"))
        self.assertIn("BSD-2-Clause", block(t, "libmpdec 2.5.1"))
        self.assertIn("Python Software Foundation", block(t, "Python 3.12.10"))
        self.assertIn("Bootloader Exception", block(t, "PyInstaller 6.22.3"))
        self.assertIn("Apache License, Version 2.0", block(t, "PyInstaller 6.22.3"))

    def test_no_obsolete_ideviceinfo_gpl_claim(self):
        self.assertNotIn("ideviceinfo: GPL", self.text)
        self.assertNotRegex(self.text, r"LGPL-2\.1-or-later \(ideviceinfo")
        entry = block(self.text, "libimobiledevice 1.4.0")
        self.assertIn("ideviceinfo is LGPL, not GPL", entry)
        self.assertIn("tools/ideviceinfo.c", entry)
        self.assertIn("tools/idevicesetlocation.c", entry)               # the one GPL program that is NOT bundled
        self.assertNotRegex(entry, r"Licence\s*:\s*GPL")

    def test_libplist_qualification_is_retained(self):
        entry = block(self.text, "libplist 2.7.0-4")
        self.assertIn("Open point (kept deliberately)", entry)
        self.assertIn('"GPL-2.0-or-later AND LGPL-2.1-or-later"', entry)
        self.assertIn("has NOT been established", entry)
        self.assertIn("GPL reference is retained", entry)
        self.assertIn("212 files", entry)
        self.assertIn("libplist-2.7.0-COPYING-GPLv2.txt", entry)

    def test_libplist_investigation_findings_are_recorded_without_dropping_the_gpl_reference(self):
        entry = block(self.text, "libplist 2.7.0-4")
        self.assertIn("\"GPL2+\" from the package's first version (libplist 1.12, 2014)", entry)
        self.assertIn("2.3.0 update (2023-05-13)", entry)
        self.assertIn("without stating a reason", entry)
        self.assertIn("MSYS2 has not documented why its GPL entry exists", entry)
        self.assertIn("003-fix-py-soext.patch", entry)
        self.assertIn("GPL v3 or later", entry)
        self.assertIn("GPL reference is retained here rather than removed", entry)
        self.assertIn("not been reviewed by a lawyer", entry)

    def test_microsoft_distributable_code_condition_is_stated_as_not_established(self):
        t = " ".join(self.text.split())
        i = t.index("Microsoft Distributable Code inside Python")
        para = t[i:i + 1400]
        self.assertIn("require distributors and end users to agree to terms", para)
        self.assertIn("does not currently present end-user terms", para)
        self.assertIn("has NOT been established that this condition is met", para)
        self.assertIn("does not include Microsoft's Visual C++ Redistributable", para)
        self.assertNotRegex(para, r"(?i)is (fully )?compliant|complies with")

    def test_python_xz_5_2_5_is_described_separately_from_msys2_xz_5_8_4(self):
        t = self.text
        entry = block(t, "xz/liblzma 5.2.5")
        self.assertIn("separate from the MSYS2 xz 5.8.4 in section 1", entry)
        self.assertIn("Public domain", entry)
        self.assertIn("131 carry a public-domain dedication", entry)
        self.assertIn("_lzma.pyd", entry)
        self.assertIn("python.props and get_externals.bat", entry)
        self.assertIn("This software includes code from XZ Utils", entry)
        self.assertIn("belong to the separate MSYS2 xz 5.8.4", entry)
        self.assertNotIn("not separately verified", t)
        msys2 = block(t, "xz 5.8.4-1")
        self.assertIn("0BSD", msys2)
        self.assertNotIn("5.2.5", msys2)

    def test_microsoft_prerequisite_wording_is_retained(self):
        t = self.text
        self.assertIn(rp.VC_DOWNLOAD_PAGE, t)
        self.assertIn("NOT INCLUDED", t)
        self.assertIn(".".join(map(str, rp.VC_MINIMUM[:3])), t)
        self.assertIn("administrator rights", t)
        self.assertIn("Windows Universal C Runtime (UCRT) - NOT INCLUDED", t)
        self.assertIn("no longer bundles ucrtbase.dll", t)
        self.assertIn("Additional Conditions for this", t)

    def test_inno_setup_is_acknowledged_for_the_installer_only(self):
        t = self.text
        self.assertIn("5. Installer only: Inno Setup", t)
        self.assertIn("not to the portable ZIP", t)
        self.assertIn("Copyright (C) 1997-2026 Jordan Russell", t)
        self.assertIn("Martijn Laan", t)

    def test_source_bundle_scope_is_not_overstated(self):
        t = " ".join(self.text.split())
        self.assertIn("FIVE components", t)
        self.assertIn("four MSYS2 source packages and the upstream libimobiledevice 1.4.0 tarball", t)
        self.assertIn("It contains nothing else", t)
        self.assertIn("does not cover the other", t)
        self.assertIn("no libtatsu code is in the release", t)
        self.assertIn(tp.bundle_name("1.0.0"), t)
        for src in tp.UPSTREAM_SOURCES:
            self.assertIn(f"{src.sha256} {src.archive}", t)                 # (whitespace-normalised text)

    def test_notices_make_no_compliance_claim(self):
        self.assertIn("not a statement that every obligation has been met", self.text)
        self.assertIn("not been reviewed by a lawyer", self.text)
        self.assertNotRegex(self.text, r"(?i)\bfully compliant\b|\blegally compliant\b|guarantees? (of )?compliance")

    def test_generation_is_deterministic_and_text_is_ascii(self):
        again = tp.build_notices("iPhone App Manager", "1.0.0")
        self.assertEqual(self.text, again)
        self.text.encode("ascii")

    def test_every_licence_file_named_in_the_notices_exists(self):
        named = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9._+-]*\.txt", self.text))
        named -= {"SHA256SUMS.txt", "THIRD-PARTY-NOTICES.txt", "COPYING.txt"}      # COPYING.txt: PyInstaller's own name, quoted
        shipped = set(tp.licence_file_names()) | MSYS2_OTHER_LICENCE_FILES
        missing = {n for n in named if n not in shipped and not n.startswith("mingw-w64-")}
        self.assertEqual(missing, set())
        for n in EXPECTED_LICENCE_FILES:                                  # and every committed text is referenced
            self.assertIn(n, self.text, n)


class LicenceFileTests(unittest.TestCase):
    def test_manifest_covers_exactly_the_expected_files(self):
        self.assertEqual(set(tp.licence_file_names()), EXPECTED_LICENCE_FILES)

    def test_committed_licence_files_match_their_recorded_hashes(self):
        self.assertEqual(tp.verify_licence_files(), [])

    def test_licence_files_have_the_expected_content(self):
        def text(name):
            return " ".join((tp.LICENCES_DIR / name).read_bytes().decode("utf-8", "replace").split())
        self.assertIn("GNU GENERAL PUBLIC LICENSE", text("ideviceinstaller-1.1.1-COPYING.txt")[:200])
        for name in ("libimobiledevice-1.4.0-COPYING.LESSER.txt", "libplist-2.7.0-COPYING.LESSER.txt",
                     "libimobiledevice-glue-1.3.2-COPYING.txt", "libusbmuxd-2.1.1-COPYING.txt"):
            self.assertIn("GNU LESSER GENERAL PUBLIC LICENSE", text(name)[:200], name)
            self.assertIn("Version 2.1", text(name)[:300], name)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", text("libplist-2.7.0-COPYING-GPLv2.txt")[:200])
        self.assertIn("Michael G Schwern", text("libplist-2.7.0-MIT-time64.txt"))
        self.assertIn("The MIT License", text("libplist-2.7.0-MIT-time64.txt"))
        self.assertIn("Serge A. Zaitsev", text("libplist-2.7.0-MIT-jsmn.txt"))
        self.assertIn("Tom St Denis", text("libimobiledevice-glue-1.3.2-LibTomCrypt-notice.txt"))
        self.assertIn("Expat maintainers", text("python-expat-2.7.1-COPYING.txt"))
        self.assertIn("Permission is hereby granted", text("python-expat-2.7.1-COPYING.txt"))
        self.assertIn("Anthony Green", text("python-libffi-3.4.4-LICENSE.txt"))
        self.assertIn("Stefan Krah", text("python-libmpdec-2.5.1-LICENSE.txt"))
        self.assertIn("SUCH DAMAGE", text("python-libmpdec-2.5.1-LICENSE.txt"))
        self.assertIn("Jean-loup Gailly", text("python-zlib-1.3.1-LICENSE.txt"))
        self.assertIn("Apache License", text("python-openssl-3.0.16-LICENSE.txt"))
        self.assertIn("Regents of the University of California", text("tcltk-8.6.15-license.terms.txt"))
        self.assertIn("Bootloader Exception", text("pyinstaller-6.22.3-COPYING.txt"))
        self.assertIn("Apache License", text("pyinstaller-6.22.3-COPYING.txt"))
        self.assertIn("Jordan Russell", text("innosetup-6.7.3-license.txt"))
        self.assertIn("Microsoft Distributable Code", text("python-3.12.10-LICENSE.txt"))

    @unittest.skipUnless(ZSTD.is_file(), "MSYS2 zstd not available")
    def test_project_texts_are_byte_identical_to_the_source_archives(self):
        import io
        import tarfile
        wanted = {
            ("ideviceinstaller", "mingw-w64-ideviceinstaller-1.1.1-2", "ideviceinstaller-1.1.1.tar.gz",
             "ideviceinstaller-1.1.1"): {"COPYING": "ideviceinstaller-1.1.1-COPYING.txt",
                                         "AUTHORS": "ideviceinstaller-1.1.1-AUTHORS.txt"},
            ("libplist", "mingw-w64-libplist-2.7.0-4", "libplist-2.7.0.tar.bz2", "libplist-2.7.0"):
                {"COPYING.LESSER": "libplist-2.7.0-COPYING.LESSER.txt", "COPYING": "libplist-2.7.0-COPYING-GPLv2.txt",
                 "AUTHORS": "libplist-2.7.0-AUTHORS.txt"},
            ("libimobiledevice-glue", "mingw-w64-libimobiledevice-glue-1.3.2-1",
             "libimobiledevice-glue-1.3.2.tar.bz2", "libimobiledevice-glue-1.3.2"):
                {"COPYING": "libimobiledevice-glue-1.3.2-COPYING.txt"},
            ("libusbmuxd", "mingw-w64-libusbmuxd-2.1.1-1", "libusbmuxd-2.1.1.tar.bz2", "libusbmuxd-2.1.1"):
                {"COPYING": "libusbmuxd-2.1.1-COPYING.txt", "AUTHORS": "libusbmuxd-2.1.1-AUTHORS.txt"},
        }
        for (comp, pkg, tarname, top), files in wanted.items():
            raw = subprocess.run([str(ZSTD), "-dc", str(tp.SOURCES_DIR / f"{pkg}.src.tar.zst")],
                                 capture_output=True, check=True).stdout
            outer = tarfile.open(fileobj=io.BytesIO(raw))
            inner = tarfile.open(fileobj=io.BytesIO(outer.extractfile(f"mingw-w64-{comp}/{tarname}").read()))
            for member, shipped in files.items():
                self.assertEqual(inner.extractfile(f"{top}/{member}").read(), (tp.LICENCES_DIR / shipped).read_bytes(),
                                 shipped)

    def test_libimobiledevice_texts_are_byte_identical_to_the_upstream_1_4_0_tarball(self):
        import tarfile
        with tarfile.open(tp.SOURCES_DIR / "libimobiledevice-1.4.0.tar.bz2", "r:bz2") as tar:
            for member, shipped in (("COPYING.LESSER", "libimobiledevice-1.4.0-COPYING.LESSER.txt"),
                                    ("AUTHORS", "libimobiledevice-1.4.0-AUTHORS.txt")):
                self.assertEqual(tar.extractfile(f"libimobiledevice-1.4.0/{member}").read(),
                                 (tp.LICENCES_DIR / shipped).read_bytes(), shipped)

    def test_generic_xz_licence_copies_are_no_longer_used_for_the_five_packages(self):
        for name in OBSOLETE_GENERIC_NAMES:
            self.assertFalse((tp.LICENCES_DIR / name).exists(), name)
        self.assertNotIn('"xz/COPYING.GPLv2"', (PACKAGING / "build.py").read_text(encoding="utf-8"))
        self.assertNotIn("COMPONENTS", (PACKAGING / "build.py").read_text(encoding="utf-8"))


class PinnedVersionTests(unittest.TestCase):
    def test_documented_sources_provide_every_bundled_file(self):
        build = load_build_script()
        provided = (list(tp.MSYS2_SOURCE_FILES) + list(tp.BUILT_FILES) +
                    [f for entry in tp.MSYS2_OTHER for f in entry[5]])
        self.assertEqual(sorted(provided), sorted(build.TOOLS + build.DLLS))
        self.assertEqual(sorted(tp.PINNED_TOOL_SHA256), sorted(build.TOOLS + build.DLLS))
        self.assertEqual(set(tp.BUILT_FILES), {"libimobiledevice-1.0.dll", "ideviceinfo.exe"})

    @unittest.skipUnless(MSYS2_AVAILABLE, "MSYS2 not installed")
    def test_pinned_hashes_match_the_installed_msys2_files(self):
        for name, want in tp.PINNED_TOOL_SHA256.items():
            if name in tp.BUILT_FILES:                                    # built from upstream, not an MSYS2 file
                continue
            got = hashlib.sha256((config.MSYS2_BIN / name).read_bytes()).hexdigest().upper()
            self.assertEqual(got, want, name)

    def test_built_files_match_their_pins_and_are_not_the_msys2_1_3_0_files(self):
        self.assertEqual(tp.verify_built_files(), [])
        for name in tp.BUILT_FILES:
            got = hashlib.sha256((tp.BUILT_DIR / name).read_bytes()).hexdigest().upper()
            self.assertEqual(got, tp.PINNED_TOOL_SHA256[name], name)
        # the hashes of the MSYS2 libimobiledevice 1.3.0-18 files that the 1.0.1 release shipped
        for old in ("7E57F601ED44351895D10DD1A72FED44AEA137F97ED32AF51EE5E897987A14E5",
                    "61F8D3D9FDBD29762D303C53010FCB7CF53B3A8BFC6246790E01A34EB8263FDB"):
            self.assertNotIn(old, tp.PINNED_TOOL_SHA256.values())

    def test_built_files_do_not_depend_on_libtatsu_or_curl(self):
        for name in tp.BUILT_FILES:
            data = (tp.BUILT_DIR / name).read_bytes().lower()
            for needle in (b"tatsu", b"libcurl", b"nghttp", b"ngtcp2", b"libssh2", b"libpsl"):
                self.assertNotIn(needle, data, f"{name} mentions {needle!r}")
        for name in ("libimobiledevice-1.0.dll", "ideviceinfo.exe"):
            self.assertIn(b"libplist-2.0.dll", (tp.BUILT_DIR / name).read_bytes())

    def test_tool_source_takes_only_the_two_built_files_from_the_pinned_build(self):
        build = load_build_script()
        for name in build.TOOLS + build.DLLS:
            want = tp.BUILT_DIR if name in tp.BUILT_FILES else config.MSYS2_BIN
            self.assertEqual(build.tool_source(name), want / name, name)

    def test_bundled_dll_list_has_no_libtatsu_or_curl_files(self):
        build = load_build_script()
        for name in build.TOOLS + build.DLLS:
            self.assertIsNone(re.search(r"(?i)tatsu|curl|nghttp|ngtcp2|libssh2|libpsl", name), name)
        with tempfile.TemporaryDirectory() as tmp:
            build.verify_no_unneeded_runtime_files(Path(tmp))                 # an empty folder passes
            (Path(tmp) / "libtatsu.dll").write_bytes(b"x")
            with self.assertRaises(SystemExit):
                build.verify_no_unneeded_runtime_files(Path(tmp))

    def test_verify_bundled_tools_fails_on_a_changed_file(self):
        build = load_build_script()
        with tempfile.TemporaryDirectory() as tmp:
            for f in build.TOOLS + build.DLLS:
                (Path(tmp) / f).write_bytes(b"not the documented file")
            with self.assertRaises(SystemExit):
                build.verify_bundled_tools(Path(tmp))

    @unittest.skipUnless(sys.version_info[:3] == (3, 12, 10), "documented Python build not in use")
    def test_python_runtime_matches_the_documented_versions(self):
        self.assertEqual(tp.python_runtime_mismatches(), [])

    def test_pins_name_the_documented_versions(self):
        self.assertEqual(tp.PYTHON_PINS, {"python": "3.12.10", "openssl": "3.0.16", "expat": "2.7.1", "zlib": "1.3.1",
                                          "libmpdec": "2.5.1", "tcl": "8.6.15", "pyinstaller": "6.22.3",
                                          "libffi": "3.4.4"})


class SourceBundleTests(unittest.TestCase):
    def test_committed_source_files_match_the_verified_hashes(self):
        self.assertEqual(tp.verify_source_files(), [])
        for name, want in VERIFIED_SOURCE_HASHES.items():
            got = hashlib.sha256((tp.SOURCES_DIR / name).read_bytes()).hexdigest()
            self.assertEqual(got, want, name)
        for pkg in tp.SOURCE_PACKAGES:
            self.assertEqual(VERIFIED_SOURCE_HASHES[pkg.archive], pkg.sha256)
            self.assertEqual(VERIFIED_SOURCE_HASHES[pkg.signature], pkg.sig_sha256)
        self.assertEqual(len(tp.SOURCE_PACKAGES), 4)
        for src in tp.UPSTREAM_SOURCES:
            self.assertEqual(VERIFIED_UPSTREAM_HASHES[src.archive], src.sha256)
            data = (tp.SOURCES_DIR / src.archive).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), src.sha256, src.archive)
            self.assertEqual(len(data), src.size, src.archive)
        self.assertEqual(sorted(VERIFIED_UPSTREAM_HASHES), sorted(s.archive for s in tp.UPSTREAM_SOURCES))

    def test_source_folder_holds_exactly_the_documented_files(self):
        on_disk = {p.name for p in tp.SOURCES_DIR.iterdir() if p.is_file()}
        self.assertEqual(on_disk, set(VERIFIED_SOURCE_HASHES) | set(VERIFIED_UPSTREAM_HASHES) | {"README.txt"})
        self.assertFalse([n for n in on_disk if "libimobiledevice-1.3.0" in n])      # the 1.3.0 package is gone

    def test_verify_source_files_detects_tampering_and_omissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(tp.SOURCES_DIR, tmp, dirs_exist_ok=True)
            self.assertEqual(tp.verify_source_files(Path(tmp)), [])
            (Path(tmp) / tp.SOURCE_PACKAGES[2].archive).write_bytes(b"changed")
            (Path(tmp) / tp.SOURCE_PACKAGES[0].signature).unlink()
            problems = tp.verify_source_files(Path(tmp))
            self.assertTrue(any("hash mismatch" in p for p in problems))
            self.assertTrue(any("missing" in p for p in problems))
            with self.assertRaises(SystemExit):
                tp.make_source_bundle(Path(tmp) / "out", "1.0.0", sources_dir=Path(tmp))

    def make(self, tmp: str) -> Path:
        return tp.make_source_bundle(Path(tmp), "1.0.0")

    def test_bundle_contents_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self.make(tmp)
            self.assertEqual(bundle.name, "Third-Party-Source-Code-1.0.0.zip")
            with zipfile.ZipFile(bundle) as z:
                self.assertIsNone(z.testzip())
                top = "Third-Party-Source-Code-1.0.0/"
                names = [i.filename for i in z.infolist()]
                self.assertEqual(sorted(n[len(top):] for n in names),
                                 sorted(list(VERIFIED_SOURCE_HASHES) + list(VERIFIED_UPSTREAM_HASHES) +
                                        [BUILD_SCRIPT.name, "README.txt", "SHA256SUMS.txt"]))
                self.assertEqual(len(names), 13)
                self.assertTrue(all(n.startswith(top) for n in names))
                self.assertEqual({i.compress_type for i in z.infolist()}, {zipfile.ZIP_STORED})
                for name, want in {**VERIFIED_SOURCE_HASHES, **VERIFIED_UPSTREAM_HASHES}.items():
                    self.assertEqual(hashlib.sha256(z.read(top + name)).hexdigest(), want, name)
                    self.assertEqual(z.read(top + name), (tp.SOURCES_DIR / name).read_bytes(), name)   # byte-for-byte
                self.assertEqual(z.read(top + BUILD_SCRIPT.name), BUILD_SCRIPT.read_bytes().replace(b"\r\n", b"\n"))
                self.assertNotIn(b"\r", z.read(top + BUILD_SCRIPT.name))              # bash cannot run a CRLF script
                self.assertEqual(z.read(top + "SHA256SUMS.txt").decode("ascii"), expected_sha256sums())
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest().upper()
            self.assertEqual((Path(tmp) / "Third-Party-Source-Code-1.0.0.sha256").read_text(encoding="ascii"),
                             f"{digest} *{bundle.name}\n")

    def test_bundle_is_reproducible(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertEqual(self.make(a).read_bytes(), self.make(b).read_bytes())

    def test_bundle_readme_states_scope_and_makes_no_overclaims(self):
        text = (tp.SOURCES_README).read_text(encoding="utf-8")
        flat = " ".join(text.split())
        for pkg in tp.SOURCE_PACKAGES:
            self.assertIn(pkg.archive, text)
        for src in tp.UPSTREAM_SOURCES:
            self.assertIn(src.archive, text)
        self.assertIn(tp.BUILD_SCRIPT_NAME, text)
        self.assertIn("FIVE third-party components", flat)
        self.assertIn("does NOT cover any other component", flat)
        self.assertIn("PKGBUILD", text)
        self.assertIn("patches", text)
        self.assertIn("upstream source archive", text)
        self.assertIn("The author did not rebuild them", flat)             # the four MSYS2 components
        self.assertIn("No claim is made that the four MSYS2 binaries can be reproduced", flat)
        self.assertIn("built by the author from the unmodified 1.4.0 tarball", flat)
        self.assertIn("No patches are applied", flat)
        self.assertIn("Upstream publishes no signature", flat)
        self.assertIn("BUILD-TIME prerequisite only", flat)                # libtatsu
        self.assertIn(tp.MSYS2_SOURCES_URL, text)
        self.assertIn("5F94 4B02 7F7F E209 1985 AA2E FA11 531A A0AA 7F57", text)
        self.assertIn("MSYS2's metadata also lists GPL-2.0-or-later", flat)
        self.assertNotIn("NOT been rebuilt", text)                          # that statement was true of 1.0.1 only
        self.assertNotIn("mingw-w64-libimobiledevice-1.3.0", text)

    def test_build_script_matches_the_pinned_sources_and_has_unix_line_endings(self):
        script = BUILD_SCRIPT.read_bytes()
        self.assertNotIn(b"\r", script)
        text = script.decode("utf-8")
        for src in tp.UPSTREAM_SOURCES:
            self.assertIn(src.archive, text)
            self.assertIn(src.sha256, text)
        self.assertIn("libtatsu.dll", text)                                  # the no-libtatsu-import check
        self.assertIn("make install-strip", text)
        self.assertIn("--no-insert-timestamp", text)
        self.assertNotRegex(text, r"(?m)^\s*patch\b")                        # no patches are applied
        self.assertIn(BUILD_SCRIPT.name, (PACKAGING / ".." / ".gitattributes").resolve().read_text(encoding="utf-8"))

    @unittest.skipUnless(Path(r"C:\Users").is_dir() and any(
        Path(r"C:\Users").glob("*/iPhone-App-Manager-Licensing-Audit/Third-Party-Source-Code-1.0.0.zip")),
        "audit copy of the verified bundle not present")
    def test_archives_equal_those_in_the_audit_bundle(self):
        audit = next(Path(r"C:\Users").glob("*/iPhone-App-Manager-Licensing-Audit/Third-Party-Source-Code-1.0.0.zip"))
        with tempfile.TemporaryDirectory() as tmp:
            top = "Third-Party-Source-Code-1.0.0/"
            with zipfile.ZipFile(self.make(tmp)) as ours, zipfile.ZipFile(audit) as theirs:
                for name in VERIFIED_SOURCE_HASHES:                    # the four MSYS2 packages are unchanged since 1.0.0
                    self.assertEqual(ours.read(top + name), theirs.read(top + name), name)

    def test_build_script_adds_the_bundle_to_the_release_output(self):
        source = (PACKAGING / "build.py").read_text(encoding="utf-8")
        self.assertIn("third_party.make_source_bundle(out_dir or DIST / \"release\", config.APP_VERSION)", source)
        self.assertIn("step(\"5. Third-party source bundle (separate release asset)\")", source)
        self.assertIn("--source-bundle-only", source)
        self.assertLess(source.index("write_licences(APP_DIR / \"licenses\")"),
                        source.index("build_source_bundle()\n\n    if \"--installer\""))

    def test_bundle_is_not_inside_the_app_folder_or_installer_script(self):
        iss = (PACKAGING / "installer.iss").read_text(encoding="utf-8")
        self.assertNotIn("Third-Party-Source-Code", iss)                  # separate asset, not packed into the app


class GeneratedReleaseFolderTests(unittest.TestCase):
    """Generate the licenses folder into a temporary folder and check what would enter the release."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dest = Path(cls.tmp.name) / "licenses"
        cls.build = load_build_script()
        cls.build.write_licences(cls.dest, check_environment=False, include_msys2_texts=MSYS2_AVAILABLE)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def files(self):
        return {p.name for p in self.dest.iterdir()}

    def test_exactly_the_expected_files_are_generated(self):
        expected = EXPECTED_LICENCE_FILES | {"THIRD-PARTY-NOTICES.txt"}
        if MSYS2_AVAILABLE:
            expected |= MSYS2_OTHER_LICENCE_FILES
        self.assertEqual(self.files(), expected)
        self.assertFalse(self.files() & OBSOLETE_GENERIC_NAMES)

    def test_every_generated_file_is_non_empty_and_listed_texts_are_verbatim(self):
        for p in self.dest.iterdir():
            self.assertGreater(p.stat().st_size, 0, p.name)
        for name, info in tp.load_licence_manifest().items():
            self.assertEqual(hashlib.sha256((self.dest / name).read_bytes()).hexdigest(), info["sha256"], name)

    def test_notices_file_matches_the_generator_and_uses_windows_line_endings(self):
        raw = (self.dest / "THIRD-PARTY-NOTICES.txt").read_bytes()
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        text = raw.decode("utf-8").replace("\r\n", "\n")
        if MSYS2_AVAILABLE:
            self.assertEqual(text, tp.build_notices("iPhone App Manager", config.APP_VERSION,
                                                    {e[0]: e[1] for e in tp.MSYS2_OTHER}))

    def test_no_personal_information_in_generated_files(self):
        identifiers = {x for x in (getpass.getuser(), os.environ.get("USERNAME"), os.environ.get("USER"),
                                   Path.home().name, os.environ.get("COMPUTERNAME")) if x and len(x) > 2}
        authored = ["THIRD-PARTY-NOTICES.txt"]
        for p in self.dest.iterdir():
            data = p.read_text(encoding="utf-8", errors="replace")
            for ident in identifiers:
                self.assertNotIn(ident.lower(), data.lower(), f"{p.name} contains {ident!r}")
            self.assertNotRegex(data, r"(?i)[A-Z]:\\Users\\", p.name)
            self.assertNotIn(str(ROOT), data, p.name)
            found = set(EMAIL.findall(data))
            self.assertLessEqual(found, UPSTREAM_EMAILS, f"{p.name}: {found - UPSTREAM_EMAILS}")
            if p.name in authored:
                self.assertEqual(found, set(), p.name)

    def test_no_personal_information_in_the_source_bundle_text_files(self):
        for name in ("README.txt",):
            data = tp.SOURCES_README.read_text(encoding="utf-8")
            self.assertEqual(EMAIL.findall(data), [], name)
            self.assertNotRegex(data, r"(?i)[A-Z]:\\Users\\")
            for ident in (getpass.getuser(), Path.home().name):
                if ident and len(ident) > 2:
                    self.assertNotIn(ident.lower(), data.lower())
        self.assertEqual(EMAIL.findall(tp.sha256sums_text()), [])


class DocumentationConsistencyTests(unittest.TestCase):
    def read(self, name):
        return " ".join((ROOT / name).read_text(encoding="utf-8").split())

    def test_readme_and_release_notes_describe_the_source_bundle_accurately(self):
        for name in ("README.md", "RELEASE_NOTES.md"):
            text = self.read(name)
            self.assertIn(tp.bundle_name(config.APP_VERSION), text, name)
            self.assertRegex(text, r"(?i)only those five|covers only those five", name)
            for component in ("ideviceinstaller", "libimobiledevice-glue", "libusbmuxd", "libplist"):
                self.assertIn(component, text, name)

    def test_libplist_qualification_appears_in_the_documents(self):
        for name in ("README.md", "RELEASE_NOTES.md"):
            text = self.read(name)
            self.assertIn("libplist", text)
            self.assertRegex(text, r"(?i)not (fully )?resolved|not been established|could not be established", name)
            self.assertIn("GPL-2.0-or-later", text, name)
            self.assertIn("no GPL-licensed source file", text, name)

    def test_documents_make_no_compliance_claim_and_no_obsolete_ideviceinfo_claim(self):
        for name in ("README.md", "RELEASE_NOTES.md"):
            text = self.read(name)
            self.assertNotRegex(text, r"(?i)\blegally compliant\b|\bfully compliant\b", name)
            self.assertNotIn("ideviceinfo: GPL", text, name)
            self.assertNotIn("some tools GPL-2.0-or-later", text, name)
            self.assertNotIn("Source for these components is available from their upstream projects and from MSYS2", text, name)
        self.assertRegex(self.read("README.md"), r"not (been )?reviewed by a lawyer")
        self.assertRegex(self.read("RELEASE_NOTES.md"), r"not been reviewed by a lawyer")

    def test_documents_name_the_inno_setup_and_python_component_versions(self):
        text = self.read("README.md")
        for fragment in ("Inno Setup 6.7.3", "Python 3.12.10", "OpenSSL 3.0.16", "Tcl/Tk 8.6.15", "libffi 3.4.4",
                         "Expat 2.7.1", "zlib 1.3.1", "libmpdec 2.5.1", "PyInstaller 6.22.3"):
            self.assertIn(fragment, text, fragment)


@unittest.skipUnless((APP_DIR / "licenses" / "python-3.12.10-LICENSE.txt").is_file(),
                     "release not yet rebuilt with the corrected licence notices")
class BuiltReleaseLicenceTests(unittest.TestCase):
    def test_built_licences_folder_is_the_generated_one(self):
        names = {p.name for p in (APP_DIR / "licenses").iterdir()}
        self.assertEqual(names, EXPECTED_LICENCE_FILES | MSYS2_OTHER_LICENCE_FILES | {"THIRD-PARTY-NOTICES.txt"})
        text = (APP_DIR / "licenses" / "THIRD-PARTY-NOTICES.txt").read_bytes().decode("utf-8").replace("\r\n", "\n")
        self.assertEqual(text, tp.build_notices("iPhone App Manager", config.APP_VERSION,
                                                {e[0]: e[1] for e in tp.MSYS2_OTHER}))


if __name__ == "__main__":
    unittest.main()
