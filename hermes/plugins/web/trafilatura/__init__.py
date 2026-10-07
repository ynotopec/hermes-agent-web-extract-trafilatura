"""Trafilatura-Local extract plugin for Hermes Agent — auto-loaded."""
from __future__ import annotations

from .provider import TrafilaturaLocalProvider


def register(ctx) -> None:
    ctx.register_web_search_provider(TrafilaturaLocalProvider())
