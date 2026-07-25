"""Unit tests for the web-search path of :class:`YandexSearchClient`."""

from __future__ import annotations

import json

import httpx
import pytest
from hermes_yandex_search.client import (
    WebResult,
    YandexSearchClient,
    YandexSearchError,
    _parse_web_xml,
)

from .conftest import SAMPLE_WEB_XML, encode_raw_data


def make_client(handler: httpx.MockTransport | None = None, **kwargs) -> YandexSearchClient:
    transport = handler or httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    http_client = httpx.Client(transport=transport)
    return YandexSearchClient("k", "f", client=http_client, **kwargs)


def test_parse_web_xml_extracts_results() -> None:
    results = _parse_web_xml(SAMPLE_WEB_XML.encode("utf-8"))
    assert len(results) == 2

    first = results[0]
    assert isinstance(first, WebResult)
    assert first.url == "https://example.com/a"
    assert first.domain == "example.com"
    assert first.position == 1
    # <hlword> highlight tags are flattened away.
    assert first.title == "Example A Title"
    # Snippet is built from passages, joined.
    assert "First passage text." in first.description
    assert "Second passage." in first.description


def test_parse_web_xml_falls_back_to_headline() -> None:
    results = _parse_web_xml(SAMPLE_WEB_XML.encode("utf-8"))
    second = results[1]
    assert second.url == "https://example.org/b"
    assert second.position == 2
    assert second.description == "Headline B"


def test_parse_web_xml_raises_on_invalid_xml() -> None:
    with pytest.raises(YandexSearchError):
        _parse_web_xml(b"<not-valid")


def test_web_search_sends_expected_request(web_raw_data: str) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json={"rawData": web_raw_data})

    client = make_client(httpx.MockTransport(handler), search_type="SEARCH_TYPE_COM")
    results = client.web_search("best espresso", n_results=3)

    assert captured["url"].endswith("/v2/web/search")
    assert captured["auth"] == "Api-Key k"
    body = captured["body"]
    assert body["folderId"] == "f"
    assert body["query"]["searchType"] == "SEARCH_TYPE_COM"
    assert body["query"]["queryText"] == "best espresso"
    assert body["groupSpec"]["groupsOnPage"] == 3
    assert body["responseFormat"] == "FORMAT_XML"
    assert len(results) == 2


def test_web_search_truncates_to_n_results(web_raw_data: str) -> None:
    client = make_client(
        httpx.MockTransport(lambda r: httpx.Response(200, json={"rawData": web_raw_data}))
    )
    results = client.web_search("q", n_results=1)
    assert len(results) == 1
    assert results[0].position == 1


def test_web_search_rejects_empty_query() -> None:
    client = make_client()
    with pytest.raises(ValueError, match="non-empty"):
        client.web_search("   ")


def test_web_search_raises_on_missing_raw_data() -> None:
    client = make_client(httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    with pytest.raises(YandexSearchError, match="rawData"):
        client.web_search("q")


def test_web_search_raises_on_bad_base64() -> None:
    client = make_client(
        httpx.MockTransport(lambda r: httpx.Response(200, json={"rawData": "!!!not-base64!!!"}))
    )
    with pytest.raises(YandexSearchError, match="Base64"):
        client.web_search("q")


def test_http_error_is_wrapped_with_status_and_request_id() -> None:
    error_body = {
        "code": 3,
        "message": "Validation error: folder_id: Field is required",
        "details": [{"@type": "...", "requestId": "rid-42"}],
    }
    client = make_client(httpx.MockTransport(lambda r: httpx.Response(400, json=error_body)))
    with pytest.raises(YandexSearchError) as exc_info:
        client.web_search("q")
    err = exc_info.value
    assert err.status_code == 400
    assert err.request_id == "rid-42"
    assert "folder_id" in str(err)


def test_transport_error_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = make_client(httpx.MockTransport(handler))
    with pytest.raises(YandexSearchError, match="failed"):
        client.web_search("q")


def test_constructor_validates_arguments() -> None:
    with pytest.raises(ValueError, match="api_key"):
        YandexSearchClient("", "f")
    with pytest.raises(ValueError, match="folder_id"):
        YandexSearchClient("k", "")
    with pytest.raises(ValueError, match="search_type"):
        YandexSearchClient("k", "f", search_type="SEARCH_TYPE_BOGUS")


def test_raw_data_survives_roundtrip() -> None:
    encoded = encode_raw_data(SAMPLE_WEB_XML)
    client = make_client(
        httpx.MockTransport(lambda r: httpx.Response(200, json={"rawData": encoded}))
    )
    results = client.web_search("q", n_results=10)
    assert [r.url for r in results] == [
        "https://example.com/a",
        "https://example.org/b",
    ]


def test_parse_web_xml_url_as_attribute() -> None:
    xml = (
        '<yandexsearch><response><results><grouping><group>'
        '<doc url="https://attr.example/x"><title>Attr URL</title></doc>'
        "</group></grouping></results></response></yandexsearch>"
    )
    results = _parse_web_xml(xml.encode("utf-8"))
    assert len(results) == 1
    assert results[0].url == "https://attr.example/x"
    assert results[0].title == "Attr URL"


def test_parse_web_xml_is_namespace_tolerant() -> None:
    xml = (
        '<yandexsearch xmlns="urn:yandex:search"><response><results><grouping>'
        "<group><doc><url>https://ns.example/y</url><title>NS Result</title></doc>"
        "</group></grouping></results></response></yandexsearch>"
    )
    results = _parse_web_xml(xml.encode("utf-8"))
    assert len(results) == 1
    assert results[0].url == "https://ns.example/y"


def test_parse_web_xml_raises_on_in_document_error() -> None:
    xml = (
        "<yandexsearch><response><error>Search backend unavailable</error>"
        "</response></yandexsearch>"
    )
    with pytest.raises(YandexSearchError, match="Search backend unavailable"):
        _parse_web_xml(xml.encode("utf-8"))


def test_web_search_sends_optional_params(web_raw_data: str) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json={"rawData": web_raw_data})

    client = make_client(httpx.MockTransport(handler))
    client.web_search("q", page=2, region="213", localization="LOCALIZATION_EN", fix_typo=False)
    body = captured["body"]
    assert body["query"]["page"] == 2
    assert body["region"] == "213"
    assert body["l10N"] == "LOCALIZATION_EN"
    assert body["query"]["fixTypoMode"] == "FIX_TYPO_MODE_OFF"


def test_owned_client_is_closed_but_injected_is_not() -> None:
    # Injected client: caller owns it, close()/__exit__ must NOT close it.
    injected = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    with YandexSearchClient("k", "f", client=injected):
        pass
    assert injected.is_closed is False
    injected.close()

    # Owned client: created internally, must be closed on __exit__.
    with YandexSearchClient("k", "f") as owned:
        internal = owned._client
    assert internal.is_closed is True
