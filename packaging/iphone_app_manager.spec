# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for iPhone App Manager (one-folder, windowed build). Run through packaging/build.py,
# which sets IPHONE_APP_MANAGER_VERSION_FILE and cleans the build environment first.
#
# It matches the options build.py used to pass on the command line, plus ONE addition: the Microsoft runtime
# files named in packaging/runtime_policy.py (the app-local UCRT and VCRUNTIME140.dll) are filtered out of
# the collected binaries. The release relies on Windows' own UCRT and on Microsoft's Visual C++
# Redistributable (x64), which the user installs separately.
import os
import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH)                      # injected by PyInstaller: the folder holding this spec
ROOT = SPEC_DIR.parent
sys.path.insert(0, str(SPEC_DIR))
import runtime_policy                          # noqa: E402

VERSION_FILE = os.environ.get("IPHONE_APP_MANAGER_VERSION_FILE", str(ROOT / "build" / "version_info.txt"))

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    # Helper modules are imported dynamically in helper mode (see main.run_helper_mode).
    hiddenimports=['iphone_app_manager.icon_helper', 'iphone_app_manager.inventory_helper'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['unittest', 'pydoc'],
    noarchive=False,
    optimize=0,
)

# Leave out the Microsoft runtime files (exactly the names in runtime_policy.EXCLUDED_RUNTIME_FILES).
_before = len(a.binaries)
a.binaries = runtime_policy.filter_binaries(a.binaries)
print(f"runtime policy: left out {_before - len(a.binaries)} Microsoft runtime file(s) from the binaries")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='iPhone App Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=VERSION_FILE,
    icon=[str(ROOT / 'packaging' / 'app.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='iPhone App Manager',
)
