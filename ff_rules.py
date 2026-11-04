"""Automatic rules: when a file turns up in a folder you choose (for example Downloads), move, copy, rename, tag or colour it by your rules.

Safe by design: rules never delete anything; only files that sit directly in the watched folder are looked at (never sub-folders); a file must be
untouched for a while and not be a half-finished download; names that already exist are never overwritten (the new file gets - Copy added);
protected folders and system folders are never touched. Nothing runs until the person switches the rules on.
"""
import fnmatch
import os
import time

import ff_extras as X

PARTIAL = (".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload", ".!ut", ".aria2", ".temp")
GROUPS = {
    "Images": set("png jpg jpeg gif webp bmp svg heic tif tiff raw".split()),
    "Videos": set("mp4 mkv avi mov wmv webm flv m4v mpg mpeg 3gp".split()),
    "Audio": set("mp3 wav flac ogg m4a aac wma".split()),
    "Documents": set("pdf doc docx txt md rtf odt xls xlsx csv ppt pptx odp ods".split()),
    "Archives": set("zip rar 7z tar gz bz2 xz".split()),
    "Installers": set("exe msi msix iso".split()),
}
ACTIONS = ("move", "copy", "rename", "tag", "label")


def new_rule(**kw):
    r = {"id": "r" + str(int(time.time() * 1000))[-9:], "name": "New rule", "enabled": True, "folder": "", "groups": [], "exts": [], "name_like": "",
         "min_age_min": 5, "older_days": 0, "min_mb": 0, "action": "move", "dest": "", "pattern": "{date} {name}{ext}", "tag": "", "label": ""}
    r.update(kw)
    return r


def group_of(ext):
    ext = ext.lower().lstrip(".")
    return next((g for g, s in GROUPS.items() if ext in s), "Other")


def _protected(path, protected):
    low = os.path.normcase(os.path.abspath(path))
    return any(low == os.path.normcase(p) or low.startswith(os.path.normcase(p).rstrip(chr(92)) + chr(92)) for p in protected or [])


def check_rule(rule):
    """Plain-language problems that make a rule unusable ('' list = fine)."""
    out = []
    f = rule.get("folder") or ""
    if not f or not os.path.isdir(f):
        out.append("Choose the folder to watch.")
    elif X.shred_check(f):  # drive roots, Windows, Program Files...
        out.append("That folder is a system folder or a drive root; rules never touch those.")
    if rule.get("action") not in ACTIONS:
        out.append("Choose what the rule does.")
    if rule.get("action") in ("move", "copy"):
        d = rule.get("dest") or ""
        if not d:
            out.append("Choose where the files should go.")
        elif os.path.normcase(os.path.abspath(d)).split("{")[0].rstrip(chr(92)) == os.path.normcase(os.path.abspath(f)).rstrip(chr(92)) and rule.get("action") == "move":
            out.append("The destination is the watched folder itself.")
    if rule.get("action") == "tag" and not (rule.get("tag") or "").strip():
        out.append("Type the tag to add.")
    if rule.get("action") == "label" and not rule.get("label"):
        out.append("Choose the colour label.")
    if not (rule.get("groups") or rule.get("exts") or rule.get("name_like") or rule.get("older_days")):
        out.append("Say which files: pick a type, a name pattern or an age (a rule for every file is too risky).")
    return out


def _fmt(template, name, mtime):
    stem, ext = os.path.splitext(name)
    t = time.localtime(mtime)
    vals = {"name": stem, "ext": ext, "year": f"{t.tm_year}", "month": f"{t.tm_mon:02d}", "day": f"{t.tm_mday:02d}",
            "date": time.strftime("%Y-%m-%d", t), "type": group_of(ext)}
    try:
        return template.format(**vals)
    except (KeyError, IndexError, ValueError):
        return template


def _safe_name(s):
    s = "".join("_" if c in '<>:"/|?*' or ord(c) < 32 else c for c in s).strip(". ")
    return s or "file"


def matches(rule, name, st, now):
    ext = os.path.splitext(name)[1].lower()
    if ext in PARTIAL or name.startswith("~$") or name.lower() == "desktop.ini" or name.startswith("."):
        return False
    if now - st.st_mtime < max(1, int(rule.get("min_age_min") or 5)) * 60:
        return False  # still being written / just arrived
    if getattr(st, "st_file_attributes", 0) & 0x6:  # hidden or system
        return False
    e = ext.lstrip(".")
    kinds = [g for g in (rule.get("groups") or [])]
    exts = [x.lower().lstrip(".") for x in (rule.get("exts") or []) if x.strip()]
    if kinds or exts:
        if not ((kinds and group_of(e) in kinds) or (exts and e in exts)):
            return False
    if rule.get("name_like") and not fnmatch.fnmatch(name.lower(), f"*{rule['name_like'].lower()}*" if "*" not in rule["name_like"] else rule["name_like"].lower()):
        return False
    if rule.get("older_days") and now - st.st_mtime < float(rule["older_days"]) * 86400:
        return False
    if rule.get("min_mb") and st.st_size < float(rule["min_mb"]) * (1 << 20):
        return False
    return True


def plan(rules, protected=(), now=None, limit=50):
    """What the enabled rules would do right now: [{'rule', 'rid', 'action', 'src', 'dest_folder', 'new_name', ...}]. Each file is claimed by the first rule that fits."""
    now = now or time.time()
    out, claimed = [], set()
    for r in rules:
        if not r.get("enabled", True) or check_rule(r) or _protected(r["folder"], protected):
            continue
        try:
            entries = list(os.scandir(r["folder"]))
        except OSError:
            continue
        for e in sorted(entries, key=lambda x: x.name.lower()):
            if len(out) >= limit:
                return out
            try:
                if e.is_dir(follow_symlinks=False) or e.is_symlink() or e.path in claimed:
                    continue
                st = e.stat()
            except OSError:
                continue
            if not matches(r, e.name, st, now):
                continue
            claimed.add(e.path)
            item = {"rule": r["name"], "rid": r["id"], "action": r["action"], "src": e.path, "name": e.name}
            if r["action"] in ("move", "copy"):
                item["dest_folder"] = os.path.normpath(_fmt(r["dest"], e.name, st.st_mtime))
                if _protected(item["dest_folder"], protected):
                    continue
            elif r["action"] == "rename":
                item["new_name"] = _safe_name(_fmt(r["pattern"], e.name, st.st_mtime))
                if item["new_name"] == e.name:
                    continue
            elif r["action"] == "tag":
                item["tag"] = r["tag"].strip()
            else:
                item["label"] = r["label"]
            out.append(item)
    return out


def describe(item):
    n = item["name"]
    a = item["action"]
    if a in ("move", "copy"):
        return f"{'Move' if a == 'move' else 'Copy'} {n}  →  {item['dest_folder']}"
    if a == "rename":
        return f"Rename {n}  →  {item['new_name']}"
    if a == "tag":
        return f"Tag {n} with “{item['tag']}”"
    return f"Colour {n} {item['label']}"


def execute(item, tags=None):
    """Do one planned action. Returns (src, new_path) for moves/renames (so Undo can put them back), or None for the others. Raises OSError."""
    src, a = item["src"], item["action"]
    if not os.path.isfile(src):
        raise OSError("the file is gone")
    if a in ("move", "copy"):
        os.makedirs(item["dest_folder"], exist_ok=True)
        pairs = X.transfer([src], item["dest_folder"], a == "move", resolve=lambda s, e: "keep")
        return pairs[0] if (pairs and a == "move") else None
    if a == "rename":
        new = X._unique(os.path.dirname(src), item["new_name"])
        os.rename(src, new)
        return (src, new)
    if tags is None:
        raise OSError("tags are not available")
    label, cur = tags.get(src)
    if a == "tag":
        if item["tag"] not in cur:
            tags.set(src, tags=cur + [item["tag"]])
    else:
        tags.set(src, color=item["label"])
    return None


def run(rules, protected=(), tags=None, now=None, limit=50, dry=False):
    """Apply the plan. Returns (moved_pairs, [(item, 'done'|'failed'|'planned', message)]). dry=True only lists what would happen."""
    moved, results = [], []
    for item in plan(rules, protected, now, limit):
        if dry:
            results.append((item, "planned", describe(item)))
            continue
        try:
            pair = execute(item, tags)
            if pair:
                moved.append(pair)
            results.append((item, "done", describe(item)))
        except OSError as e:
            results.append((item, "failed", f"{describe(item)}: {e}"))
    return moved, results
