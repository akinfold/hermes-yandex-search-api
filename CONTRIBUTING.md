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
  config.py       # builds a client from environment variables
  _compat.py      # real-vs-shim Hermes base class + env helper
  __init__.py     # register(ctx) — the plugin entry point
tests/            # unit tests (no network, httpx.MockTransport)
tests/e2e/        # live tests (Yandex API + Hermes host), marked `e2e`
```

Keep `client.py` free of any Hermes imports so it stays unit-testable in
isolation. Anything that talks to the host belongs in `provider.py` /
`generative.py` / `_compat.py`.

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

Please keep coverage from regressing — add tests for new code and error paths.

CI also fails on any function radon rates **C or worse** — split it rather than
raising the bar. `radon cc -a hermes_yandex_search` shows the average.

### Running the live e2e tests (optional)

The `e2e`-marked tests hit the live Yandex Search API. Provide credentials via
env vars or local files, then run `pytest -m e2e` — see the README section
"Running the live E2E tests" for details.

## Commit & PR conventions

- Write focused commits with imperative subject lines
  (e.g. `client: handle empty passages`).
- Open a PR against `main`. Fill in the PR template and link any related issue.
- CI (lint + tests on Python 3.11–3.13) must pass. Live e2e is manual and not
  required for a PR.
- For user-facing changes, update the README and add a note to the PR
  description.

## Reporting security issues

Please do not open public issues for security-sensitive reports. Contact the
maintainer directly (see the repository owner's profile).
