"""Bounded HTTP(S) fetching and content extraction shared by API and CLI."""
import asyncio
import ipaddress
import os
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura

MAX_BYTES = int(os.getenv("MAX_BYTES", "5000000"))
FETCH_TIMEOUT = float(os.getenv("FETCH_TIMEOUT", "30"))
MAX_REDIRECTS = 5
FORMATS = ("markdown", "txt", "html")

# Trafilatura's main-content heuristic can classify the anchor/heading markup that
# carries the actual data on directory pages (dashboards, "trending"/index listings)
# as boilerplate: it returns the surrounding prose with every link dropped, silently
# losing the entry names. When that happens on a link-dense page the main region is
# re-extracted keeping its links and headings.
_MARKDOWN_LINK_RE = re.compile(r"\]\(https?://")
_MIN_ANCHORS_FOR_LINK_FALLBACK = 8
_SKIP_TAGS = ("script", "style", "noscript", "template", "svg", "form", "header", "footer", "nav", "aside")
_HEADING_LEVELS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}
_BLOCK_LEAF_TAGS = ("p", "blockquote", "figcaption", "dt", "dd", "pre", "td", "th")


def _collapse_whitespace(text):
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n+", " ", text)).strip()


def _prepare_tree(document):
    """Parse *document* with lxml and drop chrome that is pure navigation noise."""
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(document)
    for tag in _SKIP_TAGS:
        for element in list(tree.iter(tag)):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
    return tree


def _main_region(tree):
    main = tree.find(".//main")
    if main is not None:
        return main
    return tree.body if tree.body is not None else tree


def _count_main_anchors(tree, base_url):
    """Number of web anchors inside the main region (relative hrefs resolved)."""
    count = 0
    for anchor in _main_region(tree).iter("a"):
        if urljoin(base_url, anchor.get("href") or "").startswith(("http://", "https://")):
            count += 1
    return count


def _render_inline(element, base_url):
    parts = []
    if element.text:
        parts.append(element.text)
    for child in element:
        tag = child.tag.lower() if isinstance(child.tag, str) else ""
        inner = _render_inline(child, base_url)
        if tag == "a" and inner.strip():
            href = urljoin(base_url, child.get("href") or "")
            parts.append(f"[{_collapse_whitespace(inner)}]({href})"
                         if href.startswith(("http://", "https://")) else inner)
        elif tag in ("strong", "b") and inner.strip():
            parts.append(f"**{inner.strip()}**")
        elif tag in ("em", "i") and inner.strip():
            parts.append(f"*{inner.strip()}*")
        elif tag == "br":
            parts.append(" ")
        else:
            parts.append(inner)
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _render_block(element, out, base_url):
    tag = element.tag.lower() if isinstance(element.tag, str) else ""
    if tag in _HEADING_LEVELS:
        text = _collapse_whitespace(_render_inline(element, base_url))
        if text:
            out.append(f"{_HEADING_LEVELS[tag]} {text}")
        return
    if tag == "li":
        text = _collapse_whitespace(_render_inline(element, base_url))
        if text:
            out.append(f"- {text}")
        return
    if tag in _BLOCK_LEAF_TAGS:
        text = _collapse_whitespace(_render_inline(element, base_url))
        if text:
            out.append(text)
        return
    for child in element:
        if isinstance(child.tag, str):
            _render_block(child, out, base_url)


def _render_link_preserving(tree, base_url):
    """Minimal HTML->markdown over the main region, keeping headings, list items and
    anchors. Only used when Trafilatura dropped every link (see ``extract_content``)."""
    out = []
    _render_block(_main_region(tree), out, base_url)
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(out)).strip()


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
    content = ""
    for options in ({"favor_precision": True}, {"favor_recall": True}):
        extracted = trafilatura.extract(
            document, url=url, output_format=output_format,
            include_comments=False, include_tables=True, include_links=True,
            **options,
        )
        if extracted and extracted.strip():
            content = extracted.strip()
            break
    if not content:
        raise ExtractionError("No extractable content found")
    if output_format == "markdown" and not _MARKDOWN_LINK_RE.search(content):
        # Trafilatura dropped every link: on a link-dense page it mistook the entry
        # markup for boilerplate and kept only the surrounding prose, losing the
        # entry names (e.g. GitHub Trending keeps descriptions but not owner/repo).
        tree = _prepare_tree(document)
        if _count_main_anchors(tree, url) >= _MIN_ANCHORS_FOR_LINK_FALLBACK:
            linked = _render_link_preserving(tree, url)
            if _MARKDOWN_LINK_RE.search(linked):
                return linked
    return content


def extract_title(document, url):
    """Best-effort page title from Trafilatura metadata; ``""`` when unavailable."""
    try:
        metadata = trafilatura.extract_metadata(document, default_url=url)
    except Exception:
        return ""
    title = getattr(metadata, "title", None) if metadata is not None else None
    return _collapse_whitespace(title) if title else ""
