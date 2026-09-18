#!/usr/bin/env bash
set -euo pipefail

LABEL="com.namesandfaces.server"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if it exists (doesn't override existing env vars)
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    eval "$(grep -v '^\s*#' "$REPO_DIR/.env" | grep -v '^\s*$')"
    set +a
fi

PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
UV_PATH="$(command -v uv 2>/dev/null || echo "/opt/homebrew/bin/uv")"
PORT="${NAMES_AND_FACES_PORT:-5050}"
DATA_DIR="${NAMES_AND_FACES_DATA_DIR:-$HOME/.names-and-faces}"
DATA_DIR="${DATA_DIR/#\~/$HOME}"
# Logs live in ~/Library/Logs (not the data dir): launchd cannot reliably open
# stdout/stderr files inside iCloud Drive, which makes the agent fail to spawn
# with EX_CONFIG. Keeping logs local also avoids syncing them to iCloud.
LOG_DIR="$HOME/Library/Logs"
LOG_FILE="$LOG_DIR/names-and-faces.log"

if [ ! -f "$UV_PATH" ]; then
    echo "Error: uv not found at $UV_PATH"
    echo "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$LOG_DIR"

LINKEDIN_PLIST_ENTRY=""
if [ -n "${LINKEDIN_LI_AT:-}" ]; then
    LINKEDIN_PLIST_ENTRY="
        <key>LINKEDIN_LI_AT</key>
        <string>${LINKEDIN_LI_AT}</string>"
fi

ANTHROPIC_PLIST_ENTRY=""
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    ANTHROPIC_PLIST_ENTRY="
        <key>ANTHROPIC_API_KEY</key>
        <string>${ANTHROPIC_API_KEY}</string>"
fi

# Unload existing agent if present
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${UV_PATH}</string>
        <string>run</string>
        <string>python</string>
        <string>run.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NAMES_AND_FACES_PORT</key>
        <string>${PORT}</string>
        <key>NAMES_AND_FACES_DATA_DIR</key>
        <string>${DATA_DIR}</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>${LINKEDIN_PLIST_ENTRY}${ANTHROPIC_PLIST_ENTRY}
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_FILE}</string>
</dict>
</plist>
PLIST

launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo "Names & Faces server installed and started."
echo ""
echo "  URL:      http://localhost:${PORT}"
echo "  Data dir: ${DATA_DIR}"
echo "  Logs:     ${LOG_FILE}"
echo "  Plist:    ${PLIST_PATH}"

if command -v tailscale &>/dev/null && tailscale status &>/dev/null; then
    TS_HOSTNAME="$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" 2>/dev/null || true)"
    # Prefer HTTPS (needs "HTTPS Certificates" enabled in the Tailscale admin console); fall back to plain HTTP.
    if tailscale serve --yes --bg --https "${PORT}" "http://127.0.0.1:${PORT}" >/dev/null 2>&1; then
        TS_URL="https://${TS_HOSTNAME}:${PORT}"
    else
        tailscale serve --bg --http "${PORT}" "http://127.0.0.1:${PORT}" 2>/dev/null || true
        TS_URL="http://${TS_HOSTNAME}:${PORT}"
    fi
    if [ -n "$TS_HOSTNAME" ]; then
        echo "  Tailscale: ${TS_URL}"
    fi
fi

echo ""
echo "The server will start automatically on login."
echo "To uninstall: bash $(dirname "$0")/uninstall-launchd.sh"
