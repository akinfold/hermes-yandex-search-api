"""Unit tests for :class:`YandexWebSearchProvider`."""

from __future__ import annotations

import httpx
import pytest
from hermes_yandex_search import config
from hermes_yandex_search.client import YandexSearchClient, YandexSearchError
from hermes_yandex_search.provider import YandexWebSearchProvider


def _client_with(handler: httpx.MockTransport) -> YandexSearchClient:
    return YandexSearchClient("k", "f", client=httpx.Client(transport=handler))


def test_metadata() -> None:
    provider = YandexWebSearchProvider()
    assert provider.name == "yandex"
    assert provider.display_name == "Yandex"
    assert provider.supports_search() is True
    assert provider.supports_extract() is False


def test_is_available_reflects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = YandexWebSearchProvider()
    monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    monkeypatch.delenv("YANDEX_FOLDER_ID", raising=False)
    assert provider.is_available() is False

    monkeypatch.setenv("YANDEX_API_KEY", "k")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "f")
    assert provider.is_available() is True


def test_search_returns_success_envelope(
    monkeypatch: pytest.MonkeyPatch, yandex_env: None, web_raw_data: str
) -> None:
    client = _client_with(
        httpx.MockTransport(lambda r: httpx.Response(200, json={"rawData": web_raw_data}))
    )
    monkeypatch.setattr(config, "build_client", lambda: client)

    result = YandexWebSearchProvider().search("espresso", limit=5)
    assert result["success"] is True
    web = result["data"]["web"]
    assert len(web) == 2
    assert web[0]["url"] == "https://example.com/a"
    assert web[0]["position"] == 1
    assert set(web[0]) == {"title", "url", "description", "position"}


def test_search_maps_api_error(monkeypatch: pytest.MonkeyPatch, yandex_env: None) -> None:
    client = _client_with(
        httpx.MockTransport(lambda r: httpx.Response(400, json={"message": "bad request"}))
    )
    monkeypatch.setattr(config, "build_client", lambda: client)

    result = YandexWebSearchProvider().search("q")
    assert result["success"] is False
    assert "bad request" in result["error"]


def test_search_handles_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    monkeypatch.delenv("YANDEX_FOLDER_ID", raising=False)
    result = YandexWebSearchProvider().search("q")
    assert result["success"] is False
    assert "YANDEX_API_KEY" in result["error"]


def test_search_swallows_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch, yandex_env: None
) -> None:
    class ExplodingClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def web_search(self, *a, **k):
            raise RuntimeError("kaboom")

    monkeypatch.setattr(config, "build_client", lambda: ExplodingClient())
    result = YandexWebSearchProvider().search("q")
    assert result["success"] is False
    assert "kaboom" in result["error"]


def test_search_swallows_non_valueerror_from_build_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> YandexSearchClient:
        raise RuntimeError("build blew up")

    monkeypatch.setattr(config, "build_client", boom)
    result = YandexWebSearchProvider().search("q")
    assert result["success"] is False
    assert "build blew up" in result["error"]


def test_get_setup_schema_shape() -> None:
    schema = YandexWebSearchProvider().get_setup_schema()
    assert schema["name"] == "Yandex"
    keys = {var["key"] for var in schema["env_vars"]}
    assert keys == {"YANDEX_API_KEY", "YANDEX_FOLDER_ID"}


def test_search_error_from_yandex_error_type(
    monkeypatch: pytest.MonkeyPatch, yandex_env: None
) -> None:
    class RaisingClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def web_search(self, *a, **k):
            raise YandexSearchError("explicit yandex failure", status_code=502)

    monkeypatch.setattr(config, "build_client", lambda: RaisingClient())
    result = YandexWebSearchProvider().search("q")
    assert result["success"] is False
    assert "explicit yandex failure" in result["error"]
