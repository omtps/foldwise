"""Keyboard shortcuts in the interface: binds the global keys from the table in ff_keys (with your changes) and the Tools > Keyboard shortcuts editor.

Every function takes `A` first (ff_app.App).
"""
import tkinter as tk
from tkinter import ttk

import ff_keys as K
from ff_core import T, ThemedBox as messagebox


def install(A, handlers):
    """(Re)bind every global shortcut: `handlers` maps an action id (see ff_keys.ACTIONS) to a function taking the Tk event."""
    for seq in A.st.get("keymap", {}).values():
        A.root.unbind(K.to_tk(seq))
    keymap = {}
    for aid, seq in K.effective(A.cfg.get("keys")).items():
        if seq and aid in handlers:
            A.root.bind(K.to_tk(seq), lambda e, h=handlers[aid]: h(e))
            keymap[aid] = seq
    A.st["keymap"], A.st["keyhandlers"] = keymap, handlers


def set_key(A, aid, seq):
    """Give an action a new shortcut ('' switches it off); stored only when it differs from the default."""
    keys = dict(A.cfg.get("keys") or {})
    if seq == K.DEFAULTS[aid]:
        keys.pop(aid, None)
    else:
        keys[aid] = seq
    A.save_cfg(keys=keys)
    install(A, A.st["keyhandlers"])


def capture(A, parent, aid, on_done):
    """A small window that waits for the key combination you press; calls on_done(shortcut) when you save."""
    d = tk.Toplevel(A.root)
    d.title("New shortcut")
    d.configure(bg=T["bg"])
    d.transient(A.root)
    d.attributes("-topmost", True)
    f = ttk.Frame(d, padding=22)
    f.pack()
    ttk.Label(f, text=f"Press the keys you want for “{K.label(aid)}”", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    shown = tk.StringVar(value="…")
    tk.Label(f, textvariable=shown, bg=T["raised"], fg=T["accent"], font=("Segoe UI", 18, "bold"), width=22, pady=14).pack(pady=12)
    msg = tk.StringVar(value="Hold Ctrl, Alt or Shift and press a key. Esc cancels.")
    ttk.Label(f, textvariable=msg, wraplength=380, style="DetKey.TLabel", background=T["bg"]).pack(anchor="w")
    row = ttk.Frame(f)
    row.pack(anchor="e", pady=(12, 0))
    save = ttk.Button(row, text="Save", style="Accent.TButton", state="disabled")
    ttk.Button(row, text="Cancel", command=d.destroy).pack(side="left", padx=6)
    save.pack(side="left")
    got = {"seq": None}

    def on_key(e):
        if e.keysym == "Escape":
            d.destroy()
            return "break"
        seq = K.from_event(e.keysym, e.state)
        if seq is None:
            return "break"
        shown.set(seq)
        problem = K.check(seq)
        owner = next((k for k, v in K.effective(A.cfg.get("keys")).items() if v == seq and k != aid), None)
        got["seq"] = None if problem else seq
        msg.set(problem or (f"{seq} is used for “{K.label(owner)}” now; saving moves it here and switches that one off." if owner else "Free: nothing else uses it."))
        save.configure(state="disabled" if problem else "normal")
        return "break"

    def do_save():
        seq = got["seq"]
        d.destroy()
        on_done(seq)
    save.configure(command=do_save)
    d.bind("<KeyPress>", on_key)
    d.update_idletasks()
    d.geometry(f"+{A.root.winfo_rootx() + 140}+{A.root.winfo_rooty() + 120}")
    d.grab_set()
    d.focus_force()
    d._capture = (on_key, do_save, shown)  # (the tests drive the window through these)
    A.st["keycapture"] = d


def open_keys(A):
    win = A.toplevel("Keyboard shortcuts", "900x720")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    ttk.Label(win, text="Pick an action and press Change… to give it another key combination. Changes work at once. "
              "Copy, cut, paste, Esc and the file-list keys (Enter, Delete, F2 …) are fixed.", wraplength=820, padding=(18, 14, 18, 6)).pack(fill="x")
    top = ttk.Frame(win, padding=(18, 0, 18, 6))
    top.pack(fill="x")
    ttk.Label(top, text="Find an action").pack(side="left")
    q = tk.StringVar()
    ttk.Entry(top, textvariable=q, width=30).pack(side="left", padx=8)
    msg = tk.StringVar()
    bt = ttk.Frame(win, padding=(14, 10))
    bt.pack(side="bottom", fill="x")
    ttk.Label(win, textvariable=msg, wraplength=820, padding=(18, 0, 18, 4)).pack(side="bottom", fill="x")
    box = ttk.Frame(win, padding=(18, 0, 18, 0))
    box.pack(fill="both", expand=True)
    tv = ttk.Treeview(box, columns=("keys", "default"), show="tree headings", selectmode="browse")
    for c, text, w, anc in (("#0", "Action", 360, "w"), ("keys", "Shortcut", 200, "w"), ("default", "Default", 200, "w")):
        tv.heading(c, text=text, anchor=anc)
        tv.column(c, width=w, anchor=anc, stretch=(c == "#0"))
    tv.tag_configure("changed", foreground=T["accent"])
    tv.tag_configure("clash", foreground="#f87171")
    tv.pack(side="left", fill="both", expand=True)

    def refresh(*_):
        if not alive["v"]:
            return
        eff, clash, want = K.effective(A.cfg.get("keys")), K.conflicts(K.effective(A.cfg.get("keys"))), q.get().strip().lower()
        sel = tv.selection()
        tv.delete(*tv.get_children())
        groups = {}
        for aid, group, what, default in K.ACTIONS:
            if want and want not in what.lower() and want not in (eff[aid] or "").lower():
                continue
            if group not in groups:
                groups[group] = tv.insert("", "end", text=group.upper(), open=True)
            seq = eff[aid]
            tags = ("clash",) if seq in clash else ("changed",) if seq != default else ()
            tv.insert(groups[group], "end", iid=aid, text="   " + what, values=(seq or "(off)", default), tags=tags)
        if sel and tv.exists(sel[0]):
            tv.selection_set(sel[0])
        nclash = sum(len(v) for v in clash.values())
        msg.set(f"{nclash} actions share a key (shown in red): only the last one will work." if clash else "")
    q.trace_add("write", refresh)

    def current():
        s = tv.selection()
        return s[0] if s and s[0] in K.DEFAULTS else None

    def change():
        aid = current()
        if aid is None:
            msg.set("Pick an action first.")
            return

        def done(seq):
            for other, v in K.effective(A.cfg.get("keys")).items():
                if v == seq and other != aid:
                    set_key(A, other, "")
            set_key(A, aid, seq)
            refresh()
        capture(A, win, aid, done)

    def reset():
        aid = current()
        if aid:
            set_key(A, aid, K.DEFAULTS[aid])
            refresh()

    def off():
        aid = current()
        if aid:
            set_key(A, aid, "")
            refresh()

    def reset_all():
        if A.cfg.get("keys") and messagebox.askyesno("Keyboard shortcuts", "Put every shortcut back to its default?", parent=A.root):
            A.save_cfg(keys={})
            install(A, A.st["keyhandlers"])
            refresh()
    tv.bind("<Double-1>", lambda e: change())
    ttk.Button(bt, text="Change…", style="Accent.TButton", command=change).pack(side="left")
    ttk.Button(bt, text="Switch off", command=off).pack(side="left", padx=8)
    ttk.Button(bt, text="Reset this one", command=reset).pack(side="left")
    ttk.Button(bt, text="Reset all", command=reset_all).pack(side="left", padx=8)
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    refresh()
