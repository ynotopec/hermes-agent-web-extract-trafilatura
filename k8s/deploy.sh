#!/usr/bin/env bash
# Deploy the Trafilatura-Local extraction service to Kubernetes.
#
#   ./k8s/deploy.sh [namespace]
#
# The service code and the pinned dependency tree travel in a ConfigMap; an
# initContainer installs the pinned dependencies into a shared volume, so the
# application container never runs `pip install` on the serving path (a pip
# install at startup outlasts the liveness probe and produces a restart loop).
#
# The image is plain `python:3.12-slim`: the cluster's internal registry is not
# pullable from the kubelet (the node resolver does not answer for service
# names and containerd has no insecure-registry entry), so a locally built
# image cannot be consumed here.
set -euo pipefail

NS="${1:-demo1}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found" >&2; exit 1; }

echo "==> Refreshing ConfigMap ($NS/trafilatura-server) from $REPO"
kubectl -n "$NS" create configmap trafilatura-server \
  --from-file=server.py="$REPO/server.py" \
  --from-file=extraction.py="$REPO/extraction.py" \
  --from-file=requirements.lock="$REPO/requirements.lock" \
  --dry-run=client -o yaml | kubectl -n "$NS" apply -f -

# The code travels in a ConfigMap, and a ConfigMap change does NOT restart
# the pods that mount it: the running process keeps serving the code it
# imported at start-up. `rollout status` reports "successfully rolled out"
# without any pod ever restarting, so the new code would never reach the
# service. Anchoring the pod template on the checksum of the sources makes
# the Deployment roll whenever the code changes, and stay put when it does
# not.
echo "==> Computing source checksum"
CHECKSUM="$(cat "$REPO/server.py" "$REPO/extraction.py" "$REPO/requirements.lock" \
  | sha256sum | cut -d' ' -f1)"
echo "    code checksum: $CHECKSUM"

echo "==> Applying Deployment and Service"
kubectl -n "$NS" apply -f "$HERE/01-deployment.yaml"
kubectl -n "$NS" apply -f "$HERE/02-service.yaml"
kubectl -n "$NS" patch deployment trafilatura-service --type=merge \
  -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"trafilatura.infocepo.com/code-sha256\":\"$CHECKSUM\"}}}}}" \
  >/dev/null

echo "==> Waiting for rollout"
kubectl -n "$NS" rollout status deploy/trafilatura-service --timeout=300s

echo "==> Health check"
# The expected version is read from the source that was just deployed, so the
# check verifies that the running service serves THIS code and not a pod
# left over from a previous rollout.
EXPECTED_VERSION="$(grep -oE 'version="[0-9]+\.[0-9]+\.[0-9]+"' "$REPO/server.py" | head -1 | cut -d'"' -f2)"
echo "    expected version: $EXPECTED_VERSION"
kubectl -n "$NS" run trafilatura-health --rm -i --restart=Never \
  --image=python:3.12-slim --command -- python - "$EXPECTED_VERSION" <<'PY'
import json, sys, urllib.request
expected = sys.argv[1]
health = json.load(urllib.request.urlopen("http://trafilatura:8990/health"))
print(health)
assert health["status"] == "ok", health
assert health["version"] == expected, (health, expected)
PY

echo "==> Service ready: http://trafilatura:$NS.svc.cluster.local:8990"
