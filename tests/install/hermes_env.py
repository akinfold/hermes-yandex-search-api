"""Find the Python a Hermes install runs on, for the two layouts its installer makes.

* The older layout — what the installer of Hermes v2026.9.24, the last release
  to build it, sets up, and anything installed before 2026-09-24 and not
  updated since — runs from the virtualenv inside the checkout:
  ``~/.hermes/hermes-agent/venv``.
* The installer on Hermes ``main`` since 2026-09-24 runs Hermes from an
  environment its package manager, pm, builds and replaces. pm records the one
  in use in ``~/.hermes/installs/<key>/facts.json``, where the key is derived
  from the checkout's path (``pm/environments.py``).

Only the default places are covered: a Hermes installed as root, under another
``HERMES_HOME`` root, or on Windows is not.

Used by ``test_install.py`` to run ``probe.py`` in Hermes' own interpreter, and
by the ``setup-hermes`` action to hand that interpreter to the live e2e run::

    python tests/install/hermes_env.py [HERMES_HOME]
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def facts_file(hermes_home: Path) -> Path:
    """Where pm records the environment of the checkout in ``hermes_home``."""
    checkout = str((hermes_home / "hermes-agent").resolve())
    key = hashlib.sha256(checkout.encode("utf-8")).hexdigest()[:16]
    return hermes_home / "installs" / key / "facts.json"


def is_pm_install(hermes_home: Path) -> bool:
    """Whether pm, not a virtualenv in the checkout, runs this Hermes."""
    return facts_file(hermes_home).is_file()


def hermes_python(hermes_home: Path) -> Path:
    """The interpreter Hermes runs on, with Hermes and its dependencies importable."""
    facts = facts_file(hermes_home)
    if facts.is_file():
        record = json.loads(facts.read_text(encoding="utf-8-sig"))
        environment = record.get("packages", {}).get("venv", {}).get("environment")
        # Before its first sync pm runs the checkout's own environment, as below.
        if environment:
            return Path(environment) / "bin" / "python"
    return hermes_home / "hermes-agent" / "venv" / "bin" / "python"


if __name__ == "__main__":
    home = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".hermes"
    print(hermes_python(home.expanduser()))
