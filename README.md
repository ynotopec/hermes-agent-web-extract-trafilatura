# Trafilatura-Local

Local HTTP service and CLI for readable web extraction with Trafilatura.
HTML extraction favors precision, then retries with recall if no content is found.
Tables and links are retained; on link-dense listing pages (dashboards, "trending"
or index pages) where Trafilatura would drop every link, the main region is
re-extracted keeping its headings, list items and anchors. Plain text responses
are supported directly.
JavaScript rendering, PDFs and anti-bot bypasses are outside this service's scope.

## Install and run

```bash
./install.sh
curl --fail http://127.0.0.1:8990/health
```

The installer uses `~/projects/trafilatura-local`, fast-forwards the checkout to
`origin/main`, creates a virtualenv, reconciles requirements, installs the user
unit and restarts the service, then verifies `/health` and one real extraction.
A user service starts with the user manager. For startup before login, enable
lingering with `sudo loginctl enable-linger USER` (the installer prints this
when lingering is off); `enable` alone does not guarantee startup before login.

Alternatively:

```bash
python3 -m venv venv
./venv/bin/python -m pip install .
./venv/bin/trafilatura-server
```

To remove the service: `./uninstall.sh` (add `--purge` to also delete the checkout).

## Reproducibility

- **Dependencies** are pinned in `requirements.lock` (full transitive tree,
  CPython 3.12); `install.sh` installs it when present, else `requirements.txt`.
  Regenerate after changing `requirements.txt`:
  `pip install -r requirements.txt && pip freeze > requirements.lock`.
- **Interpreter**: `.python-version` records the tested CPython (3.12).
  `install.sh` requires >= 3.10 and recreates the venv when it was built on a
  different minor version; override with `PYTHON=/path/to/python3`.
- **Paths / port**: `TRAFILATURA_DIR` and `TRAFILATURA_PORT` (defaults
  `~/projects/trafilatura-local`, `8990`) are substituted into the installed unit.
- The test suite is offline and deterministic; CI runs it on 3.10–3.14 **and**
  once against the pinned lockfile.

## Hermes Agent integration

This service ships a Hermes web-extract provider under `hermes/`. Install it
into your Hermes home, point the extract backend at it, then restart the gateway:

```bash
./hermes/install.sh                       # copies the plugin + skill, enables it
hermes config set web.extract_backend trafilatura
hermes gateway restart                    # a running gateway keeps its provider registry
```

`./hermes/install.sh` copies `hermes/plugins/web/trafilatura/` to
`~/.hermes/plugins/web/trafilatura/` and the companion skill to
`~/.hermes/skills/web-extract/`. The provider calls this service over
loopback and falls back to the Firecrawl keyless cloud extractor when a page
comes back empty (JS-heavy or blocked pages), so listings never come back thin.
User plugins are disabled by default — `hermes plugins enable web/trafilatura`
(the installer runs it). See `hermes/skills/web-extract/SKILL.md`.

## API and CLI

```bash
curl 'http://127.0.0.1:8990/extract?url=https://example.com'
curl --fail -H 'Content-Type: application/json' \
  -d '{"urls":["https://example.com"],"format":"markdown","max_chars":15000}' \
  http://127.0.0.1:8990/extract
python3 web_fetch.py https://example.com --format plain --limit 15000
```

POST formats: `markdown`, `txt`, `html`. Results preserve input order and have
`url`, `title` (from page metadata, empty when unavailable), `content`, `error`,
and `metadata`.
Metadata includes the final URL, truncation flag and elapsed milliseconds,
including semaphore wait time. Individual extraction failures populate `error`;
invalid payloads return HTTP 422, and queue overload returns HTTP 503.
For plain text sources, the actual output format is reported as `txt`.

When the local service is unavailable, the CLI runs the same downloader and
extractor directly. It does not bypass service rejection or URL filtering with
curl. This fallback requires the project's Python dependencies.

## Limits and security

| Setting | Default | Meaning |
|---|---:|---|
| `HOST` | `127.0.0.1` | Bind address |
| `PORT` | `8990` | Listen port |
| `MAX_CHARS` | 200000 | Default and maximum API output characters |
| `MAX_BYTES` | 5000000 | Maximum decoded download bytes per page |
| `FETCH_TIMEOUT` | 30 | Total download deadline, including DNS and redirects |
| `CONCURRENCY` | 4 | Concurrent download/extraction jobs per server process |

Request bodies are capped at 256000 bytes. Requests contain 1–20 URLs, each at most 8192 characters. At most 64 URL jobs
are admitted per process. Redirects are limited to five. Streaming enforces the
byte cap even when Content-Length is absent. The downloader requests identity
encoding and rejects compressed responses to avoid decompression bombs. Output
limits apply after extraction, and truncation may cut Markdown or HTML syntax.

Only public HTTP(S) destinations are accepted, without URL credentials. Every
redirect is checked. All resolved addresses must be public; the connection is
pinned to a validated address to prevent DNS rebinding. The original Host and
TLS server name are retained, with certificate verification enabled. Separate
origin pools prevent TLS connections from being reused across unrelated hosts
sharing an IP. Connection pools are cached for up to 32 origins; additional
origins use temporary transports. Environment proxies are disabled deliberately.
Private intranet and cloud metadata endpoints are blocked, including in the CLI.

Keep the default loopback bind. The API has no authentication; exposing it needs
an authenticated reverse proxy and rate limiting. Extracted web text remains
untrusted input for agents. Systemd applies NoNewPrivileges, PrivateTmp, a private
umask, and memory/task limits (availability depends on the host's user manager).
Logs go to journald rather than an unbounded duplicate log file.

Extraction runs in a worker thread so it does not block the event loop. This
improves responsiveness but does not promise CPU parallelism or a hard deadline
for the parser. Worker processes would be needed for hard parser timeouts.

## Validation

```bash
python -m pip install '.[test]'
python -m pytest -q
```

Tests cover public-destination filtering, redirect rejection, DNS pinning,
size/deadline controls, payload validation, ordering, truncation and CLI fallback.
No deployment-specific F1 score or latency improvement is claimed. Evaluate
quality and p50/p95 latency on representative articles, documentation, wiki pages
and tables. Upstream evaluation: https://trafilatura.readthedocs.io/en/latest/evaluation.html
