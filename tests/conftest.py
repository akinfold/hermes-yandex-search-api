"""Shared fixtures and sample payloads for the test suite."""

from __future__ import annotations

import base64

import pytest

# A realistic (trimmed) ``<yandexsearch>`` XML document. The first doc carries
# passages and inline <hlword> highlight tags; the second has no passages so the
# snippet must fall back to <headline>.
SAMPLE_WEB_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response date="20260725T120000">
    <reqid>req-abc-123</reqid>
    <found priority="all">2</found>
    <results>
      <grouping>
        <group>
          <doc id="d1">
            <url>https://example.com/a</url>
            <domain>example.com</domain>
            <title>Example <hlword>A</hlword> Title</title>
            <headline>Headline A</headline>
            <passages>
              <passage>First <hlword>passage</hlword> text.</passage>
              <passage>Second passage.</passage>
            </passages>
          </doc>
        </group>
        <group>
          <doc id="d2">
            <url>https://example.org/b</url>
            <domain>example.org</domain>
            <title>Second Result</title>
            <headline>Headline B</headline>
          </doc>
        </group>
      </grouping>
    </results>
  </response>
</yandexsearch>
"""

SAMPLE_GEN_RESPONSE = {
    "message": {"role": "ROLE_ASSISTANT", "content": "Paris is the capital of France."},
    "sources": [
        {
            "url": "https://en.wikipedia.org/wiki/Paris",
            "title": "Paris",
            "usedText": "Paris is the capital of France.",
        }
    ],
    "searchQueries": [{"text": "capital of France", "reqId": "r1"}],
    "fixedMisspellQuery": "",
    "isAnswerRejected": False,
    "isBulletAnswer": False,
}


def encode_raw_data(xml: str) -> str:
    """Base64-encode an XML string the way the API wraps it in ``rawData``."""
    return base64.b64encode(xml.encode("utf-8")).decode("ascii")


@pytest.fixture
def web_raw_data() -> str:
    return encode_raw_data(SAMPLE_WEB_XML)


@pytest.fixture
def gen_response() -> dict:
    return SAMPLE_GEN_RESPONSE


@pytest.fixture
def yandex_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Populate the credentials the plugin reads from the environment."""
    monkeypatch.setenv("YANDEX_API_KEY", "test-api-key")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test-folder-id")
    monkeypatch.delenv("YANDEX_SEARCH_TYPE", raising=False)
    monkeypatch.delenv("YANDEX_SEARCH_API_URL", raising=False)
