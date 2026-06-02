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

.PARAMETER Uninstall
    Remove the task instead of installing it.

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
    [switch] $Uninstall
)

$ErrorActionPreference = "Stop"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Green
    } else {
        Write-Host "Scheduled task '$TaskName' was not registered. Nothing to remove." -ForegroundColor Yellow
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
Write-Host "  Command:           $python -m mt5_mcp serve --transport http"
Write-Host "  Working directory: $WorkingDirectory"
Write-Host "  Runs as user:      $User (interactive session)"
Write-Host "  Logon delay:       ${DelaySeconds}s"
Write-Host ""
Write-Host "Verify without rebooting:" -ForegroundColor Cyan
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
Write-Host "  Get-ScheduledTaskInfo -TaskName $TaskName"
Write-Host "  curl http://localhost:8765/mcp"
Write-Host ""
Write-Host "Remove later:" -ForegroundColor Cyan
Write-Host "  .\install-mt5-mcp-task.ps1 -Uninstall"
