"""Trafilatura-Local web extraction provider for Hermes Agent.

Wraps the local HTTP service (:8990) as a Hermes web-extract backend. Static
HTML only: no JavaScript rendering, PDFs, or anti-bot bypasses.

Config: ``web.extract_backend: trafilatura``. No API key. Service URL via
``TRAFILATURA_URL`` (default ``http://127.0.0.1:8990``).

Resilience: a URL the local service returns empty (or errors on) falls back to
the Firecrawl keyless cloud extractor, so JS-heavy / blocked pages do not come
back "thin".
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from agent.web_search_provider import WebSearchProvider, get_provider_env

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://127.0.0.1:8990"
_TIMEOUT_S = 60.0


def _base_url() -> str:
    try:
        val = get_provider_env("TRAFILATURA_URL")
    except Exception:  # noqa: BLE001 — config layer optional
        val = ""
    return (val or os.getenv("TRAFILATURA_URL") or _DEFAULT_URL).rstrip("/") or _DEFAULT_URL


def _page(url: str, title: str, content: str, *, error: Optional[str] = None, source_url: Optional[str] = None) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "url": url,
        "title": title,
        "content": content,
        "raw_content": content,
        "metadata": {"sourceURL": source_url or url, "title": title},
    }
    if error:
        entry["error"] = error
    return entry


class TrafilaturaLocalProvider(WebSearchProvider):
    """Local Trafilatura extraction service (extract-only, no credential)."""

    NAME = "trafilatura"
    DISPLAY_NAME = "Trafilatura (local)"

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    def is_available(self) -> bool:
        # Local service, no credential; the deployment provides it. Cheap, no network.
        return True

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    async def _extract_local(self, urls: List[str], fmt: str) -> List[Dict[str, Any]]:
        base = _base_url()
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
                resp = await client.post(f"{base}/extract", json={"urls": list(urls), "format": fmt})
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001 — per-URL error contract, never raise
            logger.warning("trafilatura-local unreachable at %s: %s", base, exc)
            return [
                _page(u, "", "", error=(
                    f"Trafilatura-Local service unreachable at {base} ({exc}). "
                    "Start it with `systemctl --user start trafilatura-local.service`."
                ))
                for u in urls
            ]
        by_url: Dict[str, Dict[str, Any]] = {}
        for r in data.get("results") or []:
            u = r.get("url") or ""
            meta = r.get("metadata") if isinstance(r.get("metadata"), dict) else {}
            by_url[u] = _page(
                u, r.get("title") or "", r.get("content") or "",
                error=r.get("error"), source_url=meta.get("final_url") or u,
            )
        return [by_url.get(u, _page(u, "", "", error="no content returned")) for u in urls]

    async def _firecrawl_fallback(self, urls: List[str]) -> Dict[str, Dict[str, Any]]:
        try:
            from plugins.web.keyless_mcp import firecrawl_extract_keyless

            rows = await asyncio.to_thread(firecrawl_extract_keyless, list(urls))
        except Exception as exc:  # noqa: BLE001 — fallback must never break the call
            logger.debug("trafilatura firecrawl fallback unavailable: %s", exc)
            return {}
        return {r.get("url", ""): r for r in rows if (r.get("content") or "").strip()}

    async def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        fmt = kwargs.get("format") or "markdown"
        results = await self._extract_local(list(urls), fmt)
        empty = [r["url"] for r in results if not (r.get("content") or "").strip() and r.get("url")]
        if empty:
            fallback = await self._firecrawl_fallback(empty)
            if fallback:
                logger.info("trafilatura: %d URL(s) empty, served %d via firecrawl fallback", len(empty), len(fallback))
                results = [fallback.get(r["url"], r) for r in results]
        return results

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": self.DISPLAY_NAME,
            "badge": "local · no key",
            "tag": "Local Trafilatura extraction service (127.0.0.1:8990). No API key, no rate limits; "
                   "static HTML only, with a Firecrawl cloud fallback for JS-heavy pages.",
            "env_vars": [{"key": "TRAFILATURA_URL", "prompt": "Trafilatura-Local service URL", "url": ""}],
        }
