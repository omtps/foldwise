"""Rubber-band (drag) selection in the file list and drag-and-drop of files between panes / to other programs.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import ff_extras as X
import ff_shell as Sh
import tkinter as tk
from tkinter import ttk
from ff_core import (T, log_error)


def drop_target(A, xr, yr):
    w = A.root.winfo_containing(xr, yr)
    dragged = {r[1] for r in A.drag["items"]}
    for idx, (_, t) in enumerate(A.pane_frames):
        if w is t:
            row = t.identify_row(yr - t.winfo_rooty())
            rows = A.st["rows"] if idx == A.pane["i"] else A.panes[idx]["rows"]
            if row:
                r = rows[int(row)]
                if r[4] and r[1] not in dragged:
                    return ("row", (t, row), r[1])
            return None
    if w is A.side:
        i = A.side.nearest(yr - A.side.winfo_rooty())
        if 0 <= i < len(A.side_items) and A.side_items[i][0] == "path":
            return ("side", i, A.side_items[i][1])
        return None
    p = getattr(w, "_ff_path", None)
    return ("btn", w, p) if p else None


def clear_hl(A):
    h = A.drag["hl"]
    if h:
        kind, ref, old = h
        try:
            if kind == "row":
                ref[0].item(ref[1], tags=old)
            elif kind == "side":
                A.side.itemconfigure(ref, background=T["panel"])
        except tk.TclError:
            pass
    A.drag["hl"] = None


def set_hl(A, tg):
    cur_h = A.drag["hl"]
    if cur_h and tg and cur_h[0] == tg[0] and cur_h[1] == tg[1]:
        return
    A.clear_hl()
    if not tg:
        return
    if tg[0] == "row":
        old = tg[1][0].item(tg[1][1], "tags")
        tg[1][0].item(tg[1][1], tags=tuple(old) + ("drop",))
        A.drag["hl"] = ("row", tg[1], old)
    elif tg[0] == "side":
        A.side.itemconfigure(tg[1], background=T["sel"])
        A.drag["hl"] = ("side", tg[1], None)


def ole_out(A):
    """The pointer left the window mid-drag: hand the files to Windows so any app can accept them."""
    paths = [r[1] for r in A.drag["items"] if not X.zip_is_virtual(r[1])]
    A.clear_hl()
    if A.drag["top"]:
        A.drag["top"].destroy()
    A.drag.update(start=None, row=None, hold=False, active=False, items=[], top=None, hl=None)
    if paths:
        try:
            effect = Sh.ole_drag(Sh.hwnd_of(A.root), paths)
            A.status.set({1: "Copied", 2: "Moved", 4: "Linked"}.get(effect, "Drag cancelled") + (
                f" {len(paths)} item(s) to another app" if effect else ""))
            if effect:
                A.root.after(400, A.after_change)
        except Exception as e:  # noqa
            log_error(f"ole drag: {e}")
    return "break"


def mq_rect(A, w, x0, y0, x1, y1):
    x0, x1 = sorted((max(0, x0), min(w.winfo_width() - 1, x1)))
    y0, y1 = sorted((max(0, y0), min(w.winfo_height() - 1, y1)))
    spec = {"t": (x0, y0, max(1, x1 - x0), 1), "b": (x0, y1, max(1, x1 - x0), 1), "l": (x0, y0, 1, max(1, y1 - y0)), "r": (x1, y0, 1, max(1, y1 - y0))}
    for k, (x, y, wd, ht) in spec.items():
        f = A.mq["lines"].get(k)
        if f is None or f.master is not w:
            if f is not None:
                f.destroy()
            f = A.mq["lines"][k] = tk.Frame(w, bg=T["accent"])
        f.place(x=x, y=y, width=wd, height=ht)
        f.lift()


def mq_clear(A):
    for f in A.mq["lines"].values():
        f.destroy()
    A.mq["lines"] = {}


def mq_row0(A, w):
    """y (in widget coordinates) where row 0 starts, and the row height; None if the list is empty."""
    kids = w.get_children()
    for i, k in enumerate(kids):
        bb = w.bbox(k)
        if bb:
            return bb[1] - i * bb[3], bb[3], kids
    return None


def mq_in_zone(A, w, e):
    """True when a press at e is on 'nothing' (blank area or right of the file name) so it starts a rubber band."""
    if w.identify_region(e.x, e.y) in ("heading", "separator"):
        return False
    row = w.identify_row(e.y)
    if not row:
        return True
    if w.identify_column(e.x) != "#0":
        return True
    bb = w.bbox(row, "#0")
    if not bb:
        return False
    if A.mq["font"] is None:
        import tkinter.font as tkfont
        A.mq["font"] = tkfont.Font(font=ttk.Style().lookup("Treeview", "font") or "TkDefaultFont")
    return e.x > bb[0] + 36 + A.mq["font"].measure(w.item(row, "text"))


def mq_start(A, w, e):
    r0 = A.mq_row0(w)
    A.mq.update(on=True, w=w, x0=e.x, y0=e.y, ex=e.x, ey=e.y, moved=False, base=set(w.selection()) if e.state & 0x5 else set(), last=None,
              c0=(e.y - r0[0]) if r0 else 0, job=None, row=w.identify_row(e.y))
    w.focus_set()


def mq_update(A, e_y, e_x):
    w = A.mq["w"]
    r0 = A.mq_row0(w)
    if not r0:
        return
    top, h, kids = r0
    if e_y < 24:
        w.yview_scroll(-1, "units")
    elif e_y > w.winfo_height() - 6:
        w.yview_scroll(1, "units")
    r0 = A.mq_row0(w)
    if not r0:
        return
    top, h, kids = r0
    c1 = e_y - top
    lo, hi = sorted((A.mq["c0"], c1))
    a, b = max(0, int(lo // h)), min(len(kids) - 1, int(hi // h))
    want = set(A.mq["base"]) | set(kids[a:b + 1])
    if want != A.mq["last"]:
        A.mq["last"] = want
        w.selection_set(list(want))
    A.mq_rect(w, A.mq["x0"], A.mq["c0"] + top, e_x, c1 + top)


def mq_tick(A):
    if A.mq["on"] and A.mq["moved"]:
        A.mq_update(A.mq["ey"], A.mq["ex"])
        A.mq["job"] = A.mq["w"].after(70, A.mq_tick)


def mq_motion(A, e):
    if abs(e.x - A.mq["x0"]) + abs(e.y - A.mq["y0"]) < 4 and not A.mq["moved"]:
        return
    A.mq.update(ex=e.x, ey=e.y)
    if not A.mq["moved"]:
        A.mq["moved"] = True
        A.mq["job"] = A.mq["w"].after(70, A.mq_tick)
    A.mq_update(e.y, e.x)


def mq_end(A, e):
    w = A.mq["w"]
    if A.mq.get("job"):
        w.after_cancel(A.mq["job"])
    A.mq_clear()
    was = A.mq["moved"]
    A.mq["on"] = False
    row = A.mq.get("row")
    if not was and row and w.exists(row):
        # a plain click on a row's size/date column (or the blank part of its name cell) selects that row, so double-click opens it
        if e.state & 0x4:
            w.selection_toggle(row)
        elif e.state & 0x1:
            w.selection_add(row)
        else:
            w.selection_set(row)
        w.focus(row)
    elif not was and not (e.state & 0x5):
        w.selection_set(())


def dnd_press(A, e):
    A.activate(A.pane_of(e.widget))
    if A.tree.identify_region(e.x, e.y) in ("heading", "separator"):  # resizing/sorting a column must never pick up a file
        A.drag.update(start=None, row=None, hold=False, active=False)
        return None
    if A.mq_in_zone(e.widget, e):
        A.drag.update(start=None, row=None, hold=False, active=False)
        A.mq_start(e.widget, e)
        return "break"
    row = A.tree.identify_row(e.y)
    A.drag.update(start=(e.x_root, e.y_root), row=row, hold=False, active=False)
    if row and row in A.tree.selection() and len(A.tree.selection()) > 1 and not (e.state & 0x5):
        A.drag["hold"] = True
        A.tree.focus_set()
        return "break"  # keep the multi-selection so it can be dragged


def dnd_motion(A, e):
    if A.mq["on"]:
        A.mq_motion(e)
        return "break"
    if not A.drag["start"] or not A.drag["row"]:
        return
    if not A.drag["active"]:
        if abs(e.x_root - A.drag["start"][0]) + abs(e.y_root - A.drag["start"][1]) < 8:
            return "break" if A.drag["hold"] else None
        if A.drag["row"] not in A.tree.selection():
            A.tree.selection_set(A.drag["row"])
        items = A.sel()
        if not items:
            return
        A.drag.update(items=items, active=True)
        top = tk.Toplevel(A.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.attributes("-alpha", 0.92)
        tk.Label(top, text=f" {items[0][0] if len(items) == 1 else str(len(items)) + ' items'} ", bg=T["accent"],
                 fg=T["onaccent"], font=("Segoe UI", A.cfg["font_size"], "bold"), padx=8, pady=4).pack()
        A.drag["top"] = top
    rx, ry = A.root.winfo_rootx(), A.root.winfo_rooty()
    if Sh and not (rx <= e.x_root <= rx + A.root.winfo_width() and ry <= e.y_root <= ry + A.root.winfo_height()):
        return A.ole_out()
    A.drag["top"].geometry(f"+{e.x_root + 16}+{e.y_root + 12}")
    A.set_hl(A.drop_target(e.x_root, e.y_root))
    return "break"


def dnd_release(A, e):
    if A.mq["on"]:
        A.mq_end(e)
        return "break"
    was, hold, row, items, top = A.drag["active"], A.drag["hold"], A.drag["row"], A.drag["items"], A.drag["top"]
    tg = A.drop_target(e.x_root, e.y_root) if was else None
    A.clear_hl()
    if top:
        top.destroy()
    A.drag.update(start=None, row=None, hold=False, active=False, items=[], top=None, hl=None)
    if was:
        if tg:
            A.run_transfer([r[1] for r in items], tg[2], move=not (e.state & 0x4))
        return "break"
    if hold and row:
        A.tree.selection_set(row)
