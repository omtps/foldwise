"""Version 1.2 extras: tutorial, shortcut sheet, storage by file type, file diff, folder sizes on demand, CSV export / table
preview, window memory and 'follow Windows' light/dark. Every function takes the main-window helper `A` first."""
import csv
import difflib
import io
import os
import threading
import tkinter as tk
from ui_picker import filedialog
from tkinter import ttk

from ff_core import T, TEXT_EXTS, connect, fmt_date, human_size, windows_prefers_light

def open_tutorial(A, _=None):
    """The guided tour (ui_tour): opens the real windows and points at what each step explains."""
    import ui_tour
    ui_tour.start(A)


SHORTCUTS = [
    ("Search & navigation", [("Ctrl+F", "Focus the search box"), ("Ctrl+L", "Edit the path"), ("Ctrl+K", "Command palette"),
                             ("Backspace / Alt+←", "Up / back"), ("F5", "Refresh"), ("Space", "Quick look"), ("F3", "Details pane on/off")]),
    ("Tabs & panes", [("Ctrl+T", "New tab"), ("Ctrl+W", "Close tab"), ("Ctrl+Shift+T", "Reopen closed tab"), ("Ctrl+1 … 9", "Jump to tab"),
                      ("Ctrl+Shift+D", "Split view"), ("Tab", "Switch pane (split view)"), ("Ctrl+Shift+G", "Thumbnail grid")]),
    ("Files", [("Ctrl+Shift+S", "Select by pattern (*.jpg)"), ("Ctrl+I", "Invert selection"), ("Ctrl+C / X / V", "Copy / cut / paste"), ("F2", "Rename"), ("Ctrl+Shift+R", "Bulk rename"), ("Delete", "Delete (Recycle Bin)"),
               ("Ctrl+Z", "Undo"), ("Ctrl+Shift+N", "New folder"), ("Ctrl+A", "Select all")]),
    ("Search tokens (type them in the search box)", [("ext:pdf,docx", "File types"), ("size:>100mb", "Bigger / smaller than"), ("modified:today", "also yesterday, week, 3d, 2w, 2026-05, >2026-01-01"),
                                                     ("name:report", "Only in the file name"), ("re:^IMG_\\d+", "Regular expression"), ("type:folder", "Folders or files"),
                                                     ("content:invoice", "Inside documents (needs the content index)"), ("tag:work  label:red", "Your tags and colours"), ("-word", "Exclude a word")]),
    ("App", [("F1", "This sheet"), ("Right-click a tool", "Tools list: pin it to the toolbar"), ("Ctrl+Shift+C", "Copy full path of the selection"), ("Alt+Enter", "Properties"), ("Ctrl+,", "Customize"), ("Ctrl + / Ctrl -", "Zoom"), ("Ctrl+Alt+F", "Show Foldwise from anywhere"),
             ("Esc", "Close a pop-up, clear search (never closes the window)")]),
]


def overview_stats(A):
    """[(title, value, detail, colour)] shown at the top of the Tools overview: health, space, backup, index (cheap, no scans)."""
    import shutil
    import time
    out = []
    sc = A.cfg.get("last_score")
    out.append(("PC health", f"{sc} / 100" if sc is not None else "not checked", "Open PC health for details" if sc is not None else "Open PC health to run a check",
                "#4ade80" if (sc or 0) >= 80 else "#facc15" if (sc or 0) >= 60 else "#f87171" if sc is not None else T["muted"], ("open_health", ())))
    try:
        d = os.path.splitdrive(A.st["cwd"])[0] + "\\"
        u = shutil.disk_usage(d)
        pct = u.free * 100 // u.total
        out.append((f"Free on {d}", human_size(u.free), f"{pct}% of {human_size(u.total)}", "#4ade80" if pct >= 20 else "#facc15" if pct >= 10 else "#f87171", ("open_cleaner", ())))
    except OSError:
        pass
    jobs = A.cfg.get("backups") or []
    last = max([j.get("last") or 0 for j in jobs] or [0])
    if not jobs:
        out.append(("Backups", "not set up", "Add one in Backups", "#facc15", ("open_health", ("backups",))))
    elif not last:
        out.append(("Backups", "never run", f"{len(jobs)} job(s)", "#facc15", ("open_health", ("backups",))))
    else:
        days = (time.time() - last) / 86400
        out.append(("Last backup", "today" if days < 1 else f"{int(days)} day(s) ago", f"{len(jobs)} job(s)", "#4ade80" if days < 8 else "#facc15" if days < 30 else "#f87171", ("open_health", ("backups",))))
    try:
        from ff_core import DB_DIR
        cdb = os.path.getsize(DB_DIR / "content.db")
        if not A.cfg.get("content_index") and cdb > 200 * 1048576:  # content search is off but its database still takes space
            out.append(("Unused content index", human_size(cdb), "Content search is off: free this space", "#facc15", ("open_storage", ())))
    except OSError:
        pass
    try:
        con = connect()
        n = con.execute("SELECT v FROM meta WHERE k='count'").fetchone()
        con.close()
        out.append(("Search index", f"{int(n[0]):,} items" if n else "empty", "live" if A.cfg.get("live_index") else "updates on re-index", T["fg"], ("open_storage", ())))
    except Exception:  # noqa
        pass
    return out


def _undo_text(kind, data):
    n = len(data) if isinstance(data, (list, tuple)) and kind not in ("rename", "organize") else 1
    base = lambda p: os.path.basename(p) if isinstance(p, str) else str(p)  # noqa: E731
    if kind == "rename":
        return f"Renamed {base(data[0])}  →  {base(data[1])}"
    if kind == "bulk":
        return f"Renamed {n} file(s)"
    if kind == "move":
        return f"Moved {n} item(s)"
    if kind == "copy":
        return f"Copied {n} item(s)"
    if kind == "create":
        return "Created " + (base(data[0][1] if isinstance(data[0], tuple) else data[0]) if data else "an item")
    if kind == "delete":
        return f"Deleted {n} item(s) (in the Recycle Bin)"
    if kind == "organize":
        return f"Organized {len(data[0])} file(s) into folders"
    return kind


def open_undo_history(A, _=None):
    """What Ctrl+Z would undo, newest first. Undo always takes the newest step, so older ones wait their turn."""
    win = A.toplevel("Undo history", "760x560")
    msg = tk.StringVar()
    ttk.Label(win, textvariable=msg, padding=(18, 14), wraplength=700).pack(fill="x")
    bt = ttk.Frame(win, padding=(14, 10))
    bt.pack(side="bottom", fill="x")
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=14)
    tv = ttk.Treeview(frm, columns=(), show="tree")
    tv.pack(fill="both", expand=True)

    def fill():
        tv.delete(*tv.get_children())
        stack = list(A.st["undo"])
        for n, (kind, data) in enumerate(reversed(stack)):
            tv.insert("", "end", text=("▶  " if n == 0 else "     ") + _undo_text(kind, data))
        msg.set(f"{len(stack)} step(s) can be undone, newest first. Ctrl+Z or the button undoes the top one." if stack else "Nothing to undo yet.")

    def undo():
        A.do_undo()
        fill()
    ttk.Button(bt, text="Undo the newest step", style="Accent.TButton", command=undo).pack(side="left")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    fill()


def select_pattern(A, _=None, pattern=None):
    """Select the files in this view whose name matches a pattern: *.jpg   report*   *.png;*.gif  (case ignored)."""
    import fnmatch
    from ff_core import ThemedAsk
    pat = pattern if pattern is not None else ThemedAsk.askstring("Select by pattern", "Names to select (use * and ?, separate several with ; or a space):", initialvalue="*.", parent=A.root)
    if not pat or not pat.strip():
        return
    pats = [p.lower() for p in pat.replace(";", " ").split()]
    rows = A.st["rows"]
    hit = [k for k in A.tree.get_children() if any(fnmatch.fnmatch(rows[int(k)][0].lower(), p) for p in pats)]
    A.tree.selection_set(hit)
    if hit:
        A.tree.see(hit[0])
    A.status.set(f"{len(hit)} item(s) match {pat.strip()}")


def invert_selection(A, _=None):
    kids = A.tree.get_children()
    now = set(A.tree.selection())
    A.tree.selection_set([k for k in kids if k not in now])
    A.tree.focus_set()
    return "break"


def open_system_info(A, _=None):
    """Windows version, CPU, memory, graphics, drives, BIOS - read-only, with a copy button."""
    import ff_health as HL
    win = A.toplevel("System information", "780x600")
    msg = tk.StringVar(value="Reading system information…")
    ttk.Label(win, textvariable=msg, padding=(18, 14)).pack(fill="x")
    bt = ttk.Frame(win, padding=(14, 10))
    bt.pack(side="bottom", fill="x")
    box = tk.Frame(win, bg=T["bg"])
    box.pack(fill="both", expand=True, padx=18)
    data = {"text": ""}

    def work():
        res = HL.system_info()
        A.root.after(0, lambda: fill(res))
    threading.Thread(target=work, daemon=True).start()

    def fill(res):
        if not box.winfo_exists():
            return
        if not res:
            msg.set("Couldn't read the system information (PowerShell blocked?).")
            return
        msg.set("Everything below is read-only.")
        lines = []
        for sec, rows in res:
            ttk.Label(box, text=sec.upper(), style="DetHead.TLabel", background=T["bg"]).pack(anchor="w", pady=(12, 4))
            grid = ttk.Frame(box)
            grid.pack(fill="x")
            for r, (k, v) in enumerate(rows):
                ttk.Label(grid, text=k, style="DetKey.TLabel", background=T["bg"], width=16).grid(row=r, column=0, sticky="nw", pady=2)
                ttk.Label(grid, text=v, wraplength=560, justify="left").grid(row=r, column=1, sticky="w", pady=2)
                lines.append(f"{k}: {v}")
        data["text"] = chr(10).join(lines)

    def copy():
        A.root.clipboard_clear()
        A.root.clipboard_append(data["text"])
        msg.set("Copied.")
    ttk.Button(bt, text="Copy as text", style="Accent.TButton", command=copy).pack(side="left")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")


def folder_matches(text, limit=8):
    """Sub-folders whose names start with what has been typed after the last backslash: 'C:\\Users\\bo' -> ['C:\\Users\\bob', ...]."""
    text = os.path.expandvars(text.strip().strip('"'))
    base, _sep, prefix = text.rpartition(chr(92))
    if not base and not _sep:
        return []
    parent = base + chr(92)
    if len(base) == 2 and base[1] == ":":
        parent = base + chr(92)
    out = []
    try:
        with os.scandir(parent) as it:
            for e in it:
                try:
                    if e.is_dir() and e.name.lower().startswith(prefix.lower()):
                        out.append(os.path.join(parent, e.name))
                except OSError:
                    pass
                if len(out) > 400:
                    break
    except OSError:
        return []
    return sorted(out, key=lambda p: p.lower())[:limit]


def attach_path_complete(A):
    """Folder-name suggestions under the address bar while you type a path (Tab / click completes, Up / Down choose)."""
    pop = {"lb": None}

    def hide(_=None):
        if pop["lb"] is not None:
            pop["lb"].destroy()
            pop["lb"] = None

    def show(items):
        hide()
        if not items:
            return
        e = A.path_e
        lb = tk.Listbox(A.root, height=len(items), bg=T["raised"], fg=T["fg"], selectbackground=T["sel"], selectforeground=T["fg"],
                        bd=0, highlightthickness=1, highlightbackground=T["line"], activestyle="none", exportselection=False,
                        font=("Segoe UI", A.cfg["font_size"]))
        for p in items:
            lb.insert("end", "  " + os.path.basename(p.rstrip(chr(92))) or p)
        lb._items = items
        lb.place(x=e.winfo_rootx() - A.root.winfo_rootx(), y=e.winfo_rooty() - A.root.winfo_rooty() + e.winfo_height() + 2, width=max(260, e.winfo_width() // 2))
        lb.lift()
        lb.bind("<ButtonRelease-1>", lambda ev: choose(lb.nearest(ev.y), go=True))
        pop["lb"] = lb

    def choose(i, go=False):
        lb = pop["lb"]
        if lb is None or not (0 <= i < len(lb._items)):
            return
        path = lb._items[i]
        hide()
        if go:
            A.navigate(path)
        else:
            A.pathv.set(path + chr(92))
            A.path_e.icursor("end")
            typed()

    def typed(_=None):
        show(folder_matches(A.pathv.get()))

    def key(e):
        if e.keysym in ("Up", "Down", "Return", "Escape", "Tab", "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"):
            return
        typed()

    def tab(e):
        lb = pop["lb"]
        if lb is None:
            typed()
        sel = lb.curselection() if lb is not None else ()
        if pop["lb"] is not None:
            choose(sel[0] if sel else 0)
        return "break"

    def move(d):
        def f(e):
            lb = pop["lb"]
            if lb is None:
                return None
            cur = lb.curselection()
            i = (cur[0] + d) % lb.size() if cur else (0 if d > 0 else lb.size() - 1)
            lb.selection_clear(0, "end")
            lb.selection_set(i)
            lb.see(i)
            A.pathv.set(lb._items[i])  # Enter then goes to the highlighted folder (the address bar's own Enter handler)
            A.path_e.icursor("end")
            return "break"
        return f

    e = A.path_e
    e.bind("<KeyRelease>", key, add="+")
    e.bind("<Tab>", tab)
    e.bind("<Down>", move(1))
    e.bind("<Up>", move(-1))
    e.bind("<Escape>", hide, add="+")
    e.bind("<FocusOut>", lambda ev: A.root.after(150, hide), add="+")


def open_whats_new(A, _=None):
    import ff_update
    win = A.toplevel("What's new", "760x600")
    f = ttk.Frame(win, padding=28)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text=f"What's new in Foldwise {ff_update.APP_VERSION}", font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(0, 8))
    for ver, items in ff_update.WHATS_NEW:
        ttk.Label(f, text=f"VERSION {ver}", style="DetHead.TLabel", background=T["bg"]).pack(anchor="w", pady=(14, 4))
        for it in items:
            ttk.Label(f, text="•  " + it, wraplength=680, justify="left").pack(anchor="w", pady=1)


def whats_new_check(A):
    """After an update: say so once (a toast with a link to the list)."""
    import ff_update
    if A.cfg.get("seen_version") != ff_update.APP_VERSION:
        first = not A.cfg.get("seen_version")
        A.save_cfg(seen_version=ff_update.APP_VERSION)
        if not first:  # a brand-new install has nothing to compare with
            A.show_toast(f"Foldwise was updated to {ff_update.APP_VERSION}.", "See what's new", A.open_whats_new)


def open_shortcuts(A, _=None):
    win = A.toplevel("Shortcuts & tips", "760x640")
    f = ttk.Frame(win, padding=28)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text="Keyboard shortcuts", font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(0, 6))
    for group, items in SHORTCUTS:
        ttk.Label(f, text=group.upper(), style="DetHead.TLabel", background=T["bg"]).pack(anchor="w", pady=(16, 4))
        g = ttk.Frame(f)
        g.pack(fill="x")
        for r, (k, d) in enumerate(items):
            ttk.Label(g, text=k, font=("Consolas", A.cfg["font_size"]), foreground=T["accent"], width=20).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Label(g, text=d).grid(row=r, column=1, sticky="w", pady=2)
    ttk.Button(f, text="Start the guided tour", command=A.open_tutorial).pack(anchor="w", pady=(22, 0))


def open_storage_types(A, _=None):
    """Which file types take the space - straight from the search index (no scanning)."""
    win = A.toplevel("Storage by file type", "900x640")
    msg = tk.StringVar(value="Reading the index…")
    ttk.Label(win, textvariable=msg, padding=(18, 14)).pack(fill="x")
    ttk.Button(win, text="Close", command=win.destroy).pack(side="bottom", anchor="e", padx=18, pady=12)
    frm = tk.Frame(win, bg=T["bg"])
    frm.pack(fill="both", expand=True, padx=14)
    tv = ttk.Treeview(frm, columns=("files", "size", "share"), show="tree headings")
    for c, text, w, anc in (("#0", "Type", 200, "w"), ("files", "Files", 110, "e"), ("size", "Total size", 130, "e"), ("share", "Share of indexed files", 320, "w")):
        tv.heading(c, text=text, anchor=anc)
        tv.column(c, width=w, anchor=anc, stretch=(c == "share"))
    sb = ttk.Scrollbar(frm, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    tv.pack(fill="both", expand=True)

    def work():
        try:
            con = connect()
            rows = con.execute("SELECT ext, COUNT(*), COALESCE(SUM(size),0) FROM files WHERE is_dir=0 GROUP BY ext ORDER BY 3 DESC LIMIT 300").fetchall()
            con.close()
        except Exception as e:  # noqa
            A.root.after(0, lambda err=e: msg.set(f"Couldn't read the index: {err}"))
            return
        A.root.after(0, lambda: fill(rows))

    def fill(rows):
        if not tv.winfo_exists():
            return
        total = sum(r[2] for r in rows) or 1
        msg.set(f"{sum(r[1] for r in rows):,} files, {human_size(total)} in the index. Double-click a type to list its files.")
        for ext, n, size in rows:
            share = size / total
            tv.insert("", "end", text=("." + ext) if ext else "(no extension)", values=(f"{n:,}", human_size(size), f"{'█' * max(1, round(share * 28))}  {share * 100:.1f}%"), tags=(ext or "",))

    def pick(_=None):
        s = tv.selection()
        if s:
            ext = tv.item(s[0], "tags")[0] if tv.item(s[0], "tags") else ""
            from ui_pages import show_files
            show_files(A)
            A.q.set(f"ext:{ext}" if ext else "")
    tv.bind("<Double-1>", pick)
    threading.Thread(target=work, daemon=True).start()


def open_diff(A, _=None):
    s = [r for r in A.sel() if not r[4]]
    if len(s) != 2:
        A.status.set("Select exactly two files to compare")
        return
    texts = []
    for r in s:
        try:
            if os.path.getsize(r[1]) > 3_000_000:
                A.status.set(f"{r[0]} is too big to compare (over 3 MB)")
                return
            with open(r[1], "rb") as fh:
                data = fh.read()
            if b"\0" in data:
                A.status.set(f"{r[0]} isn't a text file")
                return
            texts.append(data.decode("utf-8", "replace").splitlines())
        except OSError as e:
            A.status.set(f"Couldn't read {r[0]}: {e}")
            return
    win = A.toplevel("Compare files", "1000x680")
    diff = list(difflib.unified_diff(texts[0], texts[1], s[0][0], s[1][0], lineterm=""))
    adds = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    dels = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    ttk.Label(win, text=(f"{s[0][0]}  ↔  {s[1][0]}   •   {adds} line(s) added, {dels} removed" if diff else f"{s[0][0]} and {s[1][0]} are identical"),
              padding=(18, 12)).pack(fill="x")
    ttk.Button(win, text="Close", command=win.destroy).pack(side="bottom", anchor="e", padx=18, pady=12)
    box = tk.Frame(win, bg=T["bg"])
    box.pack(fill="both", expand=True, padx=14)
    txt = tk.Text(box, wrap="none", bg=T["panel"], fg=T["fg"], bd=0, highlightthickness=0, font=("Consolas", A.cfg["font_size"]), padx=10, pady=8)
    sb = ttk.Scrollbar(box, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    txt.pack(fill="both", expand=True)
    txt.tag_configure("add", foreground="#4ade80")
    txt.tag_configure("del", foreground="#f87171")
    txt.tag_configure("hunk", foreground=T["accent"])
    for d in diff:
        tag = "hunk" if d.startswith("@@") else "add" if d.startswith("+") and not d.startswith("+++") else "del" if d.startswith("-") and not d.startswith("---") else None
        txt.insert("end", d + "\n", tag or ())
    txt.configure(state="disabled")


def folder_sizes_now(A, _=None):
    """Right-click > Folder size: measure the selected folders now (folder sizes are off by default)."""
    folders = [r[1] for r in A.sel() if r[4]]
    if not folders:
        return
    A.status.set(f"Measuring {len(folders)} folder(s)…")

    def walk(p):
        total = n = 0
        stack = [p]
        while stack:
            try:
                with os.scandir(stack.pop()) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                stack.append(e.path)
                            else:
                                total += e.stat(follow_symlinks=False).st_size
                                n += 1
                        except OSError:
                            pass
            except OSError:
                pass
        return total, n

    def work():
        out = []
        for p in folders:
            size, n = walk(p)
            out.append((p, size, n))
        A.root.after(0, lambda: done(out))

    def done(out):
        for p, size, _n in out:
            A.fsize[p] = size
        A.status.set("   •   ".join(f"{os.path.basename(p) or p}: {human_size(sz)} in {n:,} files" for p, sz, n in out))
        A.show(A.sort_rows(A.st["rows"]), msg=A.status.get(), keep=True)
    threading.Thread(target=work, daemon=True).start()


def export_csv(A, _=None):
    rows = A.st["rows"]
    if not rows:
        A.status.set("Nothing to export in this view")
        return
    path = filedialog.asksaveasfilename(parent=A.root, title="Export this list", defaultextension=".csv", initialfile="file-list.csv",
                                        filetypes=[("CSV (Excel)", "*.csv")])
    if not path:
        return
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["Name", "Path", "Type", "Size (bytes)", "Modified"])
            for name, p, size, mtime, isdir in rows:
                w.writerow([name, p, "Folder" if isdir else os.path.splitext(name)[1][1:].lower(), "" if isdir else size, fmt_date(mtime)])
        A.status.set(f"Exported {len(rows):,} rows to {path}")
    except OSError as e:
        A.status.set(f"Couldn't write the file: {e}")


def table_text(txt, ext):
    """Aligned columns for a CSV / TSV preview (first 60 rows, 8 columns); falls back to the raw text."""
    try:
        delim = "\t" if ext == "tsv" else csv.Sniffer().sniff(txt[:2000], delimiters=",;\t|").delimiter
        rows = list(csv.reader(io.StringIO(txt), delimiter=delim))[:60]
    except (csv.Error, ValueError):
        return txt
    if not rows:
        return txt
    cols = min(8, max(len(r) for r in rows))
    widths = [min(22, max(len(r[c]) if c < len(r) else 0 for r in rows)) for c in range(cols)]
    lines = ["  ".join((r[c] if c < len(r) else "")[:22].ljust(widths[c]) for c in range(cols)).rstrip() for r in rows]
    if len(lines) > 1:
        lines.insert(1, "  ".join("─" * w for w in widths))
    return "\n".join(lines)


# ------------------------------------------------------------------ window memory + follow-Windows theme
def remember_window(A):
    """Save size / position / maximised state (debounced) when the option is on."""
    if not A.cfg.get("remember_window"):
        return
    r = A.root
    zoomed = r.state() == "zoomed"
    kw = {"win_max": zoomed}
    if not zoomed and r.state() == "normal":
        kw["win_geo"] = r.geometry()
    A.save_cfg(**kw)


def restore_window(root, cfg):
    geo = cfg.get("win_geo")
    if cfg.get("remember_window") and geo:
        try:
            w, rest = geo.split("x", 1)
            h, x, y = rest.replace("+", " +").replace("-", " -").split()
            w, h, x, y = int(w), int(h), int(x), int(y)
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            if 300 <= w <= sw + 40 and 200 <= h <= sh + 40 and -40 <= x < sw - 100 and -10 <= y < sh - 100:
                root.geometry(geo)
        except (ValueError, TypeError):
            pass
        if cfg.get("win_max"):
            root.state("zoomed")


def theme_tick(A):
    """'Follow Windows' theme: switch between Adwaita Light/Dark when Windows does."""
    try:
        if A.cfg["theme"] == "Follow Windows":
            want = "light" if windows_prefers_light() else "dark"
            if A.st.get("os_theme") != want:
                first = A.st.get("os_theme") is None
                A.st["os_theme"] = want
                if not first:
                    A.restyle()
    finally:
        A.root.after(30000, lambda: theme_tick(A))


# ------------------------------------------------------------------ previews inside delete-style tools
class PreviewPane(tk.Frame):
    """A side panel that shows the picture / thumbnail of the (up to two) selected files, so you can SEE that two files really are
    the same before you delete one. Used by Duplicates, Similar photos and Largest files."""

    def __init__(self, parent, A, width=310):
        super().__init__(parent, bg=T["panel"], width=width)
        self.pack(side="right", fill="y", padx=(10, 0))
        self.pack_propagate(False)
        self.A, self.w, self.tok, self.slots = A, width, 0, []
        fs = A.cfg["font_size"]
        for _ in range(2):
            box = tk.Frame(self, bg=T["panel"])
            box.pack(fill="both", expand=True, padx=8, pady=6)
            cap = tk.Label(box, bg=T["panel"], fg=T["muted"], justify="left", anchor="w", wraplength=width - 24, font=("Segoe UI", fs - 1))
            cap.pack(side="bottom", fill="x")
            img = tk.Label(box, bg=T["raised"], fg=T["muted"], font=("Segoe UI", fs))
            img.pack(fill="both", expand=True)
            self.slots.append((img, cap))
        self.show([])

    def watch(self, tree, path_of):
        for c in ("#0",) + tuple(tree["columns"]):  # slim columns: the list must fit next to this panel without a horizontal scroll
            tree.column(c, width=min(int(tree.column(c, "width")), 300 if c == "#0" else 110), minwidth=50, stretch=(c == "#0"))
        def changed(_=None):
            paths = []
            for i in tree.selection():
                try:
                    p = path_of(i)
                except Exception:  # noqa
                    p = None
                if p and os.path.isfile(p):
                    paths.append(p)
            self.show(paths)
        tree.bind("<<TreeviewSelect>>", changed, add="+")

    def show(self, paths):
        self.tok += 1
        for n, (img, cap) in enumerate(self.slots):
            img.configure(image="", text="Select a file to preview it" if n == 0 and not paths else "")
            img.image = None
            cap.configure(text="")
            if n < len(paths):
                self._load(n, paths[n], self.tok)

    def _load(self, n, path, tok):
        img, cap = self.slots[n]
        try:
            st = os.stat(path)
            cap.configure(text=f"{os.path.basename(path)}\n{human_size(st.st_size)}   •   {fmt_date(st.st_mtime)}\n{os.path.dirname(path)}")
        except OSError:
            return
        img.configure(text="Loading…")
        bw, bh = self.w - 28, max(120, (self.winfo_height() // 2) - 90)

        def work():
            ext = os.path.splitext(path)[1][1:].lower()
            if ext in TEXT_EXTS or ext in ("csv", "tsv"):  # text-like: show the first lines so two copies can be compared by eye
                try:
                    with open(path, "rb") as fh:
                        raw = fh.read(2500)
                    if b"\0" not in raw:
                        txt = raw.decode("utf-8", "replace")
                        txt = table_text(txt, ext) if ext in ("csv", "tsv") else txt
                        lines = txt.splitlines()[:14]
                        self.A.root.after(0, lambda: tok == self.tok and img.winfo_exists() and img.configure(
                            image="", text=chr(10).join(l[:60] for l in lines), anchor="nw", justify="left", font=("Consolas", 8)))
                        return
                except OSError:
                    pass
            try:
                from PIL import Image, ImageTk
                im = None
                try:
                    im = Image.open(path)
                    dims = f"{im.width} × {im.height} px"
                    im.thumbnail((bw, bh))
                    im = im.convert("RGBA")
                except Exception:  # noqa - not a picture PIL knows: ask Windows for a thumbnail (video, PDF, Office ...)
                    dims = ""
                    import ff_shell
                    im = ff_shell.shell_thumbnail(path, 400)
                    if im is not None:
                        im.thumbnail((bw, bh))
                if im is None:
                    raise ValueError("no preview")
                self.A.root.after(0, lambda: ok(ImageTk.PhotoImage(im), dims))
            except Exception:  # noqa
                self.A.root.after(0, lambda: tok == self.tok and img.configure(image="", text="No preview for this file type"))

        def ok(ph, dims):
            if tok != self.tok or not img.winfo_exists():
                return
            img.configure(image=ph, text="")
            img.image = ph
            if dims:
                cap.configure(text=cap.cget("text") + "\n" + dims)
        threading.Thread(target=work, daemon=True).start()
