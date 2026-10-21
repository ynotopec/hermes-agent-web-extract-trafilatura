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

# Keep each revision's sources available for rollout undo. Never overwrite a
# ConfigMap referenced by an older ReplicaSet.
CHECKSUM="$(cat "$REPO/server.py" "$REPO/extraction.py" "$REPO/requirements.lock" \
  | sha256sum | cut -d' ' -f1)"
CONFIGMAP="trafilatura-server-$CHECKSUM"
echo "==> Applying immutable ConfigMap ($NS/$CONFIGMAP)"
kubectl -n "$NS" create configmap "$CONFIGMAP" \
  --from-file=server.py="$REPO/server.py" \
  --from-file=extraction.py="$REPO/extraction.py" \
  --from-file=requirements.lock="$REPO/requirements.lock" \
  --dry-run=client -o json \
  | kubectl patch --local -f - --type=merge -p '{"immutable":true}' -o json \
  | kubectl -n "$NS" apply -f -

echo "==> Applying Deployment and Service"
# Render both the source reference and annotation before applying the template,
# so a revision can never combine a new checksum with an old source reference.
sed "s/CODE_SHA256/$CHECKSUM/g" "$HERE/01-deployment.yaml" \
  | kubectl -n "$NS" apply -f -
kubectl -n "$NS" apply -f "$HERE/02-service.yaml"

echo "==> Waiting for rollout"
kubectl -n "$NS" rollout status deploy/trafilatura-service --timeout=300s

echo "==> Health check"
# The expected version is read from the source that was just deployed, so the
# check verifies that the running service serves THIS code and not a pod
# left over from a previous rollout.
EXPECTED_VERSION="$(grep -oE 'version="[0-9]+\.[0-9]+\.[0-9]+"' "$REPO/server.py" | head -1 | cut -d'"' -f2)"
echo "    expected version: $EXPECTED_VERSION"
kubectl -n "$NS" run trafilatura-health --rm -i --restart=Never \
  --image=python:3.12-slim --override-type=strategic \
  --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":10001,"runAsGroup":10001,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"trafilatura-health","securityContext":{"allowPrivilegeEscalation":false,"readOnlyRootFilesystem":true,"capabilities":{"drop":["ALL"]}}}]}}' \
  --command -- python - "$EXPECTED_VERSION" <<'PY'
import json, sys, urllib.request
expected = sys.argv[1]
health = json.load(urllib.request.urlopen("http://trafilatura:8990/health"))
print(health)
assert health["status"] == "ok", health
assert health["version"] == expected, (health, expected)
PY

echo "==> Service ready: http://trafilatura.$NS.svc.cluster.local:8990"
