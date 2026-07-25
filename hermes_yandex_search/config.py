"""Configuration helpers: build a :class:`YandexSearchClient` from the host env.

Credentials and options are read through :func:`get_provider_env`, which inside
Hermes resolves values from ``os.environ`` first and then ``~/.hermes/.env`` —
so keys configured through Hermes are visible even in subprocess/gateway runs.

Environment variables:

* ``YANDEX_API_KEY``     (required) - Yandex Cloud API key.
* ``YANDEX_FOLDER_ID``   (required) - Yandex Cloud folder ("catalog") id.
* ``YANDEX_SEARCH_TYPE`` (optional) - market/domain enum, default ``SEARCH_TYPE_RU``.
* ``YANDEX_SEARCH_API_URL`` (optional) - override the API base URL.
"""

from __future__ import annotations

from ._compat import get_provider_env
from .client import DEFAULT_BASE_URL, DEFAULT_SEARCH_TYPE, VALID_SEARCH_TYPES, YandexSearchClient

API_KEY_ENV = "YANDEX_API_KEY"
FOLDER_ID_ENV = "YANDEX_FOLDER_ID"
SEARCH_TYPE_ENV = "YANDEX_SEARCH_TYPE"
BASE_URL_ENV = "YANDEX_SEARCH_API_URL"

_SETUP_HINT = (
    "Set YANDEX_API_KEY and YANDEX_FOLDER_ID in ~/.hermes/.env (or your "
    "environment). See https://aistudio.yandex.ru/docs/ru/search-api/quickstart"
)


def credentials_present() -> bool:
    """Return True when both required credentials are configured."""
    return bool(get_provider_env(API_KEY_ENV)) and bool(get_provider_env(FOLDER_ID_ENV))


def build_client() -> YandexSearchClient:
    """Construct a :class:`YandexSearchClient` from environment configuration.

    Raises:
        ValueError: When required credentials are missing or a value is invalid.
    """
    api_key = get_provider_env(API_KEY_ENV)
    folder_id = get_provider_env(FOLDER_ID_ENV)
    if not api_key:
        raise ValueError(f"{API_KEY_ENV} is not set. {_SETUP_HINT}")
    if not folder_id:
        raise ValueError(f"{FOLDER_ID_ENV} is not set. {_SETUP_HINT}")

    search_type = get_provider_env(SEARCH_TYPE_ENV) or DEFAULT_SEARCH_TYPE
    if search_type not in VALID_SEARCH_TYPES:
        raise ValueError(
            f"{SEARCH_TYPE_ENV}={search_type!r} is invalid; "
            f"expected one of {sorted(VALID_SEARCH_TYPES)}"
        )
    base_url = get_provider_env(BASE_URL_ENV) or DEFAULT_BASE_URL

    return YandexSearchClient(
        api_key=api_key,
        folder_id=folder_id,
        search_type=search_type,
        base_url=base_url,
    )
