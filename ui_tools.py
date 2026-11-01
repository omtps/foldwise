"""File tools: checksum, image convert, integrity check, OCR, folder sync, FTP/SFTP, photo details, disk map, compare, bulk rename, settings export/import.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import ff_extras as X
import ff_health as HL
import os
import re
import threading
import ui_extras
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from ff_core import ThemedBox as messagebox
from tkinter import ttk
from ff_core import (DB_DIR, DEFAULT_CFG, IMG_EXTS, Path, T, blend, dir_stats, fmt_date, human_size, log_error, recycle)


def ask_rows(A, title, types=(("All files", "*.*"),), multiple=False, folder=False):
    """Selected-file tools also work from the Tools list: when nothing suitable is selected, ask with a file / folder dialog."""
    from tkinter import filedialog
    kw = dict(parent=A.root, title=title, initialdir=A.st["cwd"] if os.path.isdir(A.st["cwd"]) else None)
    if folder:
        paths = [filedialog.askdirectory(**kw)]
    elif multiple:
        paths = list(filedialog.askopenfilenames(filetypes=types, **kw))
    else:
        paths = [filedialog.askopenfilename(filetypes=types, **kw)]
    rows = []
    for p in paths:
        if p and os.path.exists(p):
            p = os.path.normpath(p)
            st_ = os.stat(p)
            rows.append((os.path.basename(p) or p, p, 0 if os.path.isdir(p) else st_.st_size, st_.st_mtime, os.path.isdir(p)))
    return rows


def open_checksum(A):
    s_ = [r for r in A.sel() if not r[4] and not X.zip_is_virtual(r[1])]
    if not s_:
        s_ = [r for r in ask_rows(A, "Choose a file to checksum") if not r[4]]
    if not s_:
        return
    r = s_[0]
    win = A.toplevel(f"Checksum — {r[0]}", "860x400")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    f = ttk.Frame(win, padding=18)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text=r[1], wraplength=800, style="DetKey.TLabel", background=T["bg"]).pack(anchor="w")
    prog = ttk.Progressbar(f, mode="determinate", maximum=max(1, r[2]))
    prog.pack(fill="x", pady=(10, 14))
    vals = {}
    for algo in ("MD5", "SHA-1", "SHA-256"):
        fr = ttk.Frame(f)
        fr.pack(fill="x", pady=4)
        ttk.Label(fr, text=algo, width=9).pack(side="left")
        ev = tk.StringVar(value="calculating…")
        ttk.Entry(fr, textvariable=ev, state="readonly", font=("Consolas", 10)).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(fr, text="Copy", command=lambda ev=ev: (A.root.clipboard_clear(), A.root.clipboard_append(ev.get()),
                                                           A.status.set("Checksum copied"))).pack(side="left")
        vals[algo] = ev
    ttk.Label(f, text="Compare with a checksum you were given (paste it here):").pack(anchor="w", pady=(18, 4))
    cmpv = tk.StringVar()
    ttk.Entry(f, textvariable=cmpv, font=("Consolas", 10)).pack(fill="x")
    result = tk.Label(f, text="", bg=T["bg"], fg=T["fg"], font=("Segoe UI", A.cfg["font_size"] + 2, "bold"), anchor="w")
    result.pack(fill="x", pady=10)

    def check(*_):
        given = re.sub(r"\s+", "", cmpv.get()).lower()
        if not given:
            result.configure(text="")
            return
        ok = any(given == v.get().lower() for v in vals.values())
        result.configure(text="✔  Matches — the file is intact" if ok else "✖  Does not match",
                         fg="#4ade80" if ok else "#f87171")

    cmpv.trace_add("write", check)

    def work():
        try:
            res = X.file_hashes(r[1], lambda: not alive["v"], lambda n: alive["v"] and A.root.after(0, lambda: alive["v"] and prog.configure(value=n)))
        except OSError as e:
            res = {k: f"error: {e}" for k in vals}
        if res and alive["v"]:
            A.root.after(0, lambda: alive["v"] and (prog.configure(value=prog["maximum"]), [vals[k].set(v) for k, v in res.items()], check()))
    threading.Thread(target=work, daemon=True).start()


def open_convert_images(A):
    imgs = [r for r in A.sel() if not r[4] and os.path.splitext(r[0])[1][1:].lower() in IMG_EXTS and not X.zip_is_virtual(r[1])]
    if not imgs:
        imgs = [r for r in ask_rows(A, "Choose the images to convert or resize", (("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff"),), True) if not r[4]]
    if not imgs:
        return
    win = A.toplevel(f"Convert / resize {len(imgs)} image(s)", "560x430")
    f = ttk.Frame(win, padding=20)
    f.pack(fill="both", expand=True)
    total = sum(r[2] for r in imgs)
    ttk.Label(f, text=f"{len(imgs)} image(s), {human_size(total)}. Originals are never changed — copies go into a “Converted” folder next to them.",
              wraplength=500).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
    fmt = tk.StringVar(value="Keep each file's format")
    size = tk.StringVar(value="Original size")
    quality = tk.IntVar(value=85)
    ttk.Label(f, text="Format").grid(row=1, column=0, sticky="w", pady=6)
    ttk.Combobox(f, textvariable=fmt, state="readonly", width=26,
                 values=["Keep each file's format", "JPEG", "PNG", "WebP"]).grid(row=1, column=1, sticky="w")
    ttk.Label(f, text="Longest side").grid(row=2, column=0, sticky="w", pady=6)
    ttk.Combobox(f, textvariable=size, state="readonly", width=26,
                 values=["Original size", "3840 px (4K)", "2560 px", "1920 px (Full HD)", "1280 px", "800 px", "400 px"]).grid(row=2, column=1, sticky="w")
    ttk.Label(f, text="Quality (JPEG / WebP)").grid(row=3, column=0, sticky="w", pady=6)
    qf = ttk.Frame(f)
    qf.grid(row=3, column=1, sticky="w")
    qv = tk.StringVar(value="85")
    ttk.Scale(qf, from_=40, to=100, variable=quality, length=170, command=lambda v: qv.set(str(int(float(v))))).pack(side="left")
    ttk.Label(qf, textvariable=qv, width=4).pack(side="left", padx=8)
    info_v = tk.StringVar()
    ttk.Label(f, textvariable=info_v, wraplength=500).grid(row=4, column=0, columnspan=2, sticky="w", pady=14)
    btns = ttk.Frame(f)
    btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))

    def go():
        fmt_key = {"Keep each file's format": "keep", "JPEG": "jpg", "PNG": "png", "WebP": "webp"}[fmt.get()]
        side_px = 0 if size.get() == "Original size" else int(size.get().split()[0])
        outdir = os.path.join(A.st["cwd"], "Converted")
        info_v.set("Working…")
        go_b.state(["disabled"])

        def work():
            res = X.convert_images([r[1] for r in imgs], outdir, fmt_key, side_px, quality.get(),
                                   lambda i, n, name: A.root.after(0, info_v.set, f"Converting {i + 1}/{n}: {name}"))
            A.root.after(0, done, *res)

        def done(outs, fails):
            if outs:
                A.push_undo("create", outs)
            size_after = sum(os.path.getsize(o) for o in outs if os.path.exists(o))
            msg = f"Converted {len(outs)} image(s): {human_size(total)} → {human_size(size_after)}"
            if fails:
                msg += f"   •   {len(fails)} failed (e.g. {fails[0][0]}: {fails[0][1]})"
            A.status.set(msg + "   •   Ctrl+Z to undo")
            try:
                win.destroy()
            except tk.TclError:
                pass
            A.after_change()

        threading.Thread(target=work, daemon=True).start()

    go_b = ttk.Button(btns, text="Convert", style="Accent.TButton", command=go)
    go_b.pack(side="left")
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=8)


def open_integrity(A):
    folder = A.st["cwd"]
    if X.zip_is_virtual(folder) or not os.path.isdir(folder):
        A.status.set("Open a real folder first")
        return
    store = str(DB_DIR / "manifests")
    win = A.toplevel("Integrity check", "900x600")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    ttk.Label(win, text=f"{folder}", padding=(14, 12, 14, 0), style="DetKey.TLabel").pack(fill="x")
    ttk.Label(win, text="Create a fingerprint (SHA-256) of every file now; later, Verify tells you which files were changed, deleted, "
              "added — or silently corrupted (content changed although size and date didn't, a sign of a failing disk).",
              wraplength=860, padding=(14, 4, 14, 8)).pack(fill="x")
    msg = tk.StringVar(value="")
    ttk.Label(win, textvariable=msg, padding=(14, 4)).pack(fill="x")
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=10)
    tv = ttk.Treeview(frm, columns=("what",), show="tree headings")
    tv.heading("#0", text="File", anchor="w")
    tv.heading("what", text="Finding", anchor="w")
    tv.column("#0", width=640)
    tv.column("what", width=200)
    tv.tag_configure("corrupt", foreground="#f87171")
    tv.tag_configure("modified", foreground="#facc15")
    tv.tag_configure("missing", foreground="#fb923c")
    sb_ = ttk.Scrollbar(frm, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb_.set)
    sb_.pack(side="right", fill="y")
    tv.pack(fill="both", expand=True)
    busy = {"v": False}

    def prog(n, name):
        if alive["v"] and n % 20 == 0:
            A.root.after(0, lambda: alive["v"] and msg.set(f"Reading {n:,} files… {name}"))

    def run(kind):
        if busy["v"]:
            return
        busy["v"] = True
        tv.delete(*tv.get_children())
        msg.set("Working…")

        def work():
            try:
                res = (X.manifest_create if kind == "create" else X.manifest_verify)(folder, store, lambda: not alive["v"], prog)
            except Exception as e:  # noqa
                log_error(f"integrity {kind}: {e}")
                res = None
            A.root.after(0, lambda: alive["v"] and done(kind, res))
        threading.Thread(target=work, daemon=True).start()

    def done(kind, res):
        busy["v"] = False
        if res is None:
            msg.set("No saved fingerprint for this folder yet — press “Create fingerprint” first." if kind == "verify" else "Cancelled.")
            return
        if kind == "create":
            msg.set(f"Fingerprint saved for {res:,} file(s).")
            return
        for key, label in (("corrupt", "POSSIBLY CORRUPTED"), ("modified", "changed"), ("missing", "deleted / moved")):
            for rel in res[key]:
                tv.insert("", "end", text=rel, values=(label,), tags=(key,))
        for rel in res["new"][:2000]:
            tv.insert("", "end", text=rel, values=("new file",))
        bad = len(res["corrupt"])
        msg.set(f"{res['ok']:,} file(s) unchanged; {len(res['modified'])} changed, {len(res['missing'])} deleted, {len(res['new'])} new"
                + (f"; ⚠ {bad} possibly CORRUPTED" if bad else ".") + f"   (fingerprint from {fmt_date(res['created'])})")
        if bad:
            A.status.set(f"Integrity check: {bad} possibly corrupted file(s) in {folder}")

    bt = ttk.Frame(win, padding=12)
    bt.pack(fill="x")
    ttk.Button(bt, text="Create fingerprint", style="Accent.TButton", command=lambda: run("create")).pack(side="left")
    ttk.Button(bt, text="Verify now", command=lambda: run("verify")).pack(side="left", padx=8)
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    if X.manifest_load(folder, store):
        msg.set("A fingerprint exists for this folder. Press Verify now to check it.")


def open_ocr(A):
    """Read the text out of a selected image or (scanned) PDF with Windows' built-in OCR; copy or save it."""
    import ff_ocr
    s_ = [r for r in A.sel() if not r[4] and os.path.splitext(r[1])[1].lower() in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".pdf")
          and not X.zip_is_virtual(r[1])]
    if not s_:
        s_ = [r for r in ask_rows(A, "Choose an image or a PDF", (("Images and PDFs", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.pdf"),)) if not r[4]]
    if not s_:
        return
    if not ff_ocr.available():
        A.status.set("Text recognition isn't available on this PC")
        return
    path = s_[0][1]
    win = A.toplevel(f"Text in {s_[0][0]}", "760x600")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    msg = tk.StringVar(value="Reading the text\u2026")
    ttk.Label(win, textvariable=msg, padding=(14, 12, 14, 4)).pack(fill="x")
    txt = tk.Text(win, bg=T["panel"], fg=T["fg"], relief="flat", wrap="word", font=("Segoe UI", A.cfg["font_size"]), padx=12, pady=10)
    txt.pack(fill="both", expand=True, padx=14)
    bt = ttk.Frame(win, padding=12)
    bt.pack(fill="x")

    def work():
        try:
            if path.lower().endswith(".pdf"):
                out = ff_ocr.ocr_pdf(path, 40, cancel=lambda: not alive["v"])
            else:
                from PIL import Image
                out = ff_ocr.ocr_image(Image.open(path))
        except Exception as e:  # noqa
            log_error(f"ocr {path}: {e}")
            out = ""
        A.root.after(0, lambda: alive["v"] and done(out))

    def done(out):
        txt.insert("1.0", out or "")
        msg.set(f"{len(out.split()):,} words found." if out.strip() else "No text was found in this file.")

    def copy():
        A.root.clipboard_clear()
        A.root.clipboard_append(txt.get("1.0", "end").strip())
        A.status.set("Text copied")

    def save():
        from tkinter import filedialog
        p_ = filedialog.asksaveasfilename(parent=win, defaultextension=".txt", initialfile=os.path.splitext(s_[0][0])[0] + ".txt")
        if p_:
            Path(p_).write_text(txt.get("1.0", "end").strip(), encoding="utf-8")
            A.after_change()

    ttk.Button(bt, text="Copy text", style="Accent.TButton", command=copy).pack(side="left")
    ttk.Button(bt, text="Save as .txt\u2026", command=save).pack(side="left", padx=8)
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    threading.Thread(target=work, daemon=True).start()


def open_sync(A):
    from tkinter import filedialog
    win = A.toplevel("Sync two folders", "980x680")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    a_v, b_v = tk.StringVar(value=A.st["cwd"] if os.path.isdir(A.st["cwd"]) else ""), tk.StringVar()
    top = ttk.Frame(win, padding=(14, 12))
    top.pack(fill="x")
    for r_, (lab, var) in enumerate((("Folder A", a_v), ("Folder B", b_v))):
        ttk.Label(top, text=lab, width=9).grid(row=r_, column=0, pady=3)
        ttk.Entry(top, textvariable=var, width=80).grid(row=r_, column=1, sticky="we", pady=3)
        ttk.Button(top, text="Browse…", command=lambda v=var: (lambda p_: v.set(os.path.normpath(p_)) if p_ else None)(
            filedialog.askdirectory(parent=win))).grid(row=r_, column=2, padx=6)
    top.columnconfigure(1, weight=1)
    ttk.Label(win, text="Keeps both folders identical: files missing on one side are copied over, and when both have a file the NEWER one wins. "
              "Nothing is ever deleted. A file that gets replaced is first saved in a “.sync-old” folder. Same date but different size = conflict (left alone).",
              wraplength=930, padding=(14, 0, 14, 6)).pack(fill="x")
    msg = tk.StringVar(value="")
    ttk.Label(win, textvariable=msg, padding=(14, 4)).pack(fill="x")
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=10)
    tv = ttk.Treeview(frm, columns=("what", "size"), show="tree headings")
    tv.heading("#0", text="File", anchor="w")
    tv.heading("what", text="Will happen", anchor="w")
    tv.heading("size", text="Size", anchor="e")
    tv.column("#0", width=520)
    tv.column("what", width=260)
    tv.column("size", width=100, anchor="e")
    sb_ = ttk.Scrollbar(frm, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb_.set)
    sb_.pack(side="right", fill="y")
    tv.pack(fill="both", expand=True)
    S = {"plan": None, "busy": False}
    go_b = ttk.Button(win, text="Sync now", style="Accent.TButton", state="disabled")

    def paths():
        a, b = os.path.normpath(a_v.get().strip()), os.path.normpath(b_v.get().strip())
        if not a_v.get().strip() or not b_v.get().strip() or not os.path.isdir(a) or not os.path.isdir(b):
            msg.set("Choose two existing folders.")
            return None
        err = HL._guard(a, b)
        if err:
            msg.set("The folders can't be inside each other.")
            return None
        return a, b

    def preview():
        p = paths()
        if not p or S["busy"]:
            return
        S["busy"] = True
        tv.delete(*tv.get_children())
        go_b.configure(state="disabled")

        def work():
            plan = X.sync_plan(p[0], p[1], lambda: not alive["v"], lambda m: alive["v"] and A.root.after(0, lambda: alive["v"] and msg.set(m)))
            A.root.after(0, lambda: alive["v"] and shown(plan, p))
        threading.Thread(target=work, daemon=True).start()

    def shown(plan, p):
        S["busy"] = False
        if plan is None:
            return
        S["plan"], S["p"] = plan, p
        for src, dst, rel, size, over in plan["copy"][:3000]:
            to = "A" if os.path.normcase(dst).startswith(os.path.normcase(p[0]) + "\\") else "B"
            tv.insert("", "end", text=rel, values=(f"copy to {to}" + (" (replaces an older version)" if over else ""), human_size(size or 0)))
        for rel in plan["conflicts"][:500]:
            tv.insert("", "end", text=rel, values=("conflict — skipped", ""))
        tot = sum(c[3] or 0 for c in plan["copy"])
        msg.set(f"{len(plan['copy']):,} file(s) to copy ({human_size(tot)}), {len(plan['conflicts'])} conflict(s), {plan['same']:,} already identical."
                if plan["copy"] else f"Already in sync ({plan['same']:,} identical file(s), {len(plan['conflicts'])} conflict(s)).")
        go_b.configure(state="normal" if plan["copy"] else "disabled")

    def go():
        plan, p = S["plan"], S.get("p")
        if not plan or S["busy"] or not messagebox.askyesno("Sync", f"Copy {len(plan['copy']):,} file(s) between the two folders?\n\nNothing will be deleted.", parent=win):
            return
        S["busy"] = True
        go_b.configure(state="disabled")

        def work():
            res = X.run_sync(plan, p[0], p[1], lambda: not alive["v"],
                             lambda i, n, name: alive["v"] and A.root.after(0, lambda: alive["v"] and msg.set(f"Copying {i + 1}/{n}: {name}")))
            A.root.after(0, lambda: finished(res))
        threading.Thread(target=work, daemon=True).start()

    def finished(res):
        S["busy"] = False
        A.status.set(f"Sync finished: {res['copied']} file(s) copied" + (f", {len(res['errors'])} failed" if res["errors"] else ""))
        if alive["v"]:
            msg.set(f"Done: {res['copied']} copied ({human_size(res['bytes'])}), {res['kept_old']} older version(s) kept in .sync-old"
                    + (f", {len(res['errors'])} failed (e.g. {res['errors'][0][0]}: {res['errors'][0][1]})" if res["errors"] else "."))
        A.after_change()

    go_b.configure(command=go)
    bt = ttk.Frame(win, padding=12)
    bt.pack(fill="x")
    ttk.Button(bt, text="Preview", command=preview).pack(side="left")
    go_b.pack(in_=bt, side="left", padx=8)

    def prune_old():
        p = paths()
        if not p:
            return
        n, size = X.sync_old_size(p[0], p[1])
        if not n:
            msg.set("No saved older versions (.sync-old) in these two folders.")
            return
        if messagebox.askyesno("Older versions", f"Move {n:,} saved older version(s) ({human_size(size)}) older than 30 days to the Recycle Bin?", parent=win):
            old = X.sync_old_paths(p[0], p[1], days=30)
            if old and recycle(old):
                msg.set(f"{len(old)} old version folder(s) moved to the Recycle Bin.")
            else:
                msg.set("Nothing was old enough to remove.")

    ttk.Button(bt, text="Clean old versions\u2026", command=prune_old).pack(side="left")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")


def open_ftp(A):
    win = A.toplevel("FTP / FTPS / SFTP server", "860x640")
    alive = {"v": True, "conn": None}

    def on_destroy(e):
        if e.widget is win:
            alive["v"] = False
            if alive["conn"]:
                threading.Thread(target=alive["conn"].close, daemon=True).start()
    win.bind("<Destroy>", on_destroy)
    top = ttk.Frame(win, padding=(14, 12, 14, 4))
    top.pack(fill="x")
    host_v, port_v, user_v, pw_v, tls_v = tk.StringVar(value=A.cfg["ftp_host"]), tk.StringVar(value="21"), tk.StringVar(value=A.cfg["ftp_user"] or "anonymous"), tk.StringVar(), tk.StringVar(value="FTP")
    for c_, (lab, var, w_, show) in enumerate((("Server", host_v, 24, ""), ("Port", port_v, 6, ""), ("User", user_v, 14, ""), ("Password", pw_v, 14, "\u2022"))):
        ttk.Label(top, text=lab).grid(row=0, column=c_ * 2, padx=(0, 4))
        ttk.Entry(top, textvariable=var, width=w_, show=show).grid(row=0, column=c_ * 2 + 1, padx=(0, 10))
    ttk.Label(top, text="Protocol").grid(row=1, column=0, padx=(0, 4), pady=4, sticky="e")
    proto_cb = ttk.Combobox(top, textvariable=tls_v, values=["FTP", "FTPS (encrypted)"] + (["SFTP (SSH)"] if X.sftp_available() else []) + ["WebDAV (full https:// address in Server)"], width=34, state="readonly")
    proto_cb.grid(row=1, column=1, columnspan=2, sticky="w")
    proto_cb.bind("<<ComboboxSelected>>", lambda e: port_v.set("22" if tls_v.get().startswith("SFTP") else "21"))
    conn_b = ttk.Button(top, text="Connect", style="Accent.TButton")
    conn_b.grid(row=1, column=6, columnspan=2, sticky="e")
    msg = tk.StringVar(value="Enter a server and press Connect. The password is never saved.")
    ttk.Label(win, textvariable=msg, padding=(14, 4), wraplength=820).pack(fill="x")
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=10)
    tv = ttk.Treeview(frm, columns=("size",), show="tree headings", selectmode="extended")
    tv.heading("#0", text="Name", anchor="w")
    tv.heading("size", text="Size", anchor="e")
    tv.column("#0", width=600)
    tv.column("size", width=120, anchor="e")
    sb_ = ttk.Scrollbar(frm, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb_.set)
    sb_.pack(side="right", fill="y")
    tv.pack(fill="both", expand=True)
    rows = {}
    busy = {"v": False}

    def run_bg(fn, done, err="Failed"):
        if busy["v"]:
            return
        busy["v"] = True

        def work():
            try:
                r_ = fn()
                e_ = None
            except Exception as ex:  # noqa
                r_, e_ = None, ex
            A.root.after(0, lambda: fin(r_, e_))

        def fin(r_, e_):
            busy["v"] = False
            if not alive["v"]:
                return
            if e_:
                msg.set(f"{err}: {e_}")
            else:
                done(r_)
        threading.Thread(target=work, daemon=True).start()

    def show_list(res):
        pwd, lst = res
        tv.delete(*tv.get_children())
        rows.clear()
        tv.insert("", "end", iid="..", text="\U0001F4C1  ..  (up one level)")
        for i, (name, isdir, size, mt) in enumerate(lst):
            rows[str(i)] = (name, isdir)
            tv.insert("", "end", iid=str(i), text=("\U0001F4C1  " if isdir else "\U0001F4C4  ") + name, values=("" if isdir else human_size(size),))
        msg.set(f"{host_v.get()}:{pwd}   \u2014   {len(lst)} item(s)")

    def refresh_list():
        c = alive["conn"]
        run_bg(lambda: (c.pwd(), c.listdir()), show_list, "Couldn't list this folder")

    def connect():
        def confirm_key(host, fp):
            ev, ans = threading.Event(), {"ok": False}

            def ask():
                ans["ok"] = messagebox.askyesno("New server", f"This is the first time you connect to {host}.\n\nIts key fingerprint is:\n{fp}\n\nTrust this server and continue?", parent=win)
                ev.set()
            A.root.after(0, ask)
            ev.wait(120)
            return ans["ok"]

        def go():
            if tls_v.get().startswith("WebDAV"):
                c = X.WebDavConn(host_v.get().strip(), user=user_v.get().strip(), password=pw_v.get())
            elif tls_v.get().startswith("SFTP"):
                c = X.SftpConn(host_v.get().strip(), port_v.get() or 22, user_v.get().strip(), pw_v.get(), confirm_key, str(DB_DIR / "known_hosts"))
            else:
                c = X.FtpConn(host_v.get().strip(), port_v.get() or 21, user_v.get().strip(), pw_v.get(), tls_v.get().startswith("FTPS"))
            return c, (c.pwd(), c.listdir())

        def ok(res):
            if alive["conn"]:
                threading.Thread(target=alive["conn"].close, daemon=True).start()
            alive["conn"] = res[0]
            A.save_cfg(ftp_host=host_v.get().strip(), ftp_user=user_v.get().strip())
            show_list(res[1])
        run_bg(go, ok, "Couldn't connect")
        msg.set("Connecting\u2026")

    conn_b.configure(command=connect)

    def open_row(_=None):
        c = alive["conn"]
        sel_ = tv.selection()
        if not c or not sel_:
            return
        if sel_[0] == "..":
            run_bg(lambda: (c.up(), (c.pwd(), c.listdir()))[1], show_list)
        elif rows.get(sel_[0], (0, False))[1]:
            name = rows[sel_[0]][0]
            run_bg(lambda: (c.cd(name), (c.pwd(), c.listdir()))[1], show_list)

    tv.bind("<Double-1>", open_row)

    def download():
        c = alive["conn"]
        names = [rows[i][0] for i in tv.selection() if i in rows and not rows[i][1]]
        dest = A.st["cwd"]
        if not c or not names or X.zip_is_virtual(dest):
            msg.set("Select one or more FILES to download (they go into the folder Foldwise is showing).")
            return
        if not messagebox.askyesno("Download", f"Download {len(names)} file(s) from {host_v.get()} into\n{dest}?", parent=win):
            return

        def go():
            out = []
            for n in names:
                out.append(c.download(n, dest, lambda k, n=n: alive["v"] and A.root.after(0, lambda: alive["v"] and msg.set(f"Downloading {n}: {human_size(k)}"))))
            return out
        run_bg(go, lambda out: (msg.set(f"Downloaded {len(out)} file(s) into {dest}"), A.after_change()), "Download failed")

    def upload():
        c = alive["conn"]
        files = [r[1] for r in A.sel() if not r[4] and not X.zip_is_virtual(r[1])]
        if not c or not files:
            msg.set("Select local FILES in Foldwise's list first, then press Upload.")
            return
        if not messagebox.askyesno("Upload", f"Upload {len(files)} file(s) to {host_v.get()}?", parent=win):
            return

        def go():
            for p in files:
                c.upload(p)
            return (c.pwd(), c.listdir())
        run_bg(go, show_list, "Upload failed")

    bt = ttk.Frame(win, padding=12)
    bt.pack(fill="x")
    ttk.Button(bt, text="Download selected", style="Accent.TButton", command=download).pack(side="left")
    ttk.Button(bt, text="Upload selected files from Foldwise", command=upload).pack(side="left", padx=8)
    ttk.Button(bt, text="Refresh", command=refresh_list).pack(side="left")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")


def open_vault(A):
    """Lock the selected folder into an encrypted .ffvault file, or unlock the selected .ffvault."""
    import ff_vault
    s = A.sel()
    ok = bool(s) and not X.zip_is_virtual(s[0][1]) and (s[0][4] or s[0][1].lower().endswith(".ffvault"))
    if not ok:
        if messagebox.askyesno("Encrypted vault", "Lock a folder into a vault?\n\nYes = choose a folder to lock.\nNo = choose a .ffvault file to unlock.", parent=A.root):
            s = ask_rows(A, "Choose the folder to lock", folder=True)
        else:
            s = ask_rows(A, "Choose the vault to unlock", (("Foldwise vault", "*.ffvault"),))
    if not s:
        return
    item = s[0]
    unlocking = (not item[4]) and item[1].lower().endswith(".ffvault")
    if not unlocking and not item[4]:
        A.status.set("That is not a folder or a .ffvault file")
        return
    win = A.toplevel("Unlock vault" if unlocking else "Lock folder into an encrypted vault", "640x470")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    f = ttk.Frame(win, padding=20)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text=item[1], style="DetKey.TLabel", background=T["bg"], wraplength=590).pack(anchor="w")
    if unlocking:
        ttk.Label(f, text="Enter the password. The vault is decrypted into a new folder next to it; the vault file itself is not changed.", wraplength=590).pack(anchor="w", pady=8)
    else:
        ttk.Label(f, text="Everything in this folder is packed into ONE file and encrypted with AES-256. There is NO way to recover the data if you forget the password. "
                  "Your original folder is not touched unless you tick the box below.", wraplength=590).pack(anchor="w", pady=8)
    pw1, pw2, rm = tk.StringVar(), tk.StringVar(), tk.BooleanVar(value=False)
    ttk.Label(f, text="Password").pack(anchor="w")
    e1 = ttk.Entry(f, textvariable=pw1, show="\u2022", width=40)
    e1.pack(anchor="w", pady=(0, 8))
    if not unlocking:
        ttk.Label(f, text="Password again").pack(anchor="w")
        ttk.Entry(f, textvariable=pw2, show="\u2022", width=40).pack(anchor="w", pady=(0, 8))
        ttk.Checkbutton(f, text="Afterwards move the original folder to the Recycle Bin", variable=rm).pack(anchor="w", pady=4)
    msg = tk.StringVar()
    ttk.Label(f, textvariable=msg, wraplength=590).pack(anchor="w", pady=10)
    go = ttk.Button(f, text="Unlock" if unlocking else "Lock", style="Accent.TButton")
    go.pack(anchor="w")

    def run():
        if not pw1.get():
            msg.set("Enter a password.")
            return
        if not unlocking and pw1.get() != pw2.get():
            msg.set("The two passwords are different.")
            return
        if not unlocking and len(pw1.get()) < 8 and not messagebox.askyesno("Short password", "This password is short and easy to guess. Use it anyway?", parent=win):
            return
        go.configure(state="disabled")
        msg.set("Working\u2026 (the password check takes a second)")

        def work():
            try:
                if unlocking:
                    dest = os.path.join(os.path.dirname(item[1]), os.path.splitext(item[0])[0] + " (unlocked)")
                    ff_vault.unlock(item[1], dest, pw1.get(), lambda n: alive["v"] and A.root.after(0, lambda: alive["v"] and msg.set(f"Unpacking {n}")))
                    out, err = f"Unlocked into {dest}", None
                else:
                    target = os.path.join(os.path.dirname(item[1]), item[0] + ".ffvault")
                    ff_vault.lock_folder(item[1], target, pw1.get(), lambda n: alive["v"] and A.root.after(0, lambda: alive["v"] and msg.set(f"Locking {n}")))
                    out, err = f"Locked into {target}", None
            except Exception as e:  # noqa
                out, err = None, e
            A.root.after(0, lambda: alive["v"] and done(out, err))

        def done(out, err):
            go.configure(state="normal")
            if err:
                msg.set(f"Failed: {err}")
                return
            msg.set(out)
            if rm.get() and not unlocking and recycle([item[1]]):
                A.push_undo("delete", [item[1]])
                msg.set(out + " \u2014 the original folder is in the Recycle Bin.")
            A.after_change()
        threading.Thread(target=work, daemon=True).start()
    go.configure(command=run)
    e1.focus_set()
    win.bind("<Return>", lambda e: run())


def open_similar_photos(A):
    """Find photos that are the same picture saved at a different size/quality (exact duplicates are in the Duplicates window)."""
    folder = A.st["cwd"]
    if X.zip_is_virtual(folder):
        A.status.set("Open a normal folder first")
        return
    win = A.toplevel("Similar photos", "980x680")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    ttk.Label(win, text=f"Looking for look-alike photos in {folder} (and its sub-folders). The biggest copy of each picture is kept; the others are suggested.",
              wraplength=940, padding=(14, 12, 14, 4)).pack(fill="x")
    msg = tk.StringVar(value="Scanning\u2026")
    ttk.Label(win, textvariable=msg, padding=(14, 4)).pack(fill="x")
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=10)
    pvs = ui_extras.PreviewPane(frm, A)
    tv = ttk.Treeview(frm, columns=("res", "size", "path"), show="tree headings", selectmode="extended")
    for c, text, w, anc in (("#0", "Photo", 280, "w"), ("res", "Pixels", 110, "e"), ("size", "Size", 90, "e"), ("path", "Where", 440, "w")):
        tv.heading(c, text=text, anchor="w")
        tv.column(c, width=w, anchor=anc)
    sb = ttk.Scrollbar(frm, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    tv.pack(fill="both", expand=True)
    pvs.watch(tv, lambda i: i if os.path.isfile(i) else None)
    tv.tag_configure("keep", foreground="#4ade80")

    def work():
        res = X.find_similar_images(folder, 5, lambda: not alive["v"], lambda n: alive["v"] and A.root.after(0, lambda: alive["v"] and msg.set(f"Looking at photo {n:,}\u2026")))
        if res is not None and alive["v"]:
            A.root.after(0, lambda: alive["v"] and fill(res))

    def fill(groups):
        extra = 0
        for gi, g in enumerate(groups[:600]):
            iid = f"g{gi}"
            tv.insert("", "end", iid=iid, text=f"{len(g)} look-alike photos", open=True)
            for k, (p, px, sz) in enumerate(g):
                tv.insert(iid, "end", iid=p, text=("\u2714 keep  " if k == 0 else "") + os.path.basename(p), values=(f"{px:,}", human_size(sz), os.path.dirname(p)), tags=("keep",) if k == 0 else ())
                extra += sz if k else 0
        msg.set(f"{len(groups):,} group(s). Select the copies you don't need (the \u2714 ones are the biggest); removing the others frees {human_size(extra)}." if groups else "No look-alike photos found.")

    def trash():
        paths = [p for p in tv.selection() if os.path.isfile(p)]
        if paths and messagebox.askyesno("Recycle Bin", f"Move {len(paths)} photo(s) to the Recycle Bin?", parent=win) and recycle(paths):
            A.push_undo("delete", paths)
            for p in paths:
                tv.delete(p)
            msg.set(f"Moved {len(paths)} photo(s) to the Recycle Bin (Ctrl+Z in the main window undoes it).")
            A.after_change()
    bt = ttk.Frame(win, padding=12)
    bt.pack(fill="x")
    ttk.Button(bt, text="Move selected to Recycle Bin", style="Accent.TButton", command=trash).pack(side="left")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    threading.Thread(target=work, daemon=True).start()


def open_photo_info(A):
    imgs = [r for r in A.sel() if not r[4] and os.path.splitext(r[1])[1].lower() in (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic")
            and not X.zip_is_virtual(r[1])]
    if not imgs:
        imgs = [r for r in ask_rows(A, "Choose a photo", (("Photos", "*.jpg *.jpeg *.png *.webp *.tif *.tiff *.heic"),)) if not r[4]]
    if not imgs:
        return
    win = A.toplevel("Photo details", "720x520")
    f = ttk.Frame(win, padding=18)
    f.pack(fill="both", expand=True)
    info = X.exif_info(imgs[0][1])
    ttk.Label(f, text=imgs[0][1], wraplength=660, style="DetKey.TLabel", background=T["bg"]).pack(anchor="w", pady=(0, 10))
    tv = ttk.Treeview(f, columns=("v",), show="tree", height=12)
    tv.column("#0", width=170)
    tv.column("v", width=480)
    tv.pack(fill="both", expand=True)
    if info is None:
        tv.insert("", "end", text="Couldn't read this image")
    else:
        for k, v in info["rows"]:
            tv.insert("", "end", text=k, values=(v,))
        if len(info["rows"]) <= 2:
            tv.insert("", "end", text="Metadata", values=("none stored in this file",))
    msg = tk.StringVar(value="")
    ttk.Label(f, textvariable=msg, wraplength=660).pack(anchor="w", pady=8)
    bt = ttk.Frame(f)
    bt.pack(fill="x")

    def strip():
        out = os.path.join(os.path.dirname(imgs[0][1]), "No metadata")
        outs, fails = X.strip_metadata([r[1] for r in imgs], out)
        msg.set(f"Saved {len(outs)} clean copy(ies) in “No metadata” next to the originals (originals untouched)." + (f" {len(fails)} failed." if fails else ""))
        A.after_change()

    ttk.Button(bt, text=f"Save {'a copy' if len(imgs) == 1 else str(len(imgs)) + ' copies'} without metadata / location", style="Accent.TButton", command=strip).pack(side="left")
    if info and info["gps"]:
        import webbrowser
        ttk.Button(bt, text="Show on map", command=lambda: webbrowser.open("https://www.openstreetmap.org/?mlat=%f&mlon=%f&zoom=15" % info["gps"])).pack(side="left", padx=8)
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")


def export_settings(A):
    from tkinter import filedialog
    import json
    p_ = filedialog.asksaveasfilename(parent=A.root, defaultextension=".json", initialfile="Foldwise settings.json", filetypes=[("Settings", "*.json")])
    if p_:
        keep = {k: v for k, v in A.cfg.items() if k not in ("frec", "visits", "space_history", "alerted", "seen_threats", "tabs", "autoclean_log")}
        Path(p_).write_text(json.dumps(keep, indent=1), encoding="utf-8")
        A.status.set(f"Settings saved to {p_}")


def import_settings(A):
    from tkinter import filedialog
    import json
    p_ = filedialog.askopenfilename(parent=A.root, filetypes=[("Settings", "*.json")])
    if not p_:
        return
    try:
        data = json.loads(Path(p_).read_text(encoding="utf-8"))
        assert isinstance(data, dict)
    except (OSError, ValueError, AssertionError):
        messagebox.showerror("Import", "That file isn't a Foldwise settings file.", parent=A.root)
        return
    ok = {k: v for k, v in data.items() if k in DEFAULT_CFG and isinstance(v, type(DEFAULT_CFG[k])) and k not in ("tabs",)}
    if ok and messagebox.askyesno("Import settings", f"Apply {len(ok)} setting(s) from this file? Foldwise needs a restart afterwards.", parent=A.root):
        A.save_cfg(**ok)
        A.status.set("Settings imported \u2014 restart Foldwise to apply them")


def open_treemap(A, path=None):
    path = path or A.st["cwd"]
    win = A.toplevel("Disk usage", "1000x680")
    stt = {"path": path, "tok": 0, "items": [], "total": 0}
    top = tk.Frame(win, bg=T["bg"])
    top.pack(fill="x", padx=12, pady=10)
    lab = tk.StringVar()
    ttk.Button(top, text="↑ Up", command=lambda: load(os.path.dirname(stt["path"].rstrip("\\")) or stt["path"])).pack(
        side="left")
    ttk.Label(top, textvariable=lab, padding=(12, 0)).pack(side="left")
    ttk.Label(top, text="double-click a folder to drill in • right-click to go up", style="DetKey.TLabel",
              background=T["bg"]).pack(side="right")
    cv = tk.Canvas(win, bg=T["bg"], highlightthickness=0)
    cv.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    win.bind("<Destroy>", lambda e: stt.update(tok=-1) if e.widget is win else None)

    def load(p):
        if not os.path.isdir(p):
            return
        stt["tok"] += 1
        tok = stt["tok"]
        stt.update(path=p, items=[], total=0)
        cv.delete("all")
        lab.set(f"{p}  —  calculating…")
        cv.create_text(20, 20, anchor="nw", text="Calculating sizes…", fill=T["muted"],
                       font=("Segoe UI", A.cfg["font_size"] + 2))

        def work():
            items, dirs = [], []
            try:
                with os.scandir(p) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                dirs.append(e)
                            else:
                                items.append((e.stat(follow_symlinks=False).st_size, (e.name, e.path, False)))
                        except OSError:
                            pass
            except OSError:
                pass
            with ThreadPoolExecutor(6) as ex:
                futs = [(e, ex.submit(dir_stats, e.path, lambda: tok != stt["tok"])) for e in dirs]
                for e, f in futs:
                    r = f.result()
                    if r is not None:
                        items.append((r[2], (e.name, e.path, True)))
            if tok == stt["tok"]:
                A.root.after(0, ready, items, tok)

        threading.Thread(target=work, daemon=True).start()

    def ready(items, tok):
        if tok != stt["tok"]:
            return
        stt["items"] = items
        stt["total"] = sum(v for v, _ in items)
        draw()

    def draw(_=None):
        cv.delete("all")
        items = stt["items"]
        if not items:
            return
        lab.set(f"{stt['path']}  —  {human_size(stt['total'])}")
        W, H = max(cv.winfo_width(), 300), max(cv.winfo_height(), 200)
        rects = X.squarify(items[:], 0, 0, W, H)
        for k, (x, y, w, h, (name, p, isdir)) in enumerate(rects):
            t = 0.30 + 0.45 * (((k * 37) % 100) / 100)
            col = blend(T["accent"] if isdir else T["muted"], T["bg"], t if isdir else t * 0.7)
            rid = cv.create_rectangle(x + 1, y + 1, x + w - 1, y + h - 1, fill=col, outline=T["bg"], width=2)
            if w > 80 and h > 36:
                size = next(v for v, pl in items if pl[1] == p)
                cv.create_text(x + 8, y + 6, anchor="nw", text=name, fill=T["fg"], width=w - 14,
                               font=("Segoe UI", A.cfg["font_size"], "bold"))
                cv.create_text(x + 8, y + 26, anchor="nw", text=human_size(size), fill=T["fg"],
                               font=("Segoe UI", A.cfg["font_size"] - 1))
            cv.tag_bind(rid, "<Double-1>", lambda e, p=p, d=isdir: load(p) if d else None)
            cv.tag_bind(rid, "<Enter>", lambda e, n=name, p=p: lab.set(f"{p}"))
        cv.bind("<Button-3>", lambda e: load(os.path.dirname(stt["path"].rstrip("\\")) or stt["path"]))

    cv.bind("<Configure>", lambda e: win.after(120, draw) if stt["items"] else None)
    load(path)


def open_compare(A):
    cwd_of = lambda idx: A.st["cwd"] if idx == A.pane["i"] else A.panes[idx]["cwd"]
    if A.pane["split"]:
        left, right = cwd_of(0), cwd_of(1)
    else:  # from the Tools list: compare the current folder with one you pick
        left = A.st["cwd"]
        pick = ask_rows(A, f"Choose the folder to compare with {os.path.basename(left) or left}", folder=True)
        if not pick:
            return
        right = pick[0][1]
    if X.zip_is_virtual(left) or X.zip_is_virtual(right):
        A.status.set("Can't compare inside an archive")
        return
    if os.path.normcase(left) == os.path.normcase(right):
        A.status.set("Both panes show the same folder — open two different folders to compare")
        return
    win = A.toplevel("Compare folders", "1120x700")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    info_v = tk.StringVar(value="Scanning…")
    head = ttk.Frame(win, padding=(14, 10, 14, 0))
    head.pack(fill="x")
    ttk.Label(head, text=f"LEFT   {left}", style="DetKey.TLabel", background=T["bg"]).pack(anchor="w")
    ttk.Label(head, text=f"RIGHT  {right}", style="DetKey.TLabel", background=T["bg"]).pack(anchor="w")
    ttk.Label(head, textvariable=info_v, padding=(0, 8)).pack(anchor="w")
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=10)
    t3 = ttk.Treeview(frm, columns=("state", "lsize", "lmod", "rsize", "rmod"), show="tree headings",
                      selectmode="extended")
    for c, text, w, anc in (("#0", "File (relative path)", 380, "w"), ("state", "Status", 150, "w"),
                            ("lsize", "Left size", 90, "e"), ("lmod", "Left modified", 140, "w"),
                            ("rsize", "Right size", 90, "e"), ("rmod", "Right modified", 140, "w")):
        t3.heading(c, text=text, anchor=anc)
        t3.column(c, width=w, anchor=anc)
    for tag, col in (("only_left", "#4ade80"), ("only_right", "#fb923c"), ("newer_left", "#58a6ff"),
                     ("newer_right", "#a78bfa"), ("differ", "#f87171")):
        t3.tag_configure(tag, foreground=col)
    vs3 = ttk.Scrollbar(frm, orient="vertical", command=t3.yview)
    t3.configure(yscrollcommand=vs3.set)
    vs3.pack(side="right", fill="y")
    t3.pack(fill="both", expand=True)
    hide_same = tk.BooleanVar(value=True)
    btns = tk.Frame(win, bg=T["bg"])
    btns.pack(fill="x", padx=10, pady=10)
    LABEL = {"only_left": "Only on the left", "only_right": "Only on the right", "newer_left": "Newer on the left",
             "newer_right": "Newer on the right", "differ": "Different (same date)", "same": "Identical"}
    data = {"rows": []}

    def fill():
        t3.delete(*t3.get_children())
        for r in data["rows"]:
            rel, kind, ls, lm, rs, rm = r[:6]
            if kind == "same" and hide_same.get():
                continue
            t3.insert("", "end", text=rel, tags=(kind,), values=(
                LABEL[kind], human_size(ls) if ls is not None else "", fmt_date(lm) if lm else "",
                human_size(rs) if rs is not None else "", fmt_date(rm) if rm else ""))

    def summary():
        cnt = {}
        for r in data["rows"]:
            cnt[r[1]] = cnt.get(r[1], 0) + 1
        info_v.set("   •   ".join(f"{LABEL[k]}: {cnt[k]:,}" for k in LABEL if cnt.get(k)) or "Nothing to compare")

    def scan():
        info_v.set("Scanning…")
        t3.delete(*t3.get_children())

        def work():
            res = X.compare_folders(left, right, lambda: not alive["v"],
                                    lambda m: alive["v"] and A.root.after(0, lambda: alive["v"] and info_v.set(m)))
            if res is not None and alive["v"]:
                A.root.after(0, lambda: alive["v"] and (data.update(rows=res), summary(), fill()))
        threading.Thread(target=work, daemon=True).start()

    def sync(to_right=True, to_left=False, mirror=False):
        rows_ = data["rows"]
        copies, trash = [], []
        for rel, kind, ls, lm, rs, rm, lp, rp in rows_:
            if to_right and kind in ("only_left", "newer_left"):
                copies.append((lp, os.path.join(right, rel), kind == "newer_left"))
            if to_left and kind in ("only_right", "newer_right"):
                copies.append((rp, os.path.join(left, rel), kind == "newer_right"))
            if mirror and kind == "only_right":
                trash.append(rp)
        if not copies and not trash:
            messagebox.showinfo("Compare", "Nothing to do for that choice.", parent=win)
            return
        size = sum(os.path.getsize(c[0]) for c in copies if os.path.exists(c[0]))
        msg = (f"{len(copies):,} file(s) will be copied ({human_size(size)}), {sum(1 for c in copies if c[2]):,} of them "
               "replace an older version (the old version goes to the Recycle Bin)."
               + (f"\n{len(trash):,} file(s) that exist only on the right go to the Recycle Bin." if trash else "")
               + "\n\nContinue?")
        if not messagebox.askyesno("Compare", msg, parent=win):
            return
        info_v.set("Working…")

        def work():
            done, errs_ = 0, 0
            for src, dst, replace_ in copies:
                try:
                    if replace_ and os.path.exists(dst):
                        recycle([dst])
                    X.copy_file_to(src, dst)
                    done += 1
                except OSError as e:
                    errs_ += 1
                    log_error(f"sync {src} -> {dst}: {e}")
                if done % 20 == 0:
                    A.root.after(0, lambda d=done: alive["v"] and info_v.set(f"Copied {d:,} of {len(copies):,}…"))
            if trash:
                recycle(trash)
            A.root.after(0, finished, done, errs_)

        def finished(done, errs_):
            A.status.set(f"Sync: {done:,} copied" + (f", {errs_} failed (see error.log)" if errs_ else ""))
            A.after_change()
            if alive["v"]:
                scan()

        threading.Thread(target=work, daemon=True).start()

    for text, kw in (("Copy new → right", dict()), ("← Copy new to left", dict(to_right=False, to_left=True)),
                     ("Two-way sync", dict(to_left=True)), ("Mirror left → right", dict(mirror=True))):
        ttk.Button(btns, text=text, command=lambda kw=kw: sync(**kw)).pack(side="left", padx=(0, 8))
    ttk.Checkbutton(btns, text="Hide identical files", variable=hide_same, command=fill).pack(side="left", padx=12)
    ttk.Button(btns, text="Rescan", command=scan).pack(side="right", padx=(8, 0))
    ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")
    scan()


def open_bulk_rename(A):
    s = A.sel()
    if not s:
        A.status.set("Select the files to rename first")
        return
    win = A.toplevel(f"Bulk rename — {len(s)} item(s)", "760x600")
    f = ttk.Frame(win, padding=14)
    f.pack(fill="both", expand=True)
    mode, find, repl, rx = tk.StringVar(value="replace"), tk.StringVar(), tk.StringVar(), tk.BooleanVar()
    tpl, startn, case = tk.StringVar(value="{name}_{n:02}{ext}"), tk.IntVar(value=1), tk.StringVar(value="keep")
    ttk.Radiobutton(f, text="Find & replace", variable=mode, value="replace").grid(row=0, column=0, sticky="w")
    ttk.Label(f, text="Find").grid(row=1, column=0, sticky="w", pady=3)
    ttk.Entry(f, textvariable=find, width=26).grid(row=1, column=1, sticky="w")
    ttk.Label(f, text="Replace with").grid(row=1, column=2, sticky="w", padx=(14, 6))
    ttk.Entry(f, textvariable=repl, width=26).grid(row=1, column=3, sticky="w")
    ttk.Checkbutton(f, text="Regex", variable=rx).grid(row=1, column=4, padx=10)
    ttk.Radiobutton(f, text="Template", variable=mode, value="template").grid(row=2, column=0, sticky="w", pady=(10, 0))
    ttk.Label(f, text="Pattern").grid(row=3, column=0, sticky="w", pady=3)
    ttk.Entry(f, textvariable=tpl, width=26).grid(row=3, column=1, sticky="w")
    ttk.Label(f, text="Start at").grid(row=3, column=2, sticky="w", padx=(14, 6))
    ttk.Spinbox(f, from_=0, to=99999, textvariable=startn, width=8).grid(row=3, column=3, sticky="w")
    ttk.Label(f, text="{name} {ext} {n} {n:03}   dates: {date} {datetime} {year} {month} {day} {time} (photo date taken, else modified)", style="DetKey.TLabel", background=T["bg"]).grid(
        row=4, column=1, columnspan=3, sticky="w")
    ttk.Label(f, text="Letter case").grid(row=5, column=0, sticky="w", pady=(8, 0))
    cb = ttk.Combobox(f, values=["keep", "lower", "upper", "title"], textvariable=case, state="readonly", width=10)
    cb.grid(row=5, column=1, sticky="w", pady=(8, 0))
    pv = ttk.Treeview(f, columns=("new",), show="tree headings", height=14)
    pv.heading("#0", text="Current name", anchor="w")
    pv.heading("new", text="New name", anchor="w")
    pv.column("#0", width=320)
    pv.column("new", width=320)
    pv.tag_configure("bad", foreground="#f87171")
    pv.grid(row=6, column=0, columnspan=5, sticky="nsew", pady=12)
    f.rowconfigure(6, weight=1)
    f.columnconfigure(4, weight=1)
    info_v = tk.StringVar()
    ttk.Label(f, textvariable=info_v).grid(row=7, column=0, columnspan=3, sticky="w")
    plan = {"new": []}

    def preview(*_):
        try:
            n0 = startn.get()
        except tk.TclError:
            n0 = 1
        new = X.plan_rename([r[0] for r in s], mode.get(), find.get(), repl.get(), rx.get(), tpl.get(), n0,
                            case.get(), paths=[r[1] for r in s])
        plan["new"] = new
        pv.delete(*pv.get_children())
        seen, bad = set(), 0
        for r, nn in zip(s, new):
            dest = os.path.join(os.path.dirname(r[1]), nn)
            conflict = (nn in seen) or (os.path.exists(dest) and os.path.normcase(dest) != os.path.normcase(r[1])) \
                or not nn or any(c in nn for c in '<>:"/\\|?*')
            seen.add(nn)
            bad += bool(conflict)
            pv.insert("", "end", text=r[0], values=(nn,), tags=("bad",) if conflict else ())
        info_v.set(f"{bad} conflict(s) will be skipped" if bad else "Looks good")

    for v in (mode, find, repl, rx, tpl, startn, case):
        v.trace_add("write", preview)
    preview()

    def apply():
        pairs = []
        for r, nn in zip(s, plan["new"]):
            if nn == r[0]:
                continue
            dest = os.path.join(os.path.dirname(r[1]), nn)
            if (os.path.exists(dest) and os.path.normcase(dest) != os.path.normcase(r[1])) or not nn or \
                    any(c in nn for c in '<>:"/\\|?*'):
                continue
            try:
                os.rename(r[1], dest)
                pairs.append((r[1], dest))
            except OSError:
                pass
        if pairs:
            A.push_undo("bulk", pairs)
        win.destroy()
        A.after_change()
        A.status.set(f"Renamed {len(pairs)} item(s)   •   Ctrl+Z to undo")

    bt = ttk.Frame(f)
    bt.grid(row=7, column=3, columnspan=2, sticky="e")
    ttk.Button(bt, text="Cancel", command=win.destroy).pack(side="left", padx=6)
    ttk.Button(bt, text="Rename", style="Accent.TButton", command=apply).pack(side="left")
