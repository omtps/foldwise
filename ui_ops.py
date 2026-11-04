"""Tools > Transfers (the copy/move queue) and the Secure delete dialog.

Every function takes `A` first (ff_app.App).
"""
import os
import threading
import tkinter as tk
from tkinter import ttk

import ff_extras as X
from ff_core import T, ThemedBox as messagebox, human_size


STATE = {"waiting": "Waiting", "running": "Running", "done": "Done", "failed": "Failed", "cancelled": "Cancelled"}


def open_transfers(A):
    """Every copy and move of this session: see what runs and what waits, pause, cancel, clear."""
    win = A.toplevel("Transfers", "900x560")
    alive = {"v": True}
    win.bind("<Destroy>", lambda e: alive.update(v=False) if e.widget is win else None)
    ttk.Label(win, text="Copies and moves wait here in line: one runs at a time. Pause stops the running one until you press Resume. "
              "Turn on “Verify copies” in Customize to compare every copy with its original.", wraplength=820, padding=(18, 14, 18, 6)).pack(fill="x")
    bt = ttk.Frame(win, padding=(14, 10))
    bt.pack(side="bottom", fill="x")
    tv = ttk.Treeview(win, columns=("to", "state", "prog"), show="tree headings", selectmode="browse")
    for c, text, w, anc in (("#0", "What", 300, "w"), ("to", "To", 260, "w"), ("state", "State", 90, "w"), ("prog", "Progress", 150, "w")):
        tv.heading(c, text=text, anchor=anc)
        tv.column(c, width=w, anchor=anc, stretch=(c == "#0"))
    tv.pack(fill="both", expand=True, padx=14)
    pause_b = ttk.Button(bt, text="Pause")

    def refresh():
        if not alive["v"]:
            return
        sel = tv.selection()
        tv.delete(*tv.get_children())
        for j in reversed(A.st.get("xqueue", [])):
            what = os.path.basename(j["paths"][0].rstrip(chr(92))) + (f" and {len(j['paths']) - 1} more" if len(j["paths"]) > 1 else "")
            pct = f"{int(j['done'] * 100 / j['total'])}%  {j['name'][:22]}" if j["state"] == "running" and j["total"] else (j["msg"] if j["state"] in ("done", "failed", "cancelled") else "")
            tv.insert("", "end", iid=str(j["id"]), text=("Move: " if j["move"] else "Copy: ") + what, values=(j["folder"], STATE[j["state"]], pct))
        if sel and tv.exists(sel[0]):
            tv.selection_set(sel[0])
        pause_b.configure(text="Resume" if A.st.get("xpause") else "Pause")
        win.after(700, refresh)

    def toggle_pause():
        if A.st["xfer"]:
            A.st["xpause"] = not A.st.get("xpause")
            A.status.set("Transfer paused" if A.st["xpause"] else "Resumed")

    def cancel_selected():
        sel = tv.selection()
        if not sel:
            return
        j = next((x for x in A.st["xqueue"] if str(x["id"]) == sel[0]), None)
        if j is None:
            return
        if j["state"] == "waiting":
            j["state"] = "cancelled"
            j["msg"] = "removed from the queue"
        elif j["state"] == "running":
            A.st["xcancel"] = True

    def clear_done():
        A.st["xqueue"] = [j for j in A.st.get("xqueue", []) if j["state"] in ("waiting", "running")]

    pause_b.configure(command=toggle_pause)
    pause_b.pack(side="left")
    ttk.Button(bt, text="Cancel the selected one", command=cancel_selected).pack(side="left", padx=8)
    ttk.Button(bt, text="Clear finished", command=clear_done).pack(side="left")
    ttk.Button(bt, text="Close", command=win.destroy).pack(side="right")
    refresh()


def shred_selected(A, _=None):
    """Right-click > Securely delete: overwrite, then delete. Typed confirmation, and an honest warning about SSDs."""
    rows = [r for r in A.sel() if not X.zip_is_virtual(r[1])]
    if not rows:
        return
    paths = [r[1] for r in rows]
    blocked = [(p, X.shred_check(p)) for p in paths if X.shred_check(p)]
    if blocked:
        messagebox.showinfo("Secure delete", "Pinefiles won't shred:\n\n" + "\n".join(f"{os.path.basename(p) or p}: {why}" for p, why in blocked[:6]), parent=A.root)
        return
    win = tk.Toplevel(A.root)
    win.title("Securely delete")
    win.configure(bg=T["bg"])
    win.transient(A.root)
    win.attributes("-topmost", True)
    f = tk.Frame(win, bg=T["bg"], padx=22, pady=18)
    f.pack()
    n = len(paths)
    tk.Label(f, text=f"Permanently destroy {n} item{'s' if n != 1 else ''}?", bg=T["bg"], fg="#f87171", font=("Segoe UI", 13, "bold")).pack(anchor="w")
    tk.Label(f, text=chr(10).join(os.path.basename(p) or p for p in paths[:8]) + (f"{chr(10)}… and {n - 8} more" if n > 8 else ""), bg=T["bg"], fg=T["fg"], justify="left").pack(anchor="w", pady=(6, 8))
    tk.Label(f, text="The files are overwritten with random data and then deleted. They do NOT go to the Recycle Bin and cannot be recovered or undone.\n\n"
             "Be aware: on SSDs, USB sticks, SD cards, cloud-synced folders (OneDrive, Dropbox) and drives with File History or snapshots, "
             "the drive may keep older copies elsewhere, so overwriting is no guarantee there. For those, encrypting the drive (BitLocker) "
             "is the reliable protection.", bg=T["bg"], fg=T["muted"], justify="left", wraplength=480).pack(anchor="w")
    row = tk.Frame(f, bg=T["bg"])
    row.pack(fill="x", pady=(12, 4))
    tk.Label(row, text="Overwrite passes", bg=T["bg"], fg=T["fg"]).pack(side="left")
    passes = ttk.Combobox(row, values=["1 (enough for normal use)", "3 (slower)"], state="readonly", width=24)
    passes.set("1 (enough for normal use)")
    passes.pack(side="left", padx=8)
    tk.Label(f, text="Type SHRED to confirm:", bg=T["bg"], fg=T["fg"]).pack(anchor="w", pady=(8, 2))
    ev = tk.StringVar()
    ent = ttk.Entry(f, textvariable=ev, width=20)
    ent.pack(anchor="w")
    status = tk.StringVar()
    tk.Label(f, textvariable=status, bg=T["bg"], fg=T["muted"], wraplength=480, justify="left").pack(anchor="w", pady=6)
    b = tk.Frame(f, bg=T["bg"])
    b.pack(anchor="e")
    cancel = {"v": False}
    go = ttk.Button(b, text="Destroy", state="disabled")
    ttk.Button(b, text="Close", command=lambda: (cancel.update(v=True), win.destroy())).pack(side="left", padx=6)
    go.pack(side="left")
    ev.trace_add("write", lambda *_: go.configure(state="normal" if ev.get().strip().upper() == "SHRED" else "disabled"))

    def run():
        go.configure(state="disabled")
        ent.configure(state="disabled")
        np_ = 3 if passes.get().startswith("3") else 1
        status.set("Destroying…")

        def prog(d, t, name):
            A.root.after(0, lambda: win.winfo_exists() and status.set(f"{int(d * 100 / t)}%   {name}"))

        def work():
            try:
                k, errs = X.shred_paths(paths, np_, prog, lambda: cancel["v"])
                msg = f"Done: {k} file(s) destroyed." + (f"  {len(errs)} problem(s): " + "; ".join(f"{os.path.basename(p)}: {w}" for p, w in errs[:3]) if errs else "")
            except X.Cancelled:
                msg = "Stopped."
            except Exception as e:  # noqa
                msg = f"Failed: {e}"
            A.root.after(0, lambda: (win.winfo_exists() and status.set(msg), A.refresh()))
        threading.Thread(target=work, daemon=True).start()
    go.configure(command=run)
    win.bind("<Escape>", lambda e: (cancel.update(v=True), win.destroy()))
    win.update_idletasks()
    win.geometry(f"+{A.root.winfo_rootx() + 120}+{A.root.winfo_rooty() + 90}")
    ent.focus_set()
