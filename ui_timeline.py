"""Tools > Photo timeline: your photos by year and month (when they were taken), with thumbnails. Online-only photos (cloud, Phone Link) show a cloud
tile and are not opened. Every function takes `A` first (ff_app.App); the work of finding and dating photos is in ff_timeline.
"""
import os
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk

import ff_platform
import ff_timeline as TL
import ui_pages
from ff_core import DB_DIR, T
from ui_picker import filedialog

TILE, GAP, PAGE = 150, 12, 300  # thumbnail size, space between tiles, photos shown before 'Show more'


def _thumb(path):
    """A PIL thumbnail, or None for online-only files and formats PIL cannot read."""
    if ff_platform.is_online_only(path):
        return None
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((TILE, TILE))
            return im.convert("RGBA")
    except Exception:  # noqa - damaged or unsupported (HEIC ...): the tile keeps its icon
        return None


def open_timeline(A):
    win = A.toplevel("Photo timeline", "1140x760")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    pool = ThreadPoolExecutor(3)
    st = {"folder": A.cfg.get("timeline_folder") or os.path.join(os.path.expanduser("~"), "Pictures"), "entries": [], "group": {}, "node": None, "limit": PAGE,
          "tok": 0, "imgs": {}, "sel": [], "tiles": {}, "width": 0}
    status = tk.StringVar(value="")

    bt = ttk.Frame(win, padding=(14, 8))
    bt.pack(side="bottom", fill="x")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    actions = [ttk.Button(bt, text="Copy to…", command=lambda: send(False)), ttk.Button(bt, text="Move to…", command=lambda: send(True)),
               ttk.Button(bt, text="Show in folder", command=lambda: go(st["sel"][0]))]
    for b in reversed(actions):
        b.pack(side="right", padx=(0, 6))
        b.configure(state="disabled")  # (until photos are selected)
    ttk.Label(bt, textvariable=status).pack(side="left")
    top = ttk.Frame(win, padding=(18, 14, 18, 6))
    top.pack(fill="x")
    ttk.Label(top, text="Photos in").pack(side="left")
    where = tk.StringVar(value=st["folder"])
    ttk.Label(top, textvariable=where, foreground=T["accent"]).pack(side="left", padx=8)
    ttk.Button(top, text="Choose…", command=lambda: choose()).pack(side="left")
    ttk.Button(top, text="Scan again", command=lambda: scan()).pack(side="left", padx=8)
    pb = ttk.Progressbar(top, mode="determinate", maximum=100, length=160)
    body = ttk.Frame(win, padding=(18, 0, 18, 0))
    body.pack(fill="both", expand=True)
    tree = ttk.Treeview(body, show="tree", selectmode="browse")
    tree.column("#0", width=230)
    tree.pack(side="left", fill="y")
    cv = tk.Canvas(body, bg=T["bg"], highlightthickness=0)
    sb = ttk.Scrollbar(body, orient="vertical", command=cv.yview)
    cv.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    cv.pack(side="left", fill="both", expand=True, padx=(10, 0))
    ui_pages.register_scroll(A.root, cv)

    def choose():
        d = filedialog.askdirectory(parent=win, title="Folder with your photos", initialdir=st["folder"] if os.path.isdir(st["folder"]) else "")
        if d:
            st["folder"] = d
            where.set(d)
            A.save_cfg(timeline_folder=d)
            scan()

    def scan():
        st["tok"] += 1
        pb.pack(side="left", padx=8)
        pb.configure(value=0)
        status.set("Looking for photos…")

        def prog(done, total):
            A.root.after(0, lambda: alive["v"] and (pb.configure(value=100 * done / total if total else 100), status.set(f"Reading the dates of new photos… {done:,} of {total:,}")))

        def work():
            try:
                entries = TL.scan(st["folder"], str(DB_DIR / "photodates.json"), prog, lambda: not alive["v"])
            except Exception as e:  # noqa
                entries, err = [], str(e)
            else:
                err = None
            A.root.after(0, lambda: alive["v"] and loaded(entries, err))
        threading.Thread(target=work, daemon=True).start()

    def loaded(entries, err):
        pb.pack_forget()
        st["entries"], st["group"] = entries, TL.group(entries)
        tree.delete(*tree.get_children())
        for year, total, months in TL.summary(st["group"]):
            tree.insert("", "end", iid=f"y{year}", text=f"{year}    ({total:,})", open=(year == max(st["group"], default=0)))
            for m, n in months:
                tree.insert(f"y{year}", "end", iid=f"m{year}-{m}", text=f"   {TL.MONTHS[m - 1]}    ({n:,})")
        status.set(f"Couldn't read the folder: {err}" if err else f"{len(entries):,} photos, {len(st['group'])} year(s)" if entries else "No photos found in this folder.")
        kids = tree.get_children()
        if kids:
            first = tree.get_children(kids[0])
            tree.selection_set(first[0] if first else kids[0])

    def photos_of(node):
        """[(heading or None, [(ts, path)])] for a year or a month node."""
        g = st["group"]
        if node.startswith("m"):
            y, m = (int(x) for x in node[1:].split("-"))
            return [(None, g[y][m])]
        y = int(node[1:])
        return [(f"{TL.MONTHS[m - 1]} {y}", g[y][m]) for m in sorted(g[y], reverse=True)]

    def render(_e=None):
        if not alive["v"] or not st["node"]:
            return
        st["tok"] += 1
        tok = st["tok"]
        cv.delete("all")
        st["imgs"].clear()
        st["tiles"].clear()
        st["sel"] = []
        mark()
        w = max(cv.winfo_width(), 300)
        st["width"] = w
        cols = max(1, (w - GAP) // (TILE + GAP))
        y, shown, total = GAP, 0, 0
        for head, items in photos_of(st["node"]):
            total += len(items)
            if shown >= st["limit"]:
                continue
            if head:
                cv.create_text(GAP, y, text=f"{head}    ({len(items):,})", anchor="nw", fill=T["accent"], font=("Segoe UI", A.cfg["font_size"] + 1, "bold"))
                y += 30
            for i, (ts, p) in enumerate(items[:max(0, st["limit"] - shown)]):
                x, ty = GAP + (i % cols) * (TILE + GAP), y + (i // cols) * (TILE + GAP + 18)
                tag = f"t{shown + i}"
                cv.create_rectangle(x, ty, x + TILE, ty + TILE, fill=T["panel"], outline="", tags=(tag, "tile"))
                cv.create_text(x + TILE // 2, ty + TILE // 2, text="☁" if ff_platform.is_online_only(p) else "\U0001F5BC", fill=T["muted"], font=("Segoe UI", 22), tags=(tag, f"ph{shown + i}"))
                cv.create_text(x + TILE // 2, ty + TILE + 2, text=time.strftime("%d %b %Y", time.localtime(ts)), fill=T["muted"], font=("Segoe UI", 8), anchor="n", tags=(tag,))
                st["tiles"][tag] = p
                for seq, fn in (("<Double-Button-1>", lambda e, p=p: go(p)), ("<Button-1>", lambda e, p=p, t=tag: pick(e, t, p)), ("<Button-3>", lambda e, p=p: menu(e, p))):
                    cv.tag_bind(tag, seq, fn)
                pool.submit(load, tok, p, x, ty, f"ph{shown + i}", tag)
            n = min(len(items), max(0, st["limit"] - shown))
            shown += n
            y += ((n + cols - 1) // cols) * (TILE + GAP + 18) + 10
        if total > shown:
            cv.create_text(GAP, y, text=f"Show {min(PAGE, total - shown):,} more of {total - shown:,}…", anchor="nw", fill=T["accent"], font=("Segoe UI", A.cfg["font_size"], "bold"), tags="more")
            cv.tag_bind("more", "<Button-1>", lambda e: (st.update(limit=st["limit"] + PAGE), render()))
            y += 40
        cv.configure(scrollregion=(0, 0, w, y + GAP))
        status.set(f"{total:,} photos shown in this {'month' if st['node'].startswith('m') else 'year'}" + (f" (first {shown:,})" if total > shown else ""))

    def load(tok, p, x, ty, ph, tag):
        im = _thumb(p)
        if im is None:
            return

        def put():
            if not alive["v"] or tok != st["tok"]:
                return
            from PIL import ImageTk
            img = ImageTk.PhotoImage(im)
            st["imgs"][p] = img
            cv.delete(ph)
            cv.create_image(x + TILE // 2, ty + TILE // 2, image=img, tags=("img", ph, tag))  # (the tile's tag: clicks on the picture count as clicks on the tile)
        A.root.after(0, put)

    def pick(e, tag, p):
        """Click selects one photo; Ctrl or Shift + click adds/removes it from the selection."""
        cv.focus_set()  # (so Enter opens the selected photo's folder)
        if e.state & 0x5:
            st["sel"] = [x for x in st["sel"] if x != p] if p in st["sel"] else st["sel"] + [p]
        else:
            st["sel"] = [p]
        mark()

    def mark():
        cv.delete("sel")
        for tag, p in st["tiles"].items():
            if p in st["sel"]:
                x0, y0, x1, y1 = cv.coords(cv.find_withtag(tag)[0])  # (the first item of a tile is its rectangle)
                cv.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2, outline=T["accent"], width=3, tags="sel")
        n = len(st["sel"])
        status.set(st["sel"][0] if n == 1 else f"{n} photos selected" if n else "")
        for b in actions:
            b.configure(state="normal" if n else "disabled")

    def select_all(_e=None):
        st["sel"] = list(st["tiles"].values())
        mark()
        return "break"

    def send(move):
        """Copy or move the selected photos into a folder you choose (through the normal transfer queue)."""
        if not st["sel"]:
            return
        d = filedialog.askdirectory(parent=win, title=("Move" if move else "Copy") + f" {len(st['sel'])} photo(s) to…")
        if d:
            A.run_transfer(list(st["sel"]), d, move)
            status.set(f"{'Move' if move else 'Copy'} of {len(st['sel'])} photo(s) started (Tools > Transfers)" + ("; Scan again to refresh" if move else ""))

    def go(p):
        ui_pages.show_files(A)
        A.navigate(os.path.dirname(p), select=p)

    def menu(e, p):
        m = A.make_menu()
        m.add_command(label="Open", command=lambda: ff_platform.open_path(p))
        m.add_command(label="Show in its folder", command=lambda: go(p))
        m.add_command(label="Copy path", command=lambda: (A.root.clipboard_clear(), A.root.clipboard_append(p)))
        m.tk_popup(e.x_root, e.y_root)

    def chosen(_e=None):
        s = tree.selection()
        if s:
            st["node"] = s[0]
            st["limit"] = PAGE
            cv.yview_moveto(0)
            render()

    def resized(_e=None):
        if st["node"] and abs(cv.winfo_width() - st["width"]) > TILE // 2:
            win.after(250, render)
    tree.bind("<<TreeviewSelect>>", chosen)
    cv.bind("<Configure>", resized)
    cv.bind("<Return>", lambda e: st["sel"] and go(st["sel"][0]))
    cv.bind("<Control-a>", select_all)
    win._timeline = st  # (the tests drive the page through this)
    scan()
