---
name: trafilatura-local
description: "Use when deploying or wiring the Trafilatura-Local extraction service (Hermes web_extract backend)."
version: 1.0.0
author: ynotopec
license: MIT
metadata:
  hermes:
    tags: [web, extraction, trafilatura, hermesextract, backend]
    related_skills: [web-tools-diagnostic]
---

# Trafilatura-Local

Local HTTP service for readable web extraction (Trafilatura) and its Hermes
web-extract provider. Companion repo:
https://github.com/ynotopec/hermes-agent-web-extract-trafilatura

Static HTML only — no JavaScript rendering, PDFs, or anti-bot bypasses.

## Deploy the service

```bash
git clone https://github.com/ynotopec/hermes-agent-web-extract-trafilatura ~/projects/trafilatura-local
cd ~/projects/trafilatura-local && ./install.sh
curl --fail http://127.0.0.1:8990/health
```

`install.sh` creates a venv, installs the user systemd unit and starts it. The
checkout is fixed at `~/projects/trafilatura-local` (hard-coded in the unit).

## Wire it into Hermes

```bash
cd ~/projects/trafilatura-local && ./hermes/install.sh
hermes config set web.extract_backend trafilatura
hermes gateway restart
```

- User plugins are **disabled by default** — `hermes plugins enable web/trafilatura` is required.
- A **running gateway keeps its web-provider registry** from startup: after installing the plugin a fresh `python3` process resolves `get_provider('trafilatura')`, but the live session still errors `no registered web extract provider has that name` until `hermes gateway restart`.
- `~/.hermes/config.yaml` is agent-write-protected — change it with `hermes config set`, not by editing.

## Pitfalls

- **Stale cache masks a fixed backend.** After changing the backend or a service fix, purge `~/.hermes/cache/web/extract-index.json` entries for the URL (TTL default 20 min) or a fresh session resserves the old content.
- **Trafilatura drops links on listing pages** (trending/index/dashboard) unless the fix from PR #2 is present. The service falls back to a link-preserving re-extraction of `<main>` when Trafilatura returns zero links on a link-dense page; verify with the repo's tests.
- **API response `title`** is populated from Trafilatura metadata when available.

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
