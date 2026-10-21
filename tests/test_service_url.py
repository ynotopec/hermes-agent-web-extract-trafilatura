"""Tests for the provider's service-URL resolution.

``service_url`` is loaded by path: it must stay importable without Hermes
(``agent.web_search_provider``) installed, so the resolution rules can be
tested in this repository's own suite.
"""

import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "hermes" / "plugins" / "web" / "trafilatura" / "service_url.py"


def _load():
    spec = importlib.util.spec_from_file_location("trafilatura_service_url", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


service_url = _load()


def test_default_is_loopback():
    assert service_url.resolve_service_url({}) == "http://127.0.0.1:8990"


def test_explicit_url_wins():
    env = {
        "TRAFILATURA_URL": "http://extractor:9000",
        "TRAFILATURA_SERVICE_HOST": "10.0.0.5",
        "TRAFILATURA_SERVICE_PORT": "8990",
    }
    assert service_url.resolve_service_url(env) == "http://extractor:9000"


def test_explicit_url_trailing_slash_is_trimmed():
    assert service_url.resolve_service_url({"TRAFILATURA_URL": "http://extractor:9000/"}) == "http://extractor:9000"


def test_kubernetes_service_discovery():
    env = {"TRAFILATURA_SERVICE_HOST": "10.152.183.233", "TRAFILATURA_SERVICE_PORT": "8990"}
    assert service_url.resolve_service_url(env) == "http://10.152.183.233:8990"


def test_kubernetes_discovery_without_port():
    env = {"TRAFILATURA_SERVICE_HOST": "trafilatura"}
    assert service_url.resolve_service_url(env) == "http://trafilatura"


def test_kubernetes_tcp_scheme_port_is_ignored():
    # Kubernetes also injects TRAFILATURA_PORT_8990_TCP=tcp://host:port; that
    # value is not a port number and must not end up in the URL.
    env = {
        "TRAFILATURA_SERVICE_HOST": "10.152.183.233",
        "TRAFILATURA_SERVICE_PORT": "8990",
        "TRAFILATURA_PORT_8990_TCP": "tcp://10.152.183.233:8990",
    }
    assert service_url.resolve_service_url(env) == "http://10.152.183.233:8990"


def test_blank_explicit_url_falls_through_to_discovery():
    env = {"TRAFILATURA_URL": "  ", "TRAFILATURA_SERVICE_HOST": "10.0.0.5", "TRAFILATURA_SERVICE_PORT": "8990"}
    assert service_url.resolve_service_url(env) == "http://10.0.0.5:8990"


def test_k8s_service_url_returns_none_without_host():
    assert service_url.k8s_service_url({"TRAFILATURA_SERVICE_PORT": "8990"}) is None


@pytest.mark.parametrize("port", ["0", "8080", "65535"])
def test_numeric_ports_are_used(port):
    assert service_url.k8s_service_url({"TRAFILATURA_SERVICE_HOST": "h", "TRAFILATURA_SERVICE_PORT": port}) == f"http://h:{port}"
