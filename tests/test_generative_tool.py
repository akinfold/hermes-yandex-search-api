"""Unit tests for the ``yandex_generative_search`` tool handler."""

from __future__ import annotations

import json

import httpx
import pytest
from hermes_yandex_search import config, generative
from hermes_yandex_search.client import YandexSearchClient

from .conftest import SAMPLE_GEN_RESPONSE


def _client_with(handler: httpx.MockTransport) -> YandexSearchClient:
    return YandexSearchClient("k", "f", client=httpx.Client(transport=handler))


def test_schema_is_well_formed() -> None:
    assert generative.SCHEMA["name"] == "yandex_generative_search"
    params = generative.SCHEMA["parameters"]
    assert params["required"] == ["query"]
    assert "query" in params["properties"]


def test_handler_returns_answer_and_sources(
    monkeypatch: pytest.MonkeyPatch, yandex_env: None
) -> None:
    client = _client_with(
        httpx.MockTransport(lambda r: httpx.Response(200, json=SAMPLE_GEN_RESPONSE))
    )
    monkeypatch.setattr(config, "build_client", lambda: client)

    raw = generative.handle_generative_search({"query": "capital of France?"})
    payload = json.loads(raw)
    assert payload["success"] is True
    assert payload["answer"] == "Paris is the capital of France."
    assert payload["sources"][0]["url"] == "https://en.wikipedia.org/wiki/Paris"
    assert payload["search_queries"] == ["capital of France"]
    assert payload["is_bullet_answer"] is False


def test_handler_requires_query() -> None:
    payload = json.loads(generative.handle_generative_search({}))
    assert payload["success"] is False
    assert "query" in payload["error"]


def test_handler_rejects_non_list_sites(yandex_env: None) -> None:
    payload = json.loads(
        generative.handle_generative_search({"query": "q", "sites": "wikipedia.org"})
    )
    assert "error" in payload
    assert "sites" in payload["error"]


def test_handler_reports_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    monkeypatch.delenv("YANDEX_FOLDER_ID", raising=False)
    payload = json.loads(generative.handle_generative_search({"query": "q"}))
    assert "error" in payload
    assert "YANDEX_API_KEY" in payload["error"]


def test_handler_wraps_api_error(monkeypatch: pytest.MonkeyPatch, yandex_env: None) -> None:
    client = _client_with(
        httpx.MockTransport(lambda r: httpx.Response(429, json={"message": "rate limited"}))
    )
    monkeypatch.setattr(config, "build_client", lambda: client)

    payload = json.loads(generative.handle_generative_search({"query": "q"}))
    assert "error" in payload
    assert "rate limited" in payload["error"]


def test_handler_never_raises(monkeypatch: pytest.MonkeyPatch, yandex_env: None) -> None:
    class ExplodingClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def generative_search(self, *a, **k):
            raise RuntimeError("kaboom")

    monkeypatch.setattr(config, "build_client", lambda: ExplodingClient())
    payload = json.loads(generative.handle_generative_search({"query": "q"}))
    assert "error" in payload
    assert "kaboom" in payload["error"]
