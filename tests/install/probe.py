"""Report what Hermes loaded, from inside Hermes' own interpreter.

``test_install.py`` runs this with the Python of the Hermes virtualenv, after
an install. It discovers plugins the way the agent does when a session starts,
then prints one line, ``PROBE <json>``, holding:

* ``plugins`` — every plugin that did not ship with Hermes, as Hermes' plugin
  manager lists it: source, enabled, number of tools, load error;
* ``tools`` — every tool in the agent's catalog for the CLI platform, with its
  toolset. Hermes leaves out a tool whose availability check fails, so a tool
  that needs credentials is here only when Hermes can see them;
* ``web_search`` — the provider Hermes' ``web_search`` tool would call, and
  whether that provider reports itself available.

The catalog is the full one. Hermes may show the model only part of it and
defer plugin tools behind ``tool_search``; deferred tools stay callable, so
they count.

This uses Hermes internals, and a Hermes refactor can break it. It then
reports ``probe_error`` with the traceback rather than a verdict, and the test
fails saying so.
"""

from __future__ import annotations

import json
import logging
import traceback


def _report() -> dict:
    import model_tools
    from agent.web_search_registry import get_active_search_provider
    from hermes_cli.config import load_config
    from hermes_cli.plugins import discover_plugins, get_plugin_manager
    from hermes_cli.tools_config import _get_platform_tools
    from tools.registry import registry

    discover_plugins()
    plugins = [p for p in get_plugin_manager().list_plugins() if p["source"] != "bundled"]
    toolsets = sorted(_get_platform_tools(load_config(), "cli"))
    catalog = model_tools.get_tool_definitions(
        enabled_toolsets=toolsets, quiet_mode=True, skip_tool_search_assembly=True
    )
    tools = {}
    for definition in catalog:
        name = definition["function"]["name"]
        entry = registry.get_entry(name)
        tools[name] = entry.toolset if entry else None
    provider = get_active_search_provider()
    web_search = {
        "provider": getattr(provider, "name", None),
        "available": bool(provider and provider.is_available()),
    }
    return {"plugins": plugins, "tools": tools, "web_search": web_search}


def main() -> None:
    logging.disable(logging.CRITICAL)
    try:
        report = _report()
    except Exception:
        report = {"probe_error": traceback.format_exc()}
    print("PROBE " + json.dumps(report, default=str))


if __name__ == "__main__":
    main()
