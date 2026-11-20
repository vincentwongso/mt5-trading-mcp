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
#   3. Install screenshot assets + start the terminal supervisor - the EA,
#                           light template and startup.ini go in on every
#                           boot. Every 10s the supervisor launches the
#                           terminal with startup.ini if none is running, and
#                           replaces one started without it (mt5lib's bare
#                           `/portable` relaunch, which has no EA). A login
#                           (programmatic OR a one-time VNC login) can then
#                           attach.
#   4. 64-bit Wine-Python 3.11   (NEW - stock gmag11 ships 3.9 32-bit)
#   5. mt5-trading-mcp + numpy<2 (NEW - drops mt5linux entirely); reinstalled
#                           when the pin (MT5_MCP_VERSION or the image's) differs
#   6. config.toml (first boot only) + socat bridge +
#      `mt5_mcp serve --transport http`  (NEW)
#                           (server + bridge skipped when MT5_MCP_SERVE=0)
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

term_dir='/config/.wine/drive_c/Program Files/MetaTrader 5'
mt5file="$term_dir/terminal64.exe"
cfg='/config/.wine/drive_c/users/abc/AppData/Roaming/mt5-mcp/config.toml'
assets='/opt/mt5-mcp'
export WINEPREFIX='/config/.wine'
export WINEDEBUG='-all'
wine_executable="wine"
python_win='C:\Python311\python.exe'
python_unix='/config/.wine/drive_c/Python311/python.exe'
MT5_CMD_OPTIONS="${MT5_CMD_OPTIONS:-}"
# Wine shows a running terminal as `C:\Program Files\...\terminal64.exe <args>`.
# The ^C: anchor keeps pgrep/pkill off this script's own command line.
term_pat='^C:.*terminal64\.exe'
term_pid=""

mono_url="https://dl.winehq.org/wine/wine-mono/10.3.0/wine-mono-10.3.0-x86.msi"
python_url="https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
mt5setup_url="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"

# mt5-mcp binds loopback only (a hard project invariant). It serves on this
# port inside the container; socat bridges the container's network interface
# to it so Docker `-p 127.0.0.1:8765:8765` forwarding can reach it.
#
# The internal port is FIXED at 8765: `mt5_mcp serve` always binds the config
# default (8765) - the config.toml this script seeds sets no port - and the
# compose file maps the container's 8765. Remapping the *host* port is Docker's
# job (`-p 127.0.0.1:<host>:8765` / the compose `MCP_PORT` var), so this must
# stay 8765 or socat would forward to a port nothing is listening on.
mcp_host="127.0.0.1"
mcp_port="8765"
# Effective pin: a runtime MT5_MCP_VERSION wins, else the version baked at image
# build (compose cannot pass a bare override through without unsetting the ENV).
pin="${MT5_MCP_VERSION:-${MT5_MCP_IMAGE_VERSION:-}}"
mt5_mcp_spec="mt5-trading-mcp${pin:+==${pin}}"
install_retry_secs=60

log() { echo "[mt5-mcp-boot] $*"; }

# Sets $installed; returns 0 when mt5-trading-mcp must be (re)installed.
mt5_mcp_needs_install() {
    installed="$($wine_executable "$python_win" -m pip show mt5-trading-mcp 2>/dev/null | tr -d '\r' | sed -n 's/^Version: //p')"
    [ -z "$installed" ] || { [ -n "$pin" ] && [ "$installed" != "$pin" ]; }
}

# Keeps an already-installed version serving when the pinned install fails.
install_mt5_mcp() {
    log "[5/6] Installing ${mt5_mcp_spec} + numpy<2 into Wine-Python..."
    [ "${1:-}" = retry ] || $wine_executable "$python_win" -m pip install --upgrade --no-cache-dir pip
    if ! $wine_executable "$python_win" -m pip install --no-cache-dir "$mt5_mcp_spec" "numpy<2" \
        && [ -n "$installed" ]; then
        log "WARNING: could not install ${mt5_mcp_spec}; keeping ${installed}"
    fi
}

# Atomic: a partial config.toml would count as "present" on the next boot.
write_cfg() {
    local tmp
    tmp="$(dirname "$cfg")/.config.toml.$$"
    if (
        umask 077
        mkdir -p "$(dirname "$cfg")" || exit 1
        {
            printf '[screenshot]\ntemplate = "agent_light.tpl"\n'
            # Explicit, so the server never attaches to a backtest's tester terminal.
            printf '\n[mt5]\nterminal_path = %s\n' "'C:\Program Files\MetaTrader 5\terminal64.exe'"
            if [ -n "${MT5_MCP_AUTH_TOKEN:-}" ]; then
                printf '\n[transport.http]\nauth_token = "%s"\n' "$MT5_MCP_AUTH_TOKEN"
            fi
        } > "$tmp"
    ) && mv "$tmp" "$cfg"; then
        return 0
    fi
    rm -f "$tmp"
    return 1
}

require() { command -v "$1" >/dev/null 2>&1 || { log "FATAL: $1 not installed"; exit 1; }; }
require curl
require "$wine_executable"
require socat
require pgrep

launch_terminal() {
    # shellcheck disable=SC2086
    $wine_executable "$mt5file" "/config:C:\\Program Files\\MetaTrader 5\\startup.ini" $MT5_CMD_OPTIONS &
    term_pid=$!
}

# One supervisor tick. If the terminal dies, mt5lib's initialize() relaunches
# it as a bare `/portable` instance with no EA, so replace any instance that
# was not started with our ini.
check_terminal() {
    local procs
    procs="$(pgrep -af "$term_pat")"
    if [ -z "$procs" ]; then
        # Our launch is still starting (Wine has not renamed it to C:\... yet).
        kill -0 "$term_pid" 2>/dev/null && return
        log "terminal not running; launching it with startup.ini"
        launch_terminal
    elif ! grep -q '/config:' <<<"$procs"; then
        log "terminal running without startup.ini (no EA); restarting it with startup.ini"
        pkill -f "$term_pat"
        launch_terminal
    fi
}

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
    log "[3/6] Installing screenshot EA, light template and startup.ini..."
    mkdir -p "$term_dir/MQL5/Experts" "$term_dir/MQL5/Profiles/Templates"
    cp "$assets/AgentScreenshot.ex5" "$term_dir/MQL5/Experts/" \
        || log "WARNING: could not copy AgentScreenshot.ex5"
    cp "$assets/agent_light.tpl" "$term_dir/MQL5/Profiles/Templates/" \
        || log "WARNING: could not copy agent_light.tpl"
    # default.tpl is left alone: it is the user's own chart template.
    # The symbol goes through sed, so reject characters sed would misread.
    ea_symbol="${MT5_EA_SYMBOL:-BTCUSD}"
    if ! [[ "$ea_symbol" =~ ^[A-Za-z0-9._#+-]+$ ]]; then
        log "WARNING: MT5_EA_SYMBOL '${ea_symbol}' has invalid characters; using BTCUSD"
        ea_symbol=BTCUSD
    fi
    if sed "s/@EA_SYMBOL@/${ea_symbol}/" "$assets/startup.ini" > "$term_dir/startup.ini.tmp"; then
        mv "$term_dir/startup.ini.tmp" "$term_dir/startup.ini"
    else
        log "WARNING: could not write startup.ini"
    fi
    # Older images pinned it read-only; LiveUpdate must be able to replace it.
    chmod u+w "$mt5file"
    log "terminal64.exe sha256 $(sha256sum "$mt5file" | cut -c1-8)"
    log "[3/6] Starting the MetaTrader 5 terminal supervisor..."
    while true; do
        check_terminal
        sleep 10
    done &
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
if mt5_mcp_needs_install; then
    install_mt5_mcp
else
    log "[5/6] mt5-trading-mcp ${installed} already installed."
fi

# --- 6. config.toml + socat bridge + serve ------------------------------
# Seeded once; never overwritten, so user edits survive. umask 077 keeps the
# optional auth token private. The token is only ever printf'd, never logged.
# An unescaped token would break the TOML and crash-loop the server, so
# reject it up front (never fall back to unauthenticated).
token_ok=1
if [ -n "${MT5_MCP_AUTH_TOKEN:-}" ] && ! [[ "$MT5_MCP_AUTH_TOKEN" =~ ^[A-Za-z0-9._~+/=-]+$ ]]; then
    log "FATAL: MT5_MCP_AUTH_TOKEN contains characters outside [A-Za-z0-9._~+/=-]; refusing to start mt5-mcp"
    token_ok=0
fi
if [ "$token_ok" = 1 ] && [ ! -e "$cfg" ]; then
    log "[6/6] Writing initial config.toml."
    if ! write_cfg; then
        if [ -n "${MT5_MCP_AUTH_TOKEN:-}" ]; then
            log "FATAL: could not write config.toml; refusing to start mt5-mcp without the requested auth token"
            token_ok=0
        else
            log "WARNING: could not write config.toml; mt5-mcp will run on defaults"
        fi
    fi
elif [ -e "$cfg" ]; then
    log "[6/6] config.toml present; leaving it unchanged"
    [ -n "${MT5_MCP_AUTH_TOKEN:-}" ] && log "WARNING: MT5_MCP_AUTH_TOKEN ignored because config.toml is present"
fi

# MT5_MCP_SERVE=0 (the backtest container): no server, no bridge. The CLI is
# all it needs, and an unauthenticated server there could trade the account.
serve=1
[ "${MT5_MCP_SERVE:-1}" = 0 ] && serve=0

if [ "$token_ok" = 1 ] && [ "$serve" = 1 ]; then
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
    last_install=$SECONDS
    while true; do
        # The image can ship before its pinned version reaches PyPI; keep retrying.
        if [ $((SECONDS - last_install)) -ge "$install_retry_secs" ] && mt5_mcp_needs_install; then
            last_install=$SECONDS
            install_mt5_mcp retry
        fi
        $wine_executable "$python_win" -m mt5_mcp serve --transport http
        log "mt5-mcp serve exited (rc=$?); restarting in 5s..."
        sleep 5
    done &
fi

if [ "$token_ok" = 1 ] && [ "$serve" = 0 ]; then
    # The serve loop is what retries a failed or outdated install; without it the
    # CLI (`docker exec ... mt5-mcp`) would stay missing until a restart.
    while mt5_mcp_needs_install; do
        sleep "$install_retry_secs"
        install_mt5_mcp retry
    done &
fi

# Match gmag11's pattern: the autostart script returns, leaving the terminal
# supervisor, socat, and the serve supervisor running under the desktop session.
if [ "$serve" = 0 ]; then
    log "Bootstrap complete; terminal running, mt5-mcp server off (MT5_MCP_SERVE=0); CLI via mt5-mcp."
elif [ "$token_ok" = 1 ]; then
    log "Bootstrap complete; terminal + mt5-mcp running. VNC web UI for one-time login."
else
    log "Bootstrap complete; terminal running, mt5-mcp NOT started (invalid MT5_MCP_AUTH_TOKEN)."
fi
