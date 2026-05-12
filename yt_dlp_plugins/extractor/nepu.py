# nepu.to extractor.
#
# nepu.to serves video as pure HLS. The master m3u8 URL is embedded
# directly in the rendered page HTML at:
#     https://nepu.to/public/m3u8/<hex-hash>.m3u8
# Once you have the page body, a regex pull is enough -- no iframe, no
# XHR, no JS execution required.
#
# IMPORTANT: nepu.to is fronted by a Cloudflare bot-mitigation challenge.
# A plain HTTP GET from yt-dlp (even with `--impersonate chrome` via
# curl-cffi) returns 403; the response body is the challenge page, not
# the real page, so the m3u8 regex won't match. The challenge clears
# automatically in a real browser within ~10-15s without user input, so
# any headless-browser bypass that handles auto-passing challenges is
# enough -- no Turnstile interactive solving needed.
#
# In production, set `WHYKNOT_FLARESOLVERR_URL` to the base URL of a
# reachable FlareSolverr instance (e.g. `http://flaresolverr:8191` in a
# container-network setup). When the env var is set, the extractor
# routes the page fetch through FlareSolverr's `POST /v1` endpoint with
# `cmd=request.get`, which returns the rendered HTML after the challenge
# has been cleared. When it is unset, the extractor falls back to a
# plain `_download_webpage` -- the parser logic is correct against the
# rendered HTML either way, so a manual `--cookies-from-browser` or
# `--cookies` flow on a workstation that already cleared the challenge
# also works.
#
# The parsing logic in this file is correct against the actual rendered
# HTML -- it's the fetch step upstream of it that requires the bypass.
# The offline test suite (`tests/test_nepu.py`) feeds fixture HTML that
# mirrors the real page shape, so it exercises the parser without
# needing CF clearance.
#
# Two URL families are supported:
#
#   - Movies:   https://nepu.to/movie/<title-slug>-<numeric-id>
#     e.g.      https://nepu.to/movie/night-of-the-living-dead-1968-1968-177219
#
#   - Episodes: https://nepu.to/show/<title-slug>-<numeric-id>/season/<N>/episode/<N>
#     e.g.      https://nepu.to/show/the-beverly-hillbillies-1962-1962-240081/season/1/episode/1
#
# The extractors return the m3u8 URL as a single `m3u8_native` pass-through
# rather than enumerating variants with `_extract_m3u8_formats`. WhyKnot.dev's
# Tier 1 pipeline runs the master through HlsCompatibilityProbe + the
# dynamic-resolution layer server-side, so variant selection happens there;
# enumerating here would duplicate that work and fight the master-filter.
# If a later caller needs the per-variant list directly from yt-dlp, swap
# the return shape to use `_extract_m3u8_formats` -- the page contents and
# regex stay the same.

from __future__ import annotations

import json
import os
import re

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import (
    ExtractorError,
    float_or_none,
    parse_duration,
    unified_strdate,
)

# Env var name + request timeout knobs for the FlareSolverr bypass. The
# 30 s ceiling matches FlareSolverr's own `maxTimeout` default; CF's
# auto-passing challenges typically clear inside 10-15 s, so 30 s is a
# comfortable upper bound that leaves enough margin to retry once before
# the resolver's outer 10 s SoftCeiling fires on the first attempt.
_FLARESOLVERR_ENV = 'WHYKNOT_FLARESOLVERR_URL'
_FLARESOLVERR_TIMEOUT_MS = 30000


_M3U8_RE = r'(https?://(?:www\.)?nepu\.to/public/m3u8/[a-f0-9]+\.m3u8)'

# og:title on nepu is marketing copy, not the canonical title. Two shapes
# observed in the wild:
#   "Watch <Title> (<Year>) Free Online in HD"          -- movies
#   "Watch <Title> (<Year>) Shows & Cartoons Free in HD" -- shows
# Both wrap the real title with a "Watch " prefix and a trailing CTA
# suffix. The h1 carries the clean title ("<Title> (<Year>)") and is
# preferred; this regex pair is the fallback for the rare page where h1
# is missing.
_OG_TITLE_PREFIX_RE = re.compile(r'^\s*Watch\s+', re.IGNORECASE)
_OG_TITLE_SUFFIX_RE = re.compile(
    r'\s+(?:Shows?\s*&\s*Cartoons?\s+)?Free(?:\s+Online)?\s+in\s+HD\s*$',
    re.IGNORECASE,
)


def _strip_og_title_marketing(title):
    if not title:
        return title
    title = _OG_TITLE_PREFIX_RE.sub('', title)
    title = _OG_TITLE_SUFFIX_RE.sub('', title)
    return title.strip() or None


class _NepuFetchMixin:
    """Page fetch with optional FlareSolverr routing.

    When `WHYKNOT_FLARESOLVERR_URL` is set, page fetches go through the
    FlareSolverr `POST /v1` endpoint with `cmd=request.get`. The endpoint
    returns a JSON envelope whose `solution.response` field is the
    rendered HTML after the Cloudflare challenge has been cleared; that
    string substitutes for the page body the regex parsers below expect.

    The env-var gate keeps default behaviour identical for anyone running
    the plugin outside WhyKnot.dev's infrastructure -- without the var,
    this method is a thin wrapper around the standard yt-dlp fetch.
    """

    def _nepu_fetch_page(self, url, video_id):
        fs_base = os.environ.get(_FLARESOLVERR_ENV)
        if not fs_base:
            return self._download_webpage(url, video_id)

        fs_endpoint = fs_base.rstrip('/') + '/v1'
        payload = {
            'cmd': 'request.get',
            'url': url,
            'maxTimeout': _FLARESOLVERR_TIMEOUT_MS,
        }
        resp = self._download_json(
            fs_endpoint, video_id,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            note='Fetching page via FlareSolverr',
            errnote='FlareSolverr request failed')

        if not isinstance(resp, dict) or resp.get('status') != 'ok':
            message = resp.get('message') if isinstance(resp, dict) else None
            raise ExtractorError(
                f'FlareSolverr did not return ok status: {message or "unknown error"}',
                expected=True)

        solution = resp.get('solution') or {}
        body = solution.get('response')
        if not body:
            raise ExtractorError(
                'FlareSolverr response missing solution body', expected=True)
        return body


class NepuMovieIE(_NepuFetchMixin, InfoExtractor):
    IE_NAME = 'whyknot:nepu:movie'
    IE_DESC = 'nepu.to movies'
    _VALID_URL = r'https?://(?:www\.)?nepu\.to/movie/(?P<id>[a-z0-9-]+)'
    _TESTS = [{
        'url': 'https://nepu.to/movie/night-of-the-living-dead-1968-1968-177219',
        'info_dict': {
            'id': 'night-of-the-living-dead-1968-1968-177219',
            'ext': 'mp4',
            'title': 'Night of the Living Dead (1968)',
            'protocol': 'm3u8_native',
        },
        'params': {'skip_download': True},
    }, {
        'url': 'https://www.nepu.to/movie/sample-only-matching-0',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._nepu_fetch_page(url, video_id)

        m3u8_url = self._search_regex(
            _M3U8_RE, webpage, 'video url', fatal=True)

        title = self._html_search_regex(
            r'<h1[^>]*>([^<]+)</h1>', webpage, 'title',
            default=None, fatal=False)
        if not title:
            title = _strip_og_title_marketing(
                self._og_search_title(webpage, default=None))
        if not title:
            raise ExtractorError('Unable to determine movie title', expected=True)

        return {
            'id': video_id,
            'title': title.strip(),
            'url': m3u8_url,
            'ext': 'mp4',
            'protocol': 'm3u8_native',
            'description': self._og_search_description(webpage, default=None),
            'thumbnail': self._og_search_thumbnail(webpage, default=None),
            'release_date': unified_strdate(self._html_search_regex(
                r'(?i)(?:release\s*date|released)[^<]*<[^>]+>\s*([0-9A-Za-z ,/-]+)',
                webpage, 'release date', default=None, fatal=False)),
            'duration': parse_duration(self._html_search_regex(
                r'(?i)(?:duration|runtime)[^<]*<[^>]+>\s*([0-9hms :]+)',
                webpage, 'duration', default=None, fatal=False)),
            'average_rating': float_or_none(self._html_search_regex(
                r'(?i)imdb[^<]*<[^>]+>\s*([0-9]+(?:\.[0-9]+)?)',
                webpage, 'imdb rating', default=None, fatal=False)),
        }


class NepuEpisodeIE(_NepuFetchMixin, InfoExtractor):
    IE_NAME = 'whyknot:nepu:episode'
    IE_DESC = 'nepu.to show episodes'
    _VALID_URL = (
        r'https?://(?:www\.)?nepu\.to/show/'
        r'(?P<show>[a-z0-9-]+)/season/(?P<season>\d+)/episode/(?P<episode>\d+)'
    )
    _TESTS = [{
        'url': 'https://nepu.to/show/the-beverly-hillbillies-1962-1962-240081/season/1/episode/1',
        'info_dict': {
            'id': 'the-beverly-hillbillies-1962-1962-240081-s1e1',
            'ext': 'mp4',
            'series': 'The Beverly Hillbillies (1962)',
            'season_number': 1,
            'episode_number': 1,
            'protocol': 'm3u8_native',
        },
        'params': {'skip_download': True},
    }, {
        'url': 'https://www.nepu.to/show/sample-only-matching-0/season/2/episode/12',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        show_slug = mobj.group('show')
        season = int(mobj.group('season'))
        episode = int(mobj.group('episode'))
        video_id = f'{show_slug}-s{season}e{episode}'
        webpage = self._nepu_fetch_page(url, video_id)

        m3u8_url = self._search_regex(
            _M3U8_RE, webpage, 'video url', fatal=True)

        series = self._html_search_regex(
            r'<h1[^>]*>([^<]+)</h1>', webpage, 'series',
            default=None, fatal=False)
        if not series:
            series = _strip_og_title_marketing(
                self._og_search_title(webpage, default=None))
        if series:
            series = series.strip()

        # On the live show page the episode title sits in the first h2.
        # A trailing "Watch History" h2 also exists; the `?<!Watch ` lookbehind
        # would be over-engineering -- the first h2 is the right one in
        # observed markup.
        episode_title = self._html_search_regex(
            r'<h2[^>]*>([^<]+)</h2>', webpage, 'episode title',
            default=None, fatal=False)
        if episode_title:
            episode_title = episode_title.strip()

        if series and episode_title:
            full_title = f'{series} - {episode_title}'
        elif series:
            full_title = f'{series} S{season:02d}E{episode:02d}'
        else:
            full_title = video_id

        return {
            'id': video_id,
            'title': full_title,
            'url': m3u8_url,
            'ext': 'mp4',
            'protocol': 'm3u8_native',
            'series': series,
            'season_number': season,
            'episode_number': episode,
            'episode': episode_title,
            'description': self._og_search_description(webpage, default=None),
            'thumbnail': self._og_search_thumbnail(webpage, default=None),
            'release_date': unified_strdate(self._html_search_regex(
                r'(?i)(?:air\s*date|aired)[^<]*<[^>]+>\s*([0-9A-Za-z ,/-]+)',
                webpage, 'air date', default=None, fatal=False)),
        }
