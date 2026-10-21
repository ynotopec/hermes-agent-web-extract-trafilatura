# Changelog

## Unreleased

- The provider resolves the service through Kubernetes discovery
  (`TRAFILATURA_SERVICE_HOST` / `TRAFILATURA_SERVICE_PORT`) when
  `TRAFILATURA_URL` is unset, before falling back to `127.0.0.1:8990`. A pod
  running next to a `trafilatura` service now finds it with no configuration.
- `install.sh` no longer requires systemd: with no reachable user manager it
  installs the checkout and the virtualenv and prints the command to start the
  service (containers, CI, WSL). `TRAFILATURA_MODE=auto|systemd|none` forces
  the behaviour.
- `hermes/install.sh` now enables the plugin and sets
  `web.extract_backend: trafilatura` instead of only printing the commands,
  finds the Hermes CLI through `$HERMES_CLI`, `hermes` on `PATH` or
  `python -m hermes_cli.main`, and verifies the plugin is listed afterwards.
  A skipped enable step is what left `web_extract` failing with "no
  registered web extract provider has that name".
- The provider's "service unreachable" error mentions the non-systemd start
  command and `TRAFILATURA_URL`, not only `systemctl --user`.
- `install.sh` honours `TRAFILATURA_REF` to pin the checkout to a tag/commit
  (e.g. `TRAFILATURA_REF=v0.3.0 ./install.sh`).
- Removed the shipped Hermes skill: the backend is transparent, so there is
  nothing special to do during a `web_extract`. Deployment lives in this README;
  `hermes/install.sh` now installs only the provider plugin.

## 0.3.0 — 2026-10-07

- **Reproducibility**: pinned `requirements.lock` (full transitive tree) used by
  `install.sh`, `.python-version`, a Python >= 3.10 guard with venv recreation on
  interpreter change, `TRAFILATURA_DIR`/`TRAFILATURA_PORT`/`PYTHON` overrides, a
  CI job that tests the lock, and `requires_hermes` on the provider manifest.
- **Hermes Agent integration**: a provider plugin (`hermes/plugins/web/trafilatura/`),
  a companion skill (`hermes/skills/web-extract/`) and `hermes/install.sh`
  to wire the service into Hermes (`web.extract_backend: trafilatura`). See the README.
- **`title` populated** from page metadata (was always empty).
- **Links kept on listing pages**: when Trafilatura drops every link on a
  link-dense page (dashboards, "trending"/index listings), the main region is
  re-extracted keeping headings, list items and anchors — fixes GitHub Trending
  losing owner/repo names.
- `install.sh` fast-forwards the checkout, recreates a broken venv, verifies
  `/health` **and** a real extraction, and prints the lingering hint.
- `uninstall.sh` added.
- MIT `LICENSE`; CI runs `ruff` and Python 3.13/3.14.
- CLI reads `TRAFILATURA_URL` and `TRAFILATURA_TIMEOUT`.
- Clearer per-URL failure message (`Content extraction failed: <ErrorType>`).

## 0.2.0

- Bounded, SSRF-hardened URL fetching; async responsiveness; extraction falls
  back from precision to recall when precision yields nothing.
