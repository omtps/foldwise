"""Encrypted vaults: lock a folder into ONE password-protected .ffvault file, unlock it again anywhere Pinefiles runs.

Security design (standard, boring choices on purpose): key = scrypt(password, random salt, n=2^15, r=8, p=1); the folder is packed as a
tar stream and encrypted in 1 MB chunks with AES-256-GCM. Every chunk is authenticated together with its position and a
'last chunk' flag, so a wrong password, a damaged file, reordered or cut-off data are all detected (nothing is silently accepted).
There is NO password recovery: if you forget it, the data is gone. Nothing is written to disk unencrypted while locking.
"""
import io
import os
import struct
import tarfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"FFVLT1\x00\x00"
CHUNK = 1 << 20
SCRYPT_N = 1 << 15


def _key(password, salt, n=SCRYPT_N):
    return Scrypt(salt=salt, length=32, n=n, r=8, p=1).derive(password.encode("utf-8"))


class _EncWriter(io.RawIOBase):
    def __init__(self, f, aes, header):
        self.f, self.aes, self.hdr, self.buf, self.i = f, aes, header, bytearray(), 0

    def writable(self):
        return True

    def _emit(self, data, last):
        nonce = os.urandom(12)
        aad = self.hdr + struct.pack(">QB", self.i, 1 if last else 0)
        ct = self.aes.encrypt(nonce, bytes(data), aad)
        self.f.write(struct.pack(">BI", 1 if last else 0, len(ct)) + nonce + ct)
        self.i += 1

    def write(self, b):
        self.buf += b
        while len(self.buf) > CHUNK:  # keep at least one byte back so the final chunk can carry the 'last' flag
            self._emit(self.buf[:CHUNK], False)
            del self.buf[:CHUNK]
        return len(b)

    def close(self):
        if not self.closed:
            self._emit(self.buf, True)
            self.buf = bytearray()
        super().close()


class _DecReader(io.RawIOBase):
    def __init__(self, f, aes, header):
        self.f, self.aes, self.hdr, self.i, self.buf, self.done = f, aes, header, 0, bytearray(), False

    def readable(self):
        return True

    def _next(self):
        head = self.f.read(5)
        if len(head) < 5:
            raise ValueError("The vault file is cut off or damaged.")
        last, n = struct.unpack(">BI", head)
        nonce, ct = self.f.read(12), self.f.read(n)
        if len(ct) != n:
            raise ValueError("The vault file is cut off or damaged.")
        try:
            self.buf += self.aes.decrypt(nonce, ct, self.hdr + struct.pack(">QB", self.i, last))
        except InvalidTag:
            raise ValueError("Wrong password, or the vault file is damaged.") from None
        self.i += 1
        self.done = bool(last)

    def readinto(self, b):
        while len(self.buf) < len(b) and not self.done:
            self._next()
        n = min(len(b), len(self.buf))
        b[:n] = self.buf[:n]
        del self.buf[:n]
        return n


def lock_folder(folder, out_path, password, progress=lambda name: None, scrypt_n=SCRYPT_N):
    """Pack `folder` into the encrypted file `out_path` (never overwrites). Returns out_path."""
    if not password:
        raise ValueError("Choose a password.")
    if os.path.exists(out_path):
        raise FileExistsError("A vault with that name already exists.")
    salt = os.urandom(16)
    header = MAGIC + struct.pack(">I", scrypt_n) + salt
    aes = AESGCM(_key(password, salt, scrypt_n))
    tmp = out_path + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(header)
            w = _EncWriter(f, aes, header)
            with tarfile.open(fileobj=w, mode="w|") as tar:
                base = os.path.basename(os.path.abspath(folder))
                for dp, dns, fns in os.walk(folder):
                    rel = os.path.relpath(dp, folder)
                    arc = base if rel == "." else os.path.join(base, rel)
                    tar.add(dp, arcname=arc, recursive=False)
                    for fn in fns:
                        p = os.path.join(dp, fn)
                        if os.path.islink(p):
                            continue
                        progress(fn)
                        tar.add(p, arcname=os.path.join(arc, fn), recursive=False)
            w.close()
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return out_path


def unlock(vault_path, dest_dir, password, progress=lambda name: None):
    """Decrypt a .ffvault into dest_dir (a new folder inside it). Raises ValueError for a wrong password / damaged file."""
    with open(vault_path, "rb") as f:
        header = f.read(len(MAGIC) + 4 + 16)
        if not header.startswith(MAGIC):
            raise ValueError("This is not a Pinefiles vault.")
        n = struct.unpack(">I", header[len(MAGIC):len(MAGIC) + 4])[0]
        if n > (1 << 20):
            raise ValueError("The vault file is damaged.")
        aes = AESGCM(_key(password, header[-16:], n))
        r = _DecReader(f, aes, header)
        os.makedirs(dest_dir, exist_ok=True)
        with tarfile.open(fileobj=io.BufferedReader(r), mode="r|") as tar:
            for m in tar:
                progress(m.name)
                tar.extract(m, dest_dir, filter="data")  # 'data' filter: no path escapes, no special files
        while not r.done:  # make sure the whole file is authentic, including the final chunk
            r._next()
    return dest_dir
