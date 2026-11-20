"""Launch iPhone App Manager."""
from __future__ import annotations

import sys


def _prepare_windows() -> None:
    """Crisp text on high-DPI screens and our own taskbar icon."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("iPhoneAppManager.App")
    except Exception:
        pass


HELPER_MODES = {"--icon-helper": "icon_helper", "--inventory-helper": "inventory_helper"}


def run_helper_mode(argv: list[str]) -> int | None:
    """Run a background helper if requested, else return None.

    The packaged app has no Python interpreter, so it starts its read-only helper processes by
    re-launching itself with one of HELPER_MODES. Each helper still runs in its own process, so
    a fault in the native iPhone libraries can never take down the main window.
    """
    if len(argv) < 2 or argv[1] not in HELPER_MODES:
        return None
    import importlib
    module = importlib.import_module(f"iphone_app_manager.{HELPER_MODES[argv[1]]}")
    return module.main([argv[1]] + argv[2:])


def main() -> None:
    if sys.version_info < (3, 10):
        sys.exit("iPhone App Manager needs Python 3.10 or newer.")

    code = run_helper_mode(sys.argv)
    if code is not None:
        sys.exit(code)

    import tkinter as tk

    from iphone_app_manager.connection import query_device_list
    from iphone_app_manager.device import DeviceService
    from iphone_app_manager.ui import MainWindow

    _prepare_windows()
    root = tk.Tk()
    # USB is the default connection; Wi-Fi is chosen in the window. The Apple device service is asked
    # which iPhones are reachable, so every command can name the exact iPhone and connection.
    MainWindow(root, DeviceService(discoverer=query_device_list))
    root.mainloop()


if __name__ == "__main__":
    main()
