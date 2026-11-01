# Foldwise changelog

## 1.0.2 - 2026-11-01
- Nearby devices: send files to and receive from phones and PCs running the free LocalSend app (or another Foldwise) on your network; right-click files > Send to a nearby device; receiving is off until you turn it on and always asks first
- Faster copying: Foldwise uses Windows' own copy routine and copies many small files at once (measured here: 4000 small files 3.5x faster, a 1 GB file about 4x faster before the drive itself is the limit)
- Moving files to another drive now shows progress, can be cancelled and removes the original only after everything arrived
- Tutorial button in Nearby devices

## 1.0.1 - 2026-11-01
- Mini-games fixed: they start on your first click, pause when the pointer leaves, can be dragged by the title bar, no longer cover a tool's buttons and keep playing when you open another tool
- Foldwise has its own file and folder chooser: tools no longer open the Windows file dialog
- Customize > Default file manager: make Foldwise open your folders instead of File Explorer, one click to switch back (reversible, undoes itself if Foldwise is deleted)
- Tutorial buttons in the FTP / SFTP / WebDAV and Phone notifications tools
- Removed the Tune-up wizard, Foldwise on another PC and Empty folders tools (Empty folders is still inside the Smart disk cleaner)
- Fixed: a scan running on a hidden tab could be closed when a third tool was opened

## 1.0.0 - 2026-11-01
First release.
- File manager: tabs, split view, details and thumbnail views, preview pane, tags and colour labels, archives as folders, undo
- Instant search over every drive, optional search inside documents and PDFs (with OCR for scanned pages)
- Cleaning: smart disk cleaner, duplicates, largest files, empty folders, look-alike photos, folder size history, smart collections
- PC health center, security audit, Windows Defender scans and a deep malware check with quarantine
- Encrypted vaults, scheduled backups, folder sync, FTP / SFTP / WebDAV, integrity checks
- Themes that can follow Windows, setup wizard, guided tour, mini-games
- Updates itself from GitHub releases (or git pull from a checkout)
