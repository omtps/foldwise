"""Custom colour themes: validation, contrast checks, registering them next to the built-in palettes, and export / import as small JSON files.

A theme is nine colours (see KEYS); the program derives the rest (selection colour, text on the accent colour) itself.
"""
import json
import re

import ff_core

KEYS = ("bg", "panel", "raised", "fg", "muted", "accent", "line", "alt", "dir")
LABELS = {"bg": "Window background", "panel": "Side panels and bars", "raised": "Buttons and raised areas", "fg": "Text", "muted": "Quiet text",
          "accent": "Accent (buttons, links, selection)", "line": "Lines and borders", "alt": "Shaded rows", "dir": "Folder names"}
BUILTIN = tuple(ff_core.PALETTES)  # the themes that ship with the program: they can be used and copied, never changed
FORMAT = "pinefiles-theme"


def clean_color(s):
    """'#abc' / '#aabbcc' (any case, # optional) -> '#aabbcc', or None when it is not a colour."""
    s = str(s).strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", s):
        s = "".join(c * 2 for c in s)
    return "#" + s.lower() if re.fullmatch(r"[0-9a-fA-F]{6}", s) else None


def luminance(color):
    """WCAG relative luminance (0 = black, 1 = white)."""
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = ff_core._rgb(color)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    """WCAG contrast ratio between two colours (1 = identical, 21 = black on white)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def validate(colors):
    """(clean palette, [problems]): every key present and a real colour."""
    out, problems = {}, []
    for k in KEYS:
        c = clean_color(colors.get(k, ""))
        if c is None:
            problems.append(f"“{LABELS[k]}” is not a colour (use something like #1e1e2e).")
        else:
            out[k] = c
    return out, problems


def warnings(colors):
    """Plain-language readability warnings for a valid palette."""
    out = []
    if contrast(colors["fg"], colors["bg"]) < 4.5:
        out.append(f"Text is hard to read on the window background (contrast {contrast(colors['fg'], colors['bg']):.1f}:1, aim for 4.5 or more).")
    if contrast(colors["muted"], colors["bg"]) < 3:
        out.append("Quiet text almost disappears on the window background.")
    if contrast(colors["accent"], colors["bg"]) < 2:
        out.append("The accent colour is too close to the background colour.")
    return out


def register_all(custom):
    """Make the saved custom themes available next to the built-in ones. Returns the names that were registered."""
    names = []
    for name, colors in (custom or {}).items():
        clean, problems = validate(colors)
        if not problems and name not in BUILTIN:
            ff_core.PALETTES[name] = clean
            names.append(name)
    return names


def unregister(name):
    if name not in BUILTIN:
        ff_core.PALETTES.pop(name, None)


def valid_name(name, existing=()):
    """(clean name, problem or None)."""
    n = re.sub(r"\s+", " ", str(name)).strip()[:30]
    if not n:
        return n, "Give the theme a name."
    if n in BUILTIN or n == "Follow Windows":
        return n, f"“{n}” is a built-in theme; choose another name."
    return n, None


def export_text(name, colors):
    return json.dumps({"format": FORMAT, "name": name, "colors": {k: colors[k] for k in KEYS}}, indent=1)


def import_text(text):
    """(name, palette) from an exported file; ValueError with a plain message when it is not a Pinefiles theme."""
    try:
        d = json.loads(text)
    except ValueError:
        raise ValueError("That file is not a theme file.") from None
    if not isinstance(d, dict) or d.get("format") != FORMAT or not isinstance(d.get("colors"), dict):
        raise ValueError("That file is not a Pinefiles theme.")
    clean, problems = validate(d["colors"])
    if problems:
        raise ValueError(problems[0])
    return str(d.get("name") or "Imported theme")[:30], clean
