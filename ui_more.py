"""Smart collections, folder size history and the crash check (added in 1.3.0).

Every function takes `A` first: a live view of the main window (ff_app.App).
"""
import os
import threading
import time
import tkinter as tk
from tkinter import ttk
from ui_picker import filedialog

import ff_core
import ff_health as HL
import ff_support
import ui_alerts
import ui_pages
from ff_core import T, ThemedAsk as simpledialog, ThemedBox as messagebox, human_size, log_error, low_priority

# (name, what it finds, search text): searches the user would otherwise have to type; they run in the normal file view
COLLECTIONS = [
    ("Recent photos", "Pictures from the last 30 days", "ext:jpg,jpeg,png,heic,webp,gif modified:30"),
    ("Screenshots", "Files with 'screenshot' in the name", "screenshot ext:png,jpg,jpeg"),
    ("Documents this week", "PDFs, Office files and text changed in 7 days", "ext:pdf,doc,docx,txt,md,xls,xlsx,ppt,pptx modified:7"),
    ("Big files", "Everything over 500 MB", "size:>500mb type:file"),
    ("Videos", "Video files over 50 MB", "ext:mp4,mkv,avi,mov,webm size:>50mb"),
    ("Music", "Audio files", "ext:mp3,flac,wav,ogg,m4a,aac"),
    ("Installers and disk images", "Setup programs you may no longer need", "ext:exe,msi,iso,msix"),
    ("Archives", "zip, rar, 7z, tar and friends", "ext:zip,rar,7z,tar,gz"),
    ("Changed today", "Everything touched in the last day", "modified:1"),
    ("Code this month", "Source files changed in 30 days", "ext:py,js,ts,cs,java,cpp,c,rs,go modified:30"),
    ("Spreadsheets", "Excel and CSV files", "ext:xlsx,xls,csv,ods"),
    ("Tiny files", "Files under 1 KB (often leftovers)", "size:<1kb type:file"),
]


def _go(A, query):
    ui_pages.show_files(A)
    A.q.set(query)


def open_collections(A):
    """Ready-made searches, plus your saved ones (rename / delete)."""
    win = A.toplevel("Smart collections", "980x680")
    tk.Label(win, text="Smart collections", bg=T["bg"], fg=T["fg"], font=("Segoe UI", A.cfg["font_size"] + 6, "bold")).pack(anchor="w", padx=22, pady=(18, 2))
    tk.Label(win, text="One click runs the search in the file view. They look at the whole index, so they stay current by themselves.",
             bg=T["bg"], fg=T["muted"], font=("Segoe UI", A.cfg["font_size"])).pack(anchor="w", padx=22, pady=(0, 10))
    grid = tk.Frame(win, bg=T["bg"])
    grid.pack(fill="x", padx=16)
    cols = 3
    for c in range(cols):
        grid.columnconfigure(c, weight=1, uniform="col")
    for i, (name, desc, query) in enumerate(COLLECTIONS):
        card = tk.Frame(grid, bg=T["raised"], cursor="hand2", padx=14, pady=10)
        card.grid(row=i // cols, column=i % cols, sticky="nsew", padx=6, pady=6)
        a = tk.Label(card, text=name, bg=T["raised"], fg=T["fg"], font=("Segoe UI", A.cfg["font_size"], "bold"), anchor="w")
        b = tk.Label(card, text=desc, bg=T["raised"], fg=T["muted"], font=("Segoe UI", A.cfg["font_size"] - 1), anchor="w", justify="left", wraplength=250)
        a.pack(fill="x")
        b.pack(fill="x")
        for w in (card, a, b):
            w.bind("<Button-1>", lambda e, q=query: _go(A, q))
    saved = tk.Frame(win, bg=T["bg"])
    saved.pack(fill="both", expand=True, padx=22, pady=(14, 8))

    def draw_saved():
        for w in saved.winfo_children():
            w.destroy()
        tk.Label(saved, text="YOUR SAVED SEARCHES", bg=T["bg"], fg=T["muted"], font=("Segoe UI", A.cfg["font_size"] - 2, "bold")).pack(anchor="w", pady=(0, 6))
        if not A.cfg["saved"]:
            tk.Label(saved, text="None yet: type a search and press the ★ Save button next to the search box.", bg=T["bg"], fg=T["muted"],
                     font=("Segoe UI", A.cfg["font_size"])).pack(anchor="w")
            return
        for name, query in list(A.cfg["saved"].items()):
            row = tk.Frame(saved, bg=T["bg"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=name, bg=T["bg"], fg=T["fg"], font=("Segoe UI", A.cfg["font_size"], "bold"), width=24, anchor="w").pack(side="left")
            tk.Label(row, text=query, bg=T["bg"], fg=T["muted"], font=("Segoe UI", A.cfg["font_size"]), anchor="w").pack(side="left", padx=8)
            ttk.Button(row, text="Delete", command=lambda n=name: delete(n)).pack(side="right")
            on = tk.BooleanVar(master=row, value=ui_alerts.enabled(A, name))
            ttk.Checkbutton(row, text="Alert me about new files", variable=on, command=lambda n=name: ui_alerts.toggle(A, n)).pack(side="right", padx=6)
            ttk.Button(row, text="Rename", command=lambda q=query: (rename_saved(A, q), draw_saved())).pack(side="right", padx=6)
            ttk.Button(row, text="Open", command=lambda q=query: _go(A, q)).pack(side="right")

    def delete(name):
        if messagebox.askyesno("Delete saved search", f"Delete the saved search “{name}”?", parent=A.root):
            A.save_cfg(saved={k: v for k, v in A.cfg["saved"].items() if k != name})
            A.build_sidebar()
            draw_saved()
    draw_saved()


def rename_saved(A, query):
    """Give the saved search with this search text a new name (keeps the order)."""
    old = next((k for k, v in A.cfg["saved"].items() if v == query), None)
    if old is None:
        return
    new = simpledialog.askstring("Rename saved search", "New name:", initialvalue=old, parent=A.root)
    if not new or not new.strip() or new.strip() == old:
        return
    new = new.strip()
    A.save_cfg(saved={(new if k == old else k): v for k, v in A.cfg["saved"].items()})
    ui_alerts.renamed(A, old, new)
    A.build_sidebar()


# ------------------------------------------------------------------------------------------------ folder size history
def _track_path(A):
    return os.path.join(os.path.dirname(str(A.hist_path)), "foldertrack.json")


def _plus(n):
    return ("+" if n > 0 else "-" if n < 0 else "") + human_size(abs(n)) if n else "no change"


def open_folder_history(A):
    """Follow folders you care about: Pinefiles measures them now and then weekly (while you're away) and draws how they grow."""
    win = A.toplevel("Folder size history", "1000x680")
    tp = _track_path(A)
    data = HL.track_load(tp)
    msg = tk.StringVar()
    ttk.Label(win, text="Follow a folder and Pinefiles measures it now and then once a week while you're away. The line shows how its size changes. "
              "Reading only: nothing is touched.", wraplength=900, padding=(18, 14, 18, 4)).pack(fill="x")
    ttk.Label(win, textvariable=msg, padding=(18, 0)).pack(fill="x")
    bt = ttk.Frame(win, padding=(14, 10))
    bt.pack(side="bottom", fill="x")
    body = tk.Frame(win, bg=T["bg"])
    body.pack(fill="both", expand=True, padx=14, pady=(6, 0))
    tv = ttk.Treeview(body, columns=("now", "chg", "n"), show="tree headings", selectmode="browse", height=7)
    for c, text, w, anc in (("#0", "Folder", 420, "w"), ("now", "Size now", 110, "e"), ("chg", "Change in 30 days", 150, "e"), ("n", "Measurements", 110, "e")):
        tv.heading(c, text=text, anchor=anc)
        tv.column(c, width=w, anchor=anc, stretch=(c == "#0"))
    tv.pack(fill="x")
    cv = tk.Canvas(body, bg=T["bg"], highlightthickness=0, height=300)
    cv.pack(fill="both", expand=True, pady=(8, 0))
    busy = {"n": 0}

    def refresh():
        keep = tv.selection()
        tv.delete(*tv.get_children())
        for folder, samples in data["samples"].items():
            now, chg = HL.track_change(samples)
            tv.insert("", "end", iid=folder, text=folder, values=(human_size(now), "-" if chg is None else _plus(chg), len(samples)))
        if keep and tv.exists(keep[0]):
            tv.selection_set(keep[0])
        elif tv.get_children():
            tv.selection_set(tv.get_children()[0])
        msg.set("" if data["samples"] else "No folder is followed yet. Open a folder, then press “Follow the current folder”.")
        draw()

    def draw(*_):
        cv.delete("all")
        w, h = max(cv.winfo_width(), 300), max(cv.winfo_height(), 120)
        sel = tv.selection()
        if not sel:
            return
        s = data["samples"].get(sel[0], [])
        if len(s) < 2:
            cv.create_text(w // 2, h // 2, fill=T["muted"], font=("Segoe UI", A.cfg["font_size"]), width=w - 80, justify="center",
                           text=(f"{len(s)} measurement so far. The line appears after the next one (weekly while you're away, "
                                 "or press “Measure now”)."))
            return
        left, right, top, bot = 84, w - 24, 18, h - 34
        ts, vs = [x[0] for x in s], [x[1] for x in s]
        lo, hi = min(vs), max(vs)
        if hi == lo:
            hi = lo + 1
        t0, t1 = ts[0], max(ts[-1], ts[0] + 1)
        pts = []
        for t, v in zip(ts, vs):
            pts += [left + (right - left) * (t - t0) / (t1 - t0), bot - (bot - top) * (v - lo) / (hi - lo)]
        cv.create_line(left, top, left, bot, right, bot, fill=T["line"])
        cv.create_text(left - 8, top, text=human_size(hi), anchor="e", fill=T["muted"], font=("Segoe UI", 9))
        cv.create_text(left - 8, bot, text=human_size(lo), anchor="e", fill=T["muted"], font=("Segoe UI", 9))
        cv.create_text(left, bot + 16, text=time.strftime("%d %b %Y", time.localtime(t0)), anchor="w", fill=T["muted"], font=("Segoe UI", 9))
        cv.create_text(right, bot + 16, text=time.strftime("%d %b %Y", time.localtime(ts[-1])), anchor="e", fill=T["muted"], font=("Segoe UI", 9))
        cv.create_line(*pts, fill=T["accent"], width=2, smooth=False)
        for i in range(0, len(pts), 2):
            cv.create_oval(pts[i] - 3, pts[i + 1] - 3, pts[i] + 3, pts[i + 1] + 3, fill=T["accent"], outline="")

    def measure(folders):
        folders = [f for f in folders if os.path.isdir(f)]
        if not folders:
            return
        busy["n"] += 1
        msg.set(f"Measuring {len(folders)} folder(s)…")

        def work():
            low_priority()
            out = []
            for f in folders:
                size = HL.track_measure(f, cancel=lambda: not win.winfo_exists(), pause=0.001)
                if size is not None:
                    out.append((f, size))
            try:
                A.root.after(0, lambda: done(out))
            except (RuntimeError, tk.TclError):
                pass
        threading.Thread(target=work, daemon=True).start()

    def done(out):
        busy["n"] -= 1
        fresh = HL.track_load(tp)  # another tick may have added samples meanwhile
        for f, size in out:
            if f in fresh["samples"]:
                HL.track_add(fresh, f, size)
        data["samples"] = fresh["samples"]
        try:
            HL.track_save(tp, fresh)
        except OSError as e:
            log_error(f"folder history: {e}")
        if win.winfo_exists():
            refresh()

    def follow(folder):
        if not folder or not os.path.isdir(folder):
            return
        data["samples"].setdefault(folder, [])
        try:
            HL.track_save(tp, data)
        except OSError as e:
            log_error(f"folder history: {e}")
        refresh()
        measure([folder])

    def unfollow():
        sel = tv.selection()
        if sel and messagebox.askyesno("Stop following", f"Stop following {sel[0]} and forget its measurements?\nThe folder itself is not touched.", parent=A.root):
            data["samples"].pop(sel[0], None)
            HL.track_save(tp, data)
            refresh()

    ttk.Button(bt, text="Follow the current folder", style="Accent.TButton", command=lambda: follow(A.st["cwd"])).pack(side="left")
    ttk.Button(bt, text="Choose a folder…", command=lambda: follow(filedialog.askdirectory(parent=A.root))).pack(side="left", padx=8)
    ttk.Button(bt, text="Measure now", command=lambda: measure(list(data["samples"]))).pack(side="left")
    ttk.Button(bt, text="Stop following", command=unfollow).pack(side="left", padx=8)
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    tv.bind("<<TreeviewSelect>>", draw)
    cv.bind("<Configure>", draw)
    refresh()


def track_tick(A):
    """Called every 5 minutes: measure the followed folders that are over a week old, only while the PC is idle."""
    if HL.idle_seconds() < 120:
        return
    tp = _track_path(A)
    data = HL.track_load(tp)
    now = time.time()
    due = [f for f, s in data["samples"].items() if (not s or now - s[-1][0] > 7 * 86400) and os.path.isdir(f)]
    if not due or A.st.get("track_running"):
        return
    A.st["track_running"] = True

    def work():
        low_priority()
        try:
            fresh = HL.track_load(tp)
            for f in due:
                size = HL.track_measure(f, pause=0.002)
                if size is not None and f in fresh["samples"]:
                    HL.track_add(fresh, f, size)
            HL.track_save(tp, fresh)
        except Exception as e:  # noqa - a background measurement must never disturb the app
            log_error(f"folder history tick: {e}")
        finally:
            A.st["track_running"] = False
    threading.Thread(target=work, daemon=True).start()


# ------------------------------------------------------------------------------------------------ crash check
def crash_count(path=None):
    """How many fatal crashes crash.log has recorded (faulthandler writes one block per crash)."""
    p = path or (ff_core.DB_DIR / "crash.log")
    try:
        txt = open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return 0
    return txt.count("Windows fatal exception") + txt.count("Fatal Python error")


def crash_check(A):
    """At start: if crash.log shows a crash we haven't told you about, offer a problem report (a zip on the Desktop, private values hidden)."""
    n = crash_count()
    seen = A.cfg.get("crash_seen", 0)
    if n < seen:  # the log was trimmed
        A.save_cfg(crash_seen=n)
        return
    if n == seen:
        return
    A.save_cfg(crash_seen=n)

    def make():
        try:
            z = ff_support.make_report()
            A.status.set(f"Problem report saved on the Desktop: {z.name}")
        except Exception as e:  # noqa
            A.status.set(f"Couldn't make the report: {e}")
    A.show_toast("Pinefiles closed unexpectedly at some point. A problem report shows why.", "Make report", make)


# ------------------------------------------------------------------------------------------------ short how-to guides inside tools
HOWTO = {
    "ftp": ("Connecting to a server (FTP / SFTP / WebDAV)", [
        ("1. Pick the protocol", "SFTP (SSH) is the safe choice and works with most servers and NAS boxes. FTPS is FTP with encryption. Plain FTP "
         "sends everything readable, so use it only on your own home network. WebDAV is for NAS boxes, Nextcloud and similar: type the full "
         "https:// address in the Server box."),
        ("2. Server and port", "Server is a name or address such as 192.168.1.20 or files.example.com. The port fills in by itself (21 for FTP and "
         "FTPS, 22 for SFTP). Change it only if your server owner tells you to."),
        ("3. User and password", "Type them every time: Pinefiles never saves the password. Public FTP servers often accept the user "
         "'anonymous' with any password."),
        ("4. Connect", "Press Connect. With SFTP the first time shows the server's fingerprint: compare it with the one the server owner gave "
         "you before you accept. Pinefiles remembers it and warns you if it ever changes."),
        ("5. Browse", "Double-click a folder to open it, '..' goes up. The file list shows names and sizes."),
        ("6. Download and upload", "Select files in the list and press 'Download selected': they are saved into the folder that is open in "
         "Pinefiles's file view. 'Upload selected files from Pinefiles' sends the files you selected in the file view. Both run in the "
         "background and tell you when they are done."),
        ("7. When you are done", "Close the tool: the connection is closed with it."),
    ]),
    "localsend": ("Sending files to nearby devices", [
        ("1. What this is", "Pinefiles speaks the LocalSend protocol, so it can exchange files directly with the free LocalSend app on Android, iPhone, "
         "Windows, Mac and Linux (and with another Pinefiles). Everything stays on your own network: nothing goes over the internet."),
        ("2. Install LocalSend on the other device", "Get LocalSend from your phone's app store or from localsend.org and open it. Both devices must be on the "
         "same Wi-Fi or network."),
        ("3. Sending from here", "Press 'Search again' until the device shows up in the list. If it does not, press 'Add by address…' and type the IP "
         "address that LocalSend shows on the other device. Pick the device, choose what to send (Files…, A folder…, or 'Selected in Pinefiles') "
         "and press 'Send to the selected device'. The other device asks to accept; you can also right-click files in Pinefiles > "
         "'Send to a nearby device…'."),
        ("4. Receiving here", "Tick 'Receive files from nearby devices'. Other devices can then see this PC under the name you chose. Every "
         "incoming transfer asks you to Accept or Decline first (and receiving switches itself off after 20 minutes, never in the middle of a transfer), and the files are saved in the folder shown (a 'Pinefiles received' folder in your Downloads "
         "unless you change it). Untick it and this PC is invisible again."),
        ("5. Windows Firewall", "The first time you turn receiving on, Windows may ask to allow Pinefiles on the network. Choose 'Private networks' "
         "only. If other devices still cannot see this PC, use 'Add by address…' on them with this PC's address shown on the tool."),
        ("6. Good to know", "PIN-protected receivers are not supported yet. Transfers can be cancelled from either side. Files that already exist "
         "are never overwritten: the new one gets (1) added to its name."),
    ]),
    "rules": ("Automatic rules", [
        ("1. What they do", "A rule watches one folder (for example Downloads). When a file turns up that fits the rule, Pinefiles moves, copies, renames, tags or "
         "colours it for you, for example 'pictures go to a folder in Pictures'. Rules never delete anything and never overwrite a file."),
        ("2. Make one", "Press 'Ready-made rule' for a common one, or 'Add rule…'. Choose the folder to watch, which files (types, a word in the name, an age) "
         "and what to do. A rule must say which files it is for, so it can never grab everything."),
        ("3. Look before you trust", "Press 'Preview now': the activity list shows what would happen right now without changing anything. 'Run the rules now' does it once."),
        ("4. Switch them on", "Tick 'Run my rules automatically…'. Pinefiles then checks about once a minute while it is open. A file must have been untouched for the "
         "number of minutes you set, so downloads that are still arriving are left alone. Nothing runs while the box is unticked, and they never start by themselves "
         "unless you left it ticked."),
        ("5. Undo", "Moves and renames can be undone with Ctrl+Z (View > Undo history). Folders marked as protected in the cleaner are never touched."),
    ]),
    "notify": ("Getting alerts on your phone", [
        ("1. What you will get", "Pinefiles can send its weekly check-up and malware warnings to your phone as a short message. Only that "
         "message text is sent, never file names or contents of your files."),
        ("2. Easiest free way: ntfy", "Install the free ntfy app on your phone (Android or iPhone). In the app press + and subscribe to a topic "
         "name that only you know, for example pinefiles-yourname-4821. Anyone who knows the name could read the messages, so make it hard to guess."),
        ("3. Paste the address here", "In Pinefiles type  https://ntfy.sh/<your topic>  in the box (for example https://ntfy.sh/pinefiles-yourname-4821) "
         "and press 'Save and send a test'. The test message should arrive on your phone within seconds."),
        ("4. Discord instead", "Create a webhook in a Discord channel you own (Channel settings > Integrations > Webhooks > New webhook > Copy "
         "webhook URL) and paste that address in the same box."),
        ("5. Turn it off", "Press Remove: nothing is sent any more. The weekly check-up toast on this PC is a separate setting."),
    ]),
}


def open_howto(A, topic):
    """A small window with numbered steps for one tool (the Tutorial buttons of the FTP and Phone notifications tools)."""
    title, steps = HOWTO[topic]
    win = tk.Toplevel(A.root)
    win.title(title)
    win.configure(bg=T["bg"])
    win.transient(A.root)
    w, h = 640, 600
    win.geometry(f"{w}x{h}+{A.root.winfo_rootx() + 60}+{A.root.winfo_rooty() + 40}")
    tk.Label(win, text=title, bg=T["bg"], fg=T["fg"], font=("Segoe UI", A.cfg["font_size"] + 5, "bold"), anchor="w", wraplength=w - 50).pack(fill="x", padx=22, pady=(18, 6))
    ttk.Button(win, text="Close", command=win.destroy).pack(side="bottom", anchor="e", padx=22, pady=14)
    txt = tk.Text(win, bg=T["bg"], fg=T["fg"], relief="flat", wrap="word", padx=4, pady=4, borderwidth=0, highlightthickness=0,
                  font=("Segoe UI", A.cfg["font_size"]), cursor="arrow")
    txt.pack(fill="both", expand=True, padx=22)
    txt.tag_configure("h", font=("Segoe UI", A.cfg["font_size"] + 1, "bold"), foreground=T["accent"], spacing1=12, spacing3=2)
    for head, body in steps:
        txt.insert("end", head + chr(10), "h")
        txt.insert("end", body + chr(10))
    txt.configure(state="disabled")
    win.bind("<Escape>", lambda e: win.destroy())
    win.focus_set()
