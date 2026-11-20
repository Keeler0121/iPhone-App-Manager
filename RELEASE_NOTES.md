# iPhone App Manager 1.0.2

**Wi-Fi fix release** · Windows desktop app · USB and Wi-Fi

> This is an independent project. It is not made by, or affiliated with, Apple Inc. "iPhone" is a trademark of Apple Inc.

## What changed in 1.0.2

- **Wi-Fi connections now work on the one iPhone tried.** The bundled `libimobiledevice` 1.3.0 could not connect to a Wi-Fi (network) device on Windows: the service listed the iPhone, but every connection failed with `Mux error (-8)`, which the app showed as "Not trusted". The cause is in libimobiledevice 1.3.0's own code, which reads the device's network address in a layout Windows does not use. Upstream fixed this after 1.3.0 (commit `a172604`, 2023) and released the fix in 1.4.0. `libimobiledevice-1.0.dll` and `ideviceinfo.exe` in the release are now libimobiledevice **1.4.0**, built from the unmodified upstream release tarball by `packaging\build_libimobiledevice.sh` with the MSYS2 UCRT64 compiler. No patches are applied, and two builds in different folders produced byte-identical files.
- **Everything else is unchanged:** `ideviceinstaller.exe` 1.1.1, libimobiledevice-glue 1.3.2, libusbmuxd 2.1.1, libplist 2.7.0, OpenSSL, libzip, zlib, bzip2, xz and zstd are the same MSYS2 files as in 1.0.1, and the same set of DLLs is bundled. `ideviceinstaller.exe` is used unchanged with the new library: every library function it imports exists in 1.4.0, and the library's version numbers mark 1.4.0 as backward compatible with 1.3.0.
- **Sort by Status.** Clicking the **STATUS** column heading now sorts the list: the first click puts Offloaded apps first, then Installed apps, and each further click reverses the two groups. Apps stay in name order (A to Z) within each group in both directions, and the heading shows an arrow for the direction. Search and your ticked apps are unaffected. The list also re-sorts itself when the offloaded information arrives after the app list.
- **Helper error reporting hardened.** The two background helper programs (app list and icons) now report errors safely when started without a console. Before, if one was started by hand outside the app with, for example, a missing library folder, the attempt to print the error raised a second exception (`'NoneType' object has no attribute 'write'`) that hid the real cause and ended in an unhandled-exception dialog. They now exit with their normal code (4 for a library that cannot be loaded). The app itself always starts the helpers with their output piped, so normal use was not affected.
- **libtatsu and curl are not bundled.** libimobiledevice 1.4.0's configure script needs libtatsu (which needs curl) to build, but neither built file imports them. The build script and the release build both check this.
- **Licence notices and source bundle updated.** `THIRD-PARTY-NOTICES.txt` now describes libimobiledevice 1.4.0 (all 64 source and header files compiled into the two files carry an LGPL-2.1-or-later header; upstream publishes no signature for the tarball), and the statement that all bundled binaries are unmodified MSYS2 binaries now names the two exceptions. `Third-Party-Source-Code-1.0.2.zip` holds the source of the same five components (four MSYS2 source packages, plus the upstream libimobiledevice 1.4.0 tarball and the script that builds it) and the libtatsu tarball the build needs. It covers only those five components; the MSYS2 libimobiledevice 1.3.0 source package is no longer part of it. The notices are the author's own audit and have not been reviewed by a lawyer.

## What was verified (and what was not)

- **Real iPhone, over Wi-Fi, read-only (one iPhone, iOS 27.2.1, one home network):** the app's device discovery listed the iPhone over both USB and Wi-Fi; the app's own device service, run against the built tools in Wi-Fi mode, read the device information, 88 apps and the storage figures with no "Not trusted" message; the bundled `ideviceinfo -n` read the device information; `ideviceinstaller -n --list-apps` returned the same number of entries (89 lines) as over USB; and the app's inventory and icon helpers (run from the built `iPhone App Manager.exe` with MSYS2 off the PATH) loaded the app list, sizes and icons over Wi-Fi. The same bundled tools failed with `Mux error (-8)` before the change.
- **Unplugged and in the installed app:** the first checks ran while the iPhone was also connected by USB (they used the Wi-Fi path only, because the `-n` flag and the helpers' Wi-Fi mode consider network devices only). They were repeated with the iPhone unplugged and awake: the Apple service listed only a Network entry, and every check above passed again. The author then tested the final installed 1.0.2 build with the same unplugged iPhone, awake on the same Wi-Fi network: it connected over Wi-Fi, loaded the app list, and the STATUS heading sorted Offloaded-first and Installed-first as described above (the author's own report of that test).
- **Compatibility of `ideviceinstaller` 1.1.1 with the 1.4.0 library (checked statically, not by installing anything):** every function it imports exists in 1.4.0 (42 of 42); the prototypes of the functions the app calls directly are identical; the only header differences are additions (a pairing enum and callback, the error code `IDEVICE_E_CONNREFUSED`, and one new trailing field in `struct lockdownd_service_descriptor`, which `ideviceinstaller` never reads or allocates itself).
- **Not tested:** installing or removing an app over Wi-Fi (no apps were installed or removed during this work), other iPhones, other routers or iOS versions, Windows 10, and a clean-PC run of this build.
- The automated test suite (298 tests) was updated for the new components and passes.

## Known limitations of Wi-Fi in this release

- Wi-Fi still needs wireless sync to be on for the iPhone. On the one iPhone tried, ticking **Show this iPhone when on Wi-Fi** in Apple Devices and clicking Apply did **not** switch it on (the box un-ticked itself). Wi-Fi worked only after the setting was written to the iPhone directly with a developer tool, which this app does not do. So Wi-Fi may be unavailable on your iPhone even though the app works.
- The app still words a connection failure of this kind as "Not trusted". That label can be wrong: the same message appeared when trust was fine.
- Running from source uses MSYS2's libimobiledevice 1.3.0, so Wi-Fi does not work there; USB does.
- **Apple's device service sometimes stops listing the iPhone over Wi-Fi.** On the test PC the list went empty several times, between about 17 and 50 minutes after it had last recovered, even though the iPhone was awake, reachable and still advertising its wireless-sync service. The app then says "iPhone not available over Wi-Fi" (the same message as when Wi-Fi sync is off). Closing and reopening Apple Devices did not fix it. Ending Apple's `AppleMobileDeviceProcess` in Task Manager did: Apple restarts it by itself within about 15 seconds and the iPhone was listed again. The cause is not known and is outside this app.
- Locking the iPhone's screen can also make it disappear from the list for a while (it dropped out within seconds of the phone going to sleep and came back when it woke); keep the iPhone awake while you use Wi-Fi.

## Downloads (1.0.2)

| File | Size |
|---|---|
| `iPhone App Manager Setup 1.0.2.exe` | 12,675,941 bytes (about 12.1 MB) |
| `iPhone-App-Manager-Setup-1.0.2.sha256` | SHA-256 checksum for the installer |
| `iPhone-App-Manager-1.0.2-Portable.zip` | 15,123,732 bytes (about 14.4 MB) |
| `iPhone-App-Manager-1.0.2-Portable.sha256` | SHA-256 checksum for the portable ZIP |
| `Third-Party-Source-Code-1.0.2.zip` | 2,210,027 bytes (about 2.1 MB) |
| `Third-Party-Source-Code-1.0.2.sha256` | SHA-256 checksum for the source-code ZIP |

**SHA-256 (1.0.2)**

```
A7ED5F0B7D463D67FBE6DC18D699BE5C40CB65A24AA5BBC7FBA7FC6ED5F9A749  iPhone App Manager Setup 1.0.2.exe
AE51E744E547CFF0626934816022755A060F68156E274FC6A049FA28670561DF  iPhone-App-Manager-1.0.2-Portable.zip
7C83246D7F488CB01AE80C2F5FF52161D6879C94804DEAA32B48FAC80C69A79C  Third-Party-Source-Code-1.0.2.zip
```

Check a download in PowerShell; the result should match the value above:

```powershell
Get-FileHash .\iPhone-App-Manager-1.0.2-Portable.zip -Algorithm SHA256
```

When you upgrade from 1.0.1 by running the new installer, the two old licence texts `libimobiledevice-1.3.0-AUTHORS.txt` and `libimobiledevice-1.3.0-COPYING.LESSER.txt` stay in the installed `licenses` folder (the installer replaces files but does not remove old ones). They are harmless and are removed when you uninstall. The requirements, installation steps and safety information below are unchanged from 1.0.0 and still apply. The installer is not code-signed, as before.

---

# Version 1.0.1 release notes (historical, unchanged)

**Licensing-notice correction release** · Windows desktop app · USB only

Version 1.0.1 changes **only the licence notices and documentation**. The application, its user interface and every bundled program and library are the same as in 1.0.0. Only the version number and the licence text have changed. If you already have 1.0.0 you gain nothing functionally; update if you want the corrected notices.

> This is an independent project. It is not made by, or affiliated with, Apple Inc. "iPhone" is a trademark of Apple Inc.

## What changed in 1.0.1

All changes are to `THIRD-PARTY-NOTICES.txt` (in the `licenses` folder of the installer and the portable ZIP), the README and these notes:

- **libplist:** the notices now record the author's investigation of libplist 2.7.0. MSYS2 lists GPL-2.0-or-later as well as LGPL-2.1-or-later, and the upstream tree contains a GPL v2 text. No GPL-licensed source file was found in the code compiled into `libplist-2.0.dll`. The reason for MSYS2's GPL entry could not be established, so the GPL reference and its qualification are kept.
- **xz/liblzma:** the copy inside Python's `_lzma.pyd` is liblzma 5.2.5, public domain according to its own `COPYING` and source headers. It is described separately from the MSYS2 xz 5.8.4 (0BSD) that the libimobiledevice tools use.
- **Microsoft code inside Python:** the notices now state Python's condition for its Windows binaries (Microsoft Distributable Code, and end users agreeing to terms that protect it). iPhone App Manager does not currently present end-user terms, and Microsoft's own terms have not been reviewed here, so it has **not been established** that this condition is met.
- **Own licence:** the README describes iPhone App Manager as intended to be released under a proprietary licence, with no permission to resell or redistribute it without the author's authorisation. A formal licence text has not been published yet.
- The README's source-code paragraph had two garbled path names, now corrected.
- `Third-Party-Source-Code-1.0.1.zip` has the same twelve MSYS2 source files, signatures and checksums as `Third-Party-Source-Code-1.0.0.zip`. Only its folder name and the version number in its `README.txt` differ.

The notices are the author's own audit. They have not been reviewed by a lawyer and are not a statement that every obligation has been met.

## Downloads (1.0.1)

| File | Size |
|---|---|
| `iPhone App Manager Setup 1.0.1.exe` | 12,631,162 bytes (about 12.0 MB) |
| `iPhone-App-Manager-Setup-1.0.1.sha256` | SHA-256 checksum for the installer |
| `iPhone-App-Manager-1.0.1-Portable.zip` | 15,094,159 bytes (about 14.4 MB) |
| `iPhone-App-Manager-1.0.1-Portable.sha256` | SHA-256 checksum for the portable ZIP |
| `Third-Party-Source-Code-1.0.1.zip` | 1,483,314 bytes (about 1.4 MB) |
| `Third-Party-Source-Code-1.0.1.sha256` | SHA-256 checksum for the source-code ZIP |

**SHA-256 (1.0.1)**

```
370327FD4FFA90C662701A505387F09762102A222F5260FCB57C12B6205AC6F4  iPhone App Manager Setup 1.0.1.exe
247D02FFB5C42AAAC754FFF67179D4C9031D4EB4B0C7518D259CCD3012165355  iPhone-App-Manager-1.0.1-Portable.zip
5B96521D68F50D8670214784AFD512F374C0E3C839B73F7983A890E9918D0C4C  Third-Party-Source-Code-1.0.1.zip
```

Check a download in PowerShell; the result should match the value above:

```powershell
Get-FileHash .\iPhone-App-Manager-1.0.1-Portable.zip -Algorithm SHA256
```

The requirements, installation steps, limitations and safety information below are unchanged from 1.0.0 and still apply. The installer is not code-signed, as before.

---

# Version 1.0.0 release notes (historical, unchanged)

The notes below are the original 1.0.0 notes, kept as published. Their file names and hashes refer to the 1.0.0 assets, which remain available on the 1.0.0 release page.

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
- iPhone App Manager itself is intended to be released under a proprietary licence: no permission is given to resell or redistribute it without the author's authorisation. A formal licence text has not been published yet. Bundled third-party components keep their own licences, and their notices are in the release's `licenses` folder. The notices have not been reviewed by a lawyer; see "Third-party software" for the libplist qualification.

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
- **libplist licence:** libplist 2.7.0 is mainly LGPL-2.1-or-later with MIT-licensed parts, but MSYS2's package metadata also lists GPL-2.0-or-later and the upstream tree contains a GPL v2 text. The author investigated this against the exact 2.7.0 source package: no GPL-licensed source file was found in the code compiled into `libplist-2.0.dll` (the only GPL-headed files are build scripts that are not part of the library). The reason for MSYS2's GPL metadata entry could not be established, so the notices keep the GPL reference and that qualification.
- **xz/liblzma:** Python's `_lzma.pyd` contains liblzma 5.2.5, which is public domain according to its own `COPYING` and source headers. It is separate from the MSYS2 xz 5.8.4 (0BSD) bundled with the libimobiledevice tools.
- **Microsoft code inside Python:** Python's licence for its Windows build says its binaries contain Microsoft Distributable Code and asks redistributors to require distributors and end users to agree to terms that protect it. iPhone App Manager does not currently present end-user terms, and Microsoft's own terms have not been reviewed here, so it has not been established that this condition is met.
- The notices are the author's own audit. They have not been reviewed by a lawyer and are not a statement that every obligation has been met.
