import asyncio
import socket

import httpx
import pytest
from fastapi.testclient import TestClient

import extraction
import server
import web_fetch


@pytest.fixture
def public_dns(monkeypatch):
    async def resolve(self, host, port, **kwargs):
        ip = "127.0.0.1" if host == "internal.test" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", resolve)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com", "http://user:pass@example.com", "http://internal.test"])
async def test_forbidden_targets(url, public_dns):
    with pytest.raises(extraction.ExtractionError):
        await extraction.public_target(url)


async def test_pinned_address_and_sni(public_dns):
    def handler(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>hello</p>")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        body, url, mime = await extraction.fetch_page(client, "https://example.com")
        assert body == b"<p>hello</p>"
        assert url == "https://example.com"


async def test_redirect_to_private_rejected(public_dns):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://internal.test"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(extraction.ExtractionError, match="Non-public"):
            await extraction.fetch_page(client, "https://example.com")
    assert len(calls) == 1


@pytest.mark.parametrize("headers,body", [({"content-type": "text/html", "content-length": "100"}, b"a"), ({"content-type": "text/html"}, b"a" * 11)])
async def test_download_limit(public_dns, monkeypatch, headers, body):
    monkeypatch.setattr(extraction, "MAX_BYTES", 10)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, headers=headers, content=body))) as client:
        with pytest.raises(extraction.ExtractionError, match="limit"):
            await extraction.fetch_page(client, "https://example.com")


async def test_total_fetch_deadline(public_dns, monkeypatch):
    monkeypatch.setattr(extraction, "FETCH_TIMEOUT", 0.01)
    async def handler(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(extraction.ExtractionError, match="timed out"):
            await extraction.fetch_page(client, "https://example.com")


@pytest.mark.parametrize("payload", [{"urls": []}, {"urls": ["x"] * 21}, {"urls": ["x"], "max_chars": 0}, {"urls": ["x"], "max_chars": None}, {"urls": ["x"], "format": "invalid"}])
def test_request_limits(payload):
    with TestClient(server.app) as client:
        assert client.post("/extract", json=payload).status_code == 422


def test_order_truncation_and_global_concurrency(monkeypatch):
    active = peak = 0
    async def fetch(client, url):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02 if url == "slow" else 0.001)
        active -= 1
        return "abcdef", url, "text/plain"
    monkeypatch.setattr(server, "fetch_page", fetch)
    monkeypatch.setattr(server, "CONCURRENCY", 1)
    with TestClient(server.app) as client:
        results = client.post("/extract", json={"urls": ["slow", "fast"], "max_chars": 3}).json()["results"]
        assert [r["url"] for r in results] == ["slow", "fast"]
        assert results[0]["content"] == "abc"
        assert results[0]["metadata"]["truncated"]
        assert peak == 1
        assert client.get("/extract", params={"url": "fast"}).status_code == 200


def test_cli_fallback_uses_extractor(monkeypatch):
    def unavailable(*args, **kwargs):
        raise web_fetch.urllib.error.URLError("refused")
    monkeypatch.setattr(web_fetch.urllib.request, "urlopen", unavailable)
    async def fetch(client, url):
        return b"<html>raw</html>", url, "text/html"
    monkeypatch.setattr(extraction, "fetch_page", fetch)
    monkeypatch.setattr(extraction, "extract_content", lambda *args: "Readable title")
    assert web_fetch.get_url("https://example.com") == ("Readable title", None)


def test_cli_does_not_bypass_service_rejection(monkeypatch):
    def denied(*args, **kwargs):
        raise web_fetch.urllib.error.HTTPError("url", 422, "invalid", {}, None)
    monkeypatch.setattr(web_fetch.urllib.request, "urlopen", denied)
    assert "422" in web_fetch.get_url("file:///etc/passwd")[1]


def test_real_html_extraction():
    html = "<html><body><article><h1>Useful title</h1>" + "<p>This is a substantial paragraph with useful details for extraction and testing.</p>" * 8 + "</article></body></html>"
    content = extraction.extract_content(html, "https://example.com")
    assert "Useful title" in content
    assert "substantial paragraph" in content
    assert "\x01" not in content


def _listing_html(count=10):
    entries = "".join(
        f'<h2><a href="https://example.com/{i}">owner / repo{i}</a></h2><p>Description number {i}.</p>'
        for i in range(count)
    )
    return f"<html><body><main>{entries}</main></body></html>"


def test_link_preserving_fallback_on_listing(monkeypatch):
    """Trafilatura drops every link on a link-dense listing -> keep the entry links."""
    monkeypatch.setattr(extraction.trafilatura, "extract", lambda *a, **k: "prose with no links at all")
    content = extraction.extract_content(_listing_html(), "https://example.com")
    assert "](https://example.com/0)" in content
    assert "owner / repo0" in content


def test_no_link_fallback_when_trafilatura_kept_links(monkeypatch):
    monkeypatch.setattr(extraction.trafilatura, "extract", lambda *a, **k: "prose with a [link](https://kept.example)")
    assert extraction.extract_content(_listing_html(), "https://example.com") == "prose with a [link](https://kept.example)"


def test_no_link_fallback_when_page_is_link_sparse(monkeypatch):
    html = "<html><body><main><h2><a href='https://example.com/0'>only entry</a></h2><p>text</p></main></body></html>"
    monkeypatch.setattr(extraction.trafilatura, "extract", lambda *a, **k: "prose with no links")
    assert extraction.extract_content(html, "https://example.com") == "prose with no links"


def test_link_fallback_skipped_for_non_markdown(monkeypatch):
    monkeypatch.setattr(extraction.trafilatura, "extract", lambda *a, **k: "plain text no links")
    assert extraction.extract_content(_listing_html(), "https://example.com", output_format="txt") == "plain text no links"


def test_extract_title_from_metadata():
    html = "<html><head><title>My Page Title</title></head><body><article><p>" + "Useful sentence. " * 30 + "</p></article></body></html>"
    assert extraction.extract_title(html, "https://example.com") == "My Page Title"


def test_extract_title_missing_returns_empty():
    assert extraction.extract_title("<html><body><p>x</p></body></html>", "https://example.com") == ""


def test_server_populates_title(monkeypatch):
    html = ("<html><head><title>Service Title</title></head><body><article><p>"
            + "Useful sentence. " * 30 + "</p></article></body></html>").encode()
    async def fetch(client, url):
        return html, url, "text/html"
    monkeypatch.setattr(server, "fetch_page", fetch)
    with TestClient(server.app) as client:
        result = client.post("/extract", json={"urls": ["https://example.com"]}).json()["results"][0]
    assert result["title"] == "Service Title"
    assert "Useful sentence." in result["content"]


def test_request_body_limit():
    with TestClient(server.app) as client:
        assert client.post("/extract", content=b"x" * 256001).status_code == 413


def test_queue_overload():
    with TestClient(server.app) as client:
        server.app.state.pending = 64
        assert client.post("/extract", json={"urls": ["https://example.com"]}).status_code == 503
        assert server.app.state.pending == 64


async def test_origin_pools_do_not_share_tls(monkeypatch):
    instances = []
    class FakeTransport:
        def __init__(self, **kwargs):
            instances.append(self)
        async def handle_async_request(self, request):
            return httpx.Response(200, content=b"ok")
        async def aclose(self):
            pass
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", FakeTransport)
    transport = extraction.OriginTransport()
    for host in ("one.example", "two.example", "one.example"):
        await transport.handle_async_request(httpx.Request("GET", "https://93.184.216.34", headers={"Host": host}))
    assert len(instances) == 2
    await transport.aclose()


async def test_compressed_response_rejected(public_dns, monkeypatch):
    import gzip
    monkeypatch.setattr(extraction, "MAX_BYTES", 100)
    def response(_):
        return httpx.Response(200, headers={"content-type": "text/html", "content-encoding": "gzip"}, content=gzip.compress(b"a" * 1000))
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        with pytest.raises(extraction.ExtractionError, match="Compressed"):
            await extraction.fetch_page(client, "https://example.com")


async def test_extraction_does_not_block_health(monkeypatch):
    import threading
    entered = threading.Event()
    release = threading.Event()
    async def fetch(client, url):
        return b"html", url, "text/html"
    def slow_extract(*args):
        entered.set()
        assert release.wait(2)
        return "content"
    monkeypatch.setattr(server, "fetch_page", fetch)
    monkeypatch.setattr(server, "extract_content", slow_extract)
    async with server.lifespan(server.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            job = asyncio.create_task(client.post("/extract", json={"urls": ["https://example.com"]}))
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                response = await asyncio.wait_for(client.get("/health"), timeout=0.5)
                assert response.status_code == 200
            finally:
                release.set()
                await job
