# iPhone App Manager 1.0.0

**First release** · Windows desktop app · USB only

iPhone App Manager lets you see every app on a USB-connected iPhone, including **offloaded** apps, with real icons and storage use. You can tick the apps you no longer want and remove them in one go. Each removal needs your confirmation, and the app re-reads the iPhone afterwards to check that each app is really gone.

> This is an independent project. It is not made by, or affiliated with, Apple Inc. "iPhone" is a trademark of Apple Inc.

> ## ⚠️ Removing apps is permanent
>
> - **Uninstalling an app permanently removes it from your iPhone**, along with the data it keeps on the phone (documents, settings, downloads, saved sign-ins).
> - **Removing an offloaded app also discards its retained data.** iOS has already removed the app itself, but kept its data. Removing the offloaded app deletes that data for good.
> - **These actions cannot be undone through iPhone App Manager.** You would have to reinstall the app yourself, for example from the App Store.
> - Check your selection carefully. Nothing is removed until you click **Uninstall** in the confirmation window. Its **Cancel** button has the keyboard focus by default, so pressing Enter cancels.
> - Removing an app through this tool does not itself delete your online accounts or cancel subscriptions. Data stored separately in iCloud or other online services is not intentionally removed.

## Highlights

- **Installed and offloaded apps in one list**, with real app icons read from the iPhone.
- **Storage information**: iPhone capacity, used and free space, plus per-app size, Docs & Data and total where iOS reports them.
- **Search, sort and multi-select**: filter by name or bundle ID, sort by name or size, and tick several apps at once.
- **Bulk uninstall with safety checks:**
  - A confirmation window always lists exactly what will be removed.
  - Apple's own apps (`com.apple.*`) are protected and cannot be removed.
  - Apps are removed one at a time, and the final summary reports removed, failed, not attempted, skipped and not verified apps separately.
  - If the iPhone disconnects, locks or stops trusting the computer, the batch stops and nothing further is removed.
- **Clear messages** for no iPhone, iPhone locked, computer not trusted, and iPhone not responding.
- **Keyboard shortcuts**: F5 refresh, Ctrl+F search, Esc clears search, Space toggles highlighted rows.
- **No networking code of its own.** The app talks to the iPhone over USB through bundled `libimobiledevice` tools. I checked the source and found no networking imports.
- **Per-user install**: the installer itself needs no administrator rights (installing the Visual C++ Redistributable, if you do not have it, normally does), and the app stores no settings or data files of its own.

## Requirements

**Windows**
- Windows 10 or 11, **64-bit**. The program has been tested on Windows 11; **Windows 10 has not been tested**.
- The **Microsoft Visual C++ Redistributable for Visual Studio 2015-2022 (x64)**, version **14.43.34808 or newer**. It is **not included** in the installer or the portable ZIP, so you install it separately from Microsoft's official page: <https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist>. Many PCs already have it. Installing it normally needs **administrator rights**; a newer version is fine.
- Apple's **Apple Devices** app from the Microsoft Store. It provides the USB driver and service that let Windows talk to an iPhone. It is **required for both the installer and the portable version**.

**iPhone**
- An iPhone and a USB cable.
- The iPhone must be unlocked and must trust the computer. Tap **Trust** when it asks "Trust This Computer?".

You do **not** need Python, MSYS2, Git or any developer tools.

## Downloads and installation

| File | Description |
|---|---|
| `iPhone App Manager Setup 1.0.0.exe` | Windows installer (12,624,878 bytes, about 12.0 MB) |
| `iPhone-App-Manager-1.0.0-Portable.zip` | Portable version, no installation (15,092,881 bytes, about 14.4 MB) |
| `iPhone-App-Manager-1.0.0-Portable.sha256` | SHA-256 checksum for the portable ZIP |
| `Third-Party-Source-Code-1.0.0.zip` | Source code (MSYS2 source packages) for five bundled components: ideviceinstaller, libimobiledevice, libimobiledevice-glue, libusbmuxd and libplist. It covers only those five. (1,483,314 bytes, about 1.4 MB) |
| `Third-Party-Source-Code-1.0.0.sha256` | SHA-256 checksum for the source-code ZIP |

### Option 1: Windows installer

1. Install the **Microsoft Visual C++ Redistributable (x64)** (see Requirements) and **Apple Devices** from the Microsoft Store if you have not already.
2. Run `iPhone App Manager Setup 1.0.0.exe`. If the Visual C++ Redistributable is missing or older than 14.43.34808, setup says so and asks whether to continue; the program will not start until it is installed.
3. By default it installs **just for you** with no administrator prompt, into `%LOCALAPPDATA%\Programs\iPhone App Manager`. It adds a Start Menu entry and, if you tick the option, a Desktop shortcut. (The installer's setup also offers an "install for all users" choice, which needs administrator rights. That option was **not tested**.)
4. Start **iPhone App Manager** from the Start Menu.

To remove it, open **Settings > Apps > Installed apps**, find **iPhone App Manager** and choose **Uninstall**. This does not affect your iPhone or its apps.

### Option 2: Portable ZIP

1. Install the **Microsoft Visual C++ Redistributable (x64)** (see Requirements) and **Apple Devices** from the Microsoft Store if you have not already. The portable version does not check for the redistributable; if the program does not start and shows "Failed to load Python DLL", it is probably missing.
2. Right-click the ZIP, choose **Extract All…** and pick a folder. Don't run the program from inside the ZIP.
3. Open the extracted `iPhone App Manager` folder and double-click `iPhone App Manager.exe`. Keep the whole folder together: the `_internal` and `tools` folders are required.

To remove it, close the program and delete the folder.

### Verify your download

**Portable ZIP SHA-256:**

```
C32BF0FF23BB18628FCC6F43E0D2BB72C146686439DD20728C3B3888CD126BE4
```

In PowerShell, run this from the folder containing the ZIP. The result should match the value above:

```powershell
Get-FileHash .\iPhone-App-Manager-1.0.0-Portable.zip -Algorithm SHA256
```

**Installer SHA-256**, for reference:

```
E9FF79479CA9E2A6DE594F5AE2E1581D6550DC5BBC3E20B7EE97524E9F6A8BA4
```

**Third-Party-Source-Code-1.0.0.zip SHA-256:**

```
6133425AA4CEB0E8A0149E4A945338927C6FDB055C18E11D04F7A4BECCC2AF4D
```

## Quick start

1. Plug the iPhone into the PC by USB, unlock it, and tap **Trust** if asked.
2. Start iPhone App Manager, or click **Refresh** (F5) if it is already open. Loading usually takes a few seconds.
3. Browse, search and sort the list. Offloaded apps are marked **Offloaded**.
4. Tick the apps to remove, then click **Uninstall Selected**.
5. Read the confirmation window carefully, then click **Uninstall** to go ahead or **Cancel** to stop.
6. Wait for the progress window to finish. The app reloads the list and checks each result.

If something goes wrong, the app shows a message with a **Try again** button. Reconnect and unlock the iPhone, then click **Refresh**.

## Known limitations and untested areas

**Limitations**
- Windows only.
- Needs the Microsoft Visual C++ Redistributable (x64), which is not included, and the Apple Devices app. Apple Devices is the only Apple driver prerequisite that has been tested.
- Apple's built-in apps cannot be removed with this tool.
- Per-app sizes appear only when iOS reports them. They can show "Calculating…" or "Not available", and the Docs & Data figure can be smaller than the one in the iPhone's Settings.
- Removals cannot be undone from this app (see the warning above).
- The installer and the program are **not code-signed**. Windows SmartScreen may show an "unknown publisher" warning. To continue, choose **More info > Run anyway**.
- The licence for the app's own source code has not been chosen yet. Bundled third-party components keep their own licences, and their notices are in the release's `licenses` folder. The notices have not been reviewed by a lawyer, and the libplist licence question described under "Third-party software" is still open.

**Not tested**
- Wi-Fi sync connections. The app is designed and tested for USB only.
- Several iPhones connected at the same time.
- Other operating systems.
- Only a limited set of iPhone and iOS versions has been tried. Other versions are not guaranteed to work, and future iOS releases may change behaviour.
- **Clean-PC testing** was done in Windows Sandbox, which has no USB passthrough. That testing covered installing, shortcuts, launching, the no-iPhone message and uninstalling, but not real iPhone connections or Apple Devices driver behaviour.
- SmartScreen behaviour was not observed. The installer was supplied through a mapped local folder.
- The portable and installer builds were tested on Windows 11 only. **Windows 10 was not tested.**
- Visual C++ Redistributable versions older than the one in the test (a clean Windows 11 Sandbox with version 14.52.37029 installed) were not tested; the stated minimum, 14.43.34808, comes from the toolset Python was built with, not from a test of that exact version.

## What was verified for this release

- The automated test suite (183 tests, with a fake device and mocked uninstalls; none skipped) passes, including the checks on the built release.
- **Portable build:** the extracted ZIP, launched with a stripped PATH and no system Python, MSYS2 or Git, started, responded and closed normally, and loaded only its own bundled Python. (The window contents were not inspected by eye on this final build.)
- **Portable ZIP:** integrity test passed. After extraction, all 991 files matched the release folder exactly. A scan for the author's personal identifiers found none.
- **Installer in a clean Windows Sandbox**, on the earlier candidate installer (before the Microsoft-runtime and licence changes; the final installer got the prerequisite-check tests described below, not a repeat of this full walk-through): per-user install, Desktop and Start Menu shortcuts, launch, interface, the no-iPhone message, normal close, and an uninstall that removed the shortcuts and install folder.
- **Microsoft runtime:** a copy of the program without any bundled Microsoft runtime files (no app-local Universal C Runtime and no `VCRUNTIME140.dll`) was tested in a clean Windows 11 Sandbox. Before the Visual C++ Redistributable (x64) was installed it did not start ("Failed to load Python DLL"); after installing Microsoft's official x64 redistributable (version 14.52.37029) it started, showed the no-iPhone screen, and its helper processes ran. This is why the redistributable is a prerequisite. (Windows 10 was not tested.)
- **Installer prerequisite check (final installer):** in a clean Windows 11 Sandbox the installer reported the Visual C++ runtime correctly in all 11 silent test cases (missing, not installed, incomplete entries, older versions including 14.43.34807, exactly 14.43.34808, newer versions, a wrong major version). Only the interactive warning's "No" and "Yes" answers and the no-dialog case were checked by window state, not by looking at the dialogs.
- Removal of an offloaded app was confirmed in a controlled test on a real iPhone on 2026-11-17: the app was gone from the offloaded list, the direct lookup and the Home Screen, and nothing else changed.

## Third-party software

The release bundles Python 3.12.10 and its components (OpenSSL 3.0.16, Tcl/Tk 8.6.15, libffi, Expat, zlib, libmpdec), PyInstaller 6.22.3's bootloader and run-time modules, and unmodified MSYS2 builds of `ideviceinstaller`, `libimobiledevice` and its supporting libraries, OpenSSL, libzip, zstd, zlib, bzip2 and xz, each under its own licence. The installer is built with Inno Setup 6.7.3. `THIRD-PARTY-NOTICES.txt` and the licence texts it names are in the `licenses` folder of the release.

- **Source code:** `Third-Party-Source-Code-1.0.0.zip` (a separate download) holds the MSYS2 source packages for the five components `ideviceinstaller`, `libimobiledevice`, `libimobiledevice-glue`, `libusbmuxd` and `libplist`, with their signatures and checksums. It covers only those five. It has not been rebuilt, and no claim is made that the binaries can be reproduced from it.
- **libplist licence: not fully resolved.** libplist 2.7.0 is mainly LGPL-2.1-or-later with MIT-licensed parts, but MSYS2's package metadata also lists GPL-2.0-or-later and the upstream tree contains a GPL v2 text. No GPL-licensed source file was found in the code compiled into the library, but the reason for the GPL entry has not been established, so the notices keep that qualification.
- The notices are the author's own audit. They have not been reviewed by a lawyer and are not a statement that every obligation has been met.
