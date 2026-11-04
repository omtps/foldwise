"""Persistent stores for Pinefiles:
 - ContentIndex   full-text index of document contents (SQLite FTS5) for instant `content:` search
 - Tags           colour labels and free-form tags on files/folders, stored by path
"""
import os
import sqlite3
import threading
import time

import ff_extras as X
import ff_platform

LABEL_COLORS = ["red", "orange", "yellow", "green", "blue", "purple"]
LABEL_EMOJI = {"red": "\U0001F534", "orange": "\U0001F7E0", "yellow": "\U0001F7E1", "green": "\U0001F7E2",
               "blue": "\U0001F535", "purple": "\U0001F7E3"}
LABEL_HEX = {"red": "#ef4444", "orange": "#fb923c", "yellow": "#facc15", "green": "#4ade80",
             "blue": "#60a5fa", "purple": "#a78bfa"}
SKIP_DIR_NAMES = {"node_modules", ".git", "__pycache__", ".venv", "venv", "site-packages", ".cache", "$recycle.bin"}
MAX_FILE_BYTES = 8 * 1024 * 1024
OCR_PDFS = False     # index scanned PDFs via OCR (set from the "ocr_pdfs" setting; off by default: it is CPU-heavy)
OCR_MAX_PAGES = 12   # OCR is slow: only short scans are read during indexing


# -------------------------------------------------------------------- content
def pdf_text(path, max_pages=60):
    """Text of a PDF's first pages, or None if pypdf isn't installed / the file can't be read."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(path)
        text = "\n".join((pg.extract_text() or "") for pg in reader.pages[:max_pages])
    except Exception:
        return None
    if len(text.strip()) < 20 and OCR_PDFS and len(reader.pages) <= OCR_MAX_PAGES:
        try:  # a scanned PDF has no text layer: read the page images with Windows' built-in OCR
            import ff_ocr
            if ff_ocr.available():
                text = ff_ocr.ocr_pdf(path, OCR_MAX_PAGES) or text
        except Exception:
            pass
    return text


def pdf_supported():
    try:
        import pypdf  # noqa: F401
        return True
    except ImportError:
        return False


@ff_platform.local_only(str)
def extract_text(path):
    ext = os.path.splitext(path)[1][1:].lower()
    if ext == "pdf":
        return pdf_text(path)
    return X.read_text(path)


def eligible(path):
    ext = os.path.splitext(path)[1][1:].lower()
    return ext in X.CONTENT_EXTS or (ext == "pdf" and pdf_supported())


class ContentIndex:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self.building = False
        self.progress = 0
        self.stop = threading.Event()
        self._live_lock = threading.Lock()  # live watcher batches run one after another

    def connect(self):
        con = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=OFF")
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(path UNINDEXED, body, "
                    "tokenize='unicode61 remove_diacritics 2')")
        con.execute("CREATE TABLE IF NOT EXISTS seen(path TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
        con.execute("CREATE TABLE IF NOT EXISTS roots(path TEXT PRIMARY KEY)")
        return con

    def count(self):
        try:
            con = self.connect()
            n = con.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
            con.close()
            return n
        except sqlite3.Error:
            return 0

    def roots(self):
        try:
            con = self.connect()
            r = [x[0] for x in con.execute("SELECT path FROM roots")]
            con.close()
            return r
        except sqlite3.Error:
            return []

    def covers(self, path):
        low = os.path.normcase(path).rstrip("\\")
        return any(low == os.path.normcase(r).rstrip("\\") or low.startswith(os.path.normcase(r).rstrip("\\") + "\\")
                   for r in self.roots())

    def _upsert(self, con, path, st=None):
        try:
            st = st or os.stat(path)
        except OSError:
            self._remove(con, path)
            return False
        if st.st_size > MAX_FILE_BYTES:
            return False
        row = con.execute("SELECT mtime, size FROM seen WHERE path=?", (path,)).fetchone()
        if row and abs(row[0] - st.st_mtime) < 1 and row[1] == st.st_size:
            return False
        if con.in_transaction:
            con.commit()  # release the write lock BEFORE the slow part (reading a PDF / OCR), so other writers aren't starved
        text = extract_text(path)
        con.execute("DELETE FROM docs WHERE path=?", (path,))
        if text:
            con.execute("INSERT INTO docs(path, body) VALUES(?,?)", (path, text))
        con.execute("INSERT OR REPLACE INTO seen VALUES(?,?,?)", (path, st.st_mtime, st.st_size))
        return True

    @staticmethod
    def _remove(con, path):
        con.execute("DELETE FROM docs WHERE path=?", (path,))
        con.execute("DELETE FROM seen WHERE path=?", (path,))

    def build(self, folders, progress=lambda n: None, throttle=0.004):
        """Index (or refresh) every eligible file under `folders`. Safe to call repeatedly: unchanged files are skipped."""
        if self.building:
            return 0
        self.building, self.progress = True, 0
        self.stop.clear()
        con = self.connect()
        done = 0
        try:
            for f in folders:
                con.execute("INSERT OR IGNORE INTO roots VALUES(?)", (f,))
            con.commit()
            live = set()
            for top in folders:
                for d, dirs, files in os.walk(top):
                    if self.stop.is_set():
                        return done
                    dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIR_NAMES]
                    for name in files:
                        p = os.path.join(d, name)
                        if not eligible(p):
                            continue
                        live.add(p)
                        try:
                            if self._upsert(con, p):
                                done += 1
                        except sqlite3.Error:
                            pass
                        self.progress += 1
                        if self.progress % 50 == 0:
                            con.commit()
                            progress(self.progress)
                            time.sleep(throttle)  # stay out of the way of whatever you're doing
            for (p,) in con.execute("SELECT path FROM seen").fetchall():  # forget files that no longer exist
                if p not in live and not os.path.exists(p):
                    self._remove(con, p)
            con.commit()
            return done
        finally:
            con.close()
            self.building = False
            progress(self.progress)

    def update_paths(self, paths):
        """Live maintenance: re-read changed files (called from the file-system watcher)."""
        if self.building:
            return
        with self._live_lock:
            try:
                con = self.connect()
            except sqlite3.Error:
                return
            try:
                for p in paths:
                    if self.stop.is_set():
                        break
                    try:
                        if self.covers(p) and (eligible(p) or not os.path.exists(p)):
                            self._upsert(con, p) if os.path.exists(p) else self._remove(con, p)
                            con.commit()
                    except sqlite3.OperationalError:  # database busy (e.g. a rebuild is running): the next change event retries
                        con.rollback()
            finally:
                con.close()

    def search(self, terms, limit=1000):
        """Paths of documents containing every term (prefix match), best matches first."""
        q = " AND ".join('"' + t.replace('"', '""') + '" *' for t in terms if t.strip())
        if not q:
            return []
        con = self.connect()
        try:
            return [r[0] for r in con.execute("SELECT path FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?",
                                              (q, limit))]
        except sqlite3.Error:
            return []
        finally:
            con.close()


# ------------------------------------------------------------------------ tags
class Tags:
    def __init__(self, db_path):
        self.db_path = str(db_path)

    def connect(self):
        con = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        con.execute("CREATE TABLE IF NOT EXISTS tags(path_lc TEXT PRIMARY KEY, path TEXT, color TEXT, tags TEXT)")
        return con

    @staticmethod
    def _norm(tags):
        out = []
        for t in tags:
            t = t.strip().lower().replace(",", " ")
            if t and t not in out:
                out.append(t)
        return out

    def get_many(self, paths):
        """{path: (color or None, [tags])} for the paths that have any."""
        out = {}
        con = self.connect()
        try:
            paths = list(paths)
            for i in range(0, len(paths), 400):
                chunk = paths[i:i + 400]
                ph = ",".join("?" * len(chunk))
                for pth, color, tags in con.execute(
                        f"SELECT path, color, tags FROM tags WHERE path_lc IN ({ph})", [p.lower() for p in chunk]):
                    out[pth] = (color or None, [t for t in (tags or "").split(",") if t])
        except sqlite3.Error:
            pass
        finally:
            con.close()
        return out

    def get(self, path):
        return self.get_many([path]).get(path, (None, []))

    def set(self, path, color="keep", tags=None):
        """Set colour and/or tags. color='keep' leaves it; tags=None leaves them."""
        cur_color, cur_tags = self.get(path)
        color = cur_color if color == "keep" else color
        tags = cur_tags if tags is None else self._norm(tags)
        con = self.connect()
        try:
            if not color and not tags:
                con.execute("DELETE FROM tags WHERE path_lc=?", (path.lower(),))
            else:
                con.execute("INSERT OR REPLACE INTO tags VALUES(?,?,?,?)", (path.lower(), path, color or "", ",".join(tags)))
            con.commit()
        finally:
            con.close()

    def move(self, old, new):
        """Keep tags when a file or folder is renamed/moved inside Pinefiles."""
        con = self.connect()
        try:
            lo = old.lower()
            rows = con.execute("SELECT path, color, tags FROM tags WHERE path_lc=? OR (path_lc>=? AND path_lc<?)",
                               (lo, lo + "\\", lo + "]")).fetchall()
            for pth, color, tags in rows:
                newp = new + pth[len(old):]
                con.execute("DELETE FROM tags WHERE path_lc=?", (pth.lower(),))
                con.execute("INSERT OR REPLACE INTO tags VALUES(?,?,?,?)", (newp.lower(), newp, color, tags))
            con.commit()
        except sqlite3.Error:
            pass
        finally:
            con.close()

    def _rewrite(self, change):
        """Apply change(color, [tags]) -> (color, [tags]) to every row; returns how many rows changed. Rows left without colour and tags are removed."""
        con = self.connect()
        done = 0
        try:
            for path_lc, color, tags in con.execute("SELECT path_lc, color, tags FROM tags").fetchall():
                old = (color or "", [t for t in (tags or "").split(",") if t])
                new_color, new_tags = change(*old)
                new_tags = self._norm(new_tags)
                if (new_color or "", new_tags) == old:
                    continue
                done += 1
                if new_color or new_tags:
                    con.execute("UPDATE tags SET color=?, tags=? WHERE path_lc=?", (new_color or "", ",".join(new_tags), path_lc))
                else:
                    con.execute("DELETE FROM tags WHERE path_lc=?", (path_lc,))
            con.commit()
        finally:
            con.close()
        return done

    def rename_tag(self, old, new):
        """Rename a tag everywhere; renaming to a tag that exists merges the two. Returns the number of items changed."""
        old, new = (self._norm([old]) or [""])[0], (self._norm([new]) or [""])[0]
        if not old or not new or old == new:
            return 0
        return self._rewrite(lambda c, t: (c, [new if x == old else x for x in t]))

    def delete_tag(self, tag):
        """Take a tag off every item (colours stay). Returns the number of items changed."""
        tag = (self._norm([tag]) or [""])[0]
        return self._rewrite(lambda c, t: (c, [x for x in t if x != tag])) if tag else 0

    def clear_color(self, color):
        """Remove one colour label from every item (tags stay). Returns the number of items changed."""
        return self._rewrite(lambda c, t: ("" if c == color else c, t))

    def paths_for(self, tag=None, color=None):
        con = self.connect()
        try:
            out = []
            for pth, c, tags in con.execute("SELECT path, color, tags FROM tags"):
                if color and (c or "") != color:
                    continue
                if tag and tag not in (tags or "").split(","):
                    continue
                out.append(pth)
            return out
        finally:
            con.close()

    def summary(self):
        """({tag: count}, {color: count}) for the sidebar."""
        tags, colors = {}, {}
        con = self.connect()
        try:
            for c, t in con.execute("SELECT color, tags FROM tags"):
                if c:
                    colors[c] = colors.get(c, 0) + 1
                for x in (t or "").split(","):
                    if x:
                        tags[x] = tags.get(x, 0) + 1
        finally:
            con.close()
        return tags, colors
