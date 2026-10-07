#!/bin/bash
set -euo pipefail

echo "=== Trafilatura-Local Setup ==="
echo "  - Installs Python dependencies"
echo "  - Configures systemd --user service"
echo "  - Enables service (survives reboot)"

DIR="$HOME/projects/trafilatura-local"
VENV="$DIR/venv"

# 1. Clone (if not already done)
if [ ! -d "$DIR/.git" ]; then
    echo "Cloning repo..."
    git clone https://github.com/ynotopec/trafilatura-local "$DIR"
fi

# 2. Venv + dependencies
if [ ! -d "$VENV" ]; then
    echo "Creating virtualenv..."
    python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install -r "$DIR/requirements.txt"

# 3. Install systemd service
echo "Installing systemd service..."
mkdir -p "$HOME/.config/systemd/user"
cp "$DIR/trafilatura-local.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload

# 4. Enable and start
echo "Enabling and starting service..."
systemctl --user enable trafilatura-local.service
systemctl --user restart trafilatura-local.service

# 5. Verification
sleep 2
if systemctl --user is-active trafilatura-local.service >/dev/null 2>&1; then
    echo "Service is running on port 8990"
    echo "Service enabled for the user session; boot without login requires loginctl enable-linger."
    curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8990/health
else
    echo "Service failed to start. Check: systemctl --user status trafilatura-local.service"
    exit 1
fi
