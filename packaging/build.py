"""Build the folder-based Windows release:  dist\\iPhone App Manager\\iPhone App Manager.exe

Run with the build environment (PyInstaller is installed only there):
    .venv-build\\Scripts\\python.exe packaging\\build.py                  portable folder only
    .venv-build\\Scripts\\python.exe packaging\\build.py --installer      portable folder + installer
    .venv-build\\Scripts\\python.exe packaging\\build.py --installer-only installer from existing folder
    .venv-build\\Scripts\\python.exe packaging\\build.py --source-bundle-only  only the source bundle
The installer (Inno Setup 6) is written to  dist\\installer\\iPhone App Manager Setup <version>.exe
The third-party source bundle is written to  dist\\release\\Third-Party-Source-Code-<version>.zip (+ .sha256)

Steps
  1. Draw the app's orange tile icon into packaging\\app.ico (same artwork as the window icon).
  2. Run PyInstaller from packaging\\iphone_app_manager.spec (one-folder build, no console window, Windows
     version information) in a cleaned environment (PATH reduced to the Python install and Windows, so no
     unrelated runtime files such as a JDK's can be collected). The spec leaves out Microsoft's runtime files
     (app-local UCRT and VCRUNTIME140.dll; see packaging\\runtime_policy.py) and the build then verifies none of
     them is present.
  3. Copy the libimobiledevice tools and every DLL they need into tools\\libimobiledevice,
     verifying the dependency list with MSYS2's ldd so nothing is missed. ideviceinfo.exe and
     libimobiledevice-1.0.dll come from packaging\\third-party-binaries (libimobiledevice 1.4.0, built by
     packaging\\build_libimobiledevice.sh); everything else is copied from the MSYS2 UCRT64 packages.
  4. Write the licence notices (THIRD-PARTY-NOTICES.txt generated from packaging\\third_party.py plus the
     verbatim texts in packaging\\licenses), plus a short README.txt.
  5. Create the separate Third-Party-Source-Code zip from packaging\\third-party-sources and
     packaging\\build_libimobiledevice.sh (hash-verified).
The source project is never modified (build output goes to build\\ and dist\\ only).

The release needs Microsoft's Visual C++ Redistributable (x64) on the user's PC; it is NOT bundled.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
APP_NAME = "iPhone App Manager"
APP_DIR = DIST / APP_NAME
SPEC_FILE = PACKAGING / "iphone_app_manager.spec"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PACKAGING))

from iphone_app_manager import config  # noqa: E402
import runtime_policy  # noqa: E402
import third_party  # noqa: E402

MSYS2_ROOT = Path(r"C:\msys64")
MSYS2_BIN = config.MSYS2_BIN
LDD = MSYS2_ROOT / "usr" / "bin" / "ldd.exe"
PACMAN = MSYS2_ROOT / "usr" / "bin" / "pacman.exe"
LICENSES_SRC = MSYS2_ROOT / "ucrt64" / "share" / "licenses"

TOOLS = ["ideviceinstaller.exe", "ideviceinfo.exe"]
# Loaded directly by the helper processes (ctypes) as well as by the tools.
DIRECT_DLLS = ["libimobiledevice-1.0.dll", "libplist-2.0.dll"]
DLLS = ["libimobiledevice-1.0.dll", "libimobiledevice-glue-1.0.dll", "libplist-2.0.dll", "libusbmuxd-2.0.dll",
        "libssl-4-x64.dll", "libcrypto-4-x64.dll", "libzip.dll", "zlib1.dll", "libbz2-1.dll", "liblzma-5.dll",
        "libzstd.dll"]

# The licence data (versions, licences, notices text, source bundle) lives in packaging/third_party.py and the
# verbatim licence texts in packaging/licenses/. Files provided by each MSYS2 package are listed there.


def step(msg: str) -> None:
    print(f"\n=== {msg}", flush=True)


# ---------------------------------------------------------------------------------------- icon
def make_icon(path: Path) -> None:
    """Multi-size .ico (PNG-compressed entries) drawn with the app's own tile renderer."""
    from iphone_app_manager.ui.icons import draw_tile
    from iphone_app_manager.ui.theme import Colors
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    images = [draw_tile(s, Colors.ORANGE).to_png() for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, blobs = b"", b""
    for s, png in zip(sizes, images):
        dim = 0 if s == 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    path.write_bytes(header + entries + blobs)


def version_file(path: Path) -> None:
    parts = [int(p) for p in config.APP_VERSION.split(".")] + [0] * (4 - len(config.APP_VERSION.split(".")))
    v = tuple(parts[:4])
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('FileVersion', '{config.APP_VERSION}'),
      StringStruct('ProductVersion', '{config.APP_VERSION}'),
      StringStruct('OriginalFilename', '{APP_NAME}.exe'),
      StringStruct('InternalName', '{APP_NAME}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")


# ---------------------------------------------------------------------------------------- tools
def tool_source(name: str) -> Path:
    """Where the build takes a bundled file from: the two files built from the upstream libimobiledevice 1.4.0
    tarball come from packaging/third-party-binaries (pinned); every other file is the MSYS2 package's file."""
    return (third_party.BUILT_DIR if name in third_party.BUILT_FILES else MSYS2_BIN) / name


def ldd_deps(binary: Path) -> set[str]:
    """The MSYS2 UCRT64 DLLs ``binary`` needs (MSYS2's bin folder is put on PATH so a binary kept outside MSYS2
    is resolved the same way). Dependencies found next to the binary or in Windows are not MSYS2 files."""
    env = dict(os.environ, PATH=str(MSYS2_BIN) + os.pathsep + os.environ.get("PATH", ""))
    out = subprocess.run([str(LDD), str(binary)], capture_output=True, text=True, check=True, env=env).stdout
    deps = set()
    for line in out.splitlines():
        name, _, location = line.strip().partition(" => ")
        if location and "/ucrt64/" in location.replace("\\", "/").lower():
            deps.add(name.strip())
    return deps


def copy_tools(dest: Path) -> None:
    missing = [f for f in TOOLS + DLLS if not tool_source(f).is_file()]
    if missing:
        sys.exit(f"Missing in {MSYS2_BIN} or {third_party.BUILT_DIR}: {missing}")
    built = third_party.verify_built_files()
    if built:
        sys.exit(f"The pinned libimobiledevice 1.4.0 build in {third_party.BUILT_DIR} does not match its recorded "
                 f"SHA-256 values: {built}. Rebuild it with packaging/build_libimobiledevice.sh and update "
                 "packaging/third_party.py.")
    if LDD.is_file():
        needed = set()
        for f in TOOLS + DIRECT_DLLS:
            needed |= ldd_deps(tool_source(f))
        unlisted = sorted(needed - set(DLLS))
        if unlisted:
            sys.exit(f"DLL list is incomplete - also needed: {unlisted}")
        unused = sorted(set(DLLS) - needed - set(DIRECT_DLLS))
        print(f"ldd check: all {len(needed)} MSYS2 dependencies are bundled"
              + (f" (bundled but not needed by the tools or helpers: {unused})" if unused else ""))
    else:
        print("WARNING: ldd not found - dependency list not re-verified")
    dest.mkdir(parents=True, exist_ok=True)
    for f in TOOLS + DLLS:
        shutil.copy2(tool_source(f), dest / f)
    print(f"copied {len(TOOLS)} tools + {len(DLLS)} DLLs to {dest.relative_to(ROOT)} "
          f"({len(third_party.BUILT_FILES)} built from upstream libimobiledevice 1.4.0, the rest from MSYS2)")
    verify_bundled_tools(dest)
    verify_no_unneeded_runtime_files(dest)


def verify_no_unneeded_runtime_files(dest: Path) -> None:
    """libimobiledevice 1.4.0 is built against libtatsu/libcurl, but the bundled files must not need them."""
    present = sorted(p.name for p in dest.iterdir() if re.search(r"(?i)tatsu|curl|nghttp|ngtcp2|libssh2|libpsl",
                                                                 p.name))
    if present:
        sys.exit(f"Unexpected libtatsu/libcurl files in the bundled tools: {present}")
    print("tool check: no libtatsu or libcurl files are bundled (the tools do not import them)")


def sha256_of(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def verify_bundled_tools(dest: Path) -> None:
    """The notices describe exact MSYS2 package versions, so the copied files must be those exact files."""
    wrong = [f for f in TOOLS + DLLS if sha256_of(dest / f) != third_party.PINNED_TOOL_SHA256.get(f)]
    if wrong:
        sys.exit(f"Bundled tool files differ from the versions documented in the licence notices: {wrong}. "
                 "Update packaging/third_party.py (versions, licences, hashes) and the source bundle before building.")
    print(f"tool check: all {len(TOOLS + DLLS)} bundled files match the documented versions "
          "(MSYS2 packages, and the pinned libimobiledevice 1.4.0 build)")


# ---------------------------------------------------------------------------------------- licences
def package_version(name: str) -> str:
    if not PACMAN.is_file():
        return "unknown"
    out = subprocess.run([str(PACMAN), "-Q", f"mingw-w64-ucrt-x86_64-{name}"], capture_output=True, text=True)
    return out.stdout.split()[-1] if out.returncode == 0 and out.stdout.strip() else "unknown"


def write_licences(dest: Path, check_environment: bool = True, include_msys2_texts: bool = True) -> None:
    """Write the release's ``licenses`` folder: THIRD-PARTY-NOTICES.txt (generated from packaging/third_party.py)
    plus the verbatim licence texts. Deterministic: it reads only files kept in the repository, except the
    licence files of the six MSYS2 libraries that are not covered by the source bundle (each MSYS2 package ships
    its own), which are checked against the documented package versions.

    ``check_environment`` verifies that the running Python/PyInstaller are the versions the notices document;
    ``include_msys2_texts`` can be switched off by tests that do not need MSYS2.
    """
    problems = third_party.verify_licence_files()
    if problems:
        sys.exit(f"packaging/licenses does not match its manifest: {problems}")
    if check_environment:
        mismatches = third_party.python_runtime_mismatches()
        pyi = third_party.pyinstaller_mismatch()
        if pyi:
            mismatches.append(pyi)
        if mismatches:
            sys.exit("The build environment differs from the versions documented in the licence notices: "
                     f"{mismatches}. Update packaging/third_party.py and packaging/licenses first.")
    dest.mkdir(parents=True, exist_ok=True)
    for name in third_party.licence_file_names():
        shutil.copyfile(third_party.LICENCES_DIR / name, dest / name)
    versions = {}
    if include_msys2_texts:
        for name, pinned, _licence, files, _url, _provides in third_party.MSYS2_OTHER:
            found = package_version(name)
            if found != pinned:
                sys.exit(f"MSYS2 package {name} is {found}, the notices document {pinned}. "
                         "Update packaging/third_party.py first.")
            versions[name] = found
            for rel, shipped in files:
                src = LICENSES_SRC / rel
                if not src.is_file():
                    sys.exit(f"Licence file missing: {src}")
                shutil.copyfile(src, dest / shipped)
    text = third_party.build_notices(APP_NAME, config.APP_VERSION, versions or None)
    with open(dest / "THIRD-PARTY-NOTICES.txt", "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)
    print(f"wrote {len(list(dest.iterdir()))} licence files to {dest}")


def build_source_bundle(out_dir: Path | None = None) -> Path:
    """Create the separate Third-Party-Source-Code zip (and its .sha256) next to the other release files."""
    out = third_party.make_source_bundle(out_dir or DIST / "release", config.APP_VERSION)
    print(f"source bundle: {out}  ({out.stat().st_size} bytes)")
    return out


def write_readme(path: Path) -> None:
    path.write_text(f"""{APP_NAME} {config.APP_VERSION}
{'=' * (len(APP_NAME) + len(config.APP_VERSION) + 1)}

Launch:   double-click "{APP_NAME}.exe" in this folder.
          Keep the whole folder together - the program needs the _internal and tools folders.

Requires: Windows 10 or 11 (64-bit)
          Microsoft Visual C++ Redistributable for Visual Studio 2015-2022 (x64), version
          {'.'.join(map(str, runtime_policy.VC_MINIMUM[:3]))} or newer. It is NOT included. Most PCs already have it; if the program
          does not start ("Failed to load Python DLL"), install the latest x64 version from
          {runtime_policy.VC_DOWNLOAD_PAGE}
          (installing it may need administrator rights).
          Apple's "Apple Devices" app (Microsoft Store) - it provides the iPhone USB driver/service.
          An iPhone connected by USB, unlocked, and set to trust this computer.

Not needed: Python, MSYS2 or any developer tools - everything else is included.

Built:    {date.today().isoformat()}
Licences: see the licenses folder.
""", encoding="utf-8")


# ---------------------------------------------------------------------------------------- PyInstaller
@contextlib.contextmanager
def build_environment():
    """Run the build with a cleaned environment: PATH is reduced to the Python install and the Windows
    folders (so a JDK or other tool on PATH cannot supply runtime DLLs) and Java variables are removed."""
    saved = dict(os.environ)
    cleaned = runtime_policy.clean_build_environment(saved)
    os.environ.clear()
    os.environ.update(cleaned)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def required_runtime_files() -> list[str]:
    """Runtime files that must still be collected (guards against filtering out something unrelated)."""
    return [f"python{sys.version_info.major}{sys.version_info.minor}.dll", "libffi-8.dll", "tcl86t.dll",
            "tk86t.dll", "zlib1.dll"]


def verify_runtime_exclusions(app_dir: Path) -> None:
    """Fail the build if a Microsoft runtime file slipped into the release, or a needed file went missing."""
    leaked = runtime_policy.find_excluded_files(app_dir)
    if leaked:
        sys.exit(f"Microsoft runtime files found in the release ({len(leaked)}): {leaked[:5]} ...")
    internal = app_dir / "_internal"
    missing = [f for f in required_runtime_files() if not (internal / f).is_file()]
    if missing:
        sys.exit(f"Required runtime files are missing from {internal}: {missing}")
    print(f"runtime check: none of the {len(runtime_policy.EXCLUDED_RUNTIME_FILES)} Microsoft runtime files "
          f"is bundled; required files present")


def write_runtime_record(workpath: Path, app_dir: Path) -> Path:
    """Record (in the build folder, never in the release) what the runtime policy did for this build."""
    record = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "excluded_files": list(runtime_policy.EXCLUDED_RUNTIME_FILES),
        "found_in_release": runtime_policy.find_excluded_files(app_dir),
        "minimum_vc_runtime": ".".join(map(str, runtime_policy.VC_MINIMUM[:3])),
    }
    path = Path(workpath) / "runtime-exclusions.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def run_pyinstaller(distpath: Path, workpath: Path, version_file: Path) -> Path:
    """Build the one-folder app from the spec file (cleaned environment). Returns the app folder."""
    import PyInstaller.__main__ as pyinstaller
    app_dir = Path(distpath) / APP_NAME
    if app_dir.exists():
        shutil.rmtree(app_dir)
    with build_environment():
        os.environ["IPHONE_APP_MANAGER_VERSION_FILE"] = str(version_file)   # read by the spec; restored on exit
        pyinstaller.run([str(SPEC_FILE), "--noconfirm", "--clean",
                         "--distpath", str(distpath), "--workpath", str(workpath)])
    verify_runtime_exclusions(app_dir)
    print(f"runtime record: {write_runtime_record(workpath, app_dir)}")
    return app_dir


# ---------------------------------------------------------------------------------------- main
INSTALLER_SCRIPT = PACKAGING / "installer.iss"
INSTALLER_DIR = DIST / "installer"


def find_iscc() -> Path:
    """Inno Setup's command-line compiler (per-user or machine-wide install)."""
    import os
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
                  Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
                  Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe"]
    found = shutil.which("ISCC.exe")
    if found:
        candidates.insert(0, Path(found))
    for path in candidates:
        if path.is_file():
            return path
    sys.exit("Inno Setup 6 (ISCC.exe) not found - install it, e.g. winget install JRSoftware.InnoSetup --scope user")


def installer_name() -> str:
    return f"{APP_NAME} Setup {config.APP_VERSION}.exe"


def build_installer() -> Path:
    """Wrap the portable release folder in a per-user Inno Setup installer."""
    if not (APP_DIR / f"{APP_NAME}.exe").is_file():
        sys.exit(f"Portable release not found in {APP_DIR} - build it first")
    INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
    out = INSTALLER_DIR / installer_name()
    if out.exists():
        out.unlink()
    major, minor, bld, rbld = runtime_policy.VC_MINIMUM
    subprocess.run([str(find_iscc()), "/Q", f"/DAppVersion={config.APP_VERSION}", f"/DSourceDir={APP_DIR}",
                    f"/DOutputDir={INSTALLER_DIR}",
                    f"/DVcMinMajor={major}", f"/DVcMinMinor={minor}", f"/DVcMinBld={bld}", f"/DVcMinRbld={rbld}",
                    str(INSTALLER_SCRIPT)], check=True)
    if not out.is_file():
        sys.exit(f"Inno Setup did not produce {out}")
    print(f"installer: {out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.1f} MB)")
    return out


def main() -> None:
    args = sys.argv[1:]
    if "--installer-only" in args:          # wrap the existing portable release, no rebuild
        step("Installer (Inno Setup)")
        build_installer()
        return
    if "--source-bundle-only" in args:      # just the separate third-party source bundle (dist\release)
        step("Third-party source bundle")
        build_source_bundle()
        return
    try:
        import PyInstaller.__main__  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller not found - run this script with .venv-build\\Scripts\\python.exe")

    step("1. App icon and version information")
    icon = PACKAGING / "app.ico"
    make_icon(icon)
    vfile = ROOT / "build" / "version_info.txt"
    vfile.parent.mkdir(exist_ok=True)
    version_file(vfile)
    print(f"icon: {icon.relative_to(ROOT)} ({icon.stat().st_size} bytes)")

    step("2. PyInstaller (one-folder, windowed; Microsoft runtime files left out)")
    run_pyinstaller(DIST, ROOT / "build", vfile)

    step("3. libimobiledevice tools and DLLs")
    copy_tools(APP_DIR / config.BUNDLED_TOOLS_SUBDIR)

    step("4. Licence notices and README")
    write_licences(APP_DIR / "licenses")
    write_readme(APP_DIR / "README.txt")

    exe = APP_DIR / f"{APP_NAME}.exe"
    size = sum(p.stat().st_size for p in APP_DIR.rglob("*") if p.is_file())
    step(f"Portable release: {exe}  (folder size {size / 1e6:.1f} MB)")

    step("5. Third-party source bundle (separate release asset)")
    build_source_bundle()

    if "--installer" in args:
        step("6. Installer (Inno Setup)")
        build_installer()


if __name__ == "__main__":
    main()
