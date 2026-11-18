# iPhone App Manager

**Version 1.0.0** · Windows desktop app

A free Windows app for viewing and removing the apps on an iPhone connected by USB. See your installed and offloaded apps with their real icons and storage use, tick the ones you no longer want, and remove them in one go, with a confirmation step and a check afterwards that each app is really gone.

> This is an independent project. It is not made by, or affiliated with, Apple Inc. "iPhone" is a trademark of Apple Inc.

> ## ⚠️ Important: removing apps is permanent
>
> - **Uninstalling an app permanently removes it from your iPhone**, together with the data it keeps on the phone (documents, settings, downloads, saved sign-ins).
> - **Removing an offloaded app also discards its retained app data.** An offloaded app has already had the app itself removed by iOS, but its data is still kept. Removing it deletes that data for good.
> - **These actions cannot be undone through iPhone App Manager.** You would have to reinstall the app yourself (for example from the App Store).
> - **Check your selection carefully** before you confirm. Only the **Uninstall** button in the confirmation window starts a removal, and its **Cancel** button has the keyboard focus by default, so pressing Enter cancels.
>
> Accounts and anything stored online or in iCloud are not deleted, and subscriptions are not cancelled.

## Features

- Lists the apps on your iPhone, including **offloaded** apps (apps whose data is kept but whose app is removed).
- Shows the real app icons taken from the iPhone.
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

Plug the iPhone in by USB, unlock it, and tap **Trust** if it asks "Trust This Computer?". Step-by-step instructions, and what to do if the iPhone isn't found, are in [How to use](#how-to-use).

## How to use

### 1. Connect your iPhone

1. Plug the iPhone into the PC with a USB cable, and unlock it.
2. If the iPhone asks **"Trust This Computer?"**, tap **Trust** and enter your passcode.
3. Start iPhone App Manager, or click **Refresh** (or press **F5**) if it is already open.

The app shows "Reading apps from your iPhone…" while it loads the list. Keep the iPhone connected and unlocked; this usually takes a few seconds.

### 2. Read the app list

Installed and offloaded apps appear together in **one list**. Each row shows the app icon, its name, its bundle identifier (a technical ID such as `com.example.app`), a status and sizes.

- Offloaded apps are marked **Offloaded** in the list.
- A summary line shows how many apps are installed and offloaded, for example "12 installed · 3 offloaded". While the app is still working, it says so ("checking for offloaded apps…", "Calculating app sizes…").
- The columns show **App size**, **Docs & Data** and **Total**. For an offloaded app, the sizes are the small placeholder left behind plus the data that iOS kept.
- Rest the mouse pointer on an app's name for a moment to see a details card (status, bundle ID, version and, where iOS reports them, sizes and other information).
- The sizes come from iOS, and the "Docs & Data" figure can be smaller than the one in the iPhone's Settings. A size can show "Calculating…" or "Not available" if iOS has not reported a figure.
- Real icons are loaded in the background. Until they arrive, placeholder icons are shown.

### 3. Search and sort

- Type in the search box (or press **Ctrl+F**) to filter by app name or bundle ID. The summary then reads "Showing X of Y apps". Press **Esc** in the box, or click **Clear search**, to clear it.
- Use the **Sort** button, or click a column heading (App name, App size, Docs & Data, Total), to change the order. Options include name A to Z, name Z to A, and largest or smallest sizes.

### 4. Select apps

- Click an app's checkbox or icon, or double-click its row, to tick it.
- Click a row to highlight it (Ctrl+click or Shift+click for several rows, or use the arrow keys), then press **Space** to tick or untick all highlighted rows.
- **Select All** (or **Ctrl+A** in the list) ticks every app currently shown. If you have searched, only the matching apps are ticked.
- **Deselect All** unticks everything, including selected apps hidden by a search.
- The **selected** counter shows how many apps are ticked. Click it to open a review list of the selected apps.

### 5. Remove apps

1. Tick the apps you want to remove. You can mix installed and offloaded apps.
2. Click **Uninstall Selected**. It is greyed out while the app is loading or when no removable app is selected.
3. A **confirmation window** lists the apps that will be removed from your iPhone (with how many are installed and how many offloaded) and warns that data on the iPhone may be permanently deleted. If you selected offloaded apps, it adds a separate notice that their retained data will be deleted.
4. Apps that can't be removed are skipped, and the window says how many and why. Apple's own apps (`com.apple.*`) are protected and are never removed.
5. Read the list carefully, then click **Uninstall** to go ahead, or **Cancel** to stop. Nothing is removed unless you click **Uninstall** in this window.

### 6. Progress and verification

- A progress window removes the apps **one at a time** and shows which one is being removed. You can't close this window while removal is running, and **Refresh** is turned off.
- If you try to close the main window during removal, the app asks you to confirm. The app being removed may still finish, but the remaining apps will not be removed.
- When the removals finish, the app **reloads the list from the iPhone and checks each result** against the installed apps, the offloaded apps and the Home Screen. An app that is reported as removed but is still on the iPhone is not counted as removed.
- The final summary shows how many were **removed**, **failed**, **not attempted**, **skipped** or **not verified**. Each app's row shows its own result and, if something went wrong, the reason.
- Apps that were not confirmed as removed stay ticked. **Nothing is retried automatically.**

### If something goes wrong

| What you see | What to do |
|---|---|
| **No iPhone connected** | Connect the iPhone with a USB cable, unlock it, then click **Refresh**. If it is already plugged in, check that the Apple Devices app can see it. |
| **iPhone doesn't trust this computer** | Unlock the iPhone. When "Trust This Computer?" appears, tap **Trust** and enter your passcode, then click **Refresh**. |
| **iPhone is locked** | Unlock the iPhone with your passcode, then click **Refresh**. |
| **iPhone isn't responding** | Unplug the iPhone, plug it back in, unlock it, then click **Refresh**. |

These screens have a **Try again** button.

**If the iPhone disconnects, locks, or stops trusting the computer during a removal**, the app stops. The app that was being removed is reported as failed, and the remaining apps are marked **Not attempted**. Nothing further is removed. Reconnect and unlock the iPhone, click **Refresh**, and check the list before trying again. If the list can't be refreshed after a removal, the app says the results could not be double-checked.

## Uninstalling the application

Open **Settings > Apps > Installed apps**, find **iPhone App Manager**, and choose **Uninstall**. The app stores no settings or data files of its own. Removing it does not affect your iPhone or the apps on it.

Apple Devices is separate software and is removed separately if you no longer want it.

## Portable version

The portable version runs without being installed. It will be offered as a ZIP file on the project's **Releases** page once it is published.

1. Install the **Apple Devices** app from the Microsoft Store if you have not already. Apple Devices and its USB drivers are **required** for the portable version too.
2. Download the portable ZIP.
3. Right-click the ZIP and choose **Extract All…**, then pick a folder (for example, one inside your Documents). Don't run the program from inside the ZIP.
4. Open the extracted `iPhone App Manager` folder and double-click `iPhone App Manager.exe`. Keep the whole folder together: the `_internal` and `tools` folders are required.
5. Connect and unlock your iPhone and follow [How to use](#how-to-use).

Python and MSYS2 are **not** needed to run the packaged application. To remove the portable version, close the program and delete the folder.

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
