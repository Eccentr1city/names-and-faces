#!/usr/bin/env bash
set -euo pipefail

LABEL="com.namesandfaces.server"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UV_PATH="$(command -v uv 2>/dev/null || echo "/opt/homebrew/bin/uv")"
PORT="${NAMES_AND_FACES_PORT:-5050}"
DATA_DIR="${NAMES_AND_FACES_DATA_DIR:-$HOME/.names-and-faces}"
LOG_DIR="$DATA_DIR/logs"

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

OPENAI_PLIST_ENTRY=""
if [ -n "${OPENAI_API_KEY:-}" ]; then
    OPENAI_PLIST_ENTRY="
        <key>OPENAI_API_KEY</key>
        <string>${OPENAI_API_KEY}</string>"
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
        <key>NAMES_AND_FACES_DATA_DIR</key>
        <string>${DATA_DIR}</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>${LINKEDIN_PLIST_ENTRY}${OPENAI_PLIST_ENTRY}
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/stderr.log</string>
</dict>
</plist>
PLIST

launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo "Names & Faces server installed and started."
echo ""
echo "  URL:      http://localhost:${PORT}"
echo "  Data dir: ${DATA_DIR}"
echo "  Logs:     ${LOG_DIR}"
echo "  Plist:    ${PLIST_PATH}"
echo ""
echo "The server will start automatically on login."
echo "To uninstall: bash $(dirname "$0")/uninstall-launchd.sh"
