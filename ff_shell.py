"""Windows shell integration for Foldwise, via ctypes (no extra packages):

 - shell_thumbnail   the same thumbnails Explorer shows (PDF, video, Office, images...)
 - native_menu       the real Windows right-click menu (7-Zip, Git, Share, Send to...)
 - ole_drag          drag files out of Foldwise into other apps
 - DropTarget        accept files dragged in from other apps / Explorer
"""
import ctypes
import os
from ctypes import POINTER, byref, c_int, c_long, c_ulong, c_void_p, wintypes

ole32, shell32, user32, gdi32 = ctypes.windll.ole32, ctypes.windll.shell32, ctypes.windll.user32, ctypes.windll.gdi32
S_OK = 0


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, POINTER(GUID)]
shell32.ILCreateFromPathW.argtypes = [wintypes.LPCWSTR]
shell32.ILCreateFromPathW.restype = c_void_p
shell32.ILFree.argtypes = [c_void_p]
shell32.SHBindToParent.argtypes = [c_void_p, POINTER(GUID), POINTER(c_void_p), POINTER(c_void_p)]
shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, c_void_p, POINTER(GUID), POINTER(c_void_p)]
user32.CreatePopupMenu.restype = c_void_p
user32.DestroyMenu.argtypes = [c_void_p]
user32.GetMenuItemCount.argtypes = [c_void_p]
user32.GetMenuStringW.argtypes = [c_void_p, wintypes.UINT, wintypes.LPWSTR, c_int, wintypes.UINT]
user32.TrackPopupMenuEx.argtypes = [c_void_p, wintypes.UINT, c_int, c_int, c_void_p, c_void_p]
user32.GetDC.argtypes = [c_void_p]
user32.GetDC.restype = c_void_p
user32.ReleaseDC.argtypes = [c_void_p, c_void_p]
user32.GetParent.argtypes = [c_void_p]
user32.GetParent.restype = c_void_p
user32.SetWindowLongPtrW.restype = c_void_p
user32.CallWindowProcW.restype = ctypes.c_ssize_t
gdi32.GetObjectW.argtypes = [c_void_p, c_int, c_void_p]
gdi32.GetDIBits.argtypes = [c_void_p, c_void_p, wintypes.UINT, wintypes.UINT, c_void_p, c_void_p, wintypes.UINT]
gdi32.DeleteObject.argtypes = [c_void_p]
ole32.DoDragDrop.argtypes = [c_void_p, c_void_p, wintypes.DWORD, POINTER(wintypes.DWORD)]
ole32.RegisterDragDrop.argtypes = [c_void_p, c_void_p]
ole32.RevokeDragDrop.argtypes = [c_void_p]
ole32.ReleaseStgMedium.argtypes = [c_void_p]
shell32.DragQueryFileW.argtypes = [c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]

_guids = {}


def guid(s):
    if s not in _guids:
        g = GUID()
        ole32.CLSIDFromString(s, byref(g))
        _guids[s] = g
    return _guids[s]


IID_SHELLFOLDER = "{000214E6-0000-0000-C000-000000000046}"
IID_CONTEXTMENU = "{000214E4-0000-0000-C000-000000000046}"
IID_CONTEXTMENU2 = "{000214F4-0000-0000-C000-000000000046}"
IID_CONTEXTMENU3 = "{BCFCE0A0-EC17-11D0-8D10-00A0C90F2719}"
IID_DATAOBJECT = "{0000010E-0000-0000-C000-000000000046}"
IID_IMAGEFACTORY = "{BCC18B79-BA16-442F-80C4-8A59C30C463B}"


def vcall(obj, index, argtypes, *args):
    """Call method `index` of the COM object at address `obj`."""
    vtbl = ctypes.cast(ctypes.cast(c_void_p(obj), POINTER(c_void_p))[0], POINTER(c_void_p))
    return ctypes.WINFUNCTYPE(c_long, c_void_p, *argtypes)(vtbl[index])(c_void_p(obj), *args)


def release(obj):
    if obj:
        vcall(obj, 2, [])


def hwnd_of(tk_root):
    """The real top-level window handle of a Tk root."""
    return user32.GetParent(tk_root.winfo_id())


# ------------------------------------------------------------------ thumbnails
class _SIZE(ctypes.Structure):
    _fields_ = [("cx", c_long), ("cy", c_long)]


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", c_long), ("bmWidth", c_long), ("bmHeight", c_long), ("bmWidthBytes", c_long),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD), ("bmBits", c_void_p)]


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", c_long), ("biHeight", c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPels", c_long), ("biYPels", c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def shell_thumbnail(path, size=256):
    """PIL RGBA thumbnail from Windows' thumbnail providers, or None if the file has none."""
    from PIL import Image
    ole32.CoInitializeEx(None, 2)  # this thread needs COM
    factory = c_void_p()
    if shell32.SHCreateItemFromParsingName(os.path.normpath(path), None, byref(guid(IID_IMAGEFACTORY)),
                                           byref(factory)) != 0 or not factory.value:
        return None
    hbm = c_void_p()
    try:
        # SIIGBF_THUMBNAILONLY: fail (rather than return a generic icon) when there is no real thumbnail
        hr = vcall(factory.value, 3, [_SIZE, wintypes.UINT, POINTER(c_void_p)], _SIZE(size, size), 0x8, byref(hbm))
        if hr != 0 or not hbm.value:
            return None
        bmp = _BITMAP()
        gdi32.GetObjectW(hbm, ctypes.sizeof(bmp), byref(bmp))
        w, h = bmp.bmWidth, bmp.bmHeight
        bih = _BIH(ctypes.sizeof(_BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        hdc = user32.GetDC(None)
        gdi32.GetDIBits(hdc, hbm, 0, h, buf, byref(bih), 0)
        user32.ReleaseDC(None, hdc)
        img = Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRa", 0, 1)
        if img.getchannel("A").getextrema()[1] == 0:  # no alpha channel: opaque picture
            img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1).convert("RGBA")
        return img
    finally:
        if hbm.value:
            gdi32.DeleteObject(hbm)
        release(factory.value)


# ------------------------------------------------------------ shell item helpers
class _ShellItems:
    """PIDLs + parent IShellFolder for a list of paths in the same folder (released on close())."""

    def __init__(self, paths):
        ole32.CoInitializeEx(None, 2)
        self.pidls, self.children, self.folder = [], [], c_void_p()
        for p in paths:
            pidl = shell32.ILCreateFromPathW(os.path.normpath(p))
            if not pidl:
                continue
            self.pidls.append(pidl)
            folder, child = c_void_p(), c_void_p()
            if shell32.SHBindToParent(pidl, byref(guid(IID_SHELLFOLDER)), byref(folder), byref(child)) != 0:
                continue
            if not self.folder.value:
                self.folder = folder
            elif folder.value != self.folder.value:  # only files from one folder can share a menu / data object
                release(folder.value)
                continue
            else:
                release(folder.value)
            self.children.append(child.value)
        self.arr = (c_void_p * len(self.children))(*self.children)

    def ui_object(self, hwnd, iid):
        out = c_void_p()
        hr = vcall(self.folder.value, 10, [c_void_p, wintypes.UINT, POINTER(c_void_p), POINTER(GUID),
                                           POINTER(wintypes.UINT), POINTER(c_void_p)],
                   hwnd, len(self.children), self.arr, byref(guid(iid)), None, byref(out))
        return out.value if hr == 0 else None

    def close(self):
        release(self.folder.value)
        for pidl in self.pidls:
            shell32.ILFree(pidl)


# ------------------------------------------------------------ native context menu
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, c_void_p, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.CallWindowProcW.argtypes = [c_void_p, c_void_p, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


class _CMI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.DWORD), ("hwnd", c_void_p), ("lpVerb", c_void_p),
                ("lpParameters", c_void_p), ("lpDirectory", c_void_p), ("nShow", c_int), ("dwHotKey", wintypes.DWORD),
                ("hIcon", c_void_p)]


def _build_menu(hwnd, items, extended):
    pcm = items.ui_object(hwnd, IID_CONTEXTMENU)
    if not pcm:
        return None, None
    hmenu = user32.CreatePopupMenu()
    vcall(pcm, 3, [c_void_p, wintypes.UINT, wintypes.UINT, wintypes.UINT, wintypes.UINT],
          hmenu, 0, 1, 0x7FFF, 0x100 if extended else 0)  # CMF_EXTENDEDVERBS = what Shift+right-click shows
    return pcm, hmenu


def native_menu(hwnd, paths, x, y, extended=False):
    """Show the real Windows context menu at screen position (x, y); runs the chosen command. True if one ran."""
    items = _ShellItems(paths)
    pcm = hmenu = pcm2 = pcm3 = None
    old = {}
    try:
        pcm, hmenu = _build_menu(hwnd, items, extended)
        if not pcm:
            return False
        for iid, slot in ((IID_CONTEXTMENU3, "3"), (IID_CONTEXTMENU2, "2")):  # owner-drawn submenus (Send to...)
            out = c_void_p()
            if vcall(pcm, 0, [POINTER(GUID), POINTER(c_void_p)], byref(guid(iid)), byref(out)) == 0 and out.value:
                if slot == "3":
                    pcm3 = out.value
                else:
                    pcm2 = out.value
                break

        def proc(h, msg, wp, lp):
            if msg in (0x117, 0x2B, 0x2C, 0x120):  # INITMENUPOPUP, DRAWITEM, MEASUREITEM, MENUCHAR
                res = ctypes.c_ssize_t(0)
                if pcm3:
                    vcall(pcm3, 7, [wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, POINTER(ctypes.c_ssize_t)],
                          msg, wp, lp, byref(res))
                    return res.value if msg == 0x120 else (1 if msg in (0x2B, 0x2C) else 0)
                if pcm2:
                    vcall(pcm2, 6, [wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], msg, wp, lp)
                    return 1 if msg in (0x2B, 0x2C) else 0
            return user32.CallWindowProcW(old["p"], h, msg, wp, lp)

        cb = WNDPROC(proc)
        user32.SetWindowLongPtrW.argtypes = [c_void_p, c_int, WNDPROC]
        old["p"] = user32.SetWindowLongPtrW(hwnd, -4, cb)
        try:
            cmd = user32.TrackPopupMenuEx(hmenu, 0x100 | 0x2, x, y, hwnd, None)  # RETURNCMD | RIGHTBUTTON
        finally:
            user32.SetWindowLongPtrW.argtypes = [c_void_p, c_int, c_void_p]
            user32.SetWindowLongPtrW(hwnd, -4, old["p"])
        if cmd:
            ci = _CMI()
            ci.cbSize, ci.hwnd, ci.lpVerb, ci.nShow = ctypes.sizeof(_CMI), hwnd, cmd - 1, 1
            vcall(pcm, 4, [c_void_p], ctypes.addressof(ci))
            return True
        return False
    finally:
        for o in (pcm3, pcm2, pcm):
            release(o)
        if hmenu:
            user32.DestroyMenu(hmenu)
        items.close()


# --------------------------------------------------------------- drag OUT (OLE)
class _Com:
    """A tiny COM object built from Python callbacks. Subclasses fill self.methods (after the 3 IUnknown ones)."""

    def _build(self, iids, sigs, fns):
        qi_t = ctypes.WINFUNCTYPE(c_long, c_void_p, POINTER(GUID), POINTER(c_void_p))
        ref_t = ctypes.WINFUNCTYPE(c_ulong, c_void_p)

        def qi(this, riid, ppv):
            g = riid[0]
            want = {guid("{00000000-0000-0000-C000-000000000046}").Data1, iids}
            if g.Data1 in want:
                ppv[0] = this
                return S_OK
            ppv[0] = None
            return -2147467262  # E_NOINTERFACE

        self._keep = [qi_t(qi), ref_t(lambda this: 1), ref_t(lambda this: 1)]
        self._keep += [t(f) for t, f in zip(sigs, fns)]
        self.vtbl = (c_void_p * len(self._keep))(*[ctypes.cast(f, c_void_p) for f in self._keep])
        self.struct = (c_void_p * 1)(ctypes.addressof(self.vtbl))
        self.ptr = ctypes.addressof(self.struct)


class DropSource(_Com):
    def __init__(self, cancel=False):
        qcd = ctypes.WINFUNCTYPE(c_long, c_void_p, wintypes.BOOL, wintypes.DWORD)
        gf = ctypes.WINFUNCTYPE(c_long, c_void_p, wintypes.DWORD)

        def query_continue(this, esc, keys):
            if esc or cancel:
                return 0x40101  # DRAGDROP_S_CANCEL
            if not keys & 1:  # left button released
                return 0x40100  # DRAGDROP_S_DROP
            return S_OK

        self._build(0x121, [qcd, gf], [query_continue, lambda this, effect: 0x40102])  # USEDEFAULTCURSORS


def ole_drag(hwnd, paths, _cancel=False):
    """Start a real Windows drag of these files (blocks until dropped). Returns 0 none, 1 copy, 2 move, 4 link."""
    ole32.OleInitialize(None)
    items = _ShellItems(paths)
    try:
        if not items.children:
            return 0
        data = items.ui_object(hwnd, IID_DATAOBJECT)
        if not data:
            return 0
        src = DropSource(_cancel)
        effect = wintypes.DWORD(0)
        user32.ReleaseCapture()  # Tk holds the mouse while a button is down; OLE needs it
        ole32.DoDragDrop(data, src.ptr, 7, byref(effect))
        release(data)
        return effect.value
    finally:
        items.close()


# ---------------------------------------------------------------- drag IN (OLE)
class _FORMATETC(ctypes.Structure):
    _fields_ = [("cfFormat", wintypes.WORD), ("ptd", c_void_p), ("dwAspect", wintypes.DWORD), ("lindex", c_long),
                ("tymed", wintypes.DWORD)]


class _STGMEDIUM(ctypes.Structure):
    _fields_ = [("tymed", wintypes.DWORD), ("handle", c_void_p), ("pUnkForRelease", c_void_p)]


def _paths_from_dataobject(pdata):
    fmt = _FORMATETC(15, None, 1, -1, 1)  # CF_HDROP, DVASPECT_CONTENT, TYMED_HGLOBAL
    stg = _STGMEDIUM()
    if vcall(pdata, 3, [POINTER(_FORMATETC), POINTER(_STGMEDIUM)], byref(fmt), byref(stg)) != 0:
        return []
    out = []
    try:
        n = shell32.DragQueryFileW(stg.handle, 0xFFFFFFFF, None, 0)
        buf = ctypes.create_unicode_buffer(32768)
        for i in range(n):
            shell32.DragQueryFileW(stg.handle, i, buf, 32767)
            out.append(buf.value)
    finally:
        ole32.ReleaseStgMedium(byref(stg))
    return out


class DropTarget(_Com):
    """Register on a window with .register(hwnd); on_drop(paths, move) is called when files are dropped on it."""

    def __init__(self, on_drop):
        pt = ctypes.c_int64  # POINTL passed by value (8 bytes)
        enter_t = ctypes.WINFUNCTYPE(c_long, c_void_p, c_void_p, wintypes.DWORD, pt, POINTER(wintypes.DWORD))
        over_t = ctypes.WINFUNCTYPE(c_long, c_void_p, wintypes.DWORD, pt, POINTER(wintypes.DWORD))
        leave_t = ctypes.WINFUNCTYPE(c_long, c_void_p)
        drop_t = ctypes.WINFUNCTYPE(c_long, c_void_p, c_void_p, wintypes.DWORD, pt, POINTER(wintypes.DWORD))

        def effect_for(keys):
            return 2 if keys & 4 and not keys & 8 else 1  # Shift = move, otherwise copy

        def enter(this, data, keys, p, eff):
            eff[0] = effect_for(keys)
            return S_OK

        def over(this, keys, p, eff):
            eff[0] = effect_for(keys)
            return S_OK

        def drop(this, data, keys, p, eff):
            eff[0] = effect_for(keys)
            try:
                paths = _paths_from_dataobject(data)
                if paths:
                    on_drop(paths, eff[0] == 2)
            except Exception:
                pass
            return S_OK

        self._build(0x122, [enter_t, over_t, leave_t, drop_t], [enter, over, lambda this: S_OK, drop])
        self.hwnd = None

    def register(self, hwnd):
        ole32.OleInitialize(None)
        self.hwnd = hwnd
        return ole32.RegisterDragDrop(hwnd, self.ptr) == 0

    def revoke(self):
        if self.hwnd:
            ole32.RevokeDragDrop(self.hwnd)


# ------------------------------------------------------------------- Win+E takeover
def is_win_e(vk, flags, win, ctrl, alt, shift):
    """True for a real (not injected) Win+E with no other modifier held."""
    return vk == 0x45 and not flags & 0x10 and bool(win) and not (ctrl or alt or shift)


class _KBD(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class WinEHook:
    """Low-level keyboard hook: Win+E calls `callback()` instead of opening Explorer. Active only while this
    process runs; stop() (or exiting) gives Win+E back to Windows."""

    HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, c_int, wintypes.WPARAM, wintypes.LPARAM)

    def __init__(self, callback):
        self.callback, self.hook, self.tid, self._cb = callback, None, None, None

    def start(self):
        import threading
        k = ctypes.windll.kernel32
        user32.SetWindowsHookExW.argtypes = [c_int, self.HOOKPROC, c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = c_void_p
        user32.CallNextHookEx.argtypes = [c_void_p, c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        k.GetModuleHandleW.restype = c_void_p
        ready = threading.Event()

        def loop():
            self.tid = k.GetCurrentThreadId()
            self._cb = self.HOOKPROC(self._proc)
            self.hook = user32.SetWindowsHookExW(13, self._cb, k.GetModuleHandleW(None), 0)  # WH_KEYBOARD_LL
            ready.set()
            msg = wintypes.MSG()
            while self.hook and user32.GetMessageW(byref(msg), None, 0, 0) > 0:
                pass
            if self.hook:
                user32.UnhookWindowsHookEx(c_void_p(self.hook))

        threading.Thread(target=loop, daemon=True).start()
        ready.wait(2)
        return bool(self.hook)

    def _proc(self, n, wparam, lparam):
        try:
            if n >= 0 and wparam in (0x100, 0x104):  # WM_KEYDOWN / WM_SYSKEYDOWN
                kb = ctypes.cast(lparam, POINTER(_KBD)).contents
                down = lambda vk: user32.GetAsyncKeyState(vk) & 0x8000
                if is_win_e(kb.vkCode, kb.flags, down(0x5B) or down(0x5C), down(0x11), down(0x12), down(0x10)):
                    # a stray key between Win-down and Win-up stops Windows opening the Start menu
                    user32.keybd_event(0xE8, 0, 0, 0)
                    user32.keybd_event(0xE8, 0, 2, 0)
                    self.callback()
                    return 1  # swallow the E: Explorer never sees it
        except Exception:
            pass
        return user32.CallNextHookEx(None, n, wparam, lparam)

    def stop(self):
        if self.tid:
            hook, self.hook = self.hook, None
            if hook:
                user32.UnhookWindowsHookEx(c_void_p(hook))
            user32.PostThreadMessageW(self.tid, 0x12, 0, 0)  # WM_QUIT ends the hook thread
