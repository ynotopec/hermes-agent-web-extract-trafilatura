---
name: web-extract-local
description: "Use when fetching or reading any URL. Hermes web_extract is backed by the local Trafilatura-Local service (:8990) with a Firecrawl fallback; browser for JS-heavy pages."
version: "3.0.0"
author: ynotopec
license: MIT
metadata:
  hermes:
    tags: [web, extract, local, no-api-key, trafilatura]
    related_skills: [web-tools-diagnostic]
---

# Web Extract Local

How to fetch readable content from a URL with this service, and how the local
extraction backend is deployed. Companion repo:
https://github.com/ynotopec/hermes-agent-web-extract-trafilatura

Static HTML only — no JavaScript rendering, PDFs, or anti-bot bypasses.

## What to do

- **Just call the `web_extract` tool** once the provider is wired in. It routes
  to the local **Trafilatura-Local** service (`127.0.0.1:8990`, F1 ~0.92) through
  the `trafilatura` provider — no API key, no rate limits.
- A URL the local service returns empty (or errors on) **falls back to Firecrawl
  keyless**, so JS-heavy / blocked pages still come back.
- **`browser_navigate`** only when `web_extract` returns empty/garbled (<200
  chars) — real JavaScript rendering is out of the service's scope.
- CLI equivalent (same service): `python3 web_fetch.py "<url>" [--format plain]`.

## Deploy the service

```bash
git clone https://github.com/ynotopec/hermes-agent-web-extract-trafilatura ~/projects/trafilatura-local
cd ~/projects/trafilatura-local && ./install.sh
curl --fail http://127.0.0.1:8990/health
```

`install.sh` fast-forwards the checkout, creates a venv, installs the user
systemd unit and restarts it, then verifies `/health` and one extraction. The
checkout is fixed at `~/projects/trafilatura-local` (hard-coded in the unit).

## Wire it into Hermes

```bash
cd ~/projects/trafilatura-local && ./hermes/install.sh
hermes config set web.extract_backend trafilatura
hermes gateway restart
```

- User plugins are **disabled by default** — `hermes plugins enable web/trafilatura` is required (the installer runs it).
- A **running gateway keeps its web-provider registry** from startup: after
  installing the plugin a fresh `python3` process resolves
  `get_provider('trafilatura')`, but the live session still errors
  `no registered web extract provider has that name` until `hermes gateway restart`.
- `~/.hermes/config.yaml` is agent-write-protected — change it with
  `hermes config set`, not by editing.

## Pitfalls

- **Stale cache masks a fixed backend.** After changing the backend or a service
  fix, purge `~/.hermes/cache/web/extract-index.json` entries for the URL (TTL
  default 20 min) or a fresh session resserves the old content.
- **Trafilatura drops links on listing pages** (trending/index/dashboard). The
  service re-extracts the main region keeping its links when Trafilatura returns
  zero links on a link-dense page; verify with the repo's tests.
- `title` in the API response comes from Trafilatura page metadata.

## API

```bash
curl 'http://127.0.0.1:8990/extract?url=https://example.com'
curl -H 'Content-Type: application/json' \
  -d '{"urls":["https://example.com"],"format":"markdown","max_chars":15000}' \
  http://127.0.0.1:8990/extract
```

POST formats: `markdown`, `txt`, `html`. Results preserve input order with
`url`, `title`, `content`, `error`, `metadata` (final URL, format, truncation,
response time).
