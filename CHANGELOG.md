# Changelog

## Unreleased

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
