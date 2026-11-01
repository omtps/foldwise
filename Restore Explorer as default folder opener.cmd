@echo off
echo.
echo This removes the Foldwise folder-opener override, so Explorer opens folders again.
echo (It deletes the Directory and Drive "shell\open\command" keys under
echo HKEY_CURRENT_USER\Software\Classes that "Use Foldwise as default folder opener" created.)
echo.
python "%~dp0foldwise.py" --restore-default-folder-opener
echo.
pause
