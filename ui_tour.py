"""Guided tour: walks through the REAL windows (file view, Tools, cleaner, health, ...) and points at the item each step is about.
A highlight frame is drawn around the target widget and a small card next to it explains it. Esc / Skip ends the tour; the card has
the 'show at startup' checkbox. Steps are plain data: (title, text, setup(A) -> widget or None)."""
import tkinter as tk
from tkinter import ttk

import ui_pages
from ff_core import T

_TOUR = {"card": None, "lines": [], "i": 0, "tok": 0, "on": False}


def _btn(A, label):
    for it in A.cmd_items:
        if it["kind"] == "btn" and it["label"].startswith(label):
            return it["w"]
    return None


def _first(widget, cls):
    stack = [widget]
    while stack:
        w = stack.pop(0)
        if w.winfo_class() == cls and w.winfo_ismapped():
            return w
        stack.extend(w.winfo_children())
    return None


def _find(widget, clsname):
    stack = [widget]
    while stack:
        w = stack.pop(0)
        if type(w).__name__ == clsname:
            return w
        stack.extend(w.winfo_children())
    return None


def _files(A):
    ui_pages.show_files(A)


def _tool(A, attr, *args):
    getattr(A, attr)(*args)
    return ui_pages.active()


# (title, text, setup) - setup opens whatever is needed and returns the widget to point at (None = centre of the window)
def _steps(A):
    return [
        ("Welcome", "This short tour opens the real windows and points at things. Use Next / Back, or press Esc any time to leave. "
                    "Nothing is changed during the tour.", lambda: (_files(A), None)[1]),
        ("Search", "Type here and results appear instantly (Ctrl+F jumps here). Add tokens to narrow it: ext:pdf  size:>100mb  "
                   "modified:today  content:invoice (search inside documents, if enabled).", lambda: (_files(A), A.entry)[1]),
        ("Quick filters", "One-click filters for common searches: Images, Videos, Docs, Big files, Today...  "
                          "You can hide this row in Tools > Customize.", lambda: (_files(A), A.chipbar if A.chipbar.winfo_ismapped() else A.entry)[1]),
        ("Places", "Your folders and drives. Recent and frequent folders can be shown here too (turn them on in Customize). "
                   "Drag a folder here to pin it; right-click for options.", lambda: (_files(A), A.side)[1]),
        ("The file list", "Click a column heading to sort; drag its border to resize. Drag in the empty strip left of the names (or any "
                          "blank space) to select many files; right-click for the menu (Shift+right-click = the full Windows menu). "
                          "Space = quick look, F2 = rename.", lambda: (_files(A), A.tree)[1]),
        ("Tabs", "Open several folders at once: Ctrl+T new tab, Ctrl+W close, Ctrl+1...9 jump. Tools you open get their own tab here too.",
         lambda: (_files(A), A.tabbar)[1]),
        ("Sort and View", "Sort order, the thumbnail grid, hidden files, row size, workspaces and the command palette live in these menus.",
         lambda: (_files(A), _btn(A, "☰ View") or _btn(A, "⇅ Sort"))[1]),
        ("Split and Details", "Split shows two folders side by side (copy or move between them). Details shows a preview and info of the selected file (F3).",
         lambda: (_files(A), _btn(A, "◫ Split"))[1]),
        ("The Tools button", "Everything beyond browsing is here: cleaning, PC health, security, backups, photos, sharing. "
                             "The number next to the heart is your latest health score.", lambda: (_files(A), _btn(A, "⚙ Tools"))[1]),
        ("Tools overview", "Clicking Tools opens one full-window area. The list on the left switches tools; your recent ones are on top of this overview. "
                           "'Back to files' returns.", lambda: (ui_pages.open_tools(A), ui_pages._S["nav"])[1]),
        ("Smart disk cleaner", "Finds junk (temp files, caches, old installers, empty folders...) and shows exactly what it would remove. "
                               "Tick categories on the left, review items on the right, then clean. Auto-clean only moves files to a restorable quarantine.",
         lambda: _first(_tool(A, "open_cleaner"), "Treeview")),
        ("Duplicates with previews", "Select two files in a group and both previews appear on the right, so you can see they really are the same "
                                     "before anything goes to the Recycle Bin. Largest files and Similar photos work the same way.",
         lambda: _find(_tool(A, "open_duplicates"), "PreviewPane") or _first(ui_pages.active(), "Treeview")),
        ("Recycle Bin and Recent changes", "Recycle Bin lists what you deleted with its original folder and date and puts items back where they came from (Foldwise never empties it). "
                                           "Recent changes shows what was created or modified in the last hour, day or week.",
         lambda: (ui_pages.open_tools(A), ui_pages._S["rows"].get("Recycle Bin") or ui_pages._S["nav"])[1]),
        ("PC health", "A score plus tabs for disks, memory, security, startup apps, network, programs and trends. "
                      "Recommendations come with a fix button; nothing is changed without you.", lambda: _tool(A, "open_health")),
        ("Malware check", "Uses Windows Defender's engine and adds Foldwise's own deep check for suspicious startup entries and unsigned programs. "
                          "Findings are scored, can be quarantined and restored.", lambda: _tool(A, "open_malware")),
        ("Backups", "Copies new and changed files to a drive you choose, daily or weekly, and never deletes anything. Set it up in the Backups tab.",
         lambda: _tool(A, "open_health", "backups")),
        ("Files, vault and sharing", "Encrypted vault, folder sync, checksums, photo tools, OCR, FTP/SFTP/WebDAV and 'Foldwise on another PC' are in the "
                                    "'Files & photos' and 'Connect & share' groups of this list.",
         lambda: (ui_pages.open_tools(A), ui_pages._S["rows"].get("Encrypted vault") or ui_pages._S["nav"])[1]),
        ("Customize", "Themes (Adwaita Dark / Light, Follow Windows...), accent colour, rounded buttons, fonts, what is on or off, and the Setup wizard.",
         lambda: _tool(A, "open_settings")),
        ("You're set", "F1 lists every shortcut; Ctrl+K opens the command palette where every tool and setting is a short search away. "
                       "Replay this tour any time: Tools > Foldwise > Tutorial.", lambda: (_files(A), None)[1]),
    ]


def start(A, _=None):
    stop(A, quiet=True)
    if A.root.state() == "withdrawn":
        A.root.deiconify()
    _TOUR.update(on=True, i=0, steps=_steps(A))
    if not _TOUR.get("bound"):
        _TOUR["bound"] = True
        A.root.bind("<Escape>", lambda e: stop(A) if _TOUR["on"] else None, add="+")
        A.root.bind("<Configure>", lambda e: _reflow(A) if e.widget is A.root and _TOUR["on"] else None, add="+")
    _show(A)


def stop(A, quiet=False):
    _TOUR["on"] = False
    _TOUR["tok"] += 1
    for w in _TOUR["lines"] + ([_TOUR["card"]] if _TOUR["card"] else []):
        try:
            w.destroy()
        except tk.TclError:
            pass
    _TOUR["lines"], _TOUR["card"] = [], None
    if not quiet:
        ui_pages.show_files(A)


def _go(A, d):
    i = _TOUR["i"] + d
    if i >= len(_TOUR["steps"]):
        stop(A)
        return
    _TOUR["i"] = max(0, i)
    _show(A)


def _show(A):
    _TOUR["tok"] += 1
    tok = _TOUR["tok"]
    title, text, setup = _TOUR["steps"][_TOUR["i"]]
    try:
        target = setup()
    except Exception as e:  # noqa - a step that can't open its window just points at nothing
        target = None
        _TOUR.setdefault("errors", []).append(f"{title}: {e!r}")
    _TOUR["target"] = target
    _draw(A, title, text)
    # tools build their pages a moment after opening: point again once they are laid out
    A.root.after(700, lambda: tok == _TOUR["tok"] and _TOUR["on"] and _redraw_target(A, setup, title, text))


def _redraw_target(A, setup, title, text):
    try:
        if _TOUR["target"] is None or not _TOUR["target"].winfo_exists() or not _TOUR["target"].winfo_ismapped():
            _TOUR["target"] = _retarget(A)
    except tk.TclError:
        _TOUR["target"] = _retarget(A)
    _draw(A, title, text)


def _retarget(A):
    page = ui_pages.active()
    return (_find(page, "PreviewPane") or _first(page, "Treeview")) if page is not None else None


def _reflow(A):
    A.root.after(80, lambda: _TOUR["on"] and _draw(A, *_TOUR["steps"][_TOUR["i"]][:2]))


def _draw(A, title, text):
    root = A.root
    for w in _TOUR["lines"]:
        w.destroy()
    _TOUR["lines"] = []
    if _TOUR["card"] is not None:
        _TOUR["card"].destroy()
    root.update_idletasks()
    rw, rh = root.winfo_width(), root.winfo_height()
    t = _TOUR.get("target")
    box = None
    try:
        if t is not None and t.winfo_exists() and t.winfo_ismapped():
            x, y = t.winfo_rootx() - root.winfo_rootx(), t.winfo_rooty() - root.winfo_rooty()
            box = (max(0, x - 3), max(0, y - 3), min(rw, x + t.winfo_width() + 3), min(rh, y + t.winfo_height() + 3))
    except tk.TclError:
        box = None
    if box:
        x0, y0, x1, y1 = box
        for (x, y, w, h) in ((x0, y0, x1 - x0, 3), (x0, y1 - 3, x1 - x0, 3), (x0, y0, 3, y1 - y0), (x1 - 3, y0, 3, y1 - y0)):
            f = tk.Frame(root, bg=T["accent"])
            f.place(x=x, y=y, width=max(1, w), height=max(1, h))
            f.lift()
            _TOUR["lines"].append(f)
    card = tk.Frame(root, bg=T["accent"])
    inner = tk.Frame(card, bg=T["panel"], padx=18, pady=14)
    inner.pack(padx=2, pady=2)
    tk.Label(inner, text=f"{_TOUR['i'] + 1} / {len(_TOUR['steps'])}", bg=T["panel"], fg=T["muted"], font=("Segoe UI", 9)).pack(anchor="e")
    tk.Label(inner, text=title, bg=T["panel"], fg=T["fg"], font=("Segoe UI", 15, "bold")).pack(anchor="w")
    tk.Label(inner, text=text, bg=T["panel"], fg=T["fg"], wraplength=370, justify="left", font=("Segoe UI", 10)).pack(anchor="w", pady=(6, 12))
    show = tk.BooleanVar(value=A.cfg.get("show_tutorial", True))
    ttk.Checkbutton(inner, text="Show this tour when Foldwise starts", variable=show,
                    command=lambda: A.save_cfg(show_tutorial=show.get())).pack(anchor="w", pady=(0, 10))
    row = tk.Frame(inner, bg=T["panel"])
    row.pack(fill="x")
    ttk.Button(row, text="Skip tour", command=lambda: stop(A)).pack(side="left")
    last = _TOUR["i"] == len(_TOUR["steps"]) - 1
    ttk.Button(row, text="Finish" if last else "Next →", style="Accent.TButton", command=lambda: _go(A, 1)).pack(side="right")
    b = ttk.Button(row, text="← Back", command=lambda: _go(A, -1))
    b.pack(side="right", padx=8)
    if _TOUR["i"] == 0:
        b.configure(state="disabled")
    card.update_idletasks()
    cw, ch = card.winfo_reqwidth(), card.winfo_reqheight()
    if box:
        x0, y0, x1, y1 = box
        if y1 + 14 + ch <= rh:
            cx, cy = x0, y1 + 14  # below the target
        elif y0 - 14 - ch >= 0:
            cx, cy = x0, y0 - 14 - ch  # above
        elif x1 + 14 + cw <= rw:
            cx, cy = x1 + 14, max(8, y0)  # right of it
        else:
            cx, cy = max(8, x0 - cw - 14), max(8, y0)
    else:
        cx, cy = (rw - cw) // 2, (rh - ch) // 3
    cx = max(8, min(cx, rw - cw - 8))
    cy = max(8, min(cy, rh - ch - 8))
    card.place(x=cx, y=cy)
    card.lift()
    _TOUR["card"] = card
