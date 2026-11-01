"""About window: version, install / uninstall, update checks and updating from a file.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import os
import threading
import time
import tkinter as tk
import ui_pages
from tkinter import ttk

import ff_update
from ff_core import ThemedBox as messagebox, T, DB_DIR, human_size, make_shortcut, shortcut_paths


def open_about(A):
    win = A.toplevel("About Foldwise", "700x640")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    f = ttk.Frame(win, padding=20)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text=f"Foldwise {ff_update.APP_VERSION}", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    exe = ff_update.exe_path()
    where = f"{exe}" if exe else "running from source (python foldwise.py)"
    ttk.Label(f, text=f"Mode: {ff_update.mode()}\nProgram: {where}\nYour data: {DB_DIR}", style="DetKey.TLabel", background=T["bg"],
              justify="left", wraplength=640).pack(anchor="w", pady=(6, 14))
    msg = tk.StringVar(value="")

    # ---- installation
    ttk.Label(f, text="Installation", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    box = ttk.Frame(f)
    box.pack(fill="x", pady=(4, 12))

    def do_install():
        if not messagebox.askyesno("Install", f"Copy Foldwise to\n{ff_update.INSTALL_DIR}\n\nand add Start-menu and start-with-Windows shortcuts?\n"
                                   "(Nothing is changed in the registry.)", parent=win):
            return
        try:
            target = ff_update.install()
            msg.set(f"Installed: {target}. From now on start it from the Start menu.")
        except Exception as e:  # noqa
            msg.set(f"Install failed: {e}")

    def do_uninstall():
        if messagebox.askyesno("Uninstall", "Remove the shortcuts and the installed program?\nYour settings and index are kept.", parent=win):
            ff_update.uninstall()
            msg.set("Foldwise will disappear when you close it. Settings were kept.")
            A.root.after(800, A.root.destroy)

    if ff_update.frozen() and not ff_update.is_installed():
        ttk.Button(box, text="Install on this PC", style="Accent.TButton", command=do_install).pack(side="left")
    if ff_update.is_installed():
        ttk.Button(box, text="Uninstall…", command=do_uninstall).pack(side="left")
    if not ff_update.frozen():
        ttk.Label(box, text="Install and update need the packaged Foldwise.exe.", style="DetKey.TLabel", background=T["bg"]).pack(side="left")

    login = tk.BooleanVar(value=shortcut_paths()[1].exists())

    def toggle_login():
        try:
            if login.get():
                make_shortcut(shortcut_paths()[1], "--hidden")
            else:
                shortcut_paths()[1].unlink(missing_ok=True)
        except Exception as e:  # noqa
            msg.set(f"Couldn't change that: {e}")
    ttk.Checkbutton(f, text="Start Foldwise (hidden, in the tray) when I sign in to Windows", variable=login, command=toggle_login).pack(anchor="w", pady=(0, 14))

    # ---- updates
    ttk.Label(f, text="Updates", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    ttk.Label(f, text="Update source: your GitHub repository as owner/name (for example yourname/foldwise): Foldwise then looks at the latest "
              "release there. You can also paste the address of an update.json. Nothing is downloaded without your OK, and every download "
              "is checked against its SHA-256 before it is used." + ("  Running from a Git checkout: use 'Update from Git'." if ff_update.source_dir() else ""),
              wraplength=640, style="DetKey.TLabel", background=T["bg"]).pack(anchor="w", pady=(2, 6))
    url_v = tk.StringVar(value=A.cfg["update_url"])
    ttk.Entry(f, textvariable=url_v).pack(fill="x")
    ub = ttk.Frame(f)
    ub.pack(fill="x", pady=8)
    pb = ttk.Progressbar(f, mode="determinate", maximum=100)

    def check():
        A.save_cfg(update_url=url_v.get().strip())
        msg.set("Checking…")

        def work():
            try:
                info = ff_update.check_update(url_v.get().strip())
                err = None
            except Exception as e:  # noqa
                info, err = None, e
            A.root.after(0, lambda: alive["v"] and found(info, err))
        threading.Thread(target=work, daemon=True).start()

    def found(info, err):
        A.save_cfg(last_update_check=time.time())
        if err:
            msg.set(f"Couldn't check: {err}")
        elif not info:
            msg.set(f"You have the newest version ({ff_update.APP_VERSION}).")
        else:
            msg.set(f"Version {info['version']} is available. " + (info.get("notes") or ""))
            if ff_update.frozen() and messagebox.askyesno("Update", f"Download and install Foldwise {info['version']}?\nFoldwise will restart.", parent=win):
                download(info)

    def download(info):
        pb.pack(fill="x")

        def work():
            try:
                path = ff_update.download_update(info, lambda d, t: alive["v"] and A.root.after(0, lambda: pb.configure(value=100 * d / t if t else 0)))
                err = None
            except Exception as e:  # noqa
                path, err = None, e
            A.root.after(0, lambda: done(path, err))

        def done(path, err):
            if err:
                msg.set(f"Update failed: {err}")
                return
            installed(ff_update.apply_update_live(path), info["version"])
        threading.Thread(target=work, daemon=True).start()

    def git_update():
        d = ff_update.source_dir()
        msg.set("Checking Git…")

        def work():
            try:
                behind, log = ff_update.git_check(d)
                err = None
            except Exception as e:  # noqa
                behind, log, err = 0, "", e
            A.root.after(0, lambda: alive["v"] and got(behind, log, err))

        def got(behind, log, err):
            A.save_cfg(last_update_check=time.time())
            if err:
                msg.set(f"Couldn't check Git: {err}")
            elif not behind:
                msg.set("This checkout is up to date with its Git remote.")
            else:
                msg.set(f"{behind} new commit(s) on the remote:\n{log}")
                if messagebox.askyesno("Update from Git", f"Pull {behind} new commit(s)?\n\n{log}\n\nOnly fast-forwards: your own edits are never touched.", parent=win):
                    pull()

        def pull():
            def run():
                try:
                    ff_update.git_pull(d)
                    err = None
                except Exception as e:  # noqa
                    err = e
                A.root.after(0, lambda: alive["v"] and (msg.set(f"Update failed: {err}") if err else (msg.set("Updated from Git."), restart_prompt(A, win))))
            threading.Thread(target=run, daemon=True).start()
        threading.Thread(target=work, daemon=True).start()

    def installed(path, version):
        msg.set("The update is installed. You can keep working: it starts the next time Foldwise starts.")
        restart_prompt(A, win)

    def from_file():
        from ui_picker import filedialog
        p = filedialog.askopenfilename(parent=win, filetypes=[("Foldwise program", "*.exe")])
        if not p:
            return
        if not ff_update.frozen():
            msg.set("Updating from a file only works for the packaged Foldwise.exe.")
            return
        if messagebox.askyesno("Update", f"Replace this Foldwise with\n{p}\n\nOnly use a file you got from a source you trust.", parent=win):
            try:
                import shutil
                tmp = os.path.join(os.environ.get("TEMP", "."), "Foldwise-update-from-file.exe")
                shutil.copy2(p, tmp)
                installed(ff_update.apply_update_live(tmp), "")
            except Exception as e:  # noqa
                msg.set(f"Update failed: {e}")

    ttk.Button(ub, text="Check for updates", style="Accent.TButton", command=check).pack(side="left")
    if ff_update.source_dir():
        ttk.Button(ub, text="Update from Git", command=git_update).pack(side="left", padx=8)
    ttk.Button(ub, text="Update from a file…", command=from_file).pack(side="left", padx=8)
    ttk.Button(ub, text="Restart Foldwise", command=lambda: restart_prompt(A, win)).pack(side="left", padx=8)
    ttk.Button(ub, text="Storage & index\u2026", command=lambda: A.open_storage()).pack(side="left")
    ttk.Button(ub, text="Problem report\u2026", command=lambda: A.make_problem_report()).pack(side="left", padx=8)
    ttk.Label(f, textvariable=msg, wraplength=640).pack(anchor="w", pady=6)
    ttk.Button(f, text="Close", command=win.destroy).pack(anchor="e", side="bottom")


def restart_prompt(A, parent=None):
    """Offer to restart now. Your tabs, settings and index are kept; the file operations in progress are NOT, so ask first."""
    if messagebox.askyesno("Restart Foldwise", "Restart now to use the newest version?\n\nYour open tabs come back automatically. "
                           "Nothing running (copying, backups) will be interrupted if you choose No \u2014 it simply starts "
                           "with the new version next time.", parent=parent or A.root):
        A.app_restart()


def update_tick(A):
    """Once a week look for a newer version (GitHub release, or the Git remote when running from a checkout) and say so with a toast."""
    A.root.after(6 * 3600 * 1000, lambda: update_tick(A))
    d = ff_update.source_dir()
    url = ff_update.manifest_url(A.cfg["update_url"])
    if (not d and not url) or time.time() - A.cfg["last_update_check"] < 6.5 * 86400:
        return

    def work():
        try:
            if d:
                behind, _log = ff_update.git_check(d)
                text = f"Foldwise has {behind} new commit(s) on Git." if behind else None
            else:
                info = ff_update.check_update(url)
                text = f"Foldwise {info['version']} is available (you have {ff_update.APP_VERSION})." if info else None
        except Exception:
            return
        A.root.after(0, lambda: A.save_cfg(last_update_check=time.time()))
        if text:
            A.root.after(0, lambda: A.show_toast(text, "Open About", "about"))
    threading.Thread(target=work, daemon=True).start()


def problem_report(A):
    import ff_support
    try:
        z = ff_support.make_report()
        messagebox.showinfo("Problem report", f"Saved on your Desktop:\n{z}\n\nIt has the version, system info, the error log and your settings "
                            "(keys and folder lists are hidden). Send it to whoever helps you.", parent=A.root)
    except Exception as e:  # noqa
        messagebox.showerror("Problem report", str(e), parent=A.root)


def open_storage(A):
    """What Foldwise stores on disk, with tools to shrink it."""
    import ff_support
    win = A.toplevel("Storage & index", "700x560")
    alive = {"v": True, "busy": False}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    f = ttk.Frame(win, padding=18)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text="Everything Foldwise keeps on this PC (all of it can be rebuilt; none of it is your files).", wraplength=640).pack(anchor="w", pady=(0, 8))
    tv = ttk.Treeview(f, columns=("size",), show="tree headings", height=10)
    tv.heading("#0", text="What", anchor="w")
    tv.heading("size", text="Size", anchor="e")
    tv.column("#0", width=420)
    tv.column("size", width=140, anchor="e")
    tv.pack(fill="x")
    msg = tk.StringVar(value="")
    ttk.Label(f, textvariable=msg, wraplength=640).pack(anchor="w", pady=10)

    def fill():
        tv.delete(*tv.get_children())
        rows = ff_support.storage_report()
        for label, size in rows:
            tv.insert("", "end", text=label, values=(human_size(size),))
        tv.insert("", "end", text="Total", values=(human_size(sum(s for _, s in rows)),))

    def compact():
        if alive["busy"] or not messagebox.askyesno("Compact", "Shrink the content search index now?\nIt needs free disk space about as big as the index and can take several minutes; searching still works meanwhile.", parent=win):
            return
        alive["busy"] = True
        msg.set("Compacting\u2026 please keep Foldwise open.")

        def work():
            try:
                b, a = ff_support.compact_content_index()
                text = f"Done: {human_size(b)} \u2192 {human_size(a)}."
            except Exception as e:  # noqa
                text = f"Couldn't compact: {e}"
            alive["busy"] = False
            A.root.after(0, lambda: alive["v"] and (msg.set(text), fill()))
        threading.Thread(target=work, daemon=True).start()

    def clear_thumbs():
        import shutil
        shutil.rmtree(DB_DIR / "thumbs", ignore_errors=True)
        msg.set("Thumbnail cache cleared (it refills as you browse).")
        fill()

    def rebuild():
        if messagebox.askyesno("Rebuild", "Throw away the content search index and build it again from scratch? Searching file contents is limited until it finishes (it runs in the background).", parent=win):
            try:
                for n in ("content.db", "content.db-wal", "content.db-shm"):
                    (DB_DIR / n).unlink(missing_ok=True)
            except OSError as e:
                msg.set(f"Couldn't remove the old index (is it busy?): {e}")
                return
            A.start_content_index(True)
            msg.set("Rebuilding in the background.")
            fill()
    def drop():
        if messagebox.askyesno("Delete the content index", "Delete the content search index to free its disk space?" + chr(10) * 2 + "Searching INSIDE documents (content:) stops working until you turn it on and let it rebuild. Your files are not touched.", parent=win):
            try:
                for n in ("content.db", "content.db-wal", "content.db-shm"):
                    (DB_DIR / n).unlink(missing_ok=True)
            except OSError as e:
                msg.set(f"Couldn't remove it (is it busy? turn content search off, restart Foldwise and try again): {e}")
                return
            msg.set("Content index deleted.")
            fill()
    bt = ttk.Frame(f)
    bt.pack(fill="x")
    ttk.Button(bt, text="Compact content index", style="Accent.TButton", command=compact).pack(side="left")
    ttk.Button(bt, text="Delete content index…", command=drop).pack(side="left", padx=(8, 0))
    ttk.Button(bt, text="Clear thumbnail cache", command=clear_thumbs).pack(side="left", padx=8)
    ttk.Button(bt, text="Rebuild content index\u2026", command=rebuild).pack(side="left")
    ttk.Button(f, text="Close", command=win.destroy).pack(anchor="e", side="bottom")
    fill()


def open_notify(A):
    """Where to send weekly check-ups and important warnings besides the pop-up on this PC (your phone via ntfy, Discord, ...)."""
    import ff_notify
    win = A.toplevel("Phone notifications", "720x420")
    f = ttk.Frame(win, padding=20)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text="Foldwise can also send its weekly check-up and malware warnings to your phone. The easiest free way: install the ntfy app, "
              "subscribe to a topic name only you know (e.g. foldwise-yourname-1234), and enter  https://ntfy.sh/<that topic>  below. "
              "A Discord channel webhook address works too. Only the short message text is sent.", wraplength=670).pack(anchor="w")
    url = tk.StringVar(value=A.cfg["notify_url"])
    ttk.Entry(f, textvariable=url).pack(fill="x", pady=12)
    msg = tk.StringVar(value="")

    def test():
        A.save_cfg(notify_url=url.get().strip())
        try:
            code = ff_notify.send(url.get(), "Foldwise", "Test message: notifications work.")
            msg.set(f"Sent (server answered {code}). Check your phone.")
        except Exception as e:  # noqa
            msg.set(f"Couldn't send: {e}")
    bt = ttk.Frame(f)
    bt.pack(fill="x")
    ttk.Button(bt, text="Save and send a test", style="Accent.TButton", command=test).pack(side="left")
    ttk.Button(bt, text="Remove", command=lambda: (url.set(""), A.save_cfg(notify_url=""), msg.set("Notifications to the phone are off."))).pack(side="left", padx=8)
    ttk.Label(f, textvariable=msg, wraplength=670).pack(anchor="w", pady=10)
    br = ttk.Frame(f)
    br.pack(anchor="e", side="bottom")
    ttk.Button(br, text="Tutorial", command=lambda: A.open_howto("notify")).pack(side="left", padx=8)
    ttk.Button(br, text="Close", command=win.destroy).pack(side="left")


SETUP_OPTIONS = [  # (config key, label, hint) - everything except plain filename indexing starts OFF; this wizard asks once
    ("live_index", "Keep the search index up to date live", "Files you create or rename show up in search at once. Needs a restart."),
    ("content_index", "Search inside documents (content: / in:)", "Reads Word, PDF, text files... Uses more disk and CPU while indexing."),
    ("ocr_pdfs", "Also read scanned PDFs (OCR)", "Slow; only useful if you have scanned documents."),
    ("folder_sizes", "Show folder sizes", "Calculates the size of every folder in the list."),
    ("details_open", "Show the details pane on the right", "Preview and info of the selected file (F3 toggles it)."),
    ("restore_tabs", "Reopen my tabs when Foldwise starts", ""),
    ("sidebar_recent", "Show recent / frequent folders and recent files in the sidebar", ""),
    ("real_icons", "Use real Windows file icons", "Off = simple built-in icons."),
    ("confirm_delete", "Ask before deleting", "Recommended: keeps deletions from happening by accident."),
    ("win_e", "Win+E opens Foldwise instead of Explorer", "Needs a restart."),
    ("remember_window", "Remember the window size and position", ""),
    ("health_alerts", "Warn me about low disk space and overdue backups", "A small pop-up, at most hourly."),
    ("weekly_summary", "Weekly PC health summary", "One notification a week with your score."),
    ("malware_weekly", "Weekly malware deep check", "Looks for suspicious startup entries and programs."),
]


def welcome(A, rerun=False):
    """First start (or Customize > Setup wizard): choose what is on. Everything except filename indexing starts off."""
    if A.root.state() == "withdrawn":  # started hidden in the tray: bring the window up for the wizard
        A.root.deiconify()
    win = A.toplevel("Setup" if rerun else "Welcome to Foldwise", "700x680", tab=False)
    f = ttk.Frame(win, padding=24)
    f.pack(fill="both", expand=True)
    bottom = ttk.Frame(f)
    bottom.pack(side="bottom", fill="x", pady=(12, 0))
    ttk.Label(f, text="Set up Foldwise", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(f, text="Only fast file-name search is always on. Tick what you want; you can change all of this later in Customize.",
              wraplength=640).pack(anchor="w", pady=(6, 10))
    box = ttk.Frame(f)
    box.pack(fill="both", expand=True)
    cv = tk.Canvas(box, bg=T["bg"], highlightthickness=0)
    sb = ttk.Scrollbar(box, orient="vertical", command=cv.yview)
    inner = ttk.Frame(cv)
    cv.create_window(0, 0, window=inner, anchor="nw")
    cv.configure(yscrollcommand=sb.set)
    inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
    ui_pages.register_scroll(A.root, cv)
    sb.pack(side="right", fill="y")
    cv.pack(side="left", fill="both", expand=True)
    vars_ = {}
    for key, label, hint in SETUP_OPTIONS:
        vars_[key] = tk.BooleanVar(value=bool(A.cfg.get(key)) if (rerun or A.cfg.get("welcomed")) else key in ("confirm_delete", "real_icons", "live_index"))  # existing users see what they have now
        ttk.Checkbutton(inner, text=label, variable=vars_[key]).pack(anchor="w", pady=(7, 0))
        if hint:
            ttk.Label(inner, text=hint, style="DetKey.TLabel", background=T["bg"]).pack(anchor="w", padx=26)
    ttk.Separator(inner).pack(fill="x", pady=10)
    login = tk.BooleanVar(value=False)
    check = tk.BooleanVar(value=False)
    ttk.Checkbutton(inner, text="Start Foldwise in the tray when I sign in (Ctrl+Alt+F and search always ready)", variable=login).pack(anchor="w", pady=3)
    if not rerun:
        ttk.Checkbutton(inner, text="Run a first health check now (about 20 seconds)", variable=check).pack(anchor="w", pady=3)
    inst = tk.BooleanVar(value=False)
    if ff_update.frozen() and not ff_update.is_installed():
        ttk.Checkbutton(inner, text="Install Foldwise on this PC (Start-menu entry; no registry changes)", variable=inst).pack(anchor="w", pady=3)
    msg = tk.StringVar()
    ttk.Label(bottom, textvariable=msg, wraplength=560).pack(side="left")

    def go():
        try:
            if inst.get():
                ff_update.install(autostart=login.get())
            elif login.get():
                make_shortcut(shortcut_paths()[1], "--hidden")
        except Exception as e:  # noqa
            msg.set(f"Couldn't set that up: {e}")
            return
        A.save_cfg(setup_done=True, welcomed=True, **{k: v.get() for k, v in vars_.items()})
        win.destroy()
        A.status.set("Setup saved. Win+E / index / OCR changes apply after a restart.")
        if check.get():
            A.open_health()
        elif A.cfg.get("show_tutorial", True) and not rerun:
            A.open_tutorial()
    ttk.Button(bottom, text="Save", style="Accent.TButton", command=go).pack(side="right")
    win.protocol("WM_DELETE_WINDOW", lambda: (A.save_cfg(setup_done=True, welcomed=True), win.destroy(),
                                              A.open_tutorial() if (A.cfg.get("show_tutorial", True) and not rerun) else None))
