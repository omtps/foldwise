"""Tools > Tag manager: every tag and colour label with how many items carry it; rename, merge and delete them in one place.
Every function takes `A` first (ff_app.App). The store is ff_index.Tags (A.tags_store).
"""
import tkinter as tk
from tkinter import ttk

import ff_index as I
import ui_pages
from ff_core import T, ThemedAsk as simpledialog, ThemedBox as messagebox


def open_tags(A):
    win = A.toplevel("Tag manager", "820x620")
    tk.Label(win, text="Tag manager", bg=T["bg"], fg=T["fg"], font=("Segoe UI", A.cfg["font_size"] + 6, "bold")).pack(anchor="w", padx=22, pady=(18, 2))
    tk.Label(win, text="Rename a tag to the name of another one to merge them. Deleting a tag or label only removes it from your items, never the files.",
             bg=T["bg"], fg=T["muted"], font=("Segoe UI", A.cfg["font_size"]), wraplength=760, justify="left").pack(anchor="w", padx=22, pady=(0, 10))
    bt = ttk.Frame(win, padding=(14, 10))
    bt.pack(side="bottom", fill="x")
    body = ttk.Frame(win, padding=(18, 0))
    body.pack(fill="both", expand=True)
    tv = ttk.Treeview(body, columns=("n",), show="tree headings", selectmode="browse")
    tv.heading("#0", text="Tag or label")
    tv.heading("n", text="Items")
    tv.column("#0", width=420)
    tv.column("n", width=90, anchor="e")
    for c in I.LABEL_COLORS:
        tv.tag_configure("c:" + c, foreground=I.LABEL_HEX[c])
    tv.pack(fill="both", expand=True)

    def fill():
        sel = tv.selection()
        tv.delete(*tv.get_children())
        tags, colors = A.tags_store.summary()
        for c in I.LABEL_COLORS:
            if colors.get(c):
                tv.insert("", "end", iid="c:" + c, text="●  " + c.title() + " label", values=(colors[c],), tags=("c:" + c,))
        for t, n in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0])):
            tv.insert("", "end", iid="t:" + t, text="\U0001F3F7  " + t, values=(n,))
        if sel and tv.exists(sel[0]):
            tv.selection_set(sel[0])
        win._tag_rows = tv.get_children()

    def changed():
        fill()
        A.build_sidebar()

    def chosen():
        s = tv.selection()
        return (s[0][0], s[0][2:]) if s else (None, None)

    def show():
        kind, name = chosen()
        if kind:
            ui_pages.show_files(A)
            A.q.set(("tag:" if kind == "t" else "label:") + name)

    def rename():
        kind, name = chosen()
        if kind != "t":
            return
        new = simpledialog.askstring("Rename tag", f"New name for “{name}” (an existing name merges the two):", initialvalue=name, parent=A.root)
        if new and new.strip():
            A.tags_store.rename_tag(name, new)
            changed()

    def delete():
        kind, name = chosen()
        if not kind:
            return
        what = f"the tag “{name}”" if kind == "t" else f"the {name} label"
        if messagebox.askyesno("Remove", f"Remove {what} from all items? The files themselves are not touched.", parent=A.root):
            (A.tags_store.delete_tag if kind == "t" else A.tags_store.clear_color)(name)
            changed()
    ttk.Button(bt, text="Show items", style="Accent.TButton", command=show).pack(side="left")
    ttk.Button(bt, text="Rename / merge…", command=rename).pack(side="left", padx=8)
    ttk.Button(bt, text="Remove from all items", command=delete).pack(side="left")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    tv.bind("<Double-Button-1>", lambda e: show())
    tv.bind("<Return>", lambda e: show())
    win._tag_actions = (show, rename, delete, tv)  # (the tests drive the page through these)
    fill()
