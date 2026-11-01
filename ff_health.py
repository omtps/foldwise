"""PC health checks for Foldwise.

Everything here only READS system state (disk space, drive health, memory, battery, security status, startup list,
event log). The one thing that writes is `run_backup`, which COPIES new/changed files to a destination you chose and
never deletes or overwrites anything newer.
"""
import ctypes
import json
import os
import subprocess
import time
from ctypes import wintypes

import ff_extras as X

SEV_ORDER = {"bad": 0, "warn": 1, "info": 2, "good": 3}


# ------------------------------------------------------------------------------------------ PowerShell
def _ps(script, timeout=30):
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script],
                           capture_output=True, timeout=timeout, creationflags=0x08000000)
        return r.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _json(script, timeout=30):
    out = _ps(script + " | ConvertTo-Json -Compress -Depth 4", timeout)
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def system_info():
    """Read-only hardware / OS facts: [(section, [(label, value), ...]), ...]. Nothing here changes the PC."""
    ps = r"""
$os = Get-CimInstance Win32_OperatingSystem; $cs = Get-CimInstance Win32_ComputerSystem; $bios = Get-CimInstance Win32_BIOS
$cpu = @(Get-CimInstance Win32_Processor)[0]; $gpu = @(Get-CimInstance Win32_VideoController)
$ram = @(Get-CimInstance Win32_PhysicalMemory); $disks = @(Get-CimInstance Win32_DiskDrive)
@{ os = "$($os.Caption) $($os.OSArchitecture)  (build $($os.BuildNumber), version $($os.Version))";
   installed = $os.InstallDate.ToString('yyyy-MM-dd'); boot = $os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm');
   name = $cs.Name; maker = "$($cs.Manufacturer) $($cs.Model)"; user = $env:USERNAME;
   cpu = "$($cpu.Name.Trim())  ($($cpu.NumberOfCores) cores, $($cpu.NumberOfLogicalProcessors) threads, $([math]::Round($cpu.MaxClockSpeed/1000,2)) GHz)";
   ram = "$([math]::Round($cs.TotalPhysicalMemory/1GB,1)) GB  ($($ram.Count) module(s): " + (($ram | ForEach-Object { "$([math]::Round($_.Capacity/1GB)) GB $($_.Speed) MHz" }) -join ', ') + ")";
   gpu = @($gpu | ForEach-Object { "$($_.Name)  (driver $($_.DriverVersion), $([math]::Round($_.AdapterRAM/1GB,1)) GB)" });
   disks = @($disks | ForEach-Object { "$($_.Model)  ($([math]::Round($_.Size/1GB)) GB, $($_.InterfaceType))" });
   bios = "$($bios.Manufacturer) $($bios.SMBIOSBIOSVersion)  ($($bios.ReleaseDate.ToString('yyyy-MM-dd')))" } | ConvertTo-Json -Compress -Depth 3
"""
    out = _ps(ps, 40)
    try:
        d = json.loads(out)
    except ValueError:
        return []
    return [("Windows", [("System", d.get("os", "")), ("Installed", d.get("installed", "")), ("Last start", d.get("boot", "")),
                         ("Computer name", d.get("name", "")), ("User", d.get("user", ""))]),
            ("Hardware", [("Maker / model", d.get("maker", "")), ("Processor", d.get("cpu", "")), ("Memory", d.get("ram", "")),
                          ("BIOS", d.get("bios", ""))]
             + [("Graphics", g) for g in _as_list(d.get("gpu"))] + [("Drive", x) for x in _as_list(d.get("disks"))])]


def _as_list(x):
    return x if isinstance(x, list) else ([] if x is None else [x])


# --------------------------------------------------------------------------------------------- storage
def disk_report():
    out = []
    for root, kind, free, total in X.drives():
        if total:
            out.append(dict(root=root, kind={2: "Removable", 3: "Fixed", 4: "Network"}.get(kind, "?"),
                            free=free, total=total, pct_free=free * 100.0 / total))
    return out


def physical_disks():
    """Windows' own health verdict per physical drive, plus SSD wear/temperature/errors when the drive reports them."""
    script = r"""
    Get-PhysicalDisk | ForEach-Object {
      $rc = $_ | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue
      [pscustomobject]@{ Name=$_.FriendlyName; Media=[string]$_.MediaType; Bus=[string]$_.BusType;
        Health=[string]$_.HealthStatus; Op=[string]$_.OperationalStatus; SizeGB=[math]::Round($_.Size/1GB);
        TempC=$rc.Temperature; Wear=$rc.Wear; ReadErr=$rc.ReadErrorsTotal; WriteErr=$rc.WriteErrorsTotal; Hours=$rc.PowerOnHours }
    }"""
    return _as_list(_json(script, 40))


# ----------------------------------------------------------------------------------------- memory / cpu
class _MEMSTATUS(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory():
    m = _MEMSTATUS()
    m.dwLength = ctypes.sizeof(_MEMSTATUS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return dict(total=m.ullTotalPhys, avail=m.ullAvailPhys, load=m.dwMemoryLoad)


def cpu_percent(interval=0.5):
    class FT(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    def sample():
        i, k, u = FT(), FT(), FT()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
        val = lambda f: (f.hi << 32) | f.lo
        return val(i), val(k), val(u)

    a = sample()
    time.sleep(interval)
    b = sample()
    idle, total = b[0] - a[0], (b[1] - a[1]) + (b[2] - a[2])  # kernel time includes idle time
    return max(0.0, min(100.0, (total - idle) * 100.0 / total)) if total else 0.0


def top_processes(n=6):
    script = (f"Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First {n} "
              "Name, @{n='MB';e={[int]($_.WorkingSet64/1MB)}}")
    return _as_list(_json(script, 20))


# ------------------------------------------------------------------------------------------------ battery
def battery():
    """None on a desktop. Otherwise {charge, plugged, health}: charge and plug state come straight from Windows,
    health is the full-charge capacity as a % of the design capacity (from the built-in powercfg battery report)."""
    class SPS(ctypes.Structure):
        _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("pct", ctypes.c_ubyte), ("sys", ctypes.c_ubyte),
                    ("life", wintypes.DWORD), ("full", wintypes.DWORD)]

    s = SPS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)) or s.flag == 128 or s.pct == 255:
        return None
    health = None
    try:
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), "ff_battery_report.xml")
        subprocess.run(["powercfg", "/batteryreport", "/output", tmp, "/xml"], capture_output=True, timeout=40,
                       creationflags=0x08000000)
        import re
        txt = open(tmp, encoding="utf-8", errors="replace").read()
        os.remove(tmp)
        d = re.search(r"<DesignCapacity>(\d+)</DesignCapacity>", txt)
        f = re.search(r"<FullChargeCapacity>(\d+)</FullChargeCapacity>", txt)
        if d and f and int(d.group(1)):
            health = round(int(f.group(1)) * 100.0 / int(d.group(1)))
    except Exception:
        pass
    return dict(charge=s.pct, plugged=s.ac == 1, health=health)


# ------------------------------------------------------------------------------------- uptime / restart
def uptime_hours():
    f = ctypes.windll.kernel32.GetTickCount64
    f.restype = ctypes.c_ulonglong
    return f() / 3600000.0


def pending_reboot():
    try:
        import winreg
        checks = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"),
                  (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired")]
        for hive, key in checks:
            try:
                winreg.CloseKey(winreg.OpenKey(hive, key))
                return True
            except OSError:
                pass
    except ImportError:
        pass
    return False


# ---------------------------------------------------------------------------------------------- security
def security():
    script = r"""
    $m = Get-MpComputerStatus -ErrorAction SilentlyContinue
    $f = Get-NetFirewallProfile -ErrorAction SilentlyContinue
    [pscustomobject]@{ HasDefender=[bool]$m; Av=[bool]$m.AntivirusEnabled; RealTime=[bool]$m.RealTimeProtectionEnabled;
      SigAge=$m.AntivirusSignatureAge; Firewall=@($f | ForEach-Object { [bool]$_.Enabled }) }"""
    return _json(script, 30) or {}


# ------------------------------------------------------------------------------------------------ startup
def startup_items():
    """Programs that start with Windows (registry Run keys + Startup folders). Read-only; disabled ones are left out."""
    out = []
    try:
        import winreg
    except ImportError:
        return out
    approved = {}
    for hive, name in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        try:
            with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run") as k:
                i = 0
                while True:
                    n, v, _t = winreg.EnumValue(k, i)
                    approved[(name, n)] = bool(v and v[0] % 2 == 1)  # odd first byte = disabled in Task Manager
                    i += 1
        except OSError:
            pass
    for hive, hname, path in ((winreg.HKEY_CURRENT_USER, "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
                              (winreg.HKEY_LOCAL_MACHINE, "HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
                              (winreg.HKEY_LOCAL_MACHINE, "HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run")):
        try:
            with winreg.OpenKey(hive, path) as k:
                i = 0
                while True:
                    n, v, _t = winreg.EnumValue(k, i)
                    i += 1
                    if not approved.get((hname, n)):
                        out.append(dict(name=n, command=str(v), where="Registry (" + ("current user" if hname == "HKCU" else "all users") + ")"))
        except OSError:
            pass
    for label, folder in (("Startup folder (you)", os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")),
                          ("Startup folder (all users)", os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs\StartUp"))):
        if os.path.isdir(folder):
            for f in os.listdir(folder):
                if f.lower() != "desktop.ini":
                    out.append(dict(name=os.path.splitext(f)[0], command=os.path.join(folder, f), where=label))
    return out


def startup_impact(items):
    """Adds what each start-up program costs RIGHT NOW: running (bool), mem (bytes), cpu_s (CPU seconds used so far), matched by exe path.
    (Windows' own boot-time trace needs administrator rights, so this uses real measurements of the running programs instead.)"""
    procs = _as_list(_json("@(Get-Process | Where-Object { $_.Path } | ForEach-Object { [pscustomobject]@{ P=$_.Path; M=[int64]$_.WorkingSet64; C=[double]$_.CPU } })", 60))
    by = {}
    for p in procs:
        if isinstance(p, dict) and p.get("P"):
            m, c = by.get(p["P"].lower(), (0, 0.0))
            by[p["P"].lower()] = (m + int(p.get("M") or 0), c + float(p.get("C") or 0))
    import re
    out = []
    for it in items:
        cmd = os.path.expandvars(it.get("command", ""))
        mm = re.match(r'^"([^"]+)"', cmd) or re.match(r"^(.+?\.(?:exe|bat|cmd|scr))(?:\s|$)", cmd, re.I)
        exe = (mm.group(1) if mm else cmd.split(" ")[0]).lower()
        m, c = by.get(exe, (0, 0.0))
        out.append(dict(it, running=exe in by, mem=m, cpu_s=c))
    return out


# ---------------------------------------------------------------------------------------------- event log
def disk_errors(days=30):
    script = (f"$e = Get-WinEvent -FilterHashtable @{{LogName='System'; ProviderName='disk','Ntfs','stornvme','storahci','volmgr'; "
              f"Level=1,2,3; StartTime=(Get-Date).AddDays(-{days})}} -ErrorAction SilentlyContinue; "
              "[pscustomobject]@{ Errors=@($e | Where-Object { $_.Level -le 2 }).Count; Warnings=@($e | Where-Object { $_.Level -eq 3 }).Count; "
              "Latest=@($e | Select-Object -First 3 | ForEach-Object { $_.TimeCreated.ToString('yyyy-MM-dd') + ' ' + $_.ProviderName + ' #' + $_.Id }) }")
    return _json(script, 40) or {"Errors": 0, "Warnings": 0, "Latest": []}


def problem_devices():
    """[{'Name','Code'}] devices Windows reports as having a problem (missing/failed driver, disabled by error ...)."""
    r = _json("@(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | Where-Object { $_.ConfigManagerErrorCode -ne 0 -and $_.ConfigManagerErrorCode -ne 22 } | "
              "ForEach-Object { [pscustomobject]@{ Name=$_.Name; Code=[int]$_.ConfigManagerErrorCode } })", 60)
    return [d for d in _as_list(r) if isinstance(d, dict)]


def pending_updates():
    """Titles of Windows updates waiting to be installed (asks Windows Update; takes 10-60 s). None if it couldn't be checked."""
    script = ("& { try { $s=New-Object -ComObject Microsoft.Update.Session; $r=$s.CreateUpdateSearcher().Search('IsInstalled=0 and IsHidden=0'); "
              "@($r.Updates | ForEach-Object { $_.Title }) } catch { $null } }")
    out = _ps("[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script + " | ConvertTo-Json -Compress", 120)
    if not out or out.strip() == "null":
        return None
    try:
        return [str(x) for x in _as_list(json.loads(out))]
    except ValueError:
        return None


def last_update():
    """{'Days': age of the newest installed Windows update (hotfix), 'Id': KB id} or None if unknown."""
    r = _json("& { $h = Get-HotFix -ErrorAction SilentlyContinue | Where-Object { $_.InstalledOn } | Sort-Object InstalledOn -Descending | Select-Object -First 1; "
              "if ($h) { [pscustomobject]@{ Days=[int]((Get-Date) - $h.InstalledOn).TotalDays; Id=$h.HotFixID } } }", 60)
    return r if isinstance(r, dict) else None


def installed_apps():
    """[{'Name','Publisher','Version','SizeMB','Date'}] from the Uninstall registry keys (read-only), biggest first."""
    script = ("$k='HKLM:/SOFTWARE/Microsoft/Windows/CurrentVersion/Uninstall/*','HKLM:/SOFTWARE/WOW6432Node/Microsoft/Windows/CurrentVersion/Uninstall/*',"
              "'HKCU:/SOFTWARE/Microsoft/Windows/CurrentVersion/Uninstall/*'; "
              "@(Get-ItemProperty $k -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -and -not $_.SystemComponent -and -not $_.ParentKeyName } | "
              "ForEach-Object { [pscustomobject]@{ Name=$_.DisplayName; Publisher=$_.Publisher; Version=$_.DisplayVersion; SizeMB=[int]($_.EstimatedSize/1024); Date=$_.InstallDate } })")
    r = _json(script, 60)
    apps = _as_list(r) if r else []
    seen, out = set(), []
    for a_ in apps:
        if a_["Name"] not in seen:
            seen.add(a_["Name"])
            out.append(a_)
    out.sort(key=lambda a_: -(a_.get("SizeMB") or 0))
    return out


# ---------------------------------------------------------------------------------------- space history
def record_snapshot(history, drives, today=None):
    """history: {'YYYY-MM-DD': {'C:\\': free_bytes}} (kept for 120 days). Returns a new dict."""
    today = today or time.strftime("%Y-%m-%d")
    h = {k: dict(v) for k, v in history.items()}
    h[today] = {d["root"]: d["free"] for d in drives if d["kind"] == "Fixed"}
    for k in sorted(h)[:-120]:
        h.pop(k, None)
    return h


def trend(history, root, days=7, today=None):
    """(free_bytes_now, free_bytes_N_days_ago or None) for one drive from the snapshots."""
    today = today or time.strftime("%Y-%m-%d")
    pts = sorted((d, v[root]) for d, v in history.items() if root in v)
    if not pts:
        return None, None
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.mktime(time.strptime(today, "%Y-%m-%d")) - days * 86400))
    older = [p for p in pts if p[0] <= cutoff]
    return pts[-1][1], (older[-1][1] if older else (pts[0][1] if pts[0][0] < today else None))


# -------------------------------------------------------------------------------------------------- backups
def _guard(src, dst):
    s, d = os.path.normcase(os.path.abspath(src)).rstrip("\\"), os.path.normcase(os.path.abspath(dst)).rstrip("\\")
    if not os.path.isdir(src):
        return "The source folder doesn't exist."
    if s == d or d.startswith(s + "\\") or s.startswith(d + "\\"):
        return "The backup folder can't be inside the folder you're backing up (or the other way round)."
    return None


def excluded(rel, patterns):
    """True when any folder/file name in rel (or the whole relative path) matches a skip pattern like node_modules or *.tmp."""
    import fnmatch
    if not patterns:
        return False
    parts = rel.replace("/", "\\").split("\\")
    for p in patterns:
        p = p.strip()
        if p and (fnmatch.fnmatch(rel.lower(), p.lower()) or any(fnmatch.fnmatch(part.lower(), p.lower()) for part in parts)):
            return True
    return False


def parse_patterns(text):
    return [p.strip() for p in (text or "").replace(";", ",").split(",") if p.strip()]


def backup_preview(src, dst, cancel=lambda: False, progress=lambda m: None, exclude=()):
    err = _guard(src, dst)
    if err:
        return {"error": err}
    os.makedirs(dst, exist_ok=True)
    rows = X.compare_folders(src, dst, cancel, progress)
    if rows is None:
        return None
    todo, same, newer_dst = [], 0, 0
    for rel, kind, ls, lm, rs, rm, lp, rp in rows:
        if exclude and excluded(rel, exclude):
            continue
        if kind in ("only_left", "newer_left", "differ"):
            todo.append((rel, lp, os.path.join(dst, rel), ls or 0, kind != "only_left"))
        elif kind == "same":
            same += 1
        elif kind == "newer_right":
            newer_dst += 1
    return {"todo": todo, "same": same, "newer_dst": newer_dst, "bytes": sum(t[3] for t in todo),
            "new": sum(1 for t in todo if not t[4]), "changed": sum(1 for t in todo if t[4])}


def run_backup(src, dst, cancel=lambda: False, progress=lambda i, n, name: None, exclude=()):
    """Copy new and changed files from src into dst. Never deletes; never overwrites a newer file in dst."""
    prev = backup_preview(src, dst, cancel, exclude=exclude)
    if prev is None or "error" in prev:
        return prev
    copied, nbytes, errors = 0, 0, []
    cancelled = False
    for i, (rel, sp, dp, size, existed) in enumerate(prev["todo"]):
        if cancel():
            cancelled = True
            break
        progress(i, len(prev["todo"]), rel)
        try:
            X.copy_file_to(sp, dp)
            copied += 1
            nbytes += size
        except OSError as e:
            errors.append((rel, str(e)))
    progress(len(prev["todo"]), len(prev["todo"]), "")
    return {"copied": copied, "bytes": nbytes, "errors": errors, "unchanged": prev["same"], "kept_newer": prev["newer_dst"],
            "cancelled": cancelled}


# ------------------------------------------------------------------------------------------- security audit
_SEC_PS = r"""
$o = [ordered]@{}
function reg($p,$n){ try { (Get-ItemProperty -Path $p -Name $n -ErrorAction Stop).$n } catch { $null } }
$o.UAC = reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'EnableLUA'
$o.SecureBoot = reg 'HKLM:\SYSTEM\CurrentControlSet\Control\SecureBoot\State' 'UEFISecureBootEnabled'
$o.RdpDeny = reg 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server' 'fDenyTSConnections'
$o.Smb1 = reg 'HKLM:\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters' 'SMB1'
$o.SmartScreen = reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer' 'SmartScreenEnabled'
try { $o.BitLocker = (New-Object -ComObject Shell.Application).NameSpace('C:').Self.ExtendedProperty('System.Volume.BitLockerProtection') } catch { $o.BitLocker = $null }
try { $o.Guest = (Get-LocalUser -Name Guest -ErrorAction Stop).Enabled } catch { $o.Guest = $null }
try { $o.Admins = @(Get-LocalGroupMember -Group Administrators -ErrorAction Stop | ForEach-Object { $_.Name }) } catch { $o.Admins = $null }
try { $s = Get-MpComputerStatus -ErrorAction Stop; $o.QuickScanAge = $s.QuickScanAge; $o.FullScanAge = $s.FullScanAge; $o.Tamper = $s.IsTamperProtected } catch { }
try { $o.Threats = @(Get-MpThreatDetection -ErrorAction Stop | Where-Object { $_.InitialDetectionTime -gt (Get-Date).AddDays(-30) } | ForEach-Object { [string]$_.ThreatID + ' ' + $_.InitialDetectionTime.ToString('yyyy-MM-dd') }) } catch { $o.Threats = $null }
try { $o.Listen = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalAddress -in '0.0.0.0','::' } | ForEach-Object { $p = (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName; "$($_.LocalPort) $p" } | Sort-Object -Unique) } catch { $o.Listen = $null }
try { $o.Hosts = @(Get-Content "$env:SystemRoot\System32\drivers\etc\hosts" -ErrorAction Stop | Where-Object { $_ -and $_ -notmatch '^\s*#' -and $_ -notmatch '^\s*$' }) } catch { $o.Hosts = $null }
try { $o.Tasks = @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskPath -notlike '\Microsoft*' -and $_.State -ne 'Disabled' } | ForEach-Object { $_.TaskName }) } catch { $o.Tasks = $null }
[pscustomobject]$o

"""


def security_raw():
    """Raw read-only facts about the machine's security settings (one PowerShell call, ~8 s)."""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".ps1")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            f.write(_SEC_PS.strip() + " | ConvertTo-Json -Compress -Depth 4")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path],
                             capture_output=True, timeout=90, creationflags=0x08000000).stdout.decode("utf-8", "replace").strip()
        r = json.loads(out) if out else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        r = None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return r if isinstance(r, dict) else None


def security_findings(r):
    """[(severity, title, detail, action)] in plain language from security_raw(). Severity: good/warn/bad/info."""
    if not r:
        return []
    out = []
    add = lambda sev, title, detail, act=None: out.append((sev, title, detail, act))
    if r.get("UAC") == 0:
        add("bad", "User Account Control is OFF", "Programs can change your PC without asking. Turn it back on in Windows Security settings.", "security")
    elif r.get("UAC") == 1:
        add("good", "User Account Control is on", "Windows asks before programs make system changes.")
    sb = r.get("SecureBoot")
    if sb == 0:
        add("warn", "Secure Boot is off", "Secure Boot stops tampered start-up software (rootkits). It is switched on in the BIOS/UEFI.")
    elif sb == 1:
        add("good", "Secure Boot is on", "The PC only starts trusted system software.")
    bl = r.get("BitLocker")
    if bl == 1:
        add("good", "Drive C: is encrypted (BitLocker)", "If the PC is stolen the data can't be read.")
    elif bl == 0:
        add("info", "Drive C: is not encrypted", "On a laptop, encryption protects your files if it is lost or stolen.")
    if r.get("RdpDeny") == 0:
        add("warn", "Remote Desktop is enabled", "Anyone who knows your password and can reach this PC could take control of it. Turn it off if you don't use it.")
    elif r.get("RdpDeny") == 1:
        add("good", "Remote Desktop is off", "Nobody can connect to control this PC remotely.")
    if r.get("Smb1") == 1:
        add("bad", "Old SMBv1 file sharing is enabled", "This outdated protocol is what the WannaCry ransomware used. Turn it off.")
    if r.get("Guest") is True:
        add("warn", "The Guest account is enabled", "A password-less account lets anyone log in. Disable it.")
    elif r.get("Guest") is False:
        add("good", "Guest account is disabled", "")
    adm = _as_list(r.get("Admins"))
    if adm:
        add("info", f"{len(adm)} administrator account(s)", ", ".join(adm) + ". Only accounts you recognise should be here.")
    q = r.get("QuickScanAge")
    if q is not None:
        if q >= 4294967000:
            add("warn", "No virus scan has ever run", "Run a quick scan from the Overview tab.", "security")
        elif q > 14:
            add("warn", f"Last quick virus scan was {q} days ago", "Run a quick scan from the Overview tab.", "security")
        else:
            add("good", f"Last quick virus scan: {q} day(s) ago", "")
    if r.get("Tamper") is False:
        add("warn", "Defender Tamper Protection is off", "Malware could switch your antivirus off. Turn it on in Windows Security.", "security")
    th = _as_list(r.get("Threats"))
    if th:
        add("bad", f"Defender found {len(th)} threat(s) in the last 30 days", ", ".join(th[:5]) + ". Open Windows Security to check they were removed.", "security")
    elif r.get("Threats") is not None:
        add("good", "No threats detected in the last 30 days", "")
    hosts = _as_list(r.get("Hosts"))
    if hosts:
        add("warn", f"The hosts file redirects {len(hosts)} address(es)", "; ".join(h.strip() for h in hosts[:4]) + ". Malware often edits this file. Remove entries you don't recognise.")
    elif r.get("Hosts") is not None:
        add("good", "The hosts file is clean", "No website redirections are set.")
    ports = _as_list(r.get("Listen"))
    if ports:
        add("info", f"{len(ports)} program(s) accept connections from the network",
            "Port / program: " + ", ".join(ports[:14]) + (" \u2026" if len(ports) > 14 else "") + ". Normal for file sharing, VMs and some apps; unknown names deserve a look.")
    tasks = _as_list(r.get("Tasks"))
    if tasks:
        add("info", f"{len(tasks)} non-Microsoft scheduled task(s) run automatically", ", ".join(t[:40] for t in tasks[:8]) + (" \u2026" if len(tasks) > 8 else "") +
            ". Check them in Task Scheduler if you see anything unfamiliar.")
    return out


# ------------------------------------------------------------------------------- trends + threat alerts
def defender_threats(days=30):
    """[{'Id','Time','Name','Res'}] Defender detections of the last `days` days (read-only)."""
    r = _json("@(Get-MpThreatDetection -ErrorAction SilentlyContinue | Where-Object { $_.InitialDetectionTime -gt (Get-Date).AddDays(-" + str(int(days)) + ") } | "
              "ForEach-Object { [pscustomobject]@{ Id=[string]$_.ThreatID; Time=$_.InitialDetectionTime.ToString('yyyy-MM-dd HH:mm'); "
              "Name=(Get-MpThreat -ThreatID $_.ThreatID -ErrorAction SilentlyContinue).ThreatName; Res=($_.Resources -join '; ') } })", 60)
    return [t for t in _as_list(r) if isinstance(t, dict)]


def new_threats(found, seen):
    """Detections whose Id+Time were not seen before."""
    return [t for t in found if f"{t['Id']}|{t['Time']}" not in set(seen)]


def threat_key(t):
    return f"{t['Id']}|{t['Time']}"


def perf_sample():
    m = memory() or {}
    return {"t": time.time(), "cpu": cpu_percent(0.3), "mem": m.get("load")}


def hourly_sample():
    """Slower facts for the trend graphs: battery %, charging, drive temperature/wear, biggest memory user."""
    b = battery() or {}
    ph = (physical_disks() or [{}])
    p0 = ph[0] if ph else {}
    procs = top_processes(3) or []
    return {"t": time.time(), "bat": b.get("charge"), "charging": b.get("plugged"), "bat_health": b.get("health"),
            "temp": p0.get("TempC"), "wear": p0.get("Wear"), "top": [pp.get("Name") for pp in procs]}


def history_load(path):
    try:
        with open(path, encoding="utf-8") as f:
            h = json.load(f)
        return {"perf": h.get("perf", []), "hourly": h.get("hourly", []), "folders": h.get("folders", [])}
    except (OSError, ValueError):
        return {"perf": [], "hourly": [], "folders": []}


def history_add(path, kind, sample, keep=None):
    """Append a sample to the history file (perf: last 7 days of 5-minute samples, hourly: last 60 days)."""
    h = history_load(path)
    h[kind].append(sample)
    keep = keep or (2016 if kind == "perf" else 52 if kind == "folders" else 1440)
    del h[kind][:-keep]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(h, f)
    os.replace(tmp, path)
    return h


def folder_roots():
    home = os.path.expanduser("~")
    roots = []
    for base in (home, os.path.join(home, "AppData", "Local"), os.path.join(home, "AppData", "Roaming"), os.environ.get("PROGRAMDATA") or r"C:\ProgramData"):
        try:
            for e in os.scandir(base):
                if e.is_dir(follow_symlinks=False) and not (base == home and e.name.lower() in ("appdata",) or e.name.startswith(".") and base == home):
                    roots.append(e.path)
        except OSError:
            pass
    return roots


def folder_snapshot(cancel=lambda: False, roots=None, pause=0.0):
    """{folder: bytes} for the first-level folders of your profile, AppData and ProgramData (read-only; can take a minute or two)."""
    out = {}
    for r in (roots if roots is not None else folder_roots()):
        total, stack = 0, [r]
        while stack:
            if cancel():
                return None
            try:
                with os.scandir(stack.pop()) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                stack.append(e.path)
                            else:
                                total += e.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
            except OSError:
                pass
            if pause:
                time.sleep(pause)
        out[r] = total
    return out


def folder_growth(snapshots, days=30, now=None, top=5):
    """[(folder, grew_bytes)] biggest growth between the newest snapshot and the one ~`days` ago (needs two snapshots)."""
    if len(snapshots) < 2:
        return []
    now = now or time.time()
    new = snapshots[-1]
    old = min(snapshots[:-1], key=lambda s: abs((now - s["t"]) - days * 86400))
    rows = [(p, sz - old["sizes"].get(p, 0)) for p, sz in new["sizes"].items()]
    return sorted((r for r in rows if r[1] > 50 << 20), key=lambda r: -r[1])[:top]


# ---- folder size history: folders YOU choose to follow (size sampled when added and then weekly)
def track_load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return {"samples": {k: [tuple(s) for s in v] for k, v in d.get("samples", {}).items()}}
    except (OSError, ValueError, TypeError):
        return {"samples": {}}


def track_save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def track_add(data, folder, size, now=None, keep=260):
    """Add one (time, bytes) sample for `folder` (about 5 years of weekly samples are kept)."""
    lst = data["samples"].setdefault(folder, [])
    lst.append((now or time.time(), int(size)))
    del lst[:-keep]
    return data


def track_change(samples, days=30, now=None):
    """(latest_bytes, change_bytes_or_None) vs the sample closest to `days` ago; None when there is only one sample."""
    if not samples:
        return 0, None
    now = now or time.time()
    last = samples[-1]
    if len(samples) < 2:
        return last[1], None
    old = min(samples[:-1], key=lambda s: abs((now - s[0]) - days * 86400))
    return last[1], last[1] - old[1]


def track_measure(folder, cancel=lambda: False, pause=0.0):
    """Total bytes below `folder` (None when cancelled); read-only."""
    res = folder_snapshot(cancel, roots=[folder], pause=pause)
    return None if res is None else res.get(folder, 0)


def series(samples, key, since=0):
    """[(t, value)] for samples having a numeric `key` after time `since`."""
    return [(s["t"], s[key]) for s in samples if s.get("t", 0) >= since and isinstance(s.get(key), (int, float))]


# ------------------------------------------------------------------------------------------------ network
def _ping(host, count=4, timeout_ms=1500):
    """{'sent','lost','avg'} via the system ping (avg in ms or None). Parses digits only, so it works in any language."""
    import re
    try:
        r = subprocess.run(["ping", "-n", str(count), "-w", str(timeout_ms), host], capture_output=True, timeout=count * (timeout_ms / 1000 + 1) + 5,
                           creationflags=0x08000000)
    except (OSError, subprocess.TimeoutExpired):
        return {"sent": count, "lost": count, "avg": None}
    out = r.stdout.decode("cp850", "replace")
    got = [int(m) for m in re.findall(r"[=<](\d+)\s*(?:ms|мс)", out, re.I)]
    replies = len(re.findall(r"TTL=", out, re.I))
    ms = [v for v in got][:replies] if replies else []
    return {"sent": count, "lost": count - replies, "avg": (sum(ms) / len(ms) if ms else None)}


def default_gateway():
    import re
    try:
        out = subprocess.run(["ipconfig"], capture_output=True, timeout=10, creationflags=0x08000000).stdout.decode("cp850", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(?:Default Gateway|Gateway)[ .]*:\s*((?:\d+\.){3}\d+)", out, re.I)
    return m.group(1) if m else None


def dns_time(host="www.microsoft.com"):
    import socket
    t = time.time()
    try:
        socket.getaddrinfo(host, 443)
        return (time.time() - t) * 1000
    except OSError:
        return None


def wifi_info():
    """{'ssid','signal','rate','channel'} of the connected Wi-Fi (English Windows wording), or None (cable / no Wi-Fi / other language)."""
    import re
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, timeout=15, creationflags=0x08000000).stdout.decode("cp850", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return None

    def g(label):
        m = re.search(r"^\s*" + label + r"\s*:\s*(.+)$", out, re.M | re.I)
        return m.group(1).strip() if m else None
    ssid, sig = g("SSID"), g("Signal")
    if not ssid or not sig:
        return None
    return {"ssid": ssid, "signal": int(re.sub(r"\D", "", sig) or 0), "rate": g("Receive rate \\(Mbps\\)"), "channel": g("Channel")}


def speed_test(nbytes=25_000_000, url="https://speed.cloudflare.com/__down?bytes=%d", progress=lambda done, total: None, cancel=lambda: False):
    """Download speed in Mbit/s: fetches `nbytes` from Cloudflare's public speed-test endpoint (sends nothing about you)."""
    import urllib.request
    req = urllib.request.Request(url % nbytes if "%d" in url else url, headers={"User-Agent": "Foldwise"})
    t0, got = time.time(), 0
    with urllib.request.urlopen(req, timeout=30) as r:
        while True:
            if cancel():
                break
            b = r.read(1 << 17)
            if not b:
                break
            got += len(b)
            progress(got, nbytes)
    dt = max(time.time() - t0, 0.001)
    return got * 8 / dt / 1e6


def network_report():
    gw = default_gateway()
    return {"gateway": gw, "gw_ping": _ping(gw) if gw else None, "net_ping": _ping("1.1.1.1"), "dns_ms": dns_time(), "at": time.time()}


def network_lines(n):
    """Plain-language lines [(severity, text)] for a network_report()."""
    L = []
    gp, npg = n.get("gw_ping"), n["net_ping"]
    if not n.get("gateway"):
        L.append(("bad", "No network connection (no gateway found). Check Wi-Fi / cable."))
    elif gp and gp["lost"] == gp["sent"]:
        L.append(("bad", f"Your router ({n['gateway']}) doesn't answer. Check your Wi-Fi/cable or restart the router."))
    elif gp:
        L.append(("good", f"Router {n['gateway']}: {gp['avg']:.0f} ms" + (f", {gp['lost']} of {gp['sent']} lost" if gp["lost"] else ", no loss")))
    if npg["lost"] == npg["sent"]:
        L.append(("bad", "Internet unreachable (1.1.1.1 doesn't answer)."))
    else:
        sev = "warn" if npg["lost"] or (npg["avg"] or 0) > 150 else "good"
        L.append((sev, f"Internet: {npg['avg']:.0f} ms" + (f", {npg['lost']} of {npg['sent']} packets lost" if npg["lost"] else ", no loss")))
    if n["dns_ms"] is None:
        L.append(("bad" if npg["lost"] < npg["sent"] else "info", "Names can't be looked up (DNS problem)" + (" although the internet works — try another DNS server." if npg["lost"] < npg["sent"] else ".")))
    else:
        L.append(("warn" if n["dns_ms"] > 500 else "good", f"DNS lookup: {n['dns_ms']:.0f} ms"))
    return L


# ------------------------------------------------------------------------------- scheduled backups
SCHEDULE_DAYS = {"daily": 1, "weekly": 7}
SCHEDULE_LABEL = {"off": "Manual only", "daily": "Daily", "weekly": "Weekly"}
RETRY_AFTER = 3600  # a failed/skipped attempt is retried after an hour, not every tick


def idle_seconds():
    """Seconds since the last keyboard/mouse input (0 if unknown)."""
    class LII(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
    try:
        li = LII(ctypes.sizeof(LII), 0)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            return max(0, (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0)
    except Exception:
        pass
    return 0.0


def job_due(job, now=None):
    """True when a scheduled job should run now (never for manual jobs)."""
    now = now or time.time()
    days = SCHEDULE_DAYS.get(job.get("schedule"))
    if not days:
        return False
    attempt = job.get("attempt") or 0
    if attempt and now - attempt < (RETRY_AFTER if job.get("ok") is False else 3600):
        return False
    last = job.get("last") or 0
    if not last:
        return True
    return now - last >= days * 86400 - 3600  # an hour of slack so "daily" really is daily


def next_run_text(job, now=None):
    now = now or time.time()
    days = SCHEDULE_DAYS.get(job.get("schedule"))
    if not days:
        return "—"
    if job_due(job, now):
        return "when idle"
    due = (job.get("last") or now) + days * 86400
    return time.strftime("%a %d %b", time.localtime(max(due, now)))


def summarize(res, human=lambda n: str(n)):
    if res["copied"]:
        s = f"Copied {res['copied']} file(s), {human(res['bytes'])}"
    else:
        s = "Up to date"
    return s + (f"; {len(res['errors'])} failed" if res["errors"] else "")


def run_scheduled(job, cancel=lambda: False, human=lambda n: str(n)):
    """Run one job unattended. Returns (ok, message). Skips (ok=False) when a drive isn't there, so removable
    backup disks that aren't plugged in just wait for next time instead of creating folders on the wrong place."""
    src, dst = job["src"], job["dst"]
    if not os.path.isdir(src):
        return False, "Skipped: the source folder isn't available"
    drv = os.path.splitdrive(os.path.abspath(dst))[0]
    if drv and not os.path.exists(drv + "\\"):
        return False, f"Skipped: drive {drv} isn't connected"
    try:
        res = run_backup(src, dst, cancel, exclude=parse_patterns(job.get("exclude")))
    except Exception as e:
        return False, f"Failed: {e}"
    if res is None:
        return False, "Cancelled"
    if "error" in res:
        return False, "Failed: " + res["error"]
    if res.get("cancelled"):
        return False, f"Paused: you came back to the PC ({res['copied']} file(s) copied so far); it will continue later"
    return (not res["errors"]), summarize(res, human)


# ----------------------------------------------------------------------------------------- recommendations
def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def recommendations(h, now=None):
    """Turn collected facts into [(severity, text, action)] and a 0-100 score. `h` holds whatever has been collected so far."""
    now = now or time.time()
    r = []
    add = lambda sev, text, action=None: r.append((sev, text, action))
    for d in h.get("drives", []):
        if d["kind"] != "Fixed":
            continue
        name = d["root"].rstrip("\\")
        if d["pct_free"] < 10 or d["free"] < 10 * 2 ** 30:
            add("bad", f"{name} is almost full: only {human(d['free'])} free ({d['pct_free']:.0f}%). Free some space before Windows slows down.", "cleaner")
        elif d["pct_free"] < 20:
            add("warn", f"{name} is getting full: {human(d['free'])} free ({d['pct_free']:.0f}%). A clean-up would help.", "cleaner")
        now_free, old_free = trend(h.get("history", {}), d["root"])
        if now_free is not None and old_free is not None and old_free - now_free > max(15 * 2 ** 30, d["total"] * 0.05):
            add("info", f"{name} lost {human(old_free - now_free)} of free space in the last week. Something is filling it up.", "largest")
    for p in h.get("physical", []):
        who = p.get("Name") or "A drive"
        if p.get("Health") not in (None, "Healthy"):
            add("bad", f"{who} reports its health as \u201C{p.get('Health')}\u201D. Back up your files now and plan to replace it.", "backup")
        elif p.get("Op") not in (None, "OK"):
            add("warn", f"{who} reports status \u201C{p.get('Op')}\u201D.", None)
        if (p.get("Wear") or 0) >= 80:
            add("warn", f"{who} has used {p['Wear']}% of its rated lifetime (SSD wear). Keep backups current.", "backup")
        if (p.get("TempC") or 0) >= 70:
            add("warn", f"{who} is running hot ({p['TempC']}\u00B0C). Check airflow and dust.", None)
        if (p.get("ReadErr") or 0) > 0 or (p.get("WriteErr") or 0) > 0:
            add("warn", f"{who} has logged read/write errors ({p.get('ReadErr') or 0}/{p.get('WriteErr') or 0}). Make sure your backups are current.", "backup")
    m = h.get("mem")
    if m and m["load"] >= 90:
        top = (h.get("procs") or [{}])[0].get("Name")
        add("warn", f"Memory is {m['load']}% full" + (f" \u2014 {top} uses the most." if top else ".") + " Close programs you don't need or restart.", "taskmgr")
    b = h.get("battery")
    if b and b.get("health") is not None:
        if b["health"] < 60:
            add("warn", f"Battery holds only {b['health']}% of its original capacity. Consider replacing it.", None)
        elif b["health"] < 80:
            add("info", f"Battery is at {b['health']}% of its original capacity (normal wear).", None)
    up = h.get("uptime")
    if h.get("reboot"):
        add("warn", "Windows is waiting for a restart to finish installing updates.", None)
    elif up is not None and up / 24 > 14:
        add("warn", f"This PC hasn't been restarted for {up / 24:.0f} days. Restarting clears memory leaks and applies updates.", None)
    s = h.get("security")
    if s:
        if s.get("HasDefender"):
            if not s.get("Av") or not s.get("RealTime"):
                add("bad", "Windows Defender real-time protection is off.", "security")
            if (s.get("SigAge") or 0) > 7:
                add("warn", f"Virus definitions are {s['SigAge']} days old. Run Windows Update.", "update")
        fw = _as_list(s.get("Firewall"))
        if fw and not all(fw):
            add("warn", "Windows Firewall is turned off on at least one network profile.", "security")
    st = h.get("startup")
    if st is not None and len(st) > 15:
        add("info", f"{len(st)} programs start with Windows, which slows startup. Review them in Task Manager.", "taskmgr")
    e = h.get("errors")
    if e and e.get("Errors", 0) > 0:
        add("bad", f"Windows logged {e['Errors']} disk error(s) in the last 30 days (latest: {', '.join(e.get('Latest') or [])}). Back up your files.", "backup")
    elif e and e.get("Warnings", 0) > 10:
        add("warn", f"Windows logged {e['Warnings']} disk warnings in the last 30 days. Keep an eye on it and keep backups current.", "backup")
    pd = h.get("devices")
    if pd:
        add("warn", f"{len(pd)} device(s) have a driver problem: " + ", ".join(d["Name"] for d in pd[:3]) + (" \u2026" if len(pd) > 3 else "") + ". Open Device Manager.", "devmgr")
    pu = h.get("pending_updates")
    if pu:
        add("warn" if len(pu) >= 5 else "info", f"{len(pu)} Windows update(s) are waiting to be installed (e.g. {pu[0][:70]}).", "update")
    u = h.get("updates")
    if u and u.get("Days") is not None:
        if u["Days"] > 90:
            add("bad", f"No Windows update was installed for {u['Days']} days (latest: {u.get('Id')}). Run Windows Update.", "update")
        elif u["Days"] > 45:
            add("warn", f"The last Windows update was installed {u['Days']} days ago. Check Windows Update.", "update")
    for sev, title, detail, act in security_findings(h.get("secaudit")):
        if sev in ("bad", "warn"):
            add(sev, title + ". " + detail, act)
    net = h.get("net")
    if net:
        for sev, text in network_lines(net):
            if sev in ("bad", "warn"):
                add(sev, text, None)
    jobs = h.get("backups")
    if jobs is not None:
        if not jobs:
            add("warn", "You have no backup set up. If this drive fails, your files are gone. Add a backup job on the Backups tab.", "backup")
        for j in jobs:
            last = j.get("last")
            days = (now - last) / 86400 if last else None
            nm = os.path.basename(j["src"].rstrip("\\")) or j["src"]
            if days is None:
                add("warn", f"Backup of \u201C{nm}\u201D has never been run.", "backup")
            elif days > 30:
                add("bad", f"Backup of \u201C{nm}\u201D is {days:.0f} days old.", "backup")
            elif days > 14:
                add("warn", f"Backup of \u201C{nm}\u201D is {days:.0f} days old.", "backup")
    score = 100
    for sev, _t, _a in r:
        score -= {"bad": 25, "warn": 10, "info": 2}.get(sev, 0)
    r.sort(key=lambda x: SEV_ORDER[x[0]])
    if not r:
        add("good", "Everything looks healthy.", None)
    return r, max(0, score)


def score_label(score):
    return "Excellent" if score >= 90 else "Good" if score >= 75 else "Needs attention" if score >= 50 else "Poor"


# ----------------------------------------------------------------------------------------------- HTML report
def report_html(h, now=None):
    """A self-contained, printable health report from whatever facts `h` holds (same dict the Health Center uses)."""
    import html
    esc = lambda x: html.escape(str(x))
    now = now or time.time()
    recs, score = recommendations(h, now)
    col = {"good": "#16a34a", "warn": "#ca8a04", "bad": "#dc2626", "info": "#475569"}
    out = ["<!doctype html><meta charset=utf-8><title>PC health report</title><style>body{font:15px Segoe UI,sans-serif;max-width:900px;margin:30px auto;padding:0 16px;color:#1e293b}"
           "h1{margin-bottom:0}h2{border-bottom:2px solid #e2e8f0;padding-bottom:4px;margin-top:28px}table{border-collapse:collapse;width:100%}"
           "td,th{text-align:left;padding:5px 8px;border-bottom:1px solid #e2e8f0}.s{font-size:54px;font-weight:700}.bar{background:#e2e8f0;height:10px;border-radius:5px}"
           ".bar i{display:block;height:10px;border-radius:5px;background:#3b82f6}@media print{body{margin:0}}</style>",
           f"<h1>PC health report</h1><div style='color:#64748b'>{esc(time.strftime('%A %d %B %Y, %H:%M', time.localtime(now)))} &middot; made by Foldwise</div>",
           f"<div class=s style='color:{col['good'] if score >= 75 else col['warn'] if score >= 50 else col['bad']}'>{score}<small style='font-size:20px'> / 100 &mdash; {esc(score_label(score))}</small></div>",
           "<h2>What needs attention</h2><ul>"]
    for sev, text, _a in recs:
        out.append(f"<li style='color:{col[sev]}'><span style='color:#1e293b'>{esc(text)}</span></li>")
    out.append("</ul>")
    if h.get("drives"):
        out.append("<h2>Drives</h2><table><tr><th>Drive<th>Type<th>Size<th>Free<th>Used</tr>")
        for d in h["drives"]:
            used = 100 - d["pct_free"]
            out.append(f"<tr><td>{esc(d['root'])}<td>{esc(d['kind'])}<td>{human(d['total'])}<td>{human(d['free'])} ({d['pct_free']:.0f}%)"
                       f"<td><div class=bar><i style='width:{used:.0f}%'></i></div></tr>")
        out.append("</table>")
    if h.get("physical"):
        out.append("<h2>Physical disks</h2><table><tr><th>Disk<th>Health<th>Temp<th>Wear<th>Power-on hours</tr>")
        for p in h["physical"]:
            out.append(f"<tr><td>{esc(p.get('Name') or '?')}<td>{esc(p.get('Health') or '?')}<td>{esc(p.get('TempC') or '—')}"
                       f"<td>{esc(str(p.get('Wear')) + '%' if p.get('Wear') is not None else '—')}<td>{esc(p.get('Hours') or '—')}</tr>")
        out.append("</table>")
    facts = []
    if h.get("mem"):
        facts.append(("Memory in use", f"{h['mem']['load']}%"))
    if h.get("uptime") is not None:
        facts.append(("Uptime", f"{h['uptime'] / 24:.1f} days"))
    if h.get("battery") and h["battery"].get("health") is not None:
        facts.append(("Battery capacity", f"{h['battery']['health']}% of original"))
    if h.get("startup") is not None:
        facts.append(("Startup programs", len(h["startup"])))
    s = h.get("security")
    if s:
        facts.append(("Defender real-time protection", "on" if s.get("RealTime") else "OFF"))
        facts.append(("Virus definitions age", f"{s.get('SigAge', '?')} days"))
    if facts:
        out.append("<h2>System</h2><table>" + "".join(f"<tr><td>{esc(k)}<td>{esc(v)}</tr>" for k, v in facts) + "</table>")
    sec = security_findings(h.get("secaudit"))
    if sec:
        out.append("<h2>Security checks</h2><table>")
        for sev, title, detail, _a in sorted(sec, key=lambda r: {"bad": 0, "warn": 1, "info": 2, "good": 3}[r[0]]):
            out.append(f"<tr><td style='color:{col[sev]}'>&#9679;<td>{esc(title)}<td style='color:#64748b'>{esc(detail)}</tr>")
        out.append("</table>")
    if h.get("backups") is not None:
        out.append("<h2>Backups</h2>")
        if not h["backups"]:
            out.append("<p>No backup jobs are set up.</p>")
        else:
            out.append("<table><tr><th>Folder<th>Into<th>Schedule<th>Last backup<th>Result</tr>")
            for j in h["backups"]:
                last = time.strftime("%Y-%m-%d %H:%M", time.localtime(j["last"])) if j.get("last") else "never"
                out.append(f"<tr><td>{esc(j['src'])}<td>{esc(j['dst'])}<td>{esc(SCHEDULE_LABEL.get(j.get('schedule'), 'Manual only'))}<td>{last}<td>{esc(j.get('result', ''))}</tr>")
            out.append("</table>")
    return "".join(out)


def collect(backups=(), history=None):
    """Gather every check (slow: several seconds) into one dict for recommendations()/report_html()."""
    def safe(fn, default=None):
        try:
            return fn()
        except Exception:
            return default
    up, rb = safe(uptime_hours), safe(pending_reboot, False)
    m = safe(memory)
    return {"drives": safe(disk_report, []), "history": history or {}, "physical": safe(physical_disks, []), "mem": m,
            "procs": safe(top_processes, []), "battery": safe(battery), "uptime": up, "reboot": rb, "security": safe(security),
            "startup": safe(startup_items), "errors": safe(disk_errors), "updates": safe(last_update), "secaudit": safe(security_raw), "devices": safe(problem_devices, []), "pending_updates": safe(pending_updates), "backups": list(backups)}


def weekly_summary(h):
    """(title-less text, n_attention) for the weekly toast."""
    recs, score = recommendations(h)
    n = sum(1 for r in recs if r[0] in ("bad", "warn"))
    top = next((r[1] for r in recs if r[0] in ("bad", "warn")), None)
    return (f"Weekly check-up: health score {score}/100 ({score_label(score)})." +
            (f" {n} thing(s) need attention, e.g. {top}" if n else " Nothing needs attention.")), n
