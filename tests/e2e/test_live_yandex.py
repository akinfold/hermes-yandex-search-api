"""End-to-end tests against the live Yandex Search API.

Run with:  pytest -m e2e
Requires real credentials (see tests/e2e/conftest.py).
"""

from __future__ import annotations

import os

import pytest
from hermes_yandex_search.client import YandexSearchClient

pytestmark = pytest.mark.e2e


def _client(api_key: str, folder_id: str) -> YandexSearchClient:
    search_type = (os.environ.get("YANDEX_SEARCH_TYPE") or "SEARCH_TYPE_RU").strip()
    return YandexSearchClient(api_key, folder_id, search_type=search_type)


def test_live_web_search_returns_results(live_credentials: tuple[str, str]) -> None:
    api_key, folder_id = live_credentials
    with _client(api_key, folder_id) as client:
        results = client.web_search("Yandex Search API", n_results=5)

    assert results, "expected at least one web result"
    for r in results:
        assert r.url.startswith("http")
        assert r.title
    positions = [r.position for r in results]
    assert positions == sorted(positions)


def test_live_generative_search_returns_answer(live_credentials: tuple[str, str]) -> None:
    api_key, folder_id = live_credentials
    with _client(api_key, folder_id) as client:
        answer = client.generative_search("What is the capital of France?")

    if answer.is_answer_rejected:
        pytest.skip("Generative search rejected the query on this run")
    assert answer.text.strip(), "expected a non-empty generative answer"
