"""Details pane, Quick Look preview window and the text/image/thumbnail rendering behind them.

Every function takes `A` first: a live view of the main window (ff_app.App) giving access to its state and helpers.
"""
import ff_extras as X
import ff_platform
import ff_shell as Sh
import os
import re
import threading
import ui_extras
import ui_notes
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


AUDIO_EXTS = set("mp3 wav wma m4a aac flac ogg mid midi".split())
MD_EXTS = {"md", "markdown"}


def md_insert(t, text, fs):
    """Show Markdown in a Text widget as formatted text (headings, bold, italic, code, lists, quotes, links as their label)."""
    base = "Segoe UI"
    t.configure(font=(base, fs + 1), wrap="word")
    t.tag_configure("h1", font=(base, fs + 9, "bold"), spacing1=12, spacing3=4)
    t.tag_configure("h2", font=(base, fs + 5, "bold"), spacing1=10, spacing3=3)
    t.tag_configure("h3", font=(base, fs + 2, "bold"), spacing1=8, spacing3=2)
    t.tag_configure("bold", font=(base, fs + 1, "bold"))
    t.tag_configure("italic", font=(base, fs + 1, "italic"))
    t.tag_configure("code", font=("Consolas", fs), background=T["raised"])
    t.tag_configure("quote", foreground=T["muted"], lmargin1=18, lmargin2=18, font=(base, fs + 1, "italic"))
    t.tag_configure("link", foreground=T["accent"], underline=True)
    t.tag_configure("rule", foreground=T["muted"])
    tok = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|\[[^\]]+\]\([^)]+\))")

    def inline(line, base_tag=None):
        for part in tok.split(line):
            if not part:
                continue
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                t.insert("end", part[2:-2], ("bold",) + ((base_tag,) if base_tag else ()))
            elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                t.insert("end", part[1:-1], ("code",))
            elif part.startswith("*") and part.endswith("*") and len(part) > 2:
                t.insert("end", part[1:-1], ("italic",))
            elif part.startswith("[") and "](" in part and part.endswith(")"):
                t.insert("end", part[1:part.index("](")], ("link",))
            else:
                t.insert("end", part, (base_tag,) if base_tag else ())
    fenced = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            t.insert("end", line + chr(10), ("code",))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            inline(m.group(2), f"h{min(len(m.group(1)), 3)}")
        elif re.match(r"^\s*[-*+]\s+", line):
            inline(re.sub(r"^(\s*)[-*+]\s+", lambda mm: mm.group(1) + "  \u2022  ", line))
        elif line.startswith(">"):
            inline(line.lstrip("> ").strip(), "quote")
        elif re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line):
            t.insert("end", "\u2500" * 50, ("rule",))
        else:
            inline(line)
        t.insert("end", chr(10))


def _clear_bar(A):
    bar = A.qp.get("bar")
    if bar is not None:
        for w in bar.winfo_children():
            w.destroy()
    A.qp["pdf"] = None


def pdf_page(A, page):
    """Quick look of a PDF: draw page `page` (0-based) with pypdfium2 and show 'Page n of N' with Previous / Next buttons."""
    st = A.qp.get("pdf")
    if not st or not A.qp["win"]:
        return
    tok = A.qp["tok"]
    maxw, maxh = A.qp["win"].winfo_width() - 60, A.qp["win"].winfo_height() - 215

    def work():
        try:
            import pypdfium2 as pdfium
            from PIL import ImageTk
            pdf = pdfium.PdfDocument(st["path"])
            n = len(pdf)
            pg = max(0, min(page, n - 1))
            w_, h_ = pdf[pg].get_size()
            im = pdf[pg].render(scale=max(0.3, min(3.0, maxw / w_, maxh / h_))).to_pil()
            pdf.close()
            ph = ImageTk.PhotoImage(im.convert("RGBA"))
        except Exception as e:  # noqa - password protected, damaged, ...
            msg = "Can't preview this PDF" + chr(10) + "(" + str(e)[:80] + ")"
            A.root.after(0, lambda: tok == A.qp["tok"] and A.qp["win"] and A.pv_show("msg", msg))
            return

        def show():
            if tok != A.qp["tok"] or not A.qp["win"]:
                return
            st.update(page=pg, n=n)
            A.pv_show("image", ph)
            ui = A.qp.get("pdfui")
            if ui:
                ui["lab"].configure(text=f"Page {pg + 1} of {n}")
                ui["prev"].configure(state="normal" if pg > 0 else "disabled")
                ui["next"].configure(state="normal" if pg < n - 1 else "disabled")
        A.root.after(0, show)
    threading.Thread(target=work, daemon=True).start()


def step_pdf(A, d):
    st = A.qp.get("pdf")
    if st:
        pdf_page(A, st["page"] + d)


def _pdf_bar(A):
    bar = A.qp["bar"]
    prev = ttk.Button(bar, text="\u25C0 Previous page", command=lambda: step_pdf(A, -1))
    nxt = ttk.Button(bar, text="Next page \u25B6", command=lambda: step_pdf(A, 1))
    lab = tk.Label(bar, text="", bg=T["panel"], fg=T["fg"])
    prev.pack(side="left")
    nxt.pack(side="left", padx=8)
    lab.pack(side="left", padx=8)
    tk.Label(bar, text="(PageUp / PageDown also turn pages)", bg=T["panel"], fg=T["muted"], font=("Segoe UI", 9)).pack(side="left", padx=8)
    A.qp["pdfui"] = {"prev": prev, "next": nxt, "lab": lab}


def _ms(ms):
    s = int(ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


def audio_panel(A, path, tok):
    """The small player in Quick look: Play / Pause, Stop, position; the tags (title, artist, length) are listed below."""
    bar = A.qp["bar"]
    play = ttk.Button(bar, text="\u25B6 Play", style="Accent.TButton")
    stop = ttk.Button(bar, text="\u25A0 Stop")
    lab = tk.Label(bar, text="", bg=T["panel"], fg=T["fg"])
    play.pack(side="left")
    stop.pack(side="left", padx=8)
    lab.pack(side="left", padx=8)

    def tick():
        if tok != A.qp["tok"] or not A.qp["win"]:
            return
        mode, pos, length = ff_platform.audio_status() if ff_platform.audio_current() == path else ("closed", 0, 0)
        if mode in ("playing", "paused"):
            lab.configure(text=f"{_ms(pos)} / {_ms(length)}" + ("   (paused)" if mode == "paused" else ""))
            play.configure(text="\u23F8 Pause" if mode == "playing" else "\u25B6 Resume")
            A.root.after(400, tick)
        else:
            play.configure(text="\u25B6 Play")
            if mode == "stopped" and ff_platform.audio_current() == path:
                ff_platform.audio_close()

    def toggle():
        mode = ff_platform.audio_status()[0] if ff_platform.audio_current() == path else "closed"
        try:
            if mode == "playing":
                ff_platform.audio_pause()
            elif mode == "paused":
                ff_platform.audio_resume()
            else:
                ff_platform.audio_open(path)
                ff_platform.audio_play()
        except OSError as e:
            lab.configure(text=f"Windows can't play this format here ({str(e)[:50]}). Press Enter to open it in your player.")
            return
        tick()

    def stop_it():
        ff_platform.audio_close()
        lab.configure(text="")
        play.configure(text="\u25B6 Play")
    play.configure(command=toggle)
    stop.configure(command=stop_it)

    def info():
        rows = X.media_info(path) or []
        txt = "\n".join(f"{k}:  {v}" for k, v in rows) or "No tag information in this file."
        A.root.after(0, lambda: tok == A.qp["tok"] and A.qp["win"] and A.pv_show("text", txt))
    A.pv_show("msg", "\u266B")
    threading.Thread(target=info, daemon=True).start()


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
    pairs += ui_notes.detail_rows(A, path)
    lab_, tg_ = A.tags_store.get(path)
    if lab_ or tg_:
        pairs.append(("Tags", ((lab_.title() + " label   ") if lab_ else "") + ", ".join(tg_)))
    A.det_rows(pairs)
    ttk.Button(A.det_btns, text="Open", style="Det.TButton", command=A.open_item).pack(side="left", padx=(0, 6))
    ttk.Button(A.det_btns, text="Properties", style="Det.TButton", command=A.show_props).pack(side="left", padx=(0, 6))
    ttk.Button(A.det_btns, text="Copy path", style="Det.TButton", command=A.copy_path).pack(side="left")
    ext = os.path.splitext(name)[1][1:].lower()
    if ff_platform.audio_current() and ff_platform.audio_current() != path:
        ff_platform.audio_close()
    if not isdir and ext in AUDIO_EXTS and not X.zip_is_virtual(path):
        play_b = ttk.Button(A.det_btns, text="\u25B6 Play", style="Det.TButton")
        play_b.pack(side="left", padx=(6, 0))

        def play_toggle():
            try:
                if ff_platform.audio_current() == path and ff_platform.audio_status()[0] == "playing":
                    ff_platform.audio_close()
                    play_b.configure(text="\u25B6 Play")
                else:
                    ff_platform.audio_open(path)
                    ff_platform.audio_play()
                    play_b.configure(text="\u25A0 Stop")
            except OSError as e:
                A.status.set(f"Windows can't play this format here: {e}")
        play_b.configure(command=play_toggle)
    A.show_glyph(glyph(name, isdir))
    online = not isdir and ff_platform.is_online_only(path)
    if online:
        A.det_rows([("Status", "Online only: the data is in the cloud or on your phone, so Pinefiles did not open it (that would download it). "
                              "Change this in Customize.")])
    if not isdir and not online and ext in MEDIA_EXTS and not X.zip_is_virtual(path):
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
    elif online:
        pass  # (see the status row above)
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
    ff_platform.audio_close()
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
    if kind in ("text", "md"):
        A.qp["txt"].pack(fill="both", expand=True)
        A.qp["txt"].configure(state="normal", font=("Consolas", A.cfg["font_size"]))
        A.qp["txt"].delete("1.0", "end")
        if kind == "md":
            md_insert(A.qp["txt"], payload, A.cfg["font_size"])
        else:
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
    ff_platform.audio_close()  # another file: the previous sound stops
    _clear_bar(A)
    A.pv_show("msg", "Loading…")
    if not isdir and not virtual and ext in MEDIA_EXTS:  # duration, frame size ... next to the date in the header
        def media_sub():
            rows = X.media_info(path) or []
            extra = "   \u2022   ".join(str(v) for _k, v in rows[:3])
            if extra:
                post(lambda: A.qp["sub"].configure(text=A.qp["sub"].cget("text") + "   \u2022   " + extra))
        threading.Thread(target=media_sub, daemon=True).start()

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
    elif ff_platform.is_online_only(path):
        A.pv_show("msg", "Online only: the data is in the cloud or on your phone.\nOpen the file (Enter) to download it; Pinefiles does not do that by itself.")
    elif ext == "pdf":
        A.qp["pdf"] = {"path": path, "page": 0, "n": 0}
        _pdf_bar(A)
        pdf_page(A, 0)
    elif ext in AUDIO_EXTS:
        audio_panel(A, path, tok)
    elif ext in MD_EXTS:
        def work():
            try:
                with open(path, "rb") as f:
                    txt = f.read(120000).decode("utf-8", "replace")
                post(lambda: A.pv_show("md", txt))
            except OSError:
                post(lambda: A.pv_show("msg", "No preview for this file"))
        threading.Thread(target=work, daemon=True).start()
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
        bar = tk.Frame(inner, bg=T["panel"])
        bar.pack(fill="x", padx=16)
        body = tk.Frame(inner, bg=T["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        img = tk.Label(body, bg=T["bg"], fg=T["muted"])
        txt = tk.Text(body, bg=T["bg"], fg=T["fg"], bd=0, highlightthickness=0, wrap="word", padx=14, pady=10,
                      font=("Consolas", fs_), state="disabled")
        tk.Label(inner, text="Space / Esc close   •   ↑ ↓ previous / next file   •   Enter open",
                 bg=T["panel"], fg=T["muted"], font=("Segoe UI", 9)).pack(pady=(0, 8))
        A.qp.update(win=w, hdr=hdr, sub=sub, img=img, txt=txt, ph=None, bar=bar, pdf=None)
        w.bind("<space>", A.close_preview)
        w.bind("<Escape>", A.close_preview)
        w.bind("<Return>", lambda e: (A.close_preview(), A.open_item()))
        w.bind("<Prior>", lambda e: step_pdf(A, -1))
        w.bind("<Next>", lambda e: step_pdf(A, 1))
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
