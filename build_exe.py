r"""Build the single-file Windows program:  python build_exe.py   ->  dist\Pinefiles.exe
Needs: pip install pyinstaller pillow pypdf pypdfium2 paramiko winrt-runtime winrt-Windows.Media.Ocr
       winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams winrt-Windows.Globalization
       winrt-Windows.Foundation winrt-Windows.Foundation.Collections
The exe contains Python and every module, so it runs on a PC without Python. Copy dist\Pinefiles.exe anywhere and double-click it
(or run it with --install to add Start-menu / start-with-Windows shortcuts)."""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
import ff_core  # noqa: E402  (only to draw the icon)
import ff_update  # noqa: E402

icon = str(ff_core.ensure_icon())
args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--name", "Pinefiles",
        "--icon", icon, "--distpath", "dist", "--workpath", os.path.join("build", "work"), "--specpath", "build",
        "--paths", HERE, "--collect-submodules", "winrt", "--collect-submodules", "paramiko",
        "--hidden-import", "ui_about", "--hidden-import", "ff_ocr", "--hidden-import", "ff_update",
        "--exclude-module", "numpy", "--exclude-module", "PIL._avif", "--exclude-module", "tkinter.test", "--exclude-module", "pytest", "--exclude-module", "unittest", "--exclude-module", "pydoc", "--exclude-module", "test",
        os.path.join(HERE, "pinefiles.py")]
print("Building Pinefiles", ff_update.APP_VERSION)
subprocess.run(args, check=True)
exe = os.path.join("dist", "Pinefiles.exe")
import ff_share  # noqa: E402
import json  # noqa: E402
with open(os.path.join("dist", "update.json"), "w", encoding="utf-8") as f:
    # with a GitHub repository set (ff_update.DEFAULT_REPO) the url points at the release asset; otherwise it stays relative
    repo = ff_update.DEFAULT_REPO
    json.dump(ff_share.manifest_for(exe, f"https://github.com/{repo}/releases/download/v{ff_update.APP_VERSION}" if repo else ""), f, indent=1)
print(f"\nDone: {os.path.abspath(exe)}  ({os.path.getsize(exe) / 1048576:.1f} MB)")
shutil.rmtree(os.path.join("build", "work"), ignore_errors=True)
