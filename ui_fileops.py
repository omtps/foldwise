"""File operations: open, copy/cut/paste, delete, rename, new, compress/extract, undo, transfers and conflict prompts.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import ff_extras as X
import ff_platform
import os
import shutil
import subprocess
import threading
import tkinter as tk
from ff_core import ThemedAsk as simpledialog
from ff_core import ThemedBox as messagebox
from tkinter import ttk
from ff_core import (T, fmt_date, human_size, log_error, recycle, shell_verb, unique_dest)


def do_undo(A, _=None):
    if not A.st["undo"]:
        A.status.set("Nothing to undo")
        return
    kind, data = A.st["undo"].pop()
    try:
        if kind == "rename":
            os.rename(data[1], data[0])
        elif kind == "bulk":
            for old, new in reversed(data):
                os.rename(new, old)
        elif kind == "move":
            for src, dst in reversed(data):
                shutil.move(dst, src)
        elif kind == "organize":
            pairs_, created_ = data
            for src, dst in reversed(pairs_):
                shutil.move(dst, src)
            for d_ in created_:
                try:
                    os.rmdir(d_)  # only succeeds if nothing else ended up in it
                except OSError:
                    pass
        elif kind in ("copy", "create"):
            recycle([d[1] if isinstance(d, tuple) else d for d in data])
        elif kind == "delete":
            A.status.set("Restoring from the Recycle Bin…")

            def work():
                back = X.restore_from_recycle(data)
                log_error(f"undo delete {data!r} -> restored {back!r}")
                msg = "Undid delete" if back else "Couldn't find it in the Recycle Bin (see error.log)"
                A.root.after(0, lambda: (A.status.set(msg), A.after_change()))
            threading.Thread(target=work, daemon=True).start()
            return
    except OSError as e:
        messagebox.showerror("Undo", str(e))
    A.status.set(f"Undid {kind}")
    A.after_change()


def run_transfer(A, paths, folder, move, clear_clip=False):
    if A.st["xfer"]:
        A.status.set("Another transfer is still running…")
        return
    if any(X.zip_is_virtual(p) for p in paths):
        move = False  # taking files out of an archive is always a copy
    A.st["xfer"], A.st["xcancel"] = True, False
    verb = "Moving" if move else "Copying"
    A.status.set(f"{verb}…")

    def prog(done, total, name):
        pct = int(done * 100 / total) if total else 0
        A.root.after(0, A.status.set, f"{verb} {name}  —  {pct}%    (Esc to cancel)")

    conflict = {"all": None}

    def resolve_conflict(src, target):  # runs on the worker thread
        if conflict["all"]:
            act = conflict["all"]
        else:
            result, ev = {}, threading.Event()
            A.root.after(0, A.conflict_dialog, src, target, result, ev)
            ev.wait()
            act = result.get("act", "cancel")
            if result.get("all") and act != "cancel":
                conflict["all"] = act
        if act == "replace" and not recycle([target]):
            act = "keep"
        return act

    def work():
        try:
            pairs, err = X.transfer(paths, folder, move, prog, lambda: A.st["xcancel"], resolve_conflict), None
        except X.Cancelled:
            pairs, err = [], "Cancelled"
        except Exception as e:  # noqa
            pairs, err = [], str(e)
        A.root.after(0, done, pairs, err)

    def done(pairs, err):
        A.st["xfer"] = False
        if err and err != "Cancelled":
            messagebox.showerror("Foldwise", err)
        if pairs:
            A.push_undo("move" if move else "copy", pairs)
            if clear_clip:
                A.st["clip"] = ([], False)
        A.status.set("Cancelled" if err == "Cancelled" else f"{verb[:-3]}ed {len(pairs)} item(s)")
        A.after_change()

    threading.Thread(target=work, daemon=True).start()


def conflict_dialog(A, src, target, result, ev):
    try:
        win = A.toplevel("Item already exists", "620x330", tab=False)
        win.attributes("-topmost", True)
        win.grab_set()
        f = ttk.Frame(win, padding=20)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"“{os.path.basename(target)}” already exists here", style="DetName.TLabel",
                  background=T["bg"], wraplength=560).pack(anchor="w")

        def info(p):
            try:
                s_ = os.stat(p)
                return ("Folder" if os.path.isdir(p) else human_size(s_.st_size)) + f"   •   modified {fmt_date(s_.st_mtime)}"
            except OSError:
                return ""

        ttk.Label(f, text="Existing:   " + info(target)).pack(anchor="w", pady=(14, 2))
        ttk.Label(f, text="Incoming:  " + info(src)).pack(anchor="w")
        allv = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Do this for all remaining conflicts", variable=allv).pack(anchor="w", pady=16)
        row = ttk.Frame(f)
        row.pack(anchor="e", side="bottom")

        def choose(act):
            result.update(act=act, all=allv.get())
            try:
                win.destroy()
            finally:
                ev.set()

        for label, act, style in (("Replace (old one → Recycle Bin)", "replace", "Accent.TButton"),
                                  ("Keep both", "keep", "TButton"), ("Skip", "skip", "TButton"),
                                  ("Cancel", "cancel", "TButton")):
            ttk.Button(row, text=label, style=style, command=lambda a=act: choose(a)).pack(side="left", padx=4)
        win.protocol("WM_DELETE_WINDOW", lambda: choose("cancel"))
        win.bind("<Escape>", lambda e: choose("cancel"))
    except Exception as e:  # noqa
        log_error(f"conflict dialog: {e}")
        result["act"] = "cancel"
        ev.set()


def open_item(A, _=None):
    s = A.sel()
    if not s:
        return
    r = s[0]
    if r[4]:
        A.navigate(r[1])
    elif X.is_archive_name(r[0]) and not X.zip_is_virtual(r[1]):
        A.navigate(r[1])  # browse the archive like a folder (right-click > Open with... for the default app)
    else:
        try:
            target = r[1]
            zs = X.zip_split(r[1])
            if zs and zs[1]:  # a file inside an archive: unpack it to a temp folder first
                import tempfile
                target = X.zip_extract(zs[0], zs[1], tempfile.mkdtemp(prefix="ff_zip_"))
            ff_platform.open_path(target)
            if not X.zip_is_virtual(r[1]):
                A.save_cfg(recent=([r[1]] + [p for p in A.cfg["recent"] if p != r[1]])[:300])
                A.commit_visit(os.path.dirname(r[1]))
        except OSError as e:
            messagebox.showerror("Foldwise", str(e))


def open_new_tab(A, _=None):
    s = [r for r in A.sel() if r[4]]
    for r in s:
        A.new_tab(r[1])


def open_with(A, _=None):
    s = A.sel()
    if s and not s[0][4]:
        shell_verb(s[0][1], "openas")


def show_props(A, _=None):
    s = A.sel()
    shell_verb(s[0][1] if s else A.st["cwd"], "properties")


def show_in_folder(A, _=None):
    s = A.sel()
    if s:
        A.navigate(os.path.dirname(s[0][1]), select=s[0][1])
        A.tree.focus_set()


def copy_path(A, _=None):
    s = A.sel()
    if s:
        A.root.clipboard_clear()
        A.root.clipboard_append("\n".join(r[1] for r in s))
        A.status.set("Path copied")


def do_copy(A, _=None, cut=False):
    s = A.sel()
    if s:
        A.st["clip"] = ([r[1] for r in s], cut)
        A.status.set(f"{len(s)} item(s) {'cut' if cut else 'copied'}")


def do_paste(A, _=None):
    paths, cut = A.st["clip"]
    if X.zip_is_virtual(A.st["cwd"]):
        A.status.set("Archives are read-only here \u2014 copy the files out first")
        return
    if paths:
        A.run_transfer(paths, A.st["cwd"], cut, clear_clip=cut)


def do_delete(A, _=None):
    s = A.sel()
    if not s:
        return
    if any(X.zip_is_virtual(r[1]) for r in s):
        A.status.set("Archives are read-only here \u2014 copy the files out first")
        return
    if A.cfg["confirm_delete"] and not messagebox.askyesno(
            "Delete", f"Move {len(s)} item(s) to the Recycle Bin?\n\n" + "\n".join(r[0] for r in s[:8])):
        return
    paths = [r[1] for r in s]
    if recycle(paths):
        A.push_undo("delete", paths)
    else:
        messagebox.showerror("Foldwise", ("Nothing was deleted." if recycle.last_rc[1] else
                                             f"Could not delete (Windows code {recycle.last_rc[0]}).") +
                             "\nDetails are in error.log")
    A.after_change()


def do_rename(A, _=None):
    s = A.sel()
    if not s:
        return
    old = s[0]
    if X.zip_is_virtual(old[1]):
        A.status.set("Archives are read-only here \u2014 copy the files out first")
        return
    new = simpledialog.askstring("Rename", "New name:", initialvalue=old[0], parent=A.root)
    if new and new != old[0]:
        dest = os.path.join(os.path.dirname(old[1]), new)
        try:
            os.rename(old[1], dest)
        except OSError as e:
            messagebox.showerror("Foldwise", str(e))
            return
        A.tags_store.move(old[1], dest)
        A.push_undo("rename", (old[1], dest))
        A.st["select"] = dest
        A.after_change()


def new_item(A, kind):
    if X.zip_is_virtual(A.st["cwd"]):
        A.status.set("Archives are read-only here \u2014 copy the files out first")
        return
    name = simpledialog.askstring("New " + ("folder" if kind == "dir" else "file"), "Name:", parent=A.root,
                                  initialvalue="New folder" if kind == "dir" else "New Text Document.txt")
    if not name:
        return
    dest = unique_dest(A.st["cwd"], name)
    try:
        os.mkdir(dest) if kind == "dir" else open(dest, "a").close()
    except OSError as e:
        messagebox.showerror("Foldwise", str(e))
        return
    A.push_undo("create", [dest])
    if A.q.get():
        A.q.set("")
    A.st["select"] = dest
    A.after_change()


def compress(A, _=None):
    s = A.sel()
    if not s:
        return
    import zipfile
    dest = unique_dest(A.st["cwd"], (s[0][0] if len(s) == 1 else os.path.basename(A.st["cwd"]) or "Archive") + ".zip")
    paths = [r[1] for r in s]
    A.status.set("Compressing...")

    def work():
        try:
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                for p in paths:
                    base = os.path.dirname(p)
                    if os.path.isdir(p):
                        for d, _, fs in os.walk(p):
                            for f in fs:
                                fp = os.path.join(d, f)
                                z.write(fp, os.path.relpath(fp, base))
                    else:
                        z.write(p, os.path.relpath(p, base))
            err = None
        except Exception as e:  # noqa
            err = e
        A.root.after(0, lambda: (messagebox.showerror("Foldwise", str(err)) if err else A.push_undo("create", [dest]),
                               A.after_change()))

    threading.Thread(target=work, daemon=True).start()


def extract(A, _=None):
    s = A.sel()
    if not s:
        return
    import zipfile
    src = s[0][1]
    dest = unique_dest(os.path.dirname(src), os.path.splitext(s[0][0])[0])
    A.status.set("Extracting...")

    def work():
        try:
            with zipfile.ZipFile(src) as z:
                z.extractall(dest)
            err = None
        except Exception as e:  # noqa
            err = e
        A.root.after(0, lambda: (messagebox.showerror("Foldwise", str(err)) if err else A.push_undo("create", [dest]),
                               A.after_change()))

    threading.Thread(target=work, daemon=True).start()


def open_terminal(A, _=None):
    try:
        subprocess.Popen(["wt", "-d", A.st["cwd"]])
    except OSError:
        subprocess.Popen(["powershell"], cwd=A.st["cwd"], creationflags=0x10)  # CREATE_NEW_CONSOLE


def open_explorer(A, _=None):
    subprocess.Popen(["explorer", os.path.normpath(A.st["cwd"])])


def rename_to(A, old, new):
    dest = os.path.join(os.path.dirname(old[1]), new)
    try:
        os.rename(old[1], dest)
    except OSError as e:
        messagebox.showerror("Foldwise", str(e))
        return
    A.tags_store.move(old[1], dest)
    A.push_undo("rename", (old[1], dest))
    A.st["select"] = dest
    A.after_change()


def inline_rename(A, _=None):
    """F2: edit the name right in the list (the dialog is used in grid view / archives)."""
    s_ = A.sel()
    if not s_:
        return "break"
    old = s_[0]
    if A.grid["on"] or X.zip_is_virtual(old[1]):
        A.do_rename()
        return "break"
    iid = A.tree.selection()[0]
    A.tree.see(iid)
    A.tree.update_idletasks()
    bb = A.tree.bbox(iid, "#0")
    if not bb:
        A.do_rename()
        return "break"
    x, y, w, h = bb
    ent = ttk.Entry(A.tree)
    ent.place(x=x + 26, y=y, width=max(w - 26, 240), height=h)
    ent.insert(0, old[0])
    ent.selection_range(0, len(old[0]) if old[4] else len(os.path.splitext(old[0])[0]))
    ent.focus_set()
    flag = {"done": False}

    def finish(commit):
        if flag["done"]:
            return
        flag["done"] = True
        new = ent.get().strip()
        ent.destroy()
        A.tree.focus_set()
        if commit and new and new != old[0]:
            A.rename_to(old, new)

    ent.bind("<Return>", lambda e: (finish(True), "break")[-1])
    ent.bind("<Escape>", lambda e: (finish(False), "break")[-1])
    ent.bind("<FocusOut>", lambda e: finish(True))
    return "break"


def edit_tags(A):
    s_ = A.sel()
    if not s_:
        return
    multi = len(s_) > 1
    cur_ = "" if multi else ", ".join(A.tags_store.get(s_[0][1])[1])
    txt = simpledialog.askstring("Tags", "Tags, separated by commas" + (" (added to every selected item)" if multi else "") + ":",
                                 initialvalue=cur_, parent=A.root)
    if txt is None:
        return
    new = [t for t in txt.replace(";", ",").split(",") if t.strip()]
    for r in s_:
        A.tags_store.set(r[1], tags=(A.tags_store.get(r[1])[1] + new) if multi else new)
    A.refresh_labels()


def set_label(A, color):
    for r in A.sel():
        A.tags_store.set(r[1], color=color or None)
    A.refresh_labels()


def pin(A, _=None):
    pins = list(A.cfg["pins"])
    for r in A.sel():
        if r[4] and r[1] not in pins:
            pins.append(r[1])
    A.save_cfg(pins=pins)
    A.build_sidebar()


def copy_as(A, kind):
    import urllib.parse
    s_ = A.sel()
    if not s_:
        return
    out = []
    for r in s_:
        p = r[1]
        out.append({"path": p, "name": r[0], "folder": os.path.dirname(p), "quoted": '"' + p + '"',
                    "unix": p.replace("\\", "/"), "url": "file:///" + urllib.parse.quote(p.replace("\\", "/"))}[kind])
    A.root.clipboard_clear()
    A.root.clipboard_append("\n".join(out))
    A.status.set(f"Copied {len(out)} item(s) to the clipboard")
