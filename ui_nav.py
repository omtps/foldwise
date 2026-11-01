"""Sidebar, breadcrumbs, tabs, split view, workspaces and folder history menus.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import ff_extras as X
import ff_index as I
import os
import time
import tkinter as tk
import ff_platform
import ui_pages
from ff_core import ThemedAsk as simpledialog
from ff_core import ThemedBox as messagebox
from tkinter import ttk
from ff_core import (T, human_size, list_dir, recent_noise)


def build_sidebar(A):
    A.side.delete(0, "end")
    A.side_items.clear()
    A.side_sections.clear()

    def add(label, kind, value=None, fg=None, section=None):
        A.side.insert("end", "  " + label if kind != "h" else "   " + label)
        A.side_items.append((kind, value))
        A.side_sections.append(section)
        if fg:
            A.side.itemconfigure("end", fg=fg)
        if kind == "h":
            A.side.itemconfigure("end", fg=T["muted"], selectforeground=T["muted"], selectbackground=T["panel"])

    add("PLACES", "h")
    add("\U0001F3E0  Home", "path", A.home)
    for n, g in (("Desktop", "\U0001F5A5"), ("Documents", "\U0001F4C4"), ("Downloads", "⬇"),
                 ("Pictures", "\U0001F5BC"), ("Music", "\U0001F3B5"), ("Videos", "\U0001F3AC")):
        p = os.path.join(A.home, n)
        if os.path.isdir(p):
            add(f"{g}  {n}", "path", p)
    add("🗑  Recycle Bin", "action", "open_recycle_bin")
    clouds = [(n, p) for n, p in (("OneDrive", os.environ.get("OneDrive") or os.path.join(A.home, "OneDrive")), ("Dropbox", os.path.join(A.home, "Dropbox")),
                                  ("Google Drive", os.path.join(A.home, "Google Drive")), ("iCloud Drive", os.path.join(A.home, "iCloudDrive"))) if os.path.isdir(p)]
    for n, p in clouds:
        add(f"\u2601  {n}", "path", p)
    pins = [p for p in A.cfg["pins"] if os.path.isdir(p)]
    if pins:
        add("PINNED", "h")
        for p in pins:
            add(f"\U0001F4CC  {os.path.basename(p) or p}", "path", p)
    skip_ = {os.path.normcase(A.home)} | {os.path.normcase(os.path.join(A.home, n)) for n in (
        "Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")} | {os.path.normcase(p) for p in pins}
    if A.cfg["sidebar_recent"]:
        n_ = max(1, min(10, int(A.cfg["sidebar_recent_n"])))
        now_ = time.time()
        ign_ = [os.path.normcase(x) for x in A.cfg["recent_ignore"]]

        def okdir(p):
            k = os.path.normcase(p)
            return (os.path.isdir(p) and k not in skip_ and not recent_noise(p)
                    and not any(k == g or k.startswith(g + "\\") for g in ign_))

        def fscore(p):
            sc, last = A.cfg["frec"].get(p, (0.0, 0.0))
            return sc * 0.5 ** ((now_ - last) / (7 * 86400))

        chosen = []
        for p in A.cfg["recent_dirs"]:
            if not okdir(p):
                continue
            k = os.path.normcase(p)
            if any(os.path.normcase(c).startswith(k + "\\") for c in chosen):
                continue  # you opened a deeper folder after this one, so this was just on the way
            chosen.append(p)
            if len(chosen) >= n_:
                break
        freq_ = sorted((p for p in A.cfg["frec"] if okdir(p) and p not in chosen), key=fscore, reverse=True)
        freq_ = [p for p in freq_ if fscore(p) >= 2.5][:n_]
        if chosen:
            add("RECENT FOLDERS", "h", section="recent_dirs")
            for p in chosen:
                add(f"\U0001F551  {os.path.basename(p.rstrip(chr(92))) or p}", "path", p, section="recent_dirs")
        if freq_:
            add("FREQUENT", "h", section="frequent")
            for p in freq_:
                add(f"\u2B50  {os.path.basename(p.rstrip(chr(92))) or p}", "path", p, section="frequent")
        files_ = [p for p in dict.fromkeys(A.cfg["recent"]) if os.path.exists(p) and "ff_zip_" not in p][:n_]
        if files_:
            add("RECENT FILES", "h", section="recent_files")
            for p in files_:
                add(f"\U0001F4C4  {os.path.basename(p)}", "file", p, section="recent_files")
    tg_, col_ = A.tags_store.summary()
    if tg_ or col_:
        add("LABELS & TAGS", "h")
        for c in I.LABEL_COLORS:
            if col_.get(c):
                add(f"\u25CF  {c.title()}  ({col_[c]})", "search", f"label:{c}", fg=I.LABEL_HEX[c])
        for t_, n_ in sorted(tg_.items(), key=lambda kv: (-kv[1], kv[0]))[:12]:
            add(f"\U0001F3F7  {t_}  ({n_})", "search", f"tag:{t_}")
    if A.cfg["saved"]:
        add("SAVED SEARCHES", "h")
        for name, text in A.cfg["saved"].items():
            add(f"\U0001F50D  {name}", "search", text)
    add("DRIVES", "h")
    dr = X.drives()
    A.st["drives"] = tuple(d[0] for d in dr)
    for d, kind, free, total in dr:
        g = {2: "\U0001F4BE", 3: "\U0001F4BD", 4: "\U0001F310"}.get(kind, "\U0001F4BD")
        add(f"{g}  {d.rstrip(chr(92))}   {human_size(free)} free" if total else f"{g}  {d.rstrip(chr(92))}", "path", d)


def on_side(A, _=None):
    c = A.side.curselection()
    if c:
        kind, val = A.side_items[c[0]]
        if kind == "h":
            A.side.selection_clear(0, "end")
        elif kind == "path":
            A.navigate(val)
        elif kind == "file":
            A.navigate(os.path.dirname(val), select=val)
        elif kind == "action":
            A.side.selection_clear(0, "end")
            getattr(A, val)()
        else:
            A.q.set(val)


def side_popup(A, e):
    i = A.side.nearest(e.y)
    if i >= len(A.side_items):
        return
    kind, val = A.side_items[i]
    sec = A.side_sections[i] if i < len(A.side_sections) else None
    m = A.make_menu()
    if kind == "path" and val in A.cfg["pins"]:
        m.add_command(label="Unpin from sidebar", command=lambda: (
            A.save_cfg(pins=[p for p in A.cfg["pins"] if p != val]), A.build_sidebar()))
    elif kind == "search" and val in A.cfg["saved"].values():
        m.add_command(label="Rename saved search", command=lambda: A.rename_saved(val))
        m.add_command(label="Delete saved search", command=lambda: (
            A.save_cfg(saved={k: v for k, v in A.cfg["saved"].items() if v != val}), A.build_sidebar()))
    if sec in ("recent_dirs", "frequent") and kind == "path":
        m.add_command(label="Remove from this list", command=lambda: A.forget_folder(val))
        m.add_command(label="Never show this folder here", command=lambda: A.forget_folder(val, ignore=True))
    if sec == "recent_files" and kind == "file":
        m.add_command(label="Remove from this list", command=lambda: A.forget_file(val))
    if sec:
        if m.index("end") is not None:
            m.add_separator()
        m.add_command(label={"recent_dirs": "Clear recent folders", "frequent": "Clear frequent folders",
                             "recent_files": "Clear recent files"}[sec], command=lambda: A.clear_recent(sec))
        m.add_command(label="Clear all recent lists", command=lambda: A.clear_recent("all"))
        m.add_command(label="Recent items settings\u2026", command=A.open_settings)
    if m.index("end") is None:
        return
    m.tk_popup(e.x_root, e.y_root)


def build_crumbs(A):
    for w in A.crumbs.winfo_children():
        w.destroy()
    p = os.path.normpath(A.st["cwd"])
    drive, rest = os.path.splitdrive(p)
    parts = [(drive + "\\", drive + "\\")]
    acc = drive + "\\"
    for seg in [s for s in rest.split("\\") if s]:
        acc = os.path.join(acc, seg)
        parts.append((seg, acc))
    if len(parts) > 7:
        parts = parts[:1] + [("…", parts[-5][1])] + parts[-4:]
    for i, (label, target) in enumerate(parts):
        if i:
            sep = ttk.Button(A.crumbs, text="\u203A", style="Crumb.TButton", width=1)
            sep.configure(command=lambda b=sep, fld=parts[i - 1][1]: A.crumb_menu(b, fld))
            sep.pack(side="left", pady=3)
        b = ttk.Button(A.crumbs, text=label, style="Crumb.TButton", width=0, command=lambda t=target: A.navigate(t))
        b._ff_path = target  # drop target for drag & drop
        b.pack(side="left", pady=3, padx=1)
    tail = ttk.Button(A.crumbs, text="\u203A", style="Crumb.TButton", width=1)
    tail.configure(command=lambda: A.crumb_menu(tail, A.st["cwd"]))
    tail.pack(side="left", pady=3)
    A.crumbs.bind("<Button-1>", lambda e: A.edit_path())


def edit_path(A, _=None):
    A.crumbs.pack_forget()
    A.path_e.pack(fill="both", expand=True)
    A.pathv.set(A.st["cwd"])
    A.path_e.focus_set()
    A.path_e.select_range(0, "end")


def crumb_menu(A, btn, folder):
    subs = A.subfolders(folder)
    m = A.make_menu()
    if not subs:
        m.add_command(label="(no sub-folders)", state="disabled")
    for r in subs[:60]:
        m.add_command(label="\U0001F4C1  " + r[0], command=lambda p=r[1]: A.navigate(p))
    if len(subs) > 60:
        m.add_command(label=f"… and {len(subs) - 60} more", state="disabled")
    A.popup_below(btn, m)


def dest_menu(A, move):
    """Quick destinations for Copy to / Move to."""
    m = A.make_menu()
    seen = {os.path.normcase(A.st["cwd"])} if move else set()

    def add(label, path):
        k = os.path.normcase(path or "")
        if not path or k in seen or not os.path.isdir(path):
            return
        seen.add(k)
        m.add_command(label=label, command=lambda: A.sel() and A.run_transfer([r[1] for r in A.sel()], path, move))

    nm = lambda p: os.path.basename(p.rstrip("\\")) or p
    if A.pane["split"]:
        other = A.panes[1 - A.pane["i"]]["cwd"]
        add(f"⇄  Other pane — {nm(other)}", other)
    for p in A.cfg["pins"]:
        add(f"\U0001F4CC  {nm(p)}", p)
    for p in A.cfg["recent_dirs"][:8]:
        if not recent_noise(p):
            add(f"\U0001F551  {nm(p)}", p)
    for n in ("Desktop", "Documents", "Downloads", "Pictures"):
        add(f"\U0001F4C2  {n}", os.path.join(A.home, n))
    m.add_separator()
    m.add_command(label="Choose another folder…", command=lambda: A.choose_dest(move))
    return m


def choose_dest(A, move):
    from ui_picker import filedialog
    d = filedialog.askdirectory(initialdir=A.st["cwd"], parent=A.root, title="Choose a destination folder")
    if d and A.sel():
        A.run_transfer([r[1] for r in A.sel()], os.path.normpath(d), move)


def _tab(A, label, on, close, pick, tool=False, menu=None, reorder=None):
    """One flat tab: label, optional ✕, and an accent underline on the active one (GNOME-ish)."""
    fs = A.cfg["font_size"]
    bgc = T["sel"] if on else T["panel"]
    fr = tk.Frame(A.tabbar, bg=bgc, cursor="hand2")
    fr.pack(side="left", padx=(0, 3))
    row = tk.Frame(fr, bg=bgc)
    row.pack(fill="x")
    lab = tk.Label(row, text=f"  {label} ", bg=bgc, fg=T["fg"] if on else T["muted"], font=("Segoe UI", fs, "bold" if tool and on else "normal"))
    lab.pack(side="left", pady=5)
    if close:
        x = tk.Label(row, text="✕ ", bg=bgc, fg=T["muted"], font=("Segoe UI", fs - 2))
        x.pack(side="left", padx=(0, 4))
        x.bind("<Button-1>", lambda e: close())
    tk.Frame(fr, bg=T["accent"] if on else bgc, height=2).pack(fill="x")
    drag = {"x": 0}
    for w in (fr, row, lab):
        if reorder:  # folder tabs: a click switches on RELEASE (switching rebuilds the tabs, which would cancel a drag); a drag reorders
            w.bind("<ButtonPress-1>", lambda e: drag.update(x=e.x_root))
            w.bind("<ButtonRelease-1>", lambda e: pick() if abs(e.x_root - drag["x"]) < 8 else reorder(e.x_root))
        else:
            w.bind("<Button-1>", lambda e: pick())
        if close:
            w.bind("<Button-2>", lambda e: close())
        if menu:
            w.bind("<Button-3>", lambda e: menu(e))
    return fr, lab


def move_tab_to(A, i, x_root):
    """Dropped the folder tab i at screen x: put it where the pointer is (before the tab it landed on)."""
    frames = [w for w in A.tabbar.winfo_children() if hasattr(w, "_ff_path")]
    for j, w in enumerate(frames):
        if w.winfo_rootx() <= x_root < w.winfo_rootx() + w.winfo_width():
            move_tab(A, i, j)
            return
    if frames and x_root >= frames[-1].winfo_rootx() + frames[-1].winfo_width():
        move_tab(A, i, len(frames) - 1)  # dropped past the last tab: move to the end
    elif frames:
        move_tab(A, i, 0)


def move_tab(A, i, j):
    if i == j or not (0 <= i < len(A.tabs) and 0 <= j < len(A.tabs)):
        return
    A.save_tab()
    active = A.tabs[A.cur["i"]]
    A.tabs.insert(j, A.tabs.pop(i))
    A.cur["i"] = next(k for k, t in enumerate(A.tabs) if t is active)
    A.build_tabs()


def tab_menu(A, e, i):
    """Right-click on a folder tab."""
    m = tab_menu_build(A, i)
    m.tk_popup(e.x_root, e.y_root)


def tab_menu_build(A, i):
    m = A.make_menu()
    m.add_command(label="Duplicate tab", command=lambda: A.new_tab(A.tabs[i]["cwd"]))
    m.add_command(label="Open in Explorer", command=lambda: ff_platform.open_path(A.tabs[i]["cwd"]) if os.path.isdir(A.tabs[i]["cwd"]) else None)
    m.add_separator()
    if len(A.tabs) > 1:
        m.add_command(label="Close tab", command=lambda: A.close_tab(i))
        m.add_command(label="Close other tabs", command=lambda: [A.close_tab(k) for k in reversed(range(len(A.tabs))) if k != i])
        if i < len(A.tabs) - 1:
            m.add_command(label="Close tabs to the right", command=lambda: [A.close_tab(k) for k in reversed(range(i + 1, len(A.tabs)))])
    return m


def build_tabs(A):
    for w in A.tabbar.winfo_children():
        w.destroy()
    fs = A.cfg["font_size"]
    page_on = ui_pages.active() is not None
    for i, t in enumerate(A.tabs):
        name = (os.path.basename(t["cwd"].rstrip("\\")) or t["cwd"])[:20]
        fr, lab = _tab(A, name, i == A.cur["i"] and not page_on,
                       (lambda i=i: A.close_tab(i)) if len(A.tabs) > 1 else None, lambda i=i: A.switch_tab(i),
                       menu=lambda e, i=i: tab_menu(A, e, i),
                       reorder=lambda x, i=i: move_tab_to(A, i, x))
        for w in (fr, lab):
            w._ff_path = t["cwd"]
    pg = ui_pages.pages()
    if pg:
        tk.Frame(A.tabbar, bg=T["muted"], width=1).pack(side="left", fill="y", padx=(4, 7), pady=6)
    for p in pg:
        _tab(A, ui_pages.tab_label(p)[:24], p is ui_pages.active(), p.close, lambda p=p: ui_pages.show_page(A, p), tool=True)
    plus = tk.Label(A.tabbar, text=" ＋ ", bg=T["bg"], fg=T["muted"], font=("Segoe UI", fs + 2), cursor="hand2")
    plus.pack(side="left")
    plus.bind("<Button-1>", lambda e: A.new_tab())


def switch_tab(A, i):
    ui_pages.show_files(A)
    A.activate(0)
    if i != A.cur["i"] and 0 <= i < len(A.tabs):
        A.save_tab()
        A.cur["i"] = i
        A.load_tab()


def new_tab(A, path=None):
    ui_pages.show_files(A)
    A.activate(0)
    A.save_tab()
    p = path or A.st["cwd"]
    A.tabs.insert(A.cur["i"] + 1, {"cwd": p, "hist": [p], "pos": 0})
    A.cur["i"] += 1
    A.load_tab()


def close_tab(A, i=None):
    i = A.cur["i"] if i is None else i
    if len(A.tabs) < 2:
        return
    A.activate(0)
    A.save_tab()
    closed = A.st.setdefault("closed_tabs", [])
    closed.append(dict(A.tabs[i]))
    del closed[:-10]
    A.tabs.pop(i)
    if i < A.cur["i"]:
        A.cur["i"] -= 1
    A.cur["i"] = min(A.cur["i"], len(A.tabs) - 1)
    A.load_tab()


def reopen_tab(A, _=None):
    stack = A.st.setdefault("closed_tabs", [])
    if not stack:
        A.status.set("No closed tabs to reopen")
        return
    A.activate(0)
    A.save_tab()
    t = stack.pop()
    A.tabs.insert(A.cur["i"] + 1, {"cwd": t["cwd"], "hist": t["hist"], "pos": t["pos"]})
    A.cur["i"] += 1
    A.load_tab()


def next_tab(A, d=1):
    A.switch_tab((A.cur["i"] + d) % len(A.tabs))


def save_workspace(A):
    name = simpledialog.askstring("Save workspace", "Name for this set of tabs:", parent=A.root)
    if name and name.strip():
        A.save_tab()
        ws = dict(A.cfg["workspaces"])
        ws[name.strip()] = [t["cwd"] for t in A.tabs if not X.zip_is_virtual(t["cwd"])]
        A.save_cfg(workspaces=ws)
        A.status.set(f"Workspace “{name.strip()}” saved ({len(ws[name.strip()])} tab(s))")


def load_workspace(A, name):
    paths = [p for p in A.cfg["workspaces"].get(name, []) if os.path.isdir(p)]
    if not paths:
        A.status.set("None of that workspace's folders exist any more")
        return
    A.activate(0)
    A.save_tab()
    A.tabs[:] = [{"cwd": p, "hist": [p], "pos": 0} for p in paths]
    A.cur["i"] = 0
    A.load_tab()
    A.status.set(f"Workspace “{name}” opened")


def delete_workspace(A, name):
    if messagebox.askyesno("Workspace", f"Forget the workspace “{name}”? (No folders are touched.)", parent=A.root):
        A.save_cfg(workspaces={k: v for k, v in A.cfg["workspaces"].items() if k != name})


def toggle_split(A, _=None):
    if A.pane["split"]:
        A.activate(0)
        A.pane["split"] = False
        A.pane_frames[1][0].grid_forget()
        A.mid.columnconfigure(1, weight=0, uniform="")
        if A.pane.pop("details_was", False):
            A.toggle_details(value=True)
        A.cmd_items[:] = [i_ for i_ in A.cmd_items if i_["w"] not in A.split_btns]
        for b in A.split_btns:
            b.destroy()
        A.split_btns.clear()
        A.root.after(10, lambda: A.layout_cmdbar(force=True))
        A.split_b.configure(style="Cmd.TButton")
    else:
        if A.grid["on"]:
            A.toggle_grid(value=False)  # the grid is a single-pane view
        A.pane["split"] = True
        if A.cfg["details_open"]:  # two panes need the width the details pane uses
            A.pane["details_was"] = True
            A.toggle_details(value=False)
        A.panes[1].update(cwd=A.st["cwd"], hist=[A.st["cwd"]], pos=0, rows=[], pos_by_path={}, mode="browse")
        A.mid.columnconfigure(1, weight=1, uniform="panes")
        A.pane_frames[1][0].grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        A.activate(1)
        A.refresh()
        A.activate(0)
        A.split_b.configure(style="On.TButton")
        for text, mv in (("Copy →", False), ("Move →", True)):
            b = ttk.Button(A.cmdbar, text=text, style="Cmd.TButton", command=lambda mv=mv: A.to_other(mv))
            A.split_btns.insert(0, b)
            A.cmd_items.insert(next(k_ for k_, i_ in enumerate(A.cmd_items) if i_["w"] is A.split_b) + 1,
                             dict(w=b, kind="btn", label=text, cmd=lambda mv=mv: A.to_other(mv), menu=None))
        A.root.after(10, lambda: A.layout_cmdbar(force=True))
    A.mark_active()


def hist_move(A, d):
    """Up/Down in the search box walks through earlier searches (Down falls through to the list otherwise)."""
    h = A.cfg["search_history"]
    i = A.st.get("hist_i")
    if d < 0:  # Up = older
        if not h:
            return None
        if i is None:
            A.st["hist_draft"] = A.q.get()
            i = 0
        else:
            i = min(i + 1, len(h) - 1)
    else:
        if i is None:
            return None
        i = i - 1
    A.st["hist_setting"] = True
    A.q.set(A.st.get("hist_draft", "") if i < 0 else h[i])
    A.st["hist_setting"] = False
    A.st["hist_i"] = None if i < 0 else i
    A.entry.icursor("end")
    return "break"


def subfolders(A, folder):
    rows = list_dir(folder, A.cfg["show_hidden"]) or []
    return sorted((r for r in rows if r[4]), key=lambda r: X.natural_key(r[0]))
