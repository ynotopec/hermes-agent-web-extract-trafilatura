#!/usr/bin/env python3
"""Local, bounded web extraction API."""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import trafilatura

from extraction import ExtractionError, extract_content, fetch_page, make_client

MAX_CHARS = int(os.getenv("MAX_CHARS", "200000"))
MAX_URLS = 20
CONCURRENCY = int(os.getenv("CONCURRENCY", "4"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    app.state.pending = 0
    app.state.slots = asyncio.Semaphore(CONCURRENCY)
    async with make_client() as client:
        app.state.client = client
        yield


class BodyLimitMiddleware:
    """Bound JSON buffering, including requests without Content-Length."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        messages = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 256000:
                return await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
            messages.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            if messages:
                return messages.pop(0)
            return await receive()
        await self.app(scope, replay, send)


app = FastAPI(title="Trafilatura-Local", version="0.2.0", lifespan=lifespan)
app.add_middleware(BodyLimitMiddleware)


class ExtractRequest(BaseModel):
    urls: list[Annotated[str, Field(min_length=1, max_length=8192)]] = Field(min_length=1, max_length=MAX_URLS)
    format: Literal["markdown", "txt", "html"] = "markdown"
    max_chars: int = Field(default=MAX_CHARS, ge=1, le=MAX_CHARS)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "trafilatura-local", "version": "0.2.0",
            "dependencies": {"trafilatura": trafilatura.__version__}}


@app.post("/extract")
async def extract(payload: ExtractRequest, request: Request):
    async def process(url):
        start = time.perf_counter()
        result = {"url": url, "title": "", "content": "", "error": None, "metadata": {}}
        try:
            async with request.app.state.slots:
                document, final_url, mime = await fetch_page(request.app.state.client, url)
                content = (document.strip() if mime == "text/plain" else
                           await asyncio.to_thread(extract_content, document, final_url, payload.format))
                result["content"] = content[:payload.max_chars]
                result["metadata"] = {
                    "extractor": "plain" if mime == "text/plain" else "trafilatura",
                    "format": "txt" if mime == "text/plain" else payload.format,
                    "final_url": final_url, "truncated": len(content) > payload.max_chars,
                }
        except ExtractionError as exc:
            result["error"] = str(exc)
        except Exception:
            logger.exception("Content extraction failed")
            result["error"] = "Content extraction failed"
        result["metadata"]["response_time_ms"] = round((time.perf_counter() - start) * 1000, 2)
        return result

    # Reject overload rather than accumulating unlimited queued fetches.
    if request.app.state.pending + len(payload.urls) > 64:
        return JSONResponse({"detail": "Extraction queue is full"}, status_code=503)
    request.app.state.pending += len(payload.urls)
    try:
        return {"results": await asyncio.gather(*(process(url) for url in payload.urls))}
    finally:
        request.app.state.pending -= len(payload.urls)


@app.get("/extract")
async def extract_get(request: Request, url: str = Query(max_length=8192)):
    return await extract(ExtractRequest(urls=[url]), request)


def main():
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"),
                port=int(os.getenv("PORT", "8990")), access_log=False)


if __name__ == "__main__":
    main()
