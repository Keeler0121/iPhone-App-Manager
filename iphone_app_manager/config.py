"""Application-wide settings and constants."""
from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "iPhone App Manager"
APP_VERSION = "1.0.1"

# True when running as the packaged Windows app (PyInstaller); False when run from source.
IS_FROZEN = bool(getattr(sys, "frozen", False))

# libimobiledevice tools installed through MSYS2 UCRT64 (used when running from source).
MSYS2_BIN = Path(r"C:\msys64\ucrt64\bin")
# Folder (next to "iPhone App Manager.exe") holding the bundled copies of the same tools + DLLs.
BUNDLED_TOOLS_SUBDIR = Path("tools") / "libimobiledevice"


def resolve_tools_dir(frozen: bool = IS_FROZEN, executable: str = sys.executable) -> Path:
    """Where ideviceinstaller.exe / ideviceinfo.exe and their DLLs live.

    The packaged app only ever uses its own bundled copies (never a developer's MSYS2 install),
    so it behaves the same on every PC.
    """
    if frozen:
        return Path(executable).resolve().parent / BUNDLED_TOOLS_SUBDIR
    return MSYS2_BIN


LIBIMOBILEDEVICE_BIN = resolve_tools_dir()
IDEVICEINSTALLER = LIBIMOBILEDEVICE_BIN / "ideviceinstaller.exe"
IDEVICEINFO = LIBIMOBILEDEVICE_BIN / "ideviceinfo.exe"

# Maximum time to wait for a single command-line tool to finish.
COMMAND_TIMEOUT_SECONDS = 60

# Maximum time for removing a single app (large apps can take a while to delete).
UNINSTALL_TIMEOUT_SECONDS = 180

# Removing OFFLOADED apps. Enabled on the evidence of a user-approved, controlled test on
# 2026-11-17: `ideviceinstaller --uninstall com.example.app` (an offloaded app) exited 0 with
# "Uninstall: Complete"; read-only checks afterwards confirmed it was gone from the
# ShowPlaceholders listing, the direct lookup and the Home Screen, and nothing else changed.
# Apple apps (com.apple.*) stay protected regardless (see device.removal_block_reason).
OFFLOADED_REMOVAL_ENABLED = True

# App inventory helper (per-app storage + offloaded-app detection). iOS needs several seconds
# to calculate app sizes, so the idle limit must cover one complete size calculation.
INVENTORY_TOTAL_TIMEOUT_SECONDS = 120
INVENTORY_IDLE_TIMEOUT_SECONDS = 60

# Real app icons (fetched by the helper process). The overall limit grows with the app count;
# the idle limit stops a helper that has stopped making progress.
ICON_BASE_TIMEOUT_SECONDS = 30
ICON_PER_APP_TIMEOUT_SECONDS = 0.5
ICON_IDLE_TIMEOUT_SECONDS = 20

# Storage sizes are not reported by `ideviceinstaller --list-apps`.
STORAGE_PLACEHOLDER = "Not available yet"
