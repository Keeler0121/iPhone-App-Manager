"""Microsoft C/C++ runtime policy for the packaged application.

The release does NOT bundle Microsoft's runtime files:

* The Universal C Runtime (UCRT) is a Windows 10/11 system component, so the app-local copies that
  PyInstaller would otherwise collect (``ucrtbase.dll`` and the ``api-ms-win-*`` forwarders) are left out.
* The Visual C++ runtime (``VCRUNTIME140.dll``) comes from Microsoft's own "Visual C++ Redistributable
  for Visual Studio 2015-2022 (x64)", which the user installs separately. The installer checks for it.

This module is the single source of truth for both rules. It is used by ``packaging/build.py``, by the
PyInstaller spec file and by the tests. It has no third-party dependencies.

Why the minimum Visual C++ runtime is 14.43.34808
------------------------------------------------
Microsoft's rule ("Determining which DLLs to redistribute" and "C++ binary compatibility between Visual
Studio versions") is that the Redistributable must be at least as new as the latest build tools used by any
component. The Python 3.12.10 binaries bundled in the app (``python312.dll`` and its extension modules) were
linked with MSVC linker 14.43 and compiled with MSVC build 34808 (read from the PE headers and Rich headers
of the actual files), which is toolset 14.43.34808. The other bundled MSVC-built components (Tcl/Tk 14.41,
OpenSSL 3 14.40, libffi 14.34) are older. So the minimum is 14.43.34808.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# ------------------------------------------------------------------------------------------------
# 1. Files that must NOT be bundled (42 files)
# ------------------------------------------------------------------------------------------------
UCRT_CORE = ("ucrtbase.dll", "ucrtbase")              # "ucrtbase" is an extension-less duplicate PyInstaller wrote
UCRT_API_SET_CRT = tuple(f"api-ms-win-crt-{n}-l1-1-0.dll" for n in (
    "conio", "convert", "environment", "filesystem", "heap", "locale", "math", "process", "runtime",
    "stdio", "string", "time", "utility"))
UCRT_API_SET_CORE = (
    "api-ms-win-core-console-l1-1-0.dll", "api-ms-win-core-datetime-l1-1-0.dll",
    "api-ms-win-core-debug-l1-1-0.dll", "api-ms-win-core-errorhandling-l1-1-0.dll",
    "api-ms-win-core-fibers-l1-1-0.dll", "api-ms-win-core-file-l1-1-0.dll",
    "api-ms-win-core-file-l1-2-0.dll", "api-ms-win-core-file-l2-1-0.dll",
    "api-ms-win-core-handle-l1-1-0.dll", "api-ms-win-core-heap-l1-1-0.dll",
    "api-ms-win-core-interlocked-l1-1-0.dll", "api-ms-win-core-libraryloader-l1-1-0.dll",
    "api-ms-win-core-localization-l1-2-0.dll", "api-ms-win-core-memory-l1-1-0.dll",
    "api-ms-win-core-namedpipe-l1-1-0.dll", "api-ms-win-core-processenvironment-l1-1-0.dll",
    "api-ms-win-core-processthreads-l1-1-0.dll", "api-ms-win-core-processthreads-l1-1-1.dll",
    "api-ms-win-core-profile-l1-1-0.dll", "api-ms-win-core-rtlsupport-l1-1-0.dll",
    "api-ms-win-core-string-l1-1-0.dll", "api-ms-win-core-synch-l1-1-0.dll",
    "api-ms-win-core-synch-l1-2-0.dll", "api-ms-win-core-sysinfo-l1-1-0.dll",
    "api-ms-win-core-timezone-l1-1-0.dll", "api-ms-win-core-util-l1-1-0.dll")
VC_RUNTIME = ("VCRUNTIME140.dll",)

#: The exact 42 file names the 1.0.0 packaging used to include and the next build must leave out.
EXCLUDED_RUNTIME_FILES = UCRT_CORE + UCRT_API_SET_CRT + UCRT_API_SET_CORE + VC_RUNTIME

# Anchored patterns (matched against the lower-cased file name only, never a path). They are deliberately
# narrow: nothing else is excluded (python312.dll, OpenSSL, Tcl/Tk, libffi, zlib1.dll, *.pyd, ... all stay).
_EXCLUDED_NAME_PATTERNS = (
    re.compile(r"^ucrtbase(\.dll)?$"),
    re.compile(r"^api-ms-win-(core|crt)-[a-z0-9-]+\.dll$"),
    re.compile(r"^vcruntime140\.dll$"),
)


def is_excluded_runtime_file(name: str) -> bool:
    """True for the Microsoft runtime files that are not bundled (case-insensitive, name or path)."""
    base = re.split(r"[\\/]", name)[-1].lower()
    return any(p.match(base) for p in _EXCLUDED_NAME_PATTERNS)


def filter_binaries(toc):
    """PyInstaller ``a.binaries`` entries are ``(dest_name, source_path, typecode)``; drop the excluded ones."""
    return [entry for entry in toc if not is_excluded_runtime_file(entry[0])]


def find_excluded_files(folder: Path) -> list[str]:
    """Relative names of excluded runtime files found anywhere under a built folder (should be empty)."""
    return sorted(str(p.relative_to(folder)) for p in Path(folder).rglob("*")
                  if p.is_file() and is_excluded_runtime_file(p.name))


# ------------------------------------------------------------------------------------------------
# 2. Clean build environment (so e.g. a JDK on PATH cannot supply runtime DLLs)
# ------------------------------------------------------------------------------------------------
def clean_search_path(base_prefix: str | None = None, system_root: str | None = None) -> list[str]:
    """The only folders PyInstaller may search for DLLs: the Python install and the Windows folders."""
    base = base_prefix or sys.base_prefix
    root = system_root or os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return [base, os.path.join(base, "DLLs"), os.path.join(root, "System32"), root]


def clean_build_environment(env: dict[str, str] | None = None, base_prefix: str | None = None,
                            system_root: str | None = None) -> dict[str, str]:
    """Return ``env`` (default: a copy of ``os.environ``) with ``PATH`` reduced to :func:`clean_search_path`
    and Java-related variables removed."""
    out = dict(os.environ if env is None else env)
    out["PATH"] = os.pathsep.join(clean_search_path(base_prefix, system_root))
    for key in list(out):
        if key.upper() in ("JAVA_HOME", "JDK_HOME", "JRE_HOME", "CLASSPATH", "_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS"):
            del out[key]
    return out


# ------------------------------------------------------------------------------------------------
# 3. Required Visual C++ runtime (installed separately by the user)
# ------------------------------------------------------------------------------------------------
#: Registry location written by Microsoft's x64 Visual C++ v14 Redistributable (64-bit registry view, HKLM).
VC_RUNTIME_REGISTRY_KEY = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
#: Values read from that key (these names were observed on real machines; see the Task 4 report).
VC_RUNTIME_VALUES = ("Installed", "Major", "Minor", "Bld", "Rbld")
#: Minimum accepted runtime: (Major, Minor, Bld, Rbld). See the module docstring for the evidence.
VC_MINIMUM = (14, 43, 34808, 0)
VC_DOWNLOAD_PAGE = "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist"

MISSING, OLDER, OK = "missing", "older", "ok"


def vc_runtime_status(installed, major=None, minor=None, bld=None, rbld=None) -> str:
    """Reference implementation of the installer's decision (the installer repeats it in Pascal Script).

    Arguments are the registry values, or ``None`` when a value (or the whole key) is absent.
    Returns ``"missing"`` (not installed or unreadable), ``"older"`` (below the minimum, or not a v14
    runtime) or ``"ok"`` (the minimum or newer). ``Rbld`` is optional and defaults to 0.
    """
    if installed != 1 or major is None or minor is None or bld is None:
        return MISSING
    version = (major, minor, bld, 0 if rbld is None else rbld)
    if major != VC_MINIMUM[0]:
        return OLDER                      # only the v14 family is compatible
    return OK if version >= VC_MINIMUM else OLDER
