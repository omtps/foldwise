"""Tool pages: every tool (cleaner, health center, settings, ...) opens as a tab INSIDE the main window instead of a separate window.

`new_page(A, title)` returns a Page: a Frame that quacks enough like a Toplevel (title/geometry/bind/protocol/destroy/...)
that the existing `win = A.toplevel(title, geo)` dialogs work unchanged. While a tool is open the whole file view (path bar,
toolbar, search, sidebar, list) is taken off the screen and the tool fills the window (scrollable, so every option is reachable
at any window size); its tab sits next to the folder tabs. Modal question dialogs stay real pop-ups (ThemedBox)."""
import tkinter as tk

from ff_core import T

_S = {"pages": [], "active": None, "host": None, "nav": None, "cv": None, "sb": None, "esc": False, "cur": None, "rows": {},
      "hidden": [], "ids": {}, "poll": None}

DESC = {"Smart disk cleaner": "Free space safely", "Duplicate files": "Find identical copies", "Largest files": "What takes the space",
        "Organize folder": "Sort by type or date", "Disk usage map": "See space visually",
        "PC health": "Score, disks, security", "Backups": "Copy new files elsewhere",
        "Malware check": "Defender + deep check", "Integrity check": "Detect changed files", "System information": "Windows, CPU, memory, drives", "Encrypted vault": "Lock a folder with a password",
        "Sync two folders": "Keep two folders equal", "Checksum": "Verify a file's hash", "Convert images": "Resize or change format",
        "Photo details": "EXIF, remove location", "Look-alike photos": "Near-duplicate pictures", "Text from image / PDF": "OCR scanned pages",
        "Compare panes": "Differences of two folders", "FTP / SFTP / WebDAV": "Browse remote servers", "Phone notifications": "Alerts to your phone",
        "Storage by file type": "Which types take the space", "Recycle Bin": "See and restore deleted files", "Folder size history": "Watch a folder grow over time", "Smart collections": "Ready-made searches", "Mini-games": "Something to do while a scan runs", "Nearby devices": "Send files to phones and PCs (LocalSend)", "Transfers": "Copy and move queue", "Photo timeline": "Your photos by year and month", "Tag manager": "Rename, merge, remove tags", "Cloud files": "Files that are only placeholders","Automatic rules": "Sort new files by themselves", "Undo history": "What Ctrl+Z would undo", "Recent changes": "What changed lately", "Shortcuts & tips": "Every keyboard shortcut", "Tutorial": "A quick tour of Pinefiles", "What's new": "Changes in this version",
        "Customize": "Theme, behaviour, keys", "Theme editor": "Make your own colours", "Keyboard shortcuts": "Change any key", "Storage & index": "Sizes, rebuild index", "About & updates": "Version, install, update"}

# the settings-style list on the left of the tools area: (group, [(label, A attribute, args)])
TOOLS = [
    ("Clean up", [("Smart disk cleaner", "open_cleaner"), ("Duplicate files", "open_duplicates"), ("Largest files", "open_largest"),
                  ("Organize folder", "open_organize"), ("Disk usage map", "open_treemap"),
                  ("Storage by file type", "open_storage_types"), ("Folder size history", "open_folder_history"), ("Recycle Bin", "open_recycle_bin")]),
    ("Health & security", [("PC health", "open_health"), ("Backups", "open_health", ("backups",)),
                           ("Malware check", "open_malware"), ("Integrity check", "open_integrity"), ("System information", "open_system_info")]),
    ("Files & photos", [("Encrypted vault", "open_vault"), ("Sync two folders", "open_sync"), ("Checksum", "open_checksum"),
                        ("Convert images", "open_convert_images"), ("Photo details", "open_photo_info"),
                        ("Look-alike photos", "open_similar_photos"), ("Photo timeline", "open_timeline"), ("Tag manager", "open_tags"), ("Cloud files", "open_cloud"),("Transfers", "open_transfers"), ("Automatic rules", "open_rules"), ("Smart collections", "open_collections"), ("Undo history", "open_undo_history"), ("Recent changes", "open_recent_changes"), ("Text from image / PDF", "open_ocr"), ("Compare panes", "open_compare")]),
    ("Connect & share", [("Nearby devices", "open_localsend"), ("FTP / SFTP / WebDAV", "open_ftp"), ("Phone notifications", "open_notify")]),
    ("Pinefiles", [("Customize", "open_settings"), ("Theme editor", "open_themes"), ("Keyboard shortcuts", "open_keys"), ("Storage & index", "open_storage"), ("About & updates", "open_about"),
                    ("Mini-games", "open_games"), ("Shortcuts & tips", "open_shortcuts"), ("What's new", "open_whats_new"), ("Tutorial", "open_tutorial")]),
]

# What the list on the left and the overview show: related tools share ONE entry and open as tabs inside it (name, [tools in TOOLS]).
HUBS = [
    ("Clean up & organize", [("Clean up", ["Smart disk cleaner", "Duplicate files", "Largest files", "Look-alike photos", "Recycle Bin"]),
                             ("Disk usage", ["Disk usage map", "Storage by file type", "Folder size history"]),
                             ("Organize", ["Organize folder", "Automatic rules"])]),
    ("Health & security", [("Health & security", ["PC health", "Malware check", "System information"]), ("Backups", ["Backups"]),
                           ("Verify files", ["Checksum", "Integrity check"])]),
    ("Files & photos", [("Images & photos", ["Convert images", "Photo details", "Photo timeline", "Text from image / PDF"]),
                        ("Tags & collections", ["Tag manager", "Smart collections"]), ("Sync & compare", ["Sync two folders", "Compare panes"]),
                        ("Activity", ["Transfers", "Undo history", "Recent changes"]), ("Encrypted vault", ["Encrypted vault"])]),
    ("Connect & share", [("Connect", ["Nearby devices", "FTP / SFTP / WebDAV", "Cloud files", "Phone notifications"])]),
    ("Pinefiles", [("Customize", ["Customize", "Theme editor", "Keyboard shortcuts"]),
                   ("Help & about", ["About & updates", "Storage & index", "What's new", "Shortcuts & tips", "Mini-games"]), ("Tutorial", ["Tutorial"])]),
]
_BY_NAME = {it[0]: it for _g, items in TOOLS for it in items}
SUBS = {name: subs for _g, hubs in HUBS for name, subs in hubs}
NAV = []  # same shape as TOOLS: (group, [(label, A attribute, args)]); a hub of several tools opens through open_hub
for _g, _hubs in HUBS:
    _items = []
    for _n, _subs in _hubs:
        if len(_subs) == 1:
            _t = _BY_NAME[_subs[0]]
            _items.append((_n, _t[1], _t[2] if len(_t) > 2 else ()))
        else:
            _items.append((_n, "open_hub", (_n,)))
            DESC[_n] = ", ".join(x.lower() if i else x for i, x in enumerate(_subs))
    NAV.append((_g, _items))


class Page(tk.Frame):
    def __init__(self, A, parent, title):
        super().__init__(parent, bg=T["bg"])
        self._A, self._title, self._esc, self._close = A, title, None, None

    LOADING = ("reading", "loading", "scanning", "searching", "measuring", "checking", "looking", "collecting", "analys", "indexing",
               "building", "computing", "counting", "working", "please wait", "finding", "comparing", "calculating", "testing")

    def slow(self):
        """busy(), or a visible status line like 'Reading the Recycle Bin…': the tool is loading (used to offer the waiting games)."""
        if self.busy():
            return True
        stack = [self]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            try:
                if w.winfo_class() in ("Label", "TLabel") and w.winfo_ismapped():
                    txt = str(w.cget("text"))
                    tv = str(w.cget("textvariable"))
                    if tv:
                        txt = str(w.getvar(tv))
                    low = txt.strip().lower()
                    if low and len(low) < 140 and low.startswith(self.LOADING) and ("…" in low or "..." in low):
                        return True
            except tk.TclError:
                pass
        return False

    def busy(self):
        """True while this tool is running something (a scan, a transfer): then its tab is kept instead of being reused."""
        stack = [self]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            try:
                cls = w.winfo_class()
                if cls == "TProgressbar" and w.winfo_manager():  # shown by its tool (a hidden tab's widgets are not 'mapped', but a scan there still runs)
                    mx, v = float(w.cget("maximum")), float(w.cget("value"))
                    if w.cget("mode") == "indeterminate" or 0 < v < mx:
                        return True
                elif cls == "TButton" and w.winfo_manager() and str(w.cget("text")).strip(" .…").lower() in (
                        "cancel", "stop", "stop scan", "cancel scan", "stop scanning") and "disabled" not in w.state():
                    return True
            except tk.TclError:
                pass
        return False

    # ---- the Toplevel methods the dialogs call
    def title(self, text=None):
        if text is None:
            return self._title
        self._title = text
        self._A.build_tabs()

    def geometry(self, *a):
        return ""

    def _noop(self, *a, **k):
        return None

    transient = attributes = resizable = minsize = maxsize = lift = grab_set = grab_release = _noop
    withdraw = deiconify = iconbitmap = overrideredirect = _noop

    def protocol(self, name, func=None):
        if name == "WM_DELETE_WINDOW":
            self._close = func

    def focus_force(self):
        self.focus_set()

    def bind(self, seq=None, func=None, add=None):
        if seq == "<Escape>":
            self._esc = func
            return ""
        return super().bind(seq, func, add)

    def close(self):
        """What the tab's ✕ does: the dialog's own close handler if it set one, else just destroy."""
        if self._close:
            self._close()
        else:
            self.destroy()

    def destroy(self):
        was_active = _S["active"] is self
        if self in _S["pages"]:
            _S["pages"].remove(self)
        wid = _S["ids"].pop(self, None)
        try:
            if wid is not None:
                _S["cv"].delete(wid)
        except tk.TclError:
            pass
        super().destroy()
        if was_active:
            _S["active"] = None
        try:  # the whole window may be closing: then there is no tab bar left to refresh
            if was_active:
                show_files(self._A, force=True)
            self._A.build_tabs()
        except tk.TclError:
            pass


# ------------------------------------------------------------------ the full-window tools area
def _host(A):
    if _S["host"] is None or not _S["host"].winfo_exists():
        from tkinter import ttk
        h = _S["host"] = tk.Frame(A.root, bg=T["bg"])
        _S["nav"] = tk.Frame(h, bg=T["panel"], width=240)
        _S["nav"].pack(side="left", fill="y")
        _S["nav"].pack_propagate(False)
        right = tk.Frame(h, bg=T["bg"])
        right.pack(side="left", fill="both", expand=True)
        _S["sb"] = ttk.Scrollbar(right, orient="vertical")
        _S["hb"] = ttk.Scrollbar(right, orient="horizontal")
        _S["cv"] = cv = tk.Canvas(right, bg=T["bg"], highlightthickness=0, bd=0, yscrollcommand=_S["sb"].set, xscrollcommand=_S["hb"].set)
        _S["sb"].configure(command=cv.yview)
        _S["hb"].configure(command=cv.xview)
        _S["sb"].pack(side="right", fill="y")
        cv.pack(side="top", fill="both", expand=True)
        cv.bind("<Configure>", lambda e: _fit())
    if not _S["esc"]:
        _S["esc"] = True
        A.root.bind("<Escape>", lambda e: _on_escape(e), add="+")
        register_scroll(A.root, _S["cv"])
    return _S["host"]


_SCROLLERS = set()
_SELF_SCROLL = ("Treeview", "Text", "Listbox", "TCombobox", "TSpinbox", "Spinbox")


def register_scroll(root, canvas):
    """Make `canvas` scroll with the mouse wheel whenever the pointer is anywhere over it or its contents."""
    _SCROLLERS.difference_update([c for c in _SCROLLERS if not c.winfo_exists()])
    _SCROLLERS.add(canvas)
    if not _S.get("wheel"):
        _S["wheel"] = True
        root.bind_all("<MouseWheel>", lambda e: _wheel(root, e), add="+")
        root.bind_all("<Shift-MouseWheel>", lambda e: _wheel(root, e, horizontal=True), add="+")


def _wheel(root, e, horizontal=False):
    try:
        w = root.winfo_containing(e.x_root, e.y_root) or e.widget
    except (KeyError, tk.TclError):
        w = e.widget
    if isinstance(w, str):
        return
    while w is not None:
        if w.winfo_class() in _SELF_SCROLL:
            return  # these scroll themselves
        if w in _SCROLLERS:
            if horizontal:
                if w.xview() != (0.0, 1.0):
                    w.xview_scroll(-1 if e.delta > 0 else 1, "units")
            elif w.yview() != (0.0, 1.0):
                w.yview_scroll(-1 if e.delta > 0 else 1, "units")
            return
        w = w.master


def _fit(_=None):
    """Size the active page to the visible area, but never smaller than it needs: then the canvas scrolls."""
    p, cv = _S["active"], _S["cv"]
    if p is None or cv is None or not cv.winfo_exists() or p not in _S["ids"]:
        return
    try:
        want = 168 if cv.winfo_toplevel().winfo_width() < 900 else 240  # narrow window: slimmer tool list
        if int(_S["nav"].cget("width")) != want:
            _S["nav"].configure(width=want)
        w, h = cv.winfo_width(), cv.winfo_height()
        need, needw = p.winfo_reqheight(), p.winfo_reqwidth()
        W, H = max(w, needw), max(h, need)
        cv.itemconfigure(_S["ids"][p], width=W, height=H)
        cv.configure(scrollregion=(0, 0, W, H))
        if need <= h:
            cv.yview_moveto(0)
            _S["sb"].pack_forget()
        elif not _S["sb"].winfo_ismapped():
            _S["sb"].pack(side="right", fill="y", before=cv)
        if needw <= w:
            cv.xview_moveto(0)
            _S["hb"].pack_forget()
        elif not _S["hb"].winfo_ismapped():
            _S["hb"].pack(side="bottom", fill="x", before=cv)
    except tk.TclError:
        pass


def _poll(A):
    if _S["active"] is None or _S["host"] is None or not _S["host"].winfo_exists():
        _S["poll"] = None
        return
    _fit()
    try:
        import ui_games
        p = _S["active"]
        ui_games.watch(A, _S["host"], p, p.slow() if A.cfg.get("game_offer", True) else False)
    except tk.TclError:
        pass
    _S["poll"] = A.root.after(400, lambda: _poll(A))


def _on_escape(e):
    p = _S["active"]
    if p and p._esc and str(e.widget).startswith(str(p)):
        p._esc(e)


def _build_nav(A):
    outer = _S["nav"]
    if _S.get("navsearch") is None or not _S["navsearch"].winfo_exists():
        from tkinter import ttk
        _S["navq"] = tk.StringVar()
        _S["navsearch"] = ttk.Entry(outer, textvariable=_S["navq"])
        _S["navsearch"].pack(side="top", fill="x", padx=10, pady=(10, 2))
        _S["navq"].trace_add("write", lambda *_: _build_nav(A))
        _S["navsearch"].bind("<Return>", lambda e: _first_match(A))
        _S["navsearch"].bind("<Escape>", lambda e: (_S["navq"].set(""), "break")[1])
        _S["navsearch"].bind("<Down>", lambda e: (_kbd_move(A, 1), "break")[1])
        _S["navsearch"].bind("<Up>", lambda e: (_kbd_move(A, -1), "break")[1])
        _S["navbox"] = tk.Frame(outer, bg=T["panel"])
        _S["navbox"].pack(side="top", fill="both", expand=True)
    box = _S["navbox"]
    for w in box.winfo_children():
        w.destroy()
    _S["rows"] = {}
    _S["kbd"] = None
    want = _S["navq"].get().strip().lower()
    cv = tk.Canvas(box, bg=T["panel"], highlightthickness=0, bd=0)
    cv.pack(fill="both", expand=True)
    nav = tk.Frame(cv, bg=T["panel"])
    win = cv.create_window(0, 0, window=nav, anchor="nw")
    nav.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
    cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))

    register_scroll(A.root, cv)
    fs = A.cfg["font_size"]
    back = tk.Label(nav, text="←  Back to files", anchor="w", bg=T["panel"], fg=T["accent"], font=("Segoe UI", fs, "bold"), cursor="hand2", padx=18, pady=12)
    back.pack(fill="x")
    back.bind("<Button-1>", lambda e: show_files(A))

    def row(label, cmd, indent, bold=False):
        r = tk.Label(nav, text=label or "Overview", anchor="w", bg=T["panel"], fg=T["muted"], font=("Segoe UI", fs, "bold" if bold else "normal"),
                     cursor="hand2", padx=indent, pady=5)
        r.pack(fill="x", padx=8, pady=1)
        r.bind("<Button-1>", lambda e: cmd())
        if label:
            r.bind("<Button-3>", lambda e, label=label: _row_menu(A, e, label))
        r.bind("<Enter>", lambda e: r.configure(bg=T["raised"]) if _S["rows"].get(_S["cur"]) is not r else None)
        r.bind("<Leave>", lambda e: r.configure(bg=T["sel"] if _S["rows"].get(_S["cur"]) is r else T["panel"]))
        _S["rows"][label] = r

    if not want:
        row(None, lambda: open_tools(A), 12, True)
    for group, items in NAV:
        shown = [it for it in items if not want or want in it[0].lower() or want in DESC.get(it[0], "").lower()]
        if not shown:
            continue
        tk.Label(nav, text=group.upper(), anchor="w", bg=T["panel"], fg=T["muted"], font=("Segoe UI", fs - 2, "bold"), padx=20).pack(fill="x", pady=(14, 3))
        for it in shown:
            row(it[0], lambda it=it: _open(A, it[0], it[1], it[2] if len(it) > 2 else ()), 20)
    if want and not _S["rows"]:
        tk.Label(nav, text="No tool matches", anchor="w", bg=T["panel"], fg=T["muted"], font=("Segoe UI", fs), padx=20, pady=10).pack(fill="x")
    _hilite()


def _row_menu(A, e, label):
    pinned = list(A.cfg.get("pinned_tools", []))
    m = A.make_menu()
    if label in pinned:
        m.add_command(label="Remove from the toolbar", command=lambda: _pin(A, [p for p in pinned if p != label]))
    elif len(pinned) < 4:
        m.add_command(label="Pin to the toolbar", command=lambda: _pin(A, pinned + [label]))
    else:
        m.add_command(label="Toolbar pins are full (4)", state="disabled")
    m.tk_popup(e.x_root, e.y_root)


def _pin(A, names):
    import ui_toolbar
    A.save_cfg(pinned_tools=names)
    ui_toolbar.sync_pins(A)


def _visible_tools():
    return [it for _, items in NAV for it in items if it[0] in _S["rows"]]


def _kbd_move(A, d):
    """Up / Down in the tool search: step through the listed tools (highlighted); Enter opens the highlighted one."""
    vis = _visible_tools()
    if not vis:
        return
    cur = _S.get("kbd")
    i = (0 if d > 0 else len(vis) - 1) if cur is None else (cur + d) % len(vis)
    _S["kbd"] = i
    _hilite()
    r = _S["rows"][vis[i][0]]
    r.configure(bg=T["raised"], fg=T["fg"])
    try:  # keep the row in view
        cv = r.master.master
        cv.update_idletasks()
        top, bot = r.winfo_y(), r.winfo_y() + r.winfo_height()
        h = cv.winfo_height()
        total = max(1, r.master.winfo_height())
        if top < cv.canvasy(0):
            cv.yview_moveto(top / total)
        elif bot > cv.canvasy(h):
            cv.yview_moveto((bot - h) / total)
    except tk.TclError:
        pass


def _first_match(A):
    """Enter in the tool search opens the highlighted tool, or the first one that matches."""
    vis = _visible_tools()
    if not vis:
        return
    it = vis[_S["kbd"]] if _S.get("kbd") is not None and _S["kbd"] < len(vis) else vis[0]
    _S["navq"].set("")
    _open(A, it[0], it[1], it[2] if len(it) > 2 else ())


def _hilite():
    cur = _S["cur"]
    for label, r in _S["rows"].items():
        on = label == cur
        r.configure(bg=T["sel"] if on else T["panel"], fg=T["fg"] if on else T["muted"])


def _open(A, label, attr, args):
    _S["pending"] = label
    A.save_cfg(recent_tools=([label] + [x for x in A.cfg.get("recent_tools", []) if x != label])[:5])
    if attr == "open_hub":
        open_hub(A, *args)
    else:
        getattr(A, attr)(*args)


def _match(title):
    """The list entry a page belongs to: its own name, or the hub holding the tool of that name."""
    t = (title or "").lower()
    for it in [i for _, items in NAV for i in items]:
        subs = SUBS.get(it[0], ())
        if it[0].lower() == t or any(x.lower() == t for x in subs):
            return it[0]
    for it in [i for _, items in NAV for i in items]:
        if it[0].lower() in t or (len(t) > 4 and t in it[0].lower()):
            return it[0]
    return None


# ------------------------------------------------------------------ opening, showing, leaving
def new_page(A, title):
    """Open a tool. There is ONE Tools tab: a new tool takes its place, unless that tool is still busy (then it keeps its own tab)."""
    if _S.get("embed") is not None:  # a tool opened inside a hub: it fills the hub's body instead of taking a tab
        p = Page(A, _S["embed"], title)
        p.pack(fill="both", expand=True)
        return p
    _host(A)
    old = [q for q in _S["pages"] if not q.busy()]
    p = Page(A, _S["cv"], title)
    _S["ids"][p] = _S["cv"].create_window(0, 0, window=p, anchor="nw", state="hidden")
    _S["pages"].append(p)
    show_page(A, p)
    for q in old:  # the old tool goes only after the new one is on screen: no flash of the file view in between
        q.destroy()
    return p


def open_hub(A, name):
    """One list entry that holds several related tools: a row of tabs on top, the chosen tool below. A tool is built when first picked and
    kept (a running scan carries on while you look at a sibling)."""
    subs = SUBS[name]
    p = new_page(A, name)
    fs = A.cfg["font_size"]
    bar = tk.Frame(p, bg=T["bg"])
    bar.pack(fill="x", padx=22, pady=(14, 0))
    body = tk.Frame(p, bg=T["bg"])
    body.pack(fill="both", expand=True)
    tabs, built = {}, {}
    cur = {"name": None}

    def pick(sub):
        old = built.get(cur["name"])
        if old is not None and old.winfo_exists():
            old.pack_forget()
        cur["name"] = sub
        for n, b in tabs.items():
            b.configure(fg=T["fg"] if n == sub else T["muted"], font=("Segoe UI", fs, "bold" if n == sub else "normal"))
            b._under.configure(bg=T["accent"] if n == sub else T["bg"])
        pg = built.get(sub)
        if pg is not None and pg.winfo_exists():
            pg.pack(fill="both", expand=True)
            return
        tool = _BY_NAME[sub]
        _S["embed"] = body
        try:
            getattr(A, tool[1])(*(tool[2] if len(tool) > 2 else ()))
        finally:
            _S["embed"] = None
        kids = [c for c in body.winfo_children() if isinstance(c, Page)]
        built[sub] = kids[-1] if kids else None

    for sub in subs:
        cell = tk.Frame(bar, bg=T["bg"])
        cell.pack(side="left", padx=(0, 18))
        b = tk.Label(cell, text=sub, bg=T["bg"], fg=T["muted"], font=("Segoe UI", fs), cursor="hand2", pady=4)
        b.pack()
        b._under = tk.Frame(cell, height=2, bg=T["bg"])
        b._under.pack(fill="x")
        b.bind("<Button-1>", lambda e, s_=sub: pick(s_))
        tabs[sub] = b
    def esc(e):  # Esc goes to the tool that is showing
        pg = built.get(cur["name"])
        if pg is not None and pg._esc:
            pg._esc(e)
    p._esc = esc
    pick(subs[0])
    return p


def tab_label(p):
    return p.title() if (p.busy() or len(_S["pages"]) > 1) else "Tools"


def open_tools(A, _=None):
    """The Tools button: straight into the Tools tab (an overview of everything; the list on the left switches tools)."""
    _S["pending"] = None
    p = new_page(A, "Tools")
    fs = A.cfg["font_size"]
    tk.Label(p, text="Tools", bg=T["bg"], fg=T["fg"], font=("Segoe UI", fs + 8, "bold")).pack(anchor="w", padx=28, pady=(22, 4))
    tk.Label(p, text="Pick a tool on the left or here.", bg=T["bg"], fg=T["muted"], font=("Segoe UI", fs)).pack(anchor="w", padx=28)
    try:
        import ui_extras
        stats = tk.Frame(p, bg=T["bg"])
        stats.pack(fill="x", padx=22, pady=(14, 0))
        for i, (title, value, detail, col, act) in enumerate(ui_extras.overview_stats(A)):
            card = tk.Frame(stats, bg=T["panel"], padx=14, pady=10, cursor="hand2")
            card.grid(row=0, column=i, padx=6, sticky="nsew")
            parts = [tk.Label(card, text=title.upper(), bg=T["panel"], fg=T["muted"], font=("Segoe UI", fs - 3, "bold")),
                     tk.Label(card, text=value, bg=T["panel"], fg=col, font=("Segoe UI", fs + 6, "bold")),
                     tk.Label(card, text=detail, bg=T["panel"], fg=T["muted"], font=("Segoe UI", fs - 2))]
            for w in parts:
                w.pack(anchor="w")
            for w in (card, *parts):
                w.configure(cursor="hand2")
                w.bind("<Button-1>", lambda e, act=act: getattr(A, act[0])(*act[1]))
            stats.columnconfigure(i, weight=1, uniform="stat")
    except Exception:  # noqa - the overview works without its status row
        pass
    every = {it[0]: it for _g, items in NAV for it in items}
    groups = ([("Recently used", [every[n] for n in A.cfg.get("recent_tools", []) if n in every])] if any(n in every for n in A.cfg.get("recent_tools", [])) else []) + NAV
    for group, items in groups:
        tk.Label(p, text=group.upper(), bg=T["bg"], fg=T["muted"], font=("Segoe UI", fs - 2, "bold")).pack(anchor="w", padx=28, pady=(10, 2))
        row = tk.Frame(p, bg=T["bg"])
        row.pack(fill="x", padx=22)
        for i, it in enumerate(items):
            card = tk.Frame(row, bg=T["panel"], cursor="hand2", padx=12, pady=6, width=210, height=58)
            card.grid(row=i // 4, column=i % 4, padx=6, pady=3, sticky="nsew")
            card.grid_propagate(False)
            parts = [tk.Label(card, text=it[0], bg=T["panel"], fg=T["fg"], font=("Segoe UI", fs, "bold"), anchor="w", cursor="hand2"),
                     tk.Label(card, text=DESC.get(it[0], ""), bg=T["panel"], fg=T["muted"], font=("Segoe UI", fs - 2), anchor="w",
                              justify="left", wraplength=190, cursor="hand2")]
            for w in parts:
                w.pack(fill="x")
            for w in (card, *parts):
                w.bind("<Button-1>", lambda e, it=it: _open(A, it[0], it[1], it[2] if len(it) > 2 else ()))
    return p


def _enter(A):
    """Take the whole file view off the screen and put the tools area in its place."""
    if _S["hidden"]:
        return
    parts = [A.crumbs.master.master, A.cmdbar, A.entry.master, A.chipbar, A.mid.master]  # path bar, toolbar, search, chips, body
    _S["hidden"] = [(w, w.pack_info()) for w in parts if w.winfo_manager() == "pack"]
    for w, _info in _S["hidden"]:
        w.pack_forget()
    _S["host"].pack(fill="both", expand=True, after=A.tabbar)
    if _S.get("navq") is not None:
        _S["navq"].set("")
    _build_nav(A)
    A.root.update_idletasks()


def show_page(A, p):
    _host(A)
    _enter(A)
    _S["active"] = p
    for q, wid in _S["ids"].items():
        _S["cv"].itemconfigure(wid, state="normal" if q is p else "hidden")
    _S["cv"].yview_moveto(0)
    _fit()
    _S["cur"] = _S.pop("pending", None) or _match(p.title())  # the entry picked in the list, else the tool whose name fits
    _hilite()
    if _S["poll"] is None:
        _S["poll"] = A.root.after(400, lambda: _poll(A))
    p.focus_set()
    A.build_tabs()


def show_files(A, _=None, force=False):
    """Back to the folder view (a page keeps living in its tab)."""
    if not _S["hidden"] and not force:
        return
    _S["active"] = None
    if _S["host"] is not None and _S["host"].winfo_exists():
        _S["host"].pack_forget()
    prev = A.tabbar
    for w, info in _S["hidden"]:
        info = {k: v for k, v in info.items() if k != "in"}
        if w is A.crumbs.master.master:  # the path bar sits ABOVE the tab bar
            w.pack(before=A.tabbar, **info)
        else:
            w.pack(after=prev, **info)
            prev = w
    _S["hidden"] = []
    A.build_tabs()


def refresh_theme(A):
    """The theme changed while the Tools area exists: recolour its frame and rebuild the tool list."""
    h = _S["host"]
    if h is None or not h.winfo_exists():
        return
    h.configure(bg=T["bg"])
    _S["cv"].configure(bg=T["bg"])
    _S["nav"].configure(bg=T["panel"])
    if _S.get("navbox") is not None:
        _S["navbox"].configure(bg=T["panel"])
    for p in _S["pages"]:
        p.configure(bg=T["bg"])
    _build_nav(A)


def active():
    return _S["active"]


def pages():
    return list(_S["pages"])
