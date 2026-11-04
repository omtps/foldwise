"""Saved-search alerts: remembers which files each alerting saved search has already shown, so only NEW matches are reported.
The first check of a search only records what matches now (nothing is reported), so switching an alert on never floods you."""
import json
import os
import threading

CAP = 20000  # paths remembered per search


class Alerts:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        self._d = None

    def _load(self):
        if self._d is None:
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                self._d = d["seen"] if isinstance(d, dict) and isinstance(d.get("seen"), dict) else {}
            except (OSError, ValueError, KeyError):
                self._d = {}
        return self._d

    def _save(self):
        tmp = self.path + ".tmp"
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "seen": self._d}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def check(self, name, paths):
        """The paths not seen before for this search (newest first as given). They count as seen from now on."""
        paths = list(paths)
        with self._lock:
            d = self._load()
            seen = d.get(name)
            if seen is None:  # first time: this is the baseline
                d[name] = [p.lower() for p in paths][:CAP]
                self._save()
                return []
            known = set(seen)
            new = [p for p in paths if p.lower() not in known]
            if new:
                d[name] = ([p.lower() for p in new] + seen)[:CAP]
                self._save()
            return new

    def forget(self, name):
        with self._lock:
            if self._load().pop(name, None) is not None:
                self._save()

    def rename(self, old, new):
        with self._lock:
            d = self._load()
            if old in d:
                d[new] = d.pop(old)
                self._save()
