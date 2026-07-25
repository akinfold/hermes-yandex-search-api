"""Yandex Search API plugin for Hermes Agent.

Registers two capabilities:

* ``yandex`` web-search backend provider (classic web results) — activate with
  ``web.search_backend: yandex`` in ``~/.hermes/config.yaml``.
* ``yandex_generative_search`` standalone tool (grounded answer with citations).

Hermes calls :func:`register` with a ``PluginContext`` at load time.
"""

from __future__ import annotations

from typing import Any

from . import generative
from .client import (
    GenerativeAnswer,
    GenerativeSource,
    WebResult,
    YandexSearchClient,
    YandexSearchError,
)
from .provider import YandexWebSearchProvider

__version__ = "0.1.0"

__all__ = [
    "GenerativeAnswer",
    "GenerativeSource",
    "WebResult",
    "YandexSearchClient",
    "YandexSearchError",
    "YandexWebSearchProvider",
    "__version__",
    "register",
]


def register(ctx: Any) -> None:
    """Register the Yandex provider and tool with the Hermes plugin context."""
    ctx.register_web_search_provider(YandexWebSearchProvider())
    ctx.register_tool(
        name=generative.TOOL_NAME,
        toolset=generative.TOOLSET,
        schema=generative.SCHEMA,
        handler=generative.handle_generative_search,
        requires_env=["YANDEX_API_KEY", "YANDEX_FOLDER_ID"],
        description="Grounded answer with citations via Yandex generative search.",
        emoji="🔎",
    )
