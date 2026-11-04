"""The ONE place for small OS-specific actions in new code: open a file/folder/URL with the default app,
open an OS settings page. Another platform would implement the same functions."""
import functools
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


# ---- audio playback (the small player in the previews). One sound at a time; Windows plays it through its own multimedia service (MCI).
_AUDIO = {"path": None}


def _mci(cmd):
    if os.name != "nt":
        raise OSError("Audio playback is only available on Windows.")
    import ctypes
    buf = ctypes.create_unicode_buffer(256)
    err = ctypes.windll.winmm.mciSendStringW(cmd, buf, 255, 0)
    if err:
        eb = ctypes.create_unicode_buffer(256)
        ctypes.windll.winmm.mciGetErrorStringW(err, eb, 255)
        raise OSError(eb.value or f"multimedia error {err}")
    return buf.value


def audio_open(path):
    """Prepare a sound file (closes the previous one). Raises OSError with a plain reason when Windows cannot play that format."""
    audio_close()
    _mci(f'open "{path}" alias ffaudio')
    _mci("set ffaudio time format milliseconds")
    _AUDIO["path"] = path


def audio_play():
    _mci("play ffaudio")


def audio_pause():
    _mci("pause ffaudio")


def audio_resume():
    _mci("resume ffaudio")


def audio_close():
    if _AUDIO["path"]:
        try:
            _mci("close ffaudio")
        except OSError:
            pass
        _AUDIO["path"] = None


def audio_current():
    return _AUDIO["path"]


def audio_status():
    """(mode, position_ms, length_ms); mode is 'playing', 'paused', 'stopped' or 'closed'."""
    if not _AUDIO["path"]:
        return "closed", 0, 0
    try:
        return _mci("status ffaudio mode"), int(_mci("status ffaudio position") or 0), int(_mci("status ffaudio length") or 0)
    except (OSError, ValueError):
        return "closed", 0, 0


# ---- online-only files (OneDrive and other cloud folders, Phone Link photos): their data is NOT on this PC, and opening one downloads it
# (for Phone Link that means Windows reaching out to your phone). With the guard on (the default) Pinefiles never reads such a file by itself.
class OnlineOnly(OSError):
    """The file is a placeholder: its data lives in the cloud or on a phone."""


GUARD = {"on": True}  # the setting 'skip_online_only'
_RECALL = 0x400000 | 0x40000 | 0x1000  # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE


def is_placeholder(st):
    """True when this stat result describes a placeholder whose data is not on this PC (whatever the guard setting is)."""
    return bool(getattr(st, "st_file_attributes", 0) & _RECALL)


def is_online_only(path, st=None):
    """True when the guard is on and `path` is a placeholder whose data is not on this PC (looking at it does not download it)."""
    if not GUARD["on"]:
        return False
    try:
        return is_placeholder(st or os.lstat(path))
    except OSError:
        return False


def local_only(default=OnlineOnly):
    """Decorator for readers whose first argument is a file path: an online-only file is not opened. The reader returns `default`
    (a value, or a function such as `list` that makes one) instead, or raises OnlineOnly when `default` is that class."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(path, *a, **k):
            if is_online_only(path):
                if default is OnlineOnly:
                    raise OnlineOnly(f"{os.path.basename(path)} is stored online (cloud or phone); Pinefiles did not open it, so nothing was downloaded.")
                return default() if callable(default) else default
            return fn(path, *a, **k)
        return wrapper
    return deco
