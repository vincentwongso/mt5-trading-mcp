#!/bin/bash
#
# All-in-one headless mt5-mcp bootstrap (Option 1 - mt5-mcp runs in-process
# under 64-bit Wine-Python, importing the official MetaTrader5 package; no
# third-party bridge). Replaces the stock gmag11 start.sh.
#
# Runs as the KasmVNC desktop autostart (user `abc`, HOME=/config, DISPLAY=:1).
# Everything heavy installs into the /config VOLUME on first boot (so it
# persists across restarts), guarded by existence checks - exactly the gmag11
# model. On later boots this is fast.
#
# Flow:
#   1. Wine-Mono            (gmag11)
#   2. MetaTrader 5         (gmag11)
#   3. Launch the terminal  (gmag11) - needed so a login (programmatic OR a
#                           one-time VNC login) can attach.
#   4. 64-bit Wine-Python 3.11   (NEW - stock gmag11 ships 3.9 32-bit)
#   5. mt5-trading-mcp + numpy<2 (NEW - drops mt5linux entirely)
#   6. socat bridge + `mt5_mcp serve --transport http`  (NEW)
#
# Credentials (MT5_LOGIN / MT5_PASSWORD / MT5_SERVER) are read by mt5-mcp from
# the environment (see config.py / server.py). Two ways the terminal ends up
# logged in:
#   * Programmatic: creds present -> mt5-mcp calls initialize(login=,password=,
#     server=). Fully headless if the broker/terminal allow it.
#   * One-time VNC login: open the KasmVNC web UI once, log the terminal in;
#     the session persists in /config. mt5-mcp's connect retry loop then
#     attaches on its next attempt.
# The password is never written to disk or logged by this script.

set -u

mt5file='/config/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe'
export WINEPREFIX='/config/.wine'
export WINEDEBUG='-all'
wine_executable="wine"
python_win='C:\Python311\python.exe'
python_unix='/config/.wine/drive_c/Python311/python.exe'
MT5_CMD_OPTIONS="${MT5_CMD_OPTIONS:-}"

mono_url="https://dl.winehq.org/wine/wine-mono/10.3.0/wine-mono-10.3.0-x86.msi"
python_url="https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
mt5setup_url="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"

# mt5-mcp binds loopback only (a hard project invariant). It serves on this
# port inside the container; socat bridges the container's network interface
# to it so Docker `-p 127.0.0.1:8765:8765` forwarding can reach it.
#
# The internal port is FIXED at 8765: `mt5_mcp serve` always binds the config
# default (8765) - this script writes no config and passes no --port - and the
# compose file maps the container's 8765. Remapping the *host* port is Docker's
# job (`-p 127.0.0.1:<host>:8765` / the compose `MCP_PORT` var), so this must
# stay 8765 or socat would forward to a port nothing is listening on.
mcp_host="127.0.0.1"
mcp_port="8765"
# Optionally pin the published mt5-trading-mcp version (else latest from PyPI).
mt5_mcp_spec="mt5-trading-mcp${MT5_MCP_VERSION:+==${MT5_MCP_VERSION}}"

log() { echo "[mt5-mcp-boot] $*"; }

require() { command -v "$1" >/dev/null 2>&1 || { log "FATAL: $1 not installed"; exit 1; }; }
require curl
require "$wine_executable"
require socat

# --- 1. Wine-Mono --------------------------------------------------------
if [ ! -e "/config/.wine/drive_c/windows/mono" ]; then
    log "[1/6] Installing Wine-Mono..."
    curl -L -o /config/.wine/drive_c/mono.msi "$mono_url"
    WINEDLLOVERRIDES=mscoree=d $wine_executable msiexec /i /config/.wine/drive_c/mono.msi /qn
    rm -f /config/.wine/drive_c/mono.msi
else
    log "[1/6] Wine-Mono already installed."
fi

# --- 2. MetaTrader 5 -----------------------------------------------------
if [ ! -e "$mt5file" ]; then
    log "[2/6] Installing MetaTrader 5 (this can take a few minutes)..."
    $wine_executable reg add "HKEY_CURRENT_USER\\Software\\Wine" /v Version /t REG_SZ /d "win10" /f
    curl -L -o /config/.wine/drive_c/mt5setup.exe "$mt5setup_url"
    $wine_executable "/config/.wine/drive_c/mt5setup.exe" "/auto" &
    wait
    rm -f /config/.wine/drive_c/mt5setup.exe
else
    log "[2/6] MetaTrader 5 already installed."
fi

# --- 3. Launch the terminal ---------------------------------------------
if [ -e "$mt5file" ]; then
    log "[3/6] Launching MetaTrader 5 terminal..."
    # shellcheck disable=SC2086
    $wine_executable "$mt5file" $MT5_CMD_OPTIONS &
else
    log "[3/6] WARNING: terminal64.exe missing; MT5 install may have failed."
fi

# --- 4. 64-bit Wine-Python 3.11 -----------------------------------------
if [ ! -e "$python_unix" ]; then
    log "[4/6] Installing 64-bit Python 3.11 under Wine..."
    curl -L "$python_url" -o /tmp/python-installer.exe
    $wine_executable /tmp/python-installer.exe /quiet InstallAllUsers=1 \
        TargetDir='C:\Python311' PrependPath=1 \
        Include_launcher=0 Include_test=0 Include_doc=0
    rm -f /tmp/python-installer.exe
else
    log "[4/6] Wine-Python 3.11 already installed."
fi

# --- 5. mt5-trading-mcp + numpy<2 ---------------------------------------
# The official MetaTrader5 package rides in as a dependency (its environment
# marker is platform_system=='Windows', which Wine-Python satisfies). numpy
# MUST stay <2 - numpy 2.x crashes the MetaTrader5 import under Wine.
if ! $wine_executable "$python_win" -m pip show mt5-trading-mcp >/dev/null 2>&1; then
    log "[5/6] Installing ${mt5_mcp_spec} + numpy<2 into Wine-Python..."
    $wine_executable "$python_win" -m pip install --upgrade --no-cache-dir pip
    $wine_executable "$python_win" -m pip install --no-cache-dir "$mt5_mcp_spec" "numpy<2"
else
    log "[5/6] mt5-trading-mcp already installed."
fi

# --- 6. socat bridge + serve --------------------------------------------
container_ip="$(hostname -i 2>/dev/null | awk '{print $1}')"
if [ -n "$container_ip" ] && [ "$container_ip" != "$mcp_host" ]; then
    log "[6/6] Bridging ${container_ip}:${mcp_port} -> ${mcp_host}:${mcp_port} (socat)"
    socat "TCP-LISTEN:${mcp_port},fork,reuseaddr,bind=${container_ip}" \
          "TCP:${mcp_host}:${mcp_port}" &
else
    log "[6/6] No distinct container IP found; skipping socat bridge."
fi

log "[6/6] Starting mt5-mcp HTTP server on ${mcp_host}:${mcp_port} (Wine-Python)."
# Keep the server alive across crashes / mid-boot terminal hiccups. Each
# relaunch gets a fresh connect-retry window, so a one-time VNC login performed
# after boot is picked up on the next attempt.
while true; do
    $wine_executable "$python_win" -m mt5_mcp serve --transport http
    log "mt5-mcp serve exited (rc=$?); restarting in 5s..."
    sleep 5
done &

# Match gmag11's pattern: the autostart script returns, leaving the terminal,
# socat, and the serve supervisor running under the desktop session.
log "Bootstrap complete; terminal + mt5-mcp running. VNC web UI for one-time login."
