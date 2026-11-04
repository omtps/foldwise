"""Pinefiles's own file / folder chooser: tools that ask for a file, a folder or a save location show this window (same look as the rest
of the app, same drives and favourite places) instead of the Windows dialog.

`filedialog` below has the same four functions and keyword arguments as tkinter.filedialog (parent, title, initialdir, initialfile,
filetypes, defaultextension), so a module only has to import it from here. If this window cannot be built the Windows dialog is used.
"""
import os
import tkinter as tk
from tkinter import ttk

from ff_core import T, ThemedBox as messagebox, fmt_date, human_size

LAST = {"dir": ""}   # the folder of the previous choice: the next dialog starts there
DIALOG = {"w": None}  # the open dialog (the tests drive it through this)


def _places():
    home = os.path.expanduser("~")
    out = [("Home", home)]
    for n in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
        p = os.path.join(home, n)
        if os.path.isdir(p):
            out.append((n, p))
    try:
        import ff_extras as X
        for d, _kind, _free, _total in X.drives():
            out.append((d.rstrip(chr(92)) or d, d))
    except Exception:  # noqa - the drive list is a convenience
        for c in "CDEFGH":
            if os.path.isdir(c + ":" + chr(92)):
                out.append((c + ":", c + ":" + chr(92)))
    return out


def _patterns(filetypes):
    """[(label, [globs])] from tkinter-style filetypes; always ends with 'All files'."""
    out = []
    for label, pat in filetypes or []:
        pats = [p.lower() for p in str(pat).replace(";", " ").split() if p]
        if pats and "*.*" not in pats and "*" not in pats:
            out.append((label, pats))
    out.append(("All files", ["*"]))
    return out


def _match(name, pats):
    import fnmatch
    low = name.lower()
    return any(fnmatch.fnmatch(low, p) for p in pats)


class Picker(tk.Toplevel):
    """mode: 'open' (one file), 'openmany', 'dir' or 'save'."""

    def __init__(self, parent, mode, title, initialdir="", initialfile="", filetypes=None, defaultextension=""):
        top = parent.winfo_toplevel() if parent is not None else tk._default_root
        super().__init__(top)
        self.mode, self.result, self.ext = mode, None, defaultextension or ""
        self.types = _patterns(filetypes)
        self.cur = ""
        self.configure(bg=T["bg"])
        self.title(title or {"open": "Open a file", "openmany": "Open files", "dir": "Choose a folder", "save": "Save as"}[mode])
        self.transient(top)
        w, h = 800, 540
        try:
            self.geometry(f"{w}x{h}+{max(0, top.winfo_rootx() + (top.winfo_width() - w) // 2)}+{max(0, top.winfo_rooty() + (top.winfo_height() - h) // 3)}")
        except tk.TclError:
            self.geometry(f"{w}x{h}")

        bar = ttk.Frame(self, padding=(12, 10, 12, 4))
        bar.pack(fill="x")
        ttk.Button(bar, text="↑ Up", width=6, command=self.up).pack(side="left")
        self.pathv = tk.StringVar()
        self.pathe = ttk.Entry(bar, textvariable=self.pathv)
        self.pathe.pack(side="left", fill="x", expand=True, padx=8)
        self.pathe.bind("<Return>", self._typed)

        bottom = ttk.Frame(self, padding=(12, 6, 12, 12))
        bottom.pack(side="bottom", fill="x")
        row = ttk.Frame(bottom)
        row.pack(fill="x")
        if mode != "dir":
            ttk.Label(row, text="Name").pack(side="left")
            self.namev = tk.StringVar(value=initialfile or "")
            self.namee = ttk.Entry(row, textvariable=self.namev)
            self.namee.pack(side="left", fill="x", expand=True, padx=8)
            self.namee.bind("<Return>", lambda e: self.accept())
        else:
            self.namev = tk.StringVar()
            self.hint = ttk.Label(row, text="Pick a folder in the list, or press the button to use the folder you are in.", style="DetKey.TLabel", background=T["bg"])
            self.hint.pack(side="left", fill="x", expand=True)
        self.typev = tk.StringVar(value=self.types[0][0])
        if mode in ("open", "openmany"):
            cb = ttk.Combobox(row, textvariable=self.typev, values=[t[0] for t in self.types], state="readonly", width=22)
            cb.pack(side="left", padx=(0, 8))
            cb.bind("<<ComboboxSelected>>", lambda e: self.load(self.cur))
        row2 = ttk.Frame(bottom)
        row2.pack(fill="x", pady=(8, 0))
        if mode in ("save", "dir"):
            ttk.Button(row2, text="New folder", command=self.new_folder).pack(side="left")
        ttk.Button(row2, text="Cancel", command=self.cancel).pack(side="right")
        okt = {"open": "Open", "openmany": "Open", "dir": "Use this folder", "save": "Save"}[mode]
        self.okb = ttk.Button(row2, text=okt, style="Accent.TButton", command=self.accept)
        self.okb.pack(side="right", padx=8)

        mid = tk.Frame(self, bg=T["bg"])
        mid.pack(fill="both", expand=True, padx=12)
        self.places = tk.Listbox(mid, width=16, bg=T["panel"], fg=T["fg"], selectbackground=T["sel"], selectforeground=T["fg"], bd=0,
                                 highlightthickness=0, activestyle="none", exportselection=False, font=("Segoe UI", 10))
        self.places.pack(side="left", fill="y", padx=(0, 8))
        self._places = _places()
        for label, _p in self._places:
            self.places.insert("end", "  " + label)
        self.places.bind("<<ListboxSelect>>", self._place)
        self.tv = ttk.Treeview(mid, columns=("mod", "size"), show="tree headings", selectmode="extended" if mode == "openmany" else "browse")
        for c, text, wd, anc in (("#0", "Name", 380, "w"), ("mod", "Modified", 130, "w"), ("size", "Size", 90, "e")):
            self.tv.heading(c, text=text, anchor=anc)
            self.tv.column(c, width=wd, anchor=anc, stretch=(c == "#0"))
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tv.pack(side="left", fill="both", expand=True)
        self.tv.tag_configure("dir", foreground=T["accent"])
        self.tv.bind("<Double-1>", self._double)
        self.tv.bind("<<TreeviewSelect>>", self._select)
        self.tv.bind("<Return>", lambda e: self.accept())
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        start = initialdir if initialdir and os.path.isdir(initialdir) else (LAST["dir"] if os.path.isdir(LAST["dir"] or "") else os.path.expanduser("~"))
        self.load(start)
        DIALOG["w"] = self
        self.focus_set()
        (self.namee if mode != "dir" else self.tv).focus_set()

    # ---- listing
    def load(self, path):
        path = os.path.normpath(path) if path else os.path.expanduser("~")
        if len(path) == 2 and path[1] == ":":
            path += chr(92)
        pats = dict(self.types).get(self.typev.get(), ["*"])
        try:
            with os.scandir(path) as it:
                ents = list(it)
        except OSError as e:
            messagebox.showerror("Can't open that folder", str(e), parent=self)
            return
        self.cur = path
        self.pathv.set(path)
        self.tv.delete(*self.tv.get_children())
        self._rows = {}
        dirs, files = [], []
        for e in ents:
            try:
                if e.name.startswith(".") and e.name != "..":
                    continue
                (dirs if e.is_dir() else files).append(e)
            except OSError:
                pass
        for e in sorted(dirs, key=lambda x: x.name.lower()):
            self._add(e, True)
        if self.mode != "dir":
            for e in sorted(files, key=lambda x: x.name.lower()):
                if self.mode == "save" or _match(e.name, pats):
                    self._add(e, False)

    def _add(self, e, isdir):
        try:
            st = e.stat()
            mod, size = fmt_date(st.st_mtime), "" if isdir else human_size(st.st_size)
        except OSError:
            mod, size = "", ""
        iid = f"r{len(self._rows)}"
        self._rows[iid] = (e.path, isdir)
        self.tv.insert("", "end", iid=iid, text=("\U0001F4C1  " if isdir else "      ") + e.name, values=(mod, size), tags=("dir",) if isdir else ())

    # ---- navigation
    def up(self):
        parent = os.path.dirname(self.cur.rstrip(chr(92)))
        if parent and parent != self.cur:
            self.load(parent)

    def _place(self, _e=None):
        c = self.places.curselection()
        if c:
            self.load(self._places[c[0]][1])

    def _typed(self, _e=None):
        p = os.path.expandvars(self.pathv.get().strip().strip('"'))
        if os.path.isdir(p):
            self.load(p)
        elif p and os.path.exists(p) and self.mode in ("open", "openmany"):
            self.load(os.path.dirname(p))
            self.namev.set(os.path.basename(p))
            self.accept()
        elif p and self.mode == "save":
            self.load(os.path.dirname(p) or self.cur)
            self.namev.set(os.path.basename(p))

    def _double(self, _e=None):
        sel = self.tv.selection()
        if not sel:
            return
        path, isdir = self._rows[sel[0]]
        if isdir:
            self.load(path)
        elif self.mode != "dir":
            self.accept()

    def _select(self, _e=None):
        sel = [self._rows[i] for i in self.tv.selection() if i in self._rows]
        files = [os.path.basename(p) for p, d in sel if not d]
        if files and self.mode != "dir":
            self.namev.set(files[0] if len(files) == 1 else " ".join(f'"{f}"' for f in files))

    def new_folder(self):
        from ff_core import ThemedAsk
        name = ThemedAsk.askstring("New folder", "Name of the new folder:", parent=self)
        if name and name.strip():
            try:
                os.makedirs(os.path.join(self.cur, name.strip()))
            except OSError as e:
                messagebox.showerror("New folder", str(e), parent=self)
            self.load(self.cur)

    # ---- result
    def _finish(self, value):
        self.result = value
        if self.mode == "dir" or self.mode == "save":
            base = value if self.mode == "dir" else os.path.dirname(value)
        else:
            base = os.path.dirname(value[0]) if value else ""
        if base:
            LAST["dir"] = base
        self.destroy()

    def accept(self):
        sel = [self._rows[i] for i in self.tv.selection() if i in self._rows]
        if self.mode == "dir":
            folders = [p for p, d in sel if d]
            return self._finish(os.path.normpath(folders[0] if folders else self.cur))
        if self.mode == "save":
            name = self.namev.get().strip().strip('"')
            if not name:
                return None
            if self.ext and not os.path.splitext(name)[1]:
                name += self.ext
            path = os.path.normpath(name if os.path.isabs(name) else os.path.join(self.cur, name))
            if os.path.isdir(path):
                return self.load(path)
            if os.path.exists(path) and not messagebox.askyesno("Replace the file?", f"{os.path.basename(path)} already exists. Replace it?", parent=self):
                return None
            return self._finish(path)
        if sel and sel[0][1] and not [p for p, d in sel if not d]:  # only a folder is selected: go into it
            return self.load(sel[0][0])
        names = [p for p, d in sel if not d]
        if not names:
            typed = self.namev.get().strip().strip('"')
            p = os.path.join(self.cur, typed) if typed else ""
            if p and os.path.isfile(p):
                names = [p]
        if not names:
            return None
        return self._finish(tuple(os.path.normpath(n) for n in names) if self.mode == "openmany" else os.path.normpath(names[0]))

    def cancel(self):
        self.result = None
        self.destroy()

    def run(self):
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.wait_window(self)
        DIALOG["w"] = None
        return self.result


def _ask(mode, kw):
    parent = kw.get("parent")
    try:
        d = Picker(parent, mode, kw.get("title"), kw.get("initialdir") or "", kw.get("initialfile") or "", kw.get("filetypes"), kw.get("defaultextension") or "")
    except tk.TclError:
        return NotImplemented
    return d.run()


class filedialog:
    """Drop-in for tkinter.filedialog (the functions Pinefiles uses)."""

    @staticmethod
    def askopenfilename(**kw):
        r = _ask("open", kw)
        if r is NotImplemented:
            from tkinter import filedialog as native
            return native.askopenfilename(**kw)
        return r or ""

    @staticmethod
    def askopenfilenames(**kw):
        r = _ask("openmany", kw)
        if r is NotImplemented:
            from tkinter import filedialog as native
            return native.askopenfilenames(**kw)
        return r or ()

    @staticmethod
    def askdirectory(**kw):
        r = _ask("dir", kw)
        if r is NotImplemented:
            from tkinter import filedialog as native
            return native.askdirectory(**kw)
        return r or ""

    @staticmethod
    def asksaveasfilename(**kw):
        r = _ask("save", kw)
        if r is NotImplemented:
            from tkinter import filedialog as native
            return native.asksaveasfilename(**kw)
        return r or ""
