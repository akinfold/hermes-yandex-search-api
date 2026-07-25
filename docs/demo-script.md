# Demo recording script

A step-by-step scenario for recording a short (~30–45s) GIF/screencast that
shows the plugin working inside Hermes Agent. Drop the resulting GIF at the top
of the README and use it as the repo's social preview.

## Tools

- Terminal recorder: [`asciinema`](https://asciinema.org) + [`agg`](https://github.com/asciinema/agg)
  to convert to GIF, **or** any screen recorder (Kap, LICEcap, ScreenToGif).
- A terminal at ~100×30, large readable font, dark theme.
- Real Yandex credentials configured in `~/.hermes/.env`
  (`YANDEX_API_KEY`, `YANDEX_FOLDER_ID`).

## Prep (do NOT record this part)

```bash
pip install hermes-yandex-search-api
hermes plugins enable yandex
# ~/.hermes/config.yaml -> web.search_backend: yandex
```

Verify the provider is available:

```bash
hermes plugins list        # 'yandex' should appear as enabled
```

## Scene 1 — web search backend (~15s)

Start Hermes and ask something that forces a fresh web lookup so the model calls
the built-in `web_search` tool (now routed to Yandex):

> Search the web: what is Hermes Agent by Nous Research, and where is its repo?

Capture: the `web_search` tool call and the returned results (titles + URLs from
Yandex). Add an on-screen caption: **"web_search → Yandex backend"**.

## Scene 2 — generative search tool (~20s)

Ask a factual question and nudge the agent toward the generative tool:

> Use yandex_generative_search to answer: what is the Yandex Search API and what does it cost?

Capture: the `yandex_generative_search` call, the synthesised answer, and the
**cited source URLs**. Caption: **"yandex_generative_search → grounded answer + citations"**.

## Post

- Keep it under ~45s and loop-friendly; capture a couple of idle frames at the
  start and end so the GIF reads cleanly.
- Convert with `agg --font-size 20 demo.cast demo.gif` (if using asciinema).
- Reference it in `README.md` (e.g. `![Demo](docs/demo.gif)`) and upload it as
  the repo Social Preview (Settings → General → Social preview).
