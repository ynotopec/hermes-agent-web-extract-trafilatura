# Changelog

## Unreleased

- **Hermes Agent integration**: a provider plugin (`hermes/plugins/web/trafilatura/`),
  a companion skill (`hermes/skills/web-extract-local/`) and `hermes/install.sh`
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
