"""Online-only files: the cloud and phone placeholders on this PC (OneDrive, Dropbox, Google Drive, iCloud, Phone Link photos).
Finding them only lists directories: no file is opened, so nothing is downloaded."""
import os

import ff_platform


def sources(home):
    """[(name, folder)] of the places on this PC that can hold online-only files."""
    j = os.path.join
    candidates = (("OneDrive", os.environ.get("OneDrive") or j(home, "OneDrive")), ("Dropbox", j(home, "Dropbox")), ("Google Drive", j(home, "Google Drive")),
                  ("iCloud Drive", j(home, "iCloudDrive")), ("Phone Link", j(home, "CrossDevice")))
    return [(n, p) for n, p in candidates if os.path.isdir(p)]


def scan(folder, cancel=lambda: False, progress=None, limit=300_000):
    """({folder: [(name, size, mtime)]}, files_seen) for the online-only files below `folder`. `progress(files_seen)` is called now and then."""
    found, seen, stack = {}, 0, [folder]
    total = 0
    while stack and not cancel() and total < limit:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                        continue
                    seen += 1
                    st = e.stat(follow_symlinks=False)  # (from the directory listing: never opens the file)
                except OSError:
                    continue
                if ff_platform.is_placeholder(st):
                    found.setdefault(d, []).append((e.name, st.st_size, st.st_mtime))
                    total += 1
        if progress:
            progress(seen)
    return found, seen


def groups(found):
    """[(folder, file count, bytes)] biggest first."""
    return sorted(((d, len(fs), sum(f[1] for f in fs)) for d, fs in found.items()), key=lambda g: (-g[2], g[0]))
