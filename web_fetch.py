#!/usr/bin/env python3
"""web_fetch.py — Fetch URL and extract readable text.

Uses local Trafilatura HTTP service (port 8990) with regex fallback.
No API keys needed.

Usage: python3 web_fetch.py <url> [--format plain|markdown] [--limit 15000]
"""
import sys
import re
import os
import json
import subprocess
from html import unescape


def fetch_via_trafilatura(url):
    """Fetch URL via local Trafilatura HTTP service (port 8990)."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"http://localhost:8990/extract",
            data=json.dumps({"urls": [url], "format": "markdown"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=35) as resp:
            data = json.loads(resp.read().decode())
            results = data.get("results", [])
            if not results:
                return None, "No result from trafilatura"
            r = results[0]
            if r.get("error"):
                return None, f"Trafilatura error: {r['error']}"
            return r.get("content"), None
    except urllib.error.URLError as e:
        return None, f"Trafilatura service unavailable: {e}"
    except Exception as e:
        return None, f"Trafilatura fetch failed: {e}"


def fetch_via_curl(url):
    """Fallback: curl + regex-based extraction."""
    try:
        result = subprocess.run(
            ["curl", "-sL", "-m", "30", "--max-filesize", "5M", "-A",
             "Mozilla/5.0 (compatible; HermesBot/1.0)", url],
            capture_output=True, text=True, timeout=35
        )
        if result.returncode != 0:
            return None, f"curl failed (exit {result.returncode}): {result.stderr[:200]}"
        return result.stdout, None
    except FileNotFoundError:
        return None, "curl not found"
    except subprocess.TimeoutExpired:
        return None, "curl timed out (30s)"


def get_url(url):
    """Try Trafilatura service first, then curl regex fallback."""
    text, err = fetch_via_trafilatura(url)
    if text is not None:
        return text, err
    # Fallback to curl
    return fetch_via_curl(url)


def clean_html(html):
    """Strip non-content tags and extract readable text (regex fallback)."""
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<meta[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<link[^>]*>', '', html, flags=re.IGNORECASE)
    for tag in ['nav', 'header', 'footer', 'aside', 'form', 'noscript', 'iframe',
                'object', 'embed', 'applet', 'video', 'audio', 'source', 'picture']:
        html = re.sub(r'</?' + tag + r'[^>]*>', '', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'\s+((?:class|style|data-[^\s=]+|aria-[^\s=]+|role|x-[^=]+))\s*=\s*"[^"]*"', '', html, flags=re.IGNORECASE)
    best = None
    best_len = 0
    for m in re.finditer(r'<(div|section|article|main|td)[^>]*>(.*?)</\1>', html, re.DOTALL | re.IGNORECASE):
        tag = m.group(1)
        body = m.group(2)
        para_count = len(re.findall(r'<p[^>]*>', body, re.IGNORECASE))
        text_len = len(re.sub(r'<[^>]+>', '', body))
        classes = re.findall(r'class="([^"]*)"', m.group(0))
        penalty = sum(1 for c in classes if any(kw in c.lower() for kw in
                    ['sidebar', 'nav', 'menu', 'widget', 'ad', 'banner', 'cookie',
                     'comment', 'related', 'share', 'social', 'toc']))
        if para_count >= 2 and text_len > best_len - penalty * 3000:
            best_len = text_len
            best = body
    if best is None:
        text = re.sub(r'<[^>]+>', ' ', html)
    else:
        text = best
    text = _to_markdown(text)
    text = unescape(text)
    lines = [line.strip() for line in text.split('\n')]
    out = []
    prev_blank = False
    for line in lines:
        if line:
            out.append(line)
            prev_blank = False
        else:
            if not prev_blank:
                out.append('')
            prev_blank = True
    return '\n'.join(out).strip()


def _to_markdown(text):
    """Convert HTML fragments to markdown-like text."""
    for i in range(1, 7):
        text = re.sub(rf'<h{i}[^>]*>(.*?)</h{i}>',
                      f'\n{"#" * i} \1\n\n', text, flags=re.DOTALL)
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                  r'[\2](\1)', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<(strong|b)[^>]*>(.*?)</\1>', r'**\2**', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<(em|i)[^>]*>(.*?)</\1>', r'*\2*', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<li[^>]*>\s*', '- ', text, flags=re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?p[^>]*>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?div[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?span[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?section[^>]*>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<blockquote[^>]*>', '\n> ', text, flags=re.IGNORECASE)
    text = re.sub(r'</blockquote>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<pre[^>]*>(.*?)</pre>', r'\n```\n\1\n```\n', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return text


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch URL and extract readable text")
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument("--format", choices=["plain", "markdown"], default="markdown",
                       help="Output format (default: markdown)")
    parser.add_argument("--limit", type=int, default=15000, help="Max characters (default: 15000)")
    args = parser.parse_args()

    text, err = get_url(args.url)
    if text is None or not text.strip():
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # Use local regex only if trafilatura failed
    if err and "Trafilatura service unavailable" in err:
        print(f"Warning: Trafilatura unavailable, using local regex extraction: {err}", file=sys.stderr)
        text, _ = get_url(args.url)  # retry with curl fallback
        if text is None:
            print(f"Error: {err}", file=sys.stderr)
            sys.exit(1)
        content = clean_html(text)
    else:
        content = text

    if args.format == "plain":
        content = re.sub(r'\*\*(.*?)\*\*', r'\1', content)
        content = re.sub(r'\*(.*?)\*', r'\1', content)
        content = re.sub(r'^#{1,6}\s', '', content, flags=re.MULTILINE)
        content = re.sub(r'^>\s?', '', content, flags=re.MULTILINE)

    if len(content) > args.limit:
        content = content[:args.limit] + "\n\n[... truncated ...]"

    print(content)


if __name__ == "__main__":
    main()
