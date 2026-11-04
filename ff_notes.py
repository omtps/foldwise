"""Short notes attached to folders (or files), kept in notes.json next to the index. Notes follow a folder when it is renamed or moved in Pinefiles."""
import json
import os
import threading
import time

MAX_LEN = 4000


def _key(path):
    return os.path.normcase(os.path.abspath(path)).rstrip(chr(92)) or path


class Notes:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        self._d = None

    def _load(self):
        if self._d is None:
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                self._d = d["notes"] if isinstance(d, dict) and isinstance(d.get("notes"), dict) else {}
            except (OSError, ValueError, KeyError):
                self._d = {}
        return self._d

    def _save(self):
        tmp = self.path + ".tmp"
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "notes": self._d}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def get(self, path):
        with self._lock:
            return (self._load().get(_key(path)) or {}).get("text", "")

    def set(self, path, text):
        """Store the note (an empty text removes it)."""
        text = (text or "").strip()[:MAX_LEN]
        with self._lock:
            d = self._load()
            if text:
                d[_key(path)] = {"path": os.path.abspath(path), "text": text, "t": time.time()}
            else:
                d.pop(_key(path), None)
            self._save()

    def move(self, old, new):
        """The note of `old` (and of everything inside it) now belongs to `new`."""
        lo, ln = _key(old), _key(new)
        with self._lock:
            d = self._load()
            hit = [k for k in d if k == lo or k.startswith(lo + chr(92))]
            if not hit:
                return
            for k in hit:
                item = d.pop(k)
                nk = ln + k[len(lo):]
                item["path"] = os.path.abspath(new) + item["path"][len(os.path.abspath(old)):]
                d[nk] = item
            self._save()

    def paths_for(self, word=""):
        """Paths whose note contains `word` (any note when `word` is empty or '*')."""
        word = word.strip().strip('"').lower()
        with self._lock:
            return [v["path"] for v in self._load().values() if word in ("", "*") or word in v["text"].lower()]

    def count(self):
        with self._lock:
            return len(self._load())
