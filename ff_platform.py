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
    """Open an OS settings page by a neutral name: 'startup_apps', 'windows_update', 'storage', 'network', 'installed_apps', 'task_scheduler', 'security_center', 'startup_folder', 'wifi', 'firewall'."""
    uris = {"startup_apps": "ms-settings:startupapps", "windows_update": "ms-settings:windowsupdate", "storage": "ms-settings:storagesense",
            "network": "ms-settings:network", "installed_apps": "ms-settings:appsfeatures", "task_scheduler": "taskschd.msc",
            "security_center": "windowsdefender:", "startup_folder": "shell:startup",
            "wifi": "ms-settings:network-wifi", "firewall": "windowsdefender://network"}
    if os.name == "nt" and page in uris:
        os.startfile(uris[page])


def recycle_bin_folder():
    """Open the OS trash / Recycle Bin folder."""
    open_path("shell:RecycleBinFolder" if os.name == "nt" else "trash:///")


def network_report(program):
    """Read-only facts about this PC's network for the file-sharing check: ([(connection name, 'Public'|'Private'|'DomainAuthenticated')],
    [(rule name, profiles)] of inbound Block rules that apply to `program`). Empty lists where the OS has no such thing or the query fails."""
    if os.name != "nt":
        return [], []
    import subprocess
    ps = ("$ErrorActionPreference='SilentlyContinue';"
          "Get-NetConnectionProfile | ForEach-Object { 'N|' + $_.Name + '|' + $_.NetworkCategory };"
          "$exe=$env:FF_PROGRAM;"
          "Get-NetFirewallRule -Direction Inbound -Enabled True -Action Block | ForEach-Object { $a=($_ | Get-NetFirewallApplicationFilter).Program;"
          "if ($a -and $exe -and ($a -ieq $exe)) { 'B|' + $_.DisplayName + '|' + $_.Profile } }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=40, creationflags=0x08000000,
                             env=dict(os.environ, FF_PROGRAM=str(program))).stdout
    except (OSError, subprocess.TimeoutExpired):
        return [], []
    nets, blocks = [], []
    for line in out.splitlines():
        parts = line.strip().split("|")
        if parts[0] == "N" and len(parts) >= 3:
            nets.append((parts[1], parts[2]))
        elif parts[0] == "B" and len(parts) >= 3:
            blocks.append((parts[1], parts[2]))
    return nets, blocks
