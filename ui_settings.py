"""Settings window and the Ctrl+K command palette.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import ff_platform
import os
import sqlite3
import threading
import tkinter as tk
from ff_core import ThemedBox as messagebox
from tkinter import colorchooser
from tkinter import ttk
from ff_core import (DATE_FORMATS, DATE_STYLE, ACCENT_SWATCHES, DB_PATH, PALETTES, T, fuzzy_score, like_esc, parse_hotkey)


def open_settings(A, _=None):
    win = A.toplevel("Customize Foldwise", "760x640")
    f = ttk.Frame(win, padding=20)
    f.pack(fill="both", expand=True)
    r = 0

    def label(t):
        nonlocal r
        ttk.Label(f, text=t, style="DetHead.TLabel", background=T["bg"]).grid(row=r, column=0, columnspan=3,
                                                                                sticky="w", pady=(12, 4))
        r += 1

    label("APPEARANCE")
    ttk.Label(f, text="Theme").grid(row=r, column=0, sticky="w", pady=4)
    theme_cb = ttk.Combobox(f, values=[*PALETTES, "Follow Windows"], state="readonly", width=18)
    theme_cb.set(A.cfg["theme"])
    theme_cb.grid(row=r, column=1, columnspan=2, sticky="w", padx=10)
    theme_cb.bind("<<ComboboxSelected>>", lambda e: (A.change_setting(theme=theme_cb.get(), accent=""),
                                                     win.destroy(), A.open_settings()))
    r += 1
    ttk.Label(f, text="Accent colour").grid(row=r, column=0, sticky="w", pady=4)
    sw = tk.Frame(f, bg=T["bg"])
    sw.grid(row=r, column=1, columnspan=2, sticky="w", padx=10)
    for c in ACCENT_SWATCHES:
        b = tk.Button(sw, bg=c, activebackground=c, width=2, height=1, bd=0, relief="flat",
                      command=lambda c=c: A.change_setting(accent=c))
        b.pack(side="left", padx=2)
    ttk.Button(sw, text="Custom…", command=lambda: (lambda c: c[1] and A.change_setting(accent=c[1]))(
        colorchooser.askcolor(color=T["accent"], parent=win))).pack(side="left", padx=(8, 0))
    r += 1
    ttk.Label(f, text="Text size").grid(row=r, column=0, sticky="w", pady=4)
    fsv = tk.IntVar(value=A.cfg["font_size"])
    ttk.Spinbox(f, from_=8, to=18, textvariable=fsv, width=6,
                command=lambda: A.change_setting(font_size=fsv.get())).grid(row=r, column=1, sticky="w", padx=10)
    r += 1
    ttk.Label(f, text="Row height").grid(row=r, column=0, sticky="w", pady=4)
    rh = ttk.Combobox(f, values=["Compact", "Normal", "Comfortable"], state="readonly", width=18)
    rh.set({24: "Compact", 30: "Normal", 38: "Comfortable"}.get(A.cfg["row_height"], "Normal"))
    rh.grid(row=r, column=1, columnspan=2, sticky="w", padx=10)
    rh.bind("<<ComboboxSelected>>", lambda e: A.change_setting(
        row_height={"Compact": 24, "Normal": 30, "Comfortable": 38}[rh.get()]))
    r += 1

    ttk.Label(f, text="Interface font").grid(row=r, column=0, sticky="w", pady=4)
    fcb = ttk.Combobox(f, values=["Segoe UI", "Segoe UI Variable", "Calibri", "Cantarell", "Arial", "Verdana", "Tahoma", "Consolas"], width=18)
    fcb.set(A.cfg.get("ui_font", "Segoe UI"))
    fcb.grid(row=r, column=1, columnspan=2, sticky="w", padx=10)
    fcb.bind("<<ComboboxSelected>>", lambda e: A.change_setting(ui_font=fcb.get()))
    r += 1
    ttk.Label(f, text="Date format").grid(row=r, column=0, sticky="w", pady=4)
    dfc = ttk.Combobox(f, values=list(DATE_FORMATS), state="readonly", width=18)
    dfc.set(A.cfg.get("date_fmt", "31/12/2026"))
    dfc.grid(row=r, column=1, columnspan=2, sticky="w", padx=10)

    def set_dates(*_):
        A.save_cfg(date_fmt=dfc.get(), clock_12h=h12.get())
        DATE_STYLE.update(fmt=DATE_FORMATS.get(dfc.get(), "%d/%m/%Y"), h12=h12.get())
        A.refresh()
    dfc.bind("<<ComboboxSelected>>", set_dates)
    r += 1
    h12 = tk.BooleanVar(value=A.cfg.get("clock_12h", False))
    ttk.Checkbutton(f, text="12-hour clock (3:05 PM)", variable=h12, command=set_dates).grid(row=r, column=0, columnspan=2, sticky="w", pady=2)
    r += 1
    zv = tk.BooleanVar(value=A.cfg.get("zebra", True))
    ttk.Checkbutton(f, text="Shade every other row in lists", variable=zv, command=lambda: A.change_setting(zebra=zv.get())).grid(
        row=r, column=0, columnspan=2, sticky="w", pady=2)
    r += 1
    rv = tk.BooleanVar(value=A.cfg.get("rounded", True))
    ttk.Checkbutton(f, text="Soft rounded buttons (GNOME-like)", variable=rv, command=lambda: A.change_setting(rounded=rv.get())).grid(
        row=r, column=0, columnspan=2, sticky="w", pady=2)
    r += 1
    ttk.Label(f, text="Corner roundness").grid(row=r, column=0, sticky="w", pady=4)
    crv = tk.IntVar(value=A.cfg.get("corner_radius", 8))
    ttk.Spinbox(f, from_=0, to=14, textvariable=crv, width=6, command=lambda: A.change_setting(corner_radius=crv.get())).grid(
        row=r, column=1, sticky="w", padx=10)
    r += 1
    ttk.Label(f, text="Sidebar width").grid(row=r, column=0, sticky="w", pady=4)
    swv = tk.IntVar(value=A.cfg.get("sidebar_w", 220))

    def set_sw():
        A.save_cfg(sidebar_w=max(120, min(400, swv.get())))
        A.side.master.configure(width=A.cfg["sidebar_w"])
    ttk.Spinbox(f, from_=120, to=400, increment=10, textvariable=swv, width=6, command=set_sw).grid(row=r, column=1, sticky="w", padx=10)
    r += 1
    chv = tk.BooleanVar(value=A.cfg.get("show_chips", True))

    def set_chips():
        A.save_cfg(show_chips=chv.get())
        if chv.get():
            if not A.chipbar.winfo_manager():
                A.chipbar.pack(fill="x", padx=12, pady=(0, 8), before=A.mid.master)
        else:
            A.chipbar.pack_forget()
    ttk.Checkbutton(f, text="Show the quick filter chips (Images, Videos, Docs...)", variable=chv, command=set_chips).grid(
        row=r, column=0, columnspan=3, sticky="w", pady=2)
    r += 1

    label("BEHAVIOUR")
    for text, key in (("Show hidden files", "show_hidden"), ("Calculate folder sizes", "folder_sizes"),
                      ("Real Windows file icons", "real_icons"),
                      ("Folders first when sorting", "folders_first"), ("Open details pane on startup", "details_open"),
                      ("Confirm before deleting", "confirm_delete"),
                      ("Offer a mini-game when a tool takes a while", "game_offer"),
                      ("Restore my tabs on startup", "restore_tabs"),
                      ("Index document contents (instant content: search)", "content_index"),
                      ("Warn me about low disk space and overdue backups", "health_alerts"),
                      ("Show a weekly PC health summary", "weekly_summary"),
                      ("Read scanned PDFs when indexing (OCR, restart to apply)", "ocr_pdfs"),
                      ("Win+E opens Foldwise (restart to apply)", "win_e"),
                      ("Keep search index live (restart to apply)", "live_index")):
        v = tk.BooleanVar(value=A.cfg[key])

        def chg(key=key, v=v):
            A.save_cfg(**{key: v.get()})
            if key == "details_open":
                A.toggle_details(value=v.get())
            elif key == "real_icons":
                A.setup_icons()
                A.refresh()
            elif key == "content_index":
                A.start_content_index() if v.get() else None
            else:
                A.hidden_var.set(A.cfg["show_hidden"])
                A.fsz_var.set(A.cfg["folder_sizes"])
                A.ff_var.set(A.cfg["folders_first"])
                A.refresh()

        ttk.Checkbutton(f, text=text, variable=v, command=chg).grid(row=r, column=0, columnspan=3, sticky="w", pady=2)
        r += 1
    ttk.Label(f, text="Start in").grid(row=r, column=0, sticky="w", pady=(8, 2))
    sv = tk.StringVar(value=A.cfg["start"])
    fr = tk.Frame(f, bg=T["bg"])
    fr.grid(row=r, column=1, columnspan=2, sticky="w", padx=10)
    for t, val in (("Home folder", "home"), ("Last folder", "last")):
        ttk.Radiobutton(fr, text=t, value=val, variable=sv, command=lambda: A.save_cfg(start=sv.get())).pack(
            side="left", padx=(0, 12))
    r += 1

    label("RECENT ITEMS")
    v_show = tk.BooleanVar(value=A.cfg["sidebar_recent"])
    ttk.Checkbutton(f, text="Show recent / frequent folders and recent files in the sidebar", variable=v_show,
                    command=lambda: (A.save_cfg(sidebar_recent=v_show.get()), A.build_sidebar())).grid(
        row=r, column=0, columnspan=3, sticky="w", pady=2)
    r += 1
    ttk.Label(f, text="How many in each list").grid(row=r, column=0, sticky="w", pady=4)
    nv = tk.IntVar(value=A.cfg["sidebar_recent_n"])
    ttk.Spinbox(f, from_=1, to=10, textvariable=nv, width=6, command=lambda: (
        A.save_cfg(sidebar_recent_n=max(1, min(10, nv.get()))), A.build_sidebar())).grid(row=r, column=1, sticky="w", padx=10)
    r += 1
    bf = tk.Frame(f, bg=T["bg"])
    bf.grid(row=r, column=0, columnspan=3, sticky="w", pady=(4, 2))
    for text_, which_ in (("Clear recent folders", "recent_dirs"), ("Clear frequent", "frequent"),
                          ("Clear recent files", "recent_files"), ("Clear all", "all")):
        ttk.Button(bf, text=text_, command=lambda w=which_: A.clear_recent(w)).pack(side="left", padx=(0, 6))
    r += 1
    hid_v = tk.StringVar(value=f"{len(A.cfg['recent_ignore'])} folder(s) hidden from these lists")
    ttk.Label(f, textvariable=hid_v, style="DetKey.TLabel", background=T["bg"]).grid(row=r, column=0, columnspan=2, sticky="w")
    ttk.Button(f, text="Show them again", command=lambda: (A.save_cfg(recent_ignore=[]), A.build_sidebar(),
                                                            hid_v.set("0 folder(s) hidden from these lists"))).grid(
        row=r, column=2, sticky="w", padx=10)
    r += 1

    label("GLOBAL HOTKEY")
    hk = tk.StringVar(value=A.cfg["hotkey"] or A.st["hk"].split(" ")[0].lower())
    ttk.Entry(f, textvariable=hk, width=22).grid(row=r, column=0, columnspan=2, sticky="w", pady=4)

    def set_hk():
        try:
            parse_hotkey(hk.get())
        except ValueError as e:
            messagebox.showerror("Hotkey", str(e), parent=win)
            return
        A.save_cfg(hotkey=hk.get().strip().lower())
        messagebox.showinfo("Hotkey", "Saved. Quit Foldwise from the tray icon and relaunch to apply.", parent=win)

    ttk.Button(f, text="Set", command=set_hk).grid(row=r, column=2, sticky="w", padx=10)
    r += 1
    ttk.Label(f, text="e.g. ctrl+alt+f   (modifiers: ctrl alt shift win)", style="DetKey.TLabel",
              background=T["bg"]).grid(row=r, column=0, columnspan=3, sticky="w")
    r += 1
    ttk.Button(f, text="Setup wizard…", command=lambda: A.welcome(rerun=True)).grid(row=r, column=0, sticky="w", pady=(18, 0))
    ttk.Button(f, text="Close", style="Accent.TButton", command=win.destroy).grid(
        row=r, column=1, columnspan=2, sticky="e", pady=(18, 0))
    win.bind("<Escape>", lambda e: win.destroy())
    _add_filter(win, f, last_row=r)


def _add_filter(win, f, last_row):
    """Search box above the settings: type a word and only the matching options (and their section) stay."""
    q = tk.StringVar()
    e = ttk.Entry(win, textvariable=q)
    e.pack(fill="x", padx=20, pady=(16, 0), before=f)
    ttk.Label(win, text="Type to find a setting, e.g. font, date, hotkey", style="DetKey.TLabel", background=T["bg"]).pack(
        anchor="w", padx=22, before=f)

    def row_text(widgets):
        out = []
        for w in widgets:
            try:
                out.append(str(w.cget("text")).lower())
            except tk.TclError:
                pass
        return " ".join(out)

    rows = {}  # row number -> widgets, taken once while everything is still shown (grid_slaves forgets hidden ones)
    for w in f.grid_slaves():
        rows.setdefault(int(w.grid_info()["row"]), []).append(w)

    def apply(*_):
        want = q.get().strip().lower()
        section = None
        groups = []  # [heading row, [rows]]
        for rn in sorted(rows):
            ws = rows[rn]
            if any(str(w.cget("style")) == "DetHead.TLabel" for w in ws if isinstance(w, ttk.Label)):
                section = [rn, []]
                groups.append(section)
            elif section is not None:
                section[1].append(rn)
        for head, items in groups:
            head_hit = want in row_text(rows[head])
            shown = [rn for rn in items if rn != last_row and (not want or head_hit or want in row_text(rows[rn]))]
            for rn in items:
                for w in rows[rn]:
                    if rn == last_row or rn in shown:
                        w.grid()
                    else:
                        w.grid_remove()
            for w in rows[head]:
                if not want or head_hit or shown:
                    w.grid()
                else:
                    w.grid_remove()
    q.trace_add("write", apply)
    e.bind("<Escape>", lambda ev: (q.set(""), "break")[1] if q.get() else None)


def open_palette(A, _=None):
    if A.st.get("palette"):
        return
    win = tk.Toplevel(A.root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=T["accent"])
    sw = A.root.winfo_screenwidth()
    W = min(700, sw - 100)
    win.geometry(f"{W}x430+{max(20, (sw - W) // 2)}+{max(20, A.root.winfo_rooty() + 90)}")
    inner = tk.Frame(win, bg=T["panel"])
    inner.pack(fill="both", expand=True, padx=2, pady=2)
    v = tk.StringVar()
    e = ttk.Entry(inner, textvariable=v, style="Search.TEntry")
    e.pack(fill="x", padx=12, pady=12)
    lb = tk.Listbox(inner, bg=T["panel"], fg=T["fg"], selectbackground=T["sel"], selectforeground=T["fg"],
                    highlightthickness=0, bd=0, activestyle="none", font=("Segoe UI", A.cfg["font_size"] + 1), height=12)
    lb.pack(fill="both", expand=True, padx=12, pady=(0, 6))
    tk.Label(inner, text="↵ run / open    ↑↓ choose    Esc close    "
             "files: ↵ shows it in its folder, Ctrl+↵ opens it", bg=T["panel"], fg=T["muted"],
             font=("Segoe UI", 9)).pack(pady=(0, 8))
    items, extra, tok = [], [], {"n": 0}
    A.st["palette"] = win

    def close(_=None):
        if A.st.get("palette") is win:
            A.st["palette"] = None
            win.destroy()
            A.tree.focus_set()

    def rebuild():
        text = v.get().strip()
        cand, seen = [], set()
        for label, fn in A.palette_actions():
            sc = 0 if not text else fuzzy_score(text, label)
            if sc is not None:
                cand.append((sc, "▶  " + label, ("act", fn)))
        if text:
            for p in A.local_folders():
                sc = fuzzy_score(text, os.path.basename(p.rstrip("\\")) or p)
                if sc is not None:
                    cand.append((sc - 1, f"\U0001F4C1  {os.path.basename(p.rstrip(chr(92))) or p}   —   {p}", ("dir", p)))
            for p in A.cfg["recent"][:150]:
                sc = fuzzy_score(text, os.path.basename(p))
                if sc is not None:
                    cand.append((sc - 2, f"\U0001F4C4  {os.path.basename(p)}   —   {os.path.dirname(p)}", ("file", p)))
        cand.sort(key=lambda c: -c[0])
        rows = [c[1:] for c in cand] + extra
        lb.delete(0, "end")
        items.clear()
        for label, payload in rows:
            key = (payload[0], str(payload[1]))
            if key in seen:
                continue
            seen.add(key)
            items.append(payload)
            lb.insert("end", "  " + label)
        if items:
            lb.selection_set(0)

    def on_type(*_):
        tok["n"] += 1
        my = tok["n"]
        extra.clear()
        rebuild()
        text = v.get().strip()
        if len(text) < 2:
            return

        def work():
            c = sqlite3.connect(DB_PATH)
            try:
                rows = c.execute("SELECT name,path FROM files WHERE is_dir=1 AND name_lc LIKE ? ESCAPE '\\' "
                                 "ORDER BY length(path) LIMIT 12", ("%" + like_esc(text.lower()) + "%",)).fetchall()
            except sqlite3.Error:
                rows = []
            finally:
                c.close()
            if my == tok["n"] and rows:
                A.root.after(0, lambda: my == tok["n"] and A.st.get("palette") is win and (
                    extra.extend((f"\U0001F4C1  {n}   —   {pth}", ("dir", pth)) for n, pth in rows), rebuild()))

        threading.Thread(target=work, daemon=True).start()

    def move(d):
        c = lb.curselection()
        i = max(0, min(len(items) - 1, (c[0] if c else 0) + d))
        lb.selection_clear(0, "end")
        lb.selection_set(i)
        lb.see(i)
        return "break"

    def run(ctrl=False):
        c = lb.curselection()
        if not c or c[0] >= len(items):
            return "break"
        kind, payload = items[c[0]]
        close()
        if kind == "act":
            A.root.after(20, payload)
        elif kind == "dir":
            A.navigate(payload)
        elif ctrl:
            ff_platform.open_path(payload)
        else:
            A.navigate(os.path.dirname(payload), select=payload)
        return "break"

    v.trace_add("write", on_type)
    e.bind("<Down>", lambda ev: move(1))
    e.bind("<Up>", lambda ev: move(-1))
    e.bind("<Return>", lambda ev: run())
    e.bind("<Control-Return>", lambda ev: run(True))
    win.bind("<Escape>", close)
    lb.bind("<Double-1>", lambda ev: run())
    win.bind("<FocusOut>", lambda ev: A.root.after(150, lambda: close() if A.st.get("palette") is win
                                                 and win.focus_displayof() is None else None))
    rebuild()
    win.focus_force()
    e.focus_set()
