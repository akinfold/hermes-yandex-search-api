"""Compatibility layer between this plugin and the Hermes Agent host.

When running inside Hermes, we use the real ``WebSearchProvider`` base class
and ``get_provider_env`` helper from ``agent.web_search_provider`` — the host
checks ``isinstance(provider, WebSearchProvider)`` at registration time, so the
provider MUST subclass the real class.

When Hermes is not importable (unit tests, standalone use), we fall back to a
minimal shim that mirrors the parts of the ABC surface this plugin relies on,
and read credentials directly from the process environment.
"""

from __future__ import annotations

import os
from typing import Any

# Narrow to ImportError on purpose: if ``agent.web_search_provider`` exists but
# fails to import for some other reason (circular import during Hermes startup,
# a version mismatch, ...), we must NOT silently fall back to the shim — that
# would make ``isinstance(provider, WebSearchProvider)`` fail at registration
# with no useful diagnostic. Let such errors surface instead.
try:
    from agent.web_search_provider import WebSearchProvider, get_provider_env

    HERMES_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only outside Hermes
    HERMES_AVAILABLE = False

    class WebSearchProvider:  # type: ignore[no-redef]
        """Minimal stand-in mirroring ``agent.web_search_provider.WebSearchProvider``."""

        @property
        def name(self) -> str:
            raise NotImplementedError

        @property
        def display_name(self) -> str:
            return self.name

        def is_available(self) -> bool:
            raise NotImplementedError

        def supports_search(self) -> bool:
            return True

        def supports_extract(self) -> bool:
            return False

        def search(self, query: str, limit: int = 5) -> dict[str, Any]:
            raise NotImplementedError

        def extract(self, urls: list[str], **kwargs: Any) -> Any:
            raise NotImplementedError

        def get_setup_schema(self) -> dict[str, Any]:
            return {"name": self.display_name, "badge": "", "tag": "", "env_vars": []}

    def get_provider_env(name: str) -> str:  # type: ignore[misc]
        """Read an env var, mirroring the host helper's stripped-string contract."""
        return (os.environ.get(name) or "").strip()


__all__ = ["HERMES_AVAILABLE", "WebSearchProvider", "get_provider_env"]
