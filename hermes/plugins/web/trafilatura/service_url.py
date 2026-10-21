"""Resolution of the Trafilatura-Local service URL.

Kept free of any Hermes import so it can be unit-tested standalone (the
provider module needs ``agent.web_search_provider``).

Order of resolution:

1. ``TRAFILATURA_URL`` — explicit override, wins over everything.
2. Kubernetes service discovery: ``TRAFILATURA_SERVICE_HOST`` +
   ``TRAFILATURA_SERVICE_PORT``. Kubernetes injects these into every pod of
   the namespace that owns a service named ``trafilatura``, so a pod running
   next to the service finds it without any extra configuration. The
   ``_PORT_<n>_TCP`` variants are ignored on purpose: their values carry the
   ``tcp://`` scheme and are not a port number.
3. ``http://127.0.0.1:8990`` — the loopback default.
"""

from __future__ import annotations

import os
from typing import Mapping, Optional

DEFAULT_URL = "http://127.0.0.1:8990"

#: Env var holding the service host injected by Kubernetes.
K8S_HOST_VAR = "TRAFILATURA_SERVICE_HOST"
#: Env var holding the service port injected by Kubernetes.
K8S_PORT_VAR = "TRAFILATURA_SERVICE_PORT"


def _clean(value: Optional[str]) -> str:
    return (value or "").strip()


def k8s_service_url(env: Mapping[str, str]) -> Optional[str]:
    """Service URL from the Kubernetes-injected env vars, or None.

    The port is optional: a service without a declared port still resolves
    through the host alone.
    """
    host = _clean(env.get(K8S_HOST_VAR))
    if not host:
        return None
    port = _clean(env.get(K8S_PORT_VAR))
    # A non-numeric port means the variable is not a port (some clusters
    # inject ``tcp://host:port`` shapes); the host alone is still usable.
    if port.isdigit():
        return f"http://{host}:{port}"
    return f"http://{host}"


def resolve_service_url(env: Optional[Mapping[str, str]] = None) -> str:
    """Base URL of the Trafilatura-Local service."""
    env = os.environ if env is None else env

    explicit = _clean(env.get("TRAFILATURA_URL"))
    if explicit:
        return explicit.rstrip("/") or DEFAULT_URL

    discovered = k8s_service_url(env)
    if discovered:
        return discovered.rstrip("/")

    return DEFAULT_URL
