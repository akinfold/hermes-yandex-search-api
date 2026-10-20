# Contributing

Thanks for your interest in improving **hermes-yandex-search-api** — a
[Hermes Agent](https://hermes-agent.nousresearch.com) plugin for the
[Yandex Search API](https://aistudio.yandex.ru/docs/ru/search-api/concepts/).
Contributions of all sizes are welcome: bug reports, docs, tests, and features.

## Ground rules

- All repository content (code, comments, docs, commit messages, issues, PRs)
  is in **English**.
- Be respectful and constructive. Assume good intent.

## Project layout

```
hermes_yandex_search/
  client.py       # Hermes-independent Yandex Search API client (HTTP + parsing)
  provider.py     # `yandex` web-search backend provider
  generative.py   # `yandex_generative_search` standalone tool
  config.py       # builds a client from the settings Hermes resolves
  _compat.py      # real-vs-shim Hermes base class + env helper
  __init__.py     # register(ctx) — the plugin entry point
tests/            # unit tests (no network, httpx.MockTransport)
tests/e2e/        # live tests (Yandex API + Hermes host), marked `e2e`
tests/install/    # installs the build into a real Hermes by every README route, marked `install`
```

Keep `client.py` free of any Hermes imports so it stays unit-testable in
isolation. Anything that talks to the host belongs in `provider.py` /
`generative.py` / `_compat.py`.

The plugin needs nothing beyond `httpx` and the standard library: the
recommended installs copy only the plugin directory, so nothing else would be
installed. Keep it that way. Parse XML only through `_parse_xml` in
`client.py`. It refuses any DTD, any document that is not UTF-8 or is larger
than `MAX_XML_BYTES`, any element nested deeper than `MAX_XML_DEPTH`, more than
`MAX_XML_NAMES` distinct names, and any namespace URI longer than
`MAX_NAMESPACE_URI_CHARS` or not in ASCII, and refuses to parse at
all on an Expat older than `MIN_EXPAT_VERSION`. It spells each distinct element
and attribute name once, as ElementTree's own parser does, so a namespace URI
is not copied into every element that uses it.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

## Checks (run before opening a PR)

```bash
ruff check .            # lint
ruff format --check .   # code style (run `ruff format .` to fix)
pytest                  # unit tests; live e2e tests are deselected by default
radon cc -s -n C hermes_yandex_search   # complexity; must print nothing
```

CI runs the unit tests with coverage and **fails below 90% total coverage**.
Reproduce that gate locally with:

```bash
pytest --cov=hermes_yandex_search --cov-report=term-missing --cov-fail-under=90
```

Add tests for new code and error paths so coverage does not regress.

CI also fails on any function radon rates **C or worse** — split it rather than
raising the bar. `radon cc -a hermes_yandex_search` shows the average.

### Running the live e2e tests (optional)

The `e2e`-marked tests hit the live Yandex Search API. Provide credentials via
env vars or local files, then run `pytest -m e2e` — see the README section
"Running the live E2E tests" for details.

### The install check

`tests/install/`, marked `install`, installs the Git tree, the drop-in archive, a
copy of the plugin directory, and (on a Hermes in the older layout) the built
wheel into a real Hermes set up by its official installer, using the commands the
README gives, and asks Hermes what it loaded. Change an install
instruction in the README and you change the test:
`test_readme_gives_the_commands_under_test`, which runs with the unit tests, fails
until the two agree.

The **Install check** workflow runs it against three Hermes installs, each made
by the official installer of that Hermes: `legacy`, Hermes v2026.9.24, the last
release whose installer builds the older layout the PyPI command is for;
`release`, the latest Hermes release; and `main`. It runs on every pull request,
and the release workflow runs it on the artifacts it has just built: the GitHub
Release and the PyPI upload wait for it. It also runs on its own every Monday and
on demand from the Actions tab, because Hermes changes while this repository does
not: `main` every day, its releases every few days.

The check installs into the real `~/.hermes`, so run it yourself only in a
disposable container or VM, never where you use Hermes: for example an
`ubuntu:24.04` container with a non-root user, Hermes installed there by the
installer of the channel you want — saved to a file and run with
`--non-interactive --skip-setup --skip-browser --skip-computer-use`, plus
`--branch` and the tag for a release (`v2026.9.24` for `legacy`) or
`--channel main` for `main` — and the commit under test pushed, since Hermes
clones it from GitHub. The v2026.9.24 installer also needs a C++ compiler
(`build-essential` on Ubuntu), which GitHub runners already have. The docstring
of `tests/install/test_install.py` lists the variables to set. Remove the
container afterwards.

## Commit & PR conventions

- Write focused commits with imperative subject lines
  (e.g. `client: handle empty passages`).
- Open a PR against `main`. Fill in the PR template and link any related issue.
- CI (lint + tests on Python 3.11–3.14) must pass. Live e2e is manual and not
  required for a PR.
- For user-facing changes, update the README and add a note to the PR
  description.

## Reporting security issues

Please do not open public issues for security-sensitive reports. Contact the
maintainer directly (see the repository owner's profile).
