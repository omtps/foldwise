"""Tools > Theme editor: make your own colour theme (with a live miniature preview), save it, use it, export and import it.

Every function takes `A` first (ff_app.App).
"""
import tkinter as tk
from tkinter import colorchooser, ttk

import ff_core
import ff_themes as TH
from ff_core import T, ThemedAsk, ThemedBox as messagebox, blend
from ui_picker import filedialog


def open_themes(A):
    win = A.toplevel("Theme editor", "1000x700")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    st = {"name": A.cfg["theme"] if A.cfg["theme"] in ff_core.PALETTES else "Adwaita Dark"}
    colors = dict(ff_core.PALETTES[st["name"]])
    msg = tk.StringVar()

    bt = ttk.Frame(win, padding=(14, 10))
    bt.pack(side="bottom", fill="x")
    ttk.Label(win, text="Pick a theme on the left, change any colour on the right (the little preview shows it at once), then Save as… under your own name "
              "and Use it. Built-in themes can be copied but not changed.", wraplength=900, padding=(18, 14, 18, 4)).pack(fill="x")
    body = ttk.Frame(win, padding=(18, 4, 18, 0))
    body.pack(fill="both", expand=True)
    left = ttk.Frame(body)
    left.pack(side="left", fill="y")
    lst = ttk.Treeview(left, show="tree", selectmode="browse", height=16)
    lst.pack(side="left", fill="y")
    right = ttk.Frame(body, padding=(20, 0, 0, 0))
    right.pack(side="left", fill="both", expand=True)

    # ---- the colour rows
    rows, hexvars, swatches = ttk.Frame(right), {}, {}
    rows.pack(anchor="w")
    for i, k in enumerate(TH.KEYS):
        ttk.Label(rows, text=TH.LABELS[k], width=34).grid(row=i, column=0, sticky="w", pady=3)
        sw = tk.Label(rows, width=4, relief="flat", cursor="hand2")
        sw.grid(row=i, column=1, padx=6)
        v = tk.StringVar()
        e = ttk.Entry(rows, textvariable=v, width=10)
        e.grid(row=i, column=2)
        sw.bind("<Button-1>", lambda ev, k=k: choose(k))
        e.bind("<Return>", lambda ev, k=k: typed(k))
        e.bind("<FocusOut>", lambda ev, k=k: typed(k))
        hexvars[k], swatches[k] = v, sw

    # ---- the miniature window
    prev = tk.Frame(right, bd=0, highlightthickness=1)
    prev.pack(fill="x", pady=(16, 4))
    tk.Label(right, textvariable=msg, wraplength=520, justify="left", anchor="w").pack(fill="x")
    pv = {}
    pv["bar"] = tk.Frame(prev)
    pv["bar"].pack(fill="x")
    pv["title"] = tk.Label(pv["bar"], text="Pinefiles", anchor="w", padx=10, pady=4)
    pv["title"].pack(side="left")
    pv["btn"] = tk.Label(pv["bar"], text=" Button ", padx=6, pady=2)
    pv["btn"].pack(side="left", padx=6)
    pv["acc"] = tk.Label(pv["bar"], text=" Accent ", padx=6, pady=2)
    pv["acc"].pack(side="left")
    pv["list"] = tk.Frame(prev)
    pv["list"].pack(fill="x")
    for n, text in enumerate(("Documents", "notes.txt   (shaded row)", "Photos   (selected)", "Quiet text: 3 items")):
        pv[n] = tk.Label(pv["list"], text="  " + text, anchor="w", pady=3)
        pv[n].pack(fill="x")

    def paint():
        c = colors
        prev.configure(bg=c["bg"], highlightbackground=c["line"])
        pv["bar"].configure(bg=c["panel"])
        pv["title"].configure(bg=c["panel"], fg=c["fg"])
        pv["btn"].configure(bg=c["raised"], fg=c["fg"])
        pv["acc"].configure(bg=c["accent"], fg="#08111f" if ff_core.luminance(c["accent"]) > 0.55 else "#ffffff")
        pv["list"].configure(bg=c["bg"])
        pv[0].configure(bg=c["bg"], fg=c["dir"])
        pv[1].configure(bg=c["alt"], fg=c["fg"])
        pv[2].configure(bg=blend(c["accent"], c["bg"], 0.32), fg=c["fg"])
        pv[3].configure(bg=c["bg"], fg=c["muted"])
        for k in TH.KEYS:
            swatches[k].configure(bg=c[k])
            if hexvars[k].get() != c[k]:
                hexvars[k].set(c[k])
        warn = TH.warnings(c)
        msg.set("  ".join(warn) if warn else "Readable: the text stands out well on the background.")

    def choose(k):
        got = colorchooser.askcolor(color=colors[k], parent=win, title=TH.LABELS[k])
        if got and got[1]:
            colors[k] = TH.clean_color(got[1])
            paint()

    def typed(k):
        c = TH.clean_color(hexvars[k].get())
        if c:
            colors[k] = c
        paint()

    # ---- the list of themes
    def fill_list(select=None):
        lst.delete(*lst.get_children())
        lst.insert("", "end", iid="__b", text="BUILT-IN", open=True)
        for n in TH.BUILTIN:
            lst.insert("__b", "end", iid=n, text="   " + n)
        mine = [n for n in ff_core.PALETTES if n not in TH.BUILTIN]
        lst.insert("", "end", iid="__m", text="MY THEMES" if mine else "MY THEMES (none yet)", open=True)
        for n in sorted(mine):
            lst.insert("__m", "end", iid=n, text="   " + n)
        if select and lst.exists(select):
            lst.selection_set(select)

    def picked(_e=None):
        s = lst.selection()
        if s and s[0] in ff_core.PALETTES:
            st["name"] = s[0]
            colors.clear()
            colors.update(ff_core.PALETTES[s[0]])
            paint()
    lst.bind("<<TreeviewSelect>>", picked)

    # ---- actions
    def save_as():
        name = ThemedAsk.askstring("Save theme", "Name for your theme:", initialvalue=("" if st["name"] in TH.BUILTIN else st["name"]), parent=win)
        if name is None:
            return None
        name, problem = TH.valid_name(name)
        clean, problems = TH.validate(colors)
        if problem or problems:
            messagebox.showerror("Save theme", problem or problems[0], parent=win)
            return None
        mine = dict(A.cfg.get("custom_themes") or {})
        if name in mine and name != st["name"] and not messagebox.askyesno("Save theme", f"Replace your theme “{name}”?", parent=win):
            return None
        mine[name] = clean
        A.save_cfg(custom_themes=mine)
        TH.register_all({name: clean})
        st["name"] = name
        fill_list(name)
        msg.set(f"Saved “{name}”.")
        return name

    def use():
        name = st["name"]
        if name in ff_core.PALETTES and dict(ff_core.PALETTES[name]) == {k: colors[k] for k in TH.KEYS}:
            pass  # unchanged theme: use as it is
        else:
            name = save_as()
            if not name:
                return
        A.change_setting(theme=name, accent="")

    def delete():
        name = st["name"]
        if name in TH.BUILTIN or name not in ff_core.PALETTES:
            msg.set("Built-in themes can't be deleted.")
            return
        if not messagebox.askyesno("Delete theme", f"Delete your theme “{name}”?", parent=win):
            return
        mine = dict(A.cfg.get("custom_themes") or {})
        mine.pop(name, None)
        A.save_cfg(custom_themes=mine)
        TH.unregister(name)
        if A.cfg["theme"] == name:
            A.change_setting(theme="Adwaita Dark", accent="")
        st["name"] = "Adwaita Dark"
        colors.clear()
        colors.update(ff_core.PALETTES["Adwaita Dark"])
        fill_list("Adwaita Dark")
        paint()

    def export():
        p = filedialog.asksaveasfilename(parent=win, defaultextension=".json", initialfile=f"{st['name']}.json", filetypes=[("Pinefiles theme", "*.json")])
        if p:
            clean, problems = TH.validate(colors)
            if problems:
                messagebox.showerror("Export theme", problems[0], parent=win)
                return
            with open(p, "w", encoding="utf-8") as f:
                f.write(TH.export_text(st["name"], clean))
            msg.set(f"Exported to {p}")

    def import_():
        p = filedialog.askopenfilename(parent=win, filetypes=[("Pinefiles theme", "*.json")])
        if not p:
            return
        try:
            with open(p, encoding="utf-8") as f:
                name, clean = TH.import_text(f.read())
        except (OSError, ValueError) as e:
            messagebox.showerror("Import theme", str(e), parent=win)
            return
        name, problem = TH.valid_name(name)
        n = 2
        base = name if not problem else "Imported theme"
        name = base
        while name in ff_core.PALETTES:
            name, n = f"{base} ({n})", n + 1
        mine = dict(A.cfg.get("custom_themes") or {})
        mine[name] = clean
        A.save_cfg(custom_themes=mine)
        TH.register_all({name: clean})
        st["name"] = name
        colors.clear()
        colors.update(clean)
        fill_list(name)
        paint()
        msg.set(f"Imported as “{name}”.")

    ttk.Button(bt, text="Use this theme", style="Accent.TButton", command=use).pack(side="left")
    ttk.Button(bt, text="Save as…", command=save_as).pack(side="left", padx=8)
    ttk.Button(bt, text="Delete", command=delete).pack(side="left")
    ttk.Button(bt, text="Export…", command=export).pack(side="left", padx=(24, 8))
    ttk.Button(bt, text="Import…", command=import_).pack(side="left")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    fill_list(st["name"])
    paint()
    win._theme_state = (st, colors, hexvars)  # (the tests drive the editor through these)
