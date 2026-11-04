"""Tools > Automatic rules: sort files by themselves when they turn up in a folder (see ff_rules). Off until switched on; never deletes.

Every function takes `A` first (ff_app.App).
"""
import os
import threading
import time
import tkinter as tk
from tkinter import ttk

import ff_extras as X
import ff_rules as RU
from ff_core import T, ThemedBox as messagebox
from ui_picker import filedialog

_S = {"timer": None, "log": [], "last_toast": 0.0}
INTERVAL = 60  # seconds between automatic checks


def log(text=""):
    """Add a line to the activity list (no text: just redraw it)."""
    if text:
        _S["log"] = (_S["log"] + [f"{time.strftime('%H:%M:%S')}  {text}"])[-150:]
    w = _S.get("logw")
    try:
        if w is not None and w.winfo_exists():
            w.configure(state="normal")
            w.delete("1.0", "end")
            w.insert("end", chr(10).join(_S["log"]))
            w.see("end")
            w.configure(state="disabled")
    except tk.TclError:
        pass


def presets():
    home = os.path.expanduser("~")
    dl, pics, docs = (os.path.join(home, n) for n in ("Downloads", "Pictures", "Documents"))
    return [
        ("Pictures from Downloads \u2192 Pictures\\From Downloads", RU.new_rule(name="Pictures from Downloads", folder=dl, groups=["Images"], action="move", dest=os.path.join(pics, "From Downloads"))),
        ("Documents from Downloads \u2192 Documents\\Downloads\\year", RU.new_rule(name="Documents from Downloads", folder=dl, groups=["Documents"], action="move", dest=os.path.join(docs, "From Downloads", "{year}"))),
        ("Old installers (30+ days) \u2192 Downloads\\Old installers", RU.new_rule(name="Old installers", folder=dl, groups=["Installers"], older_days=30, action="move", dest=os.path.join(dl, "Old installers"))),
        ("Screenshots on the Desktop \u2192 Pictures\\Screenshots", RU.new_rule(name="Screenshots", folder=os.path.join(home, "Desktop"), name_like="screenshot", action="move", dest=os.path.join(pics, "Screenshots"))),
    ]


# ------------------------------------------------------------------------------------------------ running
def run_now(A, dry=False, then=None):
    """Apply (or only list) what the rules would do; the work runs in a thread, the result is shown in the activity list."""
    rules = [dict(r) for r in A.cfg.get("rules", [])]
    prot = list(A.cfg.get("cleaner_protected", []))

    def work():
        try:
            moved, res = RU.run(rules, prot, A.tags_store, dry=dry)
        except Exception as e:  # noqa - a rule problem must never disturb the program
            moved, res = [], [({"name": ""}, "failed", f"Rules stopped: {e}")]
        A.root.after(0, lambda: done(moved, res))

    def done(moved, res):
        if moved:
            A.push_undo("move", moved)  # Ctrl+Z puts them back
        for _item, st, msg in res:
            log(("Would: " if st == "planned" else "Failed: " if st == "failed" else "") + msg)
        n_ok = sum(1 for r in res if r[1] == "done")
        if dry:
            log(f"Preview: {len(res)} action(s) would happen right now." if res else "Preview: nothing matches right now.")
        elif n_ok:
            A.refresh()
            if time.time() - _S["last_toast"] > 300 and not dry:
                _S["last_toast"] = time.time()
                A.show_toast(f"Your rules handled {n_ok} file{'s' if n_ok != 1 else ''} (Ctrl+Z undoes moves).", "Show", lambda: A.open_rules(), title="Pinefiles \u00b7 Automatic rules")
        if then:
            then(res)
    threading.Thread(target=work, daemon=True).start()


def tick(A):
    _S["timer"] = None
    if not A.cfg.get("rules_on"):
        return
    if not A.st.get("xfer"):
        run_now(A)
    arm(A)


def arm(A):
    if _S["timer"] is None and A.cfg.get("rules_on"):
        _S["timer"] = A.root.after(INTERVAL * 1000, lambda: tick(A))


def autostart(A):
    arm(A)


# ------------------------------------------------------------------------------------------------ the tool
def open_rules(A):
    win = A.toplevel("Automatic rules", "960x720")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    bt = ttk.Frame(win, padding=(14, 8))
    bt.pack(side="bottom", fill="x")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    ttk.Button(bt, text="Tutorial", command=lambda: A.open_howto("rules")).pack(side="right", padx=8)
    logw = tk.Text(win, height=8, width=10, bg=T["panel"], fg=T["fg"], relief="flat", wrap="word", font=("Consolas", 9), padx=10, pady=8, state="disabled")
    logw.pack(side="bottom", fill="x", padx=16, pady=(0, 6))
    _S["logw"] = logw
    ttk.Label(win, text="ACTIVITY", style="DetHead.TLabel", background=T["bg"]).pack(side="bottom", anchor="w", padx=18)
    log()
    top = ttk.Frame(win, padding=(18, 14, 18, 4))
    top.pack(fill="x")
    ttk.Label(top, text="Automatic rules", font=("Segoe UI", 15, "bold")).pack(anchor="w")
    ex = ttk.Label(top, text="Tell Pinefiles what to do with files that turn up in a folder, for example “pictures in Downloads go to Pictures”. "
                   "Rules never delete anything, never overwrite a file, only look at files directly in the folder, and wait until a file has been untouched for a few minutes "
                   "(so unfinished downloads are left alone). Moves can be undone with Ctrl+Z.", wraplength=800, style="DetKey.TLabel", background=T["bg"])
    ex.pack(anchor="w", pady=(2, 8))
    top.bind("<Configure>", lambda e: ex.configure(wraplength=max(260, e.width - 40)))
    on = tk.BooleanVar(value=bool(A.cfg.get("rules_on")))

    def toggle_on():
        if on.get():
            active = [r for r in A.cfg.get("rules", []) if r.get("enabled", True)]
            if not active:
                messagebox.showinfo("Automatic rules", "Add a rule first.", parent=A.root)
                on.set(False)
                return
            ok = messagebox.askyesno("Switch the rules on?", f"{len(active)} rule(s) will run about once a minute while Pinefiles is open and move, copy, rename or tag files "
                                     "that match. Nothing is ever deleted. Use “Preview now” first to see what would happen.\n\nSwitch them on?", parent=A.root)
            if not ok:
                on.set(False)
                return
        A.save_cfg(rules_on=on.get())
        log("Rules are on: checked once a minute" if on.get() else "Rules are off")
        arm(A)
    ttk.Checkbutton(top, text="Run my rules automatically while Pinefiles is open", variable=on, command=toggle_on).pack(anchor="w")

    mid = ttk.Frame(win, padding=(18, 6, 18, 0))
    mid.pack(fill="both", expand=True)
    tv = ttk.Treeview(mid, columns=("on", "folder", "what", "does"), show="tree headings", selectmode="browse", height=7)
    for c, text, w, anc in (("#0", "Rule", 190, "w"), ("on", "On", 40, "center"), ("folder", "Watches", 200, "w"), ("what", "Files", 150, "w"), ("does", "Does", 230, "w")):
        tv.heading(c, text=text, anchor=anc)
        tv.column(c, width=w, anchor=anc, stretch=(c in ("#0", "does")))
    tv.pack(fill="both", expand=True)

    def what(r):
        bits = list(r.get("groups") or []) + [x for x in (r.get("exts") or [])]
        if r.get("name_like"):
            bits.append(f"“{r['name_like']}”")
        if r.get("older_days"):
            bits.append(f"older than {r['older_days']} d")
        return ", ".join(bits)

    def does(r):
        a = r.get("action")
        if a in ("move", "copy"):
            return ("Move to " if a == "move" else "Copy to ") + (r.get("dest") or "?")
        return {"rename": f"Rename to {r.get('pattern')}", "tag": f"Tag “{r.get('tag')}”", "label": f"Label {r.get('label')}"}.get(a, "?")

    def refresh_list():
        if not alive["v"]:
            return
        keep = tv.selection()
        tv.delete(*tv.get_children())
        for i, r in enumerate(A.cfg.get("rules", [])):
            tv.insert("", "end", iid=str(i), text=r.get("name", "?"), values=("\u2714" if r.get("enabled", True) else "\u2013", r.get("folder", ""), what(r), does(r)))
        if keep and tv.exists(keep[0]):
            tv.selection_set(keep[0])

    def save_rules(rules):
        A.save_cfg(rules=rules)
        refresh_list()

    def selected():
        s = tv.selection()
        return int(s[0]) if s else None

    def edit(idx=None, preset=None):
        rules = [dict(r) for r in A.cfg.get("rules", [])]
        r = dict(preset) if preset else (dict(rules[idx]) if idx is not None else RU.new_rule(folder=os.path.join(os.path.expanduser("~"), "Downloads")))
        editor(A, win, r, lambda res: (rules.__setitem__(idx, res) if idx is not None else rules.append(res), save_rules(rules)))

    def delete():
        i = selected()
        if i is None:
            return
        rules = list(A.cfg.get("rules", []))
        if messagebox.askyesno("Delete rule", f"Delete the rule “{rules[i].get('name')}”? (Files it already moved stay where they are.)", parent=A.root):
            rules.pop(i)
            save_rules(rules)
            if not rules:
                on.set(False)
                A.save_cfg(rules_on=False)

    def flip():
        i = selected()
        if i is None:
            return
        rules = [dict(r) for r in A.cfg.get("rules", [])]
        rules[i]["enabled"] = not rules[i].get("enabled", True)
        save_rules(rules)

    row = ttk.Frame(mid)
    row.pack(fill="x", pady=6)
    ttk.Button(row, text="Add rule…", style="Accent.TButton", command=lambda: edit()).pack(side="left")
    pm = ttk.Menubutton(row, text="Ready-made rule")
    menu = tk.Menu(pm, tearoff=0)
    for label, rule in presets():
        menu.add_command(label=label, command=lambda rule=rule: edit(preset=rule))
    pm["menu"] = menu
    pm.pack(side="left", padx=8)
    ttk.Button(row, text="Edit…", command=lambda: selected() is not None and edit(selected())).pack(side="left")
    ttk.Button(row, text="Turn on / off", command=flip).pack(side="left", padx=8)
    ttk.Button(row, text="Delete", command=delete).pack(side="left")
    row2 = ttk.Frame(mid)
    row2.pack(fill="x", pady=(0, 6))
    ttk.Button(row2, text="Preview now (changes nothing)", command=lambda: run_now(A, dry=True)).pack(side="left")
    ttk.Button(row2, text="Run the rules now", command=lambda: run_now(A)).pack(side="left", padx=8)
    refresh_list()


def editor(A, parent, rule, on_save):
    d = tk.Toplevel(A.root)
    d.title("Rule")
    d.configure(bg=T["bg"])
    d.transient(A.root)
    f = ttk.Frame(d, padding=18)
    f.pack(fill="both", expand=True)
    v = {k: tk.StringVar(value=str(rule.get(k, ""))) for k in ("name", "folder", "name_like", "min_age_min", "older_days", "min_mb", "dest", "pattern", "tag")}
    v["exts"] = tk.StringVar(value=", ".join(rule.get("exts") or []))
    v["action"] = tk.StringVar(value={"move": "Move to a folder", "copy": "Copy to a folder", "rename": "Rename", "tag": "Add a tag", "label": "Colour label"}.get(rule.get("action"), "Move to a folder"))
    v["label"] = tk.StringVar(value=rule.get("label") or "blue")
    groups = {g: tk.BooleanVar(value=g in (rule.get("groups") or [])) for g in RU.GROUPS}
    r = [0]

    def line(label, widget_fn, hint=None):
        ttk.Label(f, text=label).grid(row=r[0], column=0, sticky="nw", pady=4, padx=(0, 10))
        w = widget_fn(f)
        w.grid(row=r[0], column=1, sticky="ew", pady=4)
        r[0] += 1
        if hint:
            ttk.Label(f, text=hint, style="DetKey.TLabel", background=T["bg"], wraplength=420).grid(row=r[0], column=1, sticky="w")
            r[0] += 1
        return w
    f.columnconfigure(1, weight=1)
    line("Name", lambda p: ttk.Entry(p, textvariable=v["name"], width=40))

    def folder_row(var, title):
        def make(p):
            fr = ttk.Frame(p)
            ttk.Entry(fr, textvariable=var).pack(side="left", fill="x", expand=True)
            ttk.Button(fr, text="Choose…", command=lambda: var.set(filedialog.askdirectory(parent=d, title=title, initialdir=var.get() if os.path.isdir(var.get().split("{")[0] or ".") else "") or var.get())).pack(side="left", padx=6)
            return fr
        return make
    line("Watch this folder", folder_row(v["folder"], "Folder to watch"))

    def types(p):
        fr = ttk.Frame(p)
        for i, g in enumerate(RU.GROUPS):
            ttk.Checkbutton(fr, text=g, variable=groups[g]).grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 12))
        return fr
    line("File types", types)
    line("Other extensions", lambda p: ttk.Entry(p, textvariable=v["exts"], width=30), "Comma separated, without the dot, e.g. dwg, psd")
    line("Name contains", lambda p: ttk.Entry(p, textvariable=v["name_like"], width=30), "For example “invoice” or “screenshot” (or a pattern like IMG_*)")
    line("Untouched for (minutes)", lambda p: ttk.Spinbox(p, from_=1, to=1440, textvariable=v["min_age_min"], width=6), "A file must rest this long first, so unfinished downloads are left alone")
    line("Older than (days)", lambda p: ttk.Spinbox(p, from_=0, to=3650, textvariable=v["older_days"], width=6), "0 = any age")
    line("Bigger than (MB)", lambda p: ttk.Spinbox(p, from_=0, to=100000, textvariable=v["min_mb"], width=6), "0 = any size")
    line("Then", lambda p: ttk.Combobox(p, textvariable=v["action"], state="readonly", width=24, values=["Move to a folder", "Copy to a folder", "Rename", "Add a tag", "Colour label"]))
    dest = line("Destination folder", folder_row(v["dest"], "Where should the files go?"), "Placeholders: {year} {month} {day} {type} {ext} {name} (from the file's date and kind), e.g. D:\\Sorted\\{year}\\{type}")
    pat = line("New name", lambda p: ttk.Entry(p, textvariable=v["pattern"], width=40), "e.g. {date} {name}{ext}")
    tag = line("Tag", lambda p: ttk.Entry(p, textvariable=v["tag"], width=24))
    lab = line("Colour", lambda p: ttk.Combobox(p, textvariable=v["label"], state="readonly", width=12, values=["red", "orange", "yellow", "green", "blue", "purple", "gray"]))
    en = tk.BooleanVar(value=rule.get("enabled", True))
    ttk.Checkbutton(f, text="This rule is on", variable=en).grid(row=r[0], column=1, sticky="w", pady=6)
    r[0] += 1
    msg = tk.StringVar()
    ttk.Label(f, textvariable=msg, foreground="#f87171", wraplength=480).grid(row=r[0], column=0, columnspan=2, sticky="w")
    r[0] += 1

    def build():
        a = {"Move to a folder": "move", "Copy to a folder": "copy", "Rename": "rename", "Add a tag": "tag", "Colour label": "label"}[v["action"].get()]
        try:
            rr = dict(rule, name=v["name"].get().strip() or "Rule", folder=v["folder"].get().strip(), name_like=v["name_like"].get().strip(),
                      min_age_min=max(1, int(v["min_age_min"].get() or 5)), older_days=max(0, int(v["older_days"].get() or 0)), min_mb=max(0, float(v["min_mb"].get() or 0)),
                      exts=[x.strip().lower().lstrip(".") for x in v["exts"].get().replace(";", ",").split(",") if x.strip()], groups=[g for g, b in groups.items() if b.get()],
                      action=a, dest=v["dest"].get().strip(), pattern=v["pattern"].get().strip() or "{name}{ext}", tag=v["tag"].get().strip(), label=v["label"].get(), enabled=en.get())
        except ValueError:
            return None, ["The minutes, days and size must be numbers."]
        return rr, RU.check_rule(rr)

    def save():
        rr, problems = build()
        if problems:
            msg.set(" ".join(problems))
            return
        d.destroy()
        on_save(rr)
    bt = ttk.Frame(f)
    bt.grid(row=r[0], column=0, columnspan=2, sticky="e", pady=(10, 0))
    ttk.Button(bt, text="Cancel", command=d.destroy).pack(side="left", padx=6)
    ttk.Button(bt, text="Save", style="Accent.TButton", command=save).pack(side="left")

    def show_fields(*_):
        a = v["action"].get()
        for w, shown in ((dest, a in ("Move to a folder", "Copy to a folder")), (pat, a == "Rename"), (tag, a == "Add a tag"), (lab, a == "Colour label")):
            (w.grid if shown else w.grid_remove)()
    v["action"].trace_add("write", show_fields)
    d.update_idletasks()
    show_fields()
    d.geometry(f"+{A.root.winfo_rootx() + 90}+{A.root.winfo_rooty() + 50}")
    d.attributes("-topmost", True)
    d.grab_set()
    d._rule_vars = (v, groups, en)  # (the tests drive the editor through these)
    _S["editor"] = d
