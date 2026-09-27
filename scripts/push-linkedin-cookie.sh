#!/usr/bin/env bash
#
# Refresh the LinkedIn li_at cookie on perihelion (where the app runs) from
# Chrome on this Mac. The value goes over SSH stdin straight into
# /srv/secrets/names-and-faces.env and is never printed.
#
# Usage: bash scripts/push-linkedin-cookie.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS=/srv/secrets/names-and-faces.env

line=$(bash "$SCRIPT_DIR/get-linkedin-cookie.sh")
value=${line#export LINKEDIN_LI_AT=\"}
value=${value%\"}
[ -n "$value" ] && [ "$value" != "$line" ] || { echo "Could not read the cookie from Chrome." >&2; exit 1; }

printf '%s' "$value" | ssh perihelion "python3 -c '
import sys
path, new = sys.argv[1], sys.stdin.read()
lines = [l for l in open(path).read().splitlines() if not l.startswith(\"LINKEDIN_LI_AT=\")]
lines.append(\"LINKEDIN_LI_AT=\" + new)
open(path, \"w\").write(\"\n\".join(lines) + \"\n\")
' $SECRETS && cd /srv/apps/names-and-faces && docker compose up -d --force-recreate >/dev/null 2>&1"
echo "LinkedIn cookie updated on perihelion and the app restarted." >&2
