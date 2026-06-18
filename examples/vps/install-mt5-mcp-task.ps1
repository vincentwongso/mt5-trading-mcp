<#
.SYNOPSIS
    Install (or remove) the `mt5-mcp-server` Windows scheduled task.

.DESCRIPTION
    Registers a scheduled task that auto-starts `mt5-mcp serve --transport http`
    after the configured user logs on. Pairs with a separate scheduled task
    that launches the MT5 terminal itself. Both must run in the user's
    interactive session - the MetaTrader5 Python library only talks to a
    terminal in the same Windows session, so this can't be a Session 0
    Windows service (NSSM-style).

    Re-running with the same parameters is safe: the task is unregistered
    first (`-Force`) and then re-created with the new settings.

.PARAMETER VenvPath
    Path to the venv directory that has `mt5-trading-mcp` installed. Defaults
    to `C:\projects\mt5-trading-mcp\.venv`.

.PARAMETER WorkingDirectory
    Working directory for the task. Defaults to `C:\projects\mt5-trading-mcp`.

.PARAMETER TaskName
    Scheduled-task name. Defaults to `mt5-mcp-server`.

.PARAMETER User
    The Windows account the task runs as. Defaults to the current user.
    Must be the same account MT5 logs in as via auto-logon.

.PARAMETER DelaySeconds
    How long to wait after logon before starting the MCP, so the MT5 terminal
    has time to come up first. Defaults to 60.

.PARAMETER DailyRestartAt
    Time of day (24h "HH:mm") to restart the MCP server once a day, as a safety
    net against slow memory growth in long-running HTTP deployments. Installs a
    companion task "<TaskName>-restart" that stops and restarts the server task.
    Defaults to "03:30". Pass -NoDailyRestart to skip it.

.PARAMETER NoDailyRestart
    Do not install the daily-restart companion task.

.PARAMETER Uninstall
    Remove the task (and its daily-restart companion) instead of installing it.

.EXAMPLE
    .\install-mt5-mcp-task.ps1

    Installs with the default paths.

.EXAMPLE
    .\install-mt5-mcp-task.ps1 -VenvPath D:\trading\.venv -WorkingDirectory D:\trading

    Installs with non-default paths.

.EXAMPLE
    .\install-mt5-mcp-task.ps1 -Uninstall

    Removes the task.
#>

[CmdletBinding()]
param(
    [string] $VenvPath          = "C:\projects\mt5-trading-mcp\.venv",
    [string] $WorkingDirectory  = "C:\projects\mt5-trading-mcp",
    [string] $TaskName          = "mt5-mcp-server",
    [string] $User              = $env:USERNAME,
    [int]    $DelaySeconds      = 60,
    [string] $DailyRestartAt    = "03:30",
    [switch] $NoDailyRestart,
    [switch] $Uninstall
)

$ErrorActionPreference = "Stop"

$restartTaskName = "$TaskName-restart"

if ($Uninstall) {
    foreach ($name in @($restartTaskName, $TaskName)) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "Removed scheduled task '$name'." -ForegroundColor Green
        } else {
            Write-Host "Scheduled task '$name' was not registered. Nothing to remove." -ForegroundColor Yellow
        }
    }
    return
}

$python = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python not found at '$python'. Activate or create the venv first, then `pip install mt5-trading-mcp`."
}
if (-not (Test-Path $WorkingDirectory)) {
    throw "Working directory '$WorkingDirectory' does not exist."
}

$action  = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "-m mt5_mcp serve --transport http" `
    -WorkingDirectory $WorkingDirectory

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$trigger.Delay = "PT${DelaySeconds}S"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal `
    -UserId $User -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Auto-start mt5-mcp HTTP server after $User logs on" `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName'." -ForegroundColor Green

# --- Daily-restart companion task ---------------------------------------
# Long-running HTTP deployments creep up in memory over a day (polling MCP
# clients). A once-a-day stop+start reclaims it. We use a separate task rather
# than a second trigger on the server task because Stop-then-Start guarantees
# the restart even when an instance is already running; a duplicate trigger
# would just be ignored while the server is up.
if (-not $NoDailyRestart) {
    # Validate a real 24h time (00-23:00-59), not just the HH:mm shape, so a
    # bogus value like "99:99" fails here with a clear message instead of
    # surfacing later as a confusing New-ScheduledTaskTrigger error.
    if ($DailyRestartAt -notmatch '^([01][0-9]|2[0-3]):[0-5][0-9]$') {
        throw "DailyRestartAt must be a 24h time 'HH:mm' (00:00-23:59), got '$DailyRestartAt'."
    }
    # powershell.exe -Command runs in the user's interactive session (same
    # principal as the server task), so the restarted server lands back in the
    # session MT5's terminal lives in. Escape any single quote in the task name
    # (PowerShell doubles it inside a single-quoted string) so a name with an
    # apostrophe can't break out of the quoting. Stop is best-effort - a not-
    # running task is a no-op, and SilentlyContinue keeps any edge case from
    # blocking the Start that follows.
    $escapedName = $TaskName.Replace("'", "''")
    $restartCmd = "Stop-ScheduledTask -TaskName '$escapedName' -ErrorAction SilentlyContinue; Start-Sleep -Seconds 5; Start-ScheduledTask -TaskName '$escapedName'"
    $restartAction = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$restartCmd`""

    $restartTrigger  = New-ScheduledTaskTrigger -Daily -At $DailyRestartAt
    $restartSettings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable
    $restartPrincipal = New-ScheduledTaskPrincipal `
        -UserId $User -LogonType Interactive -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $restartTaskName `
        -Action $restartAction -Trigger $restartTrigger -Settings $restartSettings -Principal $restartPrincipal `
        -Description "Restart $TaskName daily at $DailyRestartAt to reclaim memory" `
        -Force | Out-Null

    Write-Host "Registered scheduled task '$restartTaskName' (daily at $DailyRestartAt)." -ForegroundColor Green
}
Write-Host "  Command:           $python -m mt5_mcp serve --transport http"
Write-Host "  Working directory: $WorkingDirectory"
Write-Host "  Runs as user:      $User (interactive session)"
Write-Host "  Logon delay:       ${DelaySeconds}s"
if (-not $NoDailyRestart) {
    Write-Host "  Daily restart:     ${DailyRestartAt} (task '$restartTaskName')"
}
Write-Host ""
Write-Host "Verify without rebooting:" -ForegroundColor Cyan
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
Write-Host "  Get-ScheduledTaskInfo -TaskName $TaskName"
Write-Host "  curl http://localhost:8765/mcp"
Write-Host ""
Write-Host "Remove later:" -ForegroundColor Cyan
Write-Host "  .\install-mt5-mcp-task.ps1 -Uninstall"
