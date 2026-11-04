"""Thumbnail grid view: drawing, thumbnail loading/cache, keyboard and rubber-band selection.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import ff_platform
import ff_extras as X
import ff_index as I
import ff_shell as Sh
import os
import tkinter as tk
from ff_core import (IMG_EXTS, T, THUMB_EXTS, glyph)


def grid_schedule(A, _=None):
    if A.grid["on"] and not A.grid["after"]:
        A.grid["after"] = A.root.after(25, lambda: (A.grid.update(after=None), A.render_grid()))


def gscroll(A, a, b):
    A.gsb.set(a, b)
    A.grid_schedule()


def grid_icon(A, name, isdir):
    g = A.icon_box["gen"]
    if not g:
        return None
    key = ("icon", "<dir>" if isdir else os.path.splitext(name)[1][1:].lower())
    if key not in A.grid["tk"]:
        pil = g.pil("" if isdir else key[1], isdir, 56)
        if pil is None:
            A.grid["tk"][key] = False
        else:
            from PIL import ImageTk
            A.grid["tk"][key] = ImageTk.PhotoImage(pil)
    return A.grid["tk"][key] or None


def _thumb_file(A, path):
    import hashlib
    st_ = os.stat(path)
    k = hashlib.sha1(f"{os.path.normcase(path)}|{st_.st_mtime_ns}|{st_.st_size}".encode("utf-8", "replace")).hexdigest()
    return A.thumb_dir / k[:2] / (k + ".png")


def thumb_cache_get(A, path):
    try:
        f = A._thumb_file(path)
        if f.exists():
            from PIL import Image
            im = Image.open(f)
            im.load()
            return im.convert("RGBA")
    except Exception:
        pass
    return None


def thumb_cache_put(A, path, im):
    try:
        f = A._thumb_file(path)
        f.parent.mkdir(parents=True, exist_ok=True)
        im.save(f, "PNG")
    except Exception:
        pass


def thumb_cache_prune(A, limit_mb=300):
    """Keep the thumbnail cache under limit_mb by deleting the least recently used files (it only holds our own copies)."""
    try:
        files = sorted(((p.stat().st_atime, p.stat().st_size, p) for p in A.thumb_dir.rglob("*.png")), key=lambda t: t[0])
        total = sum(s for _, s, _ in files)
        for _, s, p in files:
            if total <= limit_mb * 1048576:
                break
            p.unlink()
            total -= s
    except OSError:
        pass


def grid_load_thumb(A, key, path, ext):
    if key in A.grid["tk"] or key in A.grid["pending"]:
        return
    A.grid["pending"].add(key)

    def job():
        im = None
        try:
            if ff_platform.is_online_only(path):
                return  # an online-only file is not opened (that would download it); the tile keeps its icon
            im = A.thumb_cache_get(path)
            if im is not None:
                A.root.after(0, A.grid_thumb_ready, key, im)
                return
            if ext in IMG_EXTS:
                from PIL import Image
                im = Image.open(path)
                im.thumbnail((112, 96))
                im = im.convert("RGBA")
            elif Sh and ext in THUMB_EXTS:
                im = Sh.shell_thumbnail(path, 192)
                if im:
                    im.thumbnail((112, 96))
            if im is not None:
                A.thumb_cache_put(path, im)
        except Exception:
            im = None
        A.root.after(0, A.grid_thumb_ready, key, im)

    A.gpool.submit(job)


def grid_thumb_ready(A, key, im):
    A.grid["pending"].discard(key)
    if im is None:
        A.grid["tk"][key] = False
        return
    from PIL import ImageTk
    ph = A.grid["tk"][key] = ImageTk.PhotoImage(im)
    for iid_ in A.grid["imgs"].get(key, []):
        try:
            A.gcv.itemconfigure(iid_, image=ph)
        except tk.TclError:
            pass


def render_grid(A):
    if not A.grid["on"]:
        return
    rows_ = A.st["rows"]
    W = max(A.gcv.winfo_width(), 220)
    cw, ch = A.grid["cw"], A.grid["ch"]
    cols = max(1, W // cw)
    A.grid["cols"] = cols
    nrows = (len(rows_) + cols - 1) // cols
    A.gcv.configure(scrollregion=(0, 0, W, nrows * ch + 10))
    A.gcv.delete("all")
    A.grid["imgs"] = {}
    top, H = A.gcv.canvasy(0), max(A.gcv.winfo_height(), 100)
    r0, r1 = max(0, int(top // ch) - 1), min(nrows, int((top + H) // ch) + 2)
    selected = {int(i) for i in A.tree.selection()}
    fs_ = A.cfg["font_size"]
    xoff = max(0, (W - cols * cw) // 2)
    for rr in range(r0, r1):
        for c in range(cols):
            i = rr * cols + c
            if i >= len(rows_):
                break
            name, path, size, mtime, isdir = rows_[i]
            x, y = xoff + c * cw, rr * ch
            on = i in selected
            A.gcv.create_rectangle(x + 4, y + 4, x + cw - 4, y + ch - 4, fill=T["sel"] if on else T["bg"],
                                 outline=T["accent"] if on else "", width=2)
            lab_c = A.st.get("tinfo", {}).get(path, (None, []))[0]
            if lab_c in I.LABEL_HEX:
                A.gcv.create_oval(x + cw - 26, y + 10, x + cw - 10, y + 26, fill=I.LABEL_HEX[lab_c], outline=T["bg"], width=2)
            ext = "" if isdir else os.path.splitext(name)[1][1:].lower()
            key = ("thumb", path, mtime)
            ph = A.grid["tk"].get(key) or None
            if ph is None and not isdir and (ext in IMG_EXTS or ext in THUMB_EXTS) and not X.zip_is_virtual(path):
                A.grid_load_thumb(key, path, ext)
            if ph is None:
                ph = A.grid_icon(name, isdir)
            if ph is not None:
                iid_ = A.gcv.create_image(x + cw // 2, y + 64, image=ph)
                A.grid["imgs"].setdefault(key, []).append(iid_)
            else:
                A.gcv.create_text(x + cw // 2, y + 64, text=glyph(name, isdir), font=("Segoe UI Emoji", 32),
                                fill=T["muted"])
            label = name if len(name) <= 34 else name[:31] + "…"
            A.gcv.create_text(x + cw // 2, y + 128, text=label, width=cw - 14, fill=T["dir"] if isdir else T["fg"],
                            font=("Segoe UI", max(fs_ - 1, 8)), justify="center")


def grid_index_at(A, x, y):
    cw, ch, cols = A.grid["cw"], A.grid["ch"], A.grid["cols"]
    W = max(A.gcv.winfo_width(), 220)
    cx = A.gcv.canvasx(x) - max(0, (W - cols * cw) // 2)
    cy = A.gcv.canvasy(y)
    if cx < 0:
        return None
    col, row = int(cx // cw), int(cy // ch)
    i = row * cols + col
    return i if col < cols and 0 <= i < len(A.st["rows"]) else None


def grid_see(A, i):
    if not A.grid["on"]:
        return
    ch, cols = A.grid["ch"], A.grid["cols"]
    y0, y1 = (i // cols) * ch, (i // cols) * ch + ch
    top, H = A.gcv.canvasy(0), A.gcv.winfo_height()
    total = max(1, ((len(A.st["rows"]) + cols - 1) // cols) * ch + 10)
    if y0 < top:
        A.gcv.yview_moveto(y0 / total)
    elif y1 > top + H:
        A.gcv.yview_moveto((y1 - H) / total)
    A.grid_schedule()


def grid_select(A, i, extend=False, toggle=False):
    if i is None or not A.tree.exists(str(i)):
        return
    if toggle:
        A.tree.selection_toggle(str(i))
    elif extend and A.grid["last"] is not None:
        a, b = sorted((A.grid["last"], i))
        A.tree.selection_set([str(k) for k in range(a, b + 1) if A.tree.exists(str(k))])
    else:
        A.tree.selection_set(str(i))
    if not extend:
        A.grid["last"] = i
    A.tree.focus(str(i))
    A.grid_see(i)


def grid_tiles_in(A, x0, y0, x1, y1):
    cw, ch, cols = A.grid["cw"], A.grid["ch"], A.grid["cols"]
    W = max(A.gcv.winfo_width(), 220)
    off = max(0, (W - cols * cw) // 2)
    c0, c1 = sorted((int((x0 - off) // cw), int((x1 - off) // cw)))
    r0, r1 = sorted((int(y0 // ch), int(y1 // ch)))
    out = []
    for r_ in range(r0, r1 + 1):
        for c_ in range(max(0, c0), min(cols - 1, c1) + 1):
            i_ = r_ * cols + c_
            if 0 <= i_ < len(A.st["rows"]):
                out.append(str(i_))
    return out


def grid_motion(A, e):
    if not A.gmq["on"]:
        return
    x0, y0 = A.gmq["x"], A.gmq["y"]
    cx, cy = A.gcv.canvasx(e.x), A.gcv.canvasy(e.y)
    if not A.gmq["moved"] and abs(cx - x0) + abs(cy - y0) < 4:
        return
    A.gmq["moved"] = True
    if e.y < 20:
        A.gcv.yview_scroll(-1, "units")
    elif e.y > A.gcv.winfo_height() - 6:
        A.gcv.yview_scroll(1, "units")
    cy = A.gcv.canvasy(e.y)
    want = set(A.gmq["base"]) | set(A.grid_tiles_in(x0, y0, cx, cy))
    if want != A.gmq.get("last"):
        A.gmq["last"] = want
        A.tree.selection_set(list(want))
    A.mq_rect(A.gcv, int(x0 - A.gcv.canvasx(0)), int(y0 - A.gcv.canvasy(0)), e.x, e.y)


def grid_release(A, e):
    if A.gmq["on"]:
        A.mq_clear()
        A.gmq["on"] = False


def grid_click(A, e):
    A.gcv.focus_set()
    i = A.grid_index_at(e.x, e.y)
    if i is None:
        A.gmq.update(on=True, moved=False, x=A.gcv.canvasx(e.x), y=A.gcv.canvasy(e.y), last=None, base=set(A.tree.selection()) if e.state & 0x5 else set())
        if not (e.state & 0x5):
            A.tree.selection_set(())
    else:
        A.grid_select(i, extend=bool(e.state & 0x1), toggle=bool(e.state & 0x4))


def grid_key(A, d):
    def h(e=None):
        cur_ = [int(i) for i in A.tree.selection()]
        n = len(A.st["rows"])
        if not n:
            return "break"
        i = (cur_[0] if cur_ else -1) + d
        A.grid_select(max(0, min(n - 1, i)))
        return "break"
    return h


def grid_popup(A, e):
    i = A.grid_index_at(e.x, e.y)
    if i is not None and str(i) not in A.tree.selection():
        A.grid_select(i)
    import types
    A.popup(types.SimpleNamespace(widget=A.pane_frames[0][1], y=-1, x_root=e.x_root, y_root=e.y_root, state=e.state))


def toggle_grid(A, _=None, value=None, store=True):
    """Switch between list and thumbnails. store=False applies a remembered view without making it the new default."""
    on = (not A.grid["on"]) if value is None else value
    if on and A.pane["split"]:
        A.status.set("Thumbnail grid is for single-pane view — turn Split off first")
        A.grid_var.set(False)
        return
    A.grid["on"] = on
    if store and not A.remember_view(grid=on):  # (with per-folder memory on, the choice belongs to this folder only)
        A.save_cfg(view_grid=on)
    A.grid_var.set(on)
    if on:
        A.pane_frames[0][0].grid_forget()
        A.gridf.grid(row=0, column=0, sticky="nsew")
        A.gcv.update_idletasks()
        A.render_grid()
        A.gcv.focus_set()
    else:
        A.gridf.grid_forget()
        A.pane_frames[0][0].grid(row=0, column=0, sticky="nsew")
        A.tree.focus_set()
