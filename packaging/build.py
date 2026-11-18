"""Build the folder-based Windows release:  dist\\iPhone App Manager\\iPhone App Manager.exe

Run with the build environment (PyInstaller is installed only there):
    .venv-build\\Scripts\\python.exe packaging\\build.py                  portable folder only
    .venv-build\\Scripts\\python.exe packaging\\build.py --installer      portable folder + installer
    .venv-build\\Scripts\\python.exe packaging\\build.py --installer-only installer from existing folder
The installer (Inno Setup 6) is written to  dist\\installer\\iPhone App Manager Setup <version>.exe

Steps
  1. Draw the app's orange tile icon into packaging\\app.ico (same artwork as the window icon).
  2. Run PyInstaller (one-folder build, no console window, Windows version information).
  3. Copy the libimobiledevice tools and every DLL they need into tools\\libimobiledevice,
     verifying the dependency list with MSYS2's ldd so nothing is missed.
  4. Write licence notices for everything bundled, plus a short README.txt.
The source project is never modified (build output goes to build\\ and dist\\ only).
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
APP_NAME = "iPhone App Manager"
APP_DIR = DIST / APP_NAME
sys.path.insert(0, str(ROOT))

from iphone_app_manager import config  # noqa: E402

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

# (MSYS2 package, licence, licence files, source URL, files it provides)
COMPONENTS = [
    ("ideviceinstaller", "GPL-2.0-or-later", ["xz/COPYING.GPLv2"],
     "https://github.com/libimobiledevice/ideviceinstaller", ["ideviceinstaller.exe"]),
    ("libimobiledevice", "LGPL-2.1-or-later (ideviceinfo: GPL-2.0-or-later)",
     ["xz/COPYING.LGPLv2.1", "xz/COPYING.GPLv2"],
     "https://github.com/libimobiledevice/libimobiledevice", ["libimobiledevice-1.0.dll", "ideviceinfo.exe"]),
    ("libimobiledevice-glue", "LGPL-2.1-or-later", ["xz/COPYING.LGPLv2.1"],
     "https://github.com/libimobiledevice/libimobiledevice-glue", ["libimobiledevice-glue-1.0.dll"]),
    ("libusbmuxd", "LGPL-2.1-or-later", ["xz/COPYING.LGPLv2.1"],
     "https://github.com/libimobiledevice/libusbmuxd", ["libusbmuxd-2.0.dll"]),
    ("libplist", "GPL-2.0-or-later AND LGPL-2.1-or-later", ["xz/COPYING.LGPLv2.1", "xz/COPYING.GPLv2"],
     "https://github.com/libimobiledevice/libplist", ["libplist-2.0.dll"]),
    ("openssl", "Apache-2.0", ["openssl/LICENSE"], "https://www.openssl.org/source/",
     ["libssl-4-x64.dll", "libcrypto-4-x64.dll"]),
    ("libzip", "BSD-3-Clause", ["libzip/LICENSE"], "https://libzip.org/", ["libzip.dll"]),
    ("zlib", "Zlib", ["zlib/LICENSE"], "https://zlib.net/", ["zlib1.dll"]),
    ("bzip2", "bzip2-1.0.6", ["bzip2/LICENSE"], "https://sourceware.org/bzip2/", ["libbz2-1.dll"]),
    ("xz", "0BSD (liblzma)", ["xz/COPYING", "xz/COPYING.0BSD"], "https://tukaani.org/xz/", ["liblzma-5.dll"]),
    ("zstd", "BSD-3-Clause OR GPL-2.0-only", ["zstd/LICENSE"], "https://github.com/facebook/zstd", ["libzstd.dll"]),
]


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
def ldd_deps(binary: Path) -> set[str]:
    out = subprocess.run([str(LDD), str(binary)], capture_output=True, text=True, check=True).stdout
    deps = set()
    for line in out.splitlines():
        name, _, location = line.strip().partition(" => ")
        if location and "/ucrt64/" in location.replace("\\", "/").lower():
            deps.add(name.strip())
    return deps


def copy_tools(dest: Path) -> None:
    missing = [f for f in TOOLS + DLLS if not (MSYS2_BIN / f).is_file()]
    if missing:
        sys.exit(f"Missing in {MSYS2_BIN}: {missing}")
    if LDD.is_file():
        needed = set()
        for f in TOOLS + DIRECT_DLLS:
            needed |= ldd_deps(MSYS2_BIN / f)
        unlisted = sorted(needed - set(DLLS))
        if unlisted:
            sys.exit(f"DLL list is incomplete - also needed: {unlisted}")
        print(f"ldd check: all {len(needed)} MSYS2 dependencies are bundled")
    else:
        print("WARNING: ldd not found - dependency list not re-verified")
    dest.mkdir(parents=True, exist_ok=True)
    for f in TOOLS + DLLS:
        shutil.copy2(MSYS2_BIN / f, dest / f)
    print(f"copied {len(TOOLS)} tools + {len(DLLS)} DLLs to {dest.relative_to(ROOT)}")


# ---------------------------------------------------------------------------------------- licences
def package_version(name: str) -> str:
    if not PACMAN.is_file():
        return "unknown"
    out = subprocess.run([str(PACMAN), "-Q", f"mingw-w64-ucrt-x86_64-{name}"], capture_output=True, text=True)
    return out.stdout.split()[-1] if out.returncode == 0 and out.stdout.strip() else "unknown"


def write_licences(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    lines = [f"{APP_NAME} {config.APP_VERSION} - third-party components",
             "=" * 60, "",
             "The folder tools\\libimobiledevice contains unmodified binaries from the MSYS2 project",
             "(https://www.msys2.org, UCRT64 environment). They are separate programs/libraries that",
             f"{APP_NAME} runs or loads; their licences are reproduced in this folder.",
             "Source code for each component is available from the URL listed, and the exact MSYS2",
             "package sources from https://packages.msys2.org/ (search for the package name).", ""]
    for name, licence, files, url, provides in COMPONENTS:
        version = package_version(name)
        copied = []
        for rel in files:
            src = LICENSES_SRC / rel
            if not src.is_file():
                sys.exit(f"Licence file missing: {src}")
            target = dest / f"{name}-{Path(rel).name}.txt"
            shutil.copy2(src, target)
            copied.append(target.name)
        lines += [f"{name} {version}",
                  f"  MSYS2 package : mingw-w64-ucrt-x86_64-{name}",
                  f"  Licence       : {licence}",
                  f"  Files         : {', '.join(provides)}",
                  f"  Source        : {url}",
                  f"  Licence text  : {', '.join(copied)}", ""]
    # Python runtime and Tcl/Tk bundled by PyInstaller.
    base = Path(sys.base_prefix)
    # Tcl and Tk share the same licence terms; Python's install ships the text with Tk.
    tcl_terms = next(iter(sorted((base / "tcl").glob("tcl8*/license.terms")) +
                          sorted((base / "tcl").glob("tk8*/license.terms"))), None)
    for label, src, target in (("Python", base / "LICENSE.txt", "python-LICENSE.txt"),
                               ("Tcl/Tk", tcl_terms, "tcltk-license.terms.txt")):
        if not (src and Path(src).is_file()):
            sys.exit(f"{label} licence text not found")
        shutil.copy2(src, dest / target)
        lines += [f"{label} runtime (bundled by PyInstaller)", f"  Licence text  : {target}", ""]
    lines += ["PyInstaller bootloader: GPL-2.0 with the PyInstaller bootloader exception",
              "  (https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt)", "",
              "Apple Mobile Device Support (needed to talk to an iPhone over USB) is NOT included;",
              "it is installed by Apple's 'Apple Devices' app from the Microsoft Store."]
    (dest / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(list(dest.iterdir()))} licence files to {dest.relative_to(ROOT)}")


def write_readme(path: Path) -> None:
    path.write_text(f"""{APP_NAME} {config.APP_VERSION}
{'=' * (len(APP_NAME) + len(config.APP_VERSION) + 1)}

Launch:   double-click "{APP_NAME}.exe" in this folder.
          Keep the whole folder together - the program needs the _internal and tools folders.

Requires: Windows 10 or 11 (64-bit)
          Apple's "Apple Devices" app (Microsoft Store) - it provides the iPhone USB driver/service.
          An iPhone connected by USB, unlocked, and set to trust this computer.

Not needed: Python, MSYS2 or any developer tools - everything else is included.

Built:    {date.today().isoformat()}
Licences: see the licenses folder.
""", encoding="utf-8")


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
    subprocess.run([str(find_iscc()), "/Q", f"/DAppVersion={config.APP_VERSION}", f"/DSourceDir={APP_DIR}",
                    f"/DOutputDir={INSTALLER_DIR}", str(INSTALLER_SCRIPT)], check=True)
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
    try:
        import PyInstaller.__main__ as pyinstaller
    except ImportError:
        sys.exit("PyInstaller not found - run this script with .venv-build\\Scripts\\python.exe")

    step("1. App icon and version information")
    icon = PACKAGING / "app.ico"
    make_icon(icon)
    vfile = ROOT / "build" / "version_info.txt"
    vfile.parent.mkdir(exist_ok=True)
    version_file(vfile)
    print(f"icon: {icon.relative_to(ROOT)} ({icon.stat().st_size} bytes)")

    step("2. PyInstaller (one-folder, windowed)")
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
    pyinstaller.run([
        str(ROOT / "main.py"),
        "--name", APP_NAME, "--onedir", "--windowed", "--noconfirm", "--clean",
        "--icon", str(icon), "--version-file", str(vfile),
        "--distpath", str(DIST), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
        # Helper modules are imported dynamically in helper mode (see main.run_helper_mode).
        "--hidden-import", "iphone_app_manager.icon_helper",
        "--hidden-import", "iphone_app_manager.inventory_helper",
        "--exclude-module", "unittest", "--exclude-module", "pydoc",
    ])

    step("3. libimobiledevice tools and DLLs")
    copy_tools(APP_DIR / config.BUNDLED_TOOLS_SUBDIR)

    step("4. Licence notices and README")
    write_licences(APP_DIR / "licenses")
    write_readme(APP_DIR / "README.txt")

    exe = APP_DIR / f"{APP_NAME}.exe"
    size = sum(p.stat().st_size for p in APP_DIR.rglob("*") if p.is_file())
    step(f"Portable release: {exe}  (folder size {size / 1e6:.1f} MB)")

    if "--installer" in args:
        step("5. Installer (Inno Setup)")
        build_installer()


if __name__ == "__main__":
    main()
