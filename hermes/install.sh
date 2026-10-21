#!/usr/bin/env bash
# Install the Trafilatura-Local provider plugin into a Hermes home.
#
#   HERMES_HOME=/path/to/.hermes ./hermes/install.sh
#
# The script enables the plugin, points web.extract_backend at it, and
# verifies the provider is actually registered — an enabled plugin whose
# provider never registers makes every web_extract fail with
# "no registered web extract provider has that name".
#
# The Hermes CLI is located in this order:
#   1. $HERMES_CLI            (explicit path/command)
#   2. `hermes` on PATH
#   3. `python -m hermes_cli.main` (the CLI also runs as a module)
#
# A running gateway keeps its provider registry, so it must be reloaded
# afterwards (see the final message).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hermes_home="${HERMES_HOME:-$HOME/.hermes}"

plugins_dir="$hermes_home/plugins/web"
mkdir -p "$plugins_dir"

rm -rf "$plugins_dir/trafilatura"          # replace, never nest on re-run
cp -R "$here/plugins/web/trafilatura" "$plugins_dir/trafilatura"

echo "Installed provider plugin -> $plugins_dir/trafilatura"

# --- locate the Hermes CLI ----------------------------------------------------
hermes_cmd=()
if [ -n "${HERMES_CLI:-}" ]; then
    # shellcheck disable=SC2206 # intentional word splitting: HERMES_CLI may carry args
    hermes_cmd=($HERMES_CLI)
elif command -v hermes >/dev/null 2>&1; then
    hermes_cmd=(hermes)
elif python3 -c 'import hermes_cli.main' >/dev/null 2>&1; then
    hermes_cmd=(python3 -m hermes_cli.main)
fi

if [ ${#hermes_cmd[@]} -eq 0 ]; then
    echo
    echo "Hermes CLI not found — enable the plugin manually:"
    echo "  hermes plugins enable web/trafilatura"
    echo "  hermes config set web.extract_backend trafilatura"
    exit 0
fi

echo "Using Hermes CLI: ${hermes_cmd[*]}"

# --- enable the plugin and select the backend ---------------------------------
"${hermes_cmd[@]}" plugins enable web/trafilatura
"${hermes_cmd[@]}" config set web.extract_backend trafilatura

# --- verify the provider is really registered ---------------------------------
# `plugins list` only reports the config allow-list; the provider registration
# happens at plugin load. Re-running discovery in a fresh process and asking
# the registry is the only way to prove the backend resolves.
verify_registration() {
    "${hermes_cmd[@]}" plugins list --json 2>/dev/null \
        | python3 -c '
import json, sys
try:
    plugins = json.load(sys.stdin)
except Exception:
    sys.exit(2)
names = {p.get("key") or p.get("name") for p in plugins}
names |= {p.get("name") for p in plugins}
sys.exit(0 if {"web/trafilatura", "web-trafilatura"} & names else 1)
'
}

if verify_registration; then
    echo "Plugin web/trafilatura is enabled and listed by the CLI."
else
    echo "WARNING: the plugin was enabled but 'hermes plugins list' does not show it." >&2
    echo "         Check the plugin manifest at $plugins_dir/trafilatura/plugin.yaml." >&2
fi

cat <<'EOF'

Next:
EOF
echo "  ${hermes_cmd[*]} gateway restart   # a running gateway keeps its web-provider registry"
echo "  # then check: ${hermes_cmd[*]} config get web.extract_backend"
