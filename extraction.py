"""Bounded HTTP(S) fetching and content extraction shared by API and CLI."""
import asyncio
import ipaddress
import os
import socket
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura

MAX_BYTES = int(os.getenv("MAX_BYTES", "5000000"))
FETCH_TIMEOUT = float(os.getenv("FETCH_TIMEOUT", "30"))
MAX_REDIRECTS = 5
FORMATS = ("markdown", "txt", "html")


class ExtractionError(ValueError):
    pass


async def public_target(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ExtractionError("Only HTTP(S) URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise ExtractionError("URL credentials are not allowed")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = await asyncio.get_running_loop().getaddrinfo(
            parsed.hostname, port, type=socket.SOCK_STREAM
        )
    except (ValueError, OSError) as exc:
        raise ExtractionError("Invalid or unresolvable destination") from exc
    ips = [ipaddress.ip_address(item[4][0]) for item in addresses]
    if not ips or any(
        not ip.is_global or ip.is_multicast or
        (isinstance(ip, ipaddress.IPv6Address) and (ip.sixtofour is not None or ip.teredo is not None))
        for ip in ips
    ):
        raise ExtractionError("Non-public destinations are not allowed")
    # Pin the validated address: no second DNS lookup at connection time.
    target = httpx.URL(url).copy_with(host=str(ips[0]))
    original = httpx.URL(url)
    return target, original.netloc.decode("ascii"), original.host


class OriginTransport(httpx.AsyncBaseTransport):
    """Keep TLS pools separate even when distinct hostnames share one IP."""
    def __init__(self):
        self.transports = {}

    async def handle_async_request(self, request):
        key = (request.url.scheme, request.headers["host"])
        transport = self.transports.get(key)
        temporary = False
        if transport is None:
            transport = httpx.AsyncHTTPTransport(
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=2),
                trust_env=False,
            )
            if len(self.transports) < 32:
                self.transports[key] = transport
            else:
                temporary = True
        try:
            response = await transport.handle_async_request(request)
        except BaseException:
            if temporary:
                await transport.aclose()
            raise
        if temporary:
            response.stream = ClosingStream(response.stream, transport)
        return response

    async def aclose(self):
        await asyncio.gather(*(transport.aclose() for transport in self.transports.values()))


class ClosingStream(httpx.AsyncByteStream):
    def __init__(self, stream, transport):
        self.stream, self.transport = stream, transport

    async def __aiter__(self):
        async for chunk in self.stream:
            yield chunk

    async def aclose(self):
        try:
            await self.stream.aclose()
        finally:
            await self.transport.aclose()


def make_client():
    return httpx.AsyncClient(
        timeout=httpx.Timeout(FETCH_TIMEOUT, connect=10),
        transport=OriginTransport(),
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
        headers={"User-Agent": "Trafilatura-Local/0.2", "Accept": "text/html,application/xhtml+xml,text/plain", "Accept-Encoding": "identity"},
    )


async def fetch_page(client, url):
    async def download():
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            target, host, sni = await public_target(current)
            async with client.stream(
                "GET", target, headers={"Host": host},
                extensions={"sni_hostname": sni},
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise ExtractionError("Redirect without a destination")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if mime not in ("text/html", "application/xhtml+xml", "text/plain"):
                    raise ExtractionError("Unsupported content type")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ExtractionError("Compressed responses are not supported")
                length = response.headers.get("content-length")
                if length:
                    try:
                        if int(length) > MAX_BYTES:
                            raise ExtractionError("Page exceeds download limit")
                    except ValueError as exc:
                        if isinstance(exc, ExtractionError):
                            raise
                        raise ExtractionError("Invalid Content-Length") from exc
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(body) + len(chunk) > MAX_BYTES:
                        raise ExtractionError("Page exceeds download limit")
                    body.extend(chunk)
                if mime == "text/plain":
                    text = bytes(body).decode(response.encoding or "utf-8", errors="replace")
                else:
                    text = bytes(body)  # Let Trafilatura detect HTML encoding.
                return text, current, mime
        raise ExtractionError("Too many redirects")

    try:
        return await asyncio.wait_for(download(), timeout=FETCH_TIMEOUT)
    except (asyncio.TimeoutError, httpx.HTTPError) as exc:
        raise ExtractionError("Page download failed or timed out") from exc


def extract_content(document, url, output_format="markdown"):
    if output_format not in FORMATS:
        raise ExtractionError("Unsupported output format")
    for options in ({"favor_precision": True}, {"favor_recall": True}):
        content = trafilatura.extract(
            document, url=url, output_format=output_format,
            include_comments=False, include_tables=True, include_links=True,
            **options,
        )
        if content and content.strip():
            return content.strip()
    raise ExtractionError("No extractable content found")
