# Foldwise

A file manager, instant search and PC health center for Windows 10/11, in one small program. It is built to replace File Explorer for everyday use.

**Download:** get `Foldwise.exe` (about 25 MB, no installation, no Python needed) from the [latest release](https://github.com/omtps/foldwise/releases/latest) and double-click it.

## Main features

- **File manager:** tabs, split view, details and thumbnail views, preview pane, breadcrumbs, favourites, tags and colour labels, zip/tar archives browsed like folders, undo for file operations, native Windows context menu and drag and drop. Can replace Win+E, with a tray icon and a global hotkey (Ctrl+Alt+F).
- **Instant search:** every file name on your drives is indexed and found as you type, with filters such as `ext:`, `size:`, `modified:`, `tag:` and optional search inside documents and PDFs (scanned PDFs through Windows OCR). A live watcher keeps the index fresh.
- **Cleaning up:** smart disk cleaner with protected folders, duplicate finder, largest files, empty folders, look-alike photos, disk usage map, folder size history and smart collections.
- **PC health center:** health score, disks and SMART, memory and CPU, startup programs, network and speed test, security audit, Windows Update and driver checks, trends over time and an HTML report.
- **Security:** Windows Defender scans plus a deep check for start-up tricks, fake file names and broken signatures, with a restorable quarantine; encrypted vaults (AES-256) for folders; integrity fingerprints that reveal changed or corrupted files.
- **Backups and sync:** scheduled backups that never delete, two-way folder sync with safety copies, FTP, SFTP and WebDAV browsing.
- **Photos and media:** EXIF details and metadata removal, image convert and resize, media properties, quick look for documents, spreadsheets and code.
- **Made to be personal:** Adwaita-style dark and light themes that can follow Windows, accent colours, fonts, date formats, a setup wizard that starts with almost everything off, and a guided tour that points at the real windows.
- **A little fun:** mini-games to play while a slow tool works.
- **Updates itself:** checks this repository for new releases (or `git pull` when run from a checkout), verifies the download and swaps it in while you keep working.

Everything Foldwise stores (index, settings, tags) stays on your PC in `%LOCALAPPDATA%\Foldwise`. Nothing is sent anywhere unless you turn on an online feature yourself.

## Quick start

1. Download `Foldwise.exe` from the latest release and run it. The first start shows a short setup wizard and a guided tour (Tools > Tutorial replays it, F1 lists every shortcut).
2. Optional: **About > Install on this PC** adds Start menu and start-with-Windows shortcuts (no registry changes).
3. Portable use: put an empty file named `portable.flag` next to `Foldwise.exe` and all data stays in a `data` folder beside it.

Command line: `Foldwise.exe --version | --install | --uninstall | --selftest`

## Updates

**About > Check for updates** reads the latest release of `omtps/foldwise`. The download must match its SHA-256 checksum before it is used, and nothing is installed without your OK. Running from a Git checkout, **About > Update from Git** does a fast-forward `git pull`.

## Build from source

```
pip install -r requirements.txt
python foldwise.py                 # run from source
python build_exe.py                # builds dist\Foldwise.exe
```

Layout: `foldwise.py` (main window), `ff_*.py` (index, search, health, cleaning, malware check, vaults, updates, ...), `ui_*.py` (one module per area of the interface).
