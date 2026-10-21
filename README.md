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

### Hosts without systemd (containers, CI, WSL)

When no systemd user manager is reachable, the installer skips the unit and
installs only the checkout and the virtualenv; it prints the command to start
the service yourself:

```bash
TRAFILATURA_DIR=~/projects/trafilatura-local \
TRAFILATURA_PORT=8990 \
~/projects/trafilatura-local/venv/bin/python ~/projects/trafilatura-local/server.py
```

Force the behaviour with `TRAFILATURA_MODE=systemd|none|auto` (default
`auto`). The service then runs as an ordinary background process: keep it
alive with whatever supervises your host (s6, supervisord, an init script)
and point the provider at it with `TRAFILATURA_URL` when it is not on
`127.0.0.1:8990`.

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
- **Pin a release**: `TRAFILATURA_REF=v0.3.0 ./install.sh` checks the checkout out
  at that tag/commit instead of following `main` (leaves a detached HEAD).
- The test suite is offline and deterministic; CI runs it on 3.10–3.14 **and**
  once against the pinned lockfile.

## Hermes Agent integration

This service ships a Hermes web-extract provider under `hermes/`. Install it
into your Hermes home, point the extract backend at it, then restart the gateway:

```bash
./hermes/install.sh                       # copies the plugin, enables it
hermes config set web.extract_backend trafilatura
hermes gateway restart                    # a running gateway keeps its provider registry
```

`./hermes/install.sh` copies `hermes/plugins/web/trafilatura/` to
`~/.hermes/plugins/web/trafilatura/`, enables the plugin, sets
`web.extract_backend: trafilatura` and verifies the CLI lists the plugin. It
finds the Hermes CLI via `$HERMES_CLI`, then `hermes` on `PATH`, then
`python -m hermes_cli.main` — the CLI is not always on `PATH` (containers,
source installs), and skipping the enable step leaves `web_extract` failing
with "no registered web extract provider has that name".
The provider calls this service over
loopback and falls back to the Firecrawl keyless cloud extractor when a page
comes back empty (JS-heavy or blocked pages), so listings never come back thin.
User plugins are disabled by default — `hermes plugins enable web/trafilatura`
(the installer runs it). No agent skill ships with it: the backend is
transparent, so nothing special is required at extraction time.

## API and CLI

```bash
curl 'http://127.0.0.1:8990/extract?url=https://example.com'
curl --fail -H 'Content-Type: application/json' \
    -d '{"urls":["https://example.com"],"format":"markdown","max_chars":15000}' \
    http://127.0.0.1:8990/extract
python3 web_fetch.py https://example.com --format plain --limit 15000
```

### Reaching the service

The provider resolves the service URL in this order:

1. `TRAFILATURA_URL` — explicit override, e.g. `http://extractor:9000`.
2. Kubernetes service discovery: `TRAFILATURA_SERVICE_HOST` and
   `TRAFILATURA_SERVICE_PORT`, which Kubernetes injects into every pod of the
   namespace that owns a service named `trafilatura`. A Hermes pod running
   next to that service therefore finds it with no extra configuration.
3. `http://127.0.0.1:8990` — the loopback default.

Set `TRAFILATURA_URL` to override the discovery when the service sits behind
another address.

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

## Kubernetes deployment

`k8s/` deploys the service as a Deployment (`trafilatura-service`) behind a
ClusterIP Service named `trafilatura` on port 8990, so that a Hermes pod in
the same namespace reaches it through the discovery variables described above.

```bash
./k8s/deploy.sh demo1
```

Design choices:

- **Code and pinned dependencies travel in a ConfigMap** (`server.py`,
  `extraction.py`, `requirements.lock`). An initContainer installs the locked
  dependencies into a shared volume; the application container serves directly
  from it. A `pip install` on the serving path outlasts the liveness probe and
  produces a restart loop (the pod is killed while still installing).
- **Plain `python:3.12-slim` image.** The cluster's internal registry is not
  pullable from the kubelet — the node resolver does not answer for service
  names and containerd has no insecure-registry entry — so a locally built
  image cannot be consumed by the cluster as-is. The `Dockerfile` at the
  repository root builds that image (verified: health check, non-root user,
  real extraction); it becomes usable as soon as the registry is reachable
  from the kubelet.
- **`startupProbe`** on `/health` gates the liveness and readiness probes
  while the application starts. Dependency installation finishes in the
  initContainer before the application container and its probes start.
- Each source revision uses an **immutable ConfigMap named with its checksum**.
  The script renders its name and the `trafilatura.infocepo.com/code-sha256`
  annotation into the pod template before applying it. Code changes trigger a
  rollout; unchanged sources keep the same template. Old ConfigMaps are retained
  so `kubectl rollout undo deployment/trafilatura-service` restores the matching
  sources and dependency lock. Keep them while their ReplicaSets may be restored;
  the script does not automatically delete historical ConfigMaps.
- The post-deploy health check compares the version reported by `/health`
  with the version of the source that was just deployed, so a stale pod
  fails the deployment instead of passing it.
- Two replicas, `runAsNonRoot`, read-only root filesystem, all capabilities
  dropped, and `allowPrivilegeEscalation: false`, including the initContainer.
  The temporary health-check pod also uses settings compatible with the
  Kubernetes Restricted Pod Security Standard.
- The manifests carry no `namespace:` field: the target namespace is passed
  with `kubectl -n`, so the same manifests can be applied to any namespace.
- The extraction runs on the **serving** path only against public
  destinations: internal and private IPs are rejected (see *Limits and
  security*), so the service cannot be used to reach cluster-internal
  endpoints.

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
