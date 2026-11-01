"""Hand Foldwise.exe to your other computers: a tiny download server for your home network, and a USB/folder export.

The server serves ONLY three things, all behind a random access code in the address: a download page, the exe itself and an
update.json manifest (so the other PC can use Foldwise's own update check). It is read-only and you start/stop it yourself.
"""
import hashlib
import http.server
import json
import secrets
import shutil
import socket
import socketserver
import threading
from pathlib import Path

import ff_update


def lan_addresses():
    """Private IPv4 addresses of this PC (the ones another computer on your network can reach), best guess first."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the outgoing interface
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    good = [i for i in ips if i.startswith(("192.168.", "10.")) or (i.startswith("172.") and 16 <= int(i.split(".")[1]) <= 31)]
    return sorted(good, key=lambda i: (not i.startswith("192.168."), i)) or sorted(i for i in ips if not i.startswith("127."))


def source_exe():
    """The exe to hand out: ourselves when packaged, else dist\\Foldwise.exe next to the sources."""
    me = ff_update.exe_path()
    if me:
        return me
    p = Path(__file__).resolve().parent / "dist" / "Foldwise.exe"
    return p if p.exists() else None


def manifest_for(exe, base_url=""):
    """update.json content for `exe` (url left relative when base_url is empty)."""
    h = hashlib.sha256()
    with open(exe, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return {"version": ff_update.APP_VERSION, "url": (base_url.rstrip("/") + "/Foldwise.exe") if base_url else "Foldwise.exe", "sha256": h.hexdigest(),
            "notes": "; ".join(next((n for v, n in ff_update.WHATS_NEW if v == ff_update.APP_VERSION), [])) or f"Foldwise {ff_update.APP_VERSION}"}


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Foldwise</title>
<body style="font:16px Segoe UI,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#1e293b">
<h1>Foldwise {version}</h1>
<p>File manager, instant search and PC health center for Windows 10/11. One file, no installation needed.</p>
<p><a href="Foldwise.exe" style="display:inline-block;background:#2563eb;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:600">Download Foldwise.exe ({size} MB)</a></p>
<ol><li>Download it and double-click <b>Foldwise.exe</b>.</li>
<li>Windows may say &ldquo;Windows protected your PC&rdquo; because the program isn't signed by a company: choose <b>More info &rarr; Run anyway</b> (only if you trust this page, i.e. you started it yourself).</li>
<li>Optional: in Foldwise open <b>Tools &rarr; About / install / updates</b> and press <b>Install on this PC</b>.</li></ol>
<p style="color:#64748b">SHA-256 of the file: <code style="word-break:break-all">{sha}</code><br>
Check it with <code>certutil -hashfile Foldwise.exe SHA256</code> if you like. For automatic updates from this PC, paste
<code>{manifest}</code> into About &rarr; Updates.</p></body>"""


class Share:
    def __init__(self, exe=None, port=8765):
        self.exe = Path(exe or source_exe() or "")
        if not self.exe.is_file():
            raise FileNotFoundError("Foldwise.exe was not found. Run build_exe.py first (or use the packaged exe).")
        self.token = secrets.token_urlsafe(6)
        self.port = port
        self.server = None
        self.sha = manifest_for(self.exe)["sha256"]
        self.downloads = 0

    def urls(self):
        return [f"http://{ip}:{self.server.server_address[1]}/{self.token}/" for ip in (lan_addresses() or ["localhost"])]

    def start(self):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def do_GET(self):
                parts = self.path.split("?")[0].strip("/").split("/")
                if not parts or parts[0] != outer.token:
                    return self._send(403, b"Forbidden")
                name = parts[1] if len(parts) > 1 else ""
                host = self.headers.get("Host") or f"localhost:{outer.port}"
                base = f"http://{host}/{outer.token}"
                if name == "":
                    page = PAGE.format(version=ff_update.APP_VERSION, size=f"{outer.exe.stat().st_size / 1048576:.0f}", sha=outer.sha, manifest=base + "/update.json")
                    return self._send(200, page.encode("utf-8"))
                if name == "update.json":
                    return self._send(200, json.dumps(manifest_for(outer.exe, base)).encode("utf-8"), "application/json")
                if name == "Foldwise.exe":
                    outer.downloads += 1
                    with open(outer.exe, "rb") as f:
                        data = f.read()
                    return self._send(200, data, "application/octet-stream", {"Content-Disposition": 'attachment; filename="Foldwise.exe"'})
                self._send(404, b"Not found")

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        try:
            self.server = socketserver.ThreadingTCPServer(("0.0.0.0", self.port), Handler)
        except OSError:
            self.server = socketserver.ThreadingTCPServer(("0.0.0.0", 0), Handler)  # port busy: any free one
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.urls()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


def export_package(dest_dir, exe=None):
    """Copy Foldwise.exe + update.json + a short README into dest_dir (a USB stick, a shared drive, a cloud-synced folder)."""
    exe = Path(exe or source_exe() or "")
    if not exe.is_file():
        raise FileNotFoundError("Foldwise.exe was not found. Run build_exe.py first.")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, dest / "Foldwise.exe")
    (dest / "update.json").write_text(json.dumps(manifest_for(exe), indent=1), encoding="utf-8")
    (dest / "README.txt").write_text(
        f"Foldwise {ff_update.APP_VERSION}\r\n\r\n1. Copy Foldwise.exe to the other PC and double-click it (no install needed).\r\n"
        "2. If Windows says 'protected your PC': More info > Run anyway (the program isn't signed by a company).\r\n"
        "3. Optional: Tools > About / install / updates > Install on this PC.\r\n\r\n"
        "Updating later: copy a newer Foldwise.exe next to the old one and use About > Update from a file.\r\n", encoding="utf-8")
    return dest
