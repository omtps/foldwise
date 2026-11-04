"""Two browse-and-act tools: the Recycle Bin viewer (list + restore, never empties it) and Recent changes (what changed lately)."""
import os
import threading
import time
import tkinter as tk
from tkinter import ttk

import ff_extras as X
import ff_platform
import ui_extras
from ff_core import T, connect, fmt_date, human_size


def _tree(win, A, cols, with_preview=True):
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=14)
    pv = ui_extras.PreviewPane(frm, A) if with_preview else None
    tv = ttk.Treeview(frm, columns=[c[0] for c in cols[1:]], show="tree headings", selectmode="extended")
    for c, text, w, anc in cols:
        tv.heading(c, text=text, anchor=anc)
        tv.column(c, width=w, anchor=anc, stretch=(c == "#0"))
    sb = ttk.Scrollbar(frm, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    tv.pack(fill="both", expand=True)
    return tv, pv


def open_recycle_bin(A):
    """Everything in the Recycle Bin with its original place and deletion date; restore what you want back. Never empties it."""
    win = A.toplevel("Recycle Bin", "1000x660")
    msg = tk.StringVar(value="Reading the Recycle Bin…")
    ttk.Label(win, textvariable=msg, padding=(18, 14)).pack(fill="x")
    bt = ttk.Frame(win, padding=(14, 10))
    bt.pack(side="bottom", fill="x")
    tv, pv = _tree(win, A, (("#0", "Name", 280, "w"), ("from", "Deleted from", 380, "w"), ("size", "Size", 90, "e"), ("when", "Deleted", 130, "w")), False)
    data = {}

    def load():
        msg.set("Reading the Recycle Bin…")
        tv.delete(*tv.get_children())

        def work():
            try:
                items = X.recycle_list()
            except Exception as e:  # noqa
                A.root.after(0, lambda err=e: msg.set(f"Couldn't read the Recycle Bin: {err}"))
                return
            A.root.after(0, lambda: fill(items))
        threading.Thread(target=work, daemon=True).start()

    def fill(items):
        if not tv.winfo_exists():
            return
        data.clear()
        for n, it in enumerate(items[:3000]):
            iid = f"i{n}"
            data[iid] = it
            when = it["when"].replace("T", "  ")[:17]
            tv.insert("", "end", iid=iid, text=("📁 " if it["dir"] else "") + it["name"], values=(it["from"], human_size(it["size"]), when))
        msg.set(f"{len(items):,} item(s) in the Recycle Bin, {human_size(sum(i['size'] for i in items))}. Select items and restore them to where they came from."
                if items else "The Recycle Bin is empty.")

    def restore():
        sel = [data[i] for i in tv.selection() if i in data]
        if not sel:
            return
        paths = [os.path.join(it["from"], it["name"]) for it in sel]
        msg.set(f"Restoring {len(paths)} item(s)…")

        def work():
            back = X.restore_from_recycle(paths)
            A.root.after(0, lambda: (msg.set(f"Restored {len(back)} of {len(paths)} item(s)."), load()))
        threading.Thread(target=work, daemon=True).start()

    ttk.Button(bt, text="Restore selected", style="Accent.TButton", command=restore).pack(side="left")
    ttk.Button(bt, text="Refresh", command=load).pack(side="left", padx=8)
    ttk.Button(bt, text="Open the Recycle Bin in Explorer", command=ff_platform.recycle_bin_folder).pack(side="left")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    ttk.Label(bt, text="Emptying is left to Windows: Pinefiles never empties the bin for you.", style="DetKey.TLabel",
              background=T["bg"]).pack(side="right", padx=14)
    load()


def open_recent_changes(A):
    """Files created or changed lately anywhere in the index (newest first); noise folders can be hidden."""
    win = A.toplevel("Recent changes", "1100x680")
    top = ttk.Frame(win, padding=(18, 14, 18, 4))
    top.pack(fill="x")
    ttk.Label(top, text="Changed in the last").pack(side="left")
    span = ttk.Combobox(top, values=["hour", "6 hours", "day", "3 days", "week", "month"], state="readonly", width=9)
    span.set("day")
    span.pack(side="left", padx=8)
    quiet = tk.BooleanVar(value=True)
    ttk.Checkbutton(top, text="Hide system, app-data and developer folders", variable=quiet, command=lambda: load()).pack(side="left", padx=16)
    msg = tk.StringVar()
    ttk.Label(win, textvariable=msg, padding=(18, 4)).pack(fill="x")
    bt = ttk.Frame(win, padding=(14, 10))
    bt.pack(side="bottom", fill="x")
    tv, pv = _tree(win, A, (("#0", "File", 300, "w"), ("folder", "Folder", 360, "w"), ("size", "Size", 90, "e"), ("when", "Changed", 130, "w")), True)
    HOURS = {"hour": 1, "6 hours": 6, "day": 24, "3 days": 72, "week": 168, "month": 720}
    NOISE = ("%\\appdata\\%", "%\\windows\\%", "%\\program files%", "%\\programdata\\%", "%\\node_modules\\%", "%\\.git\\%", "%\\$recycle.bin\\%",
             "%\\__pycache__\\%", "%\\.cache\\%", "%\\.vscode\\%", "%\\.claude\\%")

    def load(_=None):
        msg.set("Searching the index…")
        since = time.time() - HOURS[span.get()] * 3600
        sql = "SELECT name, path, size, mtime FROM files WHERE is_dir=0 AND mtime>?"
        args = [since]
        if quiet.get():
            sql += "".join(" AND path_lc NOT LIKE ?" for _ in NOISE)
            args += list(NOISE)
        sql += " ORDER BY mtime DESC LIMIT 1500"

        def work():
            try:
                con = connect()
                rows = con.execute(sql, args).fetchall()
                con.close()
            except Exception as e:  # noqa
                A.root.after(0, lambda err=e: msg.set(f"Couldn't read the index: {err}"))
                return
            A.root.after(0, lambda: fill(rows))
        threading.Thread(target=work, daemon=True).start()

    def fill(rows):
        if not tv.winfo_exists():
            return
        tv.delete(*tv.get_children())
        for name, path, size, mtime in rows:
            tv.insert("", "end", iid=path, text=name, values=(os.path.dirname(path), human_size(size), fmt_date(mtime)))
        msg.set(f"{len(rows):,} file(s) changed in the last {span.get()}" + (" (newest 1,500 shown)" if len(rows) >= 1500 else "")
                + ". Double-click to show a file in its folder.")

    def reveal(_=None):
        s = tv.selection()
        if s:
            from ui_pages import show_files
            show_files(A)
            A.navigate(os.path.dirname(s[0]), select=s[0])

    span.bind("<<ComboboxSelected>>", load)
    tv.bind("<Double-1>", reveal)
    pv.watch(tv, lambda i: i)
    ttk.Button(bt, text="Show in folder", style="Accent.TButton", command=reveal).pack(side="left")
    ttk.Button(bt, text="Refresh", command=load).pack(side="left", padx=8)
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    load()
