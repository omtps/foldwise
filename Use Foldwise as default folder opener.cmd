@echo off
echo.
echo This makes programs that ask Windows to "open" or "explore" a folder open it
echo in Foldwise instead of Explorer. It also sets "open" as the default action
echo for folders and drives.
echo.
echo It changes per-user registry entries under HKEY_CURRENT_USER\Software\Classes
echo (Directory and Drive). Nothing outside your user is touched, and it is safe to
echo run again: it just refreshes the entries.
echo.
echo NOT affected: Win+E, the taskbar folder icon, and apps that start explorer.exe
echo themselves (many "Show in folder" buttons do this).
echo.
echo To undo it, run "Restore Explorer as default folder opener.cmd".
echo.
choice /m "Apply this change"
if errorlevel 2 goto :eof
python "%~dp0foldwise.py" --set-default-folder-opener
echo.
pause
