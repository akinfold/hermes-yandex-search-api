"""The shipped tree must survive Hermes' install-time security scan.

``hermes plugins install`` scans a plugin before it ever runs, and a *critical*
finding is a hard block: ``--force`` does not override a dangerous verdict, and
``hermes plugins update`` disables an already-installed plugin that starts
producing one. Runtime code is where findings keep that severity - docs and the
test tree are demoted - so the guard here reads the package, not the repository.

The pattern below is Hermes' own (``tools/threat_patterns.py``). It cannot tell a
constant that *names* a credential variable from one that *holds* a credential,
which is how a sibling plugin's ``ENV_PASSWORD = "..."`` line blocked every
install of it. This package passes only because ``API_KEY_ENV`` keeps the
keyword away from the ``=`` and ``"YANDEX_API_KEY"`` is under the 20-character
threshold; pinning the shape keeps a later rename, a longer variable name or an
explanatory comment from writing the block in.
"""

from __future__ import annotations

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "hermes_yandex_search"

#: Verbatim from Hermes' ``hardcoded_secret`` rule, matched case-insensitively.
HARDCODED_SECRET = re.compile(
    r'(?:api[_-]?key|token|secret|password)\s*[=:]\s*["\'][A-Za-z0-9+/=_-]{20,}',
    re.IGNORECASE,
)


def test_no_runtime_line_looks_like_a_hardcoded_secret() -> None:
    offenders = [
        f"{source.relative_to(PACKAGE)}:{number}: {line.strip()}"
        for source in sorted(PACKAGE.rglob("*.py"))
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1)
        if HARDCODED_SECRET.search(line)
    ]
    assert not offenders, "Hermes blocks the install on these lines:\n" + "\n".join(offenders)


def test_the_guard_catches_the_shape_it_is_meant_to_catch() -> None:
    """Without this the test above passes just as well on an empty pattern."""
    # Assembled rather than written out: a literal of the shape the rule looks
    # for makes this file the top finding of the very scan it is guarding, and
    # on Hermes before 0.21.4 that was enough to push an install to CAUTION.
    quote = chr(34)
    caught = "ENV_API_KEY = " + quote + "YANDEX_SEARCH_API_" + "KEY_V2" + quote
    ignored = "API_KEY_ENV = " + quote + "YANDEX_API_" + "KEY" + quote
    assert HARDCODED_SECRET.search(caught)
    assert not HARDCODED_SECRET.search(ignored)
