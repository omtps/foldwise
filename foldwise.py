"""Foldwise - index every file on your PC and search it instantly.

Run:  python foldwise.py            (GUI + file manager; Ctrl+Alt+Space summons it)
      python foldwise.py --install  (Start menu shortcut)
      python foldwise.py --autostart / --remove-autostart  (run hidden at login)
      python foldwise.py --index    (just (re)build the index, no GUI)
      python foldwise.py --search "report ext:pdf"   (CLI search)

Search syntax (all terms are ANDed, case-insensitive, matched against the full path):
    invoice 2023          both words must appear in the path
    "annual report"       exact phrase
    -draft                exclude paths containing "draft"
    ext:pdf,docx          only these extensions
    type:dir | type:file  only folders / only files
    size:>10mb  size:<1kb files bigger / smaller than
    modified:<days>       e.g. modified:7  -> changed in the last 7 days
    name:foo              match only the file name, not the folder path
    re:^IMG_\\d+          regular expression on the file name
"""

import os
import sqlite3
import subprocess
import sys
import threading
import types
import time
from pathlib import Path

import ff_core
import ff_notify
import ff_index as I
import ui_about
import ui_cleaner
import ui_browse
import ui_more
import ui_games
import ui_dragselect
import ui_extras
import ui_fileops
import ui_grid
import ui_health
import ui_malware
import ui_nav
import ui_pages
import ui_preview
import ui_settings
import ui_tools
import ui_toolbar
from ff_app import App
from ff_core import (DATE_FORMATS, DATE_STYLE, low_priority, 
    CHIPS, DB_DIR, DB_PATH, DEFAULT_CFG, MAX_RESULTS, SKIP_DIRS, Sh, T, ThemedAsk, ThemedBox, X, apply_theme,
    build_index, connect, dark_titlebar, dir_stats, ensure_icon, fixed_drives, fmt_date, fuzzy_ok, glyph, human_size,
    list_dir, listen_for_show, load_config, log_error, make_shortcut, parse_hotkey, recent_noise, register_hotkey,
    save_config, search, search_fuzzy, set_default_folder_opener, set_theme, shortcut_paths, signal_running_instance,
    start_tray, type_name,
)


def run_gui(background=True, hidden=False, open_path=None):
    import tkinter as tk
    from concurrent.futures import ThreadPoolExecutor
    from tkinter import ttk

    if background and signal_running_instance(open_path):
        return
    if os.name == "nt":  # own taskbar identity, so it shows our icon instead of python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Foldwise.App")

    A = App()
    bind = A.binder
    A._bind(dict(ACTION_LABEL=lambda: ACTION_LABEL, _thumb_file=lambda: _thumb_file, ac_state=lambda: ac_state, activate=lambda: activate, after_change=lambda: after_change, app_restart=lambda: app_restart, autoclean_now=lambda: autoclean_now, autoclean_tick=lambda: autoclean_tick, bk_hooks=lambda: bk_hooks, bk_running=lambda: bk_running, bk_tick=lambda: bk_tick, build_crumbs=lambda: build_crumbs, build_sidebar=lambda: build_sidebar, build_tabs=lambda: build_tabs, cfg=lambda: cfg, change_setting=lambda: change_setting, check=lambda: check, chip_lay=lambda: chip_lay, chipbar=lambda: chipbar, chipbtns=lambda: chipbtns, choose_dest=lambda: choose_dest, clear_hl=lambda: clear_hl, clear_preview=lambda: clear_preview, clear_recent=lambda: clear_recent, close_preview=lambda: close_preview, close_tab=lambda: close_tab, cmd_items=lambda: cmd_items, cmdbar=lambda: cmdbar, commit_visit=lambda: commit_visit, compress=lambda: compress, conflict_dialog=lambda: conflict_dialog, copy_as=lambda: copy_as, copy_path=lambda: copy_path, crumb_menu=lambda: crumb_menu, crumbs=lambda: crumbs, cur=lambda: cur, delete_workspace=lambda: delete_workspace, dens_var=lambda: dens_var, dest_menu=lambda: dest_menu, det=lambda: det, det_btns=lambda: det_btns, det_rows=lambda: det_rows, details_btn=lambda: details_btn, details_var=lambda: details_var, do_copy=lambda: do_copy, do_delete=lambda: do_delete, do_paste=lambda: do_paste, do_rename=lambda: do_rename, do_undo=lambda: do_undo, drag=lambda: drag, drop_target=lambda: drop_target, edit_path=lambda: edit_path, edit_tags=lambda: edit_tags, entry=lambda: entry, export_csv=lambda: export_csv, extract=lambda: extract, ff_var=lambda: ff_var, fit=lambda: fit, folder_sizes_now=lambda: folder_sizes_now, forget_file=lambda: forget_file, forget_folder=lambda: forget_folder, fsize=lambda: fsize, fsz_var=lambda: fsz_var, gcv=lambda: gcv, gmq=lambda: gmq, go_back=lambda: go_back, go_up=lambda: go_up, gpool=lambda: gpool, grid=lambda: grid, grid_icon=lambda: grid_icon, grid_index_at=lambda: grid_index_at, grid_load_thumb=lambda: grid_load_thumb, grid_schedule=lambda: grid_schedule, grid_see=lambda: grid_see, grid_select=lambda: grid_select, grid_thumb_ready=lambda: grid_thumb_ready, grid_tiles_in=lambda: grid_tiles_in, grid_var=lambda: grid_var, gridf=lambda: gridf, gsb=lambda: gsb, hard_refresh=lambda: hard_refresh, health_btn=lambda: health_btn, health_watch=lambda: health_watch, hidden_var=lambda: hidden_var, hist_path=lambda: hist_path, home=lambda: home, icon_box=lambda: icon_box, info=lambda: info, info_labels=lambda: info_labels, invert_selection=lambda: invert_selection, lay=lambda: lay, layout_cmdbar=lambda: layout_cmdbar, load_tab=lambda: load_tab, load_workspace=lambda: load_workspace, local_folders=lambda: local_folders, make_menu=lambda: make_menu, make_problem_report=lambda: make_problem_report, mark_active=lambda: mark_active, mid=lambda: mid, mq=lambda: mq, mq_clear=lambda: mq_clear, mq_end=lambda: mq_end, mq_in_zone=lambda: mq_in_zone, mq_motion=lambda: mq_motion, mq_rect=lambda: mq_rect, mq_row0=lambda: mq_row0, mq_start=lambda: mq_start, mq_tick=lambda: mq_tick, mq_update=lambda: mq_update, name_l=lambda: name_l, native_ctx=lambda: native_ctx, navigate=lambda: navigate, new_item=lambda: new_item, new_menu=lambda: new_menu, new_tab=lambda: new_tab, notify=lambda: notify, ole_out=lambda: ole_out, open_about=lambda: open_about, open_action=lambda: open_action, open_autoclean=lambda: open_autoclean, open_bulk_rename=lambda: open_bulk_rename, open_checksum=lambda: open_checksum, open_cleaner=lambda: open_cleaner, open_collections=lambda: open_collections, open_compare=lambda: open_compare, open_convert_images=lambda: open_convert_images, open_diff=lambda: open_diff, open_duplicates=lambda: open_duplicates, open_explorer=lambda: open_explorer, open_folder_history=lambda: open_folder_history, open_ftp=lambda: open_ftp, open_games=lambda: open_games, open_health=lambda: open_health, open_howto=lambda: open_howto, open_integrity=lambda: open_integrity, open_item=lambda: open_item, open_largest=lambda: open_largest, open_malware=lambda: open_malware, open_new_tab=lambda: open_new_tab, open_notify=lambda: open_notify, open_ocr=lambda: open_ocr, open_organize=lambda: open_organize, open_palette=lambda: open_palette, open_photo_info=lambda: open_photo_info, open_preview=lambda: open_preview, open_recent_changes=lambda: open_recent_changes, open_recycle_bin=lambda: open_recycle_bin, open_settings=lambda: open_settings, open_shortcuts=lambda: open_shortcuts, open_similar_photos=lambda: open_similar_photos, open_storage=lambda: open_storage, open_storage_types=lambda: open_storage_types, open_sync=lambda: open_sync, open_system_info=lambda: open_system_info, open_terminal=lambda: open_terminal, open_treemap=lambda: open_treemap, open_tutorial=lambda: open_tutorial, open_undo_history=lambda: open_undo_history, open_vault=lambda: open_vault, open_whats_new=lambda: open_whats_new, open_with=lambda: open_with, over_b=lambda: over_b, palette_actions=lambda: palette_actions, pane=lambda: pane, pane_frames=lambda: pane_frames, pane_of=lambda: pane_of, panes=lambda: panes, path_e=lambda: path_e, pathv=lambda: pathv, perf_tick=lambda: perf_tick, pin=lambda: pin, pop_closed=lambda: pop_closed, popup=lambda: popup, popup_below=lambda: popup_below, prev_lbl=lambda: prev_lbl, prev_txt=lambda: prev_txt, push_undo=lambda: push_undo, pv_show=lambda: pv_show, q=lambda: q, qp=lambda: qp, qroot=lambda: qroot, refresh=lambda: refresh, refresh_labels=lambda: refresh_labels, rename_saved=lambda: rename_saved, rename_to=lambda: rename_to, render_grid=lambda: render_grid, render_preview=lambda: render_preview, reopen_tab=lambda: reopen_tab, restyle=lambda: restyle, rev_var=lambda: rev_var, root=lambda: root, run_transfer=lambda: run_transfer, save_cfg=lambda: save_cfg, save_tab=lambda: save_tab, save_workspace=lambda: save_workspace, scan_with_defender=lambda: scan_with_defender, sel=lambda: sel, sel_status=lambda: sel_status, select_pattern=lambda: select_pattern, set_b=lambda: set_b, set_dir_info=lambda: set_dir_info, set_flag=lambda: set_flag, set_hl=lambda: set_hl, set_job_fields=lambda: set_job_fields, set_label=lambda: set_label, set_pil=lambda: set_pil, set_score=lambda: set_score, set_sort=lambda: set_sort, setup_icons=lambda: setup_icons, show=lambda: show, show_glyph=lambda: show_glyph, show_image=lambda: show_image, show_in_folder=lambda: show_in_folder, show_props=lambda: show_props, show_text=lambda: show_text, show_toast=lambda: show_toast, side=lambda: side, side_items=lambda: side_items, side_sections=lambda: side_sections, sort_rows=lambda: sort_rows, sort_var=lambda: sort_var, split_b=lambda: split_b, split_btns=lambda: split_btns, st=lambda: st, start_content_index=lambda: start_content_index, start_index=lambda: start_index, status=lambda: status, step_preview=lambda: step_preview, subfolders=lambda: subfolders, switch_tab=lambda: switch_tab, sync_chips=lambda: sync_chips, tabbar=lambda: tabbar, tabs=lambda: tabs, tags_store=lambda: tags_store, themed=lambda: themed, threat_check=lambda: threat_check, thumb_cache_get=lambda: thumb_cache_get, thumb_cache_put=lambda: thumb_cache_put, thumb_dir=lambda: thumb_dir, to_other=lambda: to_other, toggle_details=lambda: toggle_details, toggle_grid=lambda: toggle_grid, toggle_split=lambda: toggle_split, toplevel=lambda: toplevel, track_tick=lambda: track_tick, tree=lambda: tree, type_select=lambda: type_select, update_details=lambda: update_details, update_headings=lambda: update_headings, weekly_check=lambda: weekly_check, welcome=lambda: welcome, zoom=lambda: zoom))  # live getters: ui_* modules read these (cells may be filled in later)

    cfg = {**DEFAULT_CFG, **load_config()}
    I.OCR_PDFS = cfg["ocr_pdfs"]
    set_theme(cfg["theme"], cfg["accent"])
    import traceback
    threading.excepthook = lambda a: log_error("thread: " + "".join(
        traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))

    def save_cfg(**kw):
        cfg.update(kw)
        save_config(**kw)

    _crash_file = __import__("ff_core").enable_crash_log()  # keep a reference: closing the file would disable it
    if os.environ.get("FF_SAMPLER"):
        ff_core_sampler = __import__("ff_core").start_sampler
        ff_core_sampler(float(os.environ["FF_SAMPLER"]) if os.environ["FF_SAMPLER"].replace(".", "").isdigit() and float(os.environ["FF_SAMPLER"]) < 1 else 1.0)
    root = tk.Tk()
    root.title("Foldwise")
    root.geometry(f"{min(1280, root.winfo_screenwidth() - 100)}x{min(760, root.winfo_screenheight() - 140)}+40+40")
    try:
        root.iconbitmap(default=str(ensure_icon()))
    except tk.TclError:
        pass
    def report_error(exc, val, tb):
        log_error("".join(traceback.format_exception(exc, val, tb)))
        try:
            status.set(f"Something went wrong: {val}  (details in error.log)")
        except Exception:
            pass

    root.report_callback_exception = report_error
    apply_theme(root, cfg)
    root.update_idletasks()
    dark_titlebar(root, T["dark"])
    ThemedBox.root = root
    messagebox, simpledialog = ThemedBox, ThemedAsk  # app-styled dialogs everywhere
    tags_store = I.Tags(DB_DIR / "tags.db")
    ff_core.TAGS = tags_store
    cindex = I.ContentIndex(DB_DIR / "content.db")
    con = connect()
    home = str(Path.home())
    start = cfg["last_folder"] if cfg["start"] == "last" and os.path.isdir(cfg["last_folder"]) else home
    st = {"stop": False, "indexing": False, "rows": [], "after": None, "gen": 0, "sgen": 0, "hk": "no hotkey",
          "cwd": start, "hist": [start], "pos": 0, "clip": ([], False), "select": None, "qcon": None,
          "sort_key": None, "sort_rev": False, "mode": "browse", "fs_tok": 0, "fs_pending": 0, "pos_by_path": {},
          "det_tok": 0, "img": None, "typed": "", "typed_t": 0.0, "det_after": None, "undo": [], "xfer": False,
          "xcancel": False, "live_after": None, "drives": None}
    fsize = {}
    pool = ThreadPoolExecutor(4)
    fcache = {"d": {}, "dirty": False, "loaded": False}  # folder sizes remembered between runs: {path: [bytes, computed_at]}
    FCACHE_TTL = 6 * 3600

    def fcache_load():
        if not fcache["loaded"]:
            fcache["loaded"] = True
            try:
                import json
                fcache["d"] = json.loads((DB_DIR / "foldersize.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                fcache["d"] = {}

    def fcache_save():
        if fcache["dirty"]:
            fcache["dirty"] = False
            try:
                import json
                d = fcache["d"]
                if len(d) > 5000:  # keep the newest 5000
                    d = dict(sorted(d.items(), key=lambda kv: kv[1][1], reverse=True)[:5000])
                    fcache["d"] = d
                (DB_DIR / "foldersize.json").write_text(json.dumps(d), encoding="utf-8")
            except OSError:
                pass
        root.after(30000, fcache_save)
    root.after(30000, fcache_save)
    themed = []  # (widget, {option: palette key}) restyled on theme change
    tabs = [{"cwd": start, "hist": st["hist"], "pos": 0}]
    cur = {"i": 0}

    def tk_themed(w, **opts):
        themed.append((w, opts))
        w.configure(**{k: T[v] for k, v in opts.items()})
        return w

    # ======================================================== real icons
    icon_box = {"gen": None, "tk": {}}

    def setup_icons():
        icon_box["tk"], icon_box["lab"] = {}, {}
        icon_box["gen"] = X.ShellIcons() if cfg["real_icons"] else None
        if icon_box["gen"] and not icon_box["gen"].ok:
            icon_box["gen"] = None
        g = icon_box["gen"]
        if g:
            def warm():
                g.pil("", True)
                for e in "txt pdf png jpg py zip exe mp4 mp3 docx xlsx json md".split():
                    g.pil(e, False)
            threading.Thread(target=warm, daemon=True).start()

    def get_icon(name, isdir):
        g = icon_box["gen"]
        if not g:
            return None
        key = "<dir>" if isdir else os.path.splitext(name)[1][1:].lower()
        im = icon_box["tk"].get(key)
        if im is None:
            pil = g.pil(key, isdir)
            if pil is None:
                icon_box["tk"][key] = False
                return None
            from PIL import ImageTk
            im = icon_box["tk"][key] = ImageTk.PhotoImage(pil)
        return im or None

    setup_icons()

    def get_label_icon(name, isdir, color):
        """The file's icon with a coloured dot in the corner (emoji circles lose their colour in a Tk list)."""
        g = icon_box["gen"]
        if not g or color not in I.LABEL_HEX:
            return None
        key = ("<dir>" if isdir else os.path.splitext(name)[1][1:].lower(), color)
        im = icon_box["lab"].get(key)
        if im is None:
            pil = g.pil(key[0] if not isdir else "", isdir)
            if pil is None:
                icon_box["lab"][key] = False
                return None
            from PIL import ImageDraw, ImageTk
            pil = pil.copy().convert("RGBA")
            ImageDraw.Draw(pil).ellipse((9, 9, 19, 19), fill=I.LABEL_HEX[color], outline="#ffffff", width=1)
            im = icon_box["lab"][key] = ImageTk.PhotoImage(pil)
        return im or None

    # ======================================================== layout
    bar = tk_themed(tk.Frame(root), bg="bg")
    bar.pack(fill="x", padx=12, pady=(8, 0))
    back_b = ttk.Button(bar, text="←", style="Nav.TButton", width=2)
    fwd_b = ttk.Button(bar, text="→", style="Nav.TButton", width=2)
    up_b = ttk.Button(bar, text="↑", style="Nav.TButton", width=2)
    ref_b = ttk.Button(bar, text="↻", style="Nav.TButton", width=2)
    for b in (back_b, fwd_b, up_b, ref_b):
        b.pack(side="left", padx=(0, 3))
    pathbox = tk_themed(tk.Frame(bar, height=30), bg="panel")
    pathbox.pack(side="left", fill="x", expand=True, padx=(6, 0))
    pathbox.pack_propagate(False)
    crumbs = tk_themed(tk.Frame(pathbox), bg="panel")
    crumbs.pack(fill="both", expand=True)
    pathv = tk.StringVar(value=start)
    path_e = ttk.Entry(pathbox, textvariable=pathv)

    tabbar = tk_themed(tk.Frame(root), bg="bg")
    tabbar.pack(fill="x", padx=12, pady=(8, 0))
    cmdbar = tk_themed(tk.Frame(root), bg="bg")
    cmdbar.pack(fill="x", padx=10, pady=(4, 0))

    sbar = tk_themed(tk.Frame(root), bg="bg")
    sbar.pack(fill="x", padx=12, pady=(10, 6))
    q = tk.StringVar()
    entry = ttk.Entry(sbar, textvariable=q, style="Search.TEntry")
    entry.pack(side="left", fill="x", expand=True)
    hint = tk_themed(tk.Label(entry, text="Search everywhere…   try  ext:pdf   size:>100mb   modified:week   -word", font=("Segoe UI", cfg["font_size"] + 1)),
                     bg="panel", fg="muted")

    def sync_hint(*_):
        if q.get() or root.focus_get() is entry:
            hint.place_forget()
        else:
            hint.place(x=16, rely=0.5, anchor="w")
    hint.bind("<Button-1>", lambda e: entry.focus_set())
    entry.bind("<FocusIn>", lambda e: hint.place_forget(), add="+")
    entry.bind("<FocusOut>", lambda e: root.after(20, sync_hint), add="+")
    q.trace_add("write", sync_hint)
    root.after(200, sync_hint)
    scope = tk.BooleanVar(value=False)
    ttk.Checkbutton(sbar, text="Only this folder", variable=scope, command=lambda: refresh()).pack(
        side="left", padx=(12, 0))
    save_b = ttk.Button(sbar, text="★ Save")
    save_b.pack(side="left", padx=(12, 0))
    idx_b = ttk.Button(sbar, text="Re-index", style="Accent.TButton")
    idx_b.pack(side="left", padx=(8, 0))

    chipbar = tk_themed(tk.Frame(root), bg="bg")
    chipbar.pack(fill="x", padx=12, pady=(0, 8))
    chipbtns = {}
    if not cfg.get("show_chips", True):
        chipbar.pack_forget()

    status = tk.StringVar()
    ttk.Label(root, textvariable=status, style="Status.TLabel").pack(side="bottom", fill="x")

    body = tk_themed(tk.Frame(root), bg="bg")
    body.pack(fill="both", expand=True)
    sidebar = tk_themed(tk.Frame(body, width=cfg.get("sidebar_w", 220)), bg="panel")
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)
    side = tk_themed(tk.Listbox(sidebar, exportselection=False, activestyle="none", highlightthickness=0, bd=0,
                                font=("Segoe UI", cfg["font_size"] + 1)),
                     bg="panel", fg="fg", selectbackground="sel", selectforeground="fg")
    side.pack(fill="both", expand=True, padx=6, pady=(4, 6))

    det = tk_themed(tk.Frame(body, width=340), bg="panel")
    det.pack_propagate(False)
    mid = tk_themed(tk.Frame(body), bg="bg")
    mid.pack(side="left", fill="both", expand=True)

    cols = ("path", "modified", "type", "size", "tags")
    heads = {"path": "Folder", "modified": "Date modified", "type": "Type", "size": "Size", "tags": "Tags"}

    def gutter_events(g, t):
        def ev(e, y=None):
            return types.SimpleNamespace(x=e.x_root - t.winfo_rootx(), y=e.y_root - t.winfo_rooty() if y is None else y, state=e.state,
                                         widget=t, x_root=e.x_root, y_root=e.y_root)

        def press(e):
            activate(pane_of(t))
            mq_start(t, ev(e))
            return "break"

        g.bind("<ButtonPress-1>", press)
        g.bind("<B1-Motion>", lambda e: mq["on"] and mq_motion(ev(e)))
        g.bind("<ButtonRelease-1>", lambda e: mq["on"] and mq_end(ev(e)))
        g.bind("<Button-3>", lambda e: (activate(pane_of(t)), t.selection_set(()), popup(ev(e, -1))))

    def save_cols():
        """Remember dragged column widths (all panes share them)."""
        t = pane_frames[pane["i"]][1]
        w = {c: int(t.column(c, "width")) for c in ("#0",) + cols}
        if w != cfg.get("col_w"):
            save_cfg(col_w=w)

    def make_pane():
        fr = tk.Frame(mid, bg=T["bg"], highlightthickness=2, highlightbackground=T["bg"],
                      highlightcolor=T["bg"])
        t = ttk.Treeview(fr, columns=cols, show="tree headings", selectmode="extended")
        t.column("#0", width=380, minwidth=60, anchor="w", stretch=False)  # fixed, so dragging its edge really resizes it
        for c, w in zip(cols, (250, 125, 105, 75, 110)):
            t.column(c, width=w, minwidth=40, stretch=(c == "tags"), anchor="e" if c == "size" else "w")  # the last column takes the slack
        for c_, w_ in (cfg.get("col_w") or {}).items():  # widths you dragged last time
            if c_ in ("#0",) + cols:
                t.column(c_, width=max(40, int(w_)))
        t.bind("<ButtonRelease-1>", lambda e: root.after(80, save_cols), add="+")
        sb = ttk.Scrollbar(fr, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        gut = tk_themed(tk.Frame(fr, width=12), bg="bg")  # a thin blank strip left of the names: drag here to rubber-band, right-click for the folder menu
        gut.pack(side="left", fill="y")
        gutter_events(gut, t)
        t.pack(fill="both", expand=True)
        return fr, t

    pane_frames = [make_pane(), make_pane()]  # (frame, tree); the right one is only shown in split view
    mid.rowconfigure(0, weight=1)
    mid.columnconfigure(0, weight=1, uniform="panes")
    pane_frames[0][0].grid(row=0, column=0, sticky="nsew")
    tree = pane_frames[0][1]  # always the ACTIVE pane's tree (rebound by activate())
    panes = [{"cwd": start, "hist": [start], "pos": 0, "rows": [], "pos_by_path": {}, "mode": "browse"},
             {"cwd": start, "hist": [start], "pos": 0, "rows": [], "pos_by_path": {}, "mode": "browse"}]
    pane = {"i": 0, "split": False}

    # ---- details pane
    ttk.Label(det, text="DETAILS", style="DetHead.TLabel").pack(anchor="w", padx=16, pady=(14, 6))
    prevbox = tk_themed(tk.Frame(det, height=170), bg="raised")
    prevbox.pack(fill="x", padx=16)
    prevbox.pack_propagate(False)
    prev_lbl = tk_themed(tk.Label(prevbox, text="", font=("Segoe UI Emoji", 54)), bg="raised", fg="muted")
    prev_txt = tk_themed(tk.Text(prevbox, wrap="word", bd=0, highlightthickness=0, padx=10, pady=8,
                                 font=("Consolas", 9), state="disabled"), bg="raised", fg="fg")
    prev_lbl.pack(fill="both", expand=True)
    name_l = ttk.Label(det, text="", style="DetName.TLabel", wraplength=300, justify="left")
    name_l.pack(anchor="w", padx=16, pady=(12, 2))
    det_btns = tk_themed(tk.Frame(det), bg="panel")
    det_btns.pack(fill="x", padx=16, pady=(4, 8))
    info = tk_themed(tk.Frame(det), bg="panel")
    info.pack(fill="x", padx=16, pady=(4, 0))
    info_labels = {}

    # ======================================================== menus
    def make_menu():
        m = tk.Menu(root, tearoff=0, bd=0, relief="flat", font=("Segoe UI", cfg["font_size"]))
        tk_themed(m, bg="panel", fg="fg", activebackground="sel", activeforeground="fg")
        return m

    # ======================================================== list display
    def update_headings():
        k = st["sort_key"]
        arrow = " ▼" if st["sort_rev"] else " ▲"
        for idx, (_, t) in enumerate(pane_frames):
            t.heading("#0", text="Name" + (arrow if k == "name" else ""), anchor="w",
                      command=lambda: set_sort("name"))
            for c, key in (("path", "path"), ("modified", "date"), ("type", "type"), ("size", "size"), ("tags", "tags")):
                t.heading(c, text=heads[c] + (arrow if k == key else ""), anchor="e" if c == "size" else "w",
                          command=lambda key=key: set_sort(key))
            mode = st["mode"] if idx == pane["i"] else panes[idx]["mode"]
            t.configure(displaycolumns=("path", "modified", "type", "size", "tags") if mode == "search"
                        else ("modified", "type", "size", "tags"))

    def sort_rows(rows):
        k = st["sort_key"]
        if k:
            keyf = {"name": lambda r: X.natural_key(r[0]), "path": lambda r: r[1].lower(),
                    "date": lambda r: r[3], "type": lambda r: (type_name(r[0], r[4]).lower(), r[0].lower()),
                    "size": lambda r: fsize.get(r[1], 0) if r[4] else r[2],
                    "tags": lambda r: ", ".join(st.get("tinfo", {}).get(r[1], (None, []))[1])}[k]
            rows = sorted(rows, key=keyf, reverse=st["sort_rev"])
        if cfg["folders_first"] and st["mode"] == "browse":
            rows = sorted(rows, key=lambda r: not r[4])  # stable
        return rows

    def set_sort(key, rev=None):
        if rev is None:
            rev = (not st["sort_rev"]) if st["sort_key"] == key else False
        st["sort_key"], st["sort_rev"] = key, rev
        sort_var.set(key)
        rev_var.set(rev)
        show(sort_rows(st["rows"]), msg=status.get(), keep=True)

    def size_text(r):
        name, path, size, mtime, isdir = r
        if not isdir:
            return human_size(size)
        if X.zip_is_virtual(path):
            return human_size(size)
        if path in fsize:
            return human_size(fsize[path])
        return "…" if cfg["folder_sizes"] and st["mode"] == "browse" else ""

    def show(rows, msg=None, took=None, keep=False, restore_y=None):
        t = tree
        keepsel = [st["rows"][int(i)][1] for i in t.selection()] if keep else []
        st["rows"] = rows
        st["gen"] += 1
        gen = st["gen"]
        t.delete(*t.get_children())
        st["pos_by_path"] = {r[1]: i for i, r in enumerate(rows)}
        pending = os.path.normcase(st["select"]) if st["select"] else None
        st["select"] = None
        n = len(rows)
        tinfo = st["tinfo"] = tags_store.get_many([r[1] for r in rows]) if rows else {}
        update_headings()
        if msg is None:
            msg = f"{n:,}{'+' if n >= MAX_RESULTS else ''} results" + (f"   •   {took:.2f}s" if took else "")
        status.set(msg)

        def fill(start):
            if gen != st["gen"]:
                return
            step = 300 if start == 0 else 3000  # first screen at once, the rest in big blocks (many small chunks = a redraw each)
            for i in range(start, min(start + step, n)):
                r = rows[i]
                name, path, size, mtime, isdir = r
                img = get_icon(name, isdir)
                lab_, tg_ = tinfo.get(path, (None, []))
                limg = get_label_icon(name, isdir, lab_) if (lab_ and img) else None
                dot = "" if (limg or not lab_) else "\u25CF"
                t.insert("", "end", iid=str(i), text=(dot + " " if dot else "") + (name if img else f"{glyph(name, isdir)}  {name}"),
                            image=limg or img or "", tags=(("dir",) if isdir else ()) + (("alt",) if i % 2 else ()),
                            values=(os.path.dirname(path), fmt_date(mtime), type_name(name, isdir), size_text(r),
                                    ", ".join(tg_)))
                if (pending and os.path.normcase(path) == pending) or path in keepsel:
                    t.selection_add(str(i))
                    if pending:
                        t.see(str(i))
            if start + step < n:
                root.after(1, fill, start + step)
            elif restore_y is not None:
                t.yview_moveto(restore_y)

        if st["mode"] == "browse" and cfg["folder_sizes"]:
            fcache_load()
            for r_ in rows:  # show the remembered size at once; the walk below refreshes anything older than 6 h
                if r_[4] and r_[1] not in fsize and r_[1] in fcache["d"]:
                    fsize[r_[1]] = fcache["d"][r_[1]][0]
        fill(0)
        if st["mode"] == "browse" and cfg["folder_sizes"]:
            compute_folder_sizes(rows)
        if grid["on"]:
            root.after(10, render_grid)

    # ---- folder sizes (live walk, cancelled when you navigate away)
    def compute_folder_sizes(rows):
        st["fs_tok"] += 1
        tok = st["fs_tok"]
        fcache_load()
        now_ = time.time()
        todo = [r[1] for r in rows if r[4] and not X.zip_is_virtual(r[1])
                and (r[1] not in fsize or now_ - fcache["d"].get(r[1], [0, 0])[1] > FCACHE_TTL)
                and now_ - fcache["d"].get(r[1], [0, 0])[1] > FCACHE_TTL]
        st["fs_pending"] = len(todo)
        if len(fsize) > 20000:
            fsize.clear()

        def job(p):
            low_priority()  # big trees (AppData, games) must never make the window feel slow
            res = dir_stats(p, lambda: tok != st["fs_tok"])
            if res is not None:
                root.after(0, got, p, res[2], tok)

        for p in todo:
            pool.submit(job, p)

    def got(path, size, tok):
        fsize[path] = size
        fcache["d"][path] = [size, time.time()]
        fcache["dirty"] = True
        if tok != st["fs_tok"]:
            return
        st["fs_pending"] -= 1
        i = st["pos_by_path"].get(path)
        if i is not None:
            r = st["rows"][i]
            st["rows"][i] = (r[0], r[1], size, r[3], r[4])
            try:
                tree.set(str(i), "size", human_size(size))
            except tk.TclError:
                pass
        if st["fs_pending"] <= 0 and st["sort_key"] == "size":
            show(sort_rows(st["rows"]), msg=status.get(), keep=True)

    # ---- navigation / search
    def meta(k):
        r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else None

    def idle_status():
        c = meta("count")
        n = len(st["rows"])
        folders = sum(1 for r in st["rows"] if r[4])
        base = f"{n:,} items ({folders:,} folders)   •   " if st["mode"] == "browse" else ""
        live = "live" if cfg["live_index"] else "updated"
        if c:
            status.set(base + f"index: {int(c):,} items, {live}   •   {st['hk']} to summon")
        else:
            status.set(base + "No index yet")

    def boost_recent(rows):
        rec = {p: i for i, p in enumerate(cfg["recent"])}
        return sorted(rows, key=lambda r: rec.get(r[1], 1 << 30)) if rec else rows

    def refresh(*_, live=False):
        st["after"] = None
        text = q.get().strip()
        if st["qcon"]:  # cancel any search still running
            try:
                st["qcon"].interrupt()
            except sqlite3.Error:
                pass
        st["sgen"] += 1
        sgen = st["sgen"]
        if not text:
            st["mode"] = "browse"
            rows = list_dir(st["cwd"], cfg["show_hidden"])
            if rows is None:
                show([], msg=f"Cannot open {st['cwd']}")
                return
            show(sort_rows(rows), msg="", keep=live, restore_y=tree.yview()[0] if live else None)
            if not st["indexing"]:
                idle_status()
            update_details()
            return
        st["mode"] = "search"
        sc = st["cwd"] if scope.get() else None
        base, cterms = X.split_content(text)
        if cterms:
            content_search(base, cterms, sc, sgen)
            return
        t0 = time.time()

        def work():
            c = sqlite3.connect(DB_PATH)
            st["qcon"] = c
            nfuzzy = 0
            try:
                rows, err = search(c, text, scope=sc), None
                if len(rows) < 8 and fuzzy_ok(text):
                    seen = {r[1] for r in rows}
                    extra = [r for r in search_fuzzy(c, text, sc) if r[1] not in seen]
                    rows, nfuzzy = rows + extra, len(extra)
            except sqlite3.Error as e:
                rows, err = None, e
            finally:
                c.close()
            if sgen == st["sgen"]:
                root.after(0, finish, rows, err, nfuzzy)

        def finish(rows, err, nfuzzy):
            if sgen != st["sgen"]:
                return
            if err is not None:
                if "interrupt" not in str(err):
                    status.set(f"Search error: {err}")
                return
            n = len(rows)
            msg = (f"{n:,}{'+' if n >= MAX_RESULTS else ''} results   •   {time.time() - t0:.2f}s"
                   + (f"   •   {nfuzzy} fuzzy matches" if nfuzzy else ""))
            show(sort_rows(boost_recent(rows)) if not st["sort_key"] else sort_rows(rows), msg=msg)
            update_details()

        threading.Thread(target=work, daemon=True).start()

    def content_search(base, terms, sc, sgen):
        forced = not base.strip() and sc is None
        if forced:
            sc = st["cwd"]
        if cfg["content_index"] and not base.strip() and cindex.count() > 0 and cindex.covers(sc):
            if content_search_fts(terms, sc):
                return
        status.set("Collecting files to scan…")
        info_s = {"scanned": 0, "total": 0, "capped": False}

        def msg(rows, final):
            m = f"{len(rows):,} files contain “{' '.join(terms)}”   •   scanned {info_s['scanned']:,}/{info_s['total']:,}"
            if forced:
                m += "   •   searching this folder only (add ext: or a filter to search everywhere)"
            if info_s["capped"]:
                m += "   •   first 30,000 candidates only"
            return m + ("" if final else " …")

        def work():
            c = sqlite3.connect(DB_PATH)
            st["qcon"] = c
            try:
                cand = search(c, base, limit=30001, scope=sc, exts=X.CONTENT_EXTS, files_only=True)
            except sqlite3.Error as e:
                if "interrupt" not in str(e) and sgen == st["sgen"]:
                    root.after(0, status.set, f"Search error: {e}")
                return
            finally:
                c.close()
            info_s["capped"] = len(cand) > 30000
            cand = cand[:30000]
            info_s["total"] = len(cand)
            by_path = {r[1]: r for r in cand}
            hits, last = [], [0.0]

            def push(final=False):
                now = time.time()
                if not final and now - last[0] < 0.5:
                    return
                last[0] = now
                rows = list(hits)
                if sgen == st["sgen"]:
                    root.after(0, lambda: sgen == st["sgen"] and show(rows, msg=msg(rows, final)))

            def on_hit(p):
                hits.append(by_path[p])
                push()

            def on_prog(n):
                info_s["scanned"] = n
                if not hits and sgen == st["sgen"]:
                    root.after(0, lambda: sgen == st["sgen"] and status.set(msg([], False)))

            X.scan_contents(list(by_path), terms, lambda: sgen != st["sgen"], on_hit, on_prog)
            push(True)

        threading.Thread(target=work, daemon=True).start()

    build_crumbs = bind(ui_nav.build_crumbs)

    edit_path = bind(ui_nav.edit_path)

    def end_edit(_=None):
        path_e.pack_forget()
        crumbs.pack(fill="both", expand=True)

    # ---- split view (two panes; `st` always holds the ACTIVE pane's state)
    def mark_active():
        for idx, (fr, _) in enumerate(pane_frames):
            on = pane["split"] and idx == pane["i"]
            fr.configure(highlightbackground=T["accent"] if on else T["bg"],
                         highlightcolor=T["accent"] if on else T["bg"])

    def activate(i):
        nonlocal tree
        if i == pane["i"] or (i == 1 and not pane["split"]):
            return
        panes[pane["i"]].update(cwd=st["cwd"], hist=st["hist"], pos=st["pos"], rows=st["rows"],
                                pos_by_path=st["pos_by_path"], mode=st["mode"])
        pane["i"] = i
        nxt = panes[i]
        st.update(cwd=nxt["cwd"], hist=nxt["hist"], pos=nxt["pos"], rows=nxt["rows"],
                  pos_by_path=nxt["pos_by_path"], mode=nxt["mode"])
        tree = pane_frames[i][1]
        st["fs_tok"] += 1  # cancels the other pane's folder-size jobs
        mark_active()
        pathv.set(st["cwd"])
        build_crumbs()
        if nxt.pop("dirty", False):
            refresh()
        elif st["mode"] == "browse" and cfg["folder_sizes"]:
            compute_folder_sizes(st["rows"])
        update_details()
        sel_status()

    def pane_of(widget):
        return 0 if widget is pane_frames[0][1] else 1

    def refresh_other():
        """Re-read the pane that is NOT active (after copies/moves/deletes)."""
        if not pane["split"] or q.get():
            return
        keep = pane["i"]
        activate(1 - keep)
        refresh()
        activate(keep)

    def to_other(move):
        if not pane["split"]:
            status.set("Turn on Split first (Ctrl+Shift+D)")
            return
        s_ = sel()
        if s_:
            run_transfer([r[1] for r in s_], panes[1 - pane["i"]]["cwd"], move)

    split_btns = []

    toggle_split = bind(ui_nav.toggle_split)

    # ---- tabs
    def save_tab():
        if pane["i"] != 0:
            return
        t = tabs[cur["i"]]
        t["cwd"], t["hist"], t["pos"] = st["cwd"], st["hist"], st["pos"]

    build_tabs = bind(ui_nav.build_tabs)

    def load_tab():
        t = tabs[cur["i"]]
        st["hist"], st["pos"], st["cwd"] = t["hist"], t["pos"], t["cwd"]
        build_tabs()
        navigate(t["cwd"], push=False)

    switch_tab = bind(ui_nav.switch_tab)

    new_tab = bind(ui_nav.new_tab)

    close_tab = bind(ui_nav.close_tab)

    next_tab = bind(ui_nav.next_tab)

    def navigate(path, push=True, select=None):
        path = os.path.normpath(os.path.expandvars(path))
        if len(path) == 2 and path[1] == ":":
            path += "\\"
        if not (os.path.isdir(path) or X.zip_split(path)):
            status.set(f"Can't find {path}")
            return
        if push and path != st["cwd"]:
            del st["hist"][st["pos"] + 1:]
            st["hist"].append(path)
            st["pos"] = len(st["hist"]) - 1
        st["cwd"] = path
        st["select"] = select
        st["fs_tok"] += 1
        record_visit(path)
        if cfg["start"] == "last":
            save_cfg(last_folder=path)
        end_edit()
        ui_pages.show_files(A)
        build_crumbs()
        save_tab()
        build_tabs()
        if q.get():
            q.set("")  # trace refreshes
        else:
            refresh()

    def go_back(_=None):
        if st["pos"] > 0:
            st["pos"] -= 1
            navigate(st["hist"][st["pos"]], push=False)

    def go_fwd(_=None):
        if st["pos"] < len(st["hist"]) - 1:
            st["pos"] += 1
            navigate(st["hist"][st["pos"]], push=False)

    def go_up(_=None):
        parent = os.path.dirname(st["cwd"].rstrip("\\/"))
        if parent and os.path.normcase(parent) != os.path.normcase(st["cwd"]):
            navigate(parent, select=st["cwd"])

    def hard_refresh(_=None):
        fsize.clear()
        refresh()

    def on_type(*_):
        if st["after"]:
            root.after_cancel(st["after"])
        st["after"] = root.after(60, refresh)
        if not st.get("hist_setting"):
            st["hist_i"] = None
            if st.get("rec_after"):
                root.after_cancel(st["rec_after"])
            t_ = q.get().strip()
            st["rec_after"] = root.after(2500, lambda: record_query(t_) if q.get().strip() == t_ else None)

    q.trace_add("write", on_type)

    def sel():
        return [st["rows"][int(i)] for i in tree.selection()]

    # ---- filter chips + saved searches
    def toggle_chip(tok):
        toks = X.tokenize(q.get())
        if tok in toks:
            toks.remove(tok)
        else:
            toks.append(tok)
        q.set(" ".join(toks))

    for label_, tok_ in CHIPS:
        b_ = ttk.Button(chipbar, text=label_, style="Chip.TButton", command=lambda t=tok_: toggle_chip(t))
        chipbtns[tok_] = b_

    def sync_chips(*_):
        toks = set(X.tokenize(q.get()))
        for tok, b in chipbtns.items():
            b.configure(style="ChipOn.TButton" if tok in toks else "Chip.TButton")

    q.trace_add("write", sync_chips)

    def save_search():
        text = q.get().strip()
        if not text:
            status.set("Type a search first, then press ★ Save")
            return
        name = simpledialog.askstring("Save search", "Name for this search:", initialvalue=text[:30], parent=root)
        if name:
            saved = dict(cfg["saved"])
            saved[name] = text
            save_cfg(saved=saved)
            build_sidebar()

    # ======================================================== details pane
    clear_preview = bind(ui_preview.clear_preview)

    show_glyph = bind(ui_preview.show_glyph)

    show_text = bind(ui_preview.show_text)

    show_image = bind(ui_preview.show_image)

    det_rows = bind(ui_preview.det_rows)

    update_details = bind(ui_preview.update_details)

    set_dir_info = bind(ui_preview.set_dir_info)

    set_pil = bind(ui_preview.set_pil)

    schedule_details = bind(ui_preview.schedule_details)

    def sel_status():
        s = sel()
        if s:
            total = sum(r[2] for r in s if not r[4])
            status.set(f"{len(s)} selected" + (f"   •   {human_size(total)}" if total else ""))
        elif st["mode"] == "browse":
            idle_status()

    def toggle_details(_=None, value=None):
        on = (not cfg["details_open"]) if value is None else value
        save_cfg(details_open=on)
        details_var.set(on)
        if on:
            det.pack(side="right", fill="y", before=mid)
            update_details()
        else:
            det.pack_forget()
        details_btn.configure(style="On.TButton" if on else "Cmd.TButton")

    # ======================================================== undo + transfers
    def push_undo(kind, data):
        st["undo"].append((kind, data))
        del st["undo"][:-50]

    def after_change():
        fsize.clear()
        fcache["d"].clear()  # files changed: remembered sizes may be wrong
        fcache["dirty"] = True
        refresh()
        refresh_other()

    do_undo = bind(ui_fileops.do_undo)

    run_transfer = bind(ui_fileops.run_transfer)

    # ======================================================== actions
    open_item = bind(ui_fileops.open_item)

    open_new_tab = bind(ui_fileops.open_new_tab)

    open_with = bind(ui_fileops.open_with)

    show_props = bind(ui_fileops.show_props)

    show_in_folder = bind(ui_fileops.show_in_folder)

    copy_path = bind(ui_fileops.copy_path)

    do_copy = bind(ui_fileops.do_copy)

    do_paste = bind(ui_fileops.do_paste)

    do_delete = bind(ui_fileops.do_delete)

    do_rename = bind(ui_fileops.do_rename)

    new_item = bind(ui_fileops.new_item)

    compress = bind(ui_fileops.compress)

    extract = bind(ui_fileops.extract)

    open_terminal = bind(ui_fileops.open_terminal)

    open_explorer = bind(ui_fileops.open_explorer)

    pin = bind(ui_fileops.pin)

    # ======================================================== tools windows
    def work_area(w):
        """(left, top, right, bottom) of the usable area of the monitor that holds window w."""
        import ctypes
        from ctypes import wintypes

        class MI(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("mon", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
        try:
            u = ctypes.windll.user32
            u.MonitorFromWindow.restype = ctypes.c_void_p
            u.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
            u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            hm = u.MonitorFromWindow(w.winfo_id(), 2)
            mi = MI()
            mi.cb = ctypes.sizeof(MI)
            if u.GetMonitorInfoW(hm, ctypes.byref(mi)):
                return mi.work.left, mi.work.top, mi.work.right, mi.work.bottom
        except Exception:
            pass
        return 0, 0, w.winfo_screenwidth(), w.winfo_screenheight()

    def toplevel(title, geo, tab=True):
        if tab:  # tools open as a tab inside the main window (modal questions pass tab=False)
            return ui_pages.new_page(A, title)
        win = tk.Toplevel(root)
        win.title(title)
        win.configure(bg=T["bg"])
        win.transient(root)
        W_, H_ = (int(v) for v in geo.split("x"))
        l_, t_, r_, b_ = work_area(root)  # keep every dialog fully on the screen the app is on (small screens / windowed app)
        W_, H_ = min(W_, r_ - l_ - 20), min(H_, b_ - t_ - 50)
        x_ = max(l_, min(root.winfo_rootx() + 80, r_ - W_))
        y_ = max(t_, min(root.winfo_rooty() + 60, b_ - H_ - 40))
        win.geometry(f"{W_}x{H_}+{x_}+{y_}")
        dark_titlebar(win, T["dark"])
        win.bind("<Escape>", lambda e: win.destroy())
        return win

    # ======================================================== duplicates (with scope) + smart disk cleaner
    open_duplicates = bind(ui_cleaner.open_duplicates)

    # ======================================================== FTP browser + settings export/import
    open_ftp = bind(ui_tools.open_ftp)

    export_settings = bind(ui_tools.export_settings)

    import_settings = bind(ui_tools.import_settings)

    # ======================================================== one-click tune-up

    # ======================================================== auto-clean (moves safe junk to a quarantine, restorable for 7 days)
    qroot = str(DB_DIR / "quarantine")
    ac_state = {"running": False}

    autoclean_now = bind(ui_health.autoclean_now)

    autoclean_tick = bind(ui_health.autoclean_tick)

    open_autoclean = bind(ui_health.open_autoclean)

    open_cleaner = bind(ui_cleaner.open_cleaner)

    open_largest = bind(ui_cleaner.open_largest)

    open_organize = bind(ui_cleaner.open_organize)

    # ======================================================== checksums, image convert, empty folders, search history
    open_checksum = bind(ui_tools.open_checksum)

    open_convert_images = bind(ui_tools.open_convert_images)

    open_integrity = bind(ui_tools.open_integrity)

    open_ocr = bind(ui_tools.open_ocr)

    open_photo_info = bind(ui_tools.open_photo_info)

    open_sync = bind(ui_tools.open_sync)


    def record_query(text):
        text = (text or "").strip()
        if len(text) < 3:
            return
        h = [x for x in cfg["search_history"] if x != text]
        h.insert(0, text)
        cfg["search_history"] = h[:40]
        save_cfg(search_history=cfg["search_history"])

    hist_move = bind(ui_nav.hist_move)

    # ======================================================== breadcrumb dropdowns, copy to / move to, copy as
    subfolders = bind(ui_nav.subfolders)

    crumb_menu = bind(ui_nav.crumb_menu)

    choose_dest = bind(ui_nav.choose_dest)

    dest_menu = bind(ui_nav.dest_menu)

    copy_as = bind(ui_fileops.copy_as)

    # ======================================================== PC health center, backups and alerts
    open_action = bind(ui_health.open_action)

    ACTION_LABEL = {"cleaner": "Open the disk cleaner", "largest": "Find the biggest files", "taskmgr": "Open Task Manager",
                    "update": "Open Windows Update", "security": "Open Windows Security", "backup": "Set up / run a backup",
                    "storage": "Open Storage settings", "health": "Open PC health"}

    show_toast = bind(ui_health.show_toast)

    health_watch = bind(ui_health.health_watch)

    bk_running = set()  # (src, dst) of jobs being backed up right now (manual or scheduled)
    bk_hooks = []       # callbacks the open Backups tab registers so it refreshes when a scheduled run finishes

    set_job_fields = bind(ui_health.set_job_fields)

    hist_path = str(DB_DIR / "history.json")

    perf_tick = bind(ui_health.perf_tick)

    bk_tick = bind(ui_health.bk_tick)

    set_score = bind(ui_health.set_score)

    weekly_check = bind(ui_health.weekly_check)

    threat_check = bind(ui_health.threat_check)

    check = bind(ui_health.check)

    open_health = bind(ui_health.open_health)

    open_treemap = bind(ui_tools.open_treemap)

    open_bulk_rename = bind(ui_tools.open_bulk_rename)

    # ======================================================== command palette (Ctrl+K)
    palette_actions = bind(ui_toolbar.palette_actions)

    def local_folders():
        out = [home] + [os.path.join(home, n) for n in ("Desktop", "Documents", "Downloads", "Pictures", "Music",
                                                         "Videos")]
        out += list(cfg["pins"]) + [d[0] for d in X.drives()] + list(reversed(st["hist"]))
        seen, res = set(), []
        for p in out:
            k = os.path.normcase(p)
            if k not in seen and os.path.isdir(p):
                seen.add(k)
                res.append(p)
        return res

    open_palette = bind(ui_settings.open_palette)

    # ======================================================== quick preview (Space)
    qp = {"win": None, "tok": 0}

    close_preview = bind(ui_preview.close_preview)

    pv_show = bind(ui_preview.pv_show)

    render_preview = bind(ui_preview.render_preview)

    step_preview = bind(ui_preview.step_preview)

    open_preview = bind(ui_preview.open_preview)

    quick_preview_key = bind(ui_preview.quick_preview_key)

    # ======================================================== copy conflicts
    conflict_dialog = bind(ui_fileops.conflict_dialog)

    # ======================================================== thumbnail grid view
    grid = {"on": False, "cw": 132, "ch": 150, "cols": 1, "tk": {}, "pending": set(), "imgs": {}, "last": None,
            "after": None}
    gridf = tk_themed(tk.Frame(mid), bg="bg")
    gcv = tk_themed(tk.Canvas(gridf, highlightthickness=0, yscrollincrement=50), bg="bg")
    gsb = ttk.Scrollbar(gridf, orient="vertical", command=gcv.yview)
    gsb.pack(side="right", fill="y")
    gcv.pack(fill="both", expand=True)
    gpool = ThreadPoolExecutor(3)
    grid_var = tk.BooleanVar(value=cfg["view_grid"])

    grid_schedule = bind(ui_grid.grid_schedule)

    gscroll = bind(ui_grid.gscroll)

    gcv.configure(yscrollcommand=gscroll)

    grid_icon = bind(ui_grid.grid_icon)

    thumb_dir = DB_DIR / "thumbs"

    _thumb_file = bind(ui_grid._thumb_file)

    thumb_cache_get = bind(ui_grid.thumb_cache_get)

    thumb_cache_put = bind(ui_grid.thumb_cache_put)

    thumb_cache_prune = bind(ui_grid.thumb_cache_prune)

    grid_load_thumb = bind(ui_grid.grid_load_thumb)

    grid_thumb_ready = bind(ui_grid.grid_thumb_ready)

    render_grid = bind(ui_grid.render_grid)

    grid_index_at = bind(ui_grid.grid_index_at)

    grid_see = bind(ui_grid.grid_see)

    grid_select = bind(ui_grid.grid_select)

    gmq = {"on": False}

    grid_tiles_in = bind(ui_grid.grid_tiles_in)

    grid_motion = bind(ui_grid.grid_motion)

    grid_release = bind(ui_grid.grid_release)

    grid_click = bind(ui_grid.grid_click)

    grid_key = bind(ui_grid.grid_key)

    grid_popup = bind(ui_grid.grid_popup)

    toggle_grid = bind(ui_grid.toggle_grid)

    gcv.bind("<Button-1>", grid_click)
    gcv.bind("<B1-Motion>", grid_motion)
    gcv.bind("<ButtonRelease-1>", grid_release)
    gcv.bind("<Double-1>", lambda e: open_item() if grid_index_at(e.x, e.y) is not None else None)
    gcv.bind("<Button-3>", grid_popup)
    gcv.bind("<Configure>", grid_schedule)
    gcv.bind("<MouseWheel>", lambda e: (gcv.yview_scroll(-3 if e.delta > 0 else 3, "units"), "break")[-1])
    gcv.bind("<Control-MouseWheel>", lambda e: (zoom(1 if e.delta > 0 else -1), "break")[-1])
    for key_, d_ in (("<Left>", -1), ("<Right>", 1)):
        gcv.bind(key_, grid_key(d_))
    gcv.bind("<Up>", lambda e: grid_key(-grid["cols"])())
    gcv.bind("<Down>", lambda e: grid_key(grid["cols"])())
    gcv.bind("<Home>", lambda e: (grid_select(0), "break")[-1])
    gcv.bind("<End>", lambda e: (grid_select(len(st["rows"]) - 1), "break")[-1])
    gcv.bind("<Return>", open_item)
    gcv.bind("<BackSpace>", go_up)
    gcv.bind("<Delete>", do_delete)
    gcv.bind("<F2>", do_rename)
    gcv.bind("<Control-c>", do_copy)
    gcv.bind("<Control-x>", lambda e: do_copy(cut=True))
    gcv.bind("<Control-v>", do_paste)
    gcv.bind("<Control-a>", lambda e: tree.selection_set(tree.get_children()))
    gcv.bind("<Alt-Return>", show_props)
    gcv.bind("<space>", quick_preview_key)

    # ======================================================== compare folders (needs split view)
    open_compare = bind(ui_tools.open_compare)

    # ======================================================== recent / frequent, tab memory, tags, content index
    def persist_soon():
        if st.get("persist_after"):
            root.after_cancel(st["persist_after"])

        def go():
            st["persist_after"] = None
            save_state()
            build_sidebar()

        st["persist_after"] = root.after(2500, go)

    def save_state():
        """Write what a restart should bring back: open tabs, recent folders, frequent folders."""
        save_tab()
        real = [t["cwd"] for t in tabs if not X.zip_is_virtual(t["cwd"]) and os.path.isdir(t["cwd"])]
        save_cfg(recent_dirs=cfg["recent_dirs"], frec=cfg["frec"], tabs=real, tab_i=min(cur["i"], max(0, len(real) - 1)))

    def app_restart():
        """Quit and start again by itself (picks up an installed update or new code); your tabs come back."""
        import ff_update
        save_state()
        ff_update.restart_app()
        root.after(200, root.destroy)

    def commit_visit(path):
        """A folder counts as 'recent' only after you actually used it (stayed, or opened a file from it)."""
        if X.zip_split(path) or recent_noise(path) or not os.path.isdir(path):
            return
        key = os.path.normcase(path)
        if any(key == os.path.normcase(g) or key.startswith(os.path.normcase(g) + "\\") for g in cfg["recent_ignore"]):
            return
        now_ = time.time()
        rd = [x for x in cfg["recent_dirs"] if os.path.normcase(x) != key]
        rd.insert(0, path)
        cfg["recent_dirs"] = rd[:40]
        sc_, last_ = cfg["frec"].get(path, (0.0, now_))
        frec = dict(cfg["frec"])
        frec[path] = [sc_ * 0.5 ** ((now_ - last_) / (7 * 86400)) + 1.0, now_]  # frecency: visits fade with a 7-day half-life
        if len(frec) > 300:
            for k_ in sorted(frec, key=lambda k: frec[k][0])[:60]:
                frec.pop(k_, None)
        cfg["frec"] = frec
        persist_soon()

    def record_visit(path):
        """Called on every navigation; only commits if you stay put for a few seconds (passing through doesn't count)."""
        if st.get("dwell_after"):
            root.after_cancel(st["dwell_after"])

        def check(p=path):
            st["dwell_after"] = None
            if os.path.normcase(st["cwd"]) == os.path.normcase(p):
                commit_visit(p)

        st["dwell_after"] = root.after(4000, check)

    def forget_folder(path, ignore=False):
        cfg["recent_dirs"] = [x for x in cfg["recent_dirs"] if x != path]
        frec = dict(cfg["frec"])
        frec.pop(path, None)
        cfg["frec"] = frec
        kw = dict(recent_dirs=cfg["recent_dirs"], frec=cfg["frec"])
        if ignore:
            kw["recent_ignore"] = list(cfg["recent_ignore"]) + [path]
        save_cfg(**kw)
        build_sidebar()
        status.set("Removed from the sidebar lists" + ("  \u2022  it won't come back (Customize \u2192 Recent items to undo)" if ignore else ""))

    def forget_file(path):
        save_cfg(recent=[x for x in cfg["recent"] if x != path])
        build_sidebar()

    def clear_recent(which):
        kw = {}
        if which in ("recent_dirs", "all"):
            kw["recent_dirs"] = []
        if which in ("frequent", "all"):
            kw["frec"] = {}
        if which in ("recent_files", "all"):
            kw["recent"] = []
        save_cfg(**kw)
        build_sidebar()
        status.set({"recent_dirs": "Recent folders cleared", "frequent": "Frequent folders cleared",
                    "recent_files": "Recent files cleared", "all": "Recent and frequent lists cleared"}[which])

    reopen_tab = bind(ui_nav.reopen_tab)

    rename_to = bind(ui_fileops.rename_to)

    inline_rename = bind(ui_fileops.inline_rename)

    def refresh_labels():
        build_sidebar()
        refresh(live=True)

    set_label = bind(ui_fileops.set_label)

    edit_tags = bind(ui_fileops.edit_tags)

    def content_folders():
        out = [os.path.join(home, n) for n in ("Documents", "Desktop", "Downloads")] + list(cfg["pins"])
        return [p for p in dict.fromkeys(out) if os.path.isdir(p)]

    def ci_progress(n):
        if not st["indexing"] and not q.get().strip():
            status.set(f"Reading documents for content search\u2026 {n:,} files")

    def ci_done(n):
        if not st["indexing"] and not q.get().strip():
            note = "" if I.pdf_supported() else "   \u2022   PDF text needs:  pip install pypdf"
            status.set(f"Content index ready: {cindex.count():,} documents ({n:,} new or changed){note}")

    def start_content_index(force=False):
        if (not cfg["content_index"] and not force) or cindex.building:
            return

        def work():
            low_priority()
            try:
                last_ci = [0.0]

                def ci_throttled(k):
                    now_ = time.monotonic()
                    if now_ - last_ci[0] > 0.2:
                        last_ci[0] = now_
                        root.after(0, ci_progress, k)
                n = cindex.build(content_folders(), ci_throttled)
            except Exception as e:  # noqa
                log_error(f"content index: {e}")
                n = 0
            root.after(0, ci_done, n)

        threading.Thread(target=work, daemon=True).start()

    def content_search_fts(terms, sc):
        """Instant answer from the content index. Returns True if it showed results."""
        hits = cindex.search(terms, 3000)
        low = os.path.normcase(sc).rstrip("\\") + "\\"
        rows = []
        for pth in hits:
            if not os.path.normcase(pth).startswith(low):
                continue
            try:
                s_ = os.stat(pth)
            except OSError:
                continue
            rows.append((os.path.basename(pth), pth, s_.st_size, s_.st_mtime, 0))
        if not rows:
            return False
        show(rows, msg=f"{len(rows):,} documents contain \u201c{' '.join(terms)}\u201d   \u2022   instant, from the content index "
                       f"({cindex.count():,} files)   \u2022   this folder only")
        return True

    # ======================================================== sidebar
    side_items = []  # (kind, value): "h" header, "path", "search"
    side_sections = []  # parallel list: which list a row belongs to (for the right-click menu)

    build_sidebar = bind(ui_nav.build_sidebar)

    on_side = bind(ui_nav.on_side)

    side_popup = bind(ui_nav.side_popup)

    def watch_drives():
        if tuple(d[0] for d in X.drives()) != st["drives"]:
            build_sidebar()
        root.after(20000, watch_drives)
    root.after(7000, start_content_index)
    root.after(25000, health_watch)
    root.after(90000, bk_tick)
    root.after(240000, autoclean_tick)
    root.after(120000, lambda: threading.Thread(target=thumb_cache_prune, daemon=True).start())
    if cfg["view_grid"]:
        root.after(150, lambda: toggle_grid(value=True))
    root._ff = locals()  # handy for tests/debugging

    # ======================================================== toolbar + menus
    sort_var = tk.StringVar(value="")
    rev_var = tk.BooleanVar(value=False)
    hidden_var = tk.BooleanVar(value=cfg["show_hidden"])
    fsz_var = tk.BooleanVar(value=cfg["folder_sizes"])
    details_var = tk.BooleanVar(value=cfg["details_open"])
    ff_var = tk.BooleanVar(value=cfg["folders_first"])
    dens_var = tk.IntVar(value=cfg["row_height"])

    pop_closed = {}  # widget -> time its menu last closed

    popup_below = bind(ui_toolbar.popup_below)

    set_flag = bind(ui_toolbar.set_flag)

    new_menu = bind(ui_toolbar.new_menu)

    sort_menu = bind(ui_toolbar.sort_menu)

    view_menu = bind(ui_toolbar.view_menu)

    save_workspace = bind(ui_nav.save_workspace)

    load_workspace = bind(ui_nav.load_workspace)

    delete_workspace = bind(ui_nav.delete_workspace)


    tip = bind(ui_toolbar.tip)

    TIPS = {"New": "Create a new folder or text document", "Cut": "Cut the selected items (Ctrl+X)", "Copy": "Copy the selected items (Ctrl+C)",
            "Paste": "Paste here (Ctrl+V)", "Rename": "Rename the selected item (F2)", "Delete": "Move the selected items to the Recycle Bin (Del)",
            "Sort": "Change how the list is sorted", "View": "Row size, hidden files and other display options",
            "Tools": "Cleaner, health, malware check, backups, sync, FTP and more", "Clean": "Smart disk cleaner",
            "Health": "PC health center: score, security, backups, trends", "Split": "Show two folders side by side (Ctrl+Shift+D)",
            "Grid": "Thumbnail grid view (Ctrl+Shift+G)", "Details": "Show or hide the details pane (F3)"}

    cmd_items = []  # toolbar entries in order; layout_cmdbar() packs what fits and moves the rest into the » menu

    def mk_btn(text, cmd, menu=None, **kw):
        kw.setdefault("width", 0)  # natural width (ttk's default minimum made every button ~100 px wide)
        b = ttk.Button(cmdbar, text=text, style="Cmd.TButton", command=cmd, **kw)
        cmd_items.append(dict(w=b, kind="btn", label=text, cmd=cmd, menu=menu))
        key_ = next((w_ for w_ in text.replace("\u2764", "").replace("\u25B8", "").split() if w_.strip("\u25BE") in TIPS), None)
        if key_:
            tip(b, TIPS[key_.strip("\u25BE")])
        return b

    def mk_sep():
        s_ = ttk.Separator(cmdbar, orient="vertical")
        cmd_items.append(dict(w=s_, kind="sep"))

    sort_b = mk_btn("⇅ Sort ▾", lambda: popup_below(sort_b, sort_menu()), menu=sort_menu)
    view_b = mk_btn("☰ View ▾", lambda: popup_below(view_b, view_menu()), menu=view_menu)
    tools_b = mk_btn("⚙ Tools" + (f"  ❤{cfg['last_score']}" if cfg.get("last_score") is not None else ""), lambda: ui_pages.open_tools(A))
    health_btn = tools_b  # the Tools button also shows the latest health score (set_score)
    split_b = mk_btn("◫ Split", toggle_split)
    set_b = ttk.Button(cmdbar, text="⚙", style="Cmd.TButton", width=3, command=lambda: open_settings())
    set_b.pack(side="right", padx=1)
    details_btn = ttk.Button(cmdbar, text="◧ Details", style="Cmd.TButton", command=toggle_details)
    details_btn.pack(side="right", padx=1)
    tip(details_btn, TIPS["Details"])
    tip(set_b, "Settings (Ctrl+,)")
    over_b = ttk.Button(cmdbar, text="»", style="Cmd.TButton", width=3, command=lambda: popup_below(over_b, overflow_menu()))
    lay = {"sig": None, "shown": set()}

    overflow_menu = bind(ui_toolbar.overflow_menu)

    layout_cmdbar = bind(ui_toolbar.layout_cmdbar)

    cmdbar.bind("<Configure>", layout_cmdbar)
    fit = {"narrow": False}

    autofit = bind(ui_toolbar.autofit)

    root.bind("<Configure>", autofit, add="+")
    root.minsize(600, 420)
    root.after(50, lambda: ui_toolbar.sync_pins(A))
    ui_extras.attach_path_complete(A)
    DATE_STYLE.update(fmt=DATE_FORMATS.get(cfg.get("date_fmt"), "%d/%m/%Y"), h12=bool(cfg.get("clock_12h")))
    ui_extras.restore_window(root, cfg)

    chip_lay = {"sig": None}

    flow_chips = bind(ui_toolbar.flow_chips)

    chipbar.bind("<Configure>", flow_chips)

    native_ctx = bind(ui_toolbar.native_ctx)

    popup = bind(ui_toolbar.popup)

    # ======================================================== drag & drop (inside the app)
    drag = {"start": None, "row": None, "hold": False, "active": False, "items": [], "top": None, "hl": None}

    drop_target = bind(ui_dragselect.drop_target)

    clear_hl = bind(ui_dragselect.clear_hl)

    set_hl = bind(ui_dragselect.set_hl)

    ole_out = bind(ui_dragselect.ole_out)

    # ---- rubber-band selection: hold the left button on empty space (or past the file name) and drag over items
    mq = {"on": False, "lines": {}, "font": None}

    mq_rect = bind(ui_dragselect.mq_rect)

    mq_clear = bind(ui_dragselect.mq_clear)

    mq_row0 = bind(ui_dragselect.mq_row0)

    mq_in_zone = bind(ui_dragselect.mq_in_zone)

    mq_start = bind(ui_dragselect.mq_start)

    mq_update = bind(ui_dragselect.mq_update)

    mq_tick = bind(ui_dragselect.mq_tick)

    mq_motion = bind(ui_dragselect.mq_motion)

    mq_end = bind(ui_dragselect.mq_end)

    dnd_press = bind(ui_dragselect.dnd_press)

    dnd_motion = bind(ui_dragselect.dnd_motion)

    dnd_release = bind(ui_dragselect.dnd_release)

    # ======================================================== customise
    restyle = bind(ui_toolbar.restyle)

    change_setting = bind(ui_toolbar.change_setting)

    zoom = bind(ui_toolbar.zoom)

    open_settings = bind(ui_settings.open_settings)
    open_about = bind(ui_about.open_about)
    welcome = lambda rerun=False: ui_about.welcome(A, rerun=rerun)
    open_tutorial = bind(ui_extras.open_tutorial)
    open_shortcuts = bind(ui_extras.open_shortcuts)
    open_storage_types = bind(ui_extras.open_storage_types)
    open_diff = bind(ui_extras.open_diff)
    open_whats_new = bind(ui_extras.open_whats_new)
    open_system_info = bind(ui_extras.open_system_info)
    select_pattern = bind(ui_extras.select_pattern)
    invert_selection = bind(ui_extras.invert_selection)
    open_undo_history = bind(ui_extras.open_undo_history)
    open_recycle_bin = bind(ui_browse.open_recycle_bin)
    open_recent_changes = bind(ui_browse.open_recent_changes)
    open_games = bind(ui_games.open_games)
    open_collections = bind(ui_more.open_collections)
    open_howto = bind(ui_more.open_howto)
    open_folder_history = bind(ui_more.open_folder_history)
    rename_saved = bind(ui_more.rename_saved)
    track_tick = bind(ui_more.track_tick)
    root.after(7000, lambda: ui_more.crash_check(A) if not os.environ.get("FF_NO_CRASHCHECK") else None)
    folder_sizes_now = bind(ui_extras.folder_sizes_now)
    export_csv = bind(ui_extras.export_csv)
    if background and not cfg["setup_done"]:
        root.after(2500, welcome)  # the wizard opens the tutorial when it is saved
    elif background and cfg["show_tutorial"]:
        root.after(2500, open_tutorial)
    if background:
        root.after(6000, lambda: ui_extras.whats_new_check(A))
    open_vault = bind(ui_tools.open_vault)
    open_similar_photos = bind(ui_tools.open_similar_photos)
    open_notify = bind(ui_about.open_notify)

    def notify(title, text):
        """Also send this to the phone/chat address set in Tools > Phone notifications (if any). Never blocks, never raises."""
        url = cfg["notify_url"].strip()
        if url:
            def go():
                try:
                    ff_notify.send(url, title, text)
                except Exception as e:  # noqa
                    log_error(f"notify: {e}")
            threading.Thread(target=go, daemon=True).start()
    open_storage = bind(ui_about.open_storage)
    make_problem_report = bind(ui_about.problem_report)
    root.after(60000, lambda: __import__("ff_update").confirm_update())  # still alive after a minute: the update is good
    open_malware = bind(ui_malware.open_malware)
    scan_with_defender = bind(ui_malware.scan_paths)
    malware_tick = bind(ui_malware.malware_tick)
    root.after(300000, malware_tick)
    update_tick = bind(ui_about.update_tick)
    root.after(180000, update_tick)

    # ======================================================== bindings
    back_b.config(command=go_back)
    fwd_b.config(command=go_fwd)
    up_b.config(command=go_up)
    ref_b.config(command=hard_refresh)
    save_b.config(command=save_search)
    path_e.bind("<Return>", lambda e: navigate(pathv.get().strip().strip('"')))
    path_e.bind("<Escape>", lambda e: (end_edit(), tree.focus_set()))
    path_e.bind("<FocusOut>", lambda e: root.after(100, end_edit) if root.focus_get() is not path_e else None)
    side.bind("<<ListboxSelect>>", on_side)
    side.bind("<Button-3>", side_popup)
    tree.bind("<Double-1>", open_item)
    tree.bind("<Return>", open_item)
    tree.bind("<Button-3>", popup)
    tree.bind("<Button-2>", lambda e: (tree.selection_set(tree.identify_row(e.y)), open_new_tab())
              if tree.identify_row(e.y) else None)
    tree.bind("<ButtonPress-1>", dnd_press)
    tree.bind("<B1-Motion>", dnd_motion)
    tree.bind("<ButtonRelease-1>", dnd_release)
    tree.bind("<ButtonRelease-1>", lambda e: root.after(80, save_cols), add="+")
    tree.bind("<BackSpace>", go_up)
    tree.bind("<Delete>", do_delete)
    tree.bind("<F2>", inline_rename)
    tree.bind("<Control-c>", do_copy)
    tree.bind("<Control-x>", lambda e: do_copy(cut=True))
    tree.bind("<Control-v>", do_paste)
    tree.bind("<Control-a>", lambda e: tree.selection_set(tree.get_children()))
    tree.bind("<<TreeviewSelect>>", schedule_details)
    tree.bind("<Alt-Return>", show_props)
    tree.bind("<space>", quick_preview_key)
    tree.bind("<<TreeviewSelect>>", grid_schedule, add="+")
    tree.bind("<Control-MouseWheel>", lambda e: (zoom(1 if e.delta > 0 else -1), "break")[-1])

    def type_select(e):  # type letters to jump to a matching name, like Explorer
        if not e.char or not e.char.isprintable() or e.state & 0x4:
            return
        now = time.time()
        st["typed"] = (st["typed"] if now - st["typed_t"] < 0.9 else "") + e.char.lower()
        st["typed_t"] = now
        for i, r in enumerate(st["rows"]):
            if r[0].lower().startswith(st["typed"]):
                tree.selection_set(str(i))
                tree.focus(str(i))
                tree.see(str(i))
                break

    tree.bind("<Key>", type_select, add="+")
    for _seq in tree.bind():  # the right-hand pane gets exactly the same bindings
        pane_frames[1][1].bind(_seq, tree.bind(_seq))

    def tab_key(e):
        if pane["split"]:
            activate(1 - pane["i"])
            tree.focus_set()
            return "break"

    for _i, (_, _t) in enumerate(pane_frames):
        _t.bind("<FocusIn>", lambda e, _i=_i: activate(_i), add="+")
        _t.bind("<Tab>", tab_key)
    root.bind("<Control-Shift-D>", toggle_split)
    root.bind("<Control-k>", open_palette)
    root.bind("<F1>", open_shortcuts)
    root.bind("<Control-Shift-S>", select_pattern)
    root.bind("<Control-i>", invert_selection)
    root.bind("<Control-Shift-C>", copy_path)
    root.bind("<Alt-Return>", lambda e: show_props())
    for _n in range(1, 10):
        root.bind(f"<Control-Key-{_n}>", lambda e, _n=_n: (switch_tab(_n - 1) if _n <= len(tabs) else None))
    _save_win = {"job": None}

    def _win_changed(e):
        if e.widget is root:
            if _save_win["job"]:
                root.after_cancel(_save_win["job"])
            _save_win["job"] = root.after(1200, lambda: ui_extras.remember_window(A))
    root.bind("<Configure>", _win_changed, add="+")
    ui_extras.theme_tick(A)
    root.bind("<Control-Shift-T>", reopen_tab)
    root.bind("<Control-Shift-G>", toggle_grid)
    root.bind("<Control-Shift-N>", lambda e: new_item("dir"))
    root.bind("<Control-Shift-R>", lambda e: open_bulk_rename())
    root.bind("<Control-z>", do_undo)
    root.bind("<Control-t>", lambda e: new_tab())
    root.bind("<Control-w>", lambda e: close_tab())
    root.bind("<Control-Tab>", lambda e: next_tab(1))
    root.bind("<Control-Shift-Tab>", lambda e: next_tab(-1))
    root.bind("<F5>", hard_refresh)
    root.bind("<F3>", toggle_details)
    root.bind("<Alt-Left>", go_back)
    root.bind("<Alt-Right>", go_fwd)
    root.bind("<Alt-Up>", go_up)
    root.bind("<Control-Return>", show_in_folder)
    root.bind("<Control-l>", edit_path)
    root.bind("<Control-f>", lambda e: (entry.focus_set(), entry.select_range(0, "end")))
    entry.bind("<FocusIn>", lambda e: ui_pages.show_files(A), add="+")
    root.bind("<Control-comma>", open_settings)
    root.bind("<Control-equal>", lambda e: zoom(1))
    root.bind("<Control-plus>", lambda e: zoom(1))
    root.bind("<Control-minus>", lambda e: zoom(-1))
    root.bind("<Control-q>", lambda e: root.destroy())
    entry.bind("<Up>", lambda e: hist_move(-1))
    entry.bind("<Return>", lambda e: record_query(q.get()))
    entry.bind("<Down>", lambda e: hist_move(1) or (tree.focus_set(), tree.get_children() and tree.selection_set(
        tree.get_children()[0]), "break")[-1])
    # mouse side buttons: Tk on Windows reports them as ButtonRelease 4 (back) / 5 (forward)
    root.bind_all("<ButtonRelease-4>", go_back)
    root.bind_all("<ButtonRelease-5>", go_fwd)

    def on_escape(_=None):
        # Esc only cancels things (a transfer, a search); it never hides or closes the main window.
        # Pop-ups (palette, preview, dialogs, tool windows) handle their own Esc.
        if st["xfer"]:
            st["xcancel"] = True
        elif q.get():
            q.set("")

    root.bind("<Escape>", on_escape)

    # ======================================================== indexing + live updates
    def start_index():
        if st["indexing"]:
            st["stop"] = True
            return
        st.update(indexing=True, stop=False)
        idx_b.config(text="Stop")

        def work():
            low_priority()

            last_post = [0.0]

            def prog(n, p):  # at most ~7 UI updates a second: thousands of root.after() calls per second made the window crawl while indexing
                now_ = time.monotonic()
                if now_ - last_post[0] > 0.15:
                    last_post[0] = now_
                    root.after(0, status.set, f"Indexing... {n:,} items  -  {p[:90]}")
            c = build_index(fixed_drives(), prog, lambda: st["stop"])
            root.after(0, done, c)

        def done(c):
            nonlocal con
            st["indexing"] = False
            idx_b.config(text="Re-index")
            con.close()
            con = connect()
            refresh()

        threading.Thread(target=work, daemon=True).start()

    idx_b.config(command=start_index)

    def on_fs_change(paths):
        """Called (on the Tk thread) with the paths the live index just absorbed."""
        if cfg["content_index"] and not cindex.building:
            threading.Thread(target=lambda: cindex.update_paths(paths[:300]), daemon=True).start()
        if st["mode"] != "browse":
            return
        cw = os.path.normcase(st["cwd"]).rstrip("\\")
        hit = any(os.path.normcase(os.path.dirname(p)).rstrip("\\") == cw for p in paths[:3000])
        if len(paths) <= 300 and fsize:
            low = [os.path.normcase(p) for p in paths]
            for k in list(fsize):
                kn = os.path.normcase(k) + "\\"
                if any(p.startswith(kn) for p in low):
                    fsize.pop(k, None)
                    hit = hit or os.path.normcase(os.path.dirname(k)).rstrip("\\") == cw
        if hit:
            if st["live_after"]:
                root.after_cancel(st["live_after"])
            st["live_after"] = root.after(400, lambda: (st.update(live_after=None), refresh(live=True)))

    if cfg["live_index"] and background and os.name == "nt":
        def start_watch():
            try:
                X.ensure_index(DB_PATH)
                w = X.Watcher(DB_PATH, fixed_drives(), SKIP_DIRS, ignore_prefixes=[str(DB_DIR)])
                w.on_change = lambda ps: root.after(0, on_fs_change, ps)
                w.start()
                st["watcher"] = w
            except Exception:
                pass
        threading.Thread(target=start_watch, daemon=True).start()

    def open_external(path):
        """Another program asked us to show a folder (or a file's folder)."""
        path = os.path.normpath(path)
        if os.path.isdir(path):
            navigate(path)
        elif os.path.exists(path):
            navigate(os.path.dirname(path), select=path)

    if Sh and background:
        def on_ext_drop(paths, move):
            if X.zip_is_virtual(st["cwd"]):
                root.after(0, status.set, "Can't drop files into an archive")
            else:
                root.after(0, lambda: run_transfer(paths, st["cwd"], move))

        try:
            st["droptarget"] = Sh.DropTarget(on_ext_drop)
            if not st["droptarget"].register(Sh.hwnd_of(root)):
                log_error("RegisterDragDrop failed")
        except Exception as e:  # noqa
            log_error(f"drop target: {e}")

    # ======================================================== show / hide (hotkey)
    def summon():
        root.deiconify()
        root.state("normal")
        root.attributes("-topmost", True)
        root.attributes("-topmost", False)
        root.lift()
        root.focus_force()
        entry.focus_set()
        entry.select_range(0, "end")

    if background:
        listen_for_show(lambda p=None: root.after(0, lambda: (summon(), p and open_external(p))))
        label = register_hotkey(lambda: root.after(0, summon))
        st["hk"] = label or "no hotkey (combos taken; run --hotkey ctrl+alt+x)"
        if Sh and cfg["win_e"]:
            try:
                st["wine"] = Sh.WinEHook(lambda: root.after(0, summon))
                if st["wine"].start():
                    st["hk"] += " / Win+E"
                else:
                    log_error("Win+E hook could not be installed")
            except Exception as e:  # noqa
                log_error(f"Win+E hook: {e}")
        tray = start_tray(lambda: root.after(0, summon), lambda: root.after(0, root.destroy))
        # with a tray icon the X button hides to tray; without one it really quits
        root.protocol("WM_DELETE_WINDOW", root.withdraw if tray else root.destroy)
        if not label:
            root.after(500, lambda: messagebox.showwarning(
                "Foldwise", "Couldn't register a global hotkey (all candidates taken). "
                "Pick another with:  python foldwise.py --hotkey ctrl+alt+x"))

    for _, _t in pane_frames:
        _t.tag_configure("alt", background=T["alt"] if cfg.get("zebra", True) else T["bg"])
        _t.tag_configure("dir", foreground=T["dir"])
        _t.tag_configure("drop", background=T["sel"])
    if not cfg["frec"] and cfg["visits"]:  # one-time migration from the old "every folder" tracking
        _now = time.time()
        cfg["frec"] = {p_: [min(c_, 5) * 0.6, _now - 2 * 86400] for p_, c_ in cfg["visits"].items() if os.path.isdir(p_)}
    if cfg["restore_tabs"] and cfg["tabs"]:
        ok_ = [p for p in cfg["tabs"] if os.path.isdir(p)]
        if ok_:
            tabs[:] = [{"cwd": p, "hist": [p], "pos": 0} for p in ok_]
            cur["i"] = max(0, min(cfg["tab_i"], len(ok_) - 1))
            t0_ = tabs[cur["i"]]
            st.update(cwd=t0_["cwd"], hist=t0_["hist"], pos=0)
            pathv.set(t0_["cwd"])
    build_sidebar()
    build_crumbs()
    build_tabs()
    update_headings()
    sync_chips()
    if cfg["details_open"]:
        det.pack(side="right", fill="y", before=mid)
        details_btn.configure(style="On.TButton")
    refresh()
    tree.focus_set()
    root.after(20000, watch_drives)
    if not meta("count"):
        root.after(300, start_index)
    if open_path:
        root.after(300, lambda: open_external(open_path))
    if hidden and background:
        root.withdraw()
    root._ff = locals()  # full snapshot for tests
    root.mainloop()



def selftest():
    """--selftest: prove that this build (source or packaged exe) has everything it needs. Writes the result to
    %TEMP%\\foldwise-selftest.txt (a packaged exe has no console) and returns the exit code."""
    import importlib
    import tempfile
    problems = []
    for mod in ("ff_core", "ff_extras", "ff_index", "ff_clean", "ff_health", "ff_shell", "ff_ocr", "ff_update", "ui_health", "ui_cleaner",
                "ui_tools", "ui_settings", "ui_preview", "ui_grid", "ui_dragselect", "ui_fileops", "ui_nav", "ui_toolbar", "ui_about",
                "ff_malware", "ff_share", "ff_vault", "ff_notify", "ff_elevated", "ff_support", "ui_malware", "ui_pages", "ui_extras", "ui_tour", "ui_browse", "ui_more", "ui_games", "ui_picker", "ff_platform", "tkinter", "PIL.Image", "pypdf", "pypdfium2", "paramiko",
                "cryptography.hazmat.primitives.ciphers.aead", "winrt.windows.media.ocr"):
        try:
            importlib.import_module(mod)
        except Exception as e:  # noqa
            problems.append(f"{mod}: {e}")
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.Error as e:
        problems.append(f"sqlite fts5: {e}")
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.destroy()
    except Exception as e:  # noqa
        problems.append(f"tk: {e}")
    import ff_update
    text = f"Foldwise {ff_update.APP_VERSION} ({ff_update.mode()})\n" + ("OK\n" if not problems else "PROBLEMS:\n" + "\n".join(problems) + "\n")
    Path(tempfile.gettempdir(), "foldwise-selftest.txt").write_text(text, encoding="utf-8")
    print(text)
    return 1 if problems else 0


def main(a):
    import ff_update
    if ff_update.boot_check() == "rolled back":  # a new version that kept failing was replaced by the previous one
        ff_update.restart_app()
        return
    ff_core.migrate_shortcuts()  # FileFinder -> Foldwise: replace the old shortcuts once
    ff_core.heal_default_folder_opener()  # Foldwise deleted/moved while it was the default folder opener: give folders back to Explorer
    ff_update.cleanup_old()  # leftovers of a live update (the old exe that kept running while the new one was installed)
    if "--version" in a:
        print(f"Foldwise {ff_update.APP_VERSION}")
    elif "--selftest" in a:
        sys.exit(selftest())
    elif "--index" in a:
        t0 = time.time()
        n = build_index(fixed_drives(), lambda n, p: print(f"\r{n:,} items  {p[:70]:<70}", end=""))
        print(f"\nDone: {n:,} items in {time.time() - t0:.0f}s")
    elif "--search" in a:
        c = connect()
        for name, path, size, mtime, isdir in search(c, a[a.index("--search") + 1], 50):
            print(path)
    elif "--install" in a:
        if ff_update.frozen():
            dest = a[a.index("--install-dir") + 1] if "--install-dir" in a else None
            exe = ff_update.install(dest, autostart="--no-autostart" not in a, shortcuts="--no-shortcuts" not in a)
            print(f"Installed to {exe}. Start Foldwise from the Start menu.")
        else:
            make_shortcut(shortcut_paths()[0])
            print("Start menu shortcut created. Launch 'Foldwise' once, then use your hotkey.")
    elif "--uninstall" in a:
        ff_update.uninstall(remove_data="--remove-data" in a)
        print("Foldwise will be removed when this window closes. Your settings were kept." if "--remove-data" not in a else "Foldwise and its data will be removed.")
    elif "--autostart" in a:
        make_shortcut(shortcut_paths()[1], "--hidden")
        print("Foldwise will now start (hidden-in-background) at login.")
    elif "--remove-autostart" in a:
        shortcut_paths()[1].unlink(missing_ok=True)
        print("Autostart removed.")
    elif "--hotkey" in a:
        spec = a[a.index("--hotkey") + 1]
        parse_hotkey(spec)
        save_config(hotkey=spec)
        print("Hotkey set to", spec, "- quit Foldwise from the tray icon and relaunch to apply.")
    elif "--set-default-folder-opener" in a:
        set_default_folder_opener(True)
        print("Done. Programs that open a folder via Windows now open it in Foldwise.")
        print("Undo any time with:  Foldwise.exe --restore-default-folder-opener")
    elif "--restore-default-folder-opener" in a:
        set_default_folder_opener(False)
        print("Done. Explorer opens folders again.")
    else:
        path_arg = next((x for x in a[1:] if not x.startswith("--")), None)
        if path_arg and not os.path.exists(path_arg):  # e.g. "This PC": Explorer keeps those
            subprocess.Popen(["explorer.exe", path_arg])
            sys.exit(0)
        run_gui(background="--no-background" not in a, hidden="--hidden" in a, open_path=path_arg)


if __name__ == "__main__":
    main(sys.argv)
