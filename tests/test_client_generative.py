"""Unit tests for the generative-search path of :class:`YandexSearchClient`."""

from __future__ import annotations

import json

import httpx
import pytest
from hermes_yandex_search.client import (
    GenerativeAnswer,
    YandexSearchClient,
    _parse_generative,
)

from .conftest import SAMPLE_GEN_RESPONSE


def make_client(handler: httpx.MockTransport, **kwargs) -> YandexSearchClient:
    return YandexSearchClient("k", "f", client=httpx.Client(transport=handler), **kwargs)


def test_parse_generative_extracts_answer_and_sources() -> None:
    answer = _parse_generative(SAMPLE_GEN_RESPONSE)
    assert isinstance(answer, GenerativeAnswer)
    assert answer.text == "Paris is the capital of France."
    assert len(answer.sources) == 1
    assert answer.sources[0].url == "https://en.wikipedia.org/wiki/Paris"
    assert answer.sources[0].used_text == "Paris is the capital of France."
    assert answer.search_queries == ["capital of France"]
    assert answer.is_answer_rejected is False


def test_parse_generative_handles_array_wrapper() -> None:
    answer = _parse_generative([SAMPLE_GEN_RESPONSE])
    assert answer.text == "Paris is the capital of France."


def test_parse_generative_handles_missing_fields() -> None:
    answer = _parse_generative({})
    assert answer.text == ""
    assert answer.sources == []
    assert answer.search_queries == []


def test_generative_search_builds_messages_and_site_filter() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read().decode("utf-8"))
        captured["url"] = str(request.url)
        return httpx.Response(200, json=SAMPLE_GEN_RESPONSE)

    client = make_client(httpx.MockTransport(handler))
    answer = client.generative_search("capital of France?", sites=["wikipedia.org"])

    assert captured["url"].endswith("/v2/gen/search")
    body = captured["body"]
    assert body["messages"] == [{"role": "ROLE_USER", "content": "capital of France?"}]
    assert body["site"] == {"site": ["wikipedia.org"]}
    assert body["folderId"] == "f"
    assert answer.text == "Paris is the capital of France."


def test_generative_search_accepts_explicit_messages() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json=SAMPLE_GEN_RESPONSE)

    client = make_client(httpx.MockTransport(handler))
    messages = [
        {"role": "ROLE_USER", "content": "hi"},
        {"role": "ROLE_ASSISTANT", "content": "hello"},
        {"role": "ROLE_USER", "content": "capital of France?"},
    ]
    client.generative_search(messages=messages)
    assert captured["body"]["messages"] == messages


def test_generative_search_requires_query_or_messages() -> None:
    client = make_client(httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    with pytest.raises(ValueError, match="query or messages"):
        client.generative_search()


def test_generative_search_host_and_url_filters() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json=SAMPLE_GEN_RESPONSE)

    client = make_client(httpx.MockTransport(handler))
    client.generative_search("q", hosts=["news.example"])
    assert captured["body"]["host"] == {"host": ["news.example"]}
    assert "site" not in captured["body"]

    client.generative_search("q", urls=["https://example.com/page"])
    assert captured["body"]["url"] == {"url": ["https://example.com/page"]}


def test_parse_generative_accepts_string_search_queries() -> None:
    data = dict(SAMPLE_GEN_RESPONSE, searchQueries=["plain query", {"text": "dict query"}])
    answer = _parse_generative(data)
    assert answer.search_queries == ["plain query", "dict query"]


def test_parse_generative_reads_flags_and_fixed_query() -> None:
    data = dict(
        SAMPLE_GEN_RESPONSE,
        fixedMisspellQuery="corrected",
        isAnswerRejected=True,
        isBulletAnswer=True,
    )
    answer = _parse_generative(data)
    assert answer.fixed_query == "corrected"
    assert answer.is_answer_rejected is True
    assert answer.is_bullet_answer is True
