"""Tools > Cloud files: which files on this PC are only placeholders (OneDrive, Phone Link photos ...) and how much they stand for.
Looking never downloads anything; opening a file from here does, so that asks first. Every function takes `A` first (ff_app.App)."""
import os
import threading
import tkinter as tk
from tkinter import ttk

import ff_cloud
import ff_platform
import ui_pages
from ff_core import T, ThemedBox as messagebox, human_size
from ui_picker import filedialog

SHOW = 400  # files listed when a folder is opened


def open_cloud(A):
    win = A.toplevel("Cloud files", "980x660")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    st = {"tok": 0, "found": {}, "root": ""}
    status = tk.StringVar(value="")
    srcs = ff_cloud.sources(A.home)

    tk.Label(win, text="Cloud files", bg=T["bg"], fg=T["fg"], font=("Segoe UI", A.cfg["font_size"] + 6, "bold")).pack(anchor="w", padx=22, pady=(18, 2))
    tk.Label(win, text="Files that are only placeholders: their data is in the cloud or on your phone, and opening one downloads it. "
                       "Looking here never downloads anything.", bg=T["bg"], fg=T["muted"], font=("Segoe UI", A.cfg["font_size"]), wraplength=900, justify="left").pack(anchor="w", padx=22, pady=(0, 8))
    bt = ttk.Frame(win, padding=(14, 10))
    bt.pack(side="bottom", fill="x")
    top = ttk.Frame(win, padding=(18, 0, 18, 6))
    top.pack(fill="x")
    ttk.Label(top, text="Look in").pack(side="left")
    names = [f"{n}  ({p})" for n, p in srcs]
    pick = ttk.Combobox(top, values=names, state="readonly", width=56)
    pick.pack(side="left", padx=8)
    ttk.Button(top, text="Other folder…", command=lambda: other()).pack(side="left")
    pb = ttk.Progressbar(top, mode="indeterminate", length=120)
    body = ttk.Frame(win, padding=(18, 0))
    body.pack(fill="both", expand=True)
    tv = ttk.Treeview(body, columns=("n", "size"), show="tree headings", selectmode="browse")
    tv.heading("#0", text="Folder")
    tv.heading("n", text="Online-only files")
    tv.heading("size", text="Size they stand for")
    tv.column("#0", width=560)
    tv.column("n", width=130, anchor="e")
    tv.column("size", width=150, anchor="e")
    sb = ttk.Scrollbar(body, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    tv.pack(fill="both", expand=True)

    def scan(root):
        st["tok"] += 1
        tok = st["tok"]
        st["root"] = root
        tv.delete(*tv.get_children())
        pb.pack(side="left", padx=8)
        pb.start(12)
        status.set("Looking…")

        def prog(n):
            A.root.after(0, lambda: alive["v"] and tok == st["tok"] and status.set(f"Looked at {n:,} files…"))

        def work():
            found, seen = ff_cloud.scan(root, cancel=lambda: not alive["v"] or tok != st["tok"], progress=prog)
            A.root.after(0, lambda: alive["v"] and tok == st["tok"] and done(found, seen))
        threading.Thread(target=work, daemon=True).start()

    def done(found, seen):
        pb.stop()
        pb.pack_forget()
        st["found"] = found
        gs = ff_cloud.groups(found)
        for i, (d, n, size) in enumerate(gs[:600]):
            iid = f"g{i}"
            tv.insert("", "end", iid=iid, text=os.path.relpath(d, st["root"]) if d != st["root"] else os.path.basename(d) or d, values=(f"{n:,}", human_size(size)))
            tv.insert(iid, "end", iid=f"{iid}.x", text="…")  # (listed when the folder is opened)
        files = sum(g[1] for g in gs)
        status.set(f"{files:,} online-only file(s) in {len(gs):,} folder(s), standing for {human_size(sum(g[2] for g in gs))}; {seen:,} files looked at" if files
                   else f"No online-only files found ({seen:,} files looked at).")
        win._cloud_groups = gs

    def opened(_e=None):
        iid = tv.focus()
        kids = tv.get_children(iid)
        if not (iid.startswith("g") and kids and kids[0].endswith(".x")):
            return
        tv.delete(kids[0])
        d = ff_cloud.groups(st["found"])[int(iid[1:])][0]
        files = sorted(st["found"][d], key=lambda f: -f[1])
        for j, (name, size, _m) in enumerate(files[:SHOW]):
            tv.insert(iid, "end", iid=f"{iid}.f{j}", text=name, values=("", human_size(size)))
        if len(files) > SHOW:
            tv.insert(iid, "end", text=f"… and {len(files) - SHOW:,} more", values=("", ""))

    def target():
        """(folder, file or None) of the selected row."""
        s = tv.selection()
        if not s:
            return None, None
        gi = int(s[0].split(".")[0][1:])
        d = ff_cloud.groups(st["found"])[gi][0]
        if ".f" in s[0]:
            return d, os.path.join(d, tv.item(s[0], "text"))
        return d, None

    def show_in_folder():
        d, f = target()
        if d:
            ui_pages.show_files(A)
            A.navigate(d, select=f)

    def open_it():
        d, f = target()
        if f and messagebox.askyesno("Download and open", "Opening this file downloads it first (for phone photos that means Windows contacting your phone). Continue?", parent=A.root):
            ff_platform.open_path(f)

    def other():
        d = filedialog.askdirectory(parent=win, title="Folder to look in")
        if d:
            pick.set("")
            scan(d)
    ttk.Button(bt, text="Show in folder", style="Accent.TButton", command=show_in_folder).pack(side="left")
    ttk.Button(bt, text="Open (downloads it)", command=open_it).pack(side="left", padx=8)
    ttk.Label(bt, textvariable=status).pack(side="left", padx=12)
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    tv.bind("<<TreeviewOpen>>", opened)
    pick.bind("<<ComboboxSelected>>", lambda e: scan(srcs[pick.current()][1]))
    win._cloud_state = (st, tv, pick, scan)  # (the tests drive the page through this)
    if srcs:
        pick.current(0)
        scan(srcs[0][1])
    else:
        status.set("No cloud or phone folders found. Use “Other folder…” to look somewhere else.")
