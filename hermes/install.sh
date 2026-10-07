#!/usr/bin/env bash
# Install the Trafilatura-Local provider plugin (+ skill) into a Hermes home.
#
#   HERMES_HOME=/path/to/.hermes ./hermes/install.sh
#
# Then set the extract backend and restart the gateway so it re-registers web
# providers:
#   hermes config set web.extract_backend trafilatura
#   hermes gateway restart
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hermes_home="${HERMES_HOME:-$HOME/.hermes}"

plugins_dir="$hermes_home/plugins/web"
skills_dir="$hermes_home/skills"
mkdir -p "$plugins_dir" "$skills_dir"

rm -rf "$plugins_dir/trafilatura"          # replace, never nest on re-run
cp -R "$here/plugins/web/trafilatura" "$plugins_dir/trafilatura"
cp -R "$here/skills/trafilatura-local" "$skills_dir/trafilatura-local"

echo "Installed provider plugin -> $plugins_dir/trafilatura"
echo "Installed skill           -> $skills_dir/trafilatura-local"

if command -v hermes >/dev/null 2>&1; then
  hermes plugins enable web/trafilatura || true
  echo
  echo "Next:"
  echo "  hermes config set web.extract_backend trafilatura"
  echo "  hermes gateway restart   # a running gateway keeps its web-provider registry"
else
  echo
  echo "hermes CLI not on PATH — enable the plugin manually: hermes plugins enable web/trafilatura"
fi
