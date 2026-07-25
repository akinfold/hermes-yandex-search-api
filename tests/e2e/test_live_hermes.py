"""End-to-end test of the plugin loaded into a live Hermes Agent host.

This exercises the real Hermes integration boundary: the provider is registered
through Hermes' actual ``web_search_registry`` and routed by ``name``, then run
against the live Yandex Search API — and the standalone generative tool is run
through its registered handler. It does NOT drive a full LLM agent loop (that
needs model credentials and is non-deterministic); it verifies that everything
the agent would call is wired correctly and returns the contracted shapes.

Run with:  pytest -m e2e
Requires ``hermes-agent`` installed and live Yandex credentials.
"""

from __future__ import annotations

import json

import pytest
from hermes_yandex_search import generative
from hermes_yandex_search._compat import HERMES_AVAILABLE
from hermes_yandex_search.provider import YandexWebSearchProvider

pytestmark = pytest.mark.e2e

if not HERMES_AVAILABLE:
    pytest.skip("hermes-agent is not installed", allow_module_level=True)


def test_provider_is_a_valid_hermes_provider() -> None:
    """The provider must subclass Hermes' real ABC so registration accepts it."""
    from agent.web_search_provider import WebSearchProvider

    provider = YandexWebSearchProvider()
    assert isinstance(provider, WebSearchProvider)


def test_provider_routes_through_hermes_registry(live_env: None) -> None:
    from agent import web_search_registry

    web_search_registry._reset_for_tests()
    web_search_registry.register_provider(YandexWebSearchProvider())

    provider = web_search_registry.get_provider("yandex")
    assert provider is not None
    assert provider.is_available() is True

    result = provider.search("Yandex Search API", limit=5)
    assert result["success"] is True
    web = result["data"]["web"]
    assert web and all(item["url"].startswith("http") for item in web)


def test_generative_tool_handler_live(live_env: None) -> None:
    raw = generative.handle_generative_search({"query": "What is the capital of France?"})
    payload = json.loads(raw)
    if payload.get("is_answer_rejected"):
        pytest.skip("Generative search rejected the query on this run")
    assert payload.get("success") is True
    assert payload.get("answer")
