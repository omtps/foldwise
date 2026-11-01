"""Mini-games for the waiting time.

A small chip sits in the corner of the Tools area at all times (it says so louder while a tool is busy); click it to play. The games run on the
Tk timer only (the scans work in their own threads), so playing never slows or interrupts a scan. The panel floats over the corner, can
be minimised, and when the tool finishes it says so without taking your game away.
The game rules are plain classes (Catcher, Stack, Match) so the tests can play them without a window.
"""
import random
import time
import tkinter as tk

from ff_core import T

W, H = 480, 220
SHAPES = ["#3584e4", "#e66100", "#2ec27e", "#c061cb", "#f5c211", "#e5484d"]
GOOD, BAD = "#2ec27e", "#e5484d"


# ------------------------------------------------------------------------------------------------ rules (no Tk in here)
class Catcher:
    """Files fall: catch them with the folder, dodge the bugs. Missing a file or catching a bug costs one of 5 lives."""
    name = "Catch"
    hint = "Move the mouse (or ← →) to catch files. Dodge the red bugs. Missing a file or hitting a bug costs a life."
    higher_is_better = True

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.reset()

    def reset(self):
        self.x, self.items, self.score, self.lives = W / 2, [], 0, 5
        self.t, self._next, self.over = 0.0, 10.0, False

    def move_to(self, x):
        self.x = max(30, min(W - 30, x))

    def nudge(self, d):
        self.move_to(self.x + d * 28)

    def step(self, dt=1.0):
        if self.over:
            return
        self.t += dt
        if self.t >= self._next:
            bug = self.rng.random() < min(0.45, 0.22 + self.score / 250)
            speed = min(6.5, 2.2 + self.score * 0.05) * self.rng.uniform(0.85, 1.15)
            self.items.append([self.rng.uniform(20, W - 20), -8.0, speed, bug, self.rng.randrange(5)])
            self._next = self.t + max(16, 44 - self.score * 0.6)
        keep = []
        for it in self.items:
            it[1] += it[2] * dt
            if H - 30 <= it[1] <= H - 6 and abs(it[0] - self.x) <= 38:
                if it[3]:
                    self.lives -= 1
                else:
                    self.score += 1
            elif it[1] > H + 6:
                if not it[3]:
                    self.lives -= 1
            else:
                keep.append(it)
        self.items = keep
        if self.lives <= 0:
            self.over = True

    def click(self, x, y):
        if self.over:
            self.reset()


class Stack:
    """A block slides back and forth; drop it on the tower. Whatever hangs over is cut off, so the tower gets thinner."""
    name = "Stack"
    hint = "Click (or press Space) to drop the sliding block. Line it up: what overhangs is cut away."
    higher_is_better = True
    BH = 16

    def __init__(self, rng=None):
        self.reset()

    def reset(self):
        self.layers = [((W - 170) / 2, 170.0)]
        self.w, self.pos, self.dir, self.speed = 170.0, 0.0, 1, 3.0
        self.score, self.over = 0, False

    def step(self, dt=1.0):
        if self.over:
            return
        self.pos += self.dir * self.speed * dt
        if self.pos <= 0:
            self.pos, self.dir = 0.0, 1
        elif self.pos >= W - self.w:
            self.pos, self.dir = W - self.w, -1

    def drop(self):
        if self.over:
            self.reset()
            return
        tx, tw = self.layers[-1]
        left, right = max(self.pos, tx), min(self.pos + self.w, tx + tw)
        if right - left <= 2:
            self.over = True
            return
        if abs(self.pos - tx) < 5:  # a perfect drop keeps the full width
            left, right = tx, tx + tw
        self.layers.append((left, right - left))
        self.w = right - left
        self.score += 1
        self.speed = min(9.0, 3.0 + self.score * 0.2)
        self.pos = min(self.pos, W - self.w)

    def click(self, x, y):
        self.drop()


class Match:
    """Six pairs of shapes face down. Turn two at a time; fewer moves is better."""
    name = "Match"
    hint = "Turn two cards at a time and find all 6 pairs in as few moves as you can."
    higher_is_better = False
    COLS, CW, CH, GAP = 6, 62, 70, 10

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.reset()

    def reset(self):
        ids = list(range(6)) * 2
        self.rng.shuffle(ids)
        self.cards, self.state, self.up = ids, [0] * 12, []
        self.moves, self.pending, self.over = 0, None, False

    @property
    def score(self):
        return self.moves

    def step(self, dt=1.0):
        pass

    def flip(self, i):
        if self.over or self.pending or not (0 <= i < 12) or self.state[i] != 0:
            return False
        self.state[i] = 1
        self.up.append(i)
        if len(self.up) == 2:
            self.moves += 1
            a, b = self.up
            if self.cards[a] == self.cards[b]:
                self.state[a] = self.state[b] = 2
                self.up = []
                self.over = all(s == 2 for s in self.state)
            else:
                self.pending = (a, b)
        return True

    def resolve(self):
        if self.pending:
            for i in self.pending:
                self.state[i] = 0
        self.pending, self.up = None, []

    def origin(self):
        return (W - (self.COLS * self.CW + (self.COLS - 1) * self.GAP)) / 2, 44

    def cell_rect(self, i):
        ox, oy = self.origin()
        c, r = i % self.COLS, i // self.COLS
        x = ox + c * (self.CW + self.GAP)
        y = oy + r * (self.CH + self.GAP)
        return x, y, x + self.CW, y + self.CH

    def cell_at(self, x, y):
        for i in range(12):
            x0, y0, x1, y1 = self.cell_rect(i)
            if x0 <= x <= x1 and y0 <= y <= y1:
                return i
        return None

    def click(self, x, y):
        if self.over:
            self.reset()
            return
        i = self.cell_at(x, y)
        if i is not None:
            self.flip(i)


GAMES = [Catcher, Stack, Match]


# ------------------------------------------------------------------------------------------------ drawing
def _shape(cv, k, cx, cy, r, color):
    if k == 0:
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")
    elif k == 1:
        cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")
    elif k == 2:
        cv.create_polygon(cx, cy - r, cx + r, cy + r, cx - r, cy + r, fill=color, outline="")
    elif k == 3:
        cv.create_polygon(cx, cy - r - 2, cx + r + 2, cy, cx, cy + r + 2, cx - r - 2, cy, fill=color, outline="")
    elif k == 4:
        cv.create_rectangle(cx - r, cy - r / 3, cx + r, cy + r / 3, fill=color, outline="")
        cv.create_rectangle(cx - r / 3, cy - r, cx + r / 3, cy + r, fill=color, outline="")
    else:
        pts = []
        for j in range(6):
            import math
            a = math.pi / 3 * j
            pts += [cx + (r + 2) * math.cos(a), cy + (r + 2) * math.sin(a)]
        cv.create_polygon(*pts, fill=color, outline="")


def draw(cv, g, mode="play"):
    cv.delete("all")
    if isinstance(g, Catcher):
        for x, y, _v, bug, c in g.items:
            if bug:
                cv.create_oval(x - 8, y - 7, x + 8, y + 7, fill=BAD, outline="")
                for dx in (-10, -5, 5, 10):
                    cv.create_line(x + dx / 2, y, x + dx, y + 8, fill=BAD, width=2)
            else:
                cv.create_rectangle(x - 7, y - 9, x + 7, y + 9, fill=SHAPES[c], outline="")
                cv.create_rectangle(x - 4, y - 4, x + 4, y - 2, fill=T["bg"], outline="")
        x = g.x
        cv.create_polygon(x - 36, H - 28, x - 14, H - 28, x - 8, H - 34, x + 8, H - 34, x + 14, H - 28, x + 36, H - 28, x + 32, H - 6, x - 32, H - 6,
                          fill=T["accent"], outline="")
        cv.create_text(10, 8, anchor="nw", fill=T["fg"], font=("Segoe UI", 12, "bold"), text=f"{g.score}")
        cv.create_text(W - 10, 8, anchor="ne", fill=BAD, font=("Segoe UI", 12), text="♥ " * g.lives)
    elif isinstance(g, Stack):
        n = len(g.layers)
        shift = max(0, n - 9) * g.BH
        for j, (x, w) in enumerate(g.layers):
            y = H - (j + 1) * g.BH + shift
            cv.create_rectangle(x, y, x + w, y + g.BH - 2, fill=SHAPES[j % 6], outline="")
        if not g.over:
            y = H - (n + 1) * g.BH + shift
            cv.create_rectangle(g.pos, y, g.pos + g.w, y + g.BH - 2, fill=T["accent"], outline="")
        cv.create_text(10, 8, anchor="nw", fill=T["fg"], font=("Segoe UI", 12, "bold"), text=f"{g.score}")
    else:
        for i in range(12):
            x0, y0, x1, y1 = g.cell_rect(i)
            if g.state[i] == 0:
                cv.create_rectangle(x0, y0, x1, y1, fill=T["accent"], outline="")
            else:
                cv.create_rectangle(x0, y0, x1, y1, fill=T["raised"] if g.state[i] == 1 else T["bg"], outline=T["line"])
                _shape(cv, g.cards[i], (x0 + x1) / 2, (y0 + y1) / 2, 14, SHAPES[g.cards[i]])
        cv.create_text(10, 8, anchor="nw", fill=T["fg"], font=("Segoe UI", 12, "bold"), text=f"{g.moves} moves")
    if mode in ("ready", "paused") and not g.over:
        cv.create_rectangle(W / 2 - 130, H / 2 - 30, W / 2 + 130, H / 2 + 30, fill=T["panel"], outline=T["line"])
        cv.create_text(W / 2, H / 2 - 9, fill=T["fg"], font=("Segoe UI", 13, "bold"), text="Click to start" if mode == "ready" else "Paused")
        cv.create_text(W / 2, H / 2 + 14, fill=T["muted"], font=("Segoe UI", 10), text="" if mode == "ready" else "Move the mouse back to go on")
    if g.over:
        cv.create_rectangle(W / 2 - 120, H / 2 - 34, W / 2 + 120, H / 2 + 34, fill=T["panel"], outline=T["line"])
        cv.create_text(W / 2, H / 2 - 12, fill=T["fg"], font=("Segoe UI", 13, "bold"),
                       text="You did it!" if isinstance(g, Match) else "Game over")
        cv.create_text(W / 2, H / 2 + 12, fill=T["muted"], font=("Segoe UI", 10), text="Click to play again")


# ------------------------------------------------------------------------------------------------ the panel
class GamePanel(tk.Frame):
    """A small floating game window. A game starts on the first click, pauses when the pointer leaves it or the panel was hidden, can be
    dragged by its title bar and keeps its state while you move between tools."""

    def __init__(self, parent, A, on_minimize=None, on_close=None, floating=True):
        super().__init__(parent, bg=T["raised"], highlightthickness=1, highlightbackground=T["line"])
        self.A = A
        self.floating = floating
        self.games = {cls.name: cls() for cls in GAMES}
        self.game = self.games["Catch"]
        self.started = {n: False for n in self.games}
        self.paused = False
        self._scored = {}
        self._was_hidden = False
        self._resolve_job = None
        self.head = head = tk.Frame(self, bg=T["raised"], cursor="fleur" if floating else "")
        head.pack(fill="x", padx=8, pady=(6, 2))
        self.tabs = {}
        for name in self.games:
            b = tk.Label(head, text=name, bg=T["raised"], fg=T["muted"], font=("Segoe UI", 10, "bold"), padx=8, pady=2, cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, n=name: self.pick(n))
            self.tabs[name] = b
        self.info = tk.Label(head, bg=T["raised"], fg=T["muted"], font=("Segoe UI", 9))
        self.info.pack(side="left", padx=10)
        if on_close:
            x = tk.Label(head, text="✕", bg=T["raised"], fg=T["muted"], cursor="hand2", padx=6)
            x.pack(side="right")
            x.bind("<Button-1>", lambda e: on_close())
        if on_minimize:
            m = tk.Label(head, text="–", bg=T["raised"], fg=T["muted"], cursor="hand2", padx=6)
            m.pack(side="right")
            m.bind("<Button-1>", lambda e: on_minimize())
        if floating:  # drag the panel by its title bar so it never has to cover what you need
            for w in (head, self.info):
                w.bind("<ButtonPress-1>", self._drag_start)
                w.bind("<B1-Motion>", self._drag_move)
        self.note = tk.Label(self, bg=T["raised"], fg=T["muted"], font=("Segoe UI", 9), anchor="w", wraplength=W)
        self.note.pack(fill="x", padx=10)
        self.cv = tk.Canvas(self, width=W, height=H, bg=T["bg"], highlightthickness=0, cursor="hand2")
        self.cv.pack(padx=8, pady=(2, 8))
        self.cv.bind("<Motion>", self._motion)
        self.cv.bind("<Enter>", self._enter)
        self.cv.bind("<Leave>", self._leave)
        self.cv.bind("<Button-1>", self._click)
        for w in (self.cv, self, head):  # the wheel must not scroll the tool page behind the game
            w.bind("<MouseWheel>", lambda e: "break")
        for k, d in (("<Left>", -1), ("<Right>", 1), ("a", -1), ("d", 1)):
            self.cv.bind(k, lambda e, d=d: self._key(d))
        self.cv.bind("<space>", lambda e: self._click(e))
        self._last = time.time()
        self._job = None
        self.pick("Catch")
        self._tick()

    # ---- dragging
    def _drag_start(self, e):
        self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _drag_move(self, e):
        host = self.master
        nx = max(0, min(host.winfo_width() - self.winfo_width(), e.x_root - self._drag[0]))
        ny = max(0, min(host.winfo_height() - self.winfo_height(), e.y_root - self._drag[1]))
        self.place(relx=0, rely=0, anchor="nw", x=nx, y=ny)

    # ---- games
    def best(self, name):
        return (self.A.cfg.get("game_best") or {}).get(name)

    def pick(self, name):
        self.game = self.games[name]
        for n, b in self.tabs.items():
            b.configure(fg=T["fg"] if n == name else T["muted"])
        self.note.configure(text=self.game.hint, fg=T["muted"])
        if isinstance(self.game, Match):
            self.started[name] = True  # no clock to wait for
        self._update_info()

    def reset_note(self):
        self.note.configure(text=self.game.hint, fg=T["muted"])

    def _update_info(self):
        b = self.best(self.game.name)
        self.info.configure(text=f"best: {b}" if b is not None else "")

    def _running(self):
        g = self.game
        return self.started[g.name] and not self.paused and not g.over

    def _enter(self, e):
        self.paused = False

    def _leave(self, e):
        if self.started[self.game.name] and not self.game.over and not isinstance(self.game, Match):
            self.paused = True

    def _motion(self, e):
        self.paused = False
        if isinstance(self.game, Catcher) and self._running():
            self.game.move_to(e.x)

    def _key(self, d):
        if isinstance(self.game, Catcher) and self._running():
            self.game.nudge(d)

    def _click(self, e):
        self.cv.focus_set()
        g = self.game
        x, y = getattr(e, "x", 0), getattr(e, "y", 0)
        self.paused = False
        if g.over:  # a click after the end: play again, but wait for the next click to start
            g.click(x, y)
            self._scored.pop(g.name, None)
            self.started[g.name] = isinstance(g, Match)
            return
        if not self.started[g.name]:
            self.started[g.name] = True
            if isinstance(g, Catcher):
                g.move_to(x)
            return
        if isinstance(g, Catcher):
            g.move_to(x)
        g.click(x, y)
        if isinstance(g, Match) and g.pending and self._resolve_job is None:
            self._resolve_job = self.after(650, self._resolve)

    def _resolve(self):
        self._resolve_job = None
        self.games["Match"].resolve()

    def _record(self):
        g = self.game
        if not g.over or self._scored.get(g.name):
            return
        self._scored[g.name] = True
        best = self.best(g.name)
        if best is None or (g.score > best if g.higher_is_better else g.score < best):
            try:
                self.A.save_cfg(game_best={**(self.A.cfg.get("game_best") or {}), g.name: g.score})
            except Exception:  # noqa - a high score is never worth an error
                pass
            self._update_info()

    def _tick(self):
        if not self.winfo_exists():
            return
        now = time.time()
        dt = min(3.0, (now - self._last) / 0.033)
        self._last = now
        mapped = self.cv.winfo_ismapped()
        if mapped:
            if self._was_hidden:  # came back from another tool / the file view: wait for the pointer before going on
                self._was_hidden = False
                if self.started[self.game.name] and not isinstance(self.game, Match):
                    self.paused = True
            if self._running():
                self.game.step(dt)
            mode = "ready" if not self.started[self.game.name] else "paused" if self.paused and not self.game.over else "play"
            draw(self.cv, self.game, mode)
            self._record()
        else:
            self._was_hidden = True
        self._job = self.after(33 if mapped else 300, self._tick)

    def tool_finished(self):
        self.note.configure(text="✔ The tool has finished. Close the game (✕) to see its results; nothing was interrupted.", fg=GOOD)

    def destroy(self):
        for j in (self._job, self._resolve_job):
            if j is not None:
                try:
                    self.after_cancel(j)
                except tk.TclError:
                    pass
        super().destroy()


# ------------------------------------------------------------------------------------------------ the chip that offers it in every tool
_G = {"chip": None, "panel": None, "page": None, "chip_label": None}
CORNER = dict(relx=1, rely=0, anchor="ne", x=-18, y=12)  # top right: the Close / Back buttons of the tools are at the bottom


def hide():
    """Remove the chip and the game (the setting 'Offer a mini-game' was turned off)."""
    for k in ("chip", "panel"):
        _drop(k)
    _G["page"] = None


def _drop(k):
    w = _G[k]
    if w is not None:
        try:
            w.destroy()
        except tk.TclError:
            pass
    _G[k] = None


def _chip(A, host, st):
    fr = tk.Frame(host, bg=T["accent"], cursor="hand2")
    lab = tk.Label(fr, text="▶  Play a quick game", bg=T["accent"], fg="#ffffff", font=("Segoe UI", 10, "bold"), padx=14, pady=6)
    lab.pack(side="left")
    lab.bind("<Button-1>", lambda e: _open_panel(A, host, st))
    fr.bind("<Button-1>", lambda e: _open_panel(A, host, st))
    fr.place(**CORNER)
    fr.lift()
    _G["chip"], _G["chip_label"] = fr, lab


def _open_panel(A, host, st):
    _drop("chip")
    if _G["panel"] is None or not _G["panel"].winfo_exists():
        p = GamePanel(host, A, on_minimize=lambda: (_drop("panel"), _chip(A, host, st)),
                      on_close=lambda: (_drop("panel"), _chip(A, host, st)))
        p.place(**CORNER)
        _G["panel"] = p
    _G["panel"].lift()


def watch(A, host, page, slow_now):
    """Called every 400 ms for the visible tool: the games are always one click away in the corner (the chip says so louder while the
    tool is busy), and a game in progress is told when the tool finishes. A game is never taken away, not even when you open another tool."""
    if page is None or host is None or not A.cfg.get("game_offer", True):
        if _G["chip"] is not None or _G["panel"] is not None:
            hide()
        return
    if _G["panel"] is not None and not _G["panel"].winfo_exists():
        _G["panel"] = None
    if _G["chip"] is not None and not _G["chip"].winfo_exists():
        _G["chip"] = None
    st = page.__dict__.setdefault("_game", {"since": None})
    if _G["page"] is not page:  # another tool: the old 'finished' note no longer applies
        _G["page"] = page
        if _G["panel"] is not None:
            _G["panel"].reset_note()
    if _G["chip"] is None and _G["panel"] is None:
        _chip(A, host, st)
    lab = _G.get("chip_label")
    if lab is not None and _G["chip"] is not None:
        try:
            lab.configure(text="This is taking a while   ▶  Play a quick game" if slow_now else "▶  Play a quick game")
        except tk.TclError:
            pass
    if slow_now:
        st["since"] = st["since"] or time.time()
    elif st["since"] is not None:  # the tool just finished
        st["since"] = None
        if _G["panel"] is not None:
            _G["panel"].tool_finished()


def open_games(A):
    """Tools > Mini-games: the same games, any time."""
    win = A.toplevel("Mini-games", "700x520")
    tk.Label(win, text="Mini-games", bg=T["bg"], fg=T["fg"], font=("Segoe UI", A.cfg["font_size"] + 6, "bold")).pack(anchor="w", padx=22, pady=(18, 2))
    tk.Label(win, text="They also pop up (as a small chip in the corner) when a tool takes more than a few seconds. Turn that off in Customize.",
             bg=T["bg"], fg=T["muted"], font=("Segoe UI", A.cfg["font_size"]), wraplength=620, justify="left").pack(anchor="w", padx=22, pady=(0, 12))
    GamePanel(win, A, floating=False).pack(anchor="w", padx=22)
