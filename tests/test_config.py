"""Unit tests for environment-driven client construction."""

from __future__ import annotations

import pytest
from hermes_yandex_search import config
from hermes_yandex_search.client import DEFAULT_BASE_URL


def test_build_client_reads_env(yandex_env: None) -> None:
    client = config.build_client()
    assert client._api_key == "test-api-key"
    assert client._folder_id == "test-folder-id"
    assert client._search_type == "SEARCH_TYPE_RU"
    assert client._base_url == DEFAULT_BASE_URL
    client.close()


def test_build_client_honours_overrides(monkeypatch: pytest.MonkeyPatch, yandex_env: None) -> None:
    monkeypatch.setenv("YANDEX_SEARCH_TYPE", "SEARCH_TYPE_COM")
    monkeypatch.setenv("YANDEX_SEARCH_API_URL", "https://example.test")
    client = config.build_client()
    assert client._search_type == "SEARCH_TYPE_COM"
    assert client._base_url == "https://example.test"
    client.close()


def test_build_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    monkeypatch.setenv("YANDEX_FOLDER_ID", "f")
    with pytest.raises(ValueError, match="YANDEX_API_KEY"):
        config.build_client()


def test_build_client_requires_folder_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_API_KEY", "k")
    monkeypatch.delenv("YANDEX_FOLDER_ID", raising=False)
    with pytest.raises(ValueError, match="YANDEX_FOLDER_ID"):
        config.build_client()


def test_build_client_rejects_bad_search_type(
    monkeypatch: pytest.MonkeyPatch, yandex_env: None
) -> None:
    monkeypatch.setenv("YANDEX_SEARCH_TYPE", "SEARCH_TYPE_MARS")
    with pytest.raises(ValueError, match="invalid"):
        config.build_client()


def test_credentials_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    monkeypatch.delenv("YANDEX_FOLDER_ID", raising=False)
    assert config.credentials_present() is False
    monkeypatch.setenv("YANDEX_API_KEY", "k")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "f")
    assert config.credentials_present() is True
