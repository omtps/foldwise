"""Photo timeline: finds the photos in a folder, works out when each was taken (EXIF date, else the file date, via ff_extras.file_date) and groups
them by year and month. Dates are remembered in a small cache file, so opening the timeline again only reads the photos that are new."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import ff_core
import ff_extras as X

PHOTO_EXTS = ("jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "heic")
NOISE = tuple(n.replace("/", chr(92)) for n in ("/appdata/", "/node_modules/", "/.", "/$recycle.bin/", "/windows/", "/program files", "/programdata/"))  # app caches, not your photos
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def _noisy(path):
    return any(n in path.lower() for n in NOISE)


def list_photos(folder, limit=100_000):
    """[(path, size, mtime)] of the photos below `folder`: from the search index when it knows the folder (fast), else by walking it."""
    out = []
    try:
        con = ff_core.connect()
        try:
            like = ff_core.like_esc(os.path.normcase(os.path.abspath(folder)).rstrip(chr(92)).lower() + chr(92)) + "%"
            marks = ",".join("?" * len(PHOTO_EXTS))
            out = con.execute(f"SELECT path, size, mtime FROM files WHERE is_dir=0 AND ext IN ({marks}) AND path_lc LIKE ? ESCAPE ? LIMIT ?",
                              (*PHOTO_EXTS, like, chr(92), limit)).fetchall()
        finally:
            con.close()
    except Exception:  # noqa - no index / not readable: walk instead
        out = []
    if not out:
        for d, dirs, files in os.walk(folder):
            dirs[:] = [x for x in dirs if not _noisy(os.path.join(d, x) + chr(92))]
            for f in files:
                if f.rsplit(".", 1)[-1].lower() in PHOTO_EXTS:
                    p = os.path.join(d, f)
                    try:
                        st = os.stat(p)
                        out.append((p, st.st_size, st.st_mtime))
                    except OSError:
                        pass
            if len(out) >= limit:
                break
    return [r for r in out if not _noisy(r[0])]


class DateCache:
    """path -> [mtime, size, taken-timestamp]; a photo is read again only when its size or date changed."""

    def __init__(self, path):
        self.path, self.d, self.dirty = str(path), {}, False
        try:
            with open(self.path, encoding="utf-8") as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {}

    def get(self, p, size, mtime):
        v = self.d.get(p)
        return v[2] if v and v[0] == mtime and v[1] == size else None

    def put(self, p, size, mtime, ts):
        self.d[p] = [mtime, size, ts]
        self.dirty = True

    def save(self):
        if self.dirty:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f)
            os.replace(tmp, self.path)
            self.dirty = False


def scan(folder, cache_path, progress=None, cancel=lambda: False, workers=4):
    """[(taken-timestamp, path)] newest first. progress(done, total) while the dates of new photos are read."""
    photos = list_photos(folder)
    cache = DateCache(cache_path)
    out, todo = [], []
    for p, _size, _mtime in photos:
        try:
            st = os.stat(p)  # the index can lag behind: size and date come from the file itself (this does not open it, so it never downloads anything)
        except OSError:
            continue  # gone since the index saw it
        ts = cache.get(p, st.st_size, st.st_mtime)
        (out.append((ts, p)) if ts is not None else todo.append((p, st.st_size, st.st_mtime)))

    def read(item):
        p, size, mtime = item
        if cancel():
            return None
        return p, size, mtime, X.file_date(p).timestamp()
    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(read, todo):
            done += 1
            if r:
                cache.put(r[0], r[1], r[2], r[3])
                out.append((r[3], r[0]))
            if progress and (done % 25 == 0 or done == len(todo)):
                progress(done, len(todo))
    cache.save()
    return sorted(out, reverse=True)


def group(entries):
    """{year: {month number: [(timestamp, path)]}} (newest first inside every month)."""
    g = {}
    for ts, p in entries:
        t = time.localtime(ts)
        g.setdefault(t.tm_year, {}).setdefault(t.tm_mon, []).append((ts, p))
    return g


def summary(g):
    """[(year, total, [(month number, count)])] newest year first, newest month first."""
    return [(y, sum(len(v) for v in months.values()), [(m, len(months[m])) for m in sorted(months, reverse=True)]) for y, months in sorted(g.items(), reverse=True)]
