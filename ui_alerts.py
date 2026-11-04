"""Saved-search alerts in the interface: a switch per saved search (Smart collections page, sidebar right-click) and a check every few minutes
that shows a pop-up when NEW files match. Every function takes `A` first (ff_app.App); the bookkeeping is ff_alerts.Alerts (A.alerts)."""
import threading

import ff_core
import ui_pages

INTERVAL = 600  # seconds between checks
SHOWN = 3  # file names named in the pop-up
_S = {"timer": None}


def enabled(A, name):
    return name in A.cfg.get("alerts", [])


def toggle(A, name):
    """Switch the alert of a saved search on or off (switching on records what matches now as the baseline)."""
    on = [n for n in A.cfg.get("alerts", []) if n != name]
    if not enabled(A, name):
        on.append(name)
    else:
        A.alerts.forget(name)
    A.save_cfg(alerts=on)
    arm(A)
    if name in on:
        _check(A, only=name)


def renamed(A, old, new):
    A.save_cfg(alerts=[new if n == old else n for n in A.cfg.get("alerts", [])])
    A.alerts.rename(old, new)


def _check(A, only=None):
    """Run the alerting searches in a thread; announce new matches."""
    jobs = [(n, A.cfg["saved"][n]) for n in A.cfg.get("alerts", []) if n in A.cfg.get("saved", {}) and only in (None, n)]

    def work():
        found = []
        con = ff_core.connect()
        try:
            for name, query in jobs:
                try:
                    new = A.alerts.check(name, [r[1] for r in ff_core.search(con, query)])
                except Exception as e:  # noqa - one broken search must not stop the others
                    ff_core.log_error(f"alert {name}: {e}")
                    continue
                if new:
                    found.append((name, query, new))
        finally:
            con.close()
        if found:
            A.root.after(0, lambda: announce(A, found))
    threading.Thread(target=work, daemon=True).start()


def announce(A, found):
    for name, query, new in found:
        names = ", ".join(p.rsplit(chr(92), 1)[-1] for p in new[:SHOWN]) + (f" and {len(new) - SHOWN} more" if len(new) > SHOWN else "")
        A.show_toast(f"{len(new)} new file{'s' if len(new) != 1 else ''} match “{name}”: {names}", "Show", lambda q=query: (ui_pages.show_files(A), A.q.set(q)),
                     title="Pinefiles · Saved search")


def tick(A):
    _S["timer"] = None
    saved = A.cfg.get("saved", {})
    stale = [n for n in A.cfg.get("alerts", []) if n not in saved]
    if stale:  # the saved search was deleted: its alert goes with it
        A.save_cfg(alerts=[n for n in A.cfg["alerts"] if n in saved])
        for n in stale:
            A.alerts.forget(n)
    if A.cfg.get("alerts") and not A.st.get("xfer"):
        _check(A)
    arm(A)


def arm(A):
    if _S["timer"] is None and A.cfg.get("alerts"):
        _S["timer"] = A.root.after(INTERVAL * 1000, lambda: tick(A))


def autostart(A):
    arm(A)
