# Tubi extractor regression corpus

URLs the plugin's `tubi.TubiTvIE` is expected to handle. Source for both manual smoke testing and the on-acceptance verification matrix.

Run a corpus check with:

```
for url in $(awk -F'|' '/^\| https:/ {print $2}' tests/tubi_corpus.md | tr -d ' '); do
  echo "=== $url ==="
  yt-dlp --no-warnings -F "$url" 2>&1 | tail -8
done
```

The command picks the URL out of column 2 of every table row, runs `-F`, prints the last 8 lines (the format table). Add a new row to the table to extend the corpus.

## Conventions

- Audio-only formats should be tagged with the correct `language` ISO 639-1 code in the `[xx] Label` prefix on the MORE INFO column.
- Video-only formats deliberately have no `language` set (video has no language; the user picks via audio selection).
- When Tubi serves multiple `video_resources` entries for the same content (alternate encodings of the same dub), the second-onwards resource gets an `-altN` suffix in the format_id so listings stay unique.
- Multi-language titles must be selectable with `-f 'bv*+ba[language=XX]'` where XX is the ISO code from the corpus row.

## Catalog

| URL | Category | Notes |
| --- | --- | --- |
| https://tubitv.com/movies/601977/hallucinations | Single-language film, hlsv6 split | Reported failure case for the WhyKnot proxy. yt-dlp resolves it directly; node-side selector strings are the proxy gap, not yt-dlp. Format list: 1 audio-only + 3 video-only. All tagged `[en]`. |
| https://tubitv.com/movies/100046547/el-infierno | Older muxed (hlsv3) | No separate audio rendition; 3 muxed video formats with `mp4a.40.2` baked in. Tagged `[es]` Spanish. Verifies the plugin doesn't break on the older Tubi format. |
| https://tubitv.com/movies/100009047/alienoid-dubbed | hlsv6, two video_resources | Tubi serves two manifests of the same English content (alternate codec ladders). Plugin disambiguates with `-alt1` suffix on the second. Both tagged `[en]`. |
| https://tubitv.com/movies/100046495/the-housemaid | True multi-language film | Korean original + English dub in a single video_resources entry (two `EXT-X-MEDIA` audio renditions). Plugin tags the Korean rendition `[ko] Korean`, English `[en] English`. `-f 'bv*+ba[language=ko]'` must select the Korean track. |
| https://tubitv.com/movies/100013541/destino-mara | 1080p Spanish, two resources | Spanish, two video_resources entries, `-alt1` suffix applied. Default selector picks `hlsv6-es-3254 + Spanish audio`. |
| https://tubitv.com/movies/100025534/transit | German, two resources | German film, two video_resources, plugin tags `[de] German`. Default selector picks German audio. |
| https://tubitv.com/movies/100056029/mary-j-blige-s-family-affair | Recent (2025) catalog single-track | Verifies recent-catalog manifest shape. 1 audio + 5 video, all `[en]`. |
| https://tubitv.com/movies/100015141/la-venganza-del-pantera | Older Spanish, no subtitles | 480p ceiling, single Spanish audio, no subtitles array. |
| https://tubitv.com/movies/100011594/el-verdugo-escarlata-subtitulado | Italian audio | Italian title (single audio), no English subs. Verifies the `it` mapping in the lang table. |
| https://tubitv.com/movies/100054182/el-caso-monroy | Spanish audio + Spanish subtitles | Subtitles array populated; verifies subtitle pass-through. |
| https://tubitv.com/movies/100033346/la-leyenda-de-la-nahuala | Animated Spanish | Animated; same shape as a regular Spanish film. |
| https://tubitv.com/movies/100002086/x | Short documentary | Short duration, single audio, no subtitles. Edge case for sparse JSON metadata. |
| https://tubitv.com/tv-shows/621108/s01-e02-episode-2 | TV episode | URL shape `/tv-shows/<id>/...` instead of `/movies/<id>/...`. Same extractor handles both. Single audio. |
| https://tubitv.com/tv-shows/100020080/s01-e01-pilot | DRM-protected | `_UNPLAYABLE_FORMATS` path. Returns clean `This video is DRM protected` error, never silently produces video-only output. |
| https://tubitv.com/movies/100039574/the-running-man | DRM-protected | Same as above. Confirmed via live probe 2026-05-06: returns clean DRM error, no partial output. |

## Holes in the corpus (TODO)

- **Live channels** (`https://tubitv.com/live/...`): Tubi's `/live` page is JS-rendered and the `/oz/videos/.../content` API requires a platform token. Need to extend the extractor (or write a separate `tubitv:live` extractor) before adding live URLs to the corpus.
- **Audio-description tracks**: none of the JSON `audio_tracks[]` entries probed had a `CHARACTERISTICS` flag like `public.accessibility.describes-video`. Either Tubi doesn't ship audio descriptions yet, or only on premium titles. Revisit when an example surfaces.
- **DASH** (`type: dash`): all probed titles ship `hlsv3` or `hlsv6`. The plugin's `dash` branch is exercised by upstream's tests but not by anything in this corpus. Add a DASH URL when one is found.
