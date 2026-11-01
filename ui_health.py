"""PC health center, tune-up, auto-clean, background health/backup/threat watchers and toasts.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import ff_clean as CL
import ff_elevated
import ff_health as HL
import ff_platform
import os
import subprocess
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from ff_core import ThemedBox as messagebox
from tkinter import ttk
from ff_core import (Path, T, fmt_date, human_size, log_error)


def open_health(A, tab=None):
    win = A.toplevel("PC health", "1200x820")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    pool_h = ThreadPoolExecutor(4)
    fs = A.cfg["font_size"]
    GOOD, WARN, BAD = "#4ade80", "#facc15", "#f87171"
    SEVC = {"good": GOOD, "warn": WARN, "bad": BAD, "info": T["fg"]}
    GLYPH = {"bad": "\u25CF", "warn": "\u25CF", "info": "\u25CB", "good": "\u2714"}
    s_ = ttk.Style()
    s_.configure("TNotebook", background=T["bg"], borderwidth=0)
    s_.configure("TNotebook.Tab", background=T["panel"], foreground=T["muted"], padding=(18, 8), borderwidth=0)
    s_.map("TNotebook.Tab", background=[("selected", T["sel"])], foreground=[("selected", T["fg"])])
    nb = ttk.Notebook(win)
    nb.pack(fill="both", expand=True, padx=10, pady=10)
    pages = {}
    for key, label in (("over", "Overview"), ("drives", "Drives && space"), ("start", "Startup apps"), ("backups", "Backups"), ("net", "Network"), ("sec", "Security"), ("trend", "Trends"), ("apps", "Programs")):
        fr = tk.Frame(nb, bg=T["bg"])
        nb.add(fr, text="  " + label.replace("&&", "&") + "  ")
        pages[key] = fr
    A.cfg["space_history"] = HL.record_snapshot(A.cfg["space_history"], HL.disk_report())
    A.save_cfg(space_history=A.cfg["space_history"])
    Hd = {"drives": HL.disk_report(), "history": A.cfg["space_history"], "backups": A.cfg["backups"]}
    state = {"recs": [], "pending": 0}

    # ---------------- overview
    ov = pages["over"]
    head = tk.Frame(ov, bg=T["bg"])
    head.pack(fill="x", padx=16, pady=(14, 4))
    score_l = tk.Label(head, text="…", bg=T["bg"], fg=T["muted"], font=("Segoe UI", 34, "bold"))
    score_l.pack(side="left")
    score_t = tk.Label(head, text="Checking your PC…", bg=T["bg"], fg=T["muted"], font=("Segoe UI", fs + 3), anchor="w")
    score_t.pack(side="left", padx=18)
    ttk.Button(head, text="Re-check", command=lambda: collect()).pack(side="right")
    grid_f = tk.Frame(ov, bg=T["bg"])
    grid_f.pack(fill="x", padx=12, pady=(6, 0))
    for c in range(3):
        grid_f.columnconfigure(c, weight=1, uniform="tiles")
    tiles = {}
    for n_, (key, title) in enumerate((("storage", "Storage"), ("drive", "Drive health"), ("mem", "Memory & CPU"),
                                       ("battery", "Battery"), ("security", "Security"), ("uptime", "Uptime & updates"),
                                       ("startup", "Startup apps"), ("errors", "Disk errors (30 days)"), ("backups", "Backups"))):
        f = tk.Frame(grid_f, bg=T["panel"], padx=14, pady=10)
        f.grid(row=n_ // 3, column=n_ % 3, sticky="nsew", padx=4, pady=4)
        tk.Label(f, text=title.upper(), bg=T["panel"], fg=T["muted"], font=("Segoe UI", fs - 2, "bold")).pack(anchor="w")
        v = tk.Label(f, text="checking…", bg=T["panel"], fg=T["muted"], font=("Segoe UI", fs + 6, "bold"))
        v.pack(anchor="w")
        sb = tk.Label(f, text="", bg=T["panel"], fg=T["muted"], wraplength=330, justify="left", font=("Segoe UI", fs - 1))
        sb.pack(anchor="w")
        tiles[key] = (v, sb)

    def set_tile(key, value, sub, sev):
        v, sb = tiles[key]
        v.configure(text=value, fg=SEVC[sev])
        sb.configure(text=sub)

    tk.Label(ov, text="WHAT TO DO", bg=T["bg"], fg=T["accent"], font=("Segoe UI", fs - 1, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
    rf = tk.Frame(ov, bg=T["bg"])
    rf.pack(fill="both", expand=True, padx=14)
    rt = ttk.Treeview(rf, columns=("act",), show="tree", height=4, selectmode="browse")
    rt.column("#0", width=900)
    rt.column("act", width=0, stretch=False)
    for sv, col in SEVC.items():
        rt.tag_configure(sv, foreground=col)
    rt.pack(fill="both", expand=True)
    rb = tk.Frame(ov, bg=T["bg"])
    rb.pack(fill="x", padx=14, pady=10, side="bottom", before=rf)  # packed first so a small window can't squash the buttons
    act_b = ttk.Button(rb, text="Fix it / open the tool", style="Accent.TButton")
    act_b.pack(side="left")
    def export_report():
        from ui_picker import filedialog
        p_ = filedialog.asksaveasfilename(parent=win, defaultextension=".html", filetypes=[("Web page", "*.html")],
                                          initialfile="PC health report " + time.strftime("%Y-%m-%d") + ".html")
        if p_:
            try:
                Path(p_).write_text(HL.report_html(Hd), encoding="utf-8")
                ff_platform.open_path(p_)
            except OSError as e:
                messagebox.showerror("Report", str(e), parent=win)

    def quick_scan():
        if not messagebox.askyesno("Virus scan", "Start a Windows Defender quick scan in the background?\n\nIt can take several minutes; Windows shows the result in Windows Security.", parent=win):
            return
        try:
            subprocess.Popen(["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", "Start-MpScan -ScanType QuickScan"],
                             creationflags=0x08000000)
            A.status.set("Defender quick scan started")
        except OSError as e:
            messagebox.showerror("Virus scan", str(e), parent=win)

    ttk.Button(rb, text="Quick virus scan", command=quick_scan).pack(side="left", padx=8)
    ttk.Button(rb, text="Export report…", command=export_report).pack(side="left", padx=8)
    hint = tk.Label(rb, text="Pick an item above, then press the button (or double-click it).", bg=T["bg"], fg=T["muted"])
    hint.pack(side="left", padx=12)

    def run_rec(_=None):
        c = rt.selection()
        if not c:
            return
        act = state["recs"][int(c[0])][2]
        if act == "backup":
            nb.select(pages["backups"])
        elif act:
            A.open_action(act)

    act_b.configure(command=run_rec)
    rt.bind("<Double-1>", run_rec)

    def refresh_recs():
        recs, score = HL.recommendations(Hd)
        state["recs"] = recs
        rt.delete(*rt.get_children())
        for i, (sv, text, act) in enumerate(recs):
            rt.insert("", "end", iid=str(i), text=f"{GLYPH[sv]}   {text}" + (f"      \u2192 {A.ACTION_LABEL[act]}" if act else ""),
                      values=(act or "",), tags=(sv,))
        col = GOOD if score >= 75 else WARN if score >= 50 else BAD
        score_l.configure(text=str(score), fg=col)
        if not state["pending"]:
            A.set_score(score)
        n_issues = sum(1 for r in recs if r[0] in ("bad", "warn"))
        score_t.configure(text=f"{HL.score_label(score)}" + (f"  —  {n_issues} thing(s) need attention" if n_issues else "  —  nothing needs attention")
                          + ("   (still checking…)" if state["pending"] else ""), fg=T["fg"])

    # ---------------- drives tab
    dp = pages["drives"]
    tk.Label(dp, text="VOLUMES", bg=T["bg"], fg=T["accent"], font=("Segoe UI", fs - 1, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
    tv = ttk.Treeview(dp, columns=("kind", "size", "free", "pct"), show="tree headings", height=4)
    for c, text, w, anc in (("#0", "Drive", 160, "w"), ("kind", "Type", 100, "w"), ("size", "Size", 110, "e"),
                            ("free", "Free", 110, "e"), ("pct", "Free %", 110, "e")):
        tv.heading(c, text=text, anchor=anc)
        tv.column(c, width=w, anchor=anc)
    tv.pack(fill="x", padx=14)
    tk.Label(dp, text="PHYSICAL DRIVES (what Windows reports about the hardware)", bg=T["bg"], fg=T["accent"],
             font=("Segoe UI", fs - 1, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
    tp = ttk.Treeview(dp, columns=("media", "size", "health", "temp", "wear", "errs", "hours"), show="tree headings", height=3)
    for c, text, w, anc in (("#0", "Drive", 330, "w"), ("media", "Type", 90, "w"), ("size", "Size", 90, "e"), ("health", "Health", 100, "w"),
                            ("temp", "Temp", 70, "e"), ("wear", "SSD wear", 80, "e"), ("errs", "R/W errors", 90, "e"), ("hours", "Power-on hrs", 100, "e")):
        tp.heading(c, text=text, anchor=anc)
        tp.column(c, width=w, anchor=anc)
    tp.pack(fill="x", padx=14)
    adm_msg = tk.StringVar(value="")
    adm_row = tk.Frame(dp, bg=T["bg"])
    adm_row.pack(fill="x", padx=14, pady=8)

    def admin_run(fn, show):
        adm_msg.set("Waiting for the Windows administrator prompt\u2026 (approve it to continue)")

        def work():
            try:
                res = fn()
            except Exception as e:  # noqa
                res = None
                log_error(f"elevated: {e}")
            A.root.after(0, lambda: alive["v"] and show(res))
        threading.Thread(target=work, daemon=True).start()

    ttk.Button(adm_row, text="Full drive health, TPM, BitLocker (asks for administrator OK)",
               command=lambda: admin_run(ff_elevated.full_info, lambda r: adm_msg.set("\n".join(ff_elevated.describe(r))))).pack(side="left")
    ttk.Button(adm_row, text="Create a restore point (asks for administrator OK)",
               command=lambda: admin_run(ff_elevated.create_restore_point, lambda r: adm_msg.set((r or {}).get("message") or "No answer: the prompt was declined or timed out."))).pack(side="left", padx=8)
    tk.Label(dp, textvariable=adm_msg, bg=T["bg"], fg=T["fg"], anchor="w", justify="left", wraplength=1100, font=("Segoe UI", fs)).pack(fill="x", padx=18)
    tk.Label(dp, text="Drives don't always report temperature, wear and errors without administrator rights — blanks just mean “not reported”.",
             bg=T["bg"], fg=T["muted"], font=("Segoe UI", fs - 1)).pack(anchor="w", padx=18, pady=(4, 0))
    tk.Label(dp, text="FREE SPACE OVER TIME (system drive; Foldwise takes one reading a day)", bg=T["bg"], fg=T["accent"],
             font=("Segoe UI", fs - 1, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
    cv = tk.Canvas(dp, bg=T["panel"], height=190, highlightthickness=0)
    cv.pack(fill="x", padx=14, pady=(0, 10))

    def draw_trend(_=None):
        cv.delete("all")
        sysroot = os.path.splitdrive(A.home)[0] + "\\"
        pts = sorted((d, v[sysroot]) for d, v in Hd["history"].items() if sysroot in v)
        W, H_ = max(cv.winfo_width(), 400), 190
        if len(pts) < 2:
            cv.create_text(W // 2, H_ // 2, text="Collecting data — the graph appears after a couple of days of readings.", fill=T["muted"],
                           font=("Segoe UI", fs))
            return
        lo, hi = min(v for _, v in pts), max(v for _, v in pts)
        span = max(hi - lo, 1)
        xs = lambda i: 60 + i * (W - 90) / (len(pts) - 1)
        ys = lambda v: H_ - 30 - (v - lo) * (H_ - 70) / span
        coords = [c for i, (_, v) in enumerate(pts) for c in (xs(i), ys(v))]
        cv.create_line(*coords, fill=T["accent"], width=3, smooth=False)
        cv.create_text(8, 20, text=human_size(hi), fill=T["muted"], anchor="w", font=("Segoe UI", fs - 1))
        cv.create_text(8, H_ - 30, text=human_size(lo), fill=T["muted"], anchor="w", font=("Segoe UI", fs - 1))
        cv.create_text(60, H_ - 10, text=pts[0][0], fill=T["muted"], anchor="w", font=("Segoe UI", fs - 1))
        cv.create_text(W - 30, H_ - 10, text=pts[-1][0], fill=T["muted"], anchor="e", font=("Segoe UI", fs - 1))
        delta = pts[-1][1] - pts[0][1]
        sign = "+" if delta >= 0 else "\u2212"
        cv.create_text(W // 2, 14, text=f"{human_size(pts[-1][1])} free now   \u2022   {sign}{human_size(abs(delta))} since {pts[0][0]}",
                       fill=T["fg"], font=("Segoe UI", fs, "bold"))

    cv.bind("<Configure>", draw_trend)

    def fill_drives_tab():
        tv.delete(*tv.get_children())
        for d in Hd["drives"]:
            tv.insert("", "end", text=d["root"], values=(d["kind"], human_size(d["total"]), human_size(d["free"]), f"{d['pct_free']:.0f}%"))
        tp.delete(*tp.get_children())
        for p in Hd.get("physical") or []:
            tp.insert("", "end", text=p.get("Name") or "?", values=(p.get("Media") or "", f"{p.get('SizeGB') or 0} GB", p.get("Health") or "",
                      f"{p['TempC']}°C" if p.get("TempC") else "", f"{p['Wear']}%" if p.get("Wear") is not None else "",
                      f"{p.get('ReadErr') or 0}/{p.get('WriteErr') or 0}" if p.get("ReadErr") is not None else "",
                      f"{p['Hours']:,}" if p.get("Hours") else ""))
        draw_trend()

    # ---------------- startup tab
    sp = pages["start"]
    tk.Label(sp, text="These programs start with Windows. Foldwise only lists them — to turn one off, use Task Manager → Startup apps "
             "(right-click → Disable). Disabling things you don't need makes the PC start faster.", bg=T["bg"], fg=T["muted"],
             wraplength=1100, justify="left", font=("Segoe UI", fs)).pack(anchor="w", padx=18, pady=(14, 8))
    tst = ttk.Treeview(sp, columns=("where", "mem", "cpu", "cmd"), show="tree headings")
    for c, text, w, anc in (("#0", "Program", 240, "w"), ("where", "Where it's set", 170, "w"), ("mem", "Memory now", 100, "e"), ("cpu", "CPU time used", 110, "e"),
                            ("cmd", "Command", 520, "w")):
        tst.heading(c, text=text, anchor=anc)
        tst.column(c, width=w, anchor=anc)
    tst.pack(fill="both", expand=True, padx=14)
    sb_ = tk.Frame(sp, bg=T["bg"])
    sb_.pack(fill="x", padx=14, pady=10, side="bottom", before=tst)
    ttk.Button(sb_, text="Open Task Manager (Startup apps)", style="Accent.TButton", command=lambda: A.open_action("taskmgr")).pack(side="left")
    ttk.Button(sb_, text="Open my Startup folder", command=lambda: ff_platform.open_os_settings("startup_folder")).pack(side="left", padx=8)
    ttk.Button(sb_, text="Turn startup apps on/off (Windows Settings)", command=lambda: ff_platform.open_os_settings("startup_apps")).pack(side="left")

    # ---------------- backups tab
    bp = pages["backups"]
    tk.Label(bp, text="A backup job copies the NEW and CHANGED files from a folder into a backup folder — ideally on another drive. "
             "It never deletes anything and never overwrites a newer file in the backup. Foldwise warns you when a backup gets old.",
             bg=T["bg"], fg=T["muted"], wraplength=1100, justify="left", font=("Segoe UI", fs)).pack(anchor="w", padx=18, pady=(14, 8))
    jt = ttk.Treeview(bp, columns=("dst", "sched", "next", "last", "result"), show="tree headings", selectmode="browse")
    for c, text, w in (("#0", "Back up this folder", 280), ("dst", "… into", 280), ("sched", "Schedule", 90), ("next", "Next run", 90),
                       ("last", "Last backup", 140), ("result", "Last result", 280)):
        jt.heading(c, text=text, anchor="w")
        jt.column(c, width=w, anchor="w")
    jt.pack(fill="both", expand=True, padx=14)
    bmsg = tk.StringVar(value="")
    bb = tk.Frame(bp, bg=T["bg"])
    bb.pack(fill="x", padx=14, pady=10, side="bottom", before=jt)
    tk.Label(bp, textvariable=bmsg, bg=T["bg"], fg=T["fg"], anchor="w", font=("Segoe UI", fs)).pack(fill="x", padx=18, pady=(8, 0), side="bottom", before=jt)

    def refresh_jobs():
        Hd["backups"] = A.cfg["backups"]
        jt.delete(*jt.get_children())
        for i, j in enumerate(A.cfg["backups"]):
            jt.insert("", "end", iid=str(i), text=j["src"], values=(
                j["dst"], HL.SCHEDULE_LABEL.get(j.get("schedule"), "Manual only"), HL.next_run_text(j),
                fmt_date(j["last"]) if j.get("last") else "never",
                ("⚠ " if j.get("ok") is False else "") + j.get("result", "")))

    A.bk_hooks.append(lambda: alive["v"] and (refresh_jobs(), refresh_recs()))

    SCHED_NAMES = {"Daily": "daily", "Weekly": "weekly", "Manual only": "off"}

    def pick_job():
        c = jt.selection()
        if not c:
            bmsg.set("Select a backup job first.")
            return None
        return int(c[0])

    def add_job(edit=None):
        d = A.toplevel("Edit backup" if edit is not None else "Add a backup", "760x470")
        fr = ttk.Frame(d, padding=22)
        fr.pack(fill="both", expand=True)
        src_v, dst_v = tk.StringVar(), tk.StringVar()
        if edit is not None:
            src_v.set(A.cfg["backups"][edit]["src"])
            dst_v.set(A.cfg["backups"][edit]["dst"])
        from ui_picker import filedialog
        for r_, (label_, var_) in enumerate((("Folder to back up", src_v), ("Back it up into", dst_v))):
            ttk.Label(fr, text=label_).grid(row=r_ * 2, column=0, sticky="w", pady=(10, 2))
            ttk.Entry(fr, textvariable=var_, width=62).grid(row=r_ * 2 + 1, column=0, sticky="we")
            ttk.Button(fr, text="Browse\u2026", command=lambda v=var_: (lambda p_: v.set(os.path.normpath(p_)) if p_ else None)(
                filedialog.askdirectory(parent=d))).grid(row=r_ * 2 + 1, column=1, padx=8)
        ex_v = tk.StringVar(value=A.cfg["backups"][edit].get("exclude", "") if edit is not None else "node_modules, *.tmp")
        sched_v = tk.StringVar(value="Daily" if edit is None else {"daily": "Daily", "weekly": "Weekly"}.get(A.cfg["backups"][edit].get("schedule"), "Manual only"))
        ttk.Label(fr, text="Skip files/folders matching (comma separated, e.g. node_modules, *.tmp, Cache)").grid(row=7, column=0, sticky="w", pady=(10, 2))
        ttk.Entry(fr, textvariable=ex_v, width=62).grid(row=8, column=0, sticky="we")
        ttk.Label(fr, text="Run automatically").grid(row=4, column=0, sticky="w", pady=(10, 2))
        ttk.Combobox(fr, textvariable=sched_v, values=list(SCHED_NAMES), state="readonly", width=24).grid(row=4, column=1, sticky="w")
        ttk.Label(fr, text="Tip: choose a folder on a DIFFERENT drive (an external disk or another internal drive), so one failing drive can't take both copies.",
                  wraplength=640, style="DetKey.TLabel", background=T["bg"]).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))

        def save():
            src, dst = os.path.normpath(src_v.get().strip()), os.path.normpath(dst_v.get().strip())
            if not src_v.get().strip() or not dst_v.get().strip():
                messagebox.showerror("Backup", "Choose both folders.", parent=d)
                return
            err = HL._guard(src, dst)
            if err:
                messagebox.showerror("Backup", err, parent=d)
                return
            if os.path.splitdrive(src)[0].lower() == os.path.splitdrive(dst)[0].lower():
                if not messagebox.askyesno("Same drive", "Both folders are on the same drive, so this won't protect you if the drive fails.\n\nAdd it anyway?", parent=d):
                    return
            if edit is not None:
                jobs = [dict(j) for j in A.cfg["backups"]]
                old = jobs[edit]
                moved = (old["src"], old["dst"]) != (src, dst)
                old.update(src=src, dst=dst, schedule=SCHED_NAMES[sched_v.get()], exclude=ex_v.get().strip())
                if moved:  # a different pair of folders has not been backed up yet
                    old.update(last=None, ok=None, attempt=0, result="")
                A.save_cfg(backups=jobs)
            else:
                A.save_cfg(backups=list(A.cfg["backups"]) + [dict(src=src, dst=dst, last=None, result="", added=time.time(), schedule=SCHED_NAMES[sched_v.get()], exclude=ex_v.get().strip())])
            refresh_jobs()
            refresh_recs()
            d.destroy()

        bt = ttk.Frame(fr)
        bt.grid(row=9, column=0, columnspan=2, sticky="e", pady=(18, 0))
        ttk.Button(bt, text="Save" if edit is not None else "Add backup", style="Accent.TButton", command=save).pack(side="left", padx=4)
        ttk.Button(bt, text="Cancel", command=d.destroy).pack(side="left")
        fr.columnconfigure(0, weight=1)

    def run_job(preview_only=False):
        idx = pick_job()
        if idx is None:
            return
        job = A.cfg["backups"][idx]
        if (job["src"], job["dst"]) in A.bk_running:
            bmsg.set("This backup is already running.")
            return
        bmsg.set("Comparing the two folders…")

        def work_prev():
            pv = HL.backup_preview(job["src"], job["dst"], lambda: not alive["v"],
                                   lambda m: alive["v"] and A.root.after(0, lambda: alive["v"] and bmsg.set(m)),
                                   exclude=HL.parse_patterns(job.get("exclude")))
            A.root.after(0, after_prev, pv)

        def after_prev(pv):
            if not alive["v"] or pv is None:
                return
            if "error" in pv:
                bmsg.set("")
                messagebox.showerror("Backup", pv["error"], parent=win)
                return
            text = (f"{pv['new']} new and {pv['changed']} changed file(s) ({human_size(pv['bytes'])}) will be copied into\n{job['dst']}.\n\n"
                    "Files already in the backup are never deleted, and newer files there are never overwritten.")
            if not pv["todo"]:
                text = "The backup is already up to date — nothing needs copying."
            bmsg.set("")
            if preview_only or not pv["todo"]:
                messagebox.showinfo("Backup preview" if preview_only else "Backup", text, parent=win)
                if not pv["todo"] and not preview_only:
                    finish_job(idx, {"copied": 0, "bytes": 0, "errors": [], "unchanged": pv["same"], "kept_newer": pv["newer_dst"]}, quiet=True)
                return
            if not messagebox.askyesno("Back up now", text + "\n\nContinue?", parent=win):
                return
            bmsg.set("Backing up…")
            A.bk_running.add((job["src"], job["dst"]))

            def work_run():
                res = HL.run_backup(job["src"], job["dst"], lambda: not alive["v"],
                                    lambda i, n, name: alive["v"] and A.root.after(0, lambda: alive["v"] and bmsg.set(f"Copying {i + 1}/{n}: {name}")),
                                    exclude=HL.parse_patterns(job.get("exclude")))
                A.root.after(0, lambda: (A.bk_running.discard((job["src"], job["dst"])), finish_job(idx, res, False)))
            threading.Thread(target=work_run, daemon=True).start()

        threading.Thread(target=work_prev, daemon=True).start()

    def finish_job(idx, res, quiet=False):
        if res is None or "error" in (res or {}):
            bmsg.set("")
            return
        jobs = [dict(j) for j in A.cfg["backups"]]
        jobs[idx]["last"] = time.time()
        jobs[idx]["ok"] = not res["errors"]
        jobs[idx]["result"] = (f"Copied {res['copied']} file(s), {human_size(res['bytes'])}" if res["copied"] else "Up to date") + \
                              (f"; {len(res['errors'])} failed" if res["errors"] else "")
        A.save_cfg(backups=jobs)
        bmsg.set("")
        if alive["v"]:
            refresh_jobs()
            refresh_recs()
        A.status.set("Backup finished: " + jobs[idx]["result"])
        if not quiet:
            extra = f"\n\n{len(res['errors'])} file(s) couldn't be copied, e.g. {res['errors'][0][0]}: {res['errors'][0][1]}" if res["errors"] else ""
            messagebox.showinfo("Backup finished", jobs[idx]["result"] + "." + extra, parent=win if alive["v"] else A.root)

    def set_schedule(name):
        idx = pick_job()
        if idx is not None:
            j = A.cfg["backups"][idx]
            A.set_job_fields(j["src"], j["dst"], schedule=SCHED_NAMES[name])
            bmsg.set(f"Schedule set to: {name}. Scheduled backups run only while you're away from the PC for a couple of minutes.")

    def remove_job():
        idx = pick_job()
        if idx is None:
            return
        if messagebox.askyesno("Remove", "Remove this backup job? (Files already backed up are left alone.)", parent=win):
            A.save_cfg(backups=[j for k, j in enumerate(A.cfg["backups"]) if k != idx])
            refresh_jobs()
            refresh_recs()

    ttk.Button(bb, text="Add backup…", style="Accent.TButton", command=add_job).pack(side="left")
    ttk.Button(bb, text="Back up now", command=lambda: run_job(False)).pack(side="left", padx=8)
    ttk.Button(bb, text="Preview", command=lambda: run_job(True)).pack(side="left")
    ttk.Button(bb, text="Edit\u2026", command=lambda: (lambda i: i is not None and add_job(i))(pick_job())).pack(side="left", padx=8)
    sm = tk.Menu(bb, tearoff=0)
    for n_ in SCHED_NAMES:
        sm.add_command(label=n_, command=lambda n_=n_: set_schedule(n_))
    mb = ttk.Menubutton(bb, text="Schedule ▾", menu=sm)
    mb.pack(side="left", padx=8)
    ttk.Button(bb, text="Remove", command=remove_job).pack(side="left", padx=8)
    ttk.Button(bb, text="Open backup folder", command=lambda: (lambda i: i is not None and os.path.isdir(A.cfg["backups"][i]["dst"]) and A.navigate(A.cfg["backups"][i]["dst"]))(pick_job())).pack(side="left")
    ttk.Button(bb, text="Close", command=win.destroy).pack(side="right")

    # ---------------- network tab
    npg = pages["net"]
    tk.Label(npg, text="Checks your router, your internet connection and name lookups (DNS) — the first things to test when “the internet is slow or down”.",
             bg=T["bg"], fg=T["muted"], wraplength=1100, justify="left", font=("Segoe UI", fs)).pack(anchor="w", padx=18, pady=(14, 8))
    nlist = tk.Frame(npg, bg=T["bg"])
    nlist.pack(fill="x", padx=18)
    nmsg = tk.StringVar(value="Press “Run network check”.")
    tk.Label(npg, textvariable=nmsg, bg=T["bg"], fg=T["muted"], font=("Segoe UI", fs)).pack(anchor="w", padx=18, pady=8)

    def net_run():
        nmsg.set("Testing… (about 10 seconds)")
        net_b.configure(state="disabled")

        def work():
            try:
                rep = HL.network_report()
            except Exception as e:  # noqa
                log_error(f"network check: {e}")
                rep = None
            A.root.after(0, lambda: alive["v"] and net_done(rep))
        threading.Thread(target=work, daemon=True).start()

    def net_done(rep):
        net_b.configure(state="normal")
        for w_ in nlist.winfo_children():
            w_.destroy()
        if rep is None:
            nmsg.set("The check failed.")
            return
        for sv, text in HL.network_lines(rep):
            tk.Label(nlist, text=f"{GLYPH[sv]}   {text}", bg=T["bg"], fg=SEVC[sv], anchor="w", font=("Segoe UI", fs + 1)).pack(fill="x", pady=3)
        nmsg.set("Checked " + time.strftime("%H:%M:%S"))
        Hd["net"] = rep
        refresh_recs()

    net_b = ttk.Button(npg, text="Run network check", style="Accent.TButton", command=net_run)
    net_b.pack(anchor="w", padx=18, pady=6)
    ttk.Button(npg, text="Open Windows network settings", command=lambda: ff_platform.open_os_settings("network")).pack(anchor="w", padx=18)
    wifi_v, speed_v = tk.StringVar(value=""), tk.StringVar(value="")
    tk.Label(npg, textvariable=wifi_v, bg=T["bg"], fg=T["fg"], anchor="w", justify="left", font=("Segoe UI", fs)).pack(anchor="w", padx=18, pady=(14, 2))
    tk.Label(npg, textvariable=speed_v, bg=T["bg"], fg=T["fg"], anchor="w", justify="left", font=("Segoe UI", fs + 1, "bold")).pack(anchor="w", padx=18, pady=2)
    speed_b = ttk.Button(npg, text="Test download speed (25 MB from Cloudflare)")
    speed_b.pack(anchor="w", padx=18, pady=6)
    speed_busy = {"v": False}

    def speed_run():
        if speed_busy["v"]:
            return
        speed_busy["v"] = True
        speed_v.set("Testing\u2026")

        def work():
            try:
                mbit = HL.speed_test(25_000_000, progress=lambda d, t: alive["v"] and root_after(lambda: speed_v.set(f"Testing\u2026 {d / 1e6:.0f} of {t / 1e6:.0f} MB")))
                text = f"Download speed: {mbit:.0f} Mbit/s  (\u2248 {mbit / 8:.1f} MB per second)"
            except Exception as e:  # noqa
                text = f"Speed test failed: {e}"
            speed_busy["v"] = False
            root_after(lambda: speed_v.set(text))
        threading.Thread(target=work, daemon=True).start()

    def root_after(fn):
        if alive["v"]:
            A.root.after(0, lambda: alive["v"] and fn())

    speed_b.configure(command=speed_run)

    # ---------------- security tab (read-only audit; fixing is done in Windows' own settings)
    scp = pages["sec"]
    tk.Label(scp, text="A read-only check of the settings that matter most for safety. Foldwise never changes any of them \u2014 "
             "select a line to read what it means and how to fix it.", bg=T["bg"], fg=T["muted"], wraplength=1100, justify="left",
             font=("Segoe UI", fs)).pack(anchor="w", padx=18, pady=(14, 8))
    sdet = tk.StringVar(value="Checking\u2026 (about 10 seconds)")
    sbtns = tk.Frame(scp, bg=T["bg"])
    sbtns.pack(side="bottom", fill="x", padx=14, pady=10)
    tk.Label(scp, textvariable=sdet, bg=T["bg"], fg=T["fg"], anchor="w", justify="left", wraplength=1100,
             font=("Segoe UI", fs)).pack(side="bottom", fill="x", padx=18, pady=(6, 0))
    sf = tk.Frame(scp, bg=T["bg"])
    sf.pack(fill="both", expand=True, padx=14)
    stv = ttk.Treeview(sf, show="tree", selectmode="browse", height=6)
    stv.column("#0", width=900)
    for sv, col in SEVC.items():
        stv.tag_configure(sv, foreground=col)
    ssb = ttk.Scrollbar(sf, orient="vertical", command=stv.yview)
    stv.configure(yscrollcommand=ssb.set)
    ssb.pack(side="right", fill="y")
    stv.pack(fill="both", expand=True)
    sfind = {"rows": []}

    def sec_show(res):
        Hd["secaudit"] = res
        stv.delete(*stv.get_children())
        sfind["rows"] = HL.security_findings(res)
        order = {"bad": 0, "warn": 1, "info": 2, "good": 3}
        for i, (sv, title, detail, act) in enumerate(sorted(sfind["rows"], key=lambda r: order[r[0]])):
            stv.insert("", "end", iid=str(i), text=f"{GLYPH[sv]}   {title}", tags=(sv,))
        sfind["sorted"] = sorted(sfind["rows"], key=lambda r: order[r[0]])
        if not sfind["rows"]:
            sdet.set("The check could not run (PowerShell blocked?).")
        else:
            bad = sum(1 for r in sfind["rows"] if r[0] in ("bad", "warn"))
            sdet.set(f"{bad} item(s) need attention. Select a line for details." if bad else "Everything checked looks fine. Select a line for details.")
        refresh_recs()

    def sec_pick(_=None):
        c = stv.selection()
        if c:
            sv, title, detail, act = sfind["sorted"][int(c[0])]
            extra = ""
            if title.startswith("Defender found"):
                try:
                    th_ = HL.defender_threats(30)
                    extra = "  Details: " + " | ".join(f"{t_.get('Name')} ({t_['Time']}): " + ((t_.get('Res') or '')[:140]) for t_ in th_[:3]) + \
                            ("  \u2014 'CmdLine' means Defender flagged the text of a running command, not a file on disk (often a false alarm from developer tools)."
                             if any((t_.get('Res') or '').startswith('CmdLine') for t_ in th_) else "")
                except Exception:
                    pass
            sdet.set(title + (" \u2014 " + detail if detail else "") + extra)

    stv.bind("<<TreeviewSelect>>", sec_pick)
    ttk.Button(sbtns, text="Open Windows Security", style="Accent.TButton", command=lambda: A.open_action("security")).pack(side="left")
    ttk.Button(sbtns, text="Malware check…", command=lambda: A.open_malware()).pack(side="left", padx=8)
    ttk.Button(sbtns, text="Open Task Scheduler", command=lambda: ff_platform.open_os_settings("task_scheduler")).pack(side="left", padx=8)
    ttk.Button(sbtns, text="Run the check again", command=lambda: (sdet.set("Checking\u2026"), task(HL.security_raw, sec_show))).pack(side="left")

    # ---------------- trends tab (CPU/RAM every 5 min, battery + drive temperature hourly)
    trp = pages["trend"]
    tk.Label(trp, text="How this PC has been behaving. Foldwise keeps a light log while it runs (CPU and memory every 5 minutes, battery and drive "
             "temperature every hour). Drive temperature is only reported when Windows allows it (often needs administrator rights).",
             bg=T["bg"], fg=T["muted"], wraplength=1100, justify="left", font=("Segoe UI", fs)).pack(anchor="w", padx=18, pady=(14, 4))
    charts = []
    trbox = tk.Frame(trp, bg=T["bg"])
    trbox.pack(fill="both", expand=True, padx=14, pady=4)
    for k_ in range(4):
        cv_ = tk.Canvas(trbox, bg=T["panel"], highlightthickness=0, height=120)
        cv_.pack(fill="both", expand=True, pady=3)
        charts.append(cv_)

    def draw_chart(cv, pts, title, unit, ymax, color, span):
        cv.delete("all")
        W, H = max(cv.winfo_width(), 300), max(cv.winfo_height(), 80)
        l_, r_, t_, b_ = 52, 14, 24, 20
        cv.create_text(10, 10, text=title, anchor="w", fill=T["accent"], font=("Segoe UI", fs - 1, "bold"))
        t1 = time.time()
        t0 = t1 - span
        for f_ in (0, .5, 1):
            y_ = t_ + (H - t_ - b_) * (1 - f_)
            cv.create_line(l_, y_, W - r_, y_, fill=T["line"])
            cv.create_text(l_ - 6, y_, text=f"{ymax * f_:.0f}{unit}", anchor="e", fill=T["muted"], font=("Segoe UI", fs - 2))
        if not pts:
            cv.create_text(W // 2, H // 2, text="no data yet", fill=T["muted"])
            return
        xy = []
        for t, v in pts:
            if t >= t0:
                xy += [l_ + (W - l_ - r_) * (t - t0) / span, t_ + (H - t_ - b_) * (1 - min(v, ymax) / ymax)]
        if len(xy) >= 4:
            cv.create_line(*xy, fill=color, width=2)
        elif len(xy) == 2:
            cv.create_oval(xy[0] - 3, xy[1] - 3, xy[0] + 3, xy[1] + 3, fill=color, outline=color)
        lbl = "last " + (f"{span / 3600:.0f} hours" if span <= 172800 else f"{span / 86400:.0f} days")
        cv.create_text(W - r_, H - 8, text=lbl, anchor="e", fill=T["muted"], font=("Segoe UI", fs - 2))
        cv.create_text(W - r_, 10, text=f"now {pts[-1][1]:.0f}{unit}", anchor="e", fill=T["fg"], font=("Segoe UI", fs - 1))

    grow_v = tk.StringVar(value="")
    tk.Label(trp, textvariable=grow_v, bg=T["bg"], fg=T["fg"], anchor="w", justify="left", wraplength=1100, font=("Segoe UI", fs)).pack(fill="x", padx=18, pady=(0, 8))

    def draw_trends(_=None):
        h_ = HL.history_load(A.hist_path)
        gr = HL.folder_growth(h_["folders"])
        grow_v.set("Folders that grew the most (last ~30 days): " + ", ".join(f"{os.path.basename(p)} +{human_size(g)}" for p, g in gr) if gr else
                   "Folder growth: Foldwise measures your main folders once a week while you're away; the first comparison appears after two weeks.")
        day = 86400
        draw_chart(charts[0], HL.series(h_["perf"], "cpu"), "CPU load", "%", 100, "#60a5fa", day)
        draw_chart(charts[1], HL.series(h_["perf"], "mem"), "Memory in use", "%", 100, "#4ade80", day)
        draw_chart(charts[2], HL.series(h_["hourly"], "bat"), "Battery charge", "%", 100, "#facc15", 7 * day)
        tp = HL.series(h_["hourly"], "temp")
        draw_chart(charts[3], tp, "Drive temperature" if tp else "Drive temperature (not reported by Windows without admin rights)", "\u00B0C", 100, "#f87171", 30 * day)

    for cv_ in charts:
        cv_.bind("<Configure>", draw_trends)
    nb.bind("<<NotebookTabChanged>>", lambda e: draw_trends() if nb.select() == str(pages["trend"]) else None, add="+")

    # ---------------- programs tab (read-only list; removal is done by Windows' own uninstaller)
    ap = pages["apps"]
    tk.Label(ap, text="Installed programs, biggest first. Foldwise only lists them — to remove one, select it and press the button: Windows runs its own uninstaller.",
             bg=T["bg"], fg=T["muted"], wraplength=1100, justify="left", font=("Segoe UI", fs)).pack(anchor="w", padx=18, pady=(14, 8))
    pf = tk.Frame(ap, bg=T["bg"])
    pf.pack(fill="both", expand=True, padx=14)
    pt = ttk.Treeview(pf, columns=("pub", "ver", "size"), show="tree headings", selectmode="browse")
    for c, text, w, anc in (("#0", "Program", 420, "w"), ("pub", "Publisher", 260, "w"), ("ver", "Version", 150, "w"), ("size", "Size", 110, "e")):
        pt.heading(c, text=text, anchor=anc)
        pt.column(c, width=w, anchor=anc)
    psb = ttk.Scrollbar(pf, orient="vertical", command=pt.yview)
    pt.configure(yscrollcommand=psb.set)
    psb.pack(side="right", fill="y")
    pt.pack(fill="both", expand=True)
    pmsg = tk.StringVar(value="Loading…")
    pbtn = ttk.Button(ap, text="Open Windows “Installed apps” to uninstall…", style="Accent.TButton",
                      command=lambda: ff_platform.open_os_settings("installed_apps"))
    pbtn.pack(anchor="w", padx=18, pady=(0, 12), side="bottom", before=pf)
    tk.Label(ap, textvariable=pmsg, bg=T["bg"], fg=T["fg"], anchor="w", font=("Segoe UI", fs)).pack(fill="x", padx=18, pady=6, side="bottom", before=pf)

    def fill_apps(res):
        pt.delete(*pt.get_children())
        for a_ in res or []:
            pt.insert("", "end", text=a_["Name"], values=(a_.get("Publisher") or "", a_.get("Version") or "",
                                                          human_size(a_["SizeMB"] * 1048576) if a_.get("SizeMB") else ""))
        tot = sum(a_.get("SizeMB") or 0 for a_ in res or [])
        pmsg.set(f"{len(res or [])} programs, about {human_size(tot * 1048576)} reported by their installers.")


    # ---------------- collecting facts (each check runs in the background and fills its tile when ready)
    def task(fn, apply):
        state["pending"] += 1

        def work():
            try:
                res = fn()
            except Exception as e:  # noqa
                log_error(f"health {getattr(fn, '__name__', fn)}: {e}")
                res = None
            A.root.after(0, done, res, apply)
        pool_h.submit(work)

    def done(res, apply):
        state["pending"] -= 1
        if alive["v"]:
            apply(res)
            refresh_recs()

    def ap_drives():
        fixed = [d for d in Hd["drives"] if d["kind"] == "Fixed"]
        if fixed:
            w = min(fixed, key=lambda d: d["pct_free"])
            sev = "bad" if (w["pct_free"] < 10 or w["free"] < 10 * 2 ** 30) else "warn" if w["pct_free"] < 20 else "good"
            set_tile("storage", f"{w['pct_free']:.0f}% free", "\n".join(f"{d['root'].rstrip(chr(92))}  {human_size(d['free'])} free of {human_size(d['total'])}" for d in Hd["drives"]), sev)
        fill_drives_tab()

    def ap_phys(res):
        Hd["physical"] = res or []
        if not res:
            set_tile("drive", "Not reported", "Windows didn't report drive health on this PC.", "info")
        else:
            bad = [p for p in res if p.get("Health") not in (None, "Healthy")]
            sev = "bad" if bad else "good"
            set_tile("drive", "Healthy" if not bad else (bad[0].get("Health") or "Check"), "\n".join(
                f"{p.get('Name')}  •  {p.get('Media')}  •  {p.get('SizeGB')} GB" + (f"  •  {p['TempC']}°C" if p.get("TempC") else "") for p in res), sev)
        fill_drives_tab()

    def ap_mem(res):
        if not res:
            return
        Hd["mem"], Hd["procs"] = res["mem"], res["procs"]
        m = res["mem"]
        top = ", ".join(f"{p['Name']} {p['MB']} MB" for p in res["procs"][:3])
        set_tile("mem", f"{m['load']}% used", f"{human_size(m['total'] - m['avail'])} of {human_size(m['total'])} in use   •   CPU {res['cpu']:.0f}%\nBiggest: {top}",
                 "bad" if m["load"] >= 90 else "warn" if m["load"] >= 80 else "good")

    def ap_battery(res):
        Hd["battery"] = res
        if not res:
            set_tile("battery", "No battery", "This looks like a desktop PC.", "info")
            return
        h = res.get("health")
        sev = "good" if h is None or h >= 80 else "warn" if h >= 60 else "bad"
        set_tile("battery", f"{res['charge']}%" + ("  (plugged in)" if res["plugged"] else ""),
                 f"Holds {h}% of its original capacity" if h is not None else "Capacity wear isn't reported", sev)

    def ap_uptime(res):
        up, rb = res
        Hd["uptime"], Hd["reboot"] = up, rb
        set_tile("uptime", f"{up / 24:.1f} days", "A restart is waiting to finish updates." if rb else "since the last restart",
                 "warn" if rb or up / 24 > 14 else "good")

    def ap_security(res):
        Hd["security"] = res or {}
        s = res or {}
        if not s.get("HasDefender"):
            set_tile("security", "Unknown", "Windows Defender status isn't available (another antivirus may be in charge).", "info")
            return
        fw = s.get("Firewall") or []
        ok = s.get("Av") and s.get("RealTime") and (not fw or all(fw))
        set_tile("security", "Protected" if ok else "Check this", f"Defender {'on' if s.get('Av') and s.get('RealTime') else 'OFF'}   •   definitions {s.get('SigAge', '?')} day(s) old   •   "
                 f"firewall {'on' if (not fw or all(fw)) else 'OFF on some networks'}", "good" if ok and (s.get("SigAge") or 0) <= 7 else "warn" if ok else "bad")

    def ap_startup(res):
        Hd["startup"] = res or []
        tst.delete(*tst.get_children())
        for it in Hd["startup"]:
            tst.insert("", "end", text=it["name"], values=(it["where"], "", "", it["command"]))
        n = len(Hd["startup"])
        set_tile("startup", f"{n} program(s)", ", ".join(i["name"] for i in Hd["startup"][:4]) + ("…" if n > 4 else ""), "warn" if n > 15 else "good")

    def ap_impact(res):
        """Fill the Memory / CPU columns and sort the heaviest first (what each start-up program really costs)."""
        if not res:
            return
        Hd["startup"] = res
        tst.delete(*tst.get_children())
        for it in sorted(res, key=lambda i: -(i["mem"] / 1e6 + i["cpu_s"])):
            tst.insert("", "end", text=it["name"] + ("" if it["running"] else "  (not running)"),
                       values=(it["where"], human_size(it["mem"]) if it["running"] else "", f"{it['cpu_s']:.0f} s" if it["running"] else "", it["command"]))
        heavy = [i for i in res if i["running"] and i["mem"] > 300e6]
        if heavy:
            set_tile("startup", f"{len(res)} program(s)", "Heaviest: " + ", ".join(f"{i['name']} ({human_size(i['mem'])})" for i in heavy[:3]), "warn")

    def ap_errors(res):
        Hd["errors"] = res
        e = res or {}
        ne, nw = e.get("Errors", 0), e.get("Warnings", 0)
        set_tile("errors", "None" if not ne and not nw else f"{ne} error(s)" if ne else f"{nw} warning(s)",
                 "Windows logged no disk problems." if not ne and not nw else f"{ne} error(s), {nw} warning(s). Latest: " + ", ".join(e.get("Latest") or []),
                 "good" if not ne and not nw else "bad" if ne else "warn")

    def ap_backups():
        jobs = A.cfg["backups"]
        if not jobs:
            set_tile("backups", "Not set up", "Nothing is protecting your files yet. Open the Backups tab.", "warn")
            return
        newest = max((j.get("last") or 0) for j in jobs)
        days = (time.time() - newest) / 86400 if newest else None
        set_tile("backups", f"{len(jobs)} job(s)", "Never run yet." if days is None else f"Last backup {days:.0f} day(s) ago.",
                 "warn" if days is None or days > 14 else "good")

    def collect():
        Hd["drives"] = HL.disk_report()
        ap_drives()
        ap_backups()
        task(HL.physical_disks, ap_phys)
        task(lambda: dict(mem=HL.memory(), cpu=HL.cpu_percent(0.4), procs=HL.top_processes(6)), ap_mem)
        task(HL.battery, ap_battery)
        task(lambda: (HL.uptime_hours(), HL.pending_reboot()), ap_uptime)
        task(HL.security, ap_security)
        task(HL.startup_items, ap_startup)
        task(lambda: HL.startup_impact(HL.startup_items()), ap_impact)
        task(HL.disk_errors, ap_errors)
        task(HL.installed_apps, fill_apps)
        task(HL.security_raw, sec_show)
        task(HL.last_update, lambda res: (Hd.update(updates=res), refresh_recs()))
        task(HL.problem_devices, lambda res: Hd.update(devices=res or []))
        task(HL.pending_updates, lambda res: Hd.update(pending_updates=res))
        task(HL.wifi_info, lambda w: wifi_v.set(f"Wi-Fi: {w['ssid']} \u2014 signal {w['signal']}%" + (f", {w['rate']} Mbit/s link" if w.get("rate") else "") + (f", channel {w['channel']}" if w.get("channel") else "")
                                          + ("   (weak: move closer to the router)" if w["signal"] < 40 else "") if w else "Wi-Fi: not connected through Wi-Fi (cable, or no Wi-Fi)."))
        refresh_recs()

    refresh_jobs()
    if tab in pages:
        nb.select(pages[tab])
    collect()


def open_autoclean(A):
    win = A.toplevel("Auto-clean & restore list", "820x600")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    ttk.Label(win, text="Auto-clean tidies temp files and app caches by itself while you're away. Nothing is deleted at once: "
              "everything is moved to a restore list and only removed for good after 7 days.", wraplength=780, padding=(16, 14, 16, 6)).pack(fill="x")
    en = tk.BooleanVar(value=A.cfg["autoclean"])
    days_v = tk.StringVar(value=str(A.cfg["autoclean_days"]))
    top = ttk.Frame(win, padding=(16, 4))
    top.pack(fill="x")
    ttk.Checkbutton(top, text="Run automatically every", variable=en, command=lambda: A.save_cfg(autoclean=en.get())).pack(side="left")
    cb = ttk.Combobox(top, textvariable=days_v, values=["1", "3", "7", "14", "30"], width=4, state="readonly")
    cb.pack(side="left", padx=6)
    cb.bind("<<ComboboxSelected>>", lambda e: A.save_cfg(autoclean_days=int(days_v.get())))
    ttk.Label(top, text="day(s), when the PC has been idle for a few minutes").pack(side="left")
    lastv = tk.StringVar()
    ttk.Label(win, textvariable=lastv, style="DetKey.TLabel", padding=(16, 2)).pack(fill="x")
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=14, pady=6)
    tv = ttk.Treeview(frm, columns=("n", "size"), show="tree headings", selectmode="browse")
    tv.heading("#0", text="Moved on", anchor="w")
    tv.heading("n", text="Items", anchor="e")
    tv.heading("size", text="Size", anchor="e")
    tv.column("#0", width=380)
    tv.column("n", width=120, anchor="e")
    tv.column("size", width=140, anchor="e")
    tv.pack(fill="both", expand=True)
    msg = tk.StringVar(value="")
    ttk.Label(win, textvariable=msg, padding=(16, 2)).pack(fill="x")
    bt = ttk.Frame(win, padding=14)
    bt.pack(fill="x")

    def fill():
        lastv.set("Last run: " + (fmt_date(A.cfg["last_autoclean"]) if A.cfg["last_autoclean"] else "never"))
        tv.delete(*tv.get_children())
        for b in CL.quarantine_batches(A.qroot):
            tv.insert("", "end", iid=b["dir"], text=fmt_date(b["created"]), values=(f"{b['count']:,}", human_size(b["bytes"])))

    def run_now():
        msg.set("Cleaning\u2026")
        A.autoclean_now(lambda res: alive["v"] and (fill(), msg.set(f"Moved {res['moved']} item(s) ({human_size(res['freed'])}) to the restore list.")))

    def restore():
        c = tv.selection()
        if not c:
            msg.set("Select a batch first.")
            return
        ok, skipped = CL.restore_batch(c[0])
        msg.set(f"Restored {ok} item(s)." + (f" {len(skipped)} skipped (e.g. {skipped[0][1]})." if skipped else ""))
        fill()
        A.after_change()

    def purge():
        c = tv.selection()
        if c and messagebox.askyesno("Delete for good", "Permanently delete this batch from the restore list? It can't be restored afterwards.", parent=win):
            msg.set(f"Freed {human_size(CL.purge_quarantine(A.qroot, only=c[0]))}.")
            fill()

    ttk.Button(bt, text="Clean now", style="Accent.TButton", command=run_now).pack(side="left")
    ttk.Button(bt, text="Restore selected batch", command=restore).pack(side="left", padx=8)
    ttk.Button(bt, text="Delete batch for good\u2026", command=purge).pack(side="left")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    fill()


def open_action(A, act):
    try:
        if act == "cleaner":
            A.open_cleaner()
        elif act == "largest":
            A.open_largest()
        elif act == "taskmgr":
            subprocess.Popen(["taskmgr.exe", "/7"])  # Task Manager, Startup apps page
        elif act == "update":
            ff_platform.open_os_settings("windows_update")
        elif act == "security":
            ff_platform.open_os_settings("security_center")
        elif act == "storage":
            ff_platform.open_os_settings("storage")
        elif act == "devmgr":
            subprocess.Popen(["mmc.exe", "devmgmt.msc"])
        elif act == "backup":
            A.open_health("backups")
        elif act == "health":
            A.open_health()
        elif act == "autoclean":
            A.open_autoclean()
        elif act == "sectab":
            A.open_health("sec")
        elif act == "about":
            A.open_about()
        elif act == "malware":
            A.open_malware()
    except OSError as e:
        A.status.set(f"Couldn't open that: {e}")


def show_toast(A, text, label, action):
    """A small corner pop-up (never steals focus) for low disk space and overdue backups."""
    t = tk.Toplevel(A.root)
    t.overrideredirect(True)
    t.attributes("-topmost", True)
    t.configure(bg=T["accent"])
    inner = tk.Frame(t, bg=T["panel"])
    inner.pack(padx=2, pady=2)
    tk.Label(inner, text="❤  Foldwise health", fg=T["accent"], bg=T["panel"],
             font=("Segoe UI", A.cfg["font_size"] - 1, "bold")).pack(anchor="w", padx=14, pady=(10, 0))
    tk.Label(inner, text=text, wraplength=360, justify="left", fg=T["fg"], bg=T["panel"],
             font=("Segoe UI", A.cfg["font_size"])).pack(anchor="w", padx=14, pady=8)
    row = tk.Frame(inner, bg=T["panel"])
    row.pack(anchor="e", padx=12, pady=(0, 10))
    ttk.Button(row, text=label, style="Accent.TButton", command=lambda: (t.destroy(), A.open_action(action))).pack(side="left", padx=4)
    ttk.Button(row, text="Dismiss", command=t.destroy).pack(side="left")
    t.update_idletasks()
    sw_, sh_ = A.root.winfo_screenwidth(), A.root.winfo_screenheight()
    t.geometry(f"+{sw_ - t.winfo_width() - 24}+{sh_ - t.winfo_height() - 72}")
    t.after(30000, lambda: t.winfo_exists() and t.destroy())
    return t


def health_watch(A):
    """Hourly: remember free space (for the trend graph) and warn about nearly-full drives / overdue backups."""
    def work():
        try:
            drives = HL.disk_report()
        except Exception:
            drives = []
        threats = None
        try:
            HL.history_add(A.hist_path, "hourly", HL.hourly_sample())
            threats = HL.defender_threats(30)
        except Exception as e:  # noqa
            log_error(f"hourly sample: {e}")
        A.root.after(0, A.check, drives)
        if threats is not None:
            A.root.after(0, A.threat_check, threats)
    threading.Thread(target=work, daemon=True).start()
    A.root.after(3600 * 1000, A.health_watch)


def check(A, drives):
    if drives:
        A.save_cfg(space_history=HL.record_snapshot(A.cfg["space_history"], drives))
    A.weekly_check()
    if not A.cfg["health_alerts"]:
        return
    today, alerted = time.strftime("%Y-%m-%d"), dict(A.cfg["alerted"])

    def alert(key, text, label, action):
        if alerted.get(key) != today:
            alerted[key] = today
            A.save_cfg(alerted=alerted)
            A.show_toast(text, label, action)

    for d in drives:
        if d["kind"] == "Fixed" and (d["pct_free"] < 10 or d["free"] < 10 * 2 ** 30):
            alert("space:" + d["root"], f"{d['root'].rstrip(chr(92))} is almost full — only {human_size(d['free'])} free.",
                  "Open the cleaner", "cleaner")
            return
    for j in A.cfg["backups"]:
        added = j.get("added", time.time())
        if j.get("last"):
            days = (time.time() - j["last"]) / 86400
        else:
            days = (time.time() - added) / 86400 if time.time() - added > 3 * 86400 else None
        if days is not None and days > 14:
            nm = os.path.basename(j["src"].rstrip("\\")) or j["src"]
            alert("backup:" + j["src"], f"Your backup of “{nm}” is {days:.0f} days old." if j.get("last")
                  else f"Your backup of “{nm}” has never been run.", "Back up now", "backup")
            return


def threat_check(A, found):
    """Toast once for every NEW Defender detection (the ones already there when this feature started are only noted)."""
    seen = set(A.cfg["seen_threats"])
    new = HL.new_threats(found, seen)
    if new:
        A.save_cfg(seen_threats=(A.cfg["seen_threats"] + [HL.threat_key(t) for t in new])[-200:])
    if not A.cfg["threats_init"]:
        A.save_cfg(threats_init=True)
        return
    if new and A.cfg["health_alerts"]:
        t = new[0]
        what = " (found in a command line, not a file)" if (t.get("Res") or "").startswith("CmdLine") else ""
        A.show_toast(f"Windows Defender detected {t.get('Name') or 'a threat'}{what} at {t['Time']}." + (f" +{len(new) - 1} more." if len(new) > 1 else ""),
                   "Open security check", "sectab")


def weekly_check(A):
    """Once a week (when enabled): run every health check in the background and pop a one-line summary."""
    if not A.cfg["weekly_summary"] or time.time() - A.cfg["last_weekly"] < 7 * 86400:
        return
    A.save_cfg(last_weekly=time.time())

    def work():
        try:
            h = HL.collect(A.cfg["backups"], A.cfg["space_history"])
            text, _n = HL.weekly_summary(h)
            A.root.after(0, A.set_score, HL.recommendations(h)[1])
        except Exception as e:  # noqa
            log_error(f"weekly summary: {e}")
            return
        A.root.after(0, lambda: A.show_toast(text, "Open PC health", "health"))
        A.notify("Foldwise weekly check-up", text)
    threading.Thread(target=work, daemon=True).start()


def set_score(A, score):
    """Show the latest PC health score on the toolbar button (and remember it for the next start)."""
    if score is None:
        return
    if A.cfg.get("last_score") != score:
        A.save_cfg(last_score=score)
    label = f"⚙ Tools  ❤{score}"
    A.health_btn.configure(text=label)
    for it in A.cmd_items:
        if it["w"] is A.health_btn:
            it["label"] = label
    A.lay["sig"] = None
    A.root.after(10, A.layout_cmdbar)


def set_job_fields(A, src, dst, **fields):
    jobs = [dict(j) for j in A.cfg["backups"]]
    for j in jobs:
        if j["src"] == src and j["dst"] == dst:
            j.update(fields)
    A.save_cfg(backups=jobs)
    for h_ in list(A.bk_hooks):
        try:
            h_()
        except tk.TclError:
            A.bk_hooks.remove(h_)


def folders_tick(A):
    """Weekly while idle: remember how big your main folders are, so the Trends tab can say which ones are growing."""
    if time.time() - A.cfg["last_folder_snap"] < 7 * 86400 or HL.idle_seconds() < 120:
        return
    A.save_cfg(last_folder_snap=time.time())

    def work():
        try:
            sizes = HL.folder_snapshot(pause=0.002)
            if sizes:
                HL.history_add(A.hist_path, "folders", {"t": time.time(), "sizes": sizes})
        except Exception as e:  # noqa
            log_error(f"folder snapshot: {e}")
    threading.Thread(target=work, daemon=True).start()


def perf_tick(A):
    """Every 5 minutes: remember CPU/RAM load for the Trends tab (cheap; runs in a thread)."""
    def work():
        try:
            HL.history_add(A.hist_path, "perf", HL.perf_sample())
        except Exception as e:  # noqa
            log_error(f"perf sample: {e}")
    threading.Thread(target=work, daemon=True).start()


def bk_tick(A):
    """Every 5 minutes: start ONE due scheduled backup, only while the PC is idle for 2+ minutes."""
    A.root.after(300 * 1000, A.bk_tick)
    A.perf_tick()
    folders_tick(A)
    A.track_tick()
    if A.bk_running or HL.idle_seconds() < 120:
        return
    job = next((j for j in A.cfg["backups"] if HL.job_due(j)), None)
    if not job:
        return
    key = (job["src"], job["dst"])
    A.bk_running.add(key)
    A.set_job_fields(*key, attempt=time.time(), result="Running scheduled backup…")

    def work():
        ok, msg = HL.run_scheduled(job, lambda: HL.idle_seconds() < 15, human_size)  # pause when the user is back
        A.root.after(0, done, key, ok, msg)

    def done(key, ok, msg):
        A.bk_running.discard(key)
        f = dict(result=msg, ok=ok, attempt=time.time())
        if ok:
            f["last"] = time.time()
        A.set_job_fields(*key, **f)
        A.status.set("Scheduled backup: " + msg)
        if not ok and A.cfg["health_alerts"] and not msg.startswith(("Skipped", "Cancelled", "Paused"))                     and A.cfg["alerted"].get("bkfail:" + key[0]) != time.strftime("%Y-%m-%d"):
            A.save_cfg(alerted={**A.cfg["alerted"], "bkfail:" + key[0]: time.strftime("%Y-%m-%d")})
            nm = os.path.basename(key[0].rstrip("\\")) or key[0]
            A.show_toast(f"The scheduled backup of “{nm}” didn't complete: {msg}.", "See backups", "backup")
    threading.Thread(target=work, daemon=True).start()


def autoclean_now(A, done_cb=None):
    if A.ac_state["running"]:
        return
    A.ac_state["running"] = True

    def work():
        try:
            res = CL.autoclean_run(A.qroot, protected=A.cfg["cleaner_protected"])
        except Exception as e:  # noqa
            log_error(f"autoclean: {e}")
            res = {"batch": None, "moved": 0, "freed": 0, "failed": [("-", str(e))]}
        A.root.after(0, finished, res)

    def finished(res):
        A.ac_state["running"] = False
        log = (A.cfg["autoclean_log"] + [{"t": time.time(), "moved": res["moved"], "freed": res["freed"], "failed": len(res["failed"])}])[-20:]
        A.save_cfg(last_autoclean=time.time(), autoclean_log=log)
        A.status.set(f"Auto-clean: {res['moved']} item(s), {human_size(res['freed'])} moved to the restore list")
        if res["moved"] and A.cfg["health_alerts"]:
            A.show_toast(f"Auto-clean freed {human_size(res['freed'])} ({res['moved']} items). You can restore them for 7 days.", "Open restore list", "autoclean")
        if done_cb:
            done_cb(res)
    threading.Thread(target=work, daemon=True).start()


def autoclean_tick(A):
    A.root.after(30 * 60 * 1000, A.autoclean_tick)
    try:
        CL.purge_quarantine(A.qroot, 7)
    except Exception as e:  # noqa
        log_error(f"quarantine purge: {e}")
    if A.cfg["autoclean"] and not A.ac_state["running"] and HL.idle_seconds() >= 180 \
            and time.time() - A.cfg["last_autoclean"] >= A.cfg["autoclean_days"] * 86400:
        A.autoclean_now()
