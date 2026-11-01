"""Support helpers: a one-click problem report and a look at what Foldwise stores on disk."""
import json
import platform
import sys
import time
import zipfile
from pathlib import Path

import ff_core
import ff_update

PRIVATE_KEYS = {"vt_key", "mb_key", "ftp_user", "ftp_host", "update_url", "malware_ignore", "backups", "workspaces", "pins", "search_history"}


def tail(path, lines=400):
    try:
        return "\n".join(Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


def make_report(dest_dir=None):
    """Zip with version, system info, the last lines of error.log and settings WITHOUT private values. Returns the zip path."""
    dest = Path(dest_dir or (Path.home() / "Desktop"))
    dest.mkdir(parents=True, exist_ok=True)
    z = dest / f"Foldwise problem report {time.strftime('%Y-%m-%d %H%M')}.zip"
    cfg = {k: ("(hidden)" if k in PRIVATE_KEYS else v) for k, v in ff_core.load_config().items() if k not in ("frec", "visits", "space_history", "recent_dirs", "tabs")}
    info = (f"Foldwise {ff_update.APP_VERSION} ({ff_update.mode()})\nWindows: {platform.platform()}\nPython: {sys.version.split()[0]}\n"
            f"Data folder: {ff_core.DB_DIR}\nTime: {time.ctime()}\n")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("info.txt", info)
        f.writestr("error-log-tail.txt", tail(ff_core.DB_DIR / "error.log"))
        f.writestr("crash-log-tail.txt", tail(ff_core.DB_DIR / "crash.log"))
        f.writestr("settings.json", json.dumps(cfg, indent=1, default=str))
        f.writestr("storage.txt", "\n".join(f"{n}: {s / 1048576:.1f} MB" for n, s in storage_report()))
    return z


def _size(p):
    p = Path(p)
    try:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return 0


def storage_report():
    """[(label, bytes)] for everything Foldwise keeps in its data folder."""
    d = Path(ff_core.DB_DIR)
    parts = [("File index (index.db)", [d / "index.db", d / "index.db-wal", d / "index.db-shm"]),
             ("Content search index (content.db)", [d / "content.db", d / "content.db-wal", d / "content.db-shm"]),
             ("Tags and labels", [d / "tags.db"]), ("Thumbnail cache", [d / "thumbs"]), ("Auto-clean restore list", [d / "quarantine"]),
             ("Malware quarantine", [d / "malware_quarantine"]), ("Trend history", [d / "history.json"]),
             ("Integrity fingerprints", [d / "manifests"]), ("Error log", [d / "error.log"])]
    return [(label, sum(_size(p) for p in paths)) for label, paths in parts]


def compact_content_index():
    """Shrink content.db (VACUUM). Needs free disk space about the size of the database and can take minutes. Returns (before, after)."""
    import sqlite3
    p = Path(ff_core.DB_DIR) / "content.db"
    before = _size(p) + _size(str(p) + "-wal")
    con = sqlite3.connect(str(p), timeout=60)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("VACUUM")
    finally:
        con.close()
    return before, _size(p) + _size(str(p) + "-wal")
