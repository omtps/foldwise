"""Version, install/uninstall and self-update for the packaged Foldwise.exe.

Nothing here touches the registry. Installing = copying the exe into a per-user folder and creating Start-menu (and
optionally Startup) shortcuts. Updating = download a newer exe from a manifest URL you choose (JSON:
{"version": "1.2.0", "url": "https://.../Foldwise.exe", "sha256": "<hex>", "notes": "..."}), verify its SHA-256, then swap
it in after Foldwise exits.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

APP_VERSION = "1.0.2"

# newest first; shown in Tools > Foldwise > What's new and as a toast after an update (keep CHANGELOG.md in step)
WHATS_NEW = [
    ('1.0.2', ['Nearby devices: send files to and receive from phones and PCs running the free LocalSend app (or another Foldwise) on your network; right-click files > Send to a nearby device; receiving is off until you turn it on and always asks first', "Faster copying: Foldwise uses Windows' own copy routine and copies many small files at once (measured here: 4000 small files 3.5x faster, a 1 GB file about 4x faster before the drive itself is the limit)", 'Moving files to another drive now shows progress, can be cancelled and removes the original only after everything arrived', 'Tutorial button in Nearby devices']),
    ('1.0.1', ["Mini-games fixed: they start on your first click, pause when the pointer leaves, can be dragged by the title bar, no longer cover a tool's buttons and keep playing when you open another tool", 'Foldwise has its own file and folder chooser: tools no longer open the Windows file dialog', 'Customize > Default file manager: make Foldwise open your folders instead of File Explorer, one click to switch back (reversible, undoes itself if Foldwise is deleted)', 'Tutorial buttons in the FTP / SFTP / WebDAV and Phone notifications tools']),
    ("1.0.0", ["File manager with tabs, split view, previews, tags, archives as folders and undo",
               "Instant search over every drive, with optional search inside documents and PDFs",
               "Smart cleaner, duplicate and look-alike photo finders, folder size history",
               "PC health center, security audit and Windows Defender plus a deep malware check",
               "Encrypted vaults, scheduled backups, folder sync, FTP / SFTP / WebDAV",
               "Themes, a setup wizard, a guided tour, mini-games, and updates from GitHub"]),
]
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "Foldwise"
NO_WINDOW = 0x08000000
SYS = "%SystemRoot%\\System32\\"  # full paths: a PATH with Git's GNU find/timeout in front would break the helper script
SLEEP = SYS + "ping.exe -n 2 127.0.0.1 >nul"


def frozen():
    return bool(getattr(sys, "frozen", False))


def exe_path():
    return Path(sys.executable) if frozen() else None


def is_installed():
    e = exe_path()
    return bool(e) and e.parent.resolve() in (INSTALL_DIR.resolve(), INSTALL_DIR.with_name("FileFinder").resolve())


def mode():
    """'installed', 'portable exe' or 'from source' - shown in the About window."""
    if frozen():
        return "installed" if is_installed() else "portable exe"
    return "from source"


def parse_version(v):
    out = []
    for part in str(v).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def is_newer(candidate, current=APP_VERSION):
    a, b = parse_version(candidate), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


# "owner/name" of the Foldwise repository on GitHub. When it is set, releases of that repository are what the program updates from
# (a release carries Foldwise.exe and update.json). It can also be typed in About on each PC, which then wins over this default.
DEFAULT_REPO = "omtps/foldwise"


def manifest_url(source):
    """Update source -> address of the update.json: 'owner/name' means the latest GitHub release of that repository, anything
    else must be a full https:// address. An empty source falls back to DEFAULT_REPO ('' when neither is set)."""
    source = (source or "").strip() or DEFAULT_REPO
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source):
        return f"https://github.com/{source}/releases/latest/download/update.json"
    return source


def check_update(url, timeout=12):
    """The manifest dict when a newer version is offered at `url` (an address or 'owner/name'), else None.
    Raises OSError/ValueError on problems."""
    url = manifest_url(url)
    if not url.lower().startswith(("https://", "http://")):
        raise ValueError("Set the update source first: your GitHub repository as owner/name, or the address of an update.json")
    req = urllib.request.Request(url, headers={"User-Agent": f"Foldwise/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        info = json.loads(r.read(200_000).decode("utf-8"))
    if not isinstance(info, dict) or "version" not in info or "url" not in info:
        raise ValueError("That address doesn't look like a Foldwise update manifest")
    return info if is_newer(info["version"]) else None


def source_dir():
    """The folder of the git checkout this program runs from (source mode), else None."""
    if frozen():
        return None
    d = Path(__file__).resolve().parent
    return d if (d / ".git").exists() else None


def _git(args, cwd, timeout=60):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW,
                       encoding="utf-8", errors="replace")
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def git_check(cwd):
    """(behind, log): how many commits the remote has that this checkout lacks (after a fetch) and the newest few as text."""
    rc, out = _git(["fetch", "--quiet"], cwd, 90)
    if rc:
        raise OSError(out or "git fetch failed")
    rc, out = _git(["rev-list", "--count", "HEAD..@{u}"], cwd)
    if rc:
        raise OSError("This branch has no upstream yet: push it first (git push -u origin main)")
    behind = int(out or 0)
    return behind, (_git(["log", "--oneline", "-n", "8", "HEAD..@{u}"], cwd)[1] if behind else "")


def git_pull(cwd):
    """Fast-forward only: never merges and never touches local edits (it refuses when tracked files were changed)."""
    rc, out = _git(["status", "--porcelain", "--untracked-files=no"], cwd)
    if rc == 0 and out.strip():
        raise OSError("This folder has uncommitted changes. Commit or stash them first, then update.")
    rc, out = _git(["pull", "--ff-only", "--quiet"], cwd, 180)
    if rc:
        raise OSError(out or "git pull failed")
    return out


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def download_update(info, progress=lambda done, total: None, cancel=lambda: False):
    """Download info['url'] to a temp file and verify info['sha256'] (required). Returns the file path."""
    want = (info.get("sha256") or "").lower()
    if len(want) != 64:
        raise ValueError("The update manifest has no SHA-256 checksum, so it can't be verified")
    dst = Path(tempfile.gettempdir()) / f"Foldwise-update-{info['version']}.exe"
    req = urllib.request.Request(info["url"], headers={"User-Agent": f"Foldwise/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel():
                raise InterruptedError("cancelled")
            b = r.read(1 << 16)
            if not b:
                break
            f.write(b)
            done += len(b)
            progress(done, total)
    if sha256_of(dst) != want:
        dst.unlink(missing_ok=True)
        raise ValueError("The downloaded file does not match its checksum - it was NOT installed")
    return dst


def _run_after_exit(script_lines):
    """Run a tiny .cmd after this process has ended (so files in use can be replaced). Returns the script path."""
    path = Path(tempfile.gettempdir()) / f"foldwise-{os.getpid()}.cmd"
    pid = os.getpid()
    body = ['@echo off', ':wait', f'{SYS}tasklist.exe /FI "PID eq {pid}" 2>nul | {SYS}find.exe "{pid}" >nul && ({SLEEP} & goto wait)'] + script_lines + ['del "%~f0"']
    path.write_text("\r\n".join(body) + "\r\n", encoding="utf-8")
    subprocess.Popen(["cmd.exe", "/c", str(path)], creationflags=NO_WINDOW | 0x00000200, close_fds=True)  # hidden console, own process group
    return path


def _retry(cmd, label):
    """cmd.exe lines that run `cmd` until it succeeds (the exe may stay locked for a moment after we exit)."""
    return [f"set n{label}=0", f":retry{label}", f"{cmd} >nul 2>&1 && goto done{label}", f"set /a n{label}+=1",
            f"if %n{label}% lss 30 ({SLEEP} & goto retry{label})", f":done{label}"]


def _swap_in(new_path, target):
    """Put `new_path` in place of `target` even while `target` is RUNNING: Windows won't let you overwrite or delete a running
    exe, but it does let you rename it. The old copy keeps running from '<name>.old' until Foldwise restarts."""
    new_path, target = Path(new_path), Path(target)
    old = None
    if target.exists():
        old = target.with_name(target.name + ".old")
        try:
            old.unlink(missing_ok=True)
        except OSError:  # the previous .old is still running/locked: pick another name
            old = target.with_name(f"{target.name}.{int(time.time())}.old")
        os.replace(target, old)
    try:
        shutil.copy2(new_path, target)
    except BaseException:
        if old is not None:
            os.replace(old, target)  # put the working copy back
        raise
    return old


def _pending_path():
    import ff_core
    return Path(ff_core.DB_DIR) / "update.pending"


def selftest_exe(path, timeout=120):
    """Run `<exe> --selftest`; returns (ok, output). A new version must pass this BEFORE it replaces the working one."""
    try:
        r = subprocess.run([str(path), "--selftest"], capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    out = Path(tempfile.gettempdir(), "foldwise-selftest.txt")
    text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
    return r.returncode == 0 and "OK" in text, text.strip()


def boot_check():
    """Call at start-up. After a live update the new exe must reach 'healthy' (see confirm_update) within a few starts;
    if it keeps failing, put the previous version back. Returns 'rolled back' / 'pending' / None."""
    p = _pending_path()
    if not p.exists() or not frozen():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        p.unlink(missing_ok=True)
        return None
    d["tries"] = d.get("tries", 0) + 1
    old = Path(d.get("old", ""))
    if d["tries"] > 2 and old.is_file():
        me = exe_path()
        bad = me.with_name(me.name + ".bad")
        try:
            bad.unlink(missing_ok=True)
            os.replace(me, bad)
            os.replace(old, me)
        except OSError:
            return None
        p.unlink(missing_ok=True)
        return "rolled back"
    p.write_text(json.dumps(d), encoding="utf-8")
    return "pending"


def confirm_update():
    """The new version has been running fine: forget the rollback record so the old copy can be cleaned up."""
    p = _pending_path()
    if p.exists():
        p.unlink(missing_ok=True)
        cleanup_old()


def cleanup_old(folder=None):
    """Delete leftovers of earlier live updates ('*.old' next to the exe). Called at every start; locked ones are skipped.
    The previous version is kept while an update is still waiting to prove itself (rollback)."""
    try:
        if _pending_path().exists():
            return
    except Exception:
        pass
    base = Path(folder) if folder else (exe_path().parent if exe_path() else None)
    if not base or not base.is_dir():
        return
    for p in base.glob("*.old"):
        try:
            p.unlink()
        except OSError:
            pass


def apply_update_live(new_exe):
    """Install the new exe NOW, while Foldwise keeps running. The new version starts at the next launch/restart."""
    me = exe_path()
    if not me:
        raise RuntimeError("Updating only works for the packaged Foldwise.exe")
    ok, text = selftest_exe(new_exe)
    if not ok:
        raise ValueError("The new version failed its own self-test, so it was NOT installed:\n" + text[:400])
    old = _swap_in(new_exe, me)
    try:
        _pending_path().write_text(json.dumps({"old": str(old) if old else "", "from": APP_VERSION, "tries": 0, "time": time.time()}), encoding="utf-8")
    except OSError:
        pass
    try:
        Path(new_exe).unlink()
    except OSError:
        pass
    return me


def restart_app(argv=None):
    """Start a fresh Foldwise as soon as this process has ended (nothing to close by hand). The caller must exit right after."""
    argv = argv or (([str(exe_path())] if frozen() else None) or _source_cmd())
    quoted = " ".join(f'"{a}"' for a in argv)
    _run_after_exit([f'start "" {quoted} --hidden'])


def _source_cmd():
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else exe), str(Path(__file__).resolve().with_name("foldwise.py"))]


def apply_update(new_exe, restart=True):
    """Replace the running exe with `new_exe` once we have exited, then start it. The caller must quit right after."""
    me = exe_path()
    if not me:
        raise RuntimeError("Updating only works for the packaged Foldwise.exe")
    lines = _retry(f'copy /Y "{new_exe}" "{me}"', "a") + [f'del "{new_exe}" 2>nul']
    if restart:
        lines.append(f'start "" "{me}" --hidden')
    _run_after_exit(lines)


def make_lnk(lnk, target, args="", icon=None, desc="Foldwise"):
    Path(lnk).parent.mkdir(parents=True, exist_ok=True)
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{target}';$s.Arguments='{args}';"
          f"$s.WorkingDirectory='{Path(target).parent}';$s.Description='{desc}';" + (f"$s.IconLocation='{icon}';" if icon else "") + "$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, creationflags=NO_WINDOW)


def shortcut_paths(appdata=None):
    base = Path(appdata or os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return base / "Foldwise.lnk", base / "Startup" / "Foldwise.lnk"


def install(dest_dir=None, autostart=True, shortcuts=True, appdata=None):
    """Copy this exe into the install folder and create shortcuts. Returns the installed exe path."""
    me = exe_path()
    if not me:
        raise RuntimeError("Installing only works for the packaged Foldwise.exe")
    dest = Path(dest_dir or INSTALL_DIR)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "Foldwise.exe"
    if me.resolve() != target.resolve():
        tmp = target.with_suffix(".new")
        tmp.write_bytes(me.read_bytes())
        os.replace(tmp, target)
    if shortcuts:
        start, startup = shortcut_paths(appdata)
        make_lnk(start, target, icon=target)
        if autostart:
            make_lnk(startup, target, "--hidden", icon=target)
    return target


def uninstall(dest_dir=None, appdata=None, remove_data=False):
    """Remove shortcuts and (after exit) the installed exe. Your settings/data folder is kept unless remove_data."""
    start, startup = shortcut_paths(appdata)
    for p in (start, startup, start.with_name("FileFinder.lnk"), startup.with_name("FileFinder.lnk")):
        p.unlink(missing_ok=True)
    dest = Path(dest_dir or INSTALL_DIR)
    lines = _retry(f'rmdir /S /Q "{dest}"', "a")
    if remove_data:
        lines.append(f'rmdir /S /Q "{Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Foldwise"}"')
    _run_after_exit(lines)
