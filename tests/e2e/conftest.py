"""Fixtures for end-to-end tests that hit the live Yandex Search API.

Credentials are resolved from (in order):

* environment variables ``YANDEX_API_KEY`` / ``YANDEX_FOLDER_ID`` (used in CI);
* local files ``~/.yandex-search-api-key`` / ``~/.yandex-folder-id`` (used for
  local debugging).

If neither yields both values, the e2e tests are skipped.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

API_KEY_FILE = Path.home() / ".yandex-search-api-key"
FOLDER_ID_FILE = Path.home() / ".yandex-folder-id"


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _resolve(env_var: str, path: Path) -> str:
    return (os.environ.get(env_var) or "").strip() or _read_file(path)


@pytest.fixture(scope="session")
def live_credentials() -> tuple[str, str]:
    api_key = _resolve("YANDEX_API_KEY", API_KEY_FILE)
    folder_id = _resolve("YANDEX_FOLDER_ID", FOLDER_ID_FILE)
    if not api_key or not folder_id:
        pytest.skip(
            "Live Yandex credentials not available "
            "(need YANDEX_API_KEY/YANDEX_FOLDER_ID env or ~/.yandex-search-api-key "
            "and ~/.yandex-folder-id files)."
        )
    return api_key, folder_id


@pytest.fixture
def live_env(live_credentials: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    api_key, folder_id = live_credentials
    monkeypatch.setenv("YANDEX_API_KEY", api_key)
    monkeypatch.setenv("YANDEX_FOLDER_ID", folder_id)
