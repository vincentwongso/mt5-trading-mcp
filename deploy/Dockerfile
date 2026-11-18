# All-in-one headless mt5-trading-mcp image (Linux).
#
# Layers our headless-MCP bootstrap onto the gmag11 MetaTrader5 + KasmVNC base:
# 64-bit Wine-Python 3.11 + the official MetaTrader5 package + mt5-trading-mcp
# serving MCP over HTTP on :8765. The stock mt5linux RPyC bridge is dropped -
# Option 1: mt5-mcp runs in-process under Wine-Python (the same native code
# path it uses on Windows).
#
#   docker build -f deploy/Dockerfile -t mt5-trading-mcp:headless .
#   # or: docker compose -f deploy/docker-compose.yml up -d --build
# Pinned to a digest for reproducible builds (tag 2.3 == latest at pin time).
# Bump via Dependabot's docker ecosystem.
FROM gmag11/metatrader5_vnc:2.3@sha256:2fdff449cf70b74c242319828b6859592ab52dfb05690d9a989c75107dabf4c1

# socat bridges the container's network interface to the loopback-bound MCP
# server, so Docker port-forwarding reaches it without relaxing mt5-mcp's
# loopback-only HTTP bind (a deliberate project invariant).
#
# The base leaves the WineHQ apt source configured but DELETES its signing key,
# so a derived `apt-get update` fails GPG verification on that repo. We only
# need socat and procps (pgrep/pkill for the terminal supervisor; Debian main) -
# drop the unsigned WineHQ source first. Wine is already installed in the
# base, so nothing here needs that repo.
RUN rm -f /etc/apt/sources.list.d/winehq*.sources /etc/apt/sources.list.d/winehq*.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends socat procps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Replace the stock bootstrap (3.9 32-bit Python + the broken mt5linux `-w`
# launcher) with our headless-MCP version. The KasmVNC desktop autostart
# already points at /Metatrader/start.sh, so this swaps the behaviour cleanly
# while keeping the base's MT5-install + terminal-launch + VNC machinery.
COPY deploy/start.sh /Metatrader/start.sh
RUN chmod +x /Metatrader/start.sh

# Screenshot EA, light chart template and startup ini; start.sh installs them
# into the terminal data folder on every boot.
COPY mql5/AgentScreenshot.ex5 deploy/agent_light.tpl deploy/startup.ini /opt/mt5-mcp/

# Release builds pin the PyPI version start.sh installs (empty = latest).
ARG MT5_MCP_VERSION=
ENV MT5_MCP_VERSION=${MT5_MCP_VERSION}

# KasmVNC web UI (one-time login) is inherited as 3000; add the MCP HTTP port.
EXPOSE 8765
