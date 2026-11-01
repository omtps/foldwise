"""Things Windows only allows with administrator rights: full drive health (SMART counters), TPM and BitLocker status, and
creating a System Restore point. Foldwise itself never runs as administrator: each action starts ONE short PowerShell script
through Windows' own permission prompt (UAC), which you must approve, writes its result to a temp file and ends."""
import json
import os
import subprocess
import tempfile
import time

NO_WINDOW = 0x08000000

INFO_SCRIPT = r"""
$o = [ordered]@{}
try { $o.Drives = @(Get-PhysicalDisk | ForEach-Object { $c = $_ | Get-StorageReliabilityCounter; [pscustomobject]@{ Name=$_.FriendlyName; Health=[string]$_.HealthStatus;
  TempC=$c.Temperature; WearPct=$c.Wear; PowerOnHours=$c.PowerOnHours; ReadErrors=$c.ReadErrorsTotal; WriteErrors=$c.WriteErrorsTotal } }) } catch { $o.Drives = $null }
try { $t = Get-Tpm; $o.Tpm = [pscustomobject]@{ Present=$t.TpmPresent; Ready=$t.TpmReady; Enabled=$t.TpmEnabled } } catch { $o.Tpm = $null }
try { $o.BitLocker = @(Get-BitLockerVolume | ForEach-Object { [pscustomobject]@{ Volume=$_.MountPoint; Protection=[string]$_.ProtectionStatus; Percent=$_.EncryptionPercentage } }) } catch { $o.BitLocker = $null }
$o | ConvertTo-Json -Compress -Depth 5 | Set-Content -Path $env:FF_OUT -Encoding UTF8
"""

RESTORE_SCRIPT = r"""
$r = @{ ok = $false; message = '' }
try { Checkpoint-Computer -Description 'Foldwise before cleanup' -RestorePointType MODIFY_SETTINGS -ErrorAction Stop; $r.ok = $true; $r.message = 'Restore point created.' }
catch { $r.message = $_.Exception.Message }
$r | ConvertTo-Json -Compress | Set-Content -Path $env:FF_OUT -Encoding UTF8
"""


def run_elevated(script, timeout=180, cancel=lambda: False):
    """Run `script` through a UAC prompt; returns the parsed JSON it wrote, or None if the prompt was declined / timed out."""
    d = tempfile.mkdtemp(prefix="ffel_")
    ps1, out = os.path.join(d, "task.ps1"), os.path.join(d, "out.json")
    with open(ps1, "w", encoding="utf-8-sig") as f:
        f.write(script)
    launcher = ("$env:FF_OUT='" + out + "'; Start-Process powershell -Verb RunAs -WindowStyle Hidden "
                "-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','" + ps1 + "' -Wait")
    # the elevated child inherits FF_OUT from this launcher's environment
    p = subprocess.Popen(["powershell", "-NoProfile", "-Command", launcher], creationflags=NO_WINDOW)
    t0 = time.time()
    while p.poll() is None and time.time() - t0 < timeout and not cancel():
        time.sleep(0.5)
    if p.poll() is None:
        p.kill()
    try:
        with open(out, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
    finally:
        for n in (ps1, out):
            try:
                os.remove(n)
            except OSError:
                pass
        try:
            os.rmdir(d)
        except OSError:
            pass


def full_info(**kw):
    return run_elevated(INFO_SCRIPT, **kw)


def create_restore_point(**kw):
    return run_elevated(RESTORE_SCRIPT, **kw)


def describe(info):
    """Plain-language lines from full_info() output."""
    if not info:
        return ["No answer: the administrator prompt was declined or timed out."]
    lines = []
    for d in info.get("Drives") or []:
        bits = [d.get("Health") or "?"]
        if d.get("TempC") is not None:
            bits.append(f"{d['TempC']}\u00B0C")
        if d.get("WearPct") is not None:
            bits.append(f"{d['WearPct']}% worn")
        if d.get("PowerOnHours") is not None:
            bits.append(f"{d['PowerOnHours']} h powered on")
        if d.get("ReadErrors") or d.get("WriteErrors"):
            bits.append(f"errors: {d.get('ReadErrors') or 0} read / {d.get('WriteErrors') or 0} write")
        lines.append(f"{d.get('Name')}: " + ", ".join(bits))
    t = info.get("Tpm")
    if t:
        lines.append("TPM security chip: " + ("ready" if t.get("Ready") else "present but not ready" if t.get("Present") else "not present"))
    for b in info.get("BitLocker") or []:
        lines.append(f"BitLocker {b.get('Volume')}: {b.get('Protection')} ({b.get('Percent')}% encrypted)")
    return lines or ["Nothing could be read."]
