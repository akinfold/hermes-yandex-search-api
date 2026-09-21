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
hermes plugins install akinfold/hermes-yandex-search-api/hermes_yandex_search --enable

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
- The Python packages `httpx >= 0.24` and `defusedxml >= 0.7`. Option C (pip)
  installs both; `httpx` already ships with Hermes, but for Option A or B you have
  to install `defusedxml` yourself — see the note under Option B.
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
hermes plugins install akinfold/hermes-yandex-search-api/hermes_yandex_search --enable
```

Note the `/hermes_yandex_search` at the end. The plugin lives in that directory,
not at the repository root, and Hermes reads the manifest from whatever you point
it at. Name the directory and the install is a plugin: Hermes prompts for
`YANDEX_API_KEY` and `YANDEX_FOLDER_ID`, installs under the manifest name
`yandex`, and `--enable` enables that name. It also scans only that directory, so
the tests and workflows in this repository stay out of the security report.

Point it at the repository root instead and the install still appears to succeed,
but it copies a directory with no manifest and no `register(ctx)` in it: Hermes
warns that it "may not be a valid Hermes plugin", asks for nothing, and enables
the repository name, which nothing answers to. There is no error to look for:
what gives it away is `hermes plugins list`, which shows the plugin under its
real name with `not enabled` beside it, because `--enable` wrote the repository
name into `plugins.enabled` and nothing matches it. If you are in that state,
remove `~/.hermes/plugins/hermes-yandex-search-api` and install again with the
directory named — enabling the real name on top of the broken install leaves a
stray entry behind.

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

> **Options A and B need `defusedxml` installed by hand.** Both copy the plugin's
> sources only, and current Hermes releases do not install a plugin's Python
> dependencies. `httpx` ships with Hermes; `defusedxml` does not, so without it the
> plugin fails to load with `ModuleNotFoundError: No module named 'defusedxml'`.
> Install it into the environment Hermes runs in:
>
> ```bash
> pip install 'defusedxml>=0.7'
> ```

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

`hermes plugins install akinfold/hermes-yandex-search-api/hermes_yandex_search`
prompts for both values, because the manifest declares them. Installing any other
way, or declining the prompt, leaves you to add them to `~/.hermes/.env` yourself,
as shown above.

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

The `yandex` backend is search-only: the Yandex Search API returns result
snippets, not page content, so the plugin does not serve `web_extract`. Page
extraction keeps using whichever extract-capable backend Hermes resolves, which
is why the snippet above sets `web.search_backend` rather than `web.backend`.

The `yandex_generative_search` tool becomes available as soon as the plugin is
enabled — no extra configuration needed. It is registered in the `yandex_search`
toolset, which Hermes enables by default; you can switch it off (or back on) per
platform with `hermes tools`.

## The `yandex_generative_search` tool

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `query` | string | yes | The question to answer. Must be a non-empty string. |
| `sites` | array of strings | no | Site domains to restrict the answer's sources to, e.g. `["example.com"]`. The Yandex API accepts up to 5; the plugin forwards the list as it is. Omit it to search the whole web. |

The search market is not a tool parameter; it comes from `YANDEX_SEARCH_TYPE`.

The tool returns a JSON string. On success:

```json
{
  "success": true,
  "answer": "Paris is the capital of France.",
  "sources": [{"url": "https://en.wikipedia.org/wiki/Paris", "title": "Paris", "used_text": ""}],
  "search_queries": ["capital of France"],
  "fixed_query": "",
  "is_answer_rejected": false,
  "is_bullet_answer": false
}
```

- `answer` — the synthesised answer text.
- `sources` — the sources the answer cites (`url`, `title`, `used_text`; the last two may be empty).
- `search_queries` — the queries Yandex actually ran.
- `fixed_query` — the typo-corrected query, or an empty string.
- `is_answer_rejected` — `true` when Yandex declined to answer.
- `is_bullet_answer` — `true` when the answer is formatted as a bullet list.

The tool never raises. Any failure — missing credentials, invalid arguments, an
HTTP or API error — comes back as `{"success": false, "error": "<message>"}`.

## Configuration reference

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `YANDEX_API_KEY` | yes | – | Yandex Cloud API key. |
| `YANDEX_FOLDER_ID` | yes | – | Yandex Cloud folder ("catalog") id. |
| `YANDEX_SEARCH_TYPE` | no | `SEARCH_TYPE_RU` | Search market/domain enum. |
| `YANDEX_SEARCH_API_URL` | no | `https://searchapi.api.cloud.yandex.net` | API base URL override. |

`YANDEX_SEARCH_TYPE` applies to both web and generative search and is case-sensitive:
an unrecognised value makes every call fail with an error naming the accepted values.

The rest of the request options are fixed and cannot be configured. Every request
times out after 30 seconds, and on expiry the call fails with an error such as
`HTTP request to /v2/gen/search failed: ...`. Web search returns at most the number
of results Hermes asks for (clamped to 1–100), one document per site group, first
page only. The family filter stays at `FAMILY_MODE_MODERATE`, Yandex typo correction
is always on for both modes, and region and snippet localisation are left at the
Yandex defaults for the selected market.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

ruff check .          # lint
ruff format --check . # code style
pytest                # unit tests (live E2E tests are deselected by default)
radon cc -s -n C hermes_yandex_search  # complexity gate; must print nothing
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

## Related Hermes plugins

Part of a family of Yandex plugins for Hermes Agent:

- [hermes-yandex-disk](https://github.com/akinfold/hermes-yandex-disk) — browse, read, write, and share files on Yandex Disk (REST API).
- [hermes-yandex-mail](https://github.com/akinfold/hermes-yandex-mail) — search, read, flag, move, and delete Yandex Mail messages over IMAP, and send over SMTP when sending is switched on.
- [hermes-yandex-calendar](https://github.com/akinfold/hermes-yandex-calendar) — list, create, update, respond to, move, and delete Yandex Calendar events (CalDAV).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the dev
setup and checks to run.

## License

[MIT](LICENSE) © Roman Akinfeev
