#!/bin/bash
set -euo pipefail

echo "=== Trafilatura-Local Setup ==="
echo "  - Updates the checkout and installs Python dependencies"
echo "  - Configures and (re)starts the systemd --user service"

DIR="$HOME/projects/trafilatura-local"
VENV="$DIR/venv"

# 1. Clone, or fast-forward an existing checkout.
if [ ! -d "$DIR/.git" ]; then
    echo "Cloning repo..."
    git clone https://github.com/ynotopec/trafilatura-local "$DIR"
else
    echo "Updating checkout..."
    git -C "$DIR" fetch --quiet origin
    git -C "$DIR" merge --ff-only origin/main \
        || echo "  ⚠ checkout has local changes or diverges from origin/main — left as-is"
fi

# 2. Virtualenv + dependencies (recreated when the interpreter is missing/broken).
if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating virtualenv..."
    python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$DIR/requirements.txt"

# 3. systemd user unit.
echo "Installing systemd service..."
mkdir -p "$HOME/.config/systemd/user"
cp "$DIR/trafilatura-local.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload

# 4. Enable and (re)start.
echo "Enabling and starting service..."
systemctl --user enable trafilatura-local.service
systemctl --user restart trafilatura-local.service

# 5. Verify: health endpoint, then one real extraction.
sleep 2
if ! systemctl --user is-active trafilatura-local.service >/dev/null 2>&1; then
    echo "Service failed to start. Check: systemctl --user status trafilatura-local.service" >&2
    exit 1
fi
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8990/health
echo
curl --fail --silent --show-error --max-time 30 \
    -H 'Content-Type: application/json' \
    -d '{"urls":["https://example.com"],"max_chars":2000}' \
    http://127.0.0.1:8990/extract >/dev/null
echo "Extraction check OK"

# 6. Startup before login needs lingering (a hint, not a failure).
if command -v loginctl >/dev/null 2>&1 \
   && ! { loginctl show-user "$USER" 2>/dev/null | grep -q 'Linger=yes'; }; then
    echo "To start the service before login: sudo loginctl enable-linger $USER"
fi
echo "Done."
