"""Per-folder view memory: a folder where you changed the sort order or switched between list and thumbnails opens that way next time.
The views live in the config as {folder: {"sort": key, "rev": bool, "grid": bool}}; the newest LIMIT folders are kept."""
import os

LIMIT = 300


def _key(path):
    return os.path.normcase(os.path.abspath(path)).rstrip(chr(92)) or path


def recall(views, path):
    """The remembered view of `path` ({} when there is none)."""
    return dict(views.get(_key(path)) or {})


def remember(views, path, **view):
    """A copy of `views` with `view` merged into the entry of `path` (that folder becomes the newest); the oldest entries beyond LIMIT go."""
    out = dict(views)
    k = _key(path)
    entry = {**(out.pop(k, None) or {}), **view}
    out[k] = entry
    while len(out) > LIMIT:
        out.pop(next(iter(out)))
    return out


def forget(views, path):
    return {k: v for k, v in views.items() if k != _key(path)}
