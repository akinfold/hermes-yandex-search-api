"""Standalone ``yandex_generative_search`` tool for Hermes Agent.

Unlike classic web search (a list of links), Yandex generative search returns a
single grounded answer synthesised from web sources, with citations. That is a
different result shape, so it is exposed as its own tool rather than through the
``web_search`` backend.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from . import config
from .client import YandexSearchError

logger = logging.getLogger(__name__)

TOOL_NAME = "yandex_generative_search"
TOOLSET = "yandex_search"

SCHEMA: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Answer a question using Yandex generative search. Returns a concise, "
        "grounded answer synthesised from live web sources, together with the "
        "source URLs it cites. Prefer this over plain web search when you want a "
        "direct answer to a factual question rather than a list of links."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The question to answer.",
            },
            "sites": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of up to 5 site domains to restrict the "
                    'answer\'s sources to (e.g. ["example.com"]).'
                ),
            },
        },
        "required": ["query"],
    },
}


def handle_generative_search(args: dict[str, Any], **_kwargs: Any) -> str:
    """Tool handler: run a generative search and return a JSON string.

    Never raises: every failure is returned as ``{"success": False, "error": ...}``
    so a bad request cannot break the agent loop.
    """
    try:
        query = (args or {}).get("query", "")
        if not isinstance(query, str) or not query.strip():
            return _error("query is required and must be a non-empty string")

        sites = args.get("sites") or None
        if sites is not None and not isinstance(sites, list):
            return _error("sites must be an array of domain strings")

        try:
            client = config.build_client()
        except ValueError as exc:
            return _error(str(exc))

        with client:
            answer = client.generative_search(query=query, sites=sites)

        return json.dumps(
            {
                "success": True,
                "answer": answer.text,
                "sources": [
                    {"url": s.url, "title": s.title, "used_text": s.used_text}
                    for s in answer.sources
                ],
                "search_queries": answer.search_queries,
                "fixed_query": answer.fixed_query,
                "is_answer_rejected": answer.is_answer_rejected,
                "is_bullet_answer": answer.is_bullet_answer,
            },
            ensure_ascii=False,
        )
    except YandexSearchError as exc:
        logger.warning("Yandex generative search error: %s", exc)
        return _error(str(exc))
    except Exception as exc:
        logger.warning("Yandex generative search failed: %s", exc)
        return _error(f"Yandex generative search failed: {exc}")


def _error(message: str) -> str:
    return json.dumps({"success": False, "error": message})
