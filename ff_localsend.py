"""Send and receive files with nearby devices using the LocalSend protocol (v2), so Foldwise works with the LocalSend apps on phones and PCs.

Nothing here runs until the user turns it on. Receiving always asks first (`on_request`), files go only into the chosen folder under
sanitised names, uploads are limited to what was announced, and every session has secret per-file tokens tied to the sender's address.
Discovery: UDP multicast 224.0.0.167:53317 with a scan of the local /24 networks as the fallback; transfer: HTTPS on port 53317 with a
self-signed certificate whose SHA-256 is the device fingerprint (plain HTTP when the cryptography library is missing).
Spec: https://github.com/localsend/protocol
"""
import hashlib
import http.client
import http.server
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import socket
import ssl
import struct
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

MCAST, PORT, API, VERSION = "224.0.0.167", 53317, "/api/localsend/v2", "2.0"
RESERVED = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}


class LocalSendError(Exception):
    pass


def safe_relpath(name):
    """A file name from another device -> a relative path that cannot leave the receive folder (no .., drives, reserved names)."""
    parts = []
    for part in str(name).replace(chr(92), "/").split("/"):
        part = re.sub(r'[<>:"|?*\x00-\x1f]', "_", part.strip()).rstrip(". ")
        if part in ("", ".", ".."):
            continue
        if part.split(".")[0].upper() in RESERVED:
            part = "_" + part
        parts.append(part[:150])
    return "/".join(parts) or "file"


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def local_ips():
    """This PC's IPv4 addresses (the one that reaches the network first)."""
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent: this only asks the OS which interface it would use
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for r in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if r[4][0] not in out:
                out.append(r[4][0])
    except OSError:
        pass
    return [ip for ip in out if not ip.startswith("127.")] or ["127.0.0.1"]


def make_cert(folder):
    """(certfile, keyfile, fingerprint) of this device's self-signed certificate, created once. Fingerprint = SHA-256 of the DER cert."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime
    os.makedirs(folder, exist_ok=True)
    cert_p, key_p = os.path.join(folder, "cert.pem"), os.path.join(folder, "key.pem")
    if os.path.exists(cert_p) and os.path.exists(key_p):
        try:
            c = x509.load_pem_x509_certificate(open(cert_p, "rb").read())
            if c.not_valid_after_utc > datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30):
                return cert_p, key_p, hashlib.sha256(c.public_bytes(serialization.Encoding.DER)).hexdigest()
        except (ValueError, OSError):
            pass
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "Foldwise")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=3650)).sign(key, hashes.SHA256()))
    open(key_p, "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    open(cert_p, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_p, key_p, hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def handle_error(self, request, client_address):
        pass  # a client that hangs up mid-handshake or mid-upload is normal, not worth a traceback

    def get_request(self):
        sock, addr = self.socket.accept()
        if self.node.ctx is not None:
            sock = self.node.ctx.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)  # the handshake happens in the handler's thread
        return sock, addr


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "Foldwise"
    sys_version = ""

    def log_message(self, *a):
        pass

    def setup(self):
        self.request.settimeout(30)
        if self.server.node.ctx is not None:
            self.request.do_handshake()
        super().setup()

    # ---- helpers
    def _json(self, code, obj=None):
        body = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        if obj is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self, limit=5 << 20):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise LocalSendError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def _query(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    # ---- routes
    def do_GET(self):
        if urlparse(self.path).path == API + "/info":
            return self._json(200, self.server.node.info())
        self._json(404, {"message": "not found"})

    def do_POST(self):
        path, node = urlparse(self.path).path, self.server.node
        try:
            if path == API + "/register":
                node._remember(self._body(), self.client_address[0])
                return self._json(200, node.info())
            if path == API + "/prepare-upload":
                return node._prepare(self, self._body(), self.client_address[0])
            if path == API + "/upload":
                return node._upload(self, self._query(), self.client_address[0])
            if path == API + "/cancel":
                node._cancel(self._query().get("sessionId"), self.client_address[0])
                return self._json(200)
        except (LocalSendError, ValueError, KeyError, TypeError):
            return self._json(400, {"message": "invalid request"})
        except (OSError, ssl.SSLError):
            return
        self._json(404, {"message": "not found"})


class Node:
    """One device on the network: announces itself, lists others, receives and sends."""

    def __init__(self, alias, data_dir, receive_dir, port=PORT, on_request=None, on_event=None, multicast=True, use_tls=True):
        self.alias, self.port, self.receive_dir = alias, port, receive_dir
        self.on_request, self.on_event = on_request or (lambda info: False), on_event or (lambda kind, data: None)
        self.multicast, self.data_dir = multicast, data_dir
        self.fingerprint = secrets.token_hex(16)
        self.ctx, self.protocol = None, "http"
        self._peers, self._sessions = {}, {}
        self._lock = threading.Lock()
        self._srv = self._udp = None
        self._stop = threading.Event()
        if use_tls:
            try:
                cert, key, self.fingerprint = make_cert(data_dir)
                self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                self.ctx.load_cert_chain(cert, key)
                self.protocol = "https"
            except Exception:  # noqa - without the cryptography library the plain-HTTP mode of the protocol is used
                self.ctx, self.protocol = None, "http"

    # ---- own description
    def info(self, with_announce=None):
        d = {"alias": self.alias, "version": VERSION, "deviceModel": "Windows PC", "deviceType": "desktop", "fingerprint": self.fingerprint,
             "port": self.port, "protocol": self.protocol, "download": False}
        if with_announce is not None:
            d["announce"] = with_announce
        return d

    # ---- life cycle
    def start(self):
        self._srv = _Server(("0.0.0.0", self.port), _Handler)
        self._srv.node = self
        threading.Thread(target=self._srv.serve_forever, daemon=True, name="localsend-http").start()
        if self.multicast:
            try:
                self._start_udp()
            except OSError:
                self._udp = None  # no multicast on this network: scanning still works
        return self

    def stop(self):
        self._stop.set()
        if self._srv:
            threading.Thread(target=self._srv.shutdown, daemon=True).start()
            self._srv.server_close()
        if self._udp:
            try:
                self._udp.close()
            except OSError:
                pass

    # ---- peers
    def _remember(self, d, ip):
        fp = str(d.get("fingerprint") or "")
        if not fp or fp == self.fingerprint:
            return None
        peer = {"alias": str(d.get("alias") or ip)[:60], "ip": ip, "port": int(d.get("port") or PORT), "protocol": "http" if d.get("protocol") == "http" else "https",
                "fingerprint": fp, "deviceType": str(d.get("deviceType") or "desktop"), "deviceModel": str(d.get("deviceModel") or ""), "seen": time.time()}
        with self._lock:
            new = fp not in self._peers
            self._peers[fp] = peer
        if new:
            self.on_event("peer", peer)
        return peer

    def peers(self):
        with self._lock:
            return sorted(self._peers.values(), key=lambda p: p["alias"].lower())

    def forget_peers(self):
        with self._lock:
            self._peers.clear()

    # ---- discovery
    def _start_udp(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", PORT))
        for ip in local_ips():
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, struct.pack("4s4s", socket.inet_aton(MCAST), socket.inet_aton(ip)))
            except OSError:
                pass
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        self._udp = s
        threading.Thread(target=self._udp_loop, daemon=True, name="localsend-udp").start()
        self.announce()

    def announce(self):
        """Tell everybody nearby that we are here (they answer with their own details)."""
        if not self._udp:
            return
        data = json.dumps(self.info(True)).encode()
        for ip in local_ips():
            try:
                self._udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                self._udp.sendto(data, (MCAST, PORT))
            except OSError:
                pass

    def _udp_loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self._udp.recvfrom(65535)
                d = json.loads(data.decode("utf-8", "replace"))
            except (OSError, ValueError):
                if self._stop.is_set():
                    return
                continue
            if not isinstance(d, dict):
                continue
            peer = self._remember(d, addr[0])
            if peer and d.get("announce") is True:
                threading.Thread(target=self._reply, args=(peer,), daemon=True).start()

    def _reply(self, peer):
        try:
            self._request(peer, "POST", API + "/register", self.info(), timeout=3)
        except (LocalSendError, OSError):
            try:  # the peer's server is not reachable: answer over UDP as the protocol allows
                self._udp.sendto(json.dumps(self.info(False)).encode(), (peer["ip"], PORT))
            except (OSError, AttributeError):
                pass

    def probe(self, ip, port=PORT, timeout=0.6):
        """Ask one address whether a LocalSend device lives there; adds it to the list. Returns the peer or None.
        While this device is listening it registers itself there (so the other side lists it too); otherwise it only asks for the other's info."""
        for proto in ("https", "http"):
            where = {"ip": ip, "port": port, "protocol": proto, "fingerprint": ""}
            try:
                if self._srv is not None:
                    st, data = self._request(where, "POST", API + "/register", self.info(), timeout=timeout)
                else:
                    st, data = self._request(where, "GET", API + "/info", None, timeout=timeout)
            except (LocalSendError, OSError):
                continue
            if st == 200 and isinstance(data, dict):
                return self._remember(dict(data, port=data.get("port") or port, protocol=data.get("protocol") or proto), ip)
        return None

    def scan(self, extra_ips=(), timeout=0.5):
        """Fallback discovery: try every address of the local /24 networks (what the apps do when multicast is blocked)."""
        targets = []
        for ip in local_ips():
            try:
                net = ipaddress.ip_network(ip + "/24", strict=False)
            except ValueError:
                continue
            targets += [str(h) for h in net.hosts() if str(h) != ip]
        targets = list(dict.fromkeys(list(extra_ips) + targets))
        with ThreadPoolExecutor(48) as ex:
            list(ex.map(lambda ip: self.probe(ip, PORT, timeout), targets))
        return self.peers()

    # ---- talking to another device
    def _request(self, peer, method, path, body=None, timeout=10, raw=None, headers=None):
        """One request to a peer; (status, json-or-None). HTTPS peers are checked against their fingerprint when they announced one."""
        if peer["protocol"] == "https":
            c = http.client.HTTPSConnection(peer["ip"], peer["port"], timeout=timeout, context=ssl._create_unverified_context())
        else:
            c = http.client.HTTPConnection(peer["ip"], peer["port"], timeout=timeout)
        try:
            c.connect()
            fp = (peer.get("fingerprint") or "").lower()
            if peer["protocol"] == "https" and re.fullmatch(r"[0-9a-f]{64}", fp):
                if hashlib.sha256(c.sock.getpeercert(binary_form=True)).hexdigest() != fp:
                    raise LocalSendError("That device's certificate does not match the one it announced; not sending.")
            payload = json.dumps(body).encode() if body is not None else raw
            h = dict(headers or {})
            if body is not None:
                h["Content-Type"] = "application/json"
            if payload is not None:
                h["Content-Length"] = str(len(payload))
            c.request(method, path, body=payload, headers=h)
            r = c.getresponse()
            data = r.read(5 << 20)
            try:
                return r.status, (json.loads(data) if data else None)
            except ValueError:
                return r.status, None
        finally:
            c.close()

    def send(self, peer, paths, progress=None, cancel=lambda: False):
        """Send files and folders to `peer`. progress(done_bytes, total_bytes, name). Returns the number of files sent.
        Raises LocalSendError with a plain explanation when the other side says no."""
        files, entries = {}, []
        for p in paths:
            if os.path.isdir(p):
                base = os.path.basename(p.rstrip(chr(92) + "/")) or "folder"
                for d, _dirs, fs in os.walk(p):
                    for f in fs:
                        full = os.path.join(d, f)
                        entries.append((full, base + "/" + os.path.relpath(full, p).replace(chr(92), "/")))
            elif os.path.isfile(p):
                entries.append((p, os.path.basename(p)))
        if not entries:
            raise LocalSendError("There is nothing to send.")
        total = 0
        for full, rel in entries:
            fid = uuid.uuid4().hex
            try:
                st = os.stat(full)
            except OSError:
                continue
            total += st.st_size
            files[fid] = {"id": fid, "fileName": rel, "size": st.st_size, "fileType": mimetypes.guess_type(full)[0] or "application/octet-stream",
                          "metadata": {"modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))}, "_path": full}
        wire = {k: {a: b for a, b in v.items() if a != "_path"} for k, v in files.items()}
        info = self.info()
        info.pop("announce", None)
        st, data = self._request(peer, "POST", API + "/prepare-upload", {"info": info, "files": wire}, timeout=130)  # the person on the other side has to accept
        reasons = {403: "The other device declined the files.", 401: "That device asks for a PIN, which Foldwise does not support yet.",
                   409: "That device is busy with another transfer. Try again in a moment.", 429: "That device has too many requests right now.",
                   400: "The other device could not read the request."}
        if st == 204:
            return 0
        if st != 200 or not isinstance(data, dict):
            raise LocalSendError(reasons.get(st, f"The other device answered with error {st}."))
        sid, tokens = data.get("sessionId"), data.get("files") or {}
        done = 0
        try:
            sent = 0
            for fid, meta in files.items():
                tok = tokens.get(fid)
                if not tok:
                    continue
                if cancel():
                    raise LocalSendError("Cancelled.")
                self._upload_one(peer, sid, fid, tok, meta, lambda n: progress and progress(done + n, total, meta["fileName"]), cancel)
                done += meta["size"]
                sent += 1
        except BaseException:
            try:
                self._request(peer, "POST", API + f"/cancel?sessionId={sid}", timeout=5)
            except (LocalSendError, OSError):
                pass
            raise
        return sent

    def _upload_one(self, peer, sid, fid, token, meta, on_bytes, cancel):
        if peer["protocol"] == "https":
            c = http.client.HTTPSConnection(peer["ip"], peer["port"], timeout=60, context=ssl._create_unverified_context())
        else:
            c = http.client.HTTPConnection(peer["ip"], peer["port"], timeout=60)
        try:
            c.putrequest("POST", API + f"/upload?sessionId={sid}&fileId={fid}&token={token}")
            c.putheader("Content-Length", str(meta["size"]))
            c.putheader("Content-Type", meta["fileType"])
            c.endheaders()
            fp = (peer.get("fingerprint") or "").lower()
            if peer["protocol"] == "https" and re.fullmatch(r"[0-9a-f]{64}", fp) and hashlib.sha256(c.sock.getpeercert(binary_form=True)).hexdigest() != fp:
                raise LocalSendError("That device's certificate does not match the one it announced; not sending.")
            sent = 0
            with open(meta["_path"], "rb") as f:
                while True:
                    if cancel():
                        raise LocalSendError("Cancelled.")
                    b = f.read(1 << 20)
                    if not b:
                        break
                    c.send(b)
                    sent += len(b)
                    on_bytes(sent)
            r = c.getresponse()
            r.read()
            if r.status != 200:
                raise LocalSendError({422: "The other device found the file damaged on arrival.", 403: "The other device refused the upload."}.get(r.status, f"Upload failed ({r.status})."))
        finally:
            c.close()

    # ---- receiving
    def _prepare(self, h, body, ip):
        files = body.get("files")
        if not isinstance(files, dict) or not files or len(files) > 20000:
            return h._json(400, {"message": "no files"})
        clean = {}
        for fid, f in files.items():
            if not isinstance(f, dict):
                raise LocalSendError("bad file entry")
            size = int(f.get("size"))
            if size < 0:
                raise LocalSendError("bad size")
            clean[str(f.get("id") or fid)] = {"name": safe_relpath(f.get("fileName")), "size": size, "sha256": (f.get("sha256") or "").lower() or None}
        with self._lock:
            now = time.time()
            for sid in [s for s, v in self._sessions.items() if now - v["t"] > 900 or v["state"] != "open"]:
                del self._sessions[sid]
            if any(v["state"] == "open" for v in self._sessions.values()):
                return h._json(409, {"message": "busy"})
        alias = str((body.get("info") or {}).get("alias") or ip)[:60]
        ask = {"alias": alias, "ip": ip, "files": [{"name": v["name"], "size": v["size"]} for v in clean.values()], "total": sum(v["size"] for v in clean.values())}
        try:
            ok = bool(self.on_request(ask))
        except Exception:  # noqa - a failing prompt means "no"
            ok = False
        if not ok:
            return h._json(403, {"message": "declined"})
        sid = uuid.uuid4().hex
        dest = self.receive_dir
        os.makedirs(dest, exist_ok=True)
        tokens = {fid: secrets.token_urlsafe(18) for fid in clean}
        with self._lock:
            self._sessions[sid] = {"ip": ip, "files": clean, "tokens": tokens, "t": time.time(), "state": "open", "dest": dest, "alias": alias,
                                   "left": set(clean), "total": ask["total"], "done": 0}
        self.on_event("incoming", {"sid": sid, "alias": alias, "count": len(clean), "total": ask["total"]})
        h._json(200, {"sessionId": sid, "files": tokens})

    def _upload(self, h, q, ip):
        sid, fid, tok = q.get("sessionId"), q.get("fileId"), q.get("token")
        if not sid or not fid or not tok:
            return h._json(400, {"message": "missing parameters"})
        with self._lock:
            s = self._sessions.get(sid)
            ok = bool(s) and s["state"] == "open" and s["ip"] == ip and secrets.compare_digest(str(s["tokens"].get(fid) or ""), tok) and fid in s["left"]
        if not ok:
            return h._json(403, {"message": "invalid token or address"})
        meta = s["files"][fid]
        n = int(h.headers.get("Content-Length") or -1)
        if n < 0 or n > meta["size"]:
            return h._json(400, {"message": "wrong size"})
        final = unique_path(os.path.join(s["dest"], *meta["name"].split("/")))
        part = final + ".part"
        os.makedirs(os.path.dirname(final), exist_ok=True)
        sha, got = hashlib.sha256(), 0
        try:
            with open(part, "wb") as out:
                while got < n:
                    if s["state"] != "open":
                        raise LocalSendError("cancelled")
                    b = h.rfile.read(min(1 << 20, n - got))
                    if not b:
                        raise LocalSendError("connection lost")
                    out.write(b)
                    sha.update(b)
                    got += len(b)
                    s["done"] += len(b)
                    self.on_event("progress", {"sid": sid, "name": meta["name"], "done": s["done"], "total": s["total"], "alias": s["alias"]})
            if got != meta["size"] or (meta["sha256"] and sha.hexdigest() != meta["sha256"]):
                os.remove(part)
                return h._json(422, {"message": "checksum mismatch"})
            os.replace(part, final)
        except (LocalSendError, OSError):
            try:
                os.remove(part)
            except OSError:
                pass
            return
        with self._lock:
            s["left"].discard(fid)
            if not s["left"]:
                s["state"] = "done"
        self.on_event("file", {"sid": sid, "path": final, "alias": s["alias"], "finished": not s["left"]})
        h._json(200)

    def _cancel(self, sid, ip):
        with self._lock:
            s = self._sessions.get(sid)
            if s and s["ip"] == ip:
                s["state"] = "cancelled"
        if s:
            self.on_event("cancelled", {"sid": sid, "alias": s["alias"]})
