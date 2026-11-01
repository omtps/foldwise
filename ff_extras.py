"""Backend helpers for Foldwise (no GUI code here).

 - Watcher        keeps the search index current by listening to NTFS change notifications
 - ShellIcons     real Windows icons per file type, as PIL images
 - content search read text / Office files and match words inside them
 - duplicates     size -> partial hash -> full hash
 - squarify       treemap layout for the disk-usage view
 - plan_rename    preview for bulk rename
 - transfer       copy/move with progress + cancel; restore_from_recycle for undoing deletes
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat as statmod
import struct
import tarfile
import subprocess
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

try:
    from ctypes import wintypes
except ValueError:  # non-windows import safety
    wintypes = None


# ------------------------------------------------------------------ live index
def ensure_index(db_path):
    con = sqlite3.connect(db_path, timeout=60)
    con.execute("CREATE INDEX IF NOT EXISTS idx_path ON files(path_lc)")
    con.commit()
    con.close()


class Watcher:
    """Applies file-system changes to the `files` table within ~1.5 s, and tells the GUI which paths changed."""

    def __init__(self, db_path, roots, skip_dirs=(), ignore_prefixes=()):
        self.db_path, self.roots = db_path, list(roots)
        self.skip = {s.lower() for s in skip_dirs}
        self.ignore = [os.path.normcase(p) for p in ignore_prefixes]
        self.pending, self.lock = {}, threading.Lock()
        self.stop = threading.Event()
        self.on_change = None  # callback(list_of_paths), called from a worker thread
        self.overflow = False
        self.applied = 0
        self._last_count = 0

    def start(self):
        for r in self.roots:
            threading.Thread(target=self._watch, args=(r,), daemon=True).start()
        threading.Thread(target=self._apply_loop, daemon=True).start()

    # -- reading change notifications
    def _watch(self, root):
        k = ctypes.windll.kernel32
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        k.CreateFileW.restype = ctypes.c_void_p
        k.ReadDirectoryChangesW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
                                            ctypes.c_void_p]
        h = k.CreateFileW(root, 1, 7, None, 3, 0x02000000, None)  # LIST_DIRECTORY, share all, BACKUP_SEMANTICS
        if h in (None, 0, ctypes.c_void_p(-1).value):
            return
        buf = ctypes.create_string_buffer(1 << 16)
        n = wintypes.DWORD()
        while not self.stop.is_set():
            ok = k.ReadDirectoryChangesW(h, buf, len(buf), True, 0x1 | 0x2 | 0x8 | 0x10, ctypes.byref(n), None, None)
            if not ok:
                time.sleep(2)
                continue
            if n.value == 0:
                self.overflow = True
                continue
            raw, off = buf.raw, 0
            while True:
                nxt, action, ln = struct.unpack_from("<III", raw, off)
                name = raw[off + 12: off + 12 + ln].decode("utf-16-le", "ignore")
                self._queue(os.path.join(root, name), action)
                if not nxt:
                    break
                off += nxt

    def _queue(self, path, action):
        low = os.path.normcase(path)
        if any(low.startswith(i) for i in self.ignore):
            return
        if self.skip and any(p in self.skip for p in low.split("\\")):
            return
        kind = "del" if action in (2, 4) else ("new" if action in (1, 5) else "up")
        with self.lock:
            if kind == "up" and self.pending.get(path) == "new":
                return
            self.pending[path] = kind

    # -- applying them
    def _apply_loop(self):
        while not self.stop.wait(1.5):
            with self.lock:
                items, self.pending = self.pending, {}
            if not items:
                continue
            try:
                self._apply(items)
            except sqlite3.Error:  # index busy (e.g. a full re-index is swapping tables): retry next round
                with self.lock:
                    for p, kind in items.items():
                        self.pending.setdefault(p, kind)
                continue
            self.applied += len(items)
            if self.on_change:
                try:
                    self.on_change(list(items))
                except Exception:
                    pass

    def _apply(self, items):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.execute("PRAGMA synchronous=OFF")
        changed = False
        for path, kind in items.items():
            if kind == "del":
                changed |= self._delete(con, path)
                continue
            try:
                st = os.lstat(path)
            except OSError:
                changed |= self._delete(con, path)
                continue
            isdir = statmod.S_ISDIR(st.st_mode)
            self._upsert(con, path, st, isdir)
            changed = True
            if kind == "new" and isdir:  # moved/created folder: its children produce no events of their own
                self._walk(con, path)
        if changed and time.time() - self._last_count > 30:
            n = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            con.execute("INSERT OR REPLACE INTO meta VALUES('count', ?)", (str(n),))
            self._last_count = time.time()
        con.commit()
        con.close()

    @staticmethod
    def _delete(con, path):
        low = path.lower()
        cur = con.execute("DELETE FROM files WHERE path_lc=? OR (path_lc>=? AND path_lc<?)",
                          (low, low + "\\", low + "]"))
        return cur.rowcount > 0

    @staticmethod
    def _upsert(con, path, st, isdir):
        name = os.path.basename(path)
        ext = "" if isdir else os.path.splitext(name)[1][1:].lower()
        row = (name, path, name.lower(), ext, 0 if isdir else st.st_size, st.st_mtime, int(isdir))
        cur = con.execute("UPDATE files SET name=?, path=?, name_lc=?, ext=?, size=?, mtime=?, is_dir=? "
                          "WHERE path_lc=?", row + (path.lower(),))
        if cur.rowcount == 0:
            con.execute("INSERT INTO files(name,path,name_lc,ext,size,mtime,is_dir,path_lc) VALUES(?,?,?,?,?,?,?,?)",
                        row + (path.lower(),))

    def _walk(self, con, top, cap=50000):
        stack, n = [top], 0
        while stack and n < cap:
            try:
                it = os.scandir(stack.pop())
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                        isdir = e.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    if isdir and e.name.lower() in self.skip:
                        continue
                    self._upsert(con, e.path, st, isdir)
                    n += 1
                    if isdir:
                        stack.append(e.path)


# ------------------------------------------------------------------ shell icons
class ShellIcons:
    """Real Windows icon for an extension (or folder) as a PIL RGBA image. Thread-safe, cached."""

    def __init__(self):
        self.cache, self.lock = {}, threading.Lock()
        self.ok = os.name == "nt"
        if self.ok:
            try:
                from PIL import Image  # noqa: F401
                self._setup()
            except Exception:
                self.ok = False

    def _setup(self):
        sh, gdi, u = ctypes.windll.shell32, ctypes.windll.gdi32, ctypes.windll.user32

        class SFI(ctypes.Structure):
            _fields_ = [("hIcon", ctypes.c_void_p), ("iIcon", ctypes.c_int), ("dwAttributes", wintypes.DWORD),
                        ("szDisplayName", wintypes.WCHAR * 260), ("szTypeName", wintypes.WCHAR * 80)]

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPels", wintypes.LONG), ("biYPels", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        self.SFI, self.BIH = SFI, BIH
        self.sh, self.gdi, self.u = sh, gdi, u
        sh.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(SFI), wintypes.UINT, wintypes.UINT]
        sh.SHGetFileInfoW.restype = ctypes.c_size_t
        gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        gdi.CreateCompatibleDC.restype = ctypes.c_void_p
        gdi.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
                                         ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, wintypes.DWORD]
        gdi.CreateDIBSection.restype = ctypes.c_void_p
        gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi.SelectObject.restype = ctypes.c_void_p
        gdi.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi.DeleteDC.argtypes = [ctypes.c_void_p]
        u.DrawIconEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
                                 ctypes.c_int, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
        u.DestroyIcon.argtypes = [ctypes.c_void_p]

    def pil(self, ext, isdir, size=20):
        if not self.ok:
            return None
        key = "<dir>" if isdir else ext.lower()
        ck = f"{key}@{size}"
        with self.lock:
            if ck in self.cache:
                return self.cache[ck]
        try:
            img = self._render(key, isdir, size)
        except Exception:
            img = None
        with self.lock:
            self.cache[ck] = img
        return img

    def _render(self, key, isdir, size):
        from PIL import Image
        sfi = self.SFI()
        name = "folder" if isdir else "file." + (key if key else "x")
        attrs = 0x10 if isdir else 0x80
        # SHGFI_ICON | SHGFI_USEFILEATTRIBUTES  (large icon, downscaled for crispness)
        if not self.sh.SHGetFileInfoW(name, attrs, ctypes.byref(sfi), ctypes.sizeof(sfi), 0x100 | 0x10):
            return None
        hicon, S = sfi.hIcon, 32
        bih = self.BIH(ctypes.sizeof(self.BIH), S, -S, 1, 32, 0, 0, 0, 0, 0, 0)
        hdc = self.gdi.CreateCompatibleDC(None)
        bits = ctypes.c_void_p()
        hbm = self.gdi.CreateDIBSection(hdc, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
        old = self.gdi.SelectObject(hdc, hbm)
        self.u.DrawIconEx(hdc, 0, 0, hicon, S, S, 0, None, 3)
        data = ctypes.string_at(bits, S * S * 4)
        self.gdi.SelectObject(hdc, old)
        self.gdi.DeleteObject(hbm)
        self.gdi.DeleteDC(hdc)
        self.u.DestroyIcon(hicon)
        img = Image.frombuffer("RGBA", (S, S), data, "raw", "BGRa", 0, 1)
        if img.getchannel("A").getextrema()[1] == 0:  # icon without alpha: treat non-black as opaque
            raw = Image.frombuffer("RGBA", (S, S), data, "raw", "BGRA", 0, 1)
            alpha = raw.convert("L").point(lambda v: 255 if v else 0)
            img = raw.copy()
            img.putalpha(alpha)
        return img.resize((size, size), Image.LANCZOS)


# --------------------------------------------------------------- content search
OFFICE = {"docx", "xlsx", "pptx"}
TEXTY = set("txt md py json csv log ini xml html htm css js ts yml yaml toml cfg bat ps1 sh c cpp h cs java rs go lua "
            "sql tsv conf tex rst srt vtt ahk kt swift php rb pl r jsx tsx vue svelte gradle properties env".split())
CONTENT_EXTS = sorted(TEXTY | OFFICE)


def tokenize(query):
    """Split on spaces, keeping quoted phrases (even inside key:"a b") together."""
    return re.findall(r'(?:[^\s"]|"[^"]*")+', query)


def split_content(query):
    """'report ext:pdf content:"net profit"' -> ('report ext:pdf', ['net profit'])."""
    toks = tokenize(query)
    rest, terms = [], []
    for t in toks:
        low = t.lower()
        if low.startswith("content:") or low.startswith("in:"):
            term = t.split(":", 1)[1].strip('"').strip()
            if term:
                terms.append(term.lower())
        else:
            rest.append(t)
    return " ".join(rest), terms


def read_text(path, limit=2_000_000):
    ext = os.path.splitext(path)[1][1:].lower()
    try:
        if ext in OFFICE:
            names = {"docx": ["word/document.xml"], "xlsx": ["xl/sharedStrings.xml"]}.get(ext)
            with zipfile.ZipFile(path) as z:
                if names is None:
                    names = [n for n in z.namelist() if n.startswith("ppt/slides/slide")]
                xml = " ".join(z.read(n).decode("utf-8", "ignore") for n in names if n in z.namelist())
            return re.sub(r"<[^>]+>", " ", xml)
        with open(path, "rb") as f:
            data = f.read(limit)
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return data.decode("utf-16", "ignore")
        if b"\0" in data[:4096]:
            return None
        return data.decode("utf-8", "ignore")
    except (OSError, zipfile.BadZipFile, KeyError):
        return None


def scan_contents(paths, terms, cancel, on_hit, on_progress, workers=8):
    """Calls on_hit(path) for every file containing all `terms` (lowercase)."""
    done = [0]
    lock = threading.Lock()

    def one(p):
        if cancel():
            return
        txt = read_text(p)
        if txt is not None:
            low = txt.lower()
            if all(t in low for t in terms):
                on_hit(p)
        with lock:
            done[0] += 1
            if done[0] % 100 == 0:
                on_progress(done[0])

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, paths))
    on_progress(done[0])


# ------------------------------------------------------------------- duplicates
def _hash(path, limit=None):
    h = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            left = limit
            while True:
                chunk = f.read(1 << 20 if left is None else min(1 << 20, left))
                if not chunk:
                    break
                h.update(chunk)
                if left is not None:
                    left -= len(chunk)
                    if left <= 0:
                        break
    except OSError:
        return None
    return h.digest()


def find_duplicates(root, cancel=lambda: False, progress=lambda msg: None, min_size=1):
    """[(size, [paths oldest-first])] biggest waste first, or None if cancelled."""
    roots = [root] if isinstance(root, str) else list(root)  # one folder or several
    by_size, seen, counted = {}, 0, set()
    skip_dirs = {"$recycle.bin", "system volume information"}
    for top in roots:
        for d, dirs, files in os.walk(top):
            if cancel():
                return None
            dirs[:] = [x for x in dirs if x.lower() not in skip_dirs]
            for f in files:
                p = os.path.join(d, f)
                key = os.path.normcase(p)
                if key in counted:  # overlapping roots must not report a file as its own duplicate
                    continue
                counted.add(key)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if statmod.S_ISREG(st.st_mode) and st.st_size >= min_size:
                    by_size.setdefault(st.st_size, []).append(p)
                seen += 1
            progress(f"Listing files... {seen:,}")
    cands = {s: ps for s, ps in by_size.items() if len(ps) > 1}
    out, n = [], 0
    for size, paths in cands.items():
        if cancel():
            return None
        n += 1
        progress(f"Comparing candidates {n:,}/{len(cands):,}")
        part = {}
        for p in paths:
            h = _hash(p, 65536)
            if h is not None:
                part.setdefault(h, []).append(p)
        for grp in part.values():
            if len(grp) < 2:
                continue
            full = {}
            for p in grp:
                h = _hash(p) if size > 65536 else b"same"
                if h is not None:
                    full.setdefault(h, []).append(p)
            for g in full.values():
                if len(g) > 1:
                    g.sort(key=lambda x: os.path.getmtime(x))
                    out.append((size, g))
    out.sort(key=lambda t: t[0] * (len(t[1]) - 1), reverse=True)
    return out


# --------------------------------------------------------------------- treemap
def squarify(items, x, y, w, h):
    """items: [(value, payload)] -> [(x, y, w, h, payload)] filling the rectangle (squarified treemap)."""
    items = sorted(((v, p) for v, p in items if v > 0), key=lambda t: -t[0])
    total = sum(v for v, _ in items)
    if total <= 0 or w <= 0 or h <= 0:
        return []
    scale = w * h / total
    sizes = [v * scale for v, _ in items]
    out, i = [], 0

    def worst(row, side):
        s = sum(row)
        return max(max(side * side * r / (s * s), s * s / (side * side * r)) for r in row)

    while i < len(sizes):
        side = min(w, h)
        row, j = [sizes[i]], i + 1
        while j < len(sizes) and worst(row + [sizes[j]], side) <= worst(row, side):
            row.append(sizes[j])
            j += 1
        s = sum(row)
        if w >= h:
            cw, cy = s / h, y
            for k, a in enumerate(row):
                rh = a / cw
                out.append((x, cy, cw, rh, items[i + k][1]))
                cy += rh
            x, w = x + cw, w - cw
        else:
            rh, cx = s / w, x
            for k, a in enumerate(row):
                rw = a / rh
                out.append((cx, y, rw, rh, items[i + k][1]))
                cx += rw
            y, h = y + rh, h - rh
        i = j
    return out


# ----------------------------------------------------------------- bulk rename
def file_date(path):
    """datetime a photo was taken (EXIF DateTimeOriginal) or, failing that, when the file was last modified."""
    import datetime as dt
    try:
        if os.path.splitext(path)[1].lower() in (".jpg", ".jpeg", ".tif", ".tiff", ".png", ".webp"):
            from PIL import Image
            with Image.open(path) as im:
                ex = im.getexif()
                raw = (ex.get_ifd(0x8769) or {}).get(0x9003) or ex.get(0x0132)
            if raw:
                return dt.datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return dt.datetime.now()


def plan_rename(names, mode="replace", find="", repl="", regex=False, template="{name}{ext}", start=1, case="keep", paths=None):
    out = []
    for i, n in enumerate(names):
        base, ext = os.path.splitext(n)
        if mode == "replace":
            new = n
            if find:
                try:
                    new = re.sub(find, repl, n) if regex else n.replace(find, repl)
                except re.error:
                    new = n
        else:
            try:
                kw = {}
                if paths and "{" in template and any(k in template for k in ("{date", "{year", "{month", "{day", "{time")):
                    d = file_date(paths[i])
                    kw = dict(date=d.strftime("%Y-%m-%d"), datetime=d.strftime("%Y-%m-%d_%H%M%S"), time=d.strftime("%H%M%S"),
                              year=d.strftime("%Y"), month=d.strftime("%m"), day=d.strftime("%d"))
                new = template.format(n=start + i, name=base, ext=ext, **kw)
            except (KeyError, ValueError, IndexError):
                new = n
        if case != "keep":
            stem, e = os.path.splitext(new)
            stem = {"lower": stem.lower(), "upper": stem.upper(), "title": stem.title()}[case]
            new = stem + e
        out.append(new)
    return out


# ------------------------------------------------------- transfer, undo helpers
class Cancelled(Exception):
    pass


def _unique(folder, name):
    dest = os.path.join(folder, name)
    base, ext = os.path.splitext(name)
    n = 1
    while os.path.exists(dest):
        dest = os.path.join(folder, f"{base} - Copy{'' if n == 1 else f' ({n})'}{ext}")
        n += 1
    return dest


def tree_size(path):
    if not os.path.isdir(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for d, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return total


def transfer(paths, folder, move, progress=None, cancel=lambda: False, resolve=None):
    """Copy/move into `folder`. Returns [(src, dst)] that completed. progress(done, total, name).
    resolve(src, existing) -> 'replace' | 'keep' | 'skip' | 'cancel' is asked when the name is already taken
    (for 'replace' the callback must already have removed the existing item)."""
    total = 0 if move else sum(tree_size(p) for p in paths)
    state, pairs = {"done": 0, "t": 0.0}, []

    def copy_file(src, dst):
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            while True:
                if cancel():
                    raise Cancelled()
                b = fi.read(1 << 20)
                if not b:
                    break
                fo.write(b)
                state["done"] += len(b)
                now = time.time()
                if progress and now - state["t"] > 0.1:
                    state["t"] = now
                    progress(state["done"], total, os.path.basename(src))
        shutil.copystat(src, dst)

    def copy_tree(src, dst):
        os.makedirs(dst)
        for e in os.scandir(src):
            if e.is_dir(follow_symlinks=False):
                copy_tree(e.path, os.path.join(dst, e.name))
            else:
                copy_file(e.path, os.path.join(dst, e.name))

    nf = os.path.normcase(folder)
    for p in paths:
        zs = zip_split(p)
        if zs and zs[1]:  # something inside an archive: unpack it (a "move" out of an archive is a copy)
            pairs.append((p, zip_extract(zs[0], zs[1], folder)))
            continue
        if not os.path.exists(p):
            continue
        np_ = os.path.normcase(p)
        if move and os.path.normcase(os.path.dirname(p)) == nf:
            continue
        if os.path.isdir(p) and (nf == np_ or nf.startswith(np_ + "\\")):
            raise OSError(f"Can't put a folder inside itself: {os.path.basename(p)}")
        target = os.path.join(folder, os.path.basename(p))
        dst = None
        if resolve and os.path.exists(target) and os.path.normcase(target) != np_:
            act = resolve(p, target)
            if act == "cancel":
                raise Cancelled()
            if act == "skip":
                continue
            if act == "replace" and not os.path.exists(target):
                dst = target
        if dst is None:
            dst = _unique(folder, os.path.basename(p))
        try:
            if move:
                shutil.move(p, dst)
            elif os.path.isdir(p):
                copy_tree(p, dst)
            else:
                copy_file(p, dst)
        except Cancelled:
            shutil.rmtree(dst, ignore_errors=True) if os.path.isdir(dst) else (os.path.exists(dst) and os.remove(dst))
            raise
        pairs.append((p, dst))
    return pairs


_RESTORE_PS = r"""
# Windows PowerShell 5.1 returns a JSON list as ONE object when piped, so unroll it explicitly
$paths = New-Object System.Collections.ArrayList
foreach ($x in (ConvertFrom-Json -InputObject $env:FF_PATHS)) { [void]$paths.Add([string]$x) }
$sh = New-Object -ComObject Shell.Application
$bin = $sh.Namespace(0xA)
foreach ($want in $paths) {
  $dir = Split-Path $want -Parent; $leaf = Split-Path $want -Leaf; $stem = [IO.Path]::GetFileNameWithoutExtension($leaf)
  $best = $null
  foreach ($it in $bin.Items()) {
    $from = $it.ExtendedProperty('System.Recycle.DeletedFrom')
    if ($from -ne $dir) { continue }
    if ($it.Name -ne $leaf -and $it.Name -ne $stem) { continue }
    $when = $it.ExtendedProperty('System.Recycle.DateDeleted')
    if ($best -eq $null -or $when -gt $best.when) { $best = @{ item = $it; when = $when } }
  }
  if ($best) {
    $best.item.InvokeVerb('undelete')
    # the restore is asynchronous: wait for it to finish (folders take a moment) or the process exits mid-way
    $deadline = (Get-Date).AddSeconds(20)
    while (-not (Test-Path -LiteralPath $want) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 150 }
  }
}
"""


_MEDIA_PS = r"""
$sh = New-Object -ComObject Shell.Application
$it = $sh.Namespace([IO.Path]::GetDirectoryName($env:FF_FILE)).ParseName([IO.Path]::GetFileName($env:FF_FILE))
$o = @{}
foreach ($p in 'System.Media.Duration','System.Video.FrameWidth','System.Video.FrameHeight','System.Video.FrameRate','System.Video.EncodingBitrate','System.Audio.EncodingBitrate',
          'System.Music.Artist','System.Music.AlbumTitle','System.Title','System.Media.Year','System.Music.Genre','System.Audio.ChannelCount','System.Audio.SampleRate') {
  $v = $it.ExtendedProperty($p); if ($v -ne $null -and "$v" -ne '') { $o[$p] = "$v" }
}
ConvertTo-Json -InputObject $o -Compress
"""


def media_info(path):
    """[(label, value)] for audio / video files from Windows' own property system (duration, size in pixels, bit rate, artist ...)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _MEDIA_PS], env=dict(os.environ, FF_FILE=path),
                           capture_output=True, text=True, timeout=25, creationflags=0x08000000)
        d = json.loads(r.stdout.strip() or "{}")
    except Exception:  # noqa
        return []
    out = []
    dur = d.get("System.Media.Duration")
    if dur and dur.isdigit():
        secs = int(dur) / 1e7
        h, rem = divmod(int(secs), 3600)
        out.append(("Duration", f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60}:{rem % 60:02d}"))
    w, h_ = d.get("System.Video.FrameWidth"), d.get("System.Video.FrameHeight")
    if w and h_:
        out.append(("Frame size", f"{w} x {h_}"))
    fr = d.get("System.Video.FrameRate")
    if fr and fr.isdigit():
        out.append(("Frame rate", f"{int(fr) / 1000:g} fps"))
    for key, label in (("System.Video.EncodingBitrate", "Video bit rate"), ("System.Audio.EncodingBitrate", "Audio bit rate")):
        v = d.get(key)
        if v and v.isdigit():
            out.append((label, f"{int(v) // 1000} kbps"))
    for key, label in (("System.Title", "Title"), ("System.Music.Artist", "Artist"), ("System.Music.AlbumTitle", "Album"), ("System.Media.Year", "Year"),
                       ("System.Music.Genre", "Genre"), ("System.Audio.SampleRate", "Sample rate")):
        v = d.get(key)
        if v:
            out.append((label, v + (" Hz" if key.endswith("SampleRate") else "")))
    return out


def restore_from_recycle(paths):
    """Undo a delete: ask the Recycle Bin to put these original paths back. Returns the paths that exist again."""
    env = dict(os.environ, FF_PATHS=json.dumps(list(paths)))
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _RESTORE_PS], env=env,
                   capture_output=True, timeout=120, creationflags=0x08000000)  # CREATE_NO_WINDOW
    return [p for p in paths if os.path.exists(p)]


_BIN_PS = r"""
$sh = New-Object -ComObject Shell.Application
$bin = $sh.Namespace(0xA)
$out = New-Object System.Collections.ArrayList
foreach ($it in $bin.Items()) {
  $ext = [IO.Path]::GetExtension([string]$it.Path)
  $leaf = [string]$it.Name
  if ($ext -and -not $leaf.ToLower().EndsWith($ext.ToLower())) { $leaf += $ext }
  $when = $it.ExtendedProperty('System.Recycle.DateDeleted')
  [void]$out.Add(@{ name = $leaf; from = [string]$it.ExtendedProperty('System.Recycle.DeletedFrom'); size = [int64]$it.Size;
                    when = $(if ($when) { ([datetime]$when).ToString('s') } else { '' }); dir = [bool]$it.IsFolder })
}
ConvertTo-Json -InputObject @($out) -Compress -Depth 3
"""


def recycle_list():
    """Read-only list of what is in the Recycle Bin: [{name, from, size, when, dir}] (newest first)."""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _BIN_PS], capture_output=True, text=True,
                       timeout=120, creationflags=0x08000000)
    data = json.loads(r.stdout.strip() or "[]")
    if isinstance(data, dict):
        data = [data]
    return sorted(data, key=lambda d: d.get("when", ""), reverse=True)


def drives():
    """[(root, kind, free_bytes, total_bytes)] for fixed (3), removable (2) and network (4) drives."""
    out = []
    if os.name != "nt":
        return out
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            kind = ctypes.windll.kernel32.GetDriveTypeW(root)
            if kind in (2, 3, 4):
                try:
                    u = shutil.disk_usage(root)
                    out.append((root, kind, u.free, u.total))
                except OSError:
                    out.append((root, kind, 0, 0))
    return out


# ------------------------------------------------------- archives (zip + tar) as folders
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")


def archive_suffix(name):
    low = name.lower()
    return next((s for s in ARCHIVE_SUFFIXES if low.endswith(s)), None)


def is_archive_name(name):
    return archive_suffix(name) is not None


def archive_stem(name):
    suf = archive_suffix(name)
    return name[:-len(suf)] if suf else os.path.splitext(name)[0]


def zip_split(path):
    """('C:\\x\\a.zip', 'inner/dir') if `path` is an archive file or lies inside one, else None."""
    parts = os.path.normpath(path).split("\\")
    if len(parts) < 2:
        return None
    acc = parts[0] + "\\"
    for i, part in enumerate(parts[1:], 1):
        acc = os.path.join(acc, part)
        if is_archive_name(part) and os.path.isfile(acc):
            return acc, "/".join(parts[i + 1:])
    return None


def zip_is_virtual(path):
    """True for a path INSIDE an archive (the archive file itself is a normal file)."""
    z = zip_split(path)
    return bool(z and z[1])


class _Arc:
    """Read-only view of a .zip or tar archive: entries() and open(name)."""

    def __init__(self, path):
        self.path = path
        self.is_zip = archive_suffix(path) == ".zip"
        self.f = zipfile.ZipFile(path) if self.is_zip else tarfile.open(path)
        self._members = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.f.close()
        return False

    def entries(self):
        """[(name, size, mtime, isdir)] with '/' separators; directory names end in '/'."""
        out = []
        if self.is_zip:
            for zi in self.f.infolist():
                try:
                    mt = time.mktime(zi.date_time + (0, 0, -1))
                except (OverflowError, ValueError):
                    mt = 0.0
                out.append((zi.filename, zi.file_size, mt, zi.is_dir()))
        else:
            for ti in self.f.getmembers():
                if not (ti.isfile() or ti.isdir()):
                    continue
                name = ti.name
                while name.startswith("./"):
                    name = name[2:]
                name = name.strip("/")
                if not name:
                    continue
                if ti.isdir():
                    name += "/"
                self._members[name] = ti
                out.append((name, ti.size, float(ti.mtime), ti.isdir()))
        return out

    def open(self, name):
        if self.is_zip:
            return self.f.open(name)
        if not self._members:
            self.entries()
        return self.f.extractfile(self._members[name])


_ENTRY_CACHE = {}


def _entries_cached(path):
    """Listing of an archive, cached per (file, mtime, size) because tar.gz has to be read sequentially."""
    try:
        st = os.stat(path)
    except OSError:
        return []
    key = (path, st.st_mtime, st.st_size)
    if key not in _ENTRY_CACHE:
        with _Arc(path) as a:
            _ENTRY_CACHE[key] = a.entries()
        while len(_ENTRY_CACHE) > 4:
            _ENTRY_CACHE.pop(next(iter(_ENTRY_CACHE)))
    return _ENTRY_CACHE[key]


def zip_rows(zip_path, inner=""):
    """list_dir-style rows (name, path, size, mtime, isdir) for one level inside an archive."""
    inner = inner.strip("/")
    prefix = inner + "/" if inner else ""
    dirs, files = {}, []
    base = zip_path + ("\\" + inner.replace("/", "\\") if inner else "")
    for name, size, mt, isdir in _entries_cached(zip_path):
        if not name.startswith(prefix) or name == prefix:
            continue
        head, sep, tail = name[len(prefix):].partition("/")
        if not head or head in ("..", "."):  # never show path-traversal names
            continue
        if sep:
            d = dirs.setdefault(head, [0, 0.0])
            if tail:
                d[0] += size
                d[1] = max(d[1], mt)
        else:
            files.append((head, base + "\\" + head, size, mt, 0))
    rows = [(n, base + "\\" + n, v[0], v[1], 1) for n, v in dirs.items()] + files
    rows.sort(key=lambda r: (not r[4], natural_key(r[0])))
    return rows


def zip_extract(zip_path, inner, folder):
    """Extract a file/folder (or the whole archive when inner == "") into `folder`; returns the new path."""
    inner = inner.strip("/")
    with _Arc(zip_path) as a:
        ents = a.entries()
        names = {e[0]: e for e in ents}
        label = inner.rsplit("/", 1)[-1] if inner else archive_stem(os.path.basename(zip_path))
        dest = _unique(folder, label)

        def safe(rel):
            parts = [p for p in rel.split("/") if p]
            return None if any(p in ("..", ".") or ":" in p for p in parts) else parts

        if inner and inner in names and not names[inner][3]:  # a single file
            with a.open(inner) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            return dest
        prefix = inner + "/" if inner else ""
        os.makedirs(dest)
        for n, size, mt, isdir in ents:
            if not n.startswith(prefix) or isdir:
                continue
            parts = safe(n[len(prefix):])
            if not parts:
                continue
            target = os.path.join(dest, *parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with a.open(n) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
        return dest


# ---------------------------------------------------------------- compare folders
def compare_folders(left, right, cancel=lambda: False, progress=lambda m: None):
    """Compare two folder trees by relative path. Rows: (rel, kind, lsize, lmtime, rsize, rmtime, lpath, rpath) with
    kind in only_left / only_right / newer_left / newer_right / differ (same time, other size) / same."""

    def walk(top):
        out, n = {}, 0
        for d, _dirs, files in os.walk(top):
            if cancel():
                return None
            for f in files:
                p = os.path.join(d, f)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                rel = os.path.relpath(p, top)
                out[rel.lower()] = (rel, st.st_size, st.st_mtime, p)
            n += len(files)
            progress(f"Scanning {os.path.basename(top.rstrip(chr(92))) or top}\u2026 {n:,} files")
        return out

    lo = walk(left)
    ro = walk(right) if lo is not None else None
    if lo is None or ro is None:
        return None
    rows = []
    for key in sorted(set(lo) | set(ro)):
        a, b = lo.get(key), ro.get(key)
        rel = (a or b)[0]
        if a and not b:
            kind = "only_left"
        elif b and not a:
            kind = "only_right"
        elif a[1] == b[1] and abs(a[2] - b[2]) <= 2:
            kind = "same"  # 2 s slack: FAT/exFAT drives store times in 2 s steps
        elif a[2] > b[2] + 2:
            kind = "newer_left"
        elif b[2] > a[2] + 2:
            kind = "newer_right"
        else:
            kind = "differ"
        rows.append((rel, kind, a[1] if a else None, a[2] if a else None, b[1] if b else None, b[2] if b else None,
                     a[3] if a else None, b[3] if b else None))
    return rows


SYNC_OLD = ".sync-old"


def sync_plan(a, b, cancel=lambda: False, progress=lambda m: None):
    """Two-way sync plan between folders a and b (nothing is deleted). Returns None if cancelled or
    {'copy': [(src, dst, rel, size, overwrites)], 'conflicts': [rel], 'same': n}. Files with the same date but a different
    size are conflicts and are left alone."""
    rows = compare_folders(a, b, cancel, progress)
    if rows is None:
        return None
    plan = {"copy": [], "conflicts": [], "same": 0}
    for rel, kind, ls, lm, rs, rm, lp, rp in rows:
        if rel.split(os.sep)[0] == SYNC_OLD:
            continue
        if kind == "only_left":
            plan["copy"].append((lp, os.path.join(b, rel), rel, ls, False))
        elif kind == "only_right":
            plan["copy"].append((rp, os.path.join(a, rel), rel, rs, False))
        elif kind == "newer_left":
            plan["copy"].append((lp, rp, rel, ls, True))
        elif kind == "newer_right":
            plan["copy"].append((rp, lp, rel, rs, True))
        elif kind == "differ":
            plan["conflicts"].append(rel)
        else:
            plan["same"] += 1
    return plan


def run_sync(plan, a, b, cancel=lambda: False, progress=lambda i, n, name: None):
    """Execute a sync plan. A file that gets replaced by a newer one is first kept in a ".sync-old" folder inside that side.
    Returns {'copied', 'bytes', 'errors': [(rel, msg)], 'kept_old'}."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    res = {"copied": 0, "bytes": 0, "errors": [], "kept_old": 0}
    todo = plan["copy"]
    for i, (src, dst, rel, size, overwrites) in enumerate(todo):
        if cancel():
            break
        progress(i, len(todo), rel)
        try:
            if overwrites and os.path.exists(dst):
                top = a if os.path.normcase(dst).startswith(os.path.normcase(a.rstrip("\\")) + "\\") else b
                keep = os.path.join(top, SYNC_OLD, stamp, rel)
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                shutil.copy2(dst, keep)
                res["kept_old"] += 1
            copy_file_to(src, dst)
            res["copied"] += 1
            res["bytes"] += size or 0
        except OSError as e:
            res["errors"].append((rel, str(e)))
    progress(len(todo), len(todo), "")
    return res


def sync_old_paths(a, b, days=30):
    """Stamp folders inside each side's .sync-old that are older than `days` (candidates for the Recycle Bin)."""
    out, cutoff = [], time.time() - days * 86400
    for top in (a, b):
        base = os.path.join(top, SYNC_OLD)
        if os.path.isdir(base):
            for name in os.listdir(base):
                p = os.path.join(base, name)
                try:
                    if os.path.isdir(p) and os.path.getmtime(p) < cutoff:
                        out.append(p)
                except OSError:
                    pass
    return out


def sync_old_size(a, b):
    """(file count, bytes) of everything kept in the two .sync-old folders."""
    n = size = 0
    for top in (a, b):
        for dp, _d, fs in os.walk(os.path.join(top, SYNC_OLD)):
            for f in fs:
                try:
                    size += os.path.getsize(os.path.join(dp, f))
                    n += 1
                except OSError:
                    pass
    return n, size


def copy_file_to(src, dst):
    """Copy one file to an exact destination path (creating folders); keeps timestamps."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


# ------------------------------------------------------------- largest files
def largest_files(top, limit=1000, cancel=lambda: False, progress=lambda m: None):
    """[(size, path, mtime)] biggest first, or None if cancelled. Keeps only `limit` in memory (min-heap)."""
    import heapq
    heap, seen = [], 0
    skip = {"$recycle.bin", "system volume information"}
    for d, dirs, files in os.walk(top):
        if cancel():
            return None
        dirs[:] = [x for x in dirs if x.lower() not in skip]
        for f in files:
            p = os.path.join(d, f)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not statmod.S_ISREG(st.st_mode):
                continue
            item = (st.st_size, p, st.st_mtime)
            if len(heap) < limit:
                heapq.heappush(heap, item)
            elif item[0] > heap[0][0]:
                heapq.heapreplace(heap, item)
        seen += len(files)
        progress(f"Scanning\u2026 {seen:,} files   \u2022   {d[:70]}")
    return sorted(heap, reverse=True)


# ------------------------------------------------------------ organize a folder
ORGANIZE_CATEGORIES = {
    "Images": "png jpg jpeg gif bmp webp svg heic heif tif tiff ico psd raw cr2 nef",
    "Videos": "mp4 mkv avi mov wmv webm flv m4v 3gp mpg mpeg",
    "Audio": "mp3 wav flac ogg m4a aac wma opus",
    "Documents": "pdf doc docx txt rtf odt md ppt pptx xls xlsx csv odp ods epub",
    "Archives": "zip rar 7z tar gz bz2 xz iso tgz",
    "Code": "py js ts html css json c cpp h cs java rs go sh bat ps1 sql xml yml yaml toml ipynb",
    "Installers": "exe msi apk dmg msix",
}
_EXT_TO_CAT = {e: c for c, exts in ORGANIZE_CATEGORIES.items() for e in exts.split()}


def organize_category(name):
    return _EXT_TO_CAT.get(os.path.splitext(name)[1][1:].lower(), "Other")


def plan_organize(folder, mode="type"):
    """[(name, path, category, size)] for the loose files directly inside `folder` (never sub-folders)."""
    items = []
    with os.scandir(folder) as it:
        for e in it:
            try:
                if not e.is_file(follow_symlinks=False):
                    continue
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if getattr(st, "st_file_attributes", 0) & 0x6:  # hidden / system
                continue
            cat = organize_category(e.name) if mode == "type" else time.strftime("%Y-%m", time.localtime(st.st_mtime))
            items.append((e.name, e.path, cat, st.st_size))
    items.sort(key=lambda r: (r[2].lower(), r[0].lower()))
    return items


def apply_organize(folder, items):
    """Move each item into <folder>/<category>. Returns ([(src, dst)], [folders it created])."""
    pairs, created = [], []
    for name, path, cat, size in items:
        dest_dir = os.path.join(folder, cat)
        try:
            if not os.path.isdir(dest_dir):
                os.makedirs(dest_dir)
                created.append(dest_dir)
            dst = _unique(dest_dir, name)
            shutil.move(path, dst)
            pairs.append((path, dst))
        except OSError:
            continue
    return pairs, created


# ------------------------------------------------------------------ natural sort
def natural_key(s):
    """Sort key so 'file2' < 'file10' (digits compare as numbers, like Explorer)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


# ----------------------------------------------------------------------- checksums
def file_hashes(path, cancel=lambda: False, progress=lambda n: None):
    """{'MD5': hex, 'SHA-1': hex, 'SHA-256': hex} read in one pass, or None if cancelled."""
    hs = {"MD5": hashlib.md5(), "SHA-1": hashlib.sha1(), "SHA-256": hashlib.sha256()}
    done = 0
    with open(path, "rb") as f:
        while True:
            if cancel():
                return None
            b = f.read(1 << 20)
            if not b:
                break
            for h in hs.values():
                h.update(b)
            done += len(b)
            progress(done)
    return {k: h.hexdigest() for k, h in hs.items()}


# ------------------------------------------------------------------------ quick-look helpers
def office_text(path, limit=6000):
    """Plain text from .docx / .pptx / .xlsx / .odt (zip of XML) without any extra library, or None."""
    import re as _re
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "word/document.xml" in names:
                parts = ["word/document.xml"]
            elif any(n.startswith("ppt/slides/slide") for n in names):
                parts = sorted((n for n in names if _re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(_re.findall(r"\d+", n)[0]))
            elif "xl/sharedStrings.xml" in names:
                parts = ["xl/sharedStrings.xml"]
            elif "content.xml" in names:
                parts = ["content.xml"]
            else:
                return None
            out = []
            for p in parts:
                xml = z.read(p).decode("utf-8", "replace")
                xml = _re.sub(r"</(w:p|a:p|text:p|si|row)>", "\n", xml)
                out.append(_re.sub(r"<[^>]+>", "", xml))
                if sum(len(o) for o in out) > limit:
                    break
            import html
            txt = html.unescape("".join(out))
            return _re.sub(r"\n\s*\n+", "\n\n", txt).strip()[:limit]
    except (OSError, zipfile.BadZipFile, KeyError):
        return None


def hex_dump(path, n=512):
    """Classic offset / hex / ASCII dump of the first n bytes (for files with no better preview)."""
    with open(path, "rb") as f:
        data = f.read(n)
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        lines.append(f"{i:08x}  {' '.join(f'{b:02x}' for b in chunk):<47}  {''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)}")
    return "\n".join(lines)


# ------------------------------------------------------------------------ photo metadata
def _dms(v, ref):
    try:
        d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
        return -d if ref in ("S", "W") else d
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return None


def exif_info(path):
    """{'rows': [(label, value)], 'gps': (lat, lon) or None, 'size': (w, h)} for an image, or None if unreadable."""
    from PIL import Image, ExifTags
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            size = im.size
            rows = [("Size", f"{size[0]} x {size[1]} px"), ("Format", im.format or "?")]
            tags = dict(ex)
            sub = ex.get_ifd(0x8769) if hasattr(ex, "get_ifd") else {}
            gps = ex.get_ifd(0x8825) if hasattr(ex, "get_ifd") else {}
    except Exception:
        return None
    names = ExifTags.TAGS
    want = ("Make", "Model", "Software", "DateTime", "Orientation")
    for k, v in tags.items():
        if names.get(k) in want:
            rows.append((names[k], str(v).strip("\x00 ")))
    for k, v in sub.items():
        n = names.get(k)
        if n in ("DateTimeOriginal", "ExposureTime", "FNumber", "ISOSpeedRatings", "FocalLength", "LensModel", "Flash"):
            rows.append((n, str(v)))
    ll = None
    if gps.get(2) and gps.get(4):
        la, lo = _dms(gps[2], gps.get(1)), _dms(gps[4], gps.get(3))
        if la is not None and lo is not None:
            ll = (la, lo)
            rows.append(("GPS location", f"{la:.5f}, {lo:.5f}  (this photo reveals where it was taken)"))
    return {"rows": rows, "gps": ll, "size": size}


def strip_metadata(paths, outdir, cancel=lambda: False):
    """Write copies of images WITHOUT EXIF/GPS into outdir (originals untouched; never overwrites). Returns (outputs, fails)."""
    from PIL import Image
    os.makedirs(outdir, exist_ok=True)
    outs, fails = [], []
    for src in paths:
        if cancel():
            break
        try:
            base, ext = os.path.splitext(os.path.basename(src))
            dst, n = os.path.join(outdir, base + ext), 1
            while os.path.exists(dst):
                n += 1
                dst = os.path.join(outdir, f"{base} ({n}){ext}")
            with Image.open(src) as im:
                fmt = im.format
                clean = Image.frombytes(im.mode, im.size, im.tobytes())  # a fresh image: no EXIF/GPS/ICC carried over
                if im.mode == "P" and im.getpalette():
                    clean.putpalette(im.getpalette())
                kw = {"quality": 95} if fmt == "JPEG" else {}
                clean.save(dst, fmt, **kw)
            outs.append(dst)
        except Exception as e:
            fails.append((os.path.basename(src), str(e)))
    return outs, fails


# ------------------------------------------------------------------------ integrity manifests
def _manifest_path(folder, store):
    key = hashlib.sha1(os.path.normcase(os.path.abspath(folder)).encode("utf-8", "replace")).hexdigest()[:16]
    return os.path.join(store, key + ".json")


def _walk_hash(folder, cancel, progress):
    out = {}
    for dp, dns, fns in os.walk(folder):
        if cancel():
            return None
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                st = os.stat(p)
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for b in iter(lambda: f.read(1 << 20), b""):
                        if cancel():
                            return None
                        h.update(b)
                out[os.path.relpath(p, folder)] = {"size": st.st_size, "mtime": int(st.st_mtime), "sha256": h.hexdigest()}
            except OSError:
                continue
            progress(len(out), fn)
    return out


def manifest_create(folder, store, cancel=lambda: False, progress=lambda n, name: None):
    """Fingerprint every file under `folder` (SHA-256) and remember it in `store`. Returns the file count or None."""
    import json
    files = _walk_hash(folder, cancel, progress)
    if files is None:
        return None
    os.makedirs(store, exist_ok=True)
    with open(_manifest_path(folder, store), "w", encoding="utf-8") as f:
        json.dump({"folder": os.path.abspath(folder), "created": time.time(), "files": files}, f)
    return len(files)


def manifest_load(folder, store):
    import json
    try:
        with open(_manifest_path(folder, store), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def manifest_verify(folder, store, cancel=lambda: False, progress=lambda n, name: None):
    """Compare the folder with its saved fingerprints. Returns None (cancelled / no manifest) or a dict of lists:
    corrupt (content changed but size+date identical: possible disk corruption), modified (edited normally),
    missing, new, ok (count)."""
    m = manifest_load(folder, store)
    if m is None:
        return None
    now = _walk_hash(folder, cancel, progress)
    if now is None:
        return None
    old = m["files"]
    r = {"corrupt": [], "modified": [], "missing": sorted(set(old) - set(now)), "new": sorted(set(now) - set(old)), "ok": 0,
         "created": m.get("created")}
    for rel, n in now.items():
        o = old.get(rel)
        if not o:
            continue
        if o["sha256"] == n["sha256"]:
            r["ok"] += 1
        elif o["size"] == n["size"] and o["mtime"] == n["mtime"]:
            r["corrupt"].append(rel)
        else:
            r["modified"].append(rel)
    r["corrupt"].sort(); r["modified"].sort()
    return r


# ------------------------------------------------------------------------------------------------- FTP client
class FtpConn:
    """Small FTP/FTPS wrapper (stdlib ftplib): browse, download and upload. Passwords are never stored."""

    def __init__(self, host, port=21, user="anonymous", password="", tls=False, timeout=20, factory=None):
        import ftplib
        cls = factory or (ftplib.FTP_TLS if tls else ftplib.FTP)
        self.f = cls()
        self.f.connect(host, int(port or 21), timeout=timeout)
        self.f.login(user or "anonymous", password or "anonymous@")
        if tls and hasattr(self.f, "prot_p"):
            self.f.prot_p()
        self.host = host

    def pwd(self):
        return self.f.pwd()

    def listdir(self):
        """[(name, is_dir, size, mtime_str)] folders first."""
        rows = []
        try:
            for name, facts in self.f.mlsd():
                if name in (".", "..") or facts.get("type") in ("cdir", "pdir"):
                    continue
                rows.append((name, facts.get("type") == "dir", int(facts.get("size", 0) or 0), facts.get("modify", "")[:14]))
        except Exception:
            lines = []
            self.f.retrlines("LIST", lines.append)
            for ln in lines:
                parts = ln.split(None, 8)
                if len(parts) >= 9 and parts[8] not in (".", ".."):
                    rows.append((parts[8], ln.startswith("d"), int(parts[4]) if parts[4].isdigit() else 0, " ".join(parts[5:8])))
        rows.sort(key=lambda r: (not r[1], r[0].lower()))
        return rows

    def cd(self, name):
        self.f.cwd(name)

    def up(self):
        self.f.cwd("..")

    def download(self, name, dest_dir, progress=lambda n: None, cancel=lambda: False):
        """Download one file into dest_dir (never overwrites: adds ' (2)'). Returns the local path."""
        dst = os.path.join(dest_dir, name)
        base, ext = os.path.splitext(dst)
        n = 1
        while os.path.exists(dst):
            n += 1
            dst = f"{base} ({n}){ext}"
        done = [0]

        def w(b):
            if cancel():
                raise Cancelled()
            fh.write(b)
            done[0] += len(b)
            progress(done[0])
        try:
            with open(dst + ".part", "wb") as fh:
                self.f.retrbinary("RETR " + name, w)
            os.replace(dst + ".part", dst)
        except BaseException:
            try:
                os.remove(dst + ".part")
            except OSError:
                pass
            raise
        return dst

    def upload(self, path, progress=lambda n: None):
        done = [0]

        def cb(b):
            done[0] += len(b)
            progress(done[0])
        with open(path, "rb") as fh:
            self.f.storbinary("STOR " + os.path.basename(path), fh, callback=cb)

    def close(self):
        try:
            self.f.quit()
        except Exception:
            try:
                self.f.close()
            except Exception:
                pass


class SftpConn:
    """SFTP over SSH (paramiko) with the same small interface as FtpConn. The server's key fingerprint must be confirmed
    by the user the first time (`confirm(host, fingerprint) -> bool`) and is then remembered in `known_hosts`."""

    def __init__(self, host, port=22, user="", password="", confirm=lambda h, fp: False, known_hosts=None, timeout=20, client=None):
        import paramiko

        class Policy(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self_, cli, hostname, key):
                fp = key.get_fingerprint().hex(":")
                if not confirm(hostname, fp):
                    raise paramiko.SSHException("Server key was not accepted")
                cli.get_host_keys().add(hostname, key.get_name(), key)
        self.ssh = client or paramiko.SSHClient()
        if known_hosts:
            try:
                self.ssh.load_host_keys(known_hosts)
            except OSError:
                pass
        self.ssh.set_missing_host_key_policy(Policy())
        self.ssh.connect(host, int(port or 22), username=user or None, password=password or None, timeout=timeout,
                         look_for_keys=not password, allow_agent=not password)
        if known_hosts:
            try:
                os.makedirs(os.path.dirname(known_hosts), exist_ok=True)
                self.ssh.save_host_keys(known_hosts)
            except OSError:
                pass
        self.f = self.ssh.open_sftp()
        self.f.chdir(".")
        self.host = host

    def pwd(self):
        return self.f.getcwd() or "/"

    def listdir(self):
        rows = []
        for a_ in self.f.listdir_attr():
            rows.append((a_.filename, statmod.S_ISDIR(a_.st_mode or 0), a_.st_size or 0, time.strftime("%Y%m%d%H%M%S", time.localtime(a_.st_mtime or 0))))
        rows.sort(key=lambda r: (not r[1], r[0].lower()))
        return rows

    def cd(self, name):
        self.f.chdir(name)

    def up(self):
        self.f.chdir("..")

    def download(self, name, dest_dir, progress=lambda n: None, cancel=lambda: False):
        dst = os.path.join(dest_dir, name)
        base, ext = os.path.splitext(dst)
        n = 1
        while os.path.exists(dst):
            n += 1
            dst = f"{base} ({n}){ext}"

        def cb(done, total):
            if cancel():
                raise Cancelled()
            progress(done)
        try:
            self.f.get(name, dst + ".part", callback=cb)
            os.replace(dst + ".part", dst)
        except BaseException:
            try:
                os.remove(dst + ".part")
            except OSError:
                pass
            raise
        return dst

    def upload(self, path, progress=lambda n: None):
        self.f.put(path, os.path.basename(path), callback=lambda done, total: progress(done))

    def close(self):
        try:
            self.f.close()
            self.ssh.close()
        except Exception:
            pass


def sftp_available():
    try:
        import paramiko  # noqa: F401
        return True
    except ImportError:
        return False


# --------------------------------------------------------------------------------------- similar photos
def dhash(path, size=8):
    """64-bit 'difference hash' of an image: equal for the same picture even when resized, re-saved or slightly edited."""
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        w, h = im.size
        g = im.convert("L").resize((size + 1, size), Image.LANCZOS)
        px = list(g.tobytes()) if hasattr(g, "tobytes") else list(g.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (1 if px[row * (size + 1) + col] > px[row * (size + 1) + col + 1] else 0)
    return bits, w * h


def find_similar_images(root, max_distance=5, cancel=lambda: False, progress=lambda n: None, exts=(".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")):
    """Groups of (almost) identical photos under `root`: [[(path, pixels, size_bytes), ...], ...] best (most pixels) first; None if cancelled.
    Exact duplicates are found by find_duplicates(); this also catches resized/re-compressed copies."""
    items = []
    for dp, dns, fns in os.walk(root):
        for fn in fns:
            if cancel():
                return None
            if fn.lower().endswith(exts):
                p = os.path.join(dp, fn)
                try:
                    h, px = dhash(p)
                    items.append((h, p, px, os.path.getsize(p)))
                except Exception:
                    pass
                if len(items) % 25 == 0:
                    progress(len(items))
    # 8 bands of 8 bits: two hashes within distance <= 7 must share at least one identical band (pigeonhole) -> only compare those
    buckets = {}
    for i, (h, *_r) in enumerate(items):
        for b in range(8):
            buckets.setdefault((b, (h >> (8 * b)) & 0xFF), []).append(i)
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for idxs in buckets.values():
        if len(idxs) > 400 or len(idxs) < 2:  # a band shared by hundreds of images is noise (e.g. plain backgrounds)
            continue
        for k, i in enumerate(idxs):
            for j in idxs[k + 1:]:
                if bin(items[i][0] ^ items[j][0]).count("1") <= max_distance:
                    parent[find(i)] = find(j)
    groups = {}
    for i, (h, p, px, sz) in enumerate(items):
        groups.setdefault(find(i), []).append((p, px, sz))
    out = [sorted(g, key=lambda t: (-t[1], -t[2])) for g in groups.values() if len(g) > 1]
    out.sort(key=lambda g: -sum(t[2] for t in g))
    return out


# ------------------------------------------------------------------------------------------------- WebDAV client
class WebDavConn:
    """Small WebDAV client (NAS, Nextcloud, ownCloud, Synology, ...) with the same interface as FtpConn: pass the full URL as host."""

    def __init__(self, url, user="", password="", timeout=30, opener=None):
        import urllib.request
        self.base = url.rstrip("/")
        self.timeout = timeout
        self.path = "/"
        import base64
        self.auth = ("Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode()) if user else None  # sent up front (use https!)
        self.opener = opener or urllib.request.build_opener()
        self.host = url
        self.listdir()  # fail early on a wrong address or password

    def _url(self, name=""):
        import urllib.parse
        p = self.path if not name else (self.path.rstrip("/") + "/" + name)
        return self.base + urllib.parse.quote(p, safe="/")

    def _req(self, method, url, data=None, headers=None):
        import urllib.request
        headers = dict(headers or {})
        if self.auth:
            headers["Authorization"] = self.auth
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        return self.opener.open(req, timeout=self.timeout)

    def pwd(self):
        return self.path

    def listdir(self):
        import urllib.parse
        import xml.etree.ElementTree as ET
        with self._req("PROPFIND", self._url() + "/", b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getcontentlength/><d:getlastmodified/></d:prop></d:propfind>',
                       {"Depth": "1", "Content-Type": "application/xml"}) as r:
            root = ET.fromstring(r.read())
        rows, me = [], urllib.parse.unquote(urllib.parse.urlparse(self._url()).path).rstrip("/")
        for resp in root.iter("{DAV:}response"):
            href = urllib.parse.unquote(urllib.parse.urlparse(resp.findtext("{DAV:}href") or "").path).rstrip("/")
            if href == me or not href:
                continue
            isdir = resp.find(".//{DAV:}resourcetype/{DAV:}collection") is not None
            size = int(resp.findtext(".//{DAV:}getcontentlength") or 0)
            rows.append((href.rsplit("/", 1)[-1], isdir, size, resp.findtext(".//{DAV:}getlastmodified") or ""))
        rows.sort(key=lambda r: (not r[1], r[0].lower()))
        return rows

    def cd(self, name):
        self.path = self.path.rstrip("/") + "/" + name

    def up(self):
        self.path = self.path.rstrip("/").rsplit("/", 1)[0] or "/"

    def download(self, name, dest_dir, progress=lambda n: None, cancel=lambda: False):
        dst = os.path.join(dest_dir, name)
        base, ext = os.path.splitext(dst)
        n = 1
        while os.path.exists(dst):
            n += 1
            dst = f"{base} ({n}){ext}"
        done = 0
        try:
            with self._req("GET", self._url(name)) as r, open(dst + ".part", "wb") as f:
                while True:
                    if cancel():
                        raise Cancelled()
                    b = r.read(1 << 16)
                    if not b:
                        break
                    f.write(b)
                    done += len(b)
                    progress(done)
            os.replace(dst + ".part", dst)
        except BaseException:
            try:
                os.remove(dst + ".part")
            except OSError:
                pass
            raise
        return dst

    def upload(self, path, progress=lambda n: None):
        with open(path, "rb") as f:
            data = f.read()
        self._req("PUT", self._url(os.path.basename(path)), data, {"Content-Type": "application/octet-stream"}).close()
        progress(len(data))

    def close(self):
        pass


# --------------------------------------------------------------- image convert/resize
IMAGE_FORMATS = {"jpg": ("JPEG", "jpg"), "jpeg": ("JPEG", "jpg"), "png": ("PNG", "png"), "webp": ("WEBP", "webp"),
                 "bmp": ("BMP", "bmp"), "gif": ("GIF", "gif"), "tif": ("TIFF", "tif"), "tiff": ("TIFF", "tif")}


def convert_images(paths, outdir, fmt="keep", max_side=0, quality=85, progress=lambda i, n, name: None,
                   cancel=lambda: False):
    """Resize (longest side <= max_side, 0 = keep) and/or convert to fmt ('keep'|'jpg'|'png'|'webp') into outdir.
    Returns ([output paths], [(name, error)])."""
    from PIL import Image, ImageOps
    os.makedirs(outdir, exist_ok=True)
    outs, fails = [], []
    for i, src in enumerate(paths):
        if cancel():
            break
        name = os.path.basename(src)
        progress(i, len(paths), name)
        try:
            ext = os.path.splitext(name)[1][1:].lower()
            kind, new_ext = IMAGE_FORMATS.get(fmt if fmt != "keep" else ext, (None, None))
            if not kind:
                raise ValueError(f"can't write .{ext} files")
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im)
                if max_side and max(im.size) > max_side:
                    im.thumbnail((max_side, max_side), Image.LANCZOS)
                params = {}
                if kind == "JPEG":
                    im = im.convert("RGB")
                    params = dict(quality=int(quality), optimize=True)
                elif kind == "WEBP":
                    params = dict(quality=int(quality))
                elif kind == "PNG":
                    params = dict(optimize=True)
                dst = _unique(outdir, os.path.splitext(name)[0] + "." + new_ext)
                im.save(dst, kind, **params)
            outs.append(dst)
        except Exception as e:  # noqa
            fails.append((name, str(e)))
    progress(len(paths), len(paths), "")
    return outs, fails


# -------------------------------------------------------------------- empty folders
def find_empty_folders(top, cancel=lambda: False, progress=lambda m: None):
    """[(folder, nested_empty_count)] for the top-most folders that contain no files at all (sub-folders count
    as empty only if they are too). Hidden/system folders, links and .git / node_modules style folders are never offered."""
    keep_names = {".git", "node_modules", "__pycache__", ".venv", "venv", "$recycle.bin", "system volume information"}
    empty, n = set(), 0
    topn = os.path.normcase(top).rstrip("\\")
    for d, dirs, files in os.walk(top, topdown=False):
        if cancel():
            return None
        n += 1
        if n % 200 == 0:
            progress(f"Scanning\u2026 {n:,} folders")
        if os.path.normcase(d).rstrip("\\") == topn:
            continue
        if any(part.lower() in keep_names for part in os.path.relpath(d, top).split("\\")) or os.path.islink(d):
            continue  # nothing inside .git / node_modules style folders is ever offered
        try:
            if getattr(os.stat(d), "st_file_attributes", 0) & 0x6:  # hidden / system
                continue
        except OSError:
            continue
        if files or any(os.path.join(d, x) not in empty for x in dirs):
            continue
        empty.add(d)
    top_most = [d for d in empty if os.path.dirname(d) not in empty]
    out = []
    for d in top_most:
        nested = sum(1 for e in empty if e != d and e.startswith(d + "\\"))
        out.append((d, nested))
    return sorted(out, key=lambda t: t[0].lower())
