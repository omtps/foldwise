"""Smart disk cleaner and the other 'find and tidy' windows: duplicates, biggest files, organize, empty folders.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import ff_clean as CL
import ff_extras as X
import ff_platform
import os
import shutil
import threading
import ui_extras
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from ff_core import ThemedBox as messagebox
from tkinter import ttk
from ff_core import (T, fmt_date, human_size, log_error, recent_noise, recycle)


def open_cleaner(A):
    win = A.toplevel("Smart disk cleaner", "1240x800")
    alive = {"v": True, "tok": 0}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    drive = os.path.splitdrive(A.home)[0] + "\\"
    cats = {cid: dict(title=title, risk=risk, mode=mode, desc=desc, items=[], allowed=[], groups=[], done=False,
                      chk=set(), error=None) for cid, title, risk, mode, desc in CL.CATEGORIES}
    order = [c[0] for c in CL.CATEGORIES]
    sel_cat = {"id": order[0]}
    RISK = {"safe": ("Safe", "#4ade80"), "review": ("Review first", "#facc15"), "careful": ("Be careful", "#fb923c")}
    pool = ThreadPoolExecutor(3)

    # ---- header: how full the drive is
    hdr = tk.Frame(win, bg=T["bg"])
    hdr.pack(fill="x", padx=14, pady=(12, 4))
    disk_v = tk.StringVar()
    ttk.Label(hdr, textvariable=disk_v, font=("Segoe UI", A.cfg["font_size"] + 2, "bold")).pack(side="left")
    bar = ttk.Progressbar(hdr, maximum=100, length=300)
    bar.pack(side="left", padx=16)
    info_v = tk.StringVar(value="Scanning your drive for things you can safely clear…")
    ttk.Label(win, textvariable=info_v, padding=(14, 0, 14, 6)).pack(fill="x")

    def update_disk():
        try:
            u = shutil.disk_usage(drive)
            disk_v.set(f"{drive}   {human_size(u.free)} free of {human_size(u.total)}")
            bar.configure(value=round((u.total - u.free) * 100 / u.total))
        except OSError:
            disk_v.set(drive)

    # ---- left: categories, right: items
    body = tk.Frame(win, bg=T["bg"])
    body.pack(fill="both", expand=True, padx=10)
    lf = tk.Frame(body, bg=T["bg"], width=470)
    lf.pack(side="left", fill="y")
    lf.pack_propagate(False)
    tc = ttk.Treeview(lf, columns=("size", "risk"), show="tree headings", selectmode="browse", height=12)
    tc.heading("#0", text="What can be cleaned", anchor="w")
    tc.heading("size", text="Size", anchor="e")
    tc.heading("risk", text="Safety", anchor="w")
    tc.column("#0", width=250)
    tc.column("size", width=90, anchor="e")
    tc.column("risk", width=105)
    for rk, (label, col) in RISK.items():
        tc.tag_configure(rk, foreground=col)
    tc.pack(fill="x")
    desc_v = tk.StringVar()
    ttk.Label(lf, textvariable=desc_v, wraplength=450, justify="left", style="DetKey.TLabel", background=T["bg"],
              padding=(4, 12)).pack(fill="x")
    rf = tk.Frame(body, bg=T["bg"])
    rf.pack(side="left", fill="both", expand=True, padx=(12, 0))
    pvc = ui_extras.PreviewPane(rf, A, 270)
    ti = ttk.Treeview(rf, columns=("size", "modified", "note"), show="tree headings", selectmode="extended")
    for c, text, w, anc in (("#0", "Item", 400, "w"), ("size", "Size", 90, "e"), ("modified", "Modified", 130, "w"),
                            ("note", "Details", 260, "w")):
        ti.heading(c, text=text, anchor=anc)
        ti.column(c, width=w, anchor=anc)
    sbi = ttk.Scrollbar(rf, orient="vertical", command=ti.yview)
    ti.configure(yscrollcommand=sbi.set)
    sbi.pack(side="right", fill="y")
    ti.pack(fill="both", expand=True)
    pvc.watch(ti, lambda i: i if os.path.isabs(i) else None)

    BOX = {"all": "☑", "none": "☐", "some": "◪"}

    def cat_state(cid):
        c = cats[cid]
        if not c["items"] or not c["chk"]:
            return "none"
        return "all" if len(c["chk"]) >= len(c["items"]) else "some"

    def cat_size(cid):
        return sum(i[1] for i in cats[cid]["items"])

    def chk_size(cid):
        c = cats[cid]
        return sum(i[1] for i in c["items"] if i[0] in c["chk"])

    def refresh_left():
        for cid in order:
            c = cats[cid]
            label, _ = RISK[c["risk"]]
            text = f"{BOX[cat_state(cid)]}  {c['title']}"
            size = "scanning…" if not c["done"] else ((human_size(cat_size(cid)) if cat_size(cid) else f"{len(c['items']):,} item(s)") if c["items"] else "—")
            if tc.exists(cid):
                tc.item(cid, text=text, values=(size, label))
            else:
                tc.insert("", "end", iid=cid, text=text, values=(size, label), tags=(c["risk"],))
        tc.selection_set(sel_cat["id"])

    def refresh_right():
        c = cats[sel_cat["id"]]
        ti.delete(*ti.get_children())
        desc_v.set(c["desc"] + ("" if c["done"] else "\n\n" + (c.get("prog") or "Scanning\u2026")))
        for path, size, mtime, note in c["items"][:2000]:
            name = path if sel_cat["id"] in ("dups", "bin") else (os.path.basename(path.rstrip("\\")) or path)
            ti.insert("", "end", iid=path, text=f"{BOX['all'] if path in c['chk'] else BOX['none']}  {name}",
                      values=(human_size(size) if size else "", fmt_date(mtime) if mtime else "", note))
        if len(c["items"]) > 2000:
            ti.insert("", "end", iid="__more__", text=f"… and {len(c['items']) - 2000:,} smaller items (included in the totals)")

    def update_summary():
        perm = rec = 0
        n = 0
        for cid in order:
            c = cats[cid]
            s_ = chk_size(cid)
            n += len(c["chk"])
            if c["mode"] == "delete":
                perm += s_
            elif c["mode"] == "bin":
                perm += s_
            else:
                rec += s_
        total_found = sum(cat_size(cid) for cid in order if cats[cid]["done"])
        pend = sum(1 for cid in order if not cats[cid]["done"])
        info_v.set((f"Found {human_size(total_found)} you can clear" if total_found else "Nothing to clear yet")
                   + (f"   •   still scanning {pend} area(s)…" if pend else "")
                   + f"   •   ticked: {n:,} item(s) — {human_size(perm)} deleted for good, {human_size(rec)} sent to the Recycle Bin")
        clean_b.configure(state="normal" if n else "disabled")

    def on_cat_select(_=None):
        s = tc.selection()
        if s:
            sel_cat["id"] = s[0]
            refresh_right()
            dup_b.pack(side="left", padx=(8, 0)) if s[0] == "dups" else dup_b.pack_forget()

    def tick_cat(cid, on):
        c = cats[cid]
        c["chk"] = {i[0] for i in c["items"]} if on else set()
        refresh_left()
        if sel_cat["id"] == cid:
            refresh_right()
        update_summary()

    def click_cat(e):
        row = tc.identify_row(e.y)
        if row and e.x < 34:
            sel_cat["id"] = row
            tick_cat(row, cat_state(row) != "all")
            on_cat_select()
            return "break"

    def click_item(e):
        row = ti.identify_row(e.y)
        if row and row != "__more__" and e.x < 34 + 0:
            c = cats[sel_cat["id"]]
            c["chk"] ^= {row}
            ti.item(row, text=f"{BOX['all'] if row in c['chk'] else BOX['none']}  " + ti.item(row, "text")[3:])
            refresh_left()
            update_summary()
            return "break"

    def space_item(_=None):
        c = cats[sel_cat["id"]]
        for row in ti.selection():
            if row != "__more__":
                c["chk"] ^= {row}
                ti.item(row, text=f"{BOX['all'] if row in c['chk'] else BOX['none']}  " + ti.item(row, "text")[3:])
        refresh_left()
        update_summary()
        return "break"

    tc.bind("<<TreeviewSelect>>", on_cat_select)
    tc.bind("<Button-1>", click_cat)
    ti.bind("<Button-1>", click_item)
    ti.bind("<space>", space_item)

    def reveal_item():
        s = [r for r in ti.selection() if r != "__more__" and os.path.exists(r)]
        if s:
            A.navigate(os.path.dirname(s[0]), select=s[0])

    ti.bind("<Double-1>", lambda e: reveal_item())

    # ---- buttons
    btns = tk.Frame(win, bg=T["bg"])
    btns.pack(fill="x", padx=10, pady=(8, 12))
    clean_b = ttk.Button(btns, text="Clean ticked items…", style="Accent.TButton")
    clean_b.pack(side="left")
    ttk.Button(btns, text="Rescan", command=lambda: scan_all()).pack(side="left", padx=8)

    def edit_protected():
        from ui_picker import filedialog
        d = A.toplevel("Protected folders", "720x420")
        f_ = ttk.Frame(d, padding=18)
        f_.pack(fill="both", expand=True)
        ttk.Label(f_, text="The cleaner will never list or delete anything inside these folders.", wraplength=660).pack(anchor="w", pady=(0, 8))
        lb = tk.Listbox(f_, bg=T["panel"], fg=T["fg"], selectbackground=T["sel"], highlightthickness=0, borderwidth=0)
        lb.pack(fill="both", expand=True)
        for p_ in A.cfg["cleaner_protected"]:
            lb.insert("end", p_)

        def add_():
            p_ = filedialog.askdirectory(parent=d)
            if p_ and os.path.normpath(p_) not in lb.get(0, "end"):
                lb.insert("end", os.path.normpath(p_))
                A.save_cfg(cleaner_protected=list(lb.get(0, "end")))

        def rem_():
            for i_ in reversed(lb.curselection()):
                lb.delete(i_)
            A.save_cfg(cleaner_protected=list(lb.get(0, "end")))
        bt_ = ttk.Frame(f_)
        bt_.pack(fill="x", pady=(10, 0))
        ttk.Button(bt_, text="Add folder…", style="Accent.TButton", command=add_).pack(side="left")
        ttk.Button(bt_, text="Remove", command=rem_).pack(side="left", padx=8)
        ttk.Button(bt_, text="Done (rescan to apply)", command=d.destroy).pack(side="right")
    ttk.Button(btns, text="Protected folders…", command=edit_protected).pack(side="left")
    ttk.Button(btns, text="Auto-clean...", command=A.open_autoclean).pack(side="left", padx=8)
    ttk.Button(btns, text="Show in Foldwise", command=reveal_item).pack(side="left")
    dup_b = ttk.Button(btns, text="Review duplicates in detail…", command=lambda: A.open_duplicates("mine"))
    ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")

    # ---- scanning
    def set_prog(cid, m, tok):
        if alive["v"] and tok == alive["tok"] and not cats[cid]["done"]:
            cats[cid]["prog"] = m
            if sel_cat["id"] == cid:
                desc_v.set(cats[cid]["desc"] + "\n\n" + m)

    def scan_one(cid, tok):
        cancel = lambda: not alive["v"] or tok != alive["tok"]
        try:
            res = CL.apply_exclusions(CL.scan(cid, cancel, lambda m: A.root.after(0, set_prog, cid, m, tok)), A.cfg['cleaner_protected'])
        except Exception as e:  # noqa
            log_error(f"cleaner scan {cid}: {e}")
            res = {"items": [], "allowed": [], "error": str(e)}
        if res is not None and not cancel():
            A.root.after(0, scan_done, cid, res, tok)

    def scan_done(cid, res, tok):
        if not alive["v"] or tok != alive["tok"]:
            return
        c = cats[cid]
        c["items"], c["allowed"], c["groups"], c["error"] = res["items"], res.get("allowed", []), res.get("groups", []), res.get("error")
        c["done"] = True
        # safe things start ticked; anything that touches your own files starts unticked until you review it
        c["chk"] = {i[0] for i in c["items"]} if c["risk"] == "safe" else set()
        refresh_left()
        if sel_cat["id"] == cid:
            refresh_right()
        update_summary()

    def scan_all():
        alive["tok"] += 1
        tok = alive["tok"]
        for cid in order:
            cats[cid].update(items=[], allowed=[], groups=[], done=False, chk=set())
        update_disk()
        refresh_left()
        refresh_right()
        update_summary()
        for cid in order:
            pool.submit(scan_one, cid, tok)

    # ---- cleaning
    def do_clean():
        plan = {cid: [i for i in cats[cid]["items"] if i[0] in cats[cid]["chk"]] for cid in order if cats[cid]["chk"]}
        if not plan:
            return
        lines, danger = [], False
        for cid, items in plan.items():
            c = cats[cid]
            how = {"delete": "deleted for good", "bin": "Recycle Bin emptied for good", "recycle": "moved to the Recycle Bin (can be undone)"}[c["mode"]]
            danger |= c["mode"] in ("delete", "bin")
            lines.append(f"• {c['title']}: {len(items):,} item(s), {human_size(sum(i[1] for i in items))} — {how}")
        msg = "\n".join(lines) + ("\n\nItems marked “deleted for good” cannot be brought back." if danger else "") + "\n\nContinue?"
        if not messagebox.askyesno("Clean selected", msg, parent=win):
            return
        clean_b.configure(state="disabled")
        info_v.set("Cleaning… please wait")

        def work():
            freed, binned, failed, recycled = 0, 0, [], []
            for cid, items in plan.items():
                if not alive["v"]:
                    break
                c = cats[cid]
                if c["mode"] == "delete":
                    f_, bad = CL.delete_items(items, c["allowed"], protected=A.cfg["cleaner_protected"])
                    freed += f_
                    failed += bad
                elif c["mode"] == "bin":
                    if CL.empty_bin():
                        freed += sum(i[1] for i in items)
                else:
                    paths = [i[0] for i in items]
                    for k in range(0, len(paths), 80):
                        chunk = paths[k:k + 80]
                        recycle(chunk)
                        gone = [p for p in chunk if not os.path.lexists(p)]  # what really left, whatever the batch said
                        gset = set(gone)
                        recycled += gone
                        binned += sum(i[1] for i in items if i[0] in gset)
                        failed += [(p, "couldn't be recycled") for p in chunk if p not in gset]
            A.root.after(0, finished, freed, binned, failed, recycled)

        def finished(freed, binned, failed, recycled):
            if recycled:
                A.push_undo("delete", recycled)
            bad = {f[0] for f in failed}
            for cid, items in plan.items():
                c = cats[cid]
                gone = {i[0] for i in items if i[0] not in bad and not os.path.exists(i[0])} if c["mode"] != "bin" else {i[0] for i in items}
                c["items"] = [i for i in c["items"] if i[0] not in gone]
                c["chk"] -= gone
            if "bin" in cats:  # moving files to the Recycle Bin makes the bin bigger
                b = CL.scan_bin()
                cats["bin"]["items"] = b["items"]
                cats["bin"]["chk"] = set()
            if not alive["v"]:
                A.after_change()
                return
            update_disk()
            refresh_left()
            refresh_right()
            update_summary()
            A.after_change()
            text = f"Freed {human_size(freed)} for good." if freed else ""
            if binned:
                text += f"\nMoved {human_size(binned)} to the Recycle Bin — empty the Recycle Bin (tick it in the list) to free that space too. Ctrl+Z in Foldwise restores them."
            if failed:
                text += f"\n\n{len(failed)} item(s) were skipped (in use or protected), e.g. {os.path.basename(failed[0][0])}: {failed[0][1]}."
            A.status.set(f"Disk cleaner: freed {human_size(freed)}" + (f", {human_size(binned)} in the Recycle Bin" if binned else ""))
            messagebox.showinfo("Cleaning finished", text.strip() or "Nothing needed cleaning.", parent=win)

        threading.Thread(target=work, daemon=True).start()

    clean_b.configure(command=do_clean, state="disabled")
    refresh_left()
    refresh_right()
    update_disk()
    update_summary()
    scan_all()


def open_duplicates(A, scope="folder"):
    folder = A.st["cwd"]
    if X.zip_is_virtual(folder):
        folder = A.home
    win = A.toplevel("Duplicate files", "1100x700")
    alive = {"v": True, "tok": 0}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    scope_v, msg = tk.StringVar(value=scope), tk.StringVar(value="Scanning…")
    drive = os.path.splitdrive(folder)[0] + "\\"
    top = ttk.Frame(win, padding=(14, 10, 14, 0))
    top.pack(fill="x")
    ttk.Label(top, text="Look in:").pack(side="left", padx=(0, 10))
    for text, val in ((f"This folder ({os.path.basename(folder.rstrip(chr(92))) or folder})", "folder"),
                      ("My files (Documents, Desktop, Downloads, Pictures, Music, Videos)", "mine"),
                      (f"Whole drive ({drive})", "drive")):
        ttk.Radiobutton(top, text=text, value=val, variable=scope_v, command=lambda: scan()).pack(side="left", padx=(0, 16))
    row2 = ttk.Frame(win, padding=(14, 6, 14, 0))
    row2.pack(fill="x")
    ttk.Label(row2, text="Ignore files smaller than").pack(side="left")
    size_cb = ttk.Combobox(row2, values=["Any size", "100 KB", "1 MB", "10 MB"], state="readonly", width=10)
    size_cb.set("100 KB")
    size_cb.pack(side="left", padx=8)
    size_cb.bind("<<ComboboxSelected>>", lambda e: scan())
    ttk.Label(win, textvariable=msg, padding=(14, 8)).pack(fill="x")
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=10)
    pv2 = ui_extras.PreviewPane(frm, A)
    t2 = ttk.Treeview(frm, columns=("size", "modified", "note"), show="tree headings", selectmode="extended")
    for c, text, w, anc in (("#0", "Group / file", 600, "w"), ("size", "Size", 100, "e"),
                            ("modified", "Date modified", 150, "w"), ("note", "Suggestion", 170, "w")):
        t2.heading(c, text=text, anchor=anc)
        t2.column(c, width=w, anchor=anc)
    t2.tag_configure("grp", foreground=T["accent"])
    t2.tag_configure("keep", foreground="#4ade80")
    sb2 = ttk.Scrollbar(frm, orient="vertical", command=t2.yview)
    t2.configure(yscrollcommand=sb2.set)
    sb2.pack(side="right", fill="y")
    t2.pack(fill="both", expand=True)
    pv2.watch(t2, lambda i: t2.item(i, "text").replace("★  ", "", 1) if t2.parent(i) else None)

    def files_selected():
        return [i for i in t2.selection() if t2.parent(i)]

    def pick_extras():
        ids = []
        for g in t2.get_children():
            ids += t2.get_children(g)[1:]  # the first child is the best copy to keep
        t2.selection_set(ids)
        msg.set(msg.get().split("   •   selected")[0] + f"   •   selected {len(ids):,} extra copies")

    def trash():
        ids = files_selected()
        if not ids:
            return
        paths = [t2.item(i, "text").replace("★  ", "") for i in ids]
        if not messagebox.askyesno("Delete", f"Move {len(paths)} file(s) to the Recycle Bin?\n(Ctrl+Z in Foldwise brings them back.)", parent=win):
            return
        if recycle(paths):
            A.push_undo("delete", paths)
            for i in ids:
                g = t2.parent(i)
                t2.delete(i)
                if g and len(t2.get_children(g)) < 2:
                    t2.delete(g)
            A.after_change()
        else:
            messagebox.showerror("Foldwise", "Couldn't delete some of them (in use or access denied).", parent=win)

    def reveal():
        ids = files_selected()
        if ids:
            p = t2.item(ids[0], "text").replace("★  ", "")
            A.navigate(os.path.dirname(p), select=p)

    btns = tk.Frame(win, bg=T["bg"])
    btns.pack(fill="x", padx=10, pady=10)
    ttk.Button(btns, text="Select extra copies (keep the best one)", style="Accent.TButton", command=pick_extras).pack(side="left")
    ttk.Button(btns, text="Move selected to Recycle Bin", command=trash).pack(side="left", padx=8)
    ttk.Button(btns, text="Show in Foldwise", command=reveal).pack(side="left")
    ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")

    def scan():
        alive["tok"] += 1
        tok = alive["tok"]
        t2.delete(*t2.get_children())
        msg.set("Scanning…")
        sc = scope_v.get()
        roots = [folder] if sc == "folder" else ([d for d in CL.USER_DIRS if os.path.isdir(d)] if sc == "mine" else [drive])
        minsz = {"Any size": 1, "100 KB": 100 << 10, "1 MB": 1 << 20, "10 MB": 10 << 20}[size_cb.get()]

        def work():
            res = X.find_duplicates(roots, lambda: not alive["v"] or tok != alive["tok"],
                                    lambda m: alive["v"] and tok == alive["tok"] and A.root.after(0, lambda: alive["v"] and tok == alive["tok"] and msg.set(m)),
                                    min_size=minsz)
            if res is not None and A.cfg["cleaner_protected"]:
                res = [(s_, ps_) for s_, ps_ in ((s0, [p for p in p0 if not CL.is_protected(p, A.cfg["cleaner_protected"])]) for s0, p0 in res) if len(ps_) > 1]
            if res is not None and alive["v"] and tok == alive["tok"]:
                A.root.after(0, lambda: alive["v"] and tok == alive["tok"] and fill(res))
        threading.Thread(target=work, daemon=True).start()

    def fill(res):
        wasted = sum(s * (len(p) - 1) for s, p in res)
        msg.set(f"{len(res):,} groups of identical files   •   {human_size(wasted)} could be freed" if res
                else "No duplicate files found.")
        for size, paths in res[:2500]:
            k = CL.suggest_keep(paths)
            ordered = [paths[k]] + [p for i, p in enumerate(paths) if i != k]
            g = t2.insert("", "end", text=f"{len(paths)} identical files × {human_size(size)}",
                          values=(human_size(size * (len(paths) - 1)) + " wasted", "", ""), tags=("grp",), open=True)
            for n_, p in enumerate(ordered):
                try:
                    mt = fmt_date(os.path.getmtime(p))
                except OSError:
                    mt = ""
                t2.insert(g, "end", text=("★  " if n_ == 0 else "") + p, values=(human_size(size), mt,
                          "Keep — best location" if n_ == 0 else "Extra copy"), tags=("keep",) if n_ == 0 else ())

    scan()


def open_largest(A):
    folder = A.st["cwd"]
    if X.zip_is_virtual(folder):
        A.status.set("Can't scan inside an archive")
        return
    win = A.toplevel("Largest files", "1060x660")
    alive = {"v": True, "tok": 0}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    scope_v, msg = tk.StringVar(value="folder"), tk.StringVar(value="Scanning…")
    top = ttk.Frame(win, padding=(14, 10, 14, 4))
    top.pack(fill="x")
    ttk.Radiobutton(top, text=f"This folder ({os.path.basename(folder) or folder})", value="folder", variable=scope_v,
                    command=lambda: scan()).pack(side="left", padx=(0, 14))
    drive = os.path.splitdrive(folder)[0] + "\\"
    ttk.Radiobutton(top, text=f"Whole drive ({drive})", value="drive", variable=scope_v,
                    command=lambda: scan()).pack(side="left", padx=(0, 24))
    size_cb = ttk.Combobox(top, values=["Any size", "10 MB and up", "100 MB and up", "1 GB and up"], state="readonly", width=14)
    size_cb.set("10 MB and up")
    size_cb.pack(side="left", padx=(0, 8))
    age_cb = ttk.Combobox(top, values=["Any age", "Not modified for 1 month", "Not modified for 6 months",
                                        "Not modified for 1 year"], state="readonly", width=24)
    age_cb.set("Any age")
    age_cb.pack(side="left")
    ttk.Label(win, textvariable=msg, padding=(14, 4)).pack(fill="x")
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=10)
    pv4 = ui_extras.PreviewPane(frm, A)
    t4 = ttk.Treeview(frm, columns=("size", "modified", "folder"), show="tree headings", selectmode="extended")
    for c, text, w, anc in (("#0", "File", 300, "w"), ("size", "Size", 100, "e"), ("modified", "Modified", 150, "w"),
                            ("folder", "Folder", 430, "w")):
        t4.heading(c, text=text, anchor=anc)
        t4.column(c, width=w, anchor=anc)
    sb4 = ttk.Scrollbar(frm, orient="vertical", command=t4.yview)
    t4.configure(yscrollcommand=sb4.set)
    sb4.pack(side="right", fill="y")
    t4.pack(fill="both", expand=True)
    pv4.watch(t4, lambda i: os.path.join(t4.set(i, "folder"), t4.item(i, "text")))
    data = {"rows": []}

    def fill(_=None):
        minsz = {"Any size": 0, "10 MB and up": 10 << 20, "100 MB and up": 100 << 20, "1 GB and up": 1 << 30}[size_cb.get()]
        days = {"Any age": 0, "Not modified for 1 month": 30, "Not modified for 6 months": 182,
                "Not modified for 1 year": 365}[age_cb.get()]
        cutoff = time.time() - days * 86400
        t4.delete(*t4.get_children())
        shown, total = 0, 0
        for size, path, mtime in data["rows"]:
            if size < minsz or (days and mtime > cutoff):
                continue
            shown += 1
            total += size
            if shown <= 600:
                t4.insert("", "end", iid=path, text=os.path.basename(path),
                          values=(human_size(size), fmt_date(mtime), os.path.dirname(path)))
        msg.set(f"{shown:,} files match   •   {human_size(total)} in total" + ("   •   showing the biggest 600" if shown > 600 else ""))

    size_cb.bind("<<ComboboxSelected>>", fill)
    age_cb.bind("<<ComboboxSelected>>", fill)

    def scan():
        alive["tok"] += 1
        tok = alive["tok"]
        data["rows"] = []
        t4.delete(*t4.get_children())
        msg.set("Scanning…")
        where = folder if scope_v.get() == "folder" else drive

        def work():
            res = X.largest_files(where, 2000, lambda: not alive["v"] or tok != alive["tok"],
                                  lambda m: alive["v"] and tok == alive["tok"] and A.root.after(0, lambda: alive["v"] and tok == alive["tok"] and msg.set(m)))
            if res is not None and A.cfg["cleaner_protected"]:
                res = [r for r in res if not CL.is_protected(r[1], A.cfg["cleaner_protected"])]
            if res is not None and alive["v"] and tok == alive["tok"]:
                A.root.after(0, lambda: alive["v"] and tok == alive["tok"] and (data.update(rows=res), fill()))
        threading.Thread(target=work, daemon=True).start()

    def chosen():
        return list(t4.selection())

    def trash():
        paths = chosen()
        if not paths:
            return
        total = sum(os.path.getsize(p) for p in paths if os.path.exists(p))
        if not messagebox.askyesno("Delete", f"Move {len(paths)} file(s) ({human_size(total)}) to the Recycle Bin?", parent=win):
            return
        if recycle(paths):
            A.push_undo("delete", paths)
            data["rows"] = [r for r in data["rows"] if r[1] not in set(paths)]
            fill()
            A.after_change()
        else:
            messagebox.showerror("Foldwise", "Couldn't delete some of them (in use or access denied).", parent=win)

    def reveal():
        c = chosen()
        if c:
            A.navigate(os.path.dirname(c[0]), select=c[0])

    def open_file():
        c = chosen()
        if c:
            try:
                ff_platform.open_path(c[0])
            except OSError as e:
                messagebox.showerror("Foldwise", str(e), parent=win)

    btns = tk.Frame(win, bg=T["bg"])
    btns.pack(fill="x", padx=10, pady=10)
    ttk.Button(btns, text="Move selected to Recycle Bin", command=trash).pack(side="left")
    ttk.Button(btns, text="Show in Foldwise", command=reveal).pack(side="left", padx=8)
    ttk.Button(btns, text="Open", command=open_file).pack(side="left")
    ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")
    t4.bind("<Double-1>", lambda e: open_file())
    scan()


def open_organize(A):
    folder = A.st["cwd"]
    if X.zip_is_virtual(folder) or recent_noise(folder):
        messagebox.showinfo("Organize", "I won't reorganize a system folder, a drive root or an archive.\n"
                            "Open a normal folder (like Downloads) first.", parent=A.root)
        return
    win = A.toplevel(f"Organize {os.path.basename(folder) or folder}", "880x640")
    mode, info_v = tk.StringVar(value="type"), tk.StringVar()
    items, inc = {"all": []}, {}
    top = ttk.Frame(win, padding=(14, 12, 14, 4))
    top.pack(fill="x")
    ttk.Label(top, text="Sort the loose files in this folder into sub-folders. Nothing is deleted, and you can undo it with Ctrl+Z.").pack(anchor="w")
    row = ttk.Frame(top)
    row.pack(anchor="w", pady=8)
    ttk.Radiobutton(row, text="By type  (Images, Documents, Videos…)", value="type", variable=mode,
                    command=lambda: load()).pack(side="left", padx=(0, 18))
    ttk.Radiobutton(row, text="By month modified  (2026-10, 2026-09…)", value="date", variable=mode,
                    command=lambda: load()).pack(side="left")
    cats = tk.Frame(win, bg=T["bg"])
    cats.pack(fill="x", padx=14)
    ttk.Label(win, textvariable=info_v, padding=(14, 6)).pack(fill="x")
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=10)
    tv = ttk.Treeview(frm, columns=("to", "size"), show="tree headings")
    for c, text, w, anc in (("#0", "File", 380, "w"), ("to", "Goes into folder", 220, "w"), ("size", "Size", 90, "e")):
        tv.heading(c, text=text, anchor=anc)
        tv.column(c, width=w, anchor=anc)
    sbv = ttk.Scrollbar(frm, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sbv.set)
    sbv.pack(side="right", fill="y")
    tv.pack(fill="both", expand=True)

    def picked():
        return [it for it in items["all"] if inc.get(it[2], tk.BooleanVar(value=True)).get()]

    def render(*_):
        tv.delete(*tv.get_children())
        sel_ = picked()
        for name, path, cat, size in sel_[:800]:
            tv.insert("", "end", text=name, values=("→ " + cat, human_size(size)))
        folders = {it[2] for it in sel_}
        info_v.set(f"{len(sel_):,} files will move into {len(folders)} sub-folder(s)" + ("   •   showing the first 800" if len(sel_) > 800 else "")
                   if sel_ else "Nothing to organize here (only loose files are moved; sub-folders are left alone)")

    def load():
        try:
            items["all"] = [r for r in X.plan_organize(folder, mode.get()) if not CL.is_protected(r[1], A.cfg["cleaner_protected"])]
        except OSError as e:
            info_v.set(f"Can't read this folder: {e}")
            return
        for w in cats.winfo_children():
            w.destroy()
        counts = {}
        for it in items["all"]:
            counts[it[2]] = counts.get(it[2], 0) + 1
        if mode.get() == "type":  # tick boxes to leave a whole category where it is
            for c in sorted(counts):
                v = inc.setdefault(c, tk.BooleanVar(value=True))
                ttk.Checkbutton(cats, text=f"{c} ({counts[c]})", variable=v, command=render).pack(side="left", padx=(0, 12))
        else:
            inc.clear()
        render()

    def apply():
        chosen_ = picked()
        if not chosen_:
            return
        n_f = len({it[2] for it in chosen_})
        if not messagebox.askyesno("Organize", f"Move {len(chosen_):,} files into {n_f} sub-folder(s) of\n{folder}?\n\nCtrl+Z undoes it.",
                                   parent=win):
            return
        info_v.set("Moving…")

        def work():
            pairs, created = X.apply_organize(folder, chosen_)
            A.root.after(0, done, pairs, created)

        def done(pairs, created):
            if pairs:
                A.push_undo("organize", (pairs, created))
            try:
                win.destroy()
            except tk.TclError:
                pass
            A.status.set(f"Organized {len(pairs):,} files into {len(created) or n_f} folder(s)   •   Ctrl+Z to undo")
            A.after_change()

        threading.Thread(target=work, daemon=True).start()

    btns = tk.Frame(win, bg=T["bg"])
    btns.pack(fill="x", padx=10, pady=10)
    ttk.Button(btns, text="Organize", style="Accent.TButton", command=apply).pack(side="left")
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=8)
    load()
