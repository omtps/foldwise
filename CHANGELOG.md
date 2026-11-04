# Pinefiles changelog

## 1.1.001 - 2026-11-04
- Mini-games no longer float over the tool: a slow tool offers them once in a pop-up and they open in the Mini-games tab
- New game: the Chrome-style dino runner
- The Tools list is much shorter: related tools now share one entry and open as tabs inside it (for example Clean up holds the cleaner, duplicates, largest files, look-alike photos and the Recycle Bin), 41 tools in 15 entries
- Customize is much shorter: sections fold (only the first is open), the options are grouped (Look in detail, Files, Safety, Search & background, Alerts & extras, Startup) and the search box still finds everything

## 1.1 - 2026-11-04
- Pinefiles is the new name of Foldwise: your settings, index, tags, notes and shortcuts carry over by themselves
- New tools: Tag manager, Photo timeline, Cloud files, Theme editor and a Keyboard shortcuts editor
- Notes on files and folders (search them with note:), every folder remembers its own sort and view, alerts when a saved search finds new files
- Never opens online-only files (Phone Link photos, OneDrive) by itself, so they are not downloaded; switch in Customize
- Copy queue with pause and merge, secure delete, verify copies after copying, drive speed test
- Automatic rules that sort new files for you
- Quick look for PDFs, Markdown and audio; drivers, startup timing and SSD wear history in PC health
- Look-alike photos: choose any folder and select all suggested copies at once; timeline photos can be copied or moved

## 1.0.2-1 - 2026-11-01
- Nearby devices: the question 'X wants to send you files' now always shows on screen (it opened off-screen when Pinefiles was minimised) and a pop-up points at it
- Nearby devices works with the real LocalSend apps: Pinefiles now presents the certificate they require, and the new 'Check my network' button explains Public networks and firewall blocks
- Receiving files switches itself off after 20 minutes (never in the middle of a transfer) and no longer starts by itself at launch
- The Nearby devices page fits narrow windows: the Send button no longer hides to the right
- Pop-up buttons (crash report, received files, update) now work; version numbers like 1.0.2-1 are understood

## 1.0.2 - 2026-11-01
- Nearby devices: send files to and receive from phones and PCs running the free LocalSend app (or another Pinefiles) on your network; right-click files > Send to a nearby device; receiving is off until you turn it on and always asks first
- Faster copying: Pinefiles uses Windows' own copy routine and copies many small files at once (measured here: 4000 small files 3.5x faster, a 1 GB file about 4x faster before the drive itself is the limit)
- Moving files to another drive now shows progress, can be cancelled and removes the original only after everything arrived
- Tutorial button in Nearby devices

## 1.0.1 - 2026-11-01
- Mini-games fixed: they start on your first click, pause when the pointer leaves, can be dragged by the title bar, no longer cover a tool's buttons and keep playing when you open another tool
- Pinefiles has its own file and folder chooser: tools no longer open the Windows file dialog
- Customize > Default file manager: make Pinefiles open your folders instead of File Explorer, one click to switch back (reversible, undoes itself if Pinefiles is deleted)
- Tutorial buttons in the FTP / SFTP / WebDAV and Phone notifications tools
- Removed the Tune-up wizard, Pinefiles on another PC and Empty folders tools (Empty folders is still inside the Smart disk cleaner)
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
