# Supported sites

Extractor modules currently shipped in this package. yt-dlp's plugin loader walks `yt_dlp_plugins.extractor.*` automatically; co-residency in the same Python environment is the only install requirement.

| Module | Site | Classes | URL families |
| --- | --- | --- | --- |
| `placeholder.py` | `plugin-test.whyknot.dev` | `WhyKnotPluginPlaceholderIE` | `https://plugin-test.whyknot.dev/test/<id>` (offline-safe sentinel for CI / release smoke / server update smoke) |
| `nepu.py` | `nepu.to` | `NepuMovieIE` | `https://nepu.to/movie/<slug>` |
|  |  | `NepuEpisodeIE` | `https://nepu.to/show/<slug>/season/<N>/episode/<N>` |

## nepu.to notes

- HLS pass-through: the embedded `nepu.to/public/m3u8/<hash>.m3u8` is returned as a single `m3u8_native` URL, not enumerated through `_extract_m3u8_formats`. Variant selection happens server-side in WhyKnot.dev's Tier 1 pipeline.
- Fetch story: nepu.to is fronted by a Cloudflare bot challenge (`Cf-Mitigated: challenge`). A plain HTTP GET returns 403 even with `yt-dlp --impersonate chrome`. Production fetches need one of:
  - `--cookies-from-browser <browser>` so a `cf_clearance` cookie from a browser session that already cleared the challenge is presented.
  - A FlareSolverr-style service that runs headless Chromium, solves the challenge, and returns the rendered HTML or cookies.
  - A real browser session co-located with the resolver.
- The parser itself is correct against the rendered HTML once that is available. Offline regression coverage lives in `tests/test_nepu.py` against inline HTML fixtures that mirror the live page shape.

## Adding a new site

See the [Project README](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins#get-a-new-extractor-in-production) for the full add-an-extractor walkthrough. In short:

1. Create `yt_dlp_plugins/extractor/<hostname>.py` with one or more `InfoExtractor` subclasses.
2. Add an offline pytest covering URL regex matching and the parser against inline HTML fixtures.
3. Push to `main`. CI runs on Python 3.10-3.13; on green, the next nightly cron (or the immediate webhook) lands the change on each WhyKnot.dev node.
