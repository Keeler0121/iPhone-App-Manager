# Screenshots

Screenshots of iPhone App Manager 1.0.0 running on Windows 11, connected to an iPhone.

The device name and the bundle identifiers have been replaced for publication (see [Privacy](#privacy)). App names, icons, versions and storage figures are as shown by the application.

| File | What it shows |
|---|---|
| [`01-main-window.png`](01-main-window.png) | **Main window.** The connection status and iPhone storage bar in the header, the search box, sort button and selection controls, and the app list with icons, bundle identifier, installed or offloaded status, version and the App size, Docs & Data and Total columns. The footer shows the installed and offloaded counts and the Docs & Data note. |
| [`02-sort-largest-total.png`](02-sort-largest-total.png) | **Sorting by storage.** The list sorted with the **Largest total** option, showing the apps that use the most space first. The sorted column is marked in the header. |
| [`03-offloaded-app.png`](03-offloaded-app.png) | **Offloaded app.** A search for one app, which is marked **Offloaded**. The row shows its small placeholder size, the data iOS kept, and the total. |
| [`04-app-details.png`](04-app-details.png) | **App details.** The panel that appears when the pointer rests on an app's name. For an offloaded app it shows the status, bundle ID, version, retained data, placeholder size, total, Home Screen location and type. |
| [`05-uninstall-confirmation.png`](05-uninstall-confirmation.png) | **Uninstall confirmation.** The window shown before anything is removed. It lists the selected app, warns that data on the iPhone may be permanently deleted, adds a notice for offloaded apps, and offers **Cancel** and **Uninstall**. This capture was taken without clicking **Uninstall**, and nothing was removed. |
| [`06-storage-overview.png`](06-storage-overview.png) | **iPhone storage.** The storage details (capacity, used, free now and an explanatory note), shown by resting the pointer on the storage bar in the header. |

All images are PNG. Screenshots 01 to 04 and 06 are 1920 × 1008 pixels. Screenshot 05 is 897 × 707 pixels.

## Privacy

The original captures contain real information from a personal iPhone and are kept locally in `Screenshots/Source/`. That folder is excluded from Git (see `.gitignore`) and must not be published.

For the images in this folder:

- The device name in the header (and in the confirmation window) was replaced with **Connected iPhone**.
- Every bundle identifier was replaced with a neutral `com.example.<app name>` identifier. In the confirmation window, the identifier line was re-drawn in the same way.
- Nothing else was changed. The edits were made by re-drawing the text in the application's own font and size on the background colour behind it.

The app names, icons and sizes are those of the apps on the iPhone the screenshots were taken from.
