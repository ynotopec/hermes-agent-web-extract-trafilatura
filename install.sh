#!/bin/bash
set -euo pipefail

echo "=== Trafilatura-Local Setup ==="
echo "  - Updates the checkout and installs Python dependencies"
echo "  - Configures and (re)starts the systemd --user service"

# Overridable: TRAFILATURA_DIR (checkout path), TRAFILATURA_PORT, PYTHON.
DIR="${TRAFILATURA_DIR:-$HOME/projects/trafilatura-local}"
VENV="$DIR/venv"
PORT="${TRAFILATURA_PORT:-8990}"
PYTHON="${PYTHON:-python3}"

# 0. The service needs CPython >= 3.10.
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Python >= 3.10 required; '$PYTHON' is $("$PYTHON" -V 2>&1). Set PYTHON=/path/to/python3." >&2
    exit 1
fi
WANT_PY="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

# 1. Clone, or fast-forward an existing checkout.
if [ ! -d "$DIR/.git" ]; then
    echo "Cloning repo..."
    mkdir -p "$(dirname "$DIR")"
    git clone https://github.com/ynotopec/hermes-agent-web-extract-trafilatura "$DIR"
else
    echo "Updating checkout..."
    git -C "$DIR" fetch --quiet origin
    git -C "$DIR" merge --ff-only origin/main \
        || echo "  ⚠ checkout has local changes or diverges from origin/main — left as-is"
fi

# 2. Virtualenv — recreated when missing/broken or built on a different Python.
if [ -x "$VENV/bin/python" ]; then
    HAVE_PY="$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if [ "$HAVE_PY" != "$WANT_PY" ]; then
        echo "Recreating virtualenv (was $HAVE_PY, want $WANT_PY)..."
        rm -rf "$VENV"
    fi
fi
if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating virtualenv..."
    "$PYTHON" -m venv "$VENV"
fi

# 3. Dependencies — the pinned lockfile when present (reproducible), else ranges.
REQ="$DIR/requirements.lock"
[ -f "$REQ" ] || REQ="$DIR/requirements.txt"
echo "Installing dependencies from $(basename "$REQ")..."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$REQ"

# 4. systemd user unit (path and port substituted in, so a custom DIR/PORT works).
echo "Installing systemd service..."
mkdir -p "$HOME/.config/systemd/user"
sed -e "s|%h/projects/trafilatura-local|$DIR|g" \
    -e "s|^Environment=PORT=.*|Environment=PORT=$PORT|" \
    "$DIR/trafilatura-local.service" \
    > "$HOME/.config/systemd/user/trafilatura-local.service"
systemctl --user daemon-reload

# 5. Enable and (re)start.
echo "Enabling and starting service..."
systemctl --user enable trafilatura-local.service
systemctl --user restart trafilatura-local.service

# 6. Verify: health endpoint, then one real extraction.
sleep 2
if ! systemctl --user is-active trafilatura-local.service >/dev/null 2>&1; then
    echo "Service failed to start. Check: systemctl --user status trafilatura-local.service" >&2
    exit 1
fi
curl --fail --silent --show-error --max-time 5 "http://127.0.0.1:$PORT/health"
echo
curl --fail --silent --show-error --max-time 30 \
    -H 'Content-Type: application/json' \
    -d '{"urls":["https://example.com"],"max_chars":2000}' \
    "http://127.0.0.1:$PORT/extract" >/dev/null
echo "Extraction check OK"

# 7. Startup before login needs lingering (a hint, not a failure).
if command -v loginctl >/dev/null 2>&1 \
   && ! { loginctl show-user "$USER" 2>/dev/null | grep -q 'Linger=yes'; }; then
    echo "To start the service before login: sudo loginctl enable-linger $USER"
fi
echo "Done."
