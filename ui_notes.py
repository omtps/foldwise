"""Folder notes in the interface: a slim banner under the toolbar when the folder you are in has a note, a note editor, and the note in the details pane.

Every function takes `A` first (ff_app.App). The store itself is ff_notes.Notes (A.notes).
"""
import os
import tkinter as tk
from tkinter import ttk

from ff_core import T, ThemedBox as messagebox

SHOW = 240  # characters of the note shown in the banner


def setup(A):
    """Create the (hidden) banner once; update() shows or hides it."""
    bar = tk.Frame(A.root, bg=T["raised"])
    A.st["notebar"] = bar
    lab = tk.Label(bar, bg=T["raised"], fg=T["fg"], anchor="w", justify="left", padx=12, pady=6, cursor="hand2")
    lab.pack(side="left", fill="x", expand=True)
    hide = tk.Label(bar, text="✕", bg=T["raised"], fg=T["muted"], padx=10, cursor="hand2")
    hide.pack(side="right")
    A.st["notelab"] = lab
    lab.bind("<Button-1>", lambda e: edit(A, A.st["cwd"]))
    hide.bind("<Button-1>", lambda e: (bar.pack_forget(), A.st.__setitem__("notehid", A.st["cwd"])))
    bar.bind("<Configure>", lambda e: lab.configure(wraplength=max(200, e.width - 70)))


def update(A):
    """Show the note of the current folder (browse mode only) in the banner, or hide the banner."""
    bar = A.st.get("notebar")
    if bar is None:
        return
    cwd = A.st["cwd"]
    text = A.notes.get(cwd) if A.st["mode"] == "browse" else ""
    if not text or A.st.get("notehid") == cwd:
        bar.pack_forget()
        return
    A.st["notelab"].configure(text="\U0001F4DD  " + (text if len(text) <= SHOW else text[:SHOW].rstrip() + "…") + "     (click to edit)", bg=T["raised"], fg=T["fg"])
    bar.configure(bg=T["raised"])
    if not bar.winfo_manager():
        bar.pack(fill="x", padx=12, pady=(0, 8), before=A.mid.master)


def edit(A, path):
    """Dialog to read, change or remove the note of a folder or file."""
    d = tk.Toplevel(A.root)
    d.title("Note: " + (os.path.basename(path.rstrip(chr(92))) or path))
    d.configure(bg=T["bg"])
    d.transient(A.root)
    f = ttk.Frame(d, padding=18)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text=path, style="DetKey.TLabel", background=T["bg"], wraplength=520).pack(anchor="w")
    txt = tk.Text(f, width=62, height=9, bg=T["panel"], fg=T["fg"], insertbackground=T["fg"], relief="flat", wrap="word", padx=10, pady=8,
                  font=("Segoe UI", A.cfg["font_size"]))
    txt.pack(fill="both", expand=True, pady=10)
    txt.insert("1.0", A.notes.get(path))
    count = tk.StringVar()
    ttk.Label(f, textvariable=count, style="DetKey.TLabel", background=T["bg"]).pack(anchor="w")

    def counted(_e=None):
        count.set(f"{len(txt.get('1.0', 'end').strip())} characters")
    txt.bind("<KeyRelease>", counted)
    counted()
    bt = ttk.Frame(f)
    bt.pack(fill="x", pady=(10, 0))

    def save():
        A.notes.set(path, txt.get("1.0", "end"))
        A.st["notehid"] = None
        d.destroy()
        changed(A)

    def delete():
        if A.notes.get(path) and not messagebox.askyesno("Delete note", "Delete this note?", parent=d):
            return
        A.notes.set(path, "")
        d.destroy()
        changed(A)
    ttk.Button(bt, text="Save", style="Accent.TButton", command=save).pack(side="left")
    ttk.Button(bt, text="Delete note", command=delete).pack(side="left", padx=8)
    ttk.Button(bt, text="Cancel", command=d.destroy).pack(side="right")
    d.bind("<Escape>", lambda e: d.destroy())
    d.update_idletasks()
    d.geometry(f"+{A.root.winfo_rootx() + 100}+{A.root.winfo_rooty() + 80}")
    txt.focus_set()
    d._note_text = txt  # (the tests drive the editor through these)
    d._note_buttons = (save, delete)
    A.st["noteeditor"] = d


def changed(A):
    update(A)
    A.update_details()


def detail_rows(A, path):
    """[('Note', text)] for the details pane when the selected item has a note."""
    text = A.notes.get(path)
    return [("Note", text if len(text) <= 300 else text[:300].rstrip() + "…")] if text else []


def edit_selected(A, _=None):
    s = A.sel()
    if len(s) == 1:
        edit(A, s[0][1])


def edit_current(A, _=None):
    edit(A, A.st["cwd"])
