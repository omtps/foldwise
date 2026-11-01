"""Toolbar: drop-down menus, responsive overflow layout, chips, tooltips, context menu, theme/zoom changes.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import ff_extras as X
import ff_index as I
import ff_shell as Sh
import os
import time
import ui_pages
import tkinter as tk
from tkinter import ttk
from ff_core import (IMG_EXTS, PALETTES, T, apply_theme, dark_titlebar, log_error, set_theme)


def popup_below(A, widget, menu):
    """Drop a menu under a toolbar button. Clicking the same button again while it is open closes the menu
        (the click that closes it must not immediately re-open it)."""
    if time.time() - A.pop_closed.get(widget, 0) < 0.45:
        A.pop_closed.pop(widget, None)
        return
    try:
        menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())
    finally:
        menu.grab_release()
        A.pop_closed[widget] = time.time()


def set_flag(A, key, var):
    A.save_cfg(**{key: var.get()})
    if key == "folder_sizes" and not var.get():
        A.st["fs_tok"] += 1
    A.refresh()


def new_menu(A):
    m = A.make_menu()
    m.add_command(label="\U0001F4C1  Folder", command=lambda: A.new_item("dir"))
    m.add_command(label="\U0001F4C4  Text document", command=lambda: A.new_item("file"))
    return m


def sort_menu(A):
    m = A.make_menu()
    for label, k in (("Name", "name"), ("Date modified", "date"), ("Type", "type"), ("Size", "size")):
        m.add_radiobutton(label=label, variable=A.sort_var, value=k, command=lambda k=k: A.set_sort(k, A.st["sort_rev"]))
    m.add_separator()
    m.add_radiobutton(label="Ascending", variable=A.rev_var, value=False,
                      command=lambda: A.set_sort(A.st["sort_key"] or "name", False))
    m.add_radiobutton(label="Descending", variable=A.rev_var, value=True,
                      command=lambda: A.set_sort(A.st["sort_key"] or "name", True))
    m.add_separator()
    m.add_checkbutton(label="Folders first", variable=A.ff_var, command=lambda: A.set_flag("folders_first", A.ff_var))
    return m


def view_menu(A):
    m = A.make_menu()
    m.add_checkbutton(label="Details pane  (F3)", variable=A.details_var, command=lambda: A.toggle_details(
        value=A.details_var.get()))
    m.add_checkbutton(label="Thumbnail grid  (Ctrl+Shift+G)", variable=A.grid_var,
                      command=lambda: A.toggle_grid(value=A.grid_var.get()))
    m.add_checkbutton(label="Folder sizes", variable=A.fsz_var, command=lambda: A.set_flag("folder_sizes", A.fsz_var))
    m.add_checkbutton(label="Hidden files", variable=A.hidden_var, command=lambda: A.set_flag("show_hidden", A.hidden_var))
    m.add_separator()
    for label, h in (("Compact rows", 24), ("Normal rows", 30), ("Comfortable rows", 38)):
        m.add_radiobutton(label=label, variable=A.dens_var, value=h, command=lambda h=h: A.change_setting(row_height=h))
    m.add_separator()
    m.add_command(label="Zoom in  (Ctrl +)", command=lambda: A.zoom(1))
    m.add_command(label="Zoom out  (Ctrl −)", command=lambda: A.zoom(-1))
    m.add_separator()
    m.add_separator()
    m.add_command(label="↶  Undo  (Ctrl+Z)", command=A.do_undo)
    m.add_command(label="Select by pattern…  (Ctrl+Shift+S)", command=A.select_pattern)
    m.add_command(label="Invert selection  (Ctrl+I)", command=A.invert_selection)
    wm = A.make_menu()
    wm.add_command(label="Save current tabs as workspace…", command=A.save_workspace)
    if A.cfg["workspaces"]:
        wm.add_separator()
        for nm_ in sorted(A.cfg["workspaces"]):
            wm.add_command(label="Open: " + nm_, command=lambda n=nm_: A.load_workspace(n))
        wm.add_separator()
        for nm_ in sorted(A.cfg["workspaces"]):
            wm.add_command(label="Forget: " + nm_, command=lambda n=nm_: A.delete_workspace(n))
    m.add_cascade(label="Workspaces", menu=wm)
    m.add_command(label="Reopen closed tab  (Ctrl+Shift+T)", command=A.reopen_tab)
    m.add_command(label="Command palette  (Ctrl+K)", command=A.open_palette)
    m.add_command(label="Open terminal here", command=A.open_terminal)
    m.add_command(label="Open this folder in Explorer", command=A.open_explorer)
    return m


def sync_pins(A):
    """Toolbar buttons for the tools you pinned (right-click a tool in the Tools list > Pin to toolbar)."""
    for it in [i for i in A.cmd_items if i.get("pin")]:
        it["w"].destroy()
        A.cmd_items.remove(it)
    pos = next(k for k, i in enumerate(A.cmd_items) if i["w"] is A.health_btn) + 1
    every = {t[0]: t for _g, items in ui_pages.TOOLS for t in items}
    for n, name in enumerate(A.cfg.get("pinned_tools", [])):
        t = every.get(name)
        if not t:
            continue
        cmd = lambda t=t: ui_pages._open(A, t[0], t[1], t[2] if len(t) > 2 else ())  # noqa: E731
        b = ttk.Button(A.cmdbar, text=name, style="Cmd.TButton", width=0, command=cmd)
        A.cmd_items.insert(pos + n, dict(w=b, kind="btn", label=name, cmd=cmd, menu=None, pin=True))
    A.lay["sig"] = None
    A.root.after(10, lambda: A.layout_cmdbar(force=True))


def tip(A, widget, text):
    """Small hover tooltip (appears after 0.6 s, never takes focus)."""
    st_ = {"job": None, "win": None}

    def show():
        if st_["win"] or not widget.winfo_exists():
            return
        w = tk.Toplevel(widget)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        tk.Label(w, text=text, bg=T["raised"], fg=T["fg"], padx=8, pady=4, relief="solid", bd=1, font=("Segoe UI", A.cfg["font_size"] - 1)).pack()
        w.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 4}")
        st_["win"] = w

    def hide(_=None):
        if st_["job"]:
            widget.after_cancel(st_["job"])
            st_["job"] = None
        if st_["win"]:
            st_["win"].destroy()
            st_["win"] = None
    widget.bind("<Enter>", lambda e: st_.update(job=widget.after(600, show)), add="+")
    widget.bind("<Leave>", hide, add="+")
    widget.bind("<ButtonPress-1>", hide, add="+")


def overflow_menu(A):
    m = A.make_menu()
    last_sep = True
    for it in A.cmd_items:
        if it["w"] in A.lay["shown"]:
            continue
        if it["kind"] == "sep":
            if not last_sep:
                m.add_separator()
                last_sep = True
            continue
        label = it["label"].replace(" ▾", "")
        if it.get("menu"):
            m.add_cascade(label=label, menu=it["menu"]())
        else:
            m.add_command(label=label, command=it["cmd"])
        last_sep = False
    return m


def layout_cmdbar(A, e=None, force=False):
    """Pack as many toolbar buttons as fit the window width; the rest live under the » button."""
    W = A.cmdbar.winfo_width()
    if W < 80:
        return
    right = A.details_btn.winfo_reqwidth() + A.set_b.winfo_reqwidth() + 16
    need = [(it, it["w"].winfo_reqwidth() + (14 if it["kind"] == "sep" else 4)) for it in A.cmd_items]
    sig = (W, tuple((id(i["w"]), w_) for i, w_ in need))
    if sig == A.lay["sig"] and not force:
        return
    A.lay["sig"] = sig
    for it in A.cmd_items:
        it["w"].pack_forget()
    A.over_b.pack_forget()
    avail = W - right
    over = sum(w_ for _, w_ in need) > avail
    if over:
        avail -= A.over_b.winfo_reqwidth() + 8
    used, shown = 0, []
    for it, w_ in need:
        if used + w_ > avail:
            break
        shown.append(it)
        used += w_
    while shown and shown[-1]["kind"] == "sep":
        shown.pop()
    A.lay["shown"] = {i["w"] for i in shown}
    for it in shown:
        if it["kind"] == "sep":
            it["w"].pack(side="left", fill="y", padx=6, pady=4)
        else:
            it["w"].pack(side="left", padx=1)
    if over:
        A.over_b.pack(side="right", padx=1)


def autofit(A, e):
    """Narrow window: tuck the details pane away (not saved) so the file list keeps its room; bring it back when wide again."""
    if e.widget is not A.root:
        return
    narrow = e.width < 1000
    if narrow == A.fit["narrow"]:
        return
    A.fit["narrow"] = narrow
    if A.cfg["details_open"]:
        if narrow:
            A.det.pack_forget()
        else:
            A.det.pack(side="right", fill="y", before=A.mid)
            A.update_details()


def flow_chips(A, e=None):
    """Wrap the filter chips onto extra rows when the window is narrow."""
    W = A.chipbar.winfo_width()
    if W < 80:
        return
    x, row, col, pos = 0, 0, 0, []
    for b in A.chipbtns.values():
        w_ = b.winfo_reqwidth() + 6
        if x + w_ > W and col:
            row, col, x = row + 1, 0, 0
        pos.append((b, row, col))
        x += w_
        col += 1
    sig = tuple((id(b), r_, c_) for b, r_, c_ in pos)
    if sig == A.chip_lay["sig"]:
        return
    A.chip_lay["sig"] = sig
    for b, r_, c_ in pos:
        b.grid(row=r_, column=c_, padx=(0, 6), pady=1, sticky="w")


def native_ctx(A, x, y, extended=False):
    if not Sh:
        return
    paths = [r[1] for r in A.sel() if not X.zip_is_virtual(r[1])] or [A.st["cwd"]]
    try:
        if Sh.native_menu(Sh.hwnd_of(A.root), paths, x, y, extended):
            A.root.after(500, A.after_change)
    except Exception as e:  # noqa
        log_error(f"native menu: {e}")
        A.status.set("Couldn't open the Windows menu (see error.log)")


def popup(A, e):
    A.activate(A.pane_of(e.widget))
    row = A.tree.identify_row(e.y)
    if row and row not in A.tree.selection():
        A.tree.selection_set(row)
    s = A.sel()
    if e.state & 0x1 and Sh:  # Shift+right-click = the full Windows menu straight away
        A.native_ctx(e.x_root, e.y_root, True)
        return
    m = A.make_menu()
    if s:
        m.add_command(label="Open", command=A.open_item)
        if any(r[4] for r in s):
            m.add_command(label="Open in new tab", command=A.open_new_tab)
        if not s[0][4]:
            m.add_command(label="Open with…", command=A.open_with)
        if A.st["mode"] == "search":
            m.add_command(label="Show in folder", command=A.show_in_folder)
        m.add_separator()
        m.add_command(label="Cut", command=lambda: A.do_copy(cut=True))
        m.add_command(label="Copy", command=A.do_copy)
        m.add_cascade(label="Copy to", menu=A.dest_menu(False))
        m.add_cascade(label="Move to", menu=A.dest_menu(True))
    m.add_command(label="Paste here", command=A.do_paste)
    if A.pane["split"] and s:
        m.add_command(label="Copy to other pane", command=lambda: A.to_other(False))
        m.add_command(label="Move to other pane", command=lambda: A.to_other(True))
    if s:
        m.add_separator()
        m.add_command(label="Rename", command=A.do_rename)
        if len(s) > 1:
            m.add_command(label="Bulk rename…", command=A.open_bulk_rename)
        m.add_command(label="Delete", command=A.do_delete)
        m.add_separator()
        m.add_command(label="Compress to ZIP", command=A.compress)
        if len(s) == 1 and not s[0][4]:
            m.add_command(label="Checksum\u2026", command=A.open_checksum)
        if any(not r[4] and os.path.splitext(r[0])[1][1:].lower() in IMG_EXTS for r in s):
            m.add_command(label="Convert / resize images\u2026", command=A.open_convert_images)
        if len(s) == 1 and X.is_archive_name(s[0][0]):
            m.add_command(label="Extract here", command=A.extract)
        if any(r[4] for r in s):
            m.add_command(label="Folder size", command=A.folder_sizes_now)
        if len(s) == 2 and not s[0][4] and not s[1][4]:
            m.add_command(label="Compare these two files…", command=A.open_diff)
        m.add_command(label="Copy full path", command=A.copy_path)
        cp = A.make_menu()
        for label_, k_ in (("Full path", "path"), ("File name", "name"), ("Folder path", "folder"),
                           ("Path in quotes", "quoted"), ("Unix-style path (C:/\u2026)", "unix"), ("file:/// link", "url")):
            cp.add_command(label=label_, command=lambda k_=k_: A.copy_as(k_))
        m.add_cascade(label="Copy as", menu=cp)
        if any(r[4] for r in s):
            m.add_command(label="Pin to sidebar", command=A.pin)
        lm = A.make_menu()
        for c_ in I.LABEL_COLORS:
            lm.add_command(label=f"{I.LABEL_EMOJI[c_]}  {c_.title()}", command=lambda c_=c_: A.set_label(c_))
        lm.add_separator()
        lm.add_command(label="No label", command=lambda: A.set_label(""))
        m.add_cascade(label="Colour label", menu=lm)
        m.add_command(label="Tags\u2026", command=A.edit_tags)
    m.add_separator()
    m.add_cascade(label="New", menu=A.new_menu())
    if not s:
        m.add_command(label="Export this list to CSV…", command=A.export_csv)
    m.add_command(label="Open terminal here", command=A.open_terminal)
    m.add_command(label="Open this folder in Explorer", command=A.open_explorer)
    if s and not any(X.zip_is_virtual(r[1]) for r in s):
        m.add_command(label="Scan with Windows Defender", command=lambda: A.scan_with_defender([r[1] for r in s]))
    m.add_command(label="Properties", command=A.show_props)
    if Sh:
        m.add_separator()
        m.add_command(label="More options (Windows menu)\u2026", command=lambda: A.native_ctx(e.x_root, e.y_root))
    m.tk_popup(e.x_root, e.y_root)


def restyle(A):
    set_theme(A.cfg["theme"], A.cfg["accent"])
    apply_theme(A.root, A.cfg)
    for w, opts in A.themed:
        try:
            w.configure(**{k: T[v] for k, v in opts.items()})
        except tk.TclError:
            pass
    for _, _t in A.pane_frames:
        _t.tag_configure("alt", background=T["alt"] if A.cfg.get("zebra", True) else T["bg"])
        _t.tag_configure("dir", foreground=T["dir"])
        _t.tag_configure("drop", background=T["sel"])
    A.mark_active()
    A.side.configure(font=("Segoe UI", A.cfg["font_size"] + 1))
    A.build_sidebar()
    dark_titlebar(A.root, T["dark"])
    A.update_headings()
    A.build_crumbs()
    A.build_tabs()
    A.details_btn.configure(style="On.TButton" if A.cfg["details_open"] else "Cmd.TButton")
    A.sync_chips()
    A.update_details()
    A.render_grid()
    ui_pages.refresh_theme(A)


def change_setting(A, **kw):
    A.save_cfg(**kw)
    A.dens_var.set(A.cfg["row_height"])
    A.restyle()


def zoom(A, d):
    A.change_setting(font_size=max(8, min(18, A.cfg["font_size"] + d)))


def palette_actions(A):
    acts = [("New tab", A.new_tab), ("Close tab", A.close_tab), ("Reopen closed tab", A.reopen_tab),
            ("Rebuild content index", lambda: A.start_content_index(True)),
            ("Clear recent folders and files", lambda: A.clear_recent("all")), ("Split view on/off", A.toggle_split),
            ("Details pane on/off", A.toggle_details), ("Thumbnail grid on/off", A.toggle_grid),
            ("Compare the two panes", A.open_compare), ("Smart disk cleaner", A.open_cleaner), ("PC health check", A.open_health),
            ("Set up or run a backup", lambda: A.open_health("backups")), ("Find duplicate files in this folder", A.open_duplicates),
            ("Find duplicate files in all my folders", lambda: A.open_duplicates("mine")), ("Find largest files", A.open_largest), ("Sync two folders", A.open_sync), ("Photo details / remove location", A.open_photo_info), ("Integrity check (detect corrupted files)", A.open_integrity),
            ("Checksum of selected file", A.open_checksum), ("Convert or resize selected images", A.open_convert_images),
            ("Clear search history", lambda: (A.save_cfg(search_history=[]), A.status.set("Search history cleared"))),
            ("Organize this folder by type or date", A.open_organize),
            ("Disk usage map of this folder", A.open_treemap), ("Bulk rename selected", A.open_bulk_rename),
            ("Undo", A.do_undo), ("Re-index everything", A.start_index), ("New folder", lambda: A.new_item("dir")),
            ("New text document", lambda: A.new_item("file")), ("Open terminal here", A.open_terminal),
            ("Open this folder in Explorer", A.open_explorer), ("Customize…", A.open_settings),
            ("Refresh", A.hard_refresh), ("Go up one folder", A.go_up), ("Go back", A.go_back),
            ("Select by pattern", A.select_pattern), ("Invert selection", A.invert_selection),
            ("Show hidden files on/off", lambda: (A.hidden_var.set(not A.cfg["show_hidden"]),
                                                  A.set_flag("show_hidden", A.hidden_var)))]
    acts += [(label, lambda a=attr, ar=args: getattr(A, a)(*ar)) for _g, items in ui_pages.TOOLS for label, attr, *rest in items
             for args in [rest[0] if rest else ()]]
    acts += [(f"Theme: {n}", lambda n=n: A.change_setting(theme=n, accent="")) for n in (*PALETTES, "Follow Windows")]
    return acts
