"""Yandex web-search backend provider for Hermes Agent.

Plugs into Hermes' built-in ``web_search`` tool: when the user selects
``web.search_backend: yandex`` in ``~/.hermes/config.yaml``, every
``web_search`` call is routed to :meth:`YandexWebSearchProvider.search`.
"""

from __future__ import annotations

import logging
from typing import Any

from . import config
from ._compat import WebSearchProvider
from .client import YandexSearchError

logger = logging.getLogger(__name__)

PROVIDER_NAME = "yandex"


class YandexWebSearchProvider(WebSearchProvider):
    """Web-search backend backed by the Yandex Search API (classic web results)."""

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def display_name(self) -> str:
        return "Yandex"

    def is_available(self) -> bool:
        """True when both credentials are configured (no network call)."""
        return config.credentials_present()

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        # Yandex Search API returns result snippets, not full page content.
        return False

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Execute a web search and return the Hermes web-results envelope.

        Per the Hermes provider contract this must never raise: every failure
        path returns ``{"success": False, "error": ...}``.
        """
        try:
            client = config.build_client()
            with client:
                results = client.web_search(query, n_results=limit)
            web = [
                {
                    "title": r.title,
                    "url": r.url,
                    "description": r.description,
                    "position": r.position,
                }
                for r in results
            ]
            return {"success": True, "data": {"web": web}}
        except (YandexSearchError, ValueError) as exc:
            logger.warning("Yandex web search error: %s", exc)
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("Yandex web search failed: %s", exc)
            return {"success": False, "error": f"Yandex search failed: {exc}"}

    def get_setup_schema(self) -> dict[str, Any]:
        return {
            "name": "Yandex",
            "badge": "paid",
            "tag": "Yandex Search API (web + generative).",
            "env_vars": [
                {
                    "key": config.API_KEY_ENV,
                    "prompt": "Yandex Cloud API key",
                    "url": "https://aistudio.yandex.ru/docs/ru/search-api/quickstart",
                },
                {
                    "key": config.FOLDER_ID_ENV,
                    "prompt": "Yandex Cloud folder id",
                    "url": "https://yandex.cloud/docs/resource-manager/operations/folder/get-id",
                },
            ],
        }
