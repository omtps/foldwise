"""Tools > Nearby devices: send files to phones and PCs running LocalSend (or Pinefiles), and receive from them.

Receiving is OFF until you switch it on, and every incoming transfer asks first. Every function takes `A` first (ff_app.App).
"""
import os
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import ff_localsend as LS
import ff_platform
from ff_core import DB_DIR, T, ThemedAsk, ThemedBox as messagebox, human_size
from ui_picker import filedialog

_S = {"node": None, "log": [], "recv": {}}


def default_dir():
    return os.path.join(os.path.expanduser("~"), "Downloads", "Pinefiles received")


def node(A):
    """The one Node of this program (created on first use; it only listens while 'Receive' is on)."""
    n = _S["node"]
    alias = (A.cfg.get("localsend_name") or "").strip() or socket.gethostname()[:30]
    folder = A.cfg.get("localsend_dir") or default_dir()
    if n is None:
        n = _S["node"] = LS.Node(alias, str(DB_DIR / "localsend"), folder, port=int(A.cfg.get("localsend_port") or LS.PORT), on_request=lambda info: _ask(A, info),
                                 on_event=lambda k, d: _later(A, lambda: _event(A, k, d)))
    n.alias, n.receive_dir = alias, folder
    return n


def listening():
    n = _S["node"]
    return bool(n and n._srv)


def _later(A, fn):
    try:
        A.root.after(0, fn)
    except (RuntimeError, tk.TclError):
        pass


def log(text=""):
    """Add a line to the activity list (no text: just redraw it)."""
    if text:
        _S["log"] = (_S["log"] + [f"{time.strftime('%H:%M:%S')}  {text}"])[-200:]
    w = _S.get("logw")
    try:
        if w is not None and w.winfo_exists():
            w.configure(state="normal")
            w.delete("1.0", "end")
            w.insert("end", chr(10).join(_S["log"]))
            w.see("end")
            w.configure(state="disabled")
    except tk.TclError:
        pass


AUTO_OFF = 20 * 60  # receiving is a temporary mode: it switches itself off after this many seconds (never in the middle of a transfer)


def autostart(A):
    """At program start receiving is always off (it never turns itself on); this only clears a stale 'on' left in the settings."""
    if A.cfg.get("localsend_on"):
        A.save_cfg(localsend_on=False)


def start_receiving(A):
    """Start listening (raises OSError when the port is taken) and arm the automatic switch-off."""
    n = node(A)
    n.start()
    n.announce()
    _S["off_at"] = time.time() + AUTO_OFF
    _arm(A)
    A.save_cfg(localsend_on=True)


def stop_receiving(A, auto=False):
    t = _S.pop("timer", None)
    if t:
        try:
            A.root.after_cancel(t)
        except tk.TclError:
            pass
    n = _S["node"]
    if n:
        n.stop()
    _S["node"] = None
    A.save_cfg(localsend_on=False)
    log("Receiving turned itself off" if auto else "Receiving is off")
    if auto:
        A.show_toast(f"Receiving files turned itself off after {max(1, round(AUTO_OFF / 60))} minutes. Switch it on again in Nearby devices when you need it.", "Open",
                     lambda: A.open_localsend(), title="Pinefiles \u00b7 Nearby devices")


def minutes_left():
    return max(0, -(-int(_S.get("off_at", 0) - time.time()) // 60))


def _arm(A):
    t = _S.pop("timer", None)
    if t:
        try:
            A.root.after_cancel(t)
        except tk.TclError:
            pass
    _S["timer"] = A.root.after(int(max(0.3, min(30, AUTO_OFF / 4)) * 1000), lambda: _check_off(A))


def _check_off(A):
    _S["timer"] = None
    n = _S["node"]
    if not (n and n._srv):
        return
    if time.time() >= _S.get("off_at", 0):
        if n.busy():  # never cut a transfer in progress
            _S["off_at"] = time.time() + 60
        else:
            stop_receiving(A, auto=True)
            return
    _arm(A)


# ------------------------------------------------------------------------------------------------ incoming
def _ask(A, info):
    """Runs in the server's thread: show the question in the window and wait for the answer (no answer in 2 minutes = no)."""
    done, res = threading.Event(), [False]

    def show():
        try:
            win = tk.Toplevel(A.root)
        except tk.TclError:
            done.set()
            return
        win.title("Incoming files")
        win.configure(bg=T["bg"])
        win.attributes("-topmost", True)
        win.resizable(False, False)
        f = tk.Frame(win, bg=T["bg"], padx=22, pady=18)
        f.pack()
        n = len(info["files"])
        tk.Label(f, text=f"{info['alias']} wants to send you {n} file{'s' if n != 1 else ''}", bg=T["bg"], fg=T["fg"], font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(f, text=f"{human_size(info['total'])}   from {info['ip']}", bg=T["bg"], fg=T["muted"]).pack(anchor="w", pady=(2, 8))
        shown = info["files"][:10]
        tk.Label(f, text=chr(10).join(f"{x['name']}   ({human_size(x['size'])})" for x in shown) + (f"{chr(10)}… and {n - 10} more" if n > 10 else ""),
                 bg=T["bg"], fg=T["fg"], justify="left", wraplength=420).pack(anchor="w")
        tk.Label(f, text=f"They will be saved in: {node(A).receive_dir}", bg=T["bg"], fg=T["muted"], wraplength=420, justify="left").pack(anchor="w", pady=(10, 12))
        row = tk.Frame(f, bg=T["bg"])
        row.pack(anchor="e")

        def answer(ok):
            res[0] = ok
            done.set()
            win.destroy()
        ttk.Button(row, text="Decline", command=lambda: answer(False)).pack(side="left", padx=6)
        ttk.Button(row, text="Accept", style="Accent.TButton", command=lambda: answer(True)).pack(side="left")
        win.protocol("WM_DELETE_WINDOW", lambda: answer(False))
        win.bind("<Escape>", lambda e: answer(False))
        win.update_idletasks()
        w_, h_, sw, sh = win.winfo_reqwidth(), win.winfo_reqheight(), win.winfo_screenwidth(), win.winfo_screenheight()
        try:  # next to the main window when it is on screen; otherwise (minimised or in the tray Windows reports it at -32000) the middle of the screen
            on_screen = A.root.state() == "normal" and A.root.winfo_viewable()
        except tk.TclError:
            on_screen = False
        x, y = (A.root.winfo_rootx() + (A.root.winfo_width() - w_) // 2, A.root.winfo_rooty() + 90) if on_screen else ((sw - w_) // 2, (sh - h_) // 3)
        win.geometry(f"+{max(0, min(sw - w_, x))}+{max(0, min(sh - h_, y))}")
        win.deiconify()
        win.lift()
        win.focus_force()
        win.bell()
        log(f"{info['alias']} wants to send {n} file(s): waiting for your answer")

        def raise_it():
            try:
                win.deiconify()
                win.lift()
                win.focus_force()
            except tk.TclError:
                pass
        A.show_toast(f"{info['alias']} wants to send you {n} file{'s' if n != 1 else ''}.", "Show", raise_it, title="Pinefiles \u00b7 Nearby devices")
    _later(A, show)
    done.wait(120)
    return res[0]


def _event(A, kind, d):
    if kind == "peer":
        log(f"Found {d['alias']} ({d['ip']})")
        w = _S.get("refresh")
        if w:
            w()
    elif kind == "incoming":
        _S["recv"][d["sid"]] = {"n": 0, "alias": d["alias"]}
        log(f"Receiving {d['count']} file(s), {human_size(d['total'])}, from {d['alias']}")
    elif kind == "file":
        r = _S["recv"].setdefault(d["sid"], {"n": 0, "alias": d["alias"]})
        r["n"] += 1
        if d["finished"]:
            log(f"Received {r['n']} file(s) from {r['alias']}")
            folder = node(A).receive_dir
            A.show_toast(f"Received {r['n']} file{'s' if r['n'] != 1 else ''} from {r['alias']}.", "Open folder", lambda: ff_platform.open_path(folder),
                         title="Pinefiles \u00b7 Nearby devices")
            A.refresh()
    elif kind == "cancelled":
        log(f"{d['alias']} cancelled the transfer")


# ------------------------------------------------------------------------------------------------ the tool
def wrap(label, frame, pad=40):
    """Let a long label wrap at the width of its frame instead of making the whole page wider than the window."""
    frame.bind("<Configure>", lambda e: label.configure(wraplength=max(220, e.width - pad)), add="+")


def open_localsend(A, paths=None):
    win = A.toplevel("Nearby devices", "920x720")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    st = {"paths": [p for p in (paths or []) if os.path.exists(p)], "sending": False, "cancel": False}
    n = node(A)
    msg = tk.StringVar()

    bt = ttk.Frame(win, padding=(14, 8))
    bt.pack(side="bottom", fill="x")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    ttk.Button(bt, text="Tutorial", command=lambda: A.open_howto("localsend")).pack(side="right", padx=8)
    logw = tk.Text(win, height=7, width=10, bg=T["panel"], fg=T["fg"], relief="flat", wrap="word", font=("Consolas", 9), padx=10, pady=8, state="disabled")
    logw.pack(side="bottom", fill="x", padx=16, pady=(0, 6))
    _S["logw"] = logw
    ttk.Label(win, text="ACTIVITY", style="DetHead.TLabel", background=T["bg"]).pack(side="bottom", anchor="w", padx=18)
    log()  # draws the history

    # ---- receive
    top = ttk.Frame(win, padding=(18, 14, 18, 4))
    top.pack(fill="x")
    ttk.Label(top, text="Nearby devices", font=("Segoe UI", 15, "bold")).pack(anchor="w")
    desc = ttk.Label(top, text="Send files to phones and PCs on the same network that run LocalSend (free, for Android, iPhone, Windows, Mac and Linux), "
                     "or receive from them. Nothing is sent over the internet.", wraplength=420, style="DetKey.TLabel", background=T["bg"])
    desc.pack(anchor="w", pady=(2, 8))
    wrap(desc, top)
    rv = tk.BooleanVar(value=listening())
    row1 = ttk.Frame(top)
    row1.pack(fill="x")
    ttk.Checkbutton(row1, text="Receive files from nearby devices", variable=rv, command=lambda: toggle()).pack(side="left")
    row1b = ttk.Frame(top)
    row1b.pack(fill="x", pady=(6, 0))
    ttk.Label(row1b, text="Visible as").pack(side="left")
    namev = tk.StringVar(value=n.alias)
    ne = ttk.Entry(row1b, textvariable=namev, width=20)
    ne.pack(side="left", padx=6)
    ttk.Button(row1b, text="Save name", command=lambda: save_name()).pack(side="left")
    row2 = ttk.Frame(top)
    row2.pack(fill="x", pady=(6, 0))
    dirv = tk.StringVar(value=n.receive_dir)
    ttk.Label(row2, text="Received files go to:").pack(side="left")
    ttk.Button(row2, text="Change…", command=lambda: change_dir()).pack(side="left", padx=(8, 0))
    ttk.Button(row2, text="Open", command=lambda: (os.makedirs(n.receive_dir, exist_ok=True), ff_platform.open_path(n.receive_dir))).pack(side="left", padx=8)
    where = ttk.Label(top, textvariable=dirv, foreground=T["accent"], wraplength=420)
    where.pack(anchor="w")
    wrap(where, top)
    status = tk.StringVar()
    stl = ttk.Label(top, textvariable=status, style="DetKey.TLabel", background=T["bg"], wraplength=420)
    stl.pack(anchor="w", pady=(6, 0))
    wrap(stl, top)

    def show_status():
        if listening():
            status.set(f"On: visible as “{n.alias}” at {', '.join(LS.local_ips()[:2])}, port {n.port} ({n.protocol.upper()}). Every incoming transfer asks you first. "
                       f"It switches itself off in about {minutes_left()} min. The first time, Windows may ask to allow Pinefiles on the network: choose Private networks.")
        else:
            status.set("Off: nobody can send to this PC. You can still send to others below.")

    def toggle():
        if rv.get():
            try:
                start_receiving(A)
            except OSError as e:
                rv.set(False)
                messagebox.showerror("Nearby devices", f"Couldn't start receiving: {e}\n\nAnother LocalSend may already be open on this PC.", parent=A.root)
                return
            log("Receiving is on (it switches itself off after " + str(max(1, round(AUTO_OFF / 60))) + " minutes)")
            check_network(auto=True)
        else:
            stop_receiving(A)
            node_after_stop()
        show_status()

    def node_after_stop():
        nonlocal n
        n = node(A)

    def save_name():
        A.save_cfg(localsend_name=namev.get().strip())
        n.alias = namev.get().strip() or socket.gethostname()[:30]
        namev.set(n.alias)
        if listening():
            n.announce()
        show_status()

    def change_dir():
        d = filedialog.askdirectory(parent=win, title="Where should received files go?", initialdir=n.receive_dir if os.path.isdir(n.receive_dir) else "")
        if d:
            A.save_cfg(localsend_dir=d)
            n.receive_dir = d
            dirv.set(d)

    # ---- devices + sending
    mid = ttk.Frame(win, padding=(18, 8, 18, 0))
    mid.pack(fill="both", expand=True)
    ttk.Label(mid, text="DEVICES NEARBY", style="DetHead.TLabel", background=T["bg"]).pack(anchor="w")
    tvf = tk.Frame(mid, bg=T["bg"])
    tvf.pack(fill="both", expand=True, pady=(4, 6))
    tv = ttk.Treeview(tvf, columns=("addr", "kind"), show="tree headings", selectmode="browse", height=5)
    for c, text, w, anc in (("#0", "Device", 200, "w"), ("addr", "Address", 150, "w"), ("kind", "Type", 90, "w")):
        tv.heading(c, text=text, anchor=anc)
        tv.column(c, width=w, anchor=anc, stretch=(c == "#0"))
    tv.pack(fill="both", expand=True)
    peers = {}

    def refresh_list():
        if not alive["v"]:
            return
        keep = tv.selection()
        tv.delete(*tv.get_children())
        peers.clear()
        for p in n.peers():
            peers[p["fingerprint"]] = p
            tv.insert("", "end", iid=p["fingerprint"], text=p["alias"], values=(f"{p['ip']}:{p['port']}", p["deviceModel"] or p["deviceType"]))
        if keep and tv.exists(keep[0]):
            tv.selection_set(keep[0])
        elif len(peers) == 1:
            tv.selection_set(next(iter(peers)))
    _S["refresh"] = lambda: alive["v"] and refresh_list()

    def check_network(auto=False):
        msg.set("Checking your network…")

        def work():
            nets, blocks = ff_platform.network_report(sys.executable)
            res = LS.explain(nets, blocks, listening(), LS.local_ips(), len(n.peers()), n.scanned)
            _later(A, lambda: alive["v"] and done(res))

        def done(res):
            bad = [t for lvl, t in res if lvl == "bad"]
            msg.set(bad[0] if bad else "Network check finished: nothing is blocking file sharing.")
            if bad or not auto:
                report(res)
        threading.Thread(target=work, daemon=True).start()

    def report(res):
        d = tk.Toplevel(A.root)
        d.title("Why can't I see devices?")
        d.configure(bg=T["bg"])
        d.transient(A.root)
        f = tk.Frame(d, bg=T["bg"], padx=22, pady=16)
        f.pack(fill="both", expand=True)
        for lvl, text in res:
            row = tk.Frame(f, bg=T["bg"])
            row.pack(fill="x", pady=4)
            tk.Label(row, text={"bad": "\u2716", "warn": "\u26A0", "ok": "\u2714"}[lvl], fg={"bad": "#f87171", "warn": "#facc15", "ok": "#4ade80"}[lvl],
                     bg=T["bg"], font=("Segoe UI", 12, "bold"), width=2).pack(side="left", anchor="n")
            tk.Label(row, text=text, bg=T["bg"], fg=T["fg"], wraplength=520, justify="left", anchor="w").pack(side="left", fill="x", expand=True)
        b = tk.Frame(f, bg=T["bg"])
        b.pack(fill="x", pady=(12, 0))
        ttk.Button(b, text="Open Wi-Fi settings", command=lambda: ff_platform.open_os_settings("wifi")).pack(side="left")
        ttk.Button(b, text="Open firewall settings", command=lambda: ff_platform.open_os_settings("firewall")).pack(side="left", padx=8)
        ttk.Button(b, text="Close", command=d.destroy).pack(side="right")
        d.update_idletasks()
        d.geometry(f"+{A.root.winfo_rootx() + 90}+{A.root.winfo_rooty() + 70}")
        _S["report"] = d

    def find():
        msg.set("Looking for devices…")

        def work():
            try:
                n.announce()
                n.scan()
            except Exception as e:  # noqa
                _later(A, lambda e=e: msg.set(f"Search failed: {e}"))
                return
            def shown():
                refresh_list()
                if n.peers():
                    msg.set(f"{len(n.peers())} device(s) found.")
                else:
                    log("Searched " + ", ".join(n.scanned) + ": no device answered")
                    msg.set("No devices found. Press “Check my network” to see what might be in the way.")
            _later(A, lambda: alive["v"] and shown())
        threading.Thread(target=work, daemon=True).start()

    def add_by_address():
        ip = ThemedAsk.askstring("Add a device", "IP address of the other device (shown in its LocalSend app):", parent=win)
        if not ip or not ip.strip():
            return

        def work():
            p = n.probe(ip.strip(), LS.PORT, 2.0)
            _later(A, lambda: alive["v"] and (refresh_list(), msg.set(f"Found {p['alias']}." if p else f"No LocalSend device answered at {ip.strip()}.")))
        threading.Thread(target=work, daemon=True).start()

    srow = ttk.Frame(mid)
    srow.pack(fill="x")
    ttk.Button(srow, text="Search again", command=find).pack(side="left")
    ttk.Button(srow, text="Add by address…", command=add_by_address).pack(side="left", padx=8)
    ttk.Button(srow, text="Check my network", command=check_network).pack(side="left")
    pick = ttk.Frame(mid)
    pick.pack(fill="x", pady=(10, 0))
    ttk.Label(pick, text="SEND", style="DetHead.TLabel", background=T["bg"]).pack(side="left")
    what = tk.StringVar()
    wl = ttk.Label(pick, textvariable=what, style="DetKey.TLabel", background=T["bg"], wraplength=300)
    wl.pack(side="left", padx=10)
    wrap(wl, mid, 150)
    brow = ttk.Frame(mid)
    brow.pack(fill="x", pady=4)
    ttk.Button(brow, text="Files…", command=lambda: choose(files=True)).pack(side="left")
    ttk.Button(brow, text="A folder…", command=lambda: choose(files=False)).pack(side="left", padx=8)
    ttk.Button(brow, text="Selected in Pinefiles", command=lambda: use_selection()).pack(side="left")
    grow = ttk.Frame(mid)  # its own row: the main button must never slide out of view in a narrow window
    grow.pack(fill="x", pady=(2, 4))
    go = ttk.Button(grow, text="Send to the selected device", style="Accent.TButton", command=lambda: send())
    go.pack(side="left")
    pb = ttk.Progressbar(mid, mode="determinate", maximum=100)
    ml = ttk.Label(mid, textvariable=msg, wraplength=420)
    ml.pack(anchor="w", pady=(2, 0))
    wrap(ml, mid)

    def show_what():
        k = len(st["paths"])
        what.set("nothing chosen yet" if not k else (os.path.basename(st["paths"][0]) if k == 1 else f"{k} items") + " ready to send")

    def choose(files):
        if files:
            got = filedialog.askopenfilenames(parent=win, title="Files to send")
            st["paths"] = list(got)
        else:
            d = filedialog.askdirectory(parent=win, title="Folder to send")
            st["paths"] = [d] if d else st["paths"]
        show_what()

    def use_selection():
        rows = [r for r in A.sel() if "ff_zip_" not in r[1]]
        if not rows:
            msg.set("Select files or folders in the Pinefiles file view first, then come back here.")
            return
        st["paths"] = [r[1] for r in rows]
        show_what()

    def send():
        if st["sending"]:
            st["cancel"] = True
            return
        sel = tv.selection()
        if not sel or sel[0] not in peers:
            msg.set("Pick a device in the list first (press Search again if it is missing).")
            return
        if not st["paths"]:
            msg.set("Choose what to send first.")
            return
        peer, paths = peers[sel[0]], list(st["paths"])
        st.update(sending=True, cancel=False)
        go.configure(text="Cancel")
        pb.pack(fill="x", pady=4)
        pb.configure(value=0)
        msg.set(f"Waiting for {peer['alias']} to accept… (they get a question on their device)")
        log(f"Sending to {peer['alias']}: {len(paths)} item(s)")
        last = [0.0]

        def prog(done, total, name):
            if time.time() - last[0] > 0.2:
                last[0] = time.time()
                _later(A, lambda: alive["v"] and (pb.configure(value=100 * done / total if total else 0),
                                                  msg.set(f"Sending {name}…  {human_size(done)} of {human_size(total)}")))

        def work():
            try:
                k = n.send(peer, paths, prog, lambda: st["cancel"])
                res = f"Sent {k} file(s) to {peer['alias']}." if k else f"{peer['alias']} already has everything."
            except LS.LocalSendError as e:
                res = str(e)
            except OSError as e:
                res = f"Couldn't reach {peer['alias']}: {e}"
            _later(A, lambda: finish(res))

        def finish(res):
            st["sending"] = False
            log(res)
            if alive["v"]:
                go.configure(text="Send to the selected device")
                pb.pack_forget()
                msg.set(res)
        threading.Thread(target=work, daemon=True).start()

    show_what()
    show_status()
    refresh_list()
    if node(A).peers() == [] and listening():
        find()

    def tick():  # peers found by multicast show up by themselves; the switch-off timer is reflected here
        nonlocal n
        if alive["v"]:
            cur = node(A)
            if cur is not n:  # receiving switched itself off: the node was replaced
                n = cur
            if rv.get() != listening():
                rv.set(listening())
            show_status()
            if len(n.peers()) != len(peers):
                refresh_list()
            win.after(3000, tick)
    win.after(3000, tick)
