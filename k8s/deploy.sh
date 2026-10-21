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

echo "==> Applying Deployment and Service"
kubectl -n "$NS" apply -f "$HERE/01-deployment.yaml"
kubectl -n "$NS" apply -f "$HERE/02-service.yaml"

echo "==> Waiting for rollout"
kubectl -n "$NS" rollout status deploy/trafilatura-service --timeout=300s

echo "==> Health check"
kubectl -n "$NS" run trafilatura-health --rm -i --restart=Never \
  --image=python:3.12-slim --command -- python - <<'PY'
import json, urllib.request
print(json.load(urllib.request.urlopen("http://trafilatura:8990/health")))
PY

echo "==> Service ready: http://trafilatura:$NS.svc.cluster.local:8990"
