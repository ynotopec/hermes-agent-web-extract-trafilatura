#!/usr/bin/env python3
"""Fetch readable content through the service, or the same safe local extractor."""
import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

SERVICE_URL = (os.getenv("TRAFILATURA_URL") or "http://127.0.0.1:8990").rstrip("/")


def get_url(url, output_format="markdown", limit=15000):
    req = urllib.request.Request(
        f"{SERVICE_URL}/extract",
        data=json.dumps({"urls": [url], "format": output_format, "max_chars": limit}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            result = json.load(response)["results"][0]
            return result["content"], result.get("error")
    except urllib.error.HTTPError as exc:
        return None, f"Extraction service rejected request: HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        # No curl bypass: the fallback uses identical URL and resource controls.
        from extraction import ExtractionError, extract_content, fetch_page, make_client

        async def fallback():
            async with make_client() as client:
                document, final_url, mime = await fetch_page(client, url)
                content = (document.strip() if mime == "text/plain" else
                           await asyncio.to_thread(extract_content, document, final_url, output_format))
                return content[:limit], None
        try:
            return asyncio.run(fallback())
        except ExtractionError as exc:
            return None, str(exc)
    except (ValueError, KeyError, IndexError) as exc:
        return None, f"Invalid service response: {exc}"


def main():
    parser = argparse.ArgumentParser(description="Fetch readable web content")
    parser.add_argument("url")
    parser.add_argument("--format", choices=["plain", "markdown"], default="markdown")
    parser.add_argument("--limit", type=int, default=15000)
    args = parser.parse_args()
    if not 1 <= args.limit <= 200000:
        parser.error("--limit must be between 1 and 200000")
    content, error = get_url(args.url, "txt" if args.format == "plain" else "markdown", args.limit)
    if error or not content:
        print(f"Error: {error or 'No extractable content'}", file=sys.stderr)
        raise SystemExit(1)
    print(content)


if __name__ == "__main__":
    main()
