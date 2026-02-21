#!/usr/bin/env bash
set -euo pipefail

LABEL="com.namesandfaces.server"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true

if [ -f "$PLIST_PATH" ]; then
    rm "$PLIST_PATH"
    echo "Removed $PLIST_PATH"
else
    echo "Plist not found at $PLIST_PATH (already removed?)"
fi

echo "Names & Faces server uninstalled. It will no longer start on login."
