<#
.SYNOPSIS
    One-shot Windows VPS setup for mt5-trading-mcp: install/upgrade the package,
    register the auto-start + daily-restart scheduled tasks, make the MT5
    terminal launch at logon, optionally enable auto-logon, then verify.

.DESCRIPTION
    Wraps the individual steps so you can drop this on the box and run it once
    (from an ELEVATED PowerShell). It is safe to re-run - every step is
    idempotent.

    What it does:
      1. (unless -SkipInstall) Creates the venv if missing and installs/upgrades
         `mt5-trading-mcp` into it.
      2. Calls install-mt5-mcp-task.ps1 (must sit next to this file) to register:
           - `mt5-mcp-server`         - starts `serve --transport http` at logon
           - `mt5-mcp-server-restart` - daily stop+start to reclaim memory
      3. (unless -NoTerminalShortcut) Drops a Startup-folder shortcut so the MT5
         terminal launches at logon, before the (delayed) server connects.
      4. (only with -EnableAutoLogon) Configures Windows auto-logon so a reboot
         logs the user in automatically and the logon-triggered task fires.
      5. Verifies: starts the task, reports its result, and checks the port.

    WHY logon, not startup: the MetaTrader5 Python library only talks to a
    terminal in the SAME interactive desktop session, so the server cannot run
    as a Session 0 service / "At system startup" task. It must run after a user
    logs on - hence auto-logon is what makes it survive a reboot unattended.

.PARAMETER VenvPath
    Venv directory that has (or will get) `mt5-trading-mcp`. Default
    `C:\projects\mt5-trading-mcp\.venv`.

.PARAMETER WorkingDirectory
    Working directory for the server task. Created if missing. Default
    `C:\projects\mt5-trading-mcp`.

.PARAMETER TerminalPath
    Path to `terminal64.exe` for the Startup shortcut. Default the standard
    install location.

.PARAMETER Port
    Port the server listens on (for the verify step). Default 8765.

.PARAMETER Version
    Pin a specific `mt5-trading-mcp` version (e.g. `1.4.0`). Default: latest.

.PARAMETER DailyRestartAt
    24h "HH:mm" for the daily restart. Default `03:30`. Use -NoDailyRestart to
    skip that task.

.PARAMETER DelaySeconds
    Seconds to wait after logon before starting the server, so MT5 comes up
    first. Default 60.

.PARAMETER EnableAutoLogon
    Configure Windows auto-logon for -User. Prompts for the password securely.
    NOTE: the registry method stores the password in plaintext under HKLM
    Winlogon (readable by administrators). For encrypted storage use Sysinternals
    Autologon instead (https://learn.microsoft.com/sysinternals/downloads/autologon)
    and omit this switch.

.PARAMETER SkipInstall
    Don't touch pip/venv - only (re)register tasks, shortcut, etc.

.PARAMETER NoTerminalShortcut
    Don't create the MT5 Startup shortcut (e.g. MT5 already auto-starts).

.PARAMETER NoDailyRestart
    Don't register the daily-restart task.

.PARAMETER TaskName
    Server task name. Default `mt5-mcp-server`.

.PARAMETER User
    Account the tasks run as / auto-logon user. Default the current user.

.PARAMETER Uninstall
    Remove the scheduled tasks and the Startup shortcut. Does NOT disable
    auto-logon (do that yourself if you set it up).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup-vps.ps1

    Default paths, latest version, no auto-logon (prints manual instructions).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup-vps.ps1 -EnableAutoLogon -DailyRestartAt 04:00

    Full unattended setup including auto-logon, daily restart at 4am.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup-vps.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [string] $VenvPath          = "C:\projects\mt5-trading-mcp\.venv",
    [string] $WorkingDirectory  = "C:\projects\mt5-trading-mcp",
    [string] $TerminalPath      = "C:\Program Files\MetaTrader 5\terminal64.exe",
    [int]    $Port              = 8765,
    [string] $Version           = "",
    [string] $DailyRestartAt    = "03:30",
    [int]    $DelaySeconds      = 60,
    [string] $TaskName          = "mt5-mcp-server",
    [string] $User              = $env:USERNAME,
    [switch] $EnableAutoLogon,
    [switch] $SkipInstall,
    [switch] $NoTerminalShortcut,
    [switch] $NoDailyRestart,
    [switch] $Uninstall
)

$ErrorActionPreference = "Stop"

function Write-Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltinRole]::Administrator)
}

$installScript = Join-Path $PSScriptRoot "install-mt5-mcp-task.ps1"
if (-not (Test-Path $installScript)) {
    throw "install-mt5-mcp-task.ps1 not found next to this script (looked in '$PSScriptRoot')."
}

# Registering/removing tasks for an arbitrary -User and writing HKLM Winlogon
# both need elevation, so require it for every path.
if (-not (Test-Admin)) {
    throw "Run this from an ELEVATED PowerShell (Run as administrator)."
}

# --- Uninstall path ------------------------------------------------------
if ($Uninstall) {
    & $installScript -TaskName $TaskName -User $User -Uninstall
    $startup = [Environment]::GetFolderPath('Startup')
    $lnk = Join-Path $startup "MT5.lnk"
    if (Test-Path $lnk) {
        Remove-Item $lnk -Force
        Write-Host "Removed Startup shortcut '$lnk'." -ForegroundColor Green
    }
    Write-Host "`nDone. (Auto-logon, if you enabled it, was left untouched.)" -ForegroundColor Green
    return
}

$python = Join-Path $VenvPath "Scripts\python.exe"

# --- 1. Install / upgrade the package -----------------------------------
if ($SkipInstall) {
    Write-Step 1 "Skipping install (-SkipInstall)."
} else {
    Write-Step 1 "Installing / upgrading mt5-trading-mcp into the venv"
    if (-not (Test-Path $python)) {
        Write-Host "    Venv not found at '$VenvPath' - creating it." -ForegroundColor Yellow
        $base = $null
        foreach ($cand in @("py", "python")) {
            if (Get-Command $cand -ErrorAction SilentlyContinue) { $base = $cand; break }
        }
        if (-not $base) {
            throw "No base Python found on PATH (tried 'py' and 'python'). Install Python first."
        }
        $parent = Split-Path $VenvPath -Parent
        if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        if ($base -eq "py") { & py -3 -m venv $VenvPath } else { & python -m venv $VenvPath }
        if (-not (Test-Path $python)) { throw "Venv creation failed; '$python' still missing." }
    }
    $spec = if ($Version) { "mt5-trading-mcp==$Version" } else { "mt5-trading-mcp" }
    # pip is an external command: a non-zero exit does NOT stop the script, so
    # check $LASTEXITCODE and fail loudly - otherwise a broken install would
    # silently proceed to register tasks against a non-working env.
    & $python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip self-upgrade failed (exit $LASTEXITCODE)." }
    & $python -m pip install --upgrade $spec
    if ($LASTEXITCODE -ne 0) { throw "Installing '$spec' failed (exit $LASTEXITCODE)." }
    $installed = (& $python -m pip show mt5-trading-mcp | Select-String '^Version:').ToString()
    Write-Host "    $installed" -ForegroundColor Green
}

if (-not (Test-Path $python)) {
    throw "Python not found at '$python'. Install the package first or drop -SkipInstall."
}
if (-not (Test-Path $WorkingDirectory)) {
    New-Item -ItemType Directory -Force -Path $WorkingDirectory | Out-Null
}

# --- 2. Register the scheduled tasks ------------------------------------
Write-Step 2 "Registering scheduled tasks (auto-start at logon + daily restart)"
$taskArgs = @{
    VenvPath         = $VenvPath
    WorkingDirectory = $WorkingDirectory
    TaskName         = $TaskName
    User             = $User
    DelaySeconds     = $DelaySeconds
    DailyRestartAt   = $DailyRestartAt
}
if ($NoDailyRestart) { $taskArgs["NoDailyRestart"] = $true }
& $installScript @taskArgs

# --- 3. MT5 terminal Startup shortcut -----------------------------------
if ($NoTerminalShortcut) {
    Write-Step 3 "Skipping MT5 Startup shortcut (-NoTerminalShortcut)."
} else {
    Write-Step 3 "Creating MT5 terminal Startup shortcut"
    if (-not (Test-Path $TerminalPath)) {
        Write-Host "    WARNING: terminal not found at '$TerminalPath'. Shortcut created anyway; fix the path if MT5 lives elsewhere." -ForegroundColor Yellow
    }
    $startup = [Environment]::GetFolderPath('Startup')
    $lnk = Join-Path $startup "MT5.lnk"
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = $TerminalPath
    $sc.WorkingDirectory = Split-Path $TerminalPath -Parent
    $sc.Save()
    Write-Host "    Shortcut: $lnk -> $TerminalPath" -ForegroundColor Green
}

# --- 4. Auto-logon (opt-in) ---------------------------------------------
if ($EnableAutoLogon) {
    Write-Step 4 "Configuring Windows auto-logon for '$User'"
    Write-Host "    SECURITY: this stores the password in plaintext under HKLM Winlogon" -ForegroundColor Yellow
    Write-Host "    (admin-readable). For encrypted storage use Sysinternals Autologon instead." -ForegroundColor Yellow
    $secure = Read-Host "    Enter the Windows password for '$User'" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
    # New-ItemProperty -Force creates the value if absent and overwrites it
    # otherwise - robust whether or not the key already exists (DefaultPassword
    # in particular is often missing on a fresh box).
    New-ItemProperty $winlogon -Name AutoAdminLogon    -Value '1'             -PropertyType String -Force | Out-Null
    New-ItemProperty $winlogon -Name DefaultUserName   -Value $User           -PropertyType String -Force | Out-Null
    New-ItemProperty $winlogon -Name DefaultDomainName -Value $env:USERDOMAIN -PropertyType String -Force | Out-Null
    New-ItemProperty $winlogon -Name DefaultPassword   -Value $plain          -PropertyType String -Force | Out-Null
    # AutoLogonCount, if present, makes auto-logon expire after N logons - clear it.
    Remove-ItemProperty $winlogon -Name AutoLogonCount -ErrorAction SilentlyContinue
    $plain = $null
    Write-Host "    Auto-logon enabled for $env:USERDOMAIN\$User." -ForegroundColor Green
} else {
    Write-Step 4 "Auto-logon NOT configured (-EnableAutoLogon to automate it)."
    Write-Host "    To survive an unattended reboot, enable auto-logon so '$User' logs in" -ForegroundColor Yellow
    Write-Host "    automatically. Easiest secure option: Sysinternals Autologon" -ForegroundColor Yellow
    Write-Host "    https://learn.microsoft.com/sysinternals/downloads/autologon" -ForegroundColor Yellow
}

# --- 5. Verify -----------------------------------------------------------
Write-Step 5 "Verifying"
# Best-effort: on a rerun the task may already be running; don't let that abort
# the verify step.
Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds ([Math]::Max($DelaySeconds, 5) + 5)
# A healthy long-running `serve` shows State=Running (its LastTaskResult would be
# 267009 "task is currently running", not 0), so State + the port check are the
# real signals here.
$state = (Get-ScheduledTask -TaskName $TaskName).State
Write-Host "    Task '$TaskName' state: $state (Running = OK)"
$listening = Test-NetConnection -ComputerName localhost -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
if ($listening) {
    Write-Host "    Server is listening on localhost:$Port." -ForegroundColor Green
} else {
    Write-Host "    Port $Port not responding yet. Give MT5 a moment to log in, then check:" -ForegroundColor Yellow
    Write-Host "      Get-ScheduledTaskInfo -TaskName $TaskName" -ForegroundColor Yellow
    Write-Host "      Test-NetConnection localhost -Port $Port" -ForegroundColor Yellow
}

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Reboot to confirm the full chain (auto-logon -> MT5 -> mt5-mcp server)." -ForegroundColor Cyan
if (-not $EnableAutoLogon) {
    Write-Host "Remember: without auto-logon the server won't start on an unattended reboot." -ForegroundColor Yellow
}
Write-Host "If localhost:$Port is reachable by anything beyond a single trusted user, set" -ForegroundColor Cyan
Write-Host "transport.http.auth_token in %APPDATA%\mt5-mcp\config.toml." -ForegroundColor Cyan
