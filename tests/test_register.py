"""Tests for plugin registration via ``register(ctx)``."""

from __future__ import annotations

import hermes_yandex_search as plugin
from hermes_yandex_search.provider import YandexWebSearchProvider


class FakeContext:
    """Captures what a plugin registers, mimicking Hermes' PluginContext."""

    def __init__(self) -> None:
        self.providers: list = []
        self.tools: list[dict] = []

    def register_web_search_provider(self, provider) -> None:
        self.providers.append(provider)

    def register_tool(self, **kwargs) -> None:
        self.tools.append(kwargs)


def test_register_wires_provider_and_tool() -> None:
    ctx = FakeContext()
    plugin.register(ctx)

    assert len(ctx.providers) == 1
    assert isinstance(ctx.providers[0], YandexWebSearchProvider)

    assert len(ctx.tools) == 1
    tool = ctx.tools[0]
    assert tool["name"] == "yandex_generative_search"
    assert tool["schema"]["name"] == "yandex_generative_search"
    assert callable(tool["handler"])
    assert set(tool["requires_env"]) == {"YANDEX_API_KEY", "YANDEX_FOLDER_ID"}


def test_public_exports() -> None:
    for symbol in (
        "register",
        "YandexSearchClient",
        "YandexWebSearchProvider",
        "YandexSearchError",
        "WebResult",
        "GenerativeAnswer",
    ):
        assert hasattr(plugin, symbol)
    assert plugin.__version__
