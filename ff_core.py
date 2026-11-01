"""Foldwise core: the instant file index and search, configuration, theme, Windows helpers (Recycle Bin, tray,
hotkey, shortcuts) and shared utilities. No GUI-window code lives here - see foldwise.py and the ui_*.py modules."""
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import ff_extras as X

try:
    import ff_shell as Sh
except Exception:  # not Windows / COM unavailable: those features are simply off
    Sh = None

_HERE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
# Portable mode: an empty file called portable.flag next to the program keeps ALL data in .\data (e.g. on a USB stick).
LEGACY_NAME = "FileFinder"  # Foldwise used to be called this: its data folder, shortcuts and scheduled names are carried over


def _migrate_data_dir(new):
    """Carry the old FileFinder data folder (index, settings, tags, ...) over to the Foldwise folder: one rename on the same drive.
    If something still holds files open the old folder is simply used again until the next start - nothing is ever lost."""
    old = new.parent / LEGACY_NAME
    if not old.is_dir() or old == new:
        return new
    try:
        if not new.exists():
            old.rename(new)
        else:  # both exist (e.g. a test run created the new one first): move over whatever the new one lacks
            import shutil
            for item in old.iterdir():
                if not (new / item.name).exists():
                    shutil.move(str(item), str(new / item.name))
            try:
                old.rmdir()
            except OSError:
                pass
    except OSError:
        return old
    # quarantine records store absolute paths into the data folder: point them at the new place
    esc = lambda p: str(p).replace(chr(92), chr(92) * 2)  # noqa - the JSON spelling of a Windows path
    for pat in ("quarantine/*/manifest.json", "malware_quarantine/*/info.json"):
        for f in new.glob(pat):
            try:
                txt = f.read_text(encoding="utf-8")
                if esc(old) in txt:
                    f.write_text(txt.replace(esc(old), esc(new)), encoding="utf-8")
            except OSError:
                pass
    return new


DB_DIR = _HERE / "data" if (_HERE / "portable.flag").exists() else _migrate_data_dir(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Foldwise")
DB_PATH = DB_DIR / "index.db"
SKIP_DIRS = {"$recycle.bin", "system volume information", "winsxs", "$windows.~bt", "$windows.~ws"}
MAX_RESULTS = 2000


# --------------------------------------------------------------------------- db
def connect():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA mmap_size=1073741824")
    con.execute("PRAGMA cache_size=-200000")
    con.execute(
        """CREATE TABLE IF NOT EXISTS files(
            id INTEGER PRIMARY KEY, name TEXT, path TEXT, name_lc TEXT, path_lc TEXT,
            ext TEXT, size INTEGER, mtime REAL, is_dir INTEGER)"""
    )
    con.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    return con


def fixed_drives():
    if os.name != "nt":
        return ["/"]
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    out = []
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
                out.append(root)
    return out


# ------------------------------------------------------------------------ index
def build_index(roots, progress=lambda n, p: None, stop=lambda: False):
    """Crawl `roots` into a fresh table, then swap it in atomically."""
    con = connect()
    con.execute("DROP TABLE IF EXISTS files_new")
    con.execute(
        """CREATE TABLE files_new(
            id INTEGER PRIMARY KEY, name TEXT, path TEXT, name_lc TEXT, path_lc TEXT,
            ext TEXT, size INTEGER, mtime REAL, is_dir INTEGER)"""
    )
    sql = "INSERT INTO files_new(name,path,name_lc,path_lc,ext,size,mtime,is_dir) VALUES(?,?,?,?,?,?,?,?)"
    batch, count = [], 0
    stack = list(roots)
    last = 0.0
    while stack and not stop():
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    isdir = e.is_dir(follow_symlinks=False)
                    if isdir and e.name.lower() in SKIP_DIRS:
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if isdir:
                    stack.append(e.path)
                ext = "" if isdir else os.path.splitext(e.name)[1][1:].lower()
                batch.append((e.name, e.path, e.name.lower(), e.path.lower(), ext,
                              0 if isdir else st.st_size, st.st_mtime, int(isdir)))
                count += 1
        if len(batch) >= 5000:
            con.executemany(sql, batch)
            batch.clear()
        now = time.time()
        if now - last > 0.15:
            last = now
            progress(count, d)
    if stop():
        con.execute("DROP TABLE files_new")
        con.commit()
        con.close()
        return None
    con.executemany(sql, batch)
    con.execute("DROP TABLE files")
    con.execute("ALTER TABLE files_new RENAME TO files")
    con.execute("CREATE INDEX IF NOT EXISTS idx_path ON files(path_lc)")
    con.execute("INSERT OR REPLACE INTO meta VALUES('indexed_at', ?)", (str(time.time()),))
    con.execute("INSERT OR REPLACE INTO meta VALUES('count', ?)", (str(count),))
    con.commit()
    con.execute("VACUUM") if count < 200000 else None
    con.close()
    return count


# ----------------------------------------------------------------------- search
SIZE_UNITS = {"b": 1, "kb": 1 << 10, "mb": 1 << 20, "gb": 1 << 30, "tb": 1 << 40}


def parse_size(s):
    m = re.fullmatch(r"([<>]=?)?(\d+(?:\.\d+)?)\s*([kmgt]?b)?", s.lower())
    if not m:
        return None
    return (m.group(1) or ">"), int(float(m.group(2)) * SIZE_UNITS[m.group(3) or "b"])


def parse_when(v):
    """modified: values -> (not_before, before) timestamps (None = open). Accepts 3 (days), 6h 2d 3w 2m 1y, today, yesterday,
    thisweek, week, month, year, 2024, 2024-05, 2024-05-17 and >2024-01-01 / <2024-01-01."""
    import datetime as dt
    v = v.strip().lower()
    now, today = time.time(), dt.date.today()
    day = lambda d: time.mktime(d.timetuple())  # noqa: E731
    one = dt.timedelta(days=1)
    fixed = {"today": (day(today), None), "yesterday": (day(today - one), day(today)),
             "thisweek": (day(today - dt.timedelta(days=today.weekday())), None),
             "week": (now - 7 * 86400, None), "month": (now - 30 * 86400, None), "year": (now - 365 * 86400, None)}
    if v in fixed:
        return fixed[v]
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([hdwmy]?)", v)
    if m and not re.fullmatch(r"(19|20)\d\d", v):  # a bare 4-digit year is a year, not 2026 days
        unit = {"h": 3600, "d": 86400, "w": 7 * 86400, "m": 30 * 86400, "y": 365 * 86400, "": 86400}[m.group(2)]
        return (now - float(m.group(1)) * unit, None)
    m = re.fullmatch(r"([<>]?)(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", v)
    if m:
        op, y, mo, d = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        try:
            if d:
                a = dt.date(y, int(mo), int(d))
                b = a + one
            elif mo:
                a = dt.date(y, int(mo), 1)
                b = dt.date(y + (a.month == 12), a.month % 12 + 1, 1)
            else:
                a, b = dt.date(y, 1, 1), dt.date(y + 1, 1, 1)
        except ValueError:
            return None
        return {"": (day(a), day(b)), ">": (day(b), None), "<": (None, day(a))}[op]
    return None


def search(con, query, limit=MAX_RESULTS, scope=None):
    try:
        tokens = re.findall(r'(?:[^\s"]|"[^"]*")+', query)
    except ValueError:
        tokens = query.split()
    where, args, regexes = [], [], []
    if scope:
        where.append("path_lc LIKE ? ESCAPE '\\'")
        args.append(like_esc(scope.lower().rstrip("\\") + "\\") + "%")
    for t in tokens:
        neg = t.startswith("-") and len(t) > 1
        if neg:
            t = t[1:]
        t = t.strip('"')
        low = t.lower()
        if not t:
            continue
        if low.startswith("ext:"):
            exts = [x.lstrip(".") for x in low[4:].split(",") if x]
            where.append(f"ext {'NOT ' if neg else ''}IN ({','.join('?' * len(exts))})")
            args += exts
        elif low.startswith("type:"):
            where.append("is_dir=?")
            args.append(1 if low[5:].startswith("d") ^ neg else 0)
        elif low.startswith("size:"):
            p = parse_size(low[5:])
            if p:
                where.append(f"is_dir=0 AND size{p[0]}?")
                args.append(p[1])
        elif low.startswith("modified:"):
            w = parse_when(low[9:])
            if w:  # (not before, before): any may be None
                if w[0] is not None:
                    where.append("mtime>=?")
                    args.append(w[0])
                if w[1] is not None:
                    where.append("mtime<?")
                    args.append(w[1])
        elif low.startswith("name:"):
            where.append(f"name_lc {'NOT ' if neg else ''}LIKE ? ESCAPE '\\'")
            args.append("%" + like_esc(low[5:]) + "%")
        elif low.startswith("re:"):
            try:
                regexes.append(re.compile(t[3:], re.I))
            except re.error:
                pass
        else:
            where.append(f"path_lc {'NOT ' if neg else ''}LIKE ? ESCAPE '\\'")
            args.append("%" + like_esc(low) + "%")
    sql = "SELECT name,path,size,mtime,is_dir FROM files"
    if where:
        sql += " WHERE " + " AND ".join(where)
    first = next((x for x in tokens if not x.startswith("-") and ":" not in x), "").strip('"').lower()
    # rank: name starts with term, then name contains term, then shorter paths first
    if first:
        # then: your own folders before system / app-data / developer folders (only for 3+ letter terms: it costs time), then shorter paths
        noise = ("(path_lc LIKE '%\\appdata\\%' OR path_lc LIKE '%\\windows\\%' OR path_lc LIKE '%\\program files%' OR path_lc LIKE '%\\programdata\\%' OR path_lc LIKE '%\\node_modules\\%' OR path_lc LIKE '%\\.git\\%' OR path_lc LIKE '%\\site-packages\\%'), ") if len(first) >= 3 else ""
        sql += (" ORDER BY (name_lc LIKE ? ESCAPE '\\') DESC, (name_lc LIKE ? ESCAPE '\\') DESC, " + noise + "length(path)")
        args += [like_esc(first) + "%", "%" + like_esc(first) + "%"]
    else:
        sql += " ORDER BY mtime DESC"
    if not regexes:  # lets SQLite keep only the best `limit` rows while sorting instead of sorting every match
        sql += " LIMIT ?"
        args.append(int(limit))
    cur = con.execute(sql, args)
    rows = []
    for r in cur:
        if regexes and not all(rx.search(r[0]) for rx in regexes):
            continue
        rows.append(r)
        if len(rows) >= limit:
            break
    return rows


def like_esc(s):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def human_size(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


# ------------------------------------------------------------- file operations
def enable_crash_log():
    """If the interpreter itself dies (access violation in a native library, fatal error) Python writes the stacks to crash.log -
    pythonw has no console, so without this such a crash would leave no trace. The file is kept small."""
    try:
        import faulthandler
        DB_DIR.mkdir(parents=True, exist_ok=True)
        p = DB_DIR / "crash.log"
        if p.exists() and p.stat().st_size > 200_000:
            p.unlink()
        f = open(p, "a", buffering=1)
        f.write(f"--- started {datetime.now():%Y-%m-%d %H:%M:%S} ---" + chr(10))
        faulthandler.enable(file=f, all_threads=True)
        return f
    except Exception:  # noqa - diagnostics must never stop the app from starting
        return None


def start_sampler(every=1.0):
    """Debug aid (env FF_SAMPLER=1): every second append the Python stack of every thread to sampler.log - finds what burns CPU."""
    import sys
    import traceback

    def run():
        me = threading.get_ident()
        with open(DB_DIR / "sampler.log", "a", encoding="utf-8") as f:
            while True:
                time.sleep(every)
                for tid, fr in sys._current_frames().items():
                    if tid == me:
                        continue
                    stack = traceback.extract_stack(fr)[-4:]
                    f.write(f"{time.strftime('%H:%M:%S')} t{tid % 1000}: " + " <- ".join(f"{os.path.basename(x.filename)}:{x.lineno}:{x.name}" for x in reversed(stack)) + chr(10))
                f.flush()
    threading.Thread(target=run, daemon=True).start()


def low_priority():
    """Run the calling (background) thread below normal priority so indexing never makes the window feel sluggish."""
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetCurrentThread.restype = ctypes.c_void_p
        k.SetThreadPriority(ctypes.c_void_p(k.GetCurrentThread()), -1)  # THREAD_PRIORITY_BELOW_NORMAL
    except Exception:  # noqa
        pass


def log_error(text):
    """Append to %LOCALAPPDATA%\\Foldwise\\error.log (pythonw has no console, so errors would vanish)."""
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        with open(DB_DIR / "error.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
    except OSError:
        pass


def recycle(paths):
    """Send files to the Recycle Bin (undoable). Paths that are already gone are skipped (they would make Windows
    reject the whole batch with 'file not found'), and if a batch still fails the items are retried one by one."""
    paths = [p for p in paths if os.path.lexists(p)]
    if not paths:
        recycle.last_rc = (0, False)
        return True
    ok = _recycle_batch(paths)
    if not ok and len(paths) > 1 and not recycle.last_rc[1]:  # not cancelled by the user: isolate the troublemaker
        ok = all([_recycle_batch([p]) for p in paths])
    return ok


def _recycle_batch(paths):
    import ctypes
    from ctypes import wintypes

    class OP(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p),
                    ("pTo", ctypes.c_void_p), ("fFlags", ctypes.c_ushort),
                    ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]

    buf = ctypes.create_unicode_buffer("\0".join(os.path.normpath(p) for p in paths) + "\0\0")
    # FO_DELETE, FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
    op = OP(None, 3, ctypes.addressof(buf), None, 0x40 | 0x10 | 0x4 | 0x4000, 0, None, None)  # ALLOWUNDO | NOCONFIRM | SILENT | WANTNUKEWARNING:
    # if Windows can't use the Recycle Bin (huge/very long-path/network/USB files) it now ASKS before deleting for good
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    recycle.last_rc = (rc, bool(op.fAnyOperationsAborted))
    log_error(f"recycle {paths!r} -> rc={rc} aborted={bool(op.fAnyOperationsAborted)}")
    return rc == 0 and not op.fAnyOperationsAborted


def unique_dest(folder, name):
    dest = os.path.join(folder, name)
    base, ext = os.path.splitext(name)
    n = 1
    while os.path.exists(dest):
        dest = os.path.join(folder, f"{base} - Copy{'' if n == 1 else f' ({n})'}{ext}")
        n += 1
    return dest



def list_dir(path, show_hidden=True):
    z = X.zip_split(path)
    if z:  # inside (or at the root of) a .zip: browse it like a folder
        try:
            return X.zip_rows(z[0], z[1])
        except Exception:  # unreadable / corrupt archive
            return None
    rows = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    isdir = e.is_dir()
                    st = e.stat()
                except OSError:
                    continue
                if not show_hidden and getattr(st, "st_file_attributes", 0) & 2:
                    continue
                rows.append((e.name, e.path, 0 if isdir else st.st_size, st.st_mtime, int(isdir)))
    except OSError:
        return None
    rows.sort(key=lambda r: (not r[4], X.natural_key(r[0])))
    return rows


# ----------------------------------------------------------------------- icon
def _render_icon_pil(n):
    """The same icon drawn with PIL at 4x and shrunk: ~100x faster than the pure-Python rasteriser below."""
    from PIL import Image, ImageDraw
    S = n * 4
    tile = Image.new("RGBA", (S, S))
    td = ImageDraw.Draw(tile)
    for y in range(S):
        f = y / S
        td.line([(0, y), (S, y)], fill=(37 - int(18 * f), 99 - int(30 * f), 235 - int(25 * f), 255))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0.02 * S, 0.02 * S, 0.98 * S, 0.98 * S), radius=0.22 * S, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(tile, (0, 0), mask)
    d = ImageDraw.Draw(img)
    white, orange = (255, 255, 255, 255), (251, 146, 60, 255)
    d.rounded_rectangle((0.15 * S, 0.26 * S, 0.46 * S, 0.42 * S), radius=0.04 * S, fill=white)
    d.rounded_rectangle((0.15 * S, 0.34 * S, 0.85 * S, 0.80 * S), radius=0.06 * S, fill=white)
    d.line([(0.72 * S, 0.70 * S), (0.87 * S, 0.85 * S)], fill=orange, width=int(0.09 * S))
    cx, cy = 0.58 * S, 0.56 * S
    d.ellipse((cx - 0.215 * S, cy - 0.215 * S, cx + 0.215 * S, cy + 0.215 * S), fill=orange)
    d.ellipse((cx - 0.155 * S, cy - 0.155 * S, cx + 0.155 * S, cy + 0.155 * S), fill=(219, 234, 254, 255))
    return img.resize((n, n), Image.LANCZOS).tobytes()


def _render_icon(n, ss=3):
    """Folder + magnifying glass on a blue tile, rasterised with supersampling (no PIL needed)."""
    try:
        return _render_icon_pil(n)
    except Exception:  # noqa - no PIL: fall back to the slow pure-Python version
        pass
    import math

    def rrect(x, y, x0, y0, x1, y1, r):
        cx, cy = min(max(x, x0 + r), x1 - r), min(max(y, y0 + r), y1 - r)
        return x0 <= x <= x1 and y0 <= y <= y1 and (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    def seg(x, y, ax, ay, bx, by, w):
        dx, dy = bx - ax, by - ay
        t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        return (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2 <= (w / 2) ** 2

    def color(x, y):
        if not rrect(x, y, 0.02, 0.02, 0.98, 0.98, 0.22):
            return (0, 0, 0, 0)
        c = (37 - int(18 * y), 99 - int(30 * y), 235 - int(25 * y), 255)  # blue gradient tile
        if rrect(x, y, 0.15, 0.26, 0.46, 0.42, 0.04) or rrect(x, y, 0.15, 0.34, 0.85, 0.80, 0.06):
            c = (255, 255, 255, 255)  # folder
        d = math.hypot(x - 0.58, y - 0.56)
        if seg(x, y, 0.72, 0.70, 0.87, 0.85, 0.09):
            c = (251, 146, 60, 255)  # handle
        if d <= 0.215:
            c = (251, 146, 60, 255) if d >= 0.155 else (219, 234, 254, 255)  # ring / lens
        return c

    out = bytearray()
    for py in range(n):
        for px in range(n):
            r = g = b = a = 0
            for sy in range(ss):
                for sx in range(ss):
                    cr, cg, cb, ca = color((px + (sx + 0.5) / ss) / n, (py + (sy + 0.5) / ss) / n)
                    r, g, b, a = r + cr * ca, g + cg * ca, b + cb * ca, a + ca
            k = ss * ss
            if a:
                out += bytes((round(r / a), round(g / a), round(b / a), round(a / k)))
            else:
                out += b"\0\0\0\0"
    return bytes(out)


def _png(n, rgba):
    import struct
    import zlib
    raw = b"".join(b"\0" + rgba[y * n * 4:(y + 1) * n * 4] for y in range(n))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ensure_icon():
    """Create foldwise.ico (16-256px) next to the index on first run; returns its path."""
    import struct
    path = DB_DIR / "foldwise.ico"
    if path.exists():
        return path
    DB_DIR.mkdir(parents=True, exist_ok=True)
    sizes = (16, 32, 48, 64, 256)
    pngs = [_png(n, _render_icon(n, 4 if n < 128 else 2)) for n in sizes]
    head = struct.pack("<HHH", 0, 1, len(sizes))
    off = 6 + 16 * len(sizes)
    entries = b""
    for n, p in zip(sizes, pngs):
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(p), off)
        off += len(p)
    path.write_bytes(head + entries + b"".join(pngs))
    return path


# --------------------------------------------------------- background / hotkey
PORT = 47653


def signal_running_instance(path=None):
    """If Foldwise is already running, ask it to show itself and return True."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.5) as s:
            s.sendall(b"show" + (b"\n" + path.encode("utf-8") if path else b""))
        return True
    except OSError:
        return False


def listen_for_show(callback):
    import socket
    srv = socket.socket()
    try:
        srv.bind(("127.0.0.1", PORT))
    except OSError:
        return
    srv.listen(5)

    def loop():
        while True:
            c, _ = srv.accept()
            with c:
                data = c.recv(65536)
                if data.startswith(b"show"):
                    callback(data[5:].decode("utf-8", "ignore") or None)

    threading.Thread(target=loop, daemon=True).start()


CONFIG = DB_DIR / "config.json"
DEFAULT_HOTKEYS = ["ctrl+alt+f", "ctrl+shift+f", "ctrl+alt+j"]
MODS = {"ctrl": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}


_CFG_LOCK = threading.RLock()


def load_config():
    """config.json, or the last good copy (config.json.bak) if it is damaged, or {} on a first run."""
    import json
    for p in (CONFIG, CONFIG.with_name(CONFIG.name + ".bak")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            continue
    return {}


def save_config(**kw):
    """Merge `kw` into config.json. Written to a temp file and swapped in (a crash can never leave half a file), the previous
    version is kept as .bak, and a lock keeps threads from interleaving writes."""
    import json
    with _CFG_LOCK:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        cfg = load_config()
        cfg.update(kw)
        tmp = CONFIG.with_name(CONFIG.name + ".tmp")
        tmp.write_text(json.dumps(cfg), encoding="utf-8")
        if CONFIG.exists():
            try:
                os.replace(CONFIG, CONFIG.with_name(CONFIG.name + ".bak"))
            except OSError:
                pass
        os.replace(tmp, CONFIG)


def parse_hotkey(spec):
    mods, key = 0, None
    for part in spec.lower().replace(" ", "").split("+"):
        if part in MODS:
            mods |= MODS[part]
        elif part == "space":
            key = 0x20
        elif re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", part):
            key = 0x6F + int(part[1:])
        elif len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        else:
            raise ValueError(f"unknown key '{part}'")
    if key is None or not mods:
        raise ValueError("need at least one modifier (ctrl/alt/shift/win) and a key")
    return mods, key


def register_hotkey(callback):
    """Global hotkey from config (or fallbacks). Returns the label that worked, or None."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    done = threading.Event()
    result = {}
    wanted = load_config().get("hotkey")
    candidates = ([wanted] if wanted else []) + DEFAULT_HOTKEYS

    def loop():
        u = ctypes.windll.user32
        for spec in candidates:
            try:
                mods, key = parse_hotkey(spec)
            except ValueError:
                continue
            if u.RegisterHotKey(None, 1, mods | 0x4000, key):
                result["label"] = "+".join(x.capitalize() for x in spec.split("+"))
                break
        done.set()
        if "label" not in result:
            return
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                callback()

    threading.Thread(target=loop, daemon=True).start()
    done.wait(2)
    return result.get("label")


def start_tray(on_show, on_quit, tip="Foldwise"):
    """Notification-area icon: click = show, right-click = Show / Quit. Returns True if created."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    u, sh, k = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.DefWindowProcW.restype = LRESULT
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD] + [ctypes.c_int] * 4 + [wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    u.LoadIconW.restype = u.LoadImageW.restype = wintypes.HANDLE
    u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int,
                             ctypes.c_int, wintypes.UINT]
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
    u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    k.GetModuleHandleW.restype = wintypes.HINSTANCE
    CB = 0x8001  # WM_USER + 1

    class WC(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("proc", WNDPROC), ("cb", ctypes.c_int), ("wb", ctypes.c_int),
                    ("inst", wintypes.HINSTANCE), ("icon", wintypes.HANDLE), ("cur", wintypes.HANDLE),
                    ("bg", wintypes.HANDLE), ("menu", wintypes.LPCWSTR), ("cls", wintypes.LPCWSTR)]

    class NID(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
                    ("hIcon", wintypes.HANDLE), ("szTip", wintypes.WCHAR * 128)]

    ready, ok = threading.Event(), {}
    nid = NID()

    def proc(hwnd, msg, wp, lp):
        if msg == CB:
            if lp == 0x202:  # WM_LBUTTONUP
                on_show()
            elif lp == 0x205:  # WM_RBUTTONUP
                m = u.CreatePopupMenu()
                u.AppendMenuW(m, 0, 1, "Show Foldwise")
                u.AppendMenuW(m, 0, 2, "Quit")
                pt = wintypes.POINT()
                u.GetCursorPos(ctypes.byref(pt))
                u.SetForegroundWindow(hwnd)
                cmd = u.TrackPopupMenu(m, 0x100 | 0x80, pt.x, pt.y, 0, hwnd, None)  # RETURNCMD|NONOTIFY
                u.DestroyMenu(m)
                if cmd == 1:
                    on_show()
                elif cmd == 2:
                    sh.Shell_NotifyIconW(2, ctypes.byref(nid))
                    on_quit()
            return 0
        return u.DefWindowProcW(hwnd, msg, wp, lp)

    cb = WNDPROC(proc)

    def loop():
        wc = WC()
        wc.proc, wc.inst, wc.cls = cb, k.GetModuleHandleW(None), "FoldwiseTray"
        u.RegisterClassW(ctypes.byref(wc))
        hwnd = u.CreateWindowExW(0, "FoldwiseTray", "Foldwise", 0, 0, 0, 0, 0, None, None, wc.inst, None)
        nid.cbSize, nid.hWnd, nid.uID = ctypes.sizeof(NID), hwnd, 1
        nid.uFlags, nid.uCallbackMessage = 0x1 | 0x2 | 0x4, CB
        nid.hIcon = u.LoadImageW(None, str(ensure_icon()), 1, 16, 16, 0x10) or u.LoadIconW(None, 32516)
        nid.szTip = tip
        ok["v"] = bool(sh.Shell_NotifyIconW(0, ctypes.byref(nid)))
        ready.set()
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    threading.Thread(target=loop, daemon=True).start()
    ready.wait(3)
    return ok.get("v", False)


# Per-user (HKCU) verbs. Only real file-system folders/drives: shell folders such as "This PC" stay with Explorer.
FOLDER_VERBS = [r"Software\Classes\Directory\shell\open", r"Software\Classes\Directory\shell\explore",
                r"Software\Classes\Drive\shell\open", r"Software\Classes\Drive\shell\explore"]
FOLDER_DEFAULT_KEYS = [r"Software\Classes\Directory\shell", r"Software\Classes\Drive\shell"]


def set_default_folder_opener(enable):
    """Registry switch (current user only): programs that ask Windows to open/explore a folder get Foldwise.
    Reversible. Only runs when YOU run it (python foldwise.py --set-default-folder-opener)."""
    import winreg
    cmd = " ".join(f'"{p}"' for p in launch_cmd()) + ' "%1"'
    hkcu = winreg.HKEY_CURRENT_USER
    for key in FOLDER_VERBS:
        if enable:
            with winreg.CreateKey(hkcu, key + "\\command") as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
                winreg.SetValueEx(k, "DelegateExecute", 0, winreg.REG_SZ, "")  # blank = run the command above
        else:
            for k_ in (key + "\\command", key):
                try:
                    winreg.DeleteKey(hkcu, k_)
                except OSError:
                    pass
    for key in FOLDER_DEFAULT_KEYS:  # make "open" the default action (Windows ships it as "none")
        try:
            if enable:
                with winreg.CreateKey(hkcu, key) as k:
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "open")
            else:
                with winreg.OpenKey(hkcu, key, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, "")
        except OSError:
            pass


def launch_cmd():
    """argv that starts this program: the packaged exe, or pythonw + foldwise.py when run from source."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable))]
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else exe), str(Path(__file__).resolve().with_name("foldwise.py"))]


def shortcut_paths():
    start = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs"
    startup = start / "Startup"
    return start / "Foldwise.lnk", startup / "Foldwise.lnk"


def migrate_shortcuts():
    """Foldwise used to be FileFinder: swap the old Start Menu / Startup shortcuts for new ones (the old ones point at the old script name)."""
    try:
        start, startup = shortcut_paths()
        for old, new, extra in ((start.parent / (LEGACY_NAME + ".lnk"), start, ""), (startup.parent / (LEGACY_NAME + ".lnk"), startup, "--hidden")):
            if old.exists():
                if not new.exists():
                    make_shortcut(new, extra)
                old.unlink(missing_ok=True)
    except Exception as e:  # noqa - a shortcut problem must never stop the program
        log_error(f"shortcut migration: {e}")


def make_shortcut(lnk, extra=""):
    target, *rest = launch_cmd()
    args = " ".join([f'"{r}"' for r in rest] + ([extra] if extra else []))
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          f"$s.TargetPath='{target}';$s.Arguments='{args}';$s.WorkingDirectory='{Path(target).parent}';"
          f"$s.Description='Foldwise';$s.IconLocation='{ensure_icon()}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, creationflags=0x08000000)


# ------------------------------------------------------------------ theme + data
PALETTES = {
    "Dark": dict(bg="#0d1117", panel="#161b22", raised="#21262d", fg="#e6edf3", muted="#8b949e",
                 accent="#58a6ff", line="#30363d", alt="#10151c", dir="#79c0ff"),
    "Midnight": dict(bg="#0b0b14", panel="#13131f", raised="#1c1c2e", fg="#e8e8f5", muted="#8a8aa8",
                     accent="#a78bfa", line="#2a2a42", alt="#0e0e19", dir="#c4b5fd"),
    "Nord": dict(bg="#2e3440", panel="#3b4252", raised="#434c5e", fg="#eceff4", muted="#9aa5b8",
                 accent="#88c0d0", line="#4c566a", alt="#323a47", dir="#8fbcbb"),
    "Forest": dict(bg="#0f1512", panel="#16201b", raised="#1f2d26", fg="#e3efe8", muted="#8aa396",
                   accent="#4ade80", line="#2b3f35", alt="#121a16", dir="#86efac"),
    "Adwaita Dark": dict(bg="#242424", panel="#303030", raised="#3d3d3d", fg="#ffffff", muted="#9a9996",
                         accent="#3584e4", line="#454545", alt="#2a2a2a", dir="#78aeed"),
    "Adwaita Light": dict(bg="#fafafa", panel="#ebebeb", raised="#dedede", fg="#2e3436", muted="#77767b",
                          accent="#3584e4", line="#d5d5d5", alt="#f6f5f4", dir="#1c71d8"),
    "Light": dict(bg="#ffffff", panel="#f3f4f6", raised="#e5e7eb", fg="#1f2328", muted="#6b7280",
                  accent="#2563eb", line="#d1d5db", alt="#f9fafb", dir="#1d4ed8"),
}
ACCENT_SWATCHES = ["#58a6ff", "#a78bfa", "#f472b6", "#fb923c", "#facc15", "#4ade80", "#2dd4bf", "#f87171"]
DEFAULT_CFG = dict(pinned_tools=[], seen_version="", zebra=True, date_fmt="31/12/2026", clock_12h=False, col_w={}, show_tutorial=True, remember_window=False, win_geo="", win_max=False, recent_tools=[], setup_done=False, rounded=True, corner_radius=8, ui_font="Segoe UI", spacing="normal", sidebar_w=220, show_chips=True, theme="Follow Windows", accent="", font_size=10, row_height=30, show_hidden=False,
                   folder_sizes=False, details_open=False, confirm_delete=True, folders_first=True,
                   start="home", last_folder="", pins=[], hotkey="", real_icons=True, live_index=True, win_e=False, view_grid=False, recent_dirs=[], visits={}, tabs=[], tab_i=0,
                   restore_tabs=False, content_index=False, frec={}, recent_ignore=[], sidebar_recent=False, sidebar_recent_n=4, search_history=[], health_alerts=False, space_history={}, backups=[], alerted={}, cleaner_protected=[], weekly_summary=False, last_weekly=0, workspaces={}, last_score=None, autoclean=False, autoclean_days=7, last_autoclean=0, autoclean_log=[], ocr_pdfs=False, notify_url="", welcomed=False, last_folder_snap=0, crash_seen=0, game_offer=True, game_best={},malware_ignore=[], malware_seen=[], malware_weekly=False, last_malware=0, vt_key="", mb_key="", online_lookup=False, update_url="", last_update_check=0, ftp_host="", ftp_user="", seen_threats=[], threats_init=False,
                   saved={}, recent=[])
T = {}


def _rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def blend(a, b, t):
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x * t + y * (1 - t)) for x, y in zip(ra, rb))


def luminance(h):
    r, g, b = _rgb(h)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def windows_prefers_light():
    """Windows' app colour mode (read-only registry lookup); dark when it can't be read."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "AppsUseLightTheme")[0])
    except Exception:  # noqa
        return False


def set_theme(name, accent=""):
    if name == "Follow Windows":
        name = "Adwaita Light" if windows_prefers_light() else "Adwaita Dark"
    p = dict(PALETTES.get(name, PALETTES["Dark"]))
    if accent:
        p["accent"] = accent
    p["sel"] = blend(p["accent"], p["bg"], 0.32)
    p["onaccent"] = "#08111f" if luminance(p["accent"]) > 0.55 else "#ffffff"
    p["dark"] = luminance(p["bg"]) < 0.5
    T.clear()
    T.update(p)


GLYPHS = {}
for _g, _exts in {
    "\U0001F5BC": "png jpg jpeg gif bmp webp svg ico tif tiff psd",
    "\U0001F3B5": "mp3 wav flac ogg m4a aac wma",
    "\U0001F3AC": "mp4 mkv avi mov wmv webm flv",
    "\U0001F4E6": "zip rar 7z tar gz iso bz2 xz",
    "\U0001F4D5": "pdf",
    "\U0001F4DD": "doc docx txt md rtf odt",
    "\U0001F4CA": "xls xlsx csv ods",
    "\U0001F4BB": "py js ts html css json c cpp h cs java rs go lua bat ps1 sh xml yml yaml toml ini cfg",
    "⚙": "exe msi dll sys",
}.items():
    for _e in _exts.split():
        GLYPHS[_e] = _g

TEXT_EXTS = set("txt md py json csv log ini xml html htm css js ts yml yaml toml cfg bat ps1 sh c cpp h cs "
                "java rs go lua sql tsv conf gitignore".split())
IMG_EXTS = set("png jpg jpeg gif bmp webp ico tif tiff".split())
TYPE_NAMES = {"pdf": "PDF document", "docx": "Word document", "doc": "Word document", "txt": "Text document",
              "png": "PNG image", "jpg": "JPEG image", "jpeg": "JPEG image", "gif": "GIF image",
              "mp4": "MP4 video", "mkv": "MKV video", "mp3": "MP3 audio", "wav": "WAV audio",
              "zip": "ZIP archive", "rar": "RAR archive", "7z": "7-Zip archive", "exe": "Application",
              "dll": "Application extension", "py": "Python file", "md": "Markdown document",
              "json": "JSON file", "xlsx": "Excel workbook", "csv": "CSV file", "pptx": "PowerPoint deck",
              "lnk": "Shortcut", "iso": "Disc image", "html": "HTML document", "js": "JavaScript file"}


def glyph(name, isdir):
    if isdir:
        return "\U0001F4C1"
    return GLYPHS.get(os.path.splitext(name)[1][1:].lower(), "\U0001F4C4")


def type_name(name, isdir):
    if isdir:
        return "File folder"
    ext = os.path.splitext(name)[1][1:].lower()
    return TYPE_NAMES.get(ext) or (f"{ext.upper()} file" if ext else "File")


DATE_FORMATS = {"31/12/2026": "%d/%m/%Y", "2026-12-31": "%Y-%m-%d", "12/31/2026": "%m/%d/%Y", "31 Dec 2026": "%d %b %Y"}
DATE_STYLE = {"fmt": "%d/%m/%Y", "h12": False}  # set from the settings (date_fmt / clock_12h)


def fmt_date(ts):
    try:
        return datetime.fromtimestamp(ts).strftime(DATE_STYLE["fmt"] + ("  %I:%M %p" if DATE_STYLE["h12"] else "  %H:%M"))
    except (OSError, ValueError, OverflowError):
        return ""


def dir_stats(path, cancelled=lambda: False):
    """(files, folders, bytes) for a folder tree, or None if cancelled."""
    files = folders = total = 0
    stack = [path]
    while stack:
        if cancelled():
            return None
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        folders += 1
                        stack.append(e.path)
                    else:
                        files += 1
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
    return files, folders, total


def shell_verb(path, verb):
    """Run a shell verb ("properties", "openas") on a path - the real Windows dialogs."""
    import ctypes
    from ctypes import wintypes

    class SEI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    sei = SEI()
    sei.cbSize = ctypes.sizeof(SEI)
    sei.fMask = 0x0000000C  # SEE_MASK_INVOKEIDLIST
    sei.lpVerb, sei.lpFile, sei.nShow = verb, os.path.normpath(path), 1
    return bool(ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)))


def dark_titlebar(win, dark=True):
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(int(dark))), 4)
    except Exception:
        pass


def apply_theme(root, cfg):
    from tkinter import ttk
    fs, F = cfg["font_size"], cfg.get("ui_font") or "Segoe UI"
    root.configure(bg=T["bg"])
    s = ttk.Style()
    s.theme_use("clam")
    s.configure(".", background=T["bg"], foreground=T["fg"], fieldbackground=T["panel"], bordercolor=T["line"],
                lightcolor=T["bg"], darkcolor=T["bg"], troughcolor=T["bg"], focuscolor=T["bg"], font=(F, fs))
    s.configure("Treeview", background=T["bg"], fieldbackground=T["bg"], foreground=T["fg"],
                rowheight=cfg["row_height"], borderwidth=0, relief="flat", font=(F, fs))
    s.map("Treeview", background=[("selected", T["sel"])], foreground=[("selected", T["fg"])])
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("Treeview.Heading", background=T["panel"], foreground=T["muted"], relief="flat", borderwidth=0,
                font=(F, max(fs - 1, 8), "bold"), padding=(10, 7))
    s.map("Treeview.Heading", background=[("active", T["raised"])], foreground=[("active", T["fg"])])
    s.configure("TButton", background=T["raised"], foreground=T["fg"], borderwidth=0, relief="flat", padding=(10, 6))
    s.map("TButton", background=[("active", T["line"]), ("pressed", T["line"])])
    s.configure("Nav.TButton", background=T["panel"], foreground=T["muted"], padding=(5, 2), font=("Segoe UI Symbol", fs + 2))
    s.map("Nav.TButton", background=[("active", T["raised"]), ("pressed", T["sel"])], foreground=[("active", T["accent"])])
    s.configure("Cmd.TButton", background=T["bg"], padding=(10, 6))
    s.map("Cmd.TButton", background=[("active", T["raised"]), ("pressed", T["line"])])
    s.configure("Crumb.TButton", background=T["panel"], padding=(5, 2))
    s.map("Crumb.TButton", background=[("active", T["raised"])])
    s.configure("Sep.TLabel", background=T["panel"], foreground=T["muted"])
    s.configure("Accent.TButton", background=T["accent"], foreground=T["onaccent"], font=(F, fs, "bold"))
    s.map("Accent.TButton", background=[("active", blend(T["accent"], T["fg"], 0.8))])
    s.configure("On.TButton", background=T["sel"], foreground=T["fg"], padding=(10, 6))
    s.configure("TEntry", fieldbackground=T["panel"], foreground=T["fg"], insertcolor=T["fg"],
                bordercolor=T["line"], lightcolor=T["line"], darkcolor=T["line"], padding=(8, 6))
    s.map("TEntry", bordercolor=[("focus", T["accent"])], lightcolor=[("focus", T["accent"])],
          darkcolor=[("focus", T["accent"])])
    s.configure("Search.TEntry", font=(F, fs + 4), padding=(12, 9))
    s.configure("TCombobox", fieldbackground=T["panel"], background=T["raised"], foreground=T["fg"],
                arrowcolor=T["fg"], bordercolor=T["line"], lightcolor=T["line"], darkcolor=T["line"])
    s.map("TCombobox", fieldbackground=[("readonly", T["panel"])], foreground=[("readonly", T["fg"])],
          bordercolor=[("focus", T["accent"])])
    s.configure("TSpinbox", fieldbackground=T["panel"], background=T["raised"], foreground=T["fg"],
                arrowcolor=T["fg"], bordercolor=T["line"], lightcolor=T["line"], darkcolor=T["line"])
    root.option_add("*TCombobox*Listbox.background", T["panel"])
    root.option_add("*TCombobox*Listbox.foreground", T["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", T["sel"])
    root.option_add("*TCombobox*Listbox.selectForeground", T["fg"])
    s.configure("TCheckbutton", background=T["bg"], foreground=T["fg"])
    s.map("TCheckbutton", background=[("active", T["bg"])], foreground=[("active", T["accent"])],
          indicatorcolor=[("selected", T["accent"]), ("!selected", T["panel"])])
    s.configure("TRadiobutton", background=T["bg"], foreground=T["fg"])
    s.map("TRadiobutton", background=[("active", T["bg"])], indicatorcolor=[("selected", T["accent"]),
                                                                           ("!selected", T["panel"])])
    s.configure("TLabel", background=T["bg"], foreground=T["fg"])
    s.configure("Status.TLabel", background=T["panel"], foreground=T["muted"], padding=(12, 6))
    s.configure("Side.TLabel", background=T["panel"], foreground=T["muted"], font=(F, 8, "bold"),
                padding=(14, 12, 0, 4))
    s.configure("Det.TLabel", background=T["panel"], foreground=T["fg"], font=(F, fs))
    s.configure("DetKey.TLabel", background=T["panel"], foreground=T["muted"], font=(F, fs))
    s.configure("DetName.TLabel", background=T["panel"], foreground=T["fg"], font=(F, fs + 3, "bold"))
    s.configure("DetHead.TLabel", background=T["panel"], foreground=T["accent"], font=(F, fs - 1, "bold"))
    s.configure("Chip.TButton", background=T["panel"], foreground=T["muted"], padding=(10, 3),
                font=(F, max(fs - 1, 8)))
    s.map("Chip.TButton", background=[("active", T["raised"])], foreground=[("active", T["fg"])])
    s.configure("ChipOn.TButton", background=T["accent"], foreground=T["onaccent"], padding=(10, 3),
                font=(F, max(fs - 1, 8), "bold"))
    s.configure("Det.TButton", background=T["raised"], foreground=T["fg"], padding=(10, 5))
    s.configure("Vertical.TScrollbar", background=blend(T["muted"], T["bg"], 0.45), troughcolor=T["panel"],
                borderwidth=0, arrowsize=16, relief="flat")
    s.map("Vertical.TScrollbar", background=[("pressed", T["accent"]), ("active", T["muted"])])
    s.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    if cfg.get("rounded", True):
        _round_buttons(s, int(cfg.get("corner_radius", 8)))
    else:  # switching the option off must undo the image-based layouts of an earlier call
        for name in _ROUND_NAMES:
            s.layout(name, [("Button.border", {"sticky": "nswe", "children": [("Button.focus", {"sticky": "nswe", "children": [
                ("Button.padding", {"sticky": "nswe", "children": [("Button.label", {"sticky": "nswe"})]})]})]})])
    return s


_ROUND_NAMES = ("TButton", "Cmd.TButton", "Nav.TButton", "Crumb.TButton", "Accent.TButton", "On.TButton", "Chip.TButton", "ChipOn.TButton", "Det.TButton")


_ROUND_IMGS = []  # PhotoImages must stay referenced
_ROUND_GEN = [0]


def _round_img(fill, outside, r, w=30, h=30, scale=4):
    from PIL import Image, ImageDraw, ImageTk
    img = Image.new("RGB", (w * scale, h * scale), outside)
    ImageDraw.Draw(img).rounded_rectangle((0, 0, w * scale - 1, h * scale - 1), r * scale, fill=fill)
    im = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))
    _ROUND_IMGS.append(im)
    return im


def _round_buttons(s, r):
    """Soft GNOME-like buttons: every button style gets rounded corners (drawn as 9-slice images in the theme's colours)."""
    del _ROUND_IMGS[:]
    _ROUND_GEN[0] += 1
    hover = lambda c: blend(T["fg"], c, 0.08)  # noqa: E731
    press = lambda c: blend(T["fg"], c, 0.16)  # noqa: E731
    specs = {  # style: (normal fill, outside colour)
        "TButton": (T["raised"], T["bg"]), "Cmd.TButton": (T["bg"], T["bg"]), "Nav.TButton": (T["panel"], T["bg"]),
        "Crumb.TButton": (T["panel"], T["panel"]), "Accent.TButton": (T["accent"], T["bg"]), "On.TButton": (T["sel"], T["bg"]),
        "Chip.TButton": (T["panel"], T["bg"]), "ChipOn.TButton": (T["accent"], T["bg"]), "Det.TButton": (T["raised"], T["panel"]),
    }
    for name, (fill, outside) in specs.items():
        el = f"RB{_ROUND_GEN[0]}" + name.replace(".", "")  # element names can not be re-created, so every call gets fresh ones
        try:
            hov = T["raised"] if name in ("Cmd.TButton", "Nav.TButton", "Crumb.TButton", "Chip.TButton") else hover(fill)
            s.element_create(el, "image", _round_img(fill, outside, r), ("pressed", _round_img(press(hov), outside, r)),
                             ("active", _round_img(hov, outside, r)), border=r + 2, padding=(1, 1), sticky="nsew")
            s.layout(name, [(el, {"sticky": "nswe", "children": [("Button.padding", {"sticky": "nswe",
                                                                                      "children": [("Button.label", {"sticky": "nswe"})]})]})])
        except Exception:  # noqa - a style that can't be rounded just stays flat
            pass
    return s


# -------------------------------------------------------------------------- gui
class ThemedBox:
    """Dark/light dialogs that match the app (instead of Windows' white message boxes). Same call signatures."""
    root = None

    @classmethod
    def _run(cls, title, message, buttons, parent=None):
        import tkinter as tk
        from tkinter import ttk
        owner = parent or cls.root
        win = tk.Toplevel(owner)
        win.title(title)
        win.configure(bg=T["bg"])
        win.transient(owner)
        win.attributes("-topmost", True)
        dark_titlebar(win, T["dark"])
        f = ttk.Frame(win, padding=22)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=message, wraplength=460, justify="left").pack(anchor="w", pady=(0, 18))
        res = {"i": len(buttons) - 1}  # closing the window counts as the last button (No / Cancel / OK)
        row = ttk.Frame(f)
        row.pack(anchor="e")

        def pick(i):
            res["i"] = i
            win.destroy()

        for i, b in enumerate(buttons):
            ttk.Button(row, text=b, style="Accent.TButton" if i == 0 else "TButton",
                       command=lambda i=i: pick(i)).pack(side="left", padx=4)
        win.bind("<Return>", lambda e: pick(0))
        win.bind("<Escape>", lambda e: pick(len(buttons) - 1))
        win.update_idletasks()
        r = cls.root
        x = r.winfo_rootx() + max(0, (r.winfo_width() - win.winfo_width()) // 2)
        y = r.winfo_rooty() + max(0, (r.winfo_height() - win.winfo_height()) // 3)
        win.geometry(f"+{x}+{y}")
        win.grab_set()
        win.focus_force()
        win.wait_window()
        return res["i"]

    @classmethod
    def askyesno(cls, title, message, parent=None, **kw):
        return cls._run(title, message, ["Yes", "No"], parent) == 0

    @classmethod
    def askokcancel(cls, title, message, parent=None, **kw):
        return cls._run(title, message, ["OK", "Cancel"], parent) == 0

    @classmethod
    def showinfo(cls, title, message, parent=None, **kw):
        cls._run(title, message, ["OK"], parent)
        return "ok"

    showwarning = showerror = showinfo


class ThemedAsk:
    @staticmethod
    def askstring(title, prompt, initialvalue="", parent=None, **kw):
        import tkinter as tk
        from tkinter import ttk
        owner = parent or ThemedBox.root
        win = tk.Toplevel(owner)
        win.title(title)
        win.configure(bg=T["bg"])
        win.transient(owner)
        win.attributes("-topmost", True)
        dark_titlebar(win, T["dark"])
        f = ttk.Frame(win, padding=22)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=prompt).pack(anchor="w", pady=(0, 8))
        v = tk.StringVar(value=initialvalue or "")
        e = ttk.Entry(f, textvariable=v, width=46)
        e.pack(fill="x", pady=(0, 18))
        res = {"v": None}

        def ok(_=None):
            res["v"] = v.get()
            win.destroy()

        row = ttk.Frame(f)
        row.pack(anchor="e")
        ttk.Button(row, text="OK", style="Accent.TButton", command=ok).pack(side="left", padx=4)
        ttk.Button(row, text="Cancel", command=win.destroy).pack(side="left", padx=4)
        win.bind("<Return>", ok)
        win.bind("<Escape>", lambda ev: win.destroy())
        win.update_idletasks()
        r = ThemedBox.root
        win.geometry(f"+{r.winfo_rootx() + max(0, (r.winfo_width() - win.winfo_width()) // 2)}"
                     f"+{r.winfo_rooty() + max(0, (r.winfo_height() - win.winfo_height()) // 3)}")
        win.grab_set()
        e.focus_force()
        e.selection_range(0, "end")
        win.wait_window()
        return res["v"]


TAGS = None  # the Tags store, set by run_gui (ff_core.TAGS = ...)
_search_core = search


def search(con, query, limit=MAX_RESULTS, scope=None, exts=None, files_only=False):
    """search() plus: ext list / files-only filters (content search) and tag: / label: tokens."""
    if exts:
        query += " ext:" + ",".join(exts)
    if files_only:
        query += " type:file"
    toks = X.tokenize(query)
    tag_toks = [t for t in toks if t.lower().startswith(("tag:", "label:"))]
    if tag_toks and TAGS is not None:
        rest = " ".join(t for t in toks if t not in tag_toks)
        wanted = None
        for t in tag_toks:
            k, _, v = t.partition(":")
            v = v.strip('"').lower()
            got = set(TAGS.paths_for(tag=v) if k.lower() == "tag" else TAGS.paths_for(color=v))
            wanted = got if wanted is None else wanted & got
        wanted = wanted or set()
        if rest.strip():
            return [r for r in _search_core(con, rest, 200000, scope) if r[1] in wanted][:limit]
        rows = []
        prefix = scope.lower().rstrip("\\") + "\\" if scope else None
        for pth in sorted(wanted):
            if prefix and not pth.lower().startswith(prefix):
                continue
            try:
                st_ = os.stat(pth)
            except OSError:
                continue
            isdir = os.path.isdir(pth)
            rows.append((os.path.basename(pth), pth, 0 if isdir else st_.st_size, st_.st_mtime, int(isdir)))
        return rows[:limit]
    return _search_core(con, query, limit, scope)


RECENT_NOISE = ("\\appdata\\local\\temp", "\\appdata\\local\\microsoft", "\\node_modules", "\\.git", "\\__pycache__",
                "\\$recycle.bin", "\\windows\\", "\\program files", "\\programdata", "ff_zip_", "\\site-packages",
                "\\.cache", "\\appdata\\local\\programs")


def recent_noise(path):
    """Folders that should never clutter the Recent/Frequent lists (system, temp, build junk, drive roots)."""
    low = path.lower().rstrip("\\")
    return len(low) <= 3 or low.endswith("\\windows") or any(n in low + "\\" for n in RECENT_NOISE)


def fuzzy_score(q, s):
    """Higher is better; None if q does not match s. Substring beats subsequence; earlier beats later."""
    q, s = q.lower(), s.lower()
    i = s.find(q)
    if i >= 0:
        return 100 - min(i, 60) + (10 if i == 0 else 0)
    pos = -1
    gaps = 0
    for ch in q:
        j = s.find(ch, pos + 1)
        if j < 0:
            return None
        gaps += j - pos - 1
        pos = j
    return max(1, 50 - gaps)


def fuzzy_ok(text):
    return len(text) >= 3 and not re.search(r'[\s":]', text) and not text.startswith("-")


def search_fuzzy(con, token, scope=None, limit=200):
    """Subsequence match on the file name: 'rprt' finds 'Report'."""
    t = [ch for ch in token.lower() if not ch.isspace()]
    sql = "SELECT name,path,size,mtime,is_dir FROM files WHERE name_lc LIKE ? ESCAPE '\\'"
    args = ["%" + "%".join(like_esc(ch) for ch in t) + "%"]
    if scope:
        sql += " AND path_lc LIKE ? ESCAPE '\\'"
        args.append(like_esc(scope.lower().rstrip("\\") + "\\") + "%")
    return con.execute(sql + " ORDER BY length(name) LIMIT ?", args + [limit]).fetchall()


THUMB_EXTS = set("pdf mp4 mkv avi mov wmv webm flv m4v 3gp mpg mpeg docx doc xlsx xls pptx ppt odt ods "
                "psd ai eps heic heif svg cr2 nef arw dng stl obj ttf otf".split())

CHIPS = [("Images", "ext:png,jpg,jpeg,gif,webp,bmp,svg"), ("Videos", "ext:mp4,mkv,avi,mov,webm"),
         ("Audio", "ext:mp3,wav,flac,ogg,m4a"), ("Docs", "ext:pdf,doc,docx,txt,md,xls,xlsx,ppt,pptx"),
         ("Archives", "ext:zip,rar,7z,tar,gz,iso"), ("Code", "ext:py,js,ts,html,css,json,c,cpp,cs,java,rs,go"),
         ("Folders", "type:dir"), ("Big (100MB+)", "size:>100mb"), ("Today", "modified:1"),
         ("Last 7 days", "modified:7")]
