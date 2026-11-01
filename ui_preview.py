"""Details pane, Quick Look preview window and the text/image/thumbnail rendering behind them.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import ff_extras as X
import ff_shell as Sh
import os
import threading
import ui_extras
import time
import tkinter as tk
from tkinter import ttk
from ff_core import (IMG_EXTS, T, TEXT_EXTS, THUMB_EXTS, dir_stats, fmt_date, glyph, human_size, log_error, type_name)


def clear_preview(A):
    A.prev_txt.pack_forget()
    A.prev_lbl.configure(image="", text="")
    A.prev_lbl.pack(fill="both", expand=True)
    A.st["img"] = None


def show_glyph(A, g):
    A.clear_preview()
    A.prev_lbl.configure(text=g, font=("Segoe UI Emoji", 54))


def show_text(A, txt):
    A.prev_lbl.pack_forget()
    A.prev_txt.pack(fill="both", expand=True)
    A.prev_txt.configure(state="normal")
    A.prev_txt.delete("1.0", "end")
    A.prev_txt.insert("1.0", txt)
    A.prev_txt.configure(state="disabled")


def show_image(A, img):
    A.clear_preview()
    A.st["img"] = img
    A.prev_lbl.configure(image=img, text="")


def add_det_rows(A, pairs):
    """Append rows to the details list (media properties arrive after the first paint)."""
    base = len(A.info.grid_slaves(column=0))
    for r, (k, v) in enumerate(pairs, start=base):
        ttk.Label(A.info, text=k, style="DetKey.TLabel").grid(row=r, column=0, sticky="nw", padx=(0, 12), pady=3)
        lab = ttk.Label(A.info, text=v, style="Det.TLabel", wraplength=200, justify="left")
        lab.grid(row=r, column=1, sticky="nw", pady=3)
        A.info_labels[k] = lab


MEDIA_EXTS = set("mp3 wav flac ogg m4a aac wma mp4 mkv avi mov wmv webm flv m4v mpg mpeg".split())


def det_rows(A, pairs):
    for w in A.info.winfo_children():
        w.destroy()
    A.info_labels.clear()
    for r, (k, v) in enumerate(pairs):
        ttk.Label(A.info, text=k, style="DetKey.TLabel").grid(row=r, column=0, sticky="nw", padx=(0, 12), pady=3)
        lab = ttk.Label(A.info, text=v, style="Det.TLabel", wraplength=200, justify="left")
        lab.grid(row=r, column=1, sticky="nw", pady=3)
        A.info_labels[k] = lab


def update_details(A):
    A.st["det_after"] = None
    if not A.cfg["details_open"]:
        return
    A.st["det_tok"] += 1
    tok = A.st["det_tok"]
    s = A.sel()
    for w in A.det_btns.winfo_children():
        w.destroy()
    if not s:
        A.show_glyph("\U0001F4C2")
        A.name_l.configure(text=os.path.basename(A.st["cwd"]) or A.st["cwd"])
        n = len(A.st["rows"])
        A.det_rows([("Type", "Folder"), ("Items", f"{n:,}"), ("Location", A.st["cwd"])] if A.st["mode"] == "browse"
                 else [("Results", f"{n:,}")])
        return
    if len(s) > 1:
        A.show_glyph("\U0001F5C2")
        A.name_l.configure(text=f"{len(s)} items selected")
        known = sum(A.fsize.get(r[1], 0) if r[4] else r[2] for r in s)
        A.det_rows([("Folders", str(sum(1 for r in s if r[4]))), ("Files", str(sum(1 for r in s if not r[4]))),
                  ("Size", human_size(known) + ("+" if any(r[4] and r[1] not in A.fsize for r in s) else ""))])
        return
    name, path, size, mtime, isdir = s[0]
    A.name_l.configure(text=name)
    try:
        stt = os.stat(path)
        attrs = getattr(stt, "st_file_attributes", 0)
        ctime = stt.st_ctime
    except OSError:
        attrs, ctime = 0, 0
    flags = ", ".join(n for b, n in ((1, "Read-only"), (2, "Hidden"), (4, "System"), (32, "Archive")) if attrs & b)
    pairs = [("Type", type_name(name, isdir))]
    pairs.append(("Size", "Calculating…" if isdir else f"{human_size(size)}  ({size:,} bytes)"))
    if isdir:
        pairs.append(("Contains", "Calculating…"))
    pairs += [("Modified", fmt_date(mtime)), ("Created", fmt_date(ctime)), ("Location", os.path.dirname(path))]
    if flags:
        pairs.append(("Attributes", flags))
    lab_, tg_ = A.tags_store.get(path)
    if lab_ or tg_:
        pairs.append(("Tags", ((lab_.title() + " label   ") if lab_ else "") + ", ".join(tg_)))
    A.det_rows(pairs)
    ttk.Button(A.det_btns, text="Open", style="Det.TButton", command=A.open_item).pack(side="left", padx=(0, 6))
    ttk.Button(A.det_btns, text="Properties", style="Det.TButton", command=A.show_props).pack(side="left", padx=(0, 6))
    ttk.Button(A.det_btns, text="Copy path", style="Det.TButton", command=A.copy_path).pack(side="left")
    ext = os.path.splitext(name)[1][1:].lower()
    A.show_glyph(glyph(name, isdir))
    if not isdir and ext in MEDIA_EXTS and not X.zip_is_virtual(path):
        def media():
            rows = X.media_info(path)
            if rows:
                A.root.after(0, lambda: tok == A.st["det_tok"] and A.info.winfo_exists() and add_det_rows(A, rows))
        threading.Thread(target=media, daemon=True).start()
    if isdir and X.zip_is_virtual(path):
        A.info_labels["Size"].configure(text=human_size(size))
        A.info_labels["Contains"].configure(text="(inside an archive)")
    elif isdir:
        def work():
            res = dir_stats(path, lambda: tok != A.st["det_tok"])
            if res:
                A.fsize[path] = res[2]
                A.root.after(0, A.set_dir_info, res, tok)
        threading.Thread(target=work, daemon=True).start()
    elif ext in IMG_EXTS and size < 60_000_000:
        def work():
            try:
                from PIL import Image
                im = Image.open(path)
                im.thumbnail((300, 160))
                im = im.convert("RGBA")
                A.root.after(0, A.set_pil, im, tok)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()
    elif Sh and ext in THUMB_EXTS and not X.zip_is_virtual(path):
        def work():
            try:
                im = Sh.shell_thumbnail(path, 320)
                if im:
                    im.thumbnail((300, 160))
                    A.root.after(0, A.set_pil, im, tok)
            except Exception as e:  # noqa
                log_error(f"thumbnail {path}: {e}")
        threading.Thread(target=work, daemon=True).start()
    elif ext in TEXT_EXTS or (not ext and size < 100_000):
        def work():
            try:
                with open(path, "rb") as f:
                    data = f.read(4000)
                if b"\0" not in data:
                    txt = data.decode("utf-8", "replace")
                if ext in ("csv", "tsv"):
                    txt = ui_extras.table_text(txt, ext)
                    if ext in ("csv", "tsv"):
                        txt = ui_extras.table_text(txt, ext)
                    A.root.after(0, lambda: tok == A.st["det_tok"] and A.show_text(txt))
            except OSError:
                pass
        threading.Thread(target=work, daemon=True).start()


def set_dir_info(A, res, tok):
    if tok != A.st["det_tok"]:
        return
    files, folders, total = res
    try:
        A.info_labels["Size"].configure(text=f"{human_size(total)}  ({total:,} bytes)")
        A.info_labels["Contains"].configure(text=f"{files:,} files, {folders:,} folders")
    except (KeyError, tk.TclError):
        pass


def set_pil(A, im, tok):
    if tok != A.st["det_tok"]:
        return
    from PIL import ImageTk
    A.show_image(ImageTk.PhotoImage(im))


def schedule_details(A, _=None):
    if A.st["det_after"]:
        A.root.after_cancel(A.st["det_after"])
    A.st["det_after"] = A.root.after(80, lambda: (A.update_details(), A.sel_status()))


def close_preview(A, _=None):
    w, A.qp["win"] = A.qp["win"], None
    A.qp["tok"] += 1
    if w:
        try:
            w.destroy()
        except tk.TclError:
            pass
    A.tree.focus_set()


def pv_show(A, kind, payload=None):
    for w in (A.qp["img"], A.qp["txt"]):
        w.pack_forget()
    if kind == "text":
        A.qp["txt"].pack(fill="both", expand=True)
        A.qp["txt"].configure(state="normal")
        A.qp["txt"].delete("1.0", "end")
        A.qp["txt"].insert("1.0", payload)
        A.qp["txt"].configure(state="disabled")
    else:
        A.qp["img"].pack(fill="both", expand=True)
        if kind == "image":
            A.qp["ph"] = payload
            A.qp["img"].configure(image=payload, text="")
        else:
            A.qp["ph"] = None
            A.qp["img"].configure(image="", text=payload, font=("Segoe UI", A.cfg["font_size"] + 4), fg=T["muted"])


def render_preview(A):
    s_ = A.sel()
    if not s_ or not A.qp["win"]:
        return
    name, path, size, mtime, isdir = s_[0]
    A.qp["tok"] += 1
    tok = A.qp["tok"]
    A.qp["hdr"].configure(text=name)
    A.qp["sub"].configure(text=f"{type_name(name, isdir)}   •   " + ("" if isdir else human_size(size) + "   •   ")
                        + fmt_date(mtime) + "   •   " + os.path.dirname(path))
    maxw, maxh = A.qp["win"].winfo_width() - 60, A.qp["win"].winfo_height() - 190
    ext = os.path.splitext(name)[1][1:].lower()
    virtual = X.zip_is_virtual(path)
    A.pv_show("msg", "Loading…")

    def post(fn):
        A.root.after(0, lambda: tok == A.qp["tok"] and A.qp["win"] and fn())

    def as_image(pil):
        from PIL import ImageTk
        pil.thumbnail((maxw, maxh))
        ph = ImageTk.PhotoImage(pil.convert("RGBA"))
        post(lambda: A.pv_show("image", ph))

    if virtual:
        A.pv_show("msg", "Inside an archive — copy it out to preview it.")
    elif isdir:
        try:
            names = sorted(os.listdir(path), key=str.lower)
        except OSError as e:
            names = [f"(can't open: {e})"]
        A.pv_show("text", f"{len(names):,} items\n\n" + "\n".join(names[:200]) + ("\n…" if len(names) > 200 else ""))
    elif ext in IMG_EXTS:
        def work():
            try:
                from PIL import Image
                as_image(Image.open(path))
            except Exception:
                post(lambda: A.pv_show("msg", "Can't preview this image"))
        threading.Thread(target=work, daemon=True).start()
    elif ext in TEXT_EXTS or (not ext and size < 200_000):
        def work():
            try:
                with open(path, "rb") as f:
                    data = f.read(40000)
                if b"\0" in data:
                    raise ValueError
                txt = data.decode("utf-8", "replace")
                post(lambda: A.pv_show("text", txt))
            except Exception:
                post(lambda: A.pv_show("msg", "No preview for this file"))
        threading.Thread(target=work, daemon=True).start()
    elif ext in ("docx", "pptx", "xlsx", "odt", "odp", "ods"):
        def work():
            txt = X.office_text(path)
            post(lambda: A.pv_show("text", txt) if txt else A.pv_show("msg", "No readable text in this document"))
        threading.Thread(target=work, daemon=True).start()
    elif Sh:
        def work():
            try:
                im = Sh.shell_thumbnail(path, 1000)
            except Exception:
                im = None
            if im:
                as_image(im)
            else:
                try:
                    hx = X.hex_dump(path)
                    post(lambda: A.pv_show("text", "Binary file \u2014 first bytes:\n\n" + hx))
                except OSError:
                    post(lambda: A.pv_show("msg", f"{glyph(name, isdir)}\n\nNo preview available"))
        threading.Thread(target=work, daemon=True).start()
    else:
        A.pv_show("msg", "No preview available")


def step_preview(A, d):
    rows_ = A.st["rows"]
    cur_ = [int(i) for i in A.tree.selection()]
    i = max(0, min(len(rows_) - 1, (cur_[0] if cur_ else 0) + d))
    if rows_ and A.tree.exists(str(i)):
        A.tree.selection_set(str(i))
        A.tree.see(str(i))
        A.grid_see(i)
        A.render_preview()
    return "break"


def open_preview(A):
    if not A.sel():
        return
    if not A.qp["win"]:
        w = tk.Toplevel(A.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=T["accent"])
        sw_, sh_ = A.root.winfo_screenwidth(), A.root.winfo_screenheight()
        W, H = min(1000, sw_ - 120), min(760, sh_ - 140)
        w.geometry(f"{W}x{H}+{(sw_ - W) // 2}+{(sh_ - H) // 2}")
        inner = tk.Frame(w, bg=T["panel"])
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        fs_ = A.cfg["font_size"]
        hdr = tk.Label(inner, bg=T["panel"], fg=T["fg"], font=("Segoe UI", fs_ + 3, "bold"), anchor="w", padx=16,
                       pady=(10))
        hdr.pack(fill="x")
        sub = tk.Label(inner, bg=T["panel"], fg=T["muted"], font=("Segoe UI", fs_ - 1), anchor="w", padx=16)
        sub.pack(fill="x")
        body = tk.Frame(inner, bg=T["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        img = tk.Label(body, bg=T["bg"], fg=T["muted"])
        txt = tk.Text(body, bg=T["bg"], fg=T["fg"], bd=0, highlightthickness=0, wrap="word", padx=14, pady=10,
                      font=("Consolas", fs_), state="disabled")
        tk.Label(inner, text="Space / Esc close   •   ↑ ↓ previous / next file   •   Enter open",
                 bg=T["panel"], fg=T["muted"], font=("Segoe UI", 9)).pack(pady=(0, 8))
        A.qp.update(win=w, hdr=hdr, sub=sub, img=img, txt=txt, ph=None)
        w.bind("<space>", A.close_preview)
        w.bind("<Escape>", A.close_preview)
        w.bind("<Return>", lambda e: (A.close_preview(), A.open_item()))
        for key_, d_ in (("<Up>", -1), ("<Left>", -1), ("<Down>", 1), ("<Right>", 1)):
            w.bind(key_, lambda e, d_=d_: A.step_preview(d_))
        w.bind("<FocusOut>", lambda e: A.root.after(200, lambda: A.qp["win"] is w and w.focus_displayof() is None
                                                  and A.close_preview()))
        w.update_idletasks()
        w.focus_force()
    A.render_preview()


def quick_preview_key(A, e=None):
    if A.st["typed"] and time.time() - A.st["typed_t"] < 0.9:
        return A.type_select(e) if e is not None else None
    if A.qp["win"]:
        A.close_preview()
    else:
        A.open_preview()
    return "break"
