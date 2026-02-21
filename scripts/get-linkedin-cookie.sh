#!/usr/bin/env bash
#
# Extract the LinkedIn li_at session cookie from Chrome.
#
# Chrome encrypts cookies on macOS using a key stored in the Keychain.
# This script uses a small Python helper to decrypt and extract the value.
#
# Usage:
#   eval $(bash scripts/get-linkedin-cookie.sh)
#   # LINKEDIN_LI_AT is now set in your shell
#
# Or to install it into the launchd service directly:
#   eval $(bash scripts/get-linkedin-cookie.sh)
#   bash scripts/install-launchd.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Chrome's cookie DB path
CHROME_COOKIE_DB="$HOME/Library/Application Support/Google/Chrome/Default/Cookies"

if [ ! -f "$CHROME_COOKIE_DB" ]; then
    # Try Profile 1 if Default doesn't exist
    CHROME_COOKIE_DB="$HOME/Library/Application Support/Google/Chrome/Profile 1/Cookies"
fi

if [ ! -f "$CHROME_COOKIE_DB" ]; then
    echo "# Could not find Chrome cookies database." >&2
    echo "# Manually set the cookie instead:" >&2
    echo "#   1. Open Chrome -> linkedin.com (make sure you're logged in)" >&2
    echo "#   2. Open DevTools (Cmd+Option+I) -> Application -> Cookies -> linkedin.com" >&2
    echo "#   3. Copy the 'li_at' cookie value" >&2
    echo "#   4. Run: export LINKEDIN_LI_AT=\"your-cookie-value\"" >&2
    exit 1
fi

cd "$REPO_DIR"
COOKIE_VALUE=$(uv run python -c "
import sqlite3, shutil, tempfile, os, sys

# Copy the DB since Chrome locks it
src = '$CHROME_COOKIE_DB'
tmp = tempfile.mktemp(suffix='.db')
shutil.copy2(src, tmp)

try:
    conn = sqlite3.connect(tmp)
    # Chrome 80+ uses encrypted_value; older versions use value
    rows = conn.execute(
        \"\"\"SELECT encrypted_value, value FROM cookies
           WHERE host_key LIKE '%linkedin.com'
           AND name = 'li_at'
           ORDER BY expires_utc DESC LIMIT 1\"\"\"
    ).fetchall()
    conn.close()

    if not rows:
        print('', end='')
        sys.exit(0)

    encrypted_value, plain_value = rows[0]

    # Try plain value first (older Chrome)
    if plain_value:
        print(plain_value, end='')
        sys.exit(0)

    # Decrypt Chrome cookie on macOS
    import subprocess
    raw_key = subprocess.check_output(
        ['security', 'find-generic-password', '-s', 'Chrome Safe Storage', '-w'],
        stderr=subprocess.DEVNULL
    )

    import hashlib
    key = hashlib.pbkdf2_hmac('sha1', raw_key.strip(), b'saltysalt', 1003, dklen=16)

    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    # Chrome prepends 'v10' to encrypted cookies on macOS
    if encrypted_value[:3] == b'v10':
        iv = b' ' * 16
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(encrypted_value[3:]) + decryptor.finalize()
        # Remove PKCS7 padding
        pad_len = decrypted[-1]
        decrypted = decrypted[:-pad_len]
        print(decrypted.decode('utf-8'), end='')
    else:
        print('', end='')
finally:
    os.unlink(tmp)
" 2>/dev/null) || true

if [ -z "$COOKIE_VALUE" ]; then
    echo "# Could not extract li_at cookie from Chrome." >&2
    echo "# You may need to install cryptography: uv add cryptography" >&2
    echo "# Or extract it manually:" >&2
    echo "#   1. Open Chrome -> linkedin.com (make sure you're logged in)" >&2
    echo "#   2. Open DevTools (Cmd+Option+I) -> Application -> Cookies -> linkedin.com" >&2
    echo "#   3. Copy the 'li_at' cookie value" >&2
    echo "#   4. Run: export LINKEDIN_LI_AT=\"your-cookie-value\"" >&2
    exit 1
fi

echo "export LINKEDIN_LI_AT=\"$COOKIE_VALUE\""
echo "# LinkedIn cookie extracted successfully. Run install-launchd.sh to apply." >&2
