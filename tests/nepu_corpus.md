# nepu.to test corpus

URLs the extractor is developed and smoke-tested against. The pytest
suite (`tests/test_nepu.py`) covers regex + parse logic offline; this
file documents canonical live URLs for `yt-dlp -F` / `yt-dlp --simulate`
runs against the real site.

## Movies

| URL | Slug captured as `id` |
| --- | --- |
| https://nepu.to/movie/night-of-the-living-dead-1968-1968-177219 | `night-of-the-living-dead-1968-1968-177219` |

## Show episodes

| URL | Synthesised `id` |
| --- | --- |
| https://nepu.to/show/the-beverly-hillbillies-1962-1962-240081/season/1/episode/1 | `the-beverly-hillbillies-1962-1962-240081-s1e1` |

## Smoke commands

Plugin discovery + extract simulation (no actual segment download):

```
yt-dlp -v --simulate --skip-download \
  "https://nepu.to/movie/night-of-the-living-dead-1968-1968-177219"
```

Expected verbose output line:

```
[debug] Extractor Plugins: ... whyknot:nepu:movie (NepuMovieIE), whyknot:nepu:episode (NepuEpisodeIE)
```

Format listing (network required):

```
yt-dlp -F "https://nepu.to/movie/night-of-the-living-dead-1968-1968-177219"
yt-dlp -F "https://nepu.to/show/the-beverly-hillbillies-1962-1962-240081/season/1/episode/1"
```

The extractor returns a single `m3u8_native` URL; downstream variant
selection is handled server-side in WhyKnot.dev's Tier 1 pipeline.
