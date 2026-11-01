"""The ONE place for small OS-specific actions in new code: open a file/folder/URL with the default app,
open an OS settings page. Another platform would implement the same functions."""
import os


def open_path(target):
    """Open a file, folder or URL with whatever the OS uses for it."""
    if os.name == "nt":
        os.startfile(target)
    else:  # pragma: no cover - other platforms
        import subprocess
        subprocess.Popen(["xdg-open", target])


def open_os_settings(page):
    """Open an OS settings page by a neutral name: 'startup_apps', 'windows_update', 'storage', 'network', 'installed_apps', 'task_scheduler', 'security_center', 'startup_folder'."""
    uris = {"startup_apps": "ms-settings:startupapps", "windows_update": "ms-settings:windowsupdate", "storage": "ms-settings:storagesense",
            "network": "ms-settings:network", "installed_apps": "ms-settings:appsfeatures", "task_scheduler": "taskschd.msc",
            "security_center": "windowsdefender:", "startup_folder": "shell:startup"}
    if os.name == "nt" and page in uris:
        os.startfile(uris[page])


def recycle_bin_folder():
    """Open the OS trash / Recycle Bin folder."""
    open_path("shell:RecycleBinFolder" if os.name == "nt" else "trash:///")
