"""Smart disk cleaner backend for Pinefiles.

The scanners only LOOK: they never delete. They return items as (path, size, mtime, note) so the GUI can show a
preview and let the user decide. The only deleting code is `delete_items`, which refuses anything outside the
whitelisted roots the scanner reported (temp folders and known cache folders), and `empty_bin`.
Files in the user's own folders are never deleted here: the GUI sends those to the Recycle Bin instead.
"""
import ctypes
import os
import re
import shutil
import time
from ctypes import wintypes

import ff_extras as X

HOME = os.path.expanduser("~")
LOCAL = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
ROAMING = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
TEMP = os.environ.get("TEMP") or os.path.join(LOCAL, "Temp")
USER_DIRS = [os.path.join(HOME, n) for n in ("Documents", "Desktop", "Downloads", "Pictures", "Videos", "Music")]
DAY = 86400
TEMP_SKIP_NAMES = {"claude"}  # folders other tools are actively using

# id, title, risk, mode, description. mode: "delete" (permanent, whitelisted caches only), "recycle", "bin"
CATEGORIES = [
    ("temp", "Temporary files", "safe", "delete",
     "Leftovers in your Temp folders that haven't changed for 2+ days. Windows and apps recreate what they need."),
    ("caches", "App & browser caches", "safe", "delete",
     "Browser, GPU-shader, crash-report and package caches. They rebuild themselves (close the app first for a full clean)."),
    ("empty", "Empty folders", "review", "recycle",
     "Folders with nothing inside. They use no space, and some games and apps create empty folders on purpose, so check the list."),
    ("bin", "Recycle Bin", "review", "bin", "Files you already deleted. Emptying it frees the space for good (this cannot be undone)."),
    ("dups", "Duplicate files", "review", "recycle",
     "Identical copies in your personal folders. The best copy of each is kept; the rest are suggested."),
    ("installers", "Old installers & downloads", "review", "recycle",
     "Setup files and archives in Downloads older than 30 days: usually already installed or unpacked."),
    ("large", "Large files not touched in 6+ months", "review", "recycle",
     "Files of 100 MB or more in your personal folders that you haven't changed for half a year."),
    ("leftovers", "Possible leftovers of uninstalled programs", "careful", "recycle",
     "Big, old folders in AppData/ProgramData that no installed program matches. Only a hint: some belong to portable apps or games, so check each one."),
    ("dev", "Old developer folders", "careful", "recycle",
     "node_modules, virtual environments and caches in projects untouched for 90+ days. Recreate with npm install / pip."),
]
TITLE = {c[0]: c[1] for c in CATEGORIES}


def _dir_size(path, cancel):
    """Total bytes of everything under `path` (0 if cancelled)."""
    total, stack = 0, [path]
    while stack:
        if cancel():
            return 0
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    else:
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
    return total


# ----------------------------------------------------------------------------------------------- temp
def scan_temp(cancel=lambda: False, min_age_days=2, dirs=None):
    dirs = dirs if dirs is not None else sorted({TEMP, os.path.join(LOCAL, "Temp")})
    items, now = [], time.time()
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if cancel():
                return None
            if e.name.lower() in TEMP_SKIP_NAMES:
                continue
            try:
                st = e.stat(follow_symlinks=False)
                if now - st.st_mtime < min_age_days * DAY:
                    continue
                size = _dir_size(e.path, cancel) if e.is_dir(follow_symlinks=False) else st.st_size
            except OSError:
                continue
            if size:
                items.append((e.path, size, st.st_mtime, f"not touched for {int((now - st.st_mtime) // DAY)} days"))
    items.sort(key=lambda i: -i[1])
    return {"items": items, "allowed": [os.path.abspath(d) for d in dirs]}


# --------------------------------------------------------------------------------------------- caches
def known_cache_dirs():
    out = []

    def add(label, path):
        if os.path.exists(path):
            out.append((label, path))

    browsers = (("Chrome", os.path.join(LOCAL, "Google", "Chrome", "User Data")),
                ("Edge", os.path.join(LOCAL, "Microsoft", "Edge", "User Data")),
                ("Brave", os.path.join(LOCAL, "BraveSoftware", "Brave-Browser", "User Data")),
                ("Vivaldi", os.path.join(LOCAL, "Vivaldi", "User Data")))
    for name, base in browsers:
        if not os.path.isdir(base):
            continue
        profiles = [d for d in os.listdir(base) if d == "Default" or d.startswith("Profile ")]
        for prof in profiles:
            for sub in ("Cache", "Code Cache", "GPUCache", "DawnCache", os.path.join("Service Worker", "CacheStorage")):
                add(f"{name} cache ({prof})", os.path.join(base, prof, sub))
    ffp = os.path.join(LOCAL, "Mozilla", "Firefox", "Profiles")
    if os.path.isdir(ffp):
        for prof in os.listdir(ffp):
            add("Firefox cache", os.path.join(ffp, prof, "cache2"))
    for app in ("discord", "Slack", "Microsoft\\Teams"):
        for sub in ("Cache", "Code Cache", "GPUCache"):
            add(f"{app.split(chr(92))[-1]} cache", os.path.join(ROAMING, app, sub))
    add("Crash dumps", os.path.join(LOCAL, "CrashDumps"))
    add("Windows error reports", os.path.join(LOCAL, "Microsoft", "Windows", "WER"))
    add("Internet cache", os.path.join(LOCAL, "Microsoft", "Windows", "INetCache"))
    add("DirectX shader cache", os.path.join(LOCAL, "D3DSCache"))
    add("NVIDIA shader cache", os.path.join(LOCAL, "NVIDIA", "DXCache"))
    add("NVIDIA GL cache", os.path.join(LOCAL, "NVIDIA", "GLCache"))
    add("pip cache", os.path.join(LOCAL, "pip", "Cache"))
    add("npm cache", os.path.join(LOCAL, "npm-cache"))
    add("npm cache", os.path.join(ROAMING, "npm-cache"))
    add("NuGet cache", os.path.join(LOCAL, "NuGet", "v3-cache"))
    exp = os.path.join(LOCAL, "Microsoft", "Windows", "Explorer")
    if os.path.isdir(exp):
        for f in os.listdir(exp):
            if re.match(r"(thumbcache|iconcache)_.*\.db$", f, re.I):
                add("Thumbnail cache", os.path.join(exp, f))
    return out


def scan_caches(cancel=lambda: False, candidates=None):
    cands = candidates if candidates is not None else known_cache_dirs()
    items, allowed = [], []
    for label, path in cands:
        if cancel():
            return None
        try:
            st = os.stat(path)
            size = _dir_size(path, cancel) if os.path.isdir(path) else st.st_size
        except OSError:
            continue
        allowed.append(os.path.abspath(path))
        if size >= 100 * 1024:
            items.append((path, size, st.st_mtime, label))
    items.sort(key=lambda i: -i[1])
    return {"items": items, "allowed": allowed}


# ------------------------------------------------------------------------------------------ recycle bin
class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_int64), ("i64NumItems", ctypes.c_int64)]


def scan_bin(cancel=lambda: False):
    info = _SHQUERYRBINFO(ctypes.sizeof(_SHQUERYRBINFO), 0, 0)
    try:
        ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    except Exception:
        return {"items": [], "allowed": []}
    items = [("Recycle Bin", info.i64Size, time.time(), f"{info.i64NumItems:,} deleted items")] if info.i64Size else []
    return {"items": items, "allowed": []}


def empty_bin():
    """Empty the Recycle Bin for good (no confirmation: the GUI already asked). True on success."""
    try:
        return ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7) in (0, 1)  # NOCONFIRM | NOPROGRESS | NOSOUND
    except Exception:
        return False


# --------------------------------------------------------------------------------------------- duplicates
_BAD_PLACES = ("\\downloads\\", "\\temp\\", "\\tmp\\", "\\cache\\", "\\recycle")
_COPY_NAME = re.compile(r"(\(\d+\)|\bcopy\b|- copy)", re.I)


def keep_score(path):
    """Higher = better candidate to KEEP: not in Downloads/Temp, not named '(1)' / 'Copy', shorter path."""
    low = path.lower() + "\\"
    s = -sum(5 for b in _BAD_PLACES if b in low)
    if _COPY_NAME.search(os.path.basename(path)):
        s -= 4
    return s - len(path) / 200.0


def suggest_keep(paths):
    """Index of the copy to keep: best place first, then the oldest file."""
    def key(i):
        try:
            mt = os.path.getmtime(paths[i])
        except OSError:
            mt = 0
        return (-keep_score(paths[i]), mt)
    return min(range(len(paths)), key=key)


def scan_duplicates(cancel=lambda: False, progress=lambda m: None, roots=None, min_size=256 * 1024):
    roots = roots if roots is not None else [d for d in USER_DIRS if os.path.isdir(d)]
    groups = X.find_duplicates(roots, cancel, progress, min_size=min_size)
    if groups is None:
        return None
    items, out_groups = [], []
    for size, paths in groups:
        k = suggest_keep(paths)
        keep = paths[k]
        out_groups.append((size, keep, [p for i, p in enumerate(paths) if i != k]))
        for i, p in enumerate(paths):
            if i != k:
                try:
                    mt = os.path.getmtime(p)
                except OSError:
                    mt = 0
                items.append((p, size, mt, "copy of " + keep))
    items.sort(key=lambda i: -i[1])
    return {"items": items, "allowed": [], "groups": out_groups}


# ------------------------------------------------------------------------------------ installers, large
def _walk_files(roots, cancel):
    for top in roots:
        for d, dirs, files in os.walk(top):
            if cancel():
                return
            dirs[:] = [x for x in dirs if x.lower() not in ("$recycle.bin", "system volume information")]
            for f in files:
                yield os.path.join(d, f)


def scan_installers(cancel=lambda: False, roots=None, older_days=30):
    roots = roots if roots is not None else [os.path.join(HOME, "Downloads")]
    exts, now, items = {"exe", "msi", "msix", "iso", "zip", "7z", "rar", "dmg", "apk"}, time.time(), []
    for p in _walk_files([r for r in roots if os.path.isdir(r)], cancel):
        if os.path.splitext(p)[1][1:].lower() not in exts:
            continue
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if st.st_size >= 1 << 20 and now - st.st_mtime > older_days * DAY:
            items.append((p, st.st_size, st.st_mtime, f"{int((now - st.st_mtime) // DAY)} days old"))
    if cancel():
        return None
    items.sort(key=lambda i: -i[1])
    return {"items": items, "allowed": []}


def scan_large_old(cancel=lambda: False, roots=None, min_mb=100, older_days=180):
    roots = roots if roots is not None else [d for d in USER_DIRS if os.path.isdir(d)]
    now, items = time.time(), []
    for p in _walk_files(roots, cancel):
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if st.st_size >= min_mb << 20 and now - st.st_mtime > older_days * DAY:
            items.append((p, st.st_size, st.st_mtime, f"untouched for {int((now - st.st_mtime) // DAY)} days"))
    if cancel():
        return None
    items.sort(key=lambda i: -i[1])
    return {"items": items, "allowed": []}


# ---------------------------------------------------------------------------------- empty + dev folders
def scan_empty(cancel=lambda: False, roots=None):
    roots = roots if roots is not None else [d for d in USER_DIRS if os.path.isdir(d)]
    items = []
    for r in roots:
        res = X.find_empty_folders(r, cancel)
        if res is None:
            return None
        for d, nested in res:
            try:
                mt = os.path.getmtime(d)
            except OSError:
                mt = 0
            items.append((d, 0, mt, "empty" + (f" (+{nested} empty inside)" if nested else "")))
    return {"items": items, "allowed": []}


DEV_DIR_NAMES = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox"}


def scan_dev(cancel=lambda: False, home=None, older_days=90, min_bytes=5 << 20, max_depth=7):
    home = home or HOME
    now, items = time.time(), []
    base_depth = home.rstrip("\\").count("\\")
    for d, dirs, files in os.walk(home):
        if cancel():
            return None
        depth = d.count("\\") - base_depth
        keep = []
        for name in dirs:
            if name in DEV_DIR_NAMES:
                p = os.path.join(d, name)
                try:
                    mt = os.path.getmtime(p)
                except OSError:
                    continue
                if now - mt > older_days * DAY:
                    size = _dir_size(p, cancel)
                    if size >= min_bytes:
                        items.append((p, size, mt, f"project untouched for {int((now - mt) // DAY)} days"))
                continue  # never descend into them
            if depth == 0 and name.lower() in ("appdata",):
                continue
            if name.startswith(".") or depth >= max_depth:
                continue
            keep.append(name)
        dirs[:] = keep
    items.sort(key=lambda i: -i[1])
    return {"items": items, "allowed": []}


# ----------------------------------------------------------------------------------- uninstall leftovers
LEFTOVER_SKIP = {"microsoft", "windows", "packages", "temp", "programs", "publishers", "connecteddevicesplatform", "d3dscache",
                 "comms", "history", "historyhub", "tempstate", "virtualstore", "pip", "npm", "nuget", "crashdumps", "diagnostics",
                 "placeholdertilelogofolder", "software distribution", "package cache", "usoprivate", "usoshared", "ssh", "pinefiles", "foldwise", "filefinder",
                 "claude", "anthropic", "python", "packagecache", "wer", "regid", "microsoftedge", "onedrive", "apple computer",
                 "wsl", "docker", "lxss", "chocolatey", "electron", "ms-playwright", "ms-playwright-go", "nvidia", "nvidia corporation"}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def scan_leftovers(cancel=lambda: False, installed=None, roots=None, older_days=120, min_bytes=1 << 20):
    """Folders in AppData/ProgramData that no installed program or publisher seems to own any more (review before removing)."""
    if installed is None:
        import ff_health as HL
        installed = HL.installed_apps()
    keys = set()
    for a_ in installed:
        for field in (a_.get("Name"), a_.get("Publisher")):
            for part in re.split(r"[ ,._()\\-]+", field or ""):
                if len(_norm(part)) >= 4:
                    keys.add(_norm(part))
            if len(_norm(field)) >= 4:
                keys.add(_norm(field))
    roots = roots if roots is not None else [LOCAL, ROAMING, os.environ.get("PROGRAMDATA") or r"C:\ProgramData"]
    items, now = [], time.time()
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for e in entries:
            if cancel():
                return None
            n = _norm(e.name)
            if not e.is_dir(follow_symlinks=False) or len(n) < 3 or e.name.lower() in LEFTOVER_SKIP or n in LEFTOVER_SKIP:
                continue
            if any(n in k or (len(k) >= 5 and k in n) for k in keys):
                continue
            try:
                st = e.stat(follow_symlinks=False)
                if now - st.st_mtime < older_days * DAY:
                    continue
                size = _dir_size(e.path, cancel)
            except OSError:
                continue
            if size >= min_bytes:
                items.append((e.path, size, st.st_mtime, f"no installed program matches this name; untouched for {int((now - st.st_mtime) // DAY)} days"))
    items.sort(key=lambda i: -i[1])
    return {"items": items, "allowed": []}


SCANNERS = {"temp": scan_temp, "caches": scan_caches, "bin": scan_bin, "installers": scan_installers,
            "large": scan_large_old, "empty": scan_empty, "dev": scan_dev, "leftovers": scan_leftovers}


def scan(cat_id, cancel=lambda: False, progress=lambda m: None):
    if cat_id == "dups":
        return scan_duplicates(cancel, progress)
    return SCANNERS[cat_id](cancel)


# ------------------------------------------------------------------------------------------- deleting
def _under(path, root):
    p, r = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root)).rstrip("\\")
    return p == r or p.startswith(r + "\\")


def is_protected(path, protected):
    return any(_under(path, r) for r in protected or ())


def apply_exclusions(res, protected):
    """Drop everything inside a protected folder from a scan result (items and duplicate groups)."""
    if not protected or not res:
        return res
    res = dict(res)
    res["items"] = [i for i in res.get("items", []) if not is_protected(i[0], protected)]
    groups = []
    for size, keep, dups in res.get("groups", []):
        dups = [d for d in dups if not is_protected(d, protected)]
        if dups:
            groups.append((size, keep, dups))
    res["groups"] = groups
    return res


def delete_items(items, allowed, cancel=lambda: False, progress=lambda i, n: None, protected=()):
    """PERMANENTLY delete paths, but only ones inside `allowed` roots (temp / known caches). Returns (freed, failed)."""
    freed, failed = 0, []
    for i, (path, size, *_rest) in enumerate(items):
        if cancel():
            break
        progress(i, len(items))
        ab = os.path.abspath(path)
        if is_protected(ab, protected):
            failed.append((path, "inside a protected folder"))
            continue
        if len(os.path.normpath(ab).split("\\")) < 4 or not any(_under(ab, r) for r in allowed):
            failed.append((path, "outside the allowed cleanup locations"))
            continue
        try:
            if os.path.isdir(ab) and not os.path.islink(ab):
                shutil.rmtree(ab, ignore_errors=True)
            elif os.path.lexists(ab):
                os.remove(ab)
        except OSError as e:
            failed.append((path, str(e)))
        if not os.path.exists(ab):
            freed += size
        elif os.path.isdir(ab):  # partly cleaned (some files in use): count what disappeared
            left = _dir_size(ab, lambda: False)
            freed += max(0, size - left)
            if left:
                failed.append((path, "some files are in use"))
    progress(len(items), len(items))
    return freed, failed


# ------------------------------------------------------------------------ auto-clean with a restore list
# The unattended cleaner never deletes: it MOVES safe items (temp files, caches) into a quarantine folder of ours and
# writes a manifest so any batch can be restored. Batches older than `days` are purged by purge_quarantine().
AUTO_CATEGORIES = ("temp", "caches")


def autoclean_run(qroot, cancel=lambda: False, protected=(), progress=lambda m: None, categories=AUTO_CATEGORIES, scan_fn=None):
    """Scan the safe categories and move what they find into qroot/<stamp>/. Returns {'batch','moved','freed','failed'}."""
    import json
    stamp = time.strftime("%Y%m%d-%H%M%S")
    batch = os.path.join(qroot, stamp)
    entries, freed, failed = [], 0, []
    for cid in categories:
        if cancel():
            break
        progress(TITLE[cid])
        res = apply_exclusions((scan_fn or scan)(cid, cancel), protected)
        if not res:
            continue
        allowed = res.get("allowed", [])
        for path, size, *_rest in res["items"]:
            if cancel():
                break
            ab = os.path.abspath(path)
            if len(os.path.normpath(ab).split("\\")) < 4 or not any(_under(ab, r) for r in allowed) or is_protected(ab, protected):
                failed.append((path, "outside the allowed cleanup locations"))
                continue
            dest = os.path.join(batch, f"{len(entries):05d}_{os.path.basename(ab)}")
            try:
                os.makedirs(batch, exist_ok=True)
                shutil.move(ab, dest)
                entries.append({"orig": ab, "stored": dest, "size": size, "cat": cid})
                freed += size
            except OSError as e:
                failed.append((path, str(e)))
    if entries:
        with open(os.path.join(batch, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"created": time.time(), "entries": entries}, f)
    return {"batch": batch if entries else None, "moved": len(entries), "freed": freed, "failed": failed}


def quarantine_batches(qroot):
    """[{'dir','created','count','bytes'}] newest first."""
    import json
    out = []
    if not os.path.isdir(qroot):
        return out
    for name in sorted(os.listdir(qroot), reverse=True):
        mf = os.path.join(qroot, name, "manifest.json")
        try:
            with open(mf, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        ents = [e for e in m["entries"] if os.path.lexists(e["stored"])]
        out.append({"dir": os.path.join(qroot, name), "created": m["created"], "count": len(ents), "bytes": sum(e["size"] for e in ents)})
    return out


def restore_batch(batch_dir):
    """Move every stored item back to where it came from (never overwrites). Returns (restored, skipped)."""
    import json
    with open(os.path.join(batch_dir, "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    ok, skipped = 0, []
    for e in m["entries"]:
        if not os.path.lexists(e["stored"]):
            continue
        if os.path.lexists(e["orig"]):
            skipped.append((e["orig"], "something is already there"))
            continue
        try:
            os.makedirs(os.path.dirname(e["orig"]), exist_ok=True)
            shutil.move(e["stored"], e["orig"])
            ok += 1
        except OSError as ex:
            skipped.append((e["orig"], str(ex)))
    return ok, skipped


def purge_quarantine(qroot, days=7, only=None):
    """Permanently remove our own quarantine batches older than `days` (or just the batch dir `only`). Returns freed bytes."""
    freed, now = 0, time.time()
    for b in quarantine_batches(qroot) if only is None else [dict(dir=only, created=0, bytes=0)]:
        d = os.path.abspath(b["dir"])
        if not _under(d, qroot) or os.path.normcase(d) == os.path.normcase(os.path.abspath(qroot)):
            continue
        if only is None and now - b["created"] < days * DAY:
            continue
        freed += b["bytes"]
        shutil.rmtree(d, ignore_errors=True)
    return freed
