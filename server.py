#!/usr/bin/env python3
"""Trafilatura-local server — HTTP service for web content extraction."""

import sys
import os
import logging
import time
import asyncio
from typing import Optional, List
from pathlib import Path

import httpx
import trafilatura
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Setup logging
LOG_DIR = Path.home() / ".hermes" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "trafilatura_local.log"),
    ],
)
logger = logging.getLogger("trafilatura_local")

# Configuration
PORT = int(os.environ.get("PORT", "8990"))
HOST = os.environ.get("HOST", "127.0.0.1")
MAX_CHARS = int(os.environ.get("MAX_CHARS", "200000"))

app = FastAPI(title="Trafilatura-Local", version="0.1.0")


class ExtractRequest(BaseModel):
    urls: List[str]
    format: str = Field(default="markdown", description="Output format: markdown, txt, html")
    max_chars: Optional[int] = Field(default=200000, description="Max characters per page")


class ExtractResult(BaseModel):
    url: str
    title: str = ""
    content: str = ""
    error: Optional[str] = None
    metadata: dict = {}


async def fetch_page(url: str) -> Optional[str]:
    """Fetch a page's HTML content."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None


def extract_content(html: str, url: str, output_format: str = "markdown") -> Optional[str]:
    """Extract content using trafilatura with fallback strategies."""
    try:
        # Strategy 1: Default extraction (favor precision)
        content = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            favor_precision=True,
            output_format=output_format,
        )
        if content and len(content.strip()) > 10:
            return content.strip()
    except Exception as e:
        logger.warning(f"Strategy 1 failed for {url}: {e}")

    try:
        # Strategy 2: With table extraction (favor recall)
        content = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
            output_format=output_format,
        )
        if content and len(content.strip()) > 10:
            return content.strip()
    except Exception as e:
        logger.warning(f"Strategy 2 failed for {url}: {e}")

    return None


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "trafilatura-local",
        "version": "0.1.0",
        "dependencies": {
            "trafilatura": trafilatura.__version__ if hasattr(trafilatura, "__version__") else "installed",
        }
    }


@app.post("/extract")
async def extract(request: ExtractRequest):
    """Extract content from multiple URLs concurrently."""
    results = []

    async def process_url(url: str):
        start = time.time()

        # Fetch HTML
        html = await fetch_page(url)
        if not html:
            results.append(ExtractResult(
                url=url,
                error="Failed to fetch page"
            ))
            return

        # Extract content
        content = extract_content(html, url, request.format)
        if not content:
            results.append(ExtractResult(
                url=url,
                error="No extractable content found"
            ))
            return

        # Truncate if needed
        if request.max_chars and len(content) > request.max_chars:
            content = content[:request.max_chars]

        elapsed = time.time() - start

        results.append(ExtractResult(
            url=url,
            content=content,
            metadata={
                "extractor": "trafilatura",
                "format": request.format,
                "response_time_ms": round(elapsed * 1000, 2),
            }
        ))

    # Process all URLs concurrently
    await asyncio.gather(*[process_url(url) for url in request.urls])

    return {"results": [r.model_dump() for r in results]}


if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting Trafilatura-Local server on {HOST}:{PORT}")
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        access_log=False,
        timeout_keep_alive=30,
    )
