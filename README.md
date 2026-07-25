# hermes-yandex-search-api

[![PyPI version](https://img.shields.io/pypi/v/hermes-yandex-search-api.svg)](https://pypi.org/project/hermes-yandex-search-api/)
[![CI](https://github.com/akinfold/hermes-yandex-search-api/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/akinfold/hermes-yandex-search-api/actions/workflows/ci.yml)
[![E2E (live)](https://github.com/akinfold/hermes-yandex-search-api/actions/workflows/e2e.yml/badge.svg)](https://github.com/akinfold/hermes-yandex-search-api/actions/workflows/e2e.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/akinfold/hermes-yandex-search-api/badges/coverage.json&v=1)](https://github.com/akinfold/hermes-yandex-search-api/actions/workflows/ci.yml)
[![CodeFactor](https://www.codefactor.io/repository/github/akinfold/hermes-yandex-search-api/badge)](https://www.codefactor.io/repository/github/akinfold/hermes-yandex-search-api)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**Give your [Hermes Agent](https://hermes-agent.nousresearch.com) first-class
Yandex search.** This plugin wires the
[Yandex Search API](https://aistudio.yandex.ru/docs/ru/search-api/concepts/) into
Hermes as a drop-in web-search backend **and** adds a grounded-answer tool —
excellent results for Russian-language queries, on infrastructure you may already
have in Yandex Cloud.

- 🔎 **`yandex` web-search backend** — routes Hermes' built-in `web_search` tool
  to Yandex web search (links with titles and snippets). Nothing new for the
  model to learn.
- 💬 **`yandex_generative_search` tool** — a single grounded answer synthesised
  from live web sources, with the source URLs it cites.

## Quick start

```bash
# 1. Install into Hermes (alternatively: pip install hermes-yandex-search-api)
hermes plugins install akinfold/hermes-yandex-search-api --enable

# 2. Add your Yandex Cloud credentials (see "Getting a token" below)
printf 'YANDEX_API_KEY=%s\nYANDEX_FOLDER_ID=%s\n' 'your-api-key' 'your-folder-id' >> ~/.hermes/.env
```

Then select Yandex as the web-search backend in `~/.hermes/config.yaml`:

```yaml
web:
  search_backend: yandex
plugins:
  enabled:
    - yandex
```

That's it — `web_search` now goes through Yandex, and the
`yandex_generative_search` tool is available to the agent. Don't have an API key
and folder id yet? See
[Getting a Yandex Search API token](#getting-a-yandex-search-api-token). Prefer a
drop-in or pip install? See
[Installing the plugin into Hermes](#installing-the-plugin-into-hermes).

## Why these two search modes

The Yandex Search API offers several modes — classic web search, generative
search, image search, deferred (async) web search, and Wordstat keyword
statistics. This plugin deliberately wires up the two that fit an autonomous
agent, each in the shape Hermes expects:

- **Web search → a `web_search` backend.** Hermes already ships a `web_search`
  tool whose backend returns a list of `{title, url, description}` results. The
  classic Yandex web search maps onto that contract exactly, so the model can
  use the search tool it already knows without learning a new one.
- **Generative search → its own tool.** Generative search returns a *synthesised
  answer with citations*, not a list of links. That is a fundamentally different
  result shape, so it is exposed as a distinct `yandex_generative_search` tool.
  It is the best fit when the agent wants a direct, grounded answer to a factual
  question.

The other modes are intentionally left out: **image search** returns image URLs
an agent cannot usefully consume, **Wordstat** is SEO keyword analytics unrelated
to agentic search, and **deferred web search** has a multi-minute latency that is
unusable for interactive turns. All of them can be added later on top of the same
`YandexSearchClient` if a use case appears.

## About the Yandex Search API

The [Yandex Search API](https://aistudio.yandex.ru/docs/ru/search-api/concepts/)
is Yandex Cloud's paid programmatic access to Yandex web search and its
generative answer engine. Requests are authenticated with a Yandex Cloud API key
and are billed to the Yandex Cloud folder that owns the key. Both search modes
used here run synchronously:

- `POST /v2/web/search` returns Base64-encoded XML search results.
- `POST /v2/gen/search` returns a JSON grounded answer with cited sources.

See the [pricing](https://yandex.cloud/docs/search-api/pricing) and
[quotas](https://yandex.cloud/docs/search-api/concepts/limits) pages for current
limits (roughly 10k web requests/hour and 1k generative requests/hour by
default).

## Requirements

- Hermes Agent `>= 0.19` (tested against 0.19.x).
- Python `>= 3.11, < 3.14`.
- A Yandex Cloud account with the Search API enabled, an **API key**, and the
  **folder id** that owns it.

## Getting a Yandex Search API token

1. Create or open a [Yandex Cloud](https://console.yandex.cloud) account and a
   **folder** (catalog). Note its **folder id** — you can copy it from the
   console URL or with the CLI:
   [how to get the folder id](https://yandex.cloud/docs/resource-manager/operations/folder/get-id).
2. Create a **service account** in that folder and grant it the
   `search-api.webSearch.user` role.
3. Create an **API key** for that service account (Console → the service account
   → *API keys* → *Create API key*), or via CLI:
   ```bash
   yc iam api-key create --service-account-name <sa-name> --format json
   ```
   Copy the `secret` value — this is your `YANDEX_API_KEY`.
4. Make sure the Search API is enabled for the folder and that billing is active.

You now have the two values the plugin needs: `YANDEX_API_KEY` and
`YANDEX_FOLDER_ID`.

## Installing the plugin into Hermes

### Option A — install from Git (recommended)

```bash
hermes plugins install akinfold/hermes-yandex-search-api --enable
```

### Option B — drop-in directory

Copy the plugin directory into your Hermes plugins folder under the `web`
category, then enable it:

```bash
mkdir -p ~/.hermes/plugins/web
cp -r hermes_yandex_search ~/.hermes/plugins/web/yandex
hermes plugins enable yandex
```

(Or download `hermes-yandex-search-plugin-<version>.zip` from a
[GitHub Release](https://github.com/akinfold/hermes-yandex-search-api/releases)
and unzip it into `~/.hermes/plugins/web/`.)

### Option C — pip

```bash
pip install hermes-yandex-search-api
hermes plugins enable yandex
```

Hermes discovers the plugin through the `hermes_agent.plugins` entry point.

## Configuring the token in Hermes

The plugin reads its credentials from the environment, resolved the way every
Hermes web backend resolves them: `os.environ` first, then `~/.hermes/.env`.
The simplest, persistent option is to put them in `~/.hermes/.env`:

```dotenv
YANDEX_API_KEY=your-api-key
YANDEX_FOLDER_ID=your-folder-id
# Optional: market/domain, default SEARCH_TYPE_RU.
# One of SEARCH_TYPE_RU | SEARCH_TYPE_COM | SEARCH_TYPE_TR | SEARCH_TYPE_KK | SEARCH_TYPE_BE | SEARCH_TYPE_UZ
YANDEX_SEARCH_TYPE=SEARCH_TYPE_RU
# Optional: override the API base URL (for a private gateway / testing).
# YANDEX_SEARCH_API_URL=https://searchapi.api.cloud.yandex.net
```

`hermes plugins install ... --enable` will also prompt for the values declared in
the plugin manifest (`YANDEX_API_KEY`, `YANDEX_FOLDER_ID`) during installation.

### Selecting Yandex as the web-search backend

To route Hermes' built-in `web_search` tool to Yandex, set the backend in
`~/.hermes/config.yaml`:

```yaml
web:
  search_backend: yandex
plugins:
  enabled:
    - yandex
```

The `yandex_generative_search` tool becomes available as soon as the plugin is
enabled — no extra configuration needed.

## Configuration reference

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `YANDEX_API_KEY` | yes | – | Yandex Cloud API key. |
| `YANDEX_FOLDER_ID` | yes | – | Yandex Cloud folder ("catalog") id. |
| `YANDEX_SEARCH_TYPE` | no | `SEARCH_TYPE_RU` | Search market/domain enum. |
| `YANDEX_SEARCH_API_URL` | no | `https://searchapi.api.cloud.yandex.net` | API base URL override. |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

ruff check .          # lint
ruff format --check . # code style
pytest                # unit tests (live E2E tests are deselected by default)
```

The package layout separates a Hermes-independent API client from the host
integration:

- `hermes_yandex_search/client.py` — the `YandexSearchClient` (pure HTTP + parsing, no Hermes imports).
- `hermes_yandex_search/provider.py` — the `yandex` web-search backend provider.
- `hermes_yandex_search/generative.py` — the `yandex_generative_search` tool.
- `hermes_yandex_search/config.py` — builds a client from environment variables.
- `hermes_yandex_search/__init__.py` — `register(ctx)`, the plugin entry point.

## Running the live E2E tests

The E2E suite (marked `e2e`, deselected by default) hits the **live** Yandex
Search API and, when `hermes-agent` is installed, a live Hermes host.

### Locally

Store your API key in a file (created with restrictive permissions), and the
folder id in a companion file:

```bash
umask 077 && printf '%s' 'your-yandex-search-api-key' > ~/.yandex-search-api-key
umask 077 && printf '%s' 'your-yandex-folder-id'      > ~/.yandex-folder-id
```

(Alternatively, export `YANDEX_API_KEY` and `YANDEX_FOLDER_ID` in your shell —
environment variables take precedence over the files.) Then:

```bash
pytest -m e2e -v
```

The Hermes-host test (`tests/e2e/test_live_hermes.py`) skips automatically unless
`hermes-agent` is importable; install it with `pip install hermes-agent` to run
it.

### On GitHub Actions

The **E2E (live)** workflow (`.github/workflows/e2e.yml`) is manual
(*Actions → E2E (live) → Run workflow*). It reads credentials from a GitHub
[Environment](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment)
so they are never committed to the repo.

If you fork this repository and want to run the live E2E workflow, set up the
Environment once:

1. Open **Settings → Environments → New environment** and name it **`yandex-e2e`**
   (the name the workflow references).
2. Under that environment, add two **secrets**:
   - `YANDEX_API_KEY` — your Yandex Cloud API key.
   - `YANDEX_FOLDER_ID` — your Yandex Cloud folder id.
3. Optionally add an environment **variable** `YANDEX_SEARCH_TYPE`
   (e.g. `SEARCH_TYPE_COM`) to change the default market. You can also override
   it per-run via the workflow input.
4. (Recommended) Add required reviewers to the environment so live runs must be
   approved — this gates access to the paid API.
5. Run the workflow from the **Actions** tab.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the dev
setup and checks to run.

## License

[MIT](LICENSE) © Roman Akinfeev
