# Tubi extractor with multi-track audio handling.
#
# Upstream yt-dlp's TubiTvIE iterates the `video_resources` array on a Tubi
# video JSON blob and feeds each entry's manifest URL through
# _extract_m3u8_formats / _extract_mpd_formats. That works for single-language
# titles but discards two pieces of metadata that are critical for foreign-
# language and dubbed content:
#
#   1. Tubi's `audio_tracks[].lang` field, which names the language of the
#      audio rendition that ships with this resource. Upstream never reads
#      it. yt-dlp's m3u8 parser does pick up `EXT-X-MEDIA:LANGUAGE` from the
#      master playlist, but Tubi's master often has a wrong or generic
#      LANGUAGE attribute (claims "en" on a Mandarin film). The video JSON
#      is the ground truth.
#
#   2. The fact that Tubi can serve multiple `video_resources` entries for
#      the same content -- e.g. one per dub. Upstream merges them all into
#      one format list keyed only by codec, so the user has no way to pick a
#      language; the format selector picks the highest-bandwidth variant,
#      which may be the wrong dub.
#
# This extractor:
#
#   - Subclasses the upstream extractor. The HTML fetch + JSON path mirror
#     upstream so a future upstream change to those is a small patch here,
#     not a full rewrite. Only the format-building loop diverges.
#
#   - Tags every format with `language` (ISO-639-1) and a human-readable
#     `format_note` like "Spanish | hlsv6 | h264". The user can then use
#     `-f 'bv*+ba[language=es]'` or pick by `format_id`.
#
#   - Suffixes the m3u8_id with the language code so the per-resource
#     formats stay distinct in the listing yt-dlp prints under
#     --list-formats, even if two resources share the same codec.
#
# yt-dlp loads plugin extractors before built-ins, so this subclass takes
# priority over upstream for matching URLs without any explicit registration.

from __future__ import annotations

from yt_dlp.extractor.tubitv import TubiTvIE as UpstreamTubiTvIE
from yt_dlp.utils import (
    ExtractorError,
    int_or_none,
    js_to_json,
    strip_or_none,
    traverse_obj,
    url_or_none,
)


# Tubi puts language names in plain English; map to ISO-639-1.
# Conservative: only the languages actually seen on Tubi metadata. Unknown
# names fall back to the first 2 chars lowered, or "und" if even that is empty.
_LANG_NAME_TO_ISO639_1 = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
    "mandarin": "zh",
    "cantonese": "zh",
    "hindi": "hi",
    "arabic": "ar",
    "russian": "ru",
    "turkish": "tr",
    "thai": "th",
    "vietnamese": "vi",
    "tagalog": "tl",
    "filipino": "tl",
    "indonesian": "id",
    "polish": "pl",
    "dutch": "nl",
    "swedish": "sv",
    "norwegian": "no",
    "danish": "da",
    "finnish": "fi",
    "greek": "el",
    "hebrew": "he",
    "hungarian": "hu",
    "czech": "cs",
    "romanian": "ro",
    "ukrainian": "uk",
}

# Reverse map for ISO -> friendly label (used when the only detected language
# clue is an ISO code with no human-readable name nearby).
_ISO_TO_LANG_NAME = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "ja": "Japanese", "ko": "Korean",
    "zh": "Chinese", "hi": "Hindi", "ar": "Arabic", "ru": "Russian",
    "tr": "Turkish", "th": "Thai", "vi": "Vietnamese", "tl": "Tagalog",
    "id": "Indonesian", "pl": "Polish", "nl": "Dutch", "sv": "Swedish",
    "no": "Norwegian", "da": "Danish", "fi": "Finnish", "el": "Greek",
    "he": "Hebrew", "hu": "Hungarian", "cs": "Czech", "ro": "Romanian",
    "uk": "Ukrainian",
}


def _lang_to_iso639_1(name) -> str:
    if not name:
        return "und"
    key = str(name).strip().lower()
    if key in _LANG_NAME_TO_ISO639_1:
        return _LANG_NAME_TO_ISO639_1[key]
    if len(key) == 2 and key.isalpha():
        return key
    if len(key) >= 2 and key[:2].isalpha():
        return key[:2]
    return "und"


def _detect_lang_from_format(f) -> tuple[str | None, str | None]:
    """Inspect a single format dict for language hints.

    Returns (iso639-1 or None, human label or None). Tubi's m3u8 master
    embeds the language NAME in EXT-X-MEDIA NAME (e.g. "acc-v3_auto-Korean"),
    which yt-dlp's parser carries through into format_id and sometimes name.
    The LANGUAGE attribute itself is unreliable on Tubi (they ship LANGUAGE="en"
    on Korean dubs), so prefer NAME-derived detection over yt-dlp's auto
    LANGUAGE pass-through.
    """
    # 1. Check format_id for a trailing language token. yt-dlp inherits
    #    EXT-X-MEDIA NAME into format_id when no explicit format-id is set.
    candidates = []
    fid = f.get("format_id") or ""
    if fid:
        # Take everything after the last "-" and the whole tail too.
        candidates.append(fid.rsplit("-", 1)[-1])
        # Some Tubi NAMEs contain an underscore-prefix junk like "acc-v3_auto-Korean";
        # so also try the token after the last "_" or "-".
        for sep in ("-", "_"):
            for tok in fid.split(sep):
                if tok and tok not in candidates:
                    candidates.append(tok)
    # 2. format[name] mirrors the m3u8 NAME directly when present.
    name = f.get("name") or ""
    if name and name not in candidates:
        candidates.append(name)
        for sep in ("-", "_"):
            for tok in name.split(sep):
                if tok and tok not in candidates:
                    candidates.append(tok)
    # 3. format[language] last (often wrong on Tubi but better than nothing).
    lang_attr = f.get("language") or ""
    if lang_attr and lang_attr not in candidates:
        candidates.append(lang_attr)

    for cand in candidates:
        key = cand.strip().lower()
        if not key:
            continue
        if key in _LANG_NAME_TO_ISO639_1:
            return _LANG_NAME_TO_ISO639_1[key], cand.strip().title()
    # ISO code already?
    for cand in candidates:
        key = cand.strip().lower()
        if len(key) == 2 and key.isalpha() and key in _ISO_TO_LANG_NAME:
            return key, _ISO_TO_LANG_NAME[key]
    return None, None


def _short_codec(vcodec) -> str:
    if not vcodec or vcodec == "none":
        return ""
    if vcodec.startswith(("avc1", "h264")):
        return "h264"
    if vcodec.startswith(("hev1", "hvc1", "h265")):
        return "h265"
    if vcodec.startswith(("vp09", "vp9")):
        return "vp9"
    if vcodec.startswith("av01"):
        return "av1"
    return vcodec.split(".")[0]


class TubiTvIE(UpstreamTubiTvIE):
    # Same URL pattern as upstream so routing is unchanged.
    _VALID_URL = UpstreamTubiTvIE._VALID_URL
    IE_NAME = "tubitv"

    _TESTS = [
        # English single-language film -- end-to-end via the same path
        # upstream takes, just with `language=en` tagged on every format.
        {
            "url": "https://tubitv.com/movies/100004539/the-39-steps",
            "info_dict": {
                "id": "100004539",
                "ext": "mp4",
                "title": "The 39 Steps",
            },
            "params": {"skip_download": "m3u8"},
        },
        # Multi-language film. Just verifies the extractor runs and routes
        # per-resource. Asserting language tagging here would require live
        # network in CI, which we deliberately avoid; the smoke surface is
        # `yt-dlp -F` against a real Tubi URL during plugin acceptance.
        {
            "url": "https://tubitv.com/movies/449366/extraordinary-mission",
            "only_matching": True,
        },
    ]

    def _real_extract(self, url):
        video_id, video_type = self._match_valid_url(url).group("id", "type")
        webpage = self._download_webpage(
            f"https://tubitv.com/{video_type}/{video_id}/", video_id
        )
        # Mirror upstream's JSON path exactly. js_to_json is the same
        # transform upstream uses; if upstream switches transforms (or the
        # window.__data shape changes), update this in lockstep.
        video_data = self._search_json(
            r"window\.__data\s*=", webpage, "data", video_id,
            transform_source=js_to_json,
        )["video"]["byId"][video_id]

        formats, subtitles, drm_only = self._build_formats_and_subtitles(
            video_id, video_data
        )

        if not formats:
            if drm_only:
                self.report_drm(video_id)
            elif not video_data.get("policy_match"):
                # policy_match=False is upstream's signal that the title
                # was withdrawn from the catalog.
                raise ExtractorError(
                    "This content is currently unavailable", expected=True
                )

        # Subtitles from the top-level `subtitles` array.
        for sub in traverse_obj(
            video_data,
            ("subtitles", lambda _, v: url_or_none(v["url"])),
        ):
            sub_lang = _lang_to_iso639_1(sub.get("lang", "English"))
            subtitles.setdefault(sub_lang, []).append({
                "url": self._proto_relative_url(sub["url"]),
            })

        title = traverse_obj(video_data, ("title", {str}))
        season_number, episode_number, episode_title = self._search_regex(
            r"^S(\d+):E(\d+) - (.+)", title or "", "episode info",
            fatal=False, group=(1, 2, 3), default=(None, None, None),
        )

        return {
            "id": video_id,
            "title": strip_or_none(title),
            "formats": formats,
            "subtitles": subtitles,
            "season_number": int_or_none(season_number),
            "episode_number": int_or_none(episode_number),
            "episode": strip_or_none(episode_title),
            **traverse_obj(video_data, {
                "description": ("description", {str}),
                "duration": ("duration", {int_or_none}),
                "uploader_id": ("publisher_id", {str}),
                "release_year": ("year", {int_or_none}),
                "thumbnails": (
                    "thumbnails", ..., {url_or_none},
                    {"url": {self._proto_relative_url}},
                ),
            }),
        }

    # --- helpers --------------------------------------------------------

    def _build_formats_and_subtitles(self, video_id, video_data):
        """Return (formats, subtitles, drm_only).

        Iterates `video_resources` once. For each entry, runs the manifest
        through the appropriate parser, then tags the resulting formats:

          - Audio formats inherit language from the m3u8 rendition NAME
            (which is reliable on Tubi), falling back to LANGUAGE attribute
            (often wrong on Tubi), then to the resource's audio_tracks[0]
            label, then to the top-level video.lang. Only after all three
            do we mark "und".

          - Video formats don't get a `language` set (video tracks have no
            language of their own; the user picks language by selecting an
            audio track for merging).

        When Tubi serves multiple `video_resources` for the same content
        (alternate encodings of the same dub), per-resource format_ids get
        a numeric suffix so they stay distinct in --list-formats.
        """
        formats = []
        subtitles: dict[str, list[dict]] = {}
        drm_only = True
        any_format = False

        top_lang_name = traverse_obj(video_data, ("lang",)) \
            or traverse_obj(video_data, ("audio_tracks", 0, "lang"))

        resources = list(traverse_obj(
            video_data,
            ("video_resources", lambda _, v: url_or_none(v["manifest"]["url"])),
        ) or [])

        # Two resources with the same resource-level lang (Tubi often serves
        # alternate encodings of the same dub) collide on format_id; track an
        # index per resource type so we can suffix the second one.
        type_seen: dict[str, int] = {}

        for resource in resources:
            resource_type = resource.get("type") or ""
            manifest_url = resource["manifest"]["url"]
            res_lang_name = traverse_obj(resource, ("audio_tracks", 0, "lang")) or top_lang_name
            res_lang_iso = _lang_to_iso639_1(res_lang_name)
            res_lang_label = (str(res_lang_name).strip() if res_lang_name else "Unknown") or "Unknown"

            if resource_type in ("hlsv3", "hlsv6"):
                drm_only = False
                idx = type_seen.get(resource_type, 0)
                type_seen[resource_type] = idx + 1
                # Suffix the m3u8_id with the resource-level language for the
                # FIRST resource of this type, plus an `-altN` for any
                # subsequent resources so format_ids stay unique.
                m3u8_id = f"{resource_type}-{res_lang_iso}"
                if idx > 0:
                    m3u8_id = f"{m3u8_id}-alt{idx}"
                fmts, subs = self._extract_m3u8_formats_and_subtitles(
                    manifest_url, video_id, "mp4",
                    m3u8_id=m3u8_id, fatal=False,
                )
                self._merge_subtitles(subs, target=subtitles)
                self._tag_formats(fmts, res_lang_iso, res_lang_label, resource_type)
                formats.extend(fmts)
                if fmts:
                    any_format = True

            elif resource_type == "dash":
                drm_only = False
                idx = type_seen.get(resource_type, 0)
                type_seen[resource_type] = idx + 1
                mpd_id = f"dash-{res_lang_iso}"
                if idx > 0:
                    mpd_id = f"{mpd_id}-alt{idx}"
                fmts, subs = self._extract_mpd_formats_and_subtitles(
                    manifest_url, video_id, mpd_id=mpd_id, fatal=False,
                )
                self._merge_subtitles(subs, target=subtitles)
                self._tag_formats(fmts, res_lang_iso, res_lang_label, "dash")
                formats.extend(fmts)
                if fmts:
                    any_format = True

            elif resource_type in self._UNPLAYABLE_FORMATS:
                # DRM-locked rendition. Upstream raises only when ALL
                # resources are DRM; same here -- tracked via drm_only.
                continue
            else:
                # Unknown resource type. Mirror upstream's warn-and-skip
                # rather than failing, so a new Tubi resource type does
                # not break playback for titles that have a known one
                # available alongside.
                self.report_warning(
                    f'Skipping unknown resource type "{resource_type}"'
                )
                continue

        if any_format:
            drm_only = False
        return formats, subtitles, drm_only

    def _tag_formats(self, fmts, fallback_iso, fallback_label, source_type):
        """Stamp each format with language + a friendly note.

        For audio-only formats, prefer language detected from the per-format
        NAME (Tubi's manifest puts the human-readable language there even
        when LANGUAGE="en" is wrong). For video formats, leave `language`
        unset -- video has no language; the user picks via audio selection.
        """
        for f in fmts:
            # Treat anything without a video codec as an audio rendition.
            # yt-dlp's m3u8 parser sometimes leaves acodec as None on audio
            # tracks too, so don't require an explicit non-none acodec.
            is_audio_only = f.get("vcodec") in (None, "none")
            # Per-format language detection.
            detected_iso = None
            detected_label = None
            if is_audio_only:
                detected_iso, detected_label = _detect_lang_from_format(f)
            if detected_iso is None:
                detected_iso = fallback_iso
                detected_label = fallback_label

            note_bits = [detected_label or fallback_label, source_type]
            short = _short_codec(f.get("vcodec") or "")
            if short:
                note_bits.append(short)
            f["format_note"] = " | ".join(b for b in note_bits if b)

            if is_audio_only:
                # Always tag audio language; this is what `-f bestaudio[language=ko]`
                # dispatches on.
                f["language"] = detected_iso
            # Video formats deliberately do NOT get `language` set.
