# iPhone App Manager

**Version 1.0.0** · Windows desktop app

A free Windows app for viewing and removing the apps on an iPhone connected by USB. See your installed and offloaded apps with their real icons and storage use, tick the ones you no longer want, and remove them in one go, with a confirmation step and a check afterwards that each app is really gone.

> This is an independent project. It is not made by, or affiliated with, Apple Inc. "iPhone" is a trademark of Apple Inc.

## Features

- Lists the apps on your iPhone, including **offloaded** apps (apps whose data is kept but whose app is removed).
- Shows the real app icons taken from the iPhone's Home Screen.
- Shows storage information for the iPhone and per-app sizes where iOS reports them.
- Search, sort, and tick several apps at once (checkbox, double-click, or Space).
- **Bulk uninstall with safety checks:**
  - You always get a confirmation dialog listing exactly what will be removed.
  - Apple's own apps (`com.apple.*`) are protected and cannot be removed.
  - Apps are removed one at a time, and the app then re-reads the iPhone to verify each removal. Anything that did not really go is reported as failed, not as a success.
  - If the iPhone disconnects, the batch stops.
- Clear messages for common problems (no iPhone, iPhone locked, not trusted).
- The app talks to your iPhone over USB. It contains no networking code of its own.

Keyboard shortcuts: **F5** refresh · **Ctrl+F** search · **Esc** (in search) clear search · **Space** toggle highlighted rows.

## Screenshots

*Screenshots have not been added yet.*

<!-- Add images to docs/screenshots/ and reference them here. Check they show no personal app names or device names first. -->

## System requirements

- Windows 10 or 11, 64-bit.
- Apple's **Apple Devices** app from the Microsoft Store. It provides the USB driver and service that let Windows talk to an iPhone.
- An iPhone with a USB cable.

You do **not** need Python or any developer tools to use the installer or portable version.

## Installation

1. Install **Apple Devices** from the Microsoft Store if you do not already have it.
2. Download `iPhone App Manager Setup 1.0.0.exe` from the project's **Releases** page.
3. Run it. It installs just for you (no administrator prompt) into `%LOCALAPPDATA%\Programs\iPhone App Manager`, adds a Start Menu entry, and optionally a Desktop shortcut.
4. Start **iPhone App Manager** from the Start Menu.

## Connecting your iPhone

1. Plug the iPhone into the PC with a USB cable.
2. Unlock the iPhone.
3. If asked **"Trust This Computer?"**, tap **Trust** and enter your passcode.
4. Open iPhone App Manager (or press **F5** to refresh).

If no iPhone is found, check that Apple Devices is installed, the cable supports data, and the iPhone is unlocked and trusting this PC.

## Uninstalling the application

Open **Settings > Apps > Installed apps**, find **iPhone App Manager**, and choose **Uninstall**. The app stores no settings or data files of its own. Removing it does not affect your iPhone or the apps on it.

Apple Devices is separate software and is removed separately if you no longer want it.

## Portable version

The release also contains a portable folder, `iPhone App Manager`. Extract it anywhere, double-click `iPhone App Manager.exe`, and keep the whole folder together (the `_internal` and `tools` folders are required). The same requirements apply, including Apple Devices.

## Known limitations

- Windows only. Not tested on other operating systems.
- Needs the Apple Devices app (or an equivalent Apple USB driver) to be installed.
- Designed and tested for USB connections only. Wi-Fi sync connections have not been tested.
- Designed for a single connected iPhone; using several at once has not been tested.
- Apple's built-in apps cannot be removed with this tool.
- Per-app storage sizes are only shown when iOS reports them, and iOS can take a few seconds to calculate them; some apps may show "Not available".
- Removing an app removes it from the iPhone as iOS would; this cannot be undone from this app. Data stored only on the iPhone may be lost.
- Tested with a limited set of iPhone and iOS versions. Other versions are not guaranteed to work, and future iOS releases may change behaviour.

## For developers

### Running from source

Requirements: Windows 10/11, Python 3.12 (with Tkinter), the Apple Devices app, and MSYS2 UCRT64 with `libimobiledevice` and `ideviceinstaller` installed in `C:\msys64\ucrt64\bin`. No extra Python packages are needed.

```
py -3.12 main.py          (or double-click launch.bat)
```

### Tests

No iPhone is needed, and uninstalls are always mocked.

```
py -3.12 -m unittest discover -s tests -v
```

The packaging tests also check the built release when `dist\iPhone App Manager` and the installer exist, and are skipped otherwise.

### Building the release

PyInstaller is installed only in a separate build environment:

```
py -3.12 -m venv .venv-build
.venv-build\Scripts\python.exe -m pip install pyinstaller
.venv-build\Scripts\python.exe packaging\build.py
```

Add `--installer` to also build the installer (requires Inno Setup 6), or `--installer-only` to wrap an existing portable folder. `packaging\build.py` generates the icon, runs PyInstaller, copies the libimobiledevice tools and DLLs into `tools\libimobiledevice`, and writes licence notices to `licenses\`. Built files go to `dist\` and are not committed.

### Project layout

```
main.py                         entry point
iphone_app_manager/
  config.py                     tool locations, timeouts, safety switches
  models.py                     data classes
  device.py                     ideviceinfo / ideviceinstaller wrapper, validated uninstall
  uninstall.py                  sequential bulk uninstall + verification
  app_icons.py, icon_helper.py  real icons (read-only helper process)
  app_inventory.py, inventory_helper.py   offloaded apps + sizes (read-only helper process)
  ui/                           window, widgets, dialogs, theme
packaging/                      build script, Inno Setup installer script, icon
tests/                          unit, UI (fake device) and packaging tests
```

## Licence and third-party software

The licence for iPhone App Manager's own source code has **not been chosen yet**. Until a licence file is added, all rights are reserved by the author.

The Windows release bundles unmodified third-party programs and libraries, each under its own licence (full texts are included in the release's `licenses` folder, along with `THIRD-PARTY-NOTICES.txt`):

| Component | Licence |
|---|---|
| Python and Tcl/Tk (runtime) | Python Software Foundation licence; Tcl/Tk licence |
| PyInstaller (bootloader) | GPL-2.0 with the PyInstaller bootloader exception |
| ideviceinstaller | GPL-2.0-or-later |
| libimobiledevice, libplist | LGPL-2.1-or-later (some tools GPL-2.0-or-later) |
| libimobiledevice-glue, libusbmuxd | LGPL-2.1-or-later |
| OpenSSL | Apache-2.0 |
| libzip, zstd | BSD-3-Clause (zstd: BSD-3-Clause OR GPL-2.0-only) |
| zlib | Zlib |
| bzip2 | bzip2-1.0.6 |
| xz (liblzma) | 0BSD |
| Inno Setup (installer builder only; not bundled in the app) | Inno Setup licence |

Source for these components is available from their upstream projects and from MSYS2 package sources (https://packages.msys2.org/).
