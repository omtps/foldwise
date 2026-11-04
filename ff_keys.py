"""Keyboard shortcuts: the actions that can be rebound, conversion between friendly names ('Ctrl+Shift+T') and Tk sequences, validation and
conflict detection. No Tk widgets here, so everything can be tested without a window."""
import os
import re

# (id, group, label, default shortcut)
ACTIONS = [
    ("search", "Search & navigation", "Focus the search box", "Ctrl+F"),
    ("path", "Search & navigation", "Edit the path", "Ctrl+L"),
    ("palette", "Search & navigation", "Command palette", "Ctrl+K"),
    ("refresh", "Search & navigation", "Refresh", "F5"),
    ("back", "Search & navigation", "Back", "Alt+Left"),
    ("forward", "Search & navigation", "Forward", "Alt+Right"),
    ("up", "Search & navigation", "Up one folder", "Alt+Up"),
    ("details", "Search & navigation", "Details pane on/off", "F3"),
    ("new_tab", "Tabs & panes", "New tab", "Ctrl+T"),
    ("close_tab", "Tabs & panes", "Close tab", "Ctrl+W"),
    ("reopen_tab", "Tabs & panes", "Reopen closed tab", "Ctrl+Shift+T"),
    ("next_tab", "Tabs & panes", "Next tab", "Ctrl+Tab"),
    ("prev_tab", "Tabs & panes", "Previous tab", "Ctrl+Shift+Tab"),
    ("split", "Tabs & panes", "Split view", "Ctrl+Shift+D"),
    ("grid", "Tabs & panes", "Thumbnail grid", "Ctrl+Shift+G"),
    ("new_folder", "Files", "New folder", "Ctrl+Shift+N"),
    ("bulk_rename", "Files", "Bulk rename", "Ctrl+Shift+R"),
    ("select_pattern", "Files", "Select by pattern (*.jpg)", "Ctrl+Shift+S"),
    ("invert", "Files", "Invert selection", "Ctrl+I"),
    ("copy_path", "Files", "Copy full path of the selection", "Ctrl+Shift+C"),
    ("properties", "Files", "Properties", "Alt+Enter"),
    ("show_in_folder", "Files", "Show in its folder", "Ctrl+Enter"),
    ("undo", "Files", "Undo", "Ctrl+Z"),
    ("shortcuts", "App", "This shortcut list", "F1"),
    ("settings", "App", "Customize", "Ctrl+,"),
    ("zoom_in", "App", "Zoom in", "Ctrl+="),
    ("zoom_out", "App", "Zoom out", "Ctrl+-"),
    ("quit", "App", "Quit Pinefiles", "Ctrl+Q"),
]
# keys that always work the same and are not rebindable (shown in the list for completeness)
FIXED = [
    ("Search & navigation", "Space", "Quick look"), ("Search & navigation", "Backspace", "Up one folder"),
    ("Tabs & panes", "Ctrl+1 … 9", "Jump to tab"), ("Tabs & panes", "Tab", "Switch pane (split view)"),
    ("Files", "Ctrl+C / X / V", "Copy / cut / paste"), ("Files", "F2", "Rename"), ("Files", "Delete", "Delete (Recycle Bin)"), ("Files", "Ctrl+A", "Select all"),
    ("App", "Esc", "Close a pop-up, clear search (never closes the window)"), ("App", "Ctrl++", "Zoom in (same as Ctrl+=)"),
]
DEFAULTS = {a[0]: a[3] for a in ACTIONS}
_KEYSYM = {"Enter": "Return", "Backspace": "BackSpace", "Del": "Delete", "Space": "space", ",": "comma", "=": "equal", "+": "plus", "-": "minus",
           "Left": "Left", "Right": "Right", "Up": "Up", "Down": "Down", "Tab": "Tab", "Home": "Home", "End": "End", "PageUp": "Prior", "PageDown": "Next",
           "Insert": "Insert", ".": "period", "/": "slash", ";": "semicolon", "'": "apostrophe", "[": "bracketleft", "]": "bracketright"}
_FRIENDLY = {v: k for k, v in _KEYSYM.items()}
_FRIENDLY.update({"Prior": "PageUp", "Next": "PageDown", "KP_Enter": "Enter", "ISO_Left_Tab": "Tab"})
_MODS = ("Ctrl", "Alt", "Shift")
_TKMOD = {"Ctrl": "Control", "Alt": "Alt", "Shift": "Shift"}
RESERVED = {"Ctrl+C", "Ctrl+X", "Ctrl+V", "Ctrl+A", "Alt+F4", "Ctrl+Alt+Delete", "Alt+Tab"}  # the clipboard and Windows' own keys


def parse(seq):
    """'ctrl + shift+t' -> (['Ctrl', 'Shift'], 'T'); ValueError when it is not a key combination."""
    parts = [p.strip() for p in str(seq).replace(" + ", "+").split("+") if p.strip()]
    if str(seq).strip().endswith("++") or str(seq).strip() == "+":
        parts = [p.strip() for p in str(seq)[:-1].split("+") if p.strip()] + ["+"]
    if not parts:
        raise ValueError("Press a key combination.")
    key, mods = parts[-1], []
    for m in parts[:-1]:
        name = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift"}.get(m.lower())
        if name is None:
            raise ValueError(f"“{m}” is not a modifier key.")
        if name not in mods:
            mods.append(name)
    if key.lower() in ("ctrl", "control", "alt", "shift"):
        raise ValueError("Press a key together with Ctrl, Alt or Shift.")
    if re.fullmatch(r"[a-zA-Z0-9]", key):
        key = key.upper()
    elif re.fullmatch(r"[Ff]([1-9]|1[0-2])", key):
        key = key.upper()
    else:
        key = {k.lower(): k for k in _KEYSYM}.get(key.lower())
        if key is None:
            raise ValueError("That key can't be used.")
    return [m for m in _MODS if m in mods], key


def normalize(seq):
    mods, key = parse(seq)
    return "+".join(mods + [key])


def to_tk(seq):
    """'Ctrl+Shift+T' -> '<Control-Shift-T>' (the sequence Tk binds)."""
    mods, key = parse(seq)
    if re.fullmatch(r"[A-Z]", key):
        key = key if "Shift" in mods else key.lower()
    elif key in _KEYSYM:
        key = _KEYSYM[key]
    return "<" + "-".join([_TKMOD[m] for m in mods] + [key]) + ">"


def from_event(keysym, state):
    """The friendly name of a pressed combination, or None while only a modifier is held. `state` is Tk's modifier bit mask."""
    if keysym in ("Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Caps_Lock", "Num_Lock", "Win_L", "Win_R"):
        return None
    mods = [m for m, bit in (("Ctrl", 0x4), ("Alt", 0x20000 if os.name == "nt" else 0x8), ("Shift", 0x1)) if state & bit]
    key = _FRIENDLY.get(keysym, keysym)
    if len(key) == 1 and key.isalpha():
        key = key.upper()
    try:
        return normalize("+".join(mods + [key]))
    except ValueError:
        return None


def check(seq):
    """Why a combination should not be used, or None. Plain letters and digits would steal normal typing; clipboard and Windows keys stay as they are."""
    try:
        mods, key = parse(seq)
    except ValueError as e:
        return str(e)
    full = "+".join(mods + [key])
    if full in RESERVED:
        return f"{full} is used by Windows or for copy and paste and can't be changed."
    if not mods and not re.fullmatch(r"F([1-9]|1[0-2])", key):
        return "Use Ctrl or Alt together with the key (a key on its own would interfere with typing). Function keys F1–F12 work on their own."
    if mods == ["Shift"] and re.fullmatch(r"[A-Z0-9]", key):
        return "Shift plus a letter is just typing a capital letter; add Ctrl or Alt."
    return None


def effective(overrides):
    """{action id: shortcut} with the user's changes applied ('' = switched off)."""
    out = dict(DEFAULTS)
    for k, v in (overrides or {}).items():
        if k in out:
            try:
                out[k] = normalize(v) if v else ""
            except ValueError:
                pass
    return out


def conflicts(eff):
    """{shortcut: [action ids]} for every shortcut that more than one action uses."""
    seen = {}
    for k, v in eff.items():
        if v:
            seen.setdefault(v, []).append(k)
    return {s: ids for s, ids in seen.items() if len(ids) > 1}


def label(action_id):
    return next(a[2] for a in ACTIONS if a[0] == action_id)


def sheet(eff):
    """[(group, [(keys, what)])] for the shortcut list: the current keys of every action plus the fixed ones."""
    groups = {}
    for aid, group, what, _d in ACTIONS:
        groups.setdefault(group, []).append((eff.get(aid) or "(off)", what))
    for group, keys, what in FIXED:
        groups.setdefault(group, []).append((keys, what))
    return list(groups.items())
