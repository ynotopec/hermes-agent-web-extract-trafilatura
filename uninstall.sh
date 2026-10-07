#!/bin/bash
set -euo pipefail
# Remove the Trafilatura-Local systemd user service.
#   ./uninstall.sh            stop + disable the service, remove the unit file
#   ./uninstall.sh --purge    also delete the checkout (~/projects/trafilatura-local)

DIR="$HOME/projects/trafilatura-local"

echo "Stopping and disabling the service..."
systemctl --user stop trafilatura-local.service 2>/dev/null || true
systemctl --user disable trafilatura-local.service 2>/dev/null || true

echo "Removing the unit file..."
rm -f "$HOME/.config/systemd/user/trafilatura-local.service"
systemctl --user daemon-reload

if [ "${1:-}" = "--purge" ]; then
    echo "Removing $DIR ..."
    rm -rf "$DIR"
fi

echo "Done.${1:+ }"
[ "${1:-}" = "--purge" ] || echo "Pass --purge to also delete the checkout at $DIR."
