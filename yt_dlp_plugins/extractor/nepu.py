# nepu.to extractor.
#
# Two-step resolve:
#
#   1. GET the movie/episode page. The page is fronted by a Cloudflare
#      bot-mitigation challenge and serves a single-page-app shell with
#      no stream URL in the static HTML. The shell contains a hidden
#      "embed id" on a player-source anchor:
#          <a ... data-embed="<numeric-id>" id="videoSource" ...>
#      That id is the database key for the source variant, NOT the
#      slug-trailing numeric id ("254078" in a URL like
#      .../night-of-the-living-dead-1968-1968-177219). Movies and
#      episodes both follow this shape; on titles with multiple sources
#      the dropdown lists additional anchors -- this extractor picks
#      the first match for now.
#
#   2. POST `id=<embed-id>` to https://nepu.to/ajax/embed with
#      X-Requested-With: XMLHttpRequest. The server replies with a
#      one-line `<script>new Playerjs({ file: [{ "file":
#      "/public/m3u8/<hash>.m3u8", ... }] });</script>` snippet plus a
#      `setTimeout(fetch("/delete_file.php?file=<hash>.m3u8"))` block
#      that removes the freshly-generated playlist a few seconds after
#      a real browser would start playback. The delete is client-side
#      only -- it doesn't fire from this code path, but downstream
#      consumers of the returned URL should fetch promptly.
#
# Cloudflare cookies + a matching User-Agent are required for both
# steps. When `WHYKNOT_FLARESOLVERR_URL` is set (the WhyKnot.dev
# deployment shape), step 1 goes through a FlareSolverr-compatible
# bypass service that solves the CF interstitial, and the resulting
# cookies + user-agent are injected into yt-dlp's cookiejar so step 2
# (and the eventual m3u8 download) carry the right session. Without
# the env var the extractor falls back to a plain `_download_webpage`,
# which means a manual `--cookies-from-browser` / `--cookies` flow on
# a workstation that already cleared the challenge is the supported
# alternative.
#
# Two URL families are supported:
#
#   - Movies:   https://nepu.to/movie/<title-slug>-<numeric-id>
#     e.g.      https://nepu.to/movie/night-of-the-living-dead-1968-1968-177219
#
#   - Episodes: https://nepu.to/show/<title-slug>-<numeric-id>/season/<N>/episode/<N>
#     e.g.      https://nepu.to/show/the-beverly-hillbillies-1962-1962-240081/season/1/episode/1
#
# The returned info_dict carries the m3u8 URL as an `m3u8_native`
# pass-through (single media playlist; no master). WhyKnot.dev's Tier 1
# pipeline handles variant selection further down, so duplicating that
# logic here would only fight it.

from __future__ import annotations

import http.cookiejar
import json
import os
import re
import tempfile
import time
import urllib.parse

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.networking import Request
from yt_dlp.utils import (
    ExtractorError,
    float_or_none,
    parse_duration,
    unified_strdate,
)


# Env var the bypass service URL is read from. The name is FlareSolverr-
# shaped for compatibility -- any service that speaks the FlareSolverr
# POST /v1 wire (e.g. Byparr, stock FlareSolverr) works here.
_BYPASS_ENV = 'WHYKNOT_FLARESOLVERR_URL'
# In-payload solver budget. FlareSolverr reads this as milliseconds,
# Byparr as seconds. We split the difference by sending the largest
# value that is still sane in either unit: 30000 means "30 s" to
# FlareSolverr and "much longer than we care about, but solver will
# return early" to Byparr. Real solve wall-clock is ~10-15 s.
_BYPASS_MAX_TIMEOUT = 30000
# Socket timeout on the HTTP call to the bypass service. yt-dlp's
# default socket_timeout is 20 s which is too tight: Byparr/Camoufox
# routinely takes 14 s end-to-end on a cold solve, leaving almost no
# slack for the TCP handshake + JSON parse. Bumped to 60 s so a
# variance-driven 17-25 s solve still fits comfortably.
_BYPASS_HTTP_TIMEOUT = 60

# Bypass session cache. The first /v1 solve costs ~14 s; we persist the
# resulting cf_clearance + PHPSESSID + UA to disk so subsequent resolves
# skip the solver entirely and complete in ~1 s. cf_clearance typically
# lasts 1-2 hours -- 30 minutes is a conservative refresh cadence that
# leaves headroom against early CF rotation. On any signal that the
# cache is stale (page fetch 403, /ajax/embed 4xx, missing data-embed)
# we invalidate and fall through to a Byparr refresh.
# Path: <state-dir>/upstream_session/nepu.to.json. The per-host
# subdirectory is the contract WhyKnot.dev's MediaProxy reads from when
# it needs the same session for its own upstream fetches -- the
# extractor and the proxy share a single source of truth on disk, no
# IPC between them.
_CACHE_SUBDIR = 'upstream_session'
_CACHE_HOST = 'nepu.to'
_CACHE_FILENAME = _CACHE_HOST + '.json'
_CACHE_TTL_SECONDS = 30 * 60
# Override for the cache directory. Defaults to /app/state (the WhyKnot.dev
# deployment, where /var/lib/whyknot/state is bind-mounted) and falls back
# to a per-user temp dir for everyone else.
_CACHE_DIR_ENV = 'WHYKNOT_PLUGIN_STATE_DIR'

_EMBED_API = 'https://nepu.to/ajax/embed'
_DATA_EMBED_RE = re.compile(r'data-embed="(\d+)"')
_PLAYERJS_FILE_RE = re.compile(r'"file"\s*:\s*"([^"]+\.m3u8)"')


def _nepu_cache_dir():
    """Resolve the cache directory. Configurable via WHYKNOT_PLUGIN_STATE_DIR.
    Falls back to /app/state when present (WhyKnot.dev shape) and to a
    per-user temp dir otherwise. Best-effort: a failure to create the dir
    just disables the cache and the extractor pays the bypass cost on
    every resolve as it did before.
    """
    override = os.environ.get(_CACHE_DIR_ENV)
    if override:
        return override
    if os.path.isdir('/app/state'):
        return '/app/state'
    return os.path.join(tempfile.gettempdir(), 'whyknot-yt-dlp-plugins')


def _nepu_cache_path():
    return os.path.join(_nepu_cache_dir(), _CACHE_SUBDIR, _CACHE_FILENAME)


def _nepu_load_cached_session():
    """Returns (cookies, user_agent) if a fresh cache entry exists, else None.

    cookies are the Playwright-shaped dicts the bypass service returns
    (name/value/domain/path/secure/expires). Filtered to nepu.to so a
    later cookie-string formatter doesn't have to re-filter.
    """
    try:
        with open(_nepu_cache_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None

    saved_at = data.get('saved_at', 0)
    try:
        saved_at = float(saved_at)
    except (TypeError, ValueError):
        return None
    if time.time() - saved_at > _CACHE_TTL_SECONDS:
        return None

    cookies = [c for c in (data.get('cookies') or [])
               if isinstance(c, dict) and 'nepu.to' in (c.get('domain') or '')]
    # cf_clearance is the gate. Without it the cached session is useless.
    if not any(c.get('name') == 'cf_clearance' for c in cookies):
        return None

    ua = data.get('user_agent') or ''
    return cookies, ua


def _nepu_save_session(cookies, user_agent):
    """Atomically persist the session. Filters to nepu.to cookies on the way
    in so we don't sprinkle hcaptcha / other-origin cookies into the cache
    file. Best-effort: silently no-ops on directory or write failure."""
    cache_path = _nepu_cache_path()
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    except OSError:
        return

    filtered = [c for c in (cookies or [])
                if isinstance(c, dict) and 'nepu.to' in (c.get('domain') or '')]
    if not filtered:
        return

    tmp_path = cache_path + '.tmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump({
                'saved_at': int(time.time()),
                'user_agent': user_agent or '',
                'cookies': filtered,
            }, f)
        os.replace(tmp_path, cache_path)
    except OSError:
        try: os.unlink(tmp_path)
        except OSError: pass


def _nepu_invalidate_cache():
    """Remove the cache file when we have signal that the cookies are stale.
    Best-effort: missing file is fine."""
    try:
        os.unlink(_nepu_cache_path())
    except OSError:
        pass

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


class _NepuResolverMixin:
    """Shared resolve logic for movies and episodes.

    The two extractor classes only differ in URL pattern, video_id
    shape, and metadata parsing -- the page-fetch + embed-POST + m3u8
    parse is identical, so it lives here once.
    """

    def _nepu_fetch_via_bypass(self, fs_base, url, video_id):
        """Drive the FlareSolverr-compatible bypass to get HTML + cookies + UA."""
        fs_endpoint = fs_base.rstrip('/') + '/v1'
        payload = json.dumps({
            'cmd': 'request.get',
            'url': url,
            'maxTimeout': _BYPASS_MAX_TIMEOUT,
        }).encode('utf-8')
        # Pre-build the Request so we can attach a longer per-request
        # socket timeout via extensions. yt-dlp's networking layer
        # honours extensions['timeout'] and merges it with the global
        # socket_timeout in YoutubeDL params.
        req = Request(
            fs_endpoint,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
            extensions={'timeout': _BYPASS_HTTP_TIMEOUT},
        )
        resp = self._download_json(
            req, video_id,
            note='Fetching page via bypass service',
            errnote='Bypass service request failed')

        if not isinstance(resp, dict) or resp.get('status') != 'ok':
            message = resp.get('message') if isinstance(resp, dict) else None
            raise ExtractorError(
                f'Bypass service did not return ok status: {message or "unknown error"}',
                expected=True)

        solution = resp.get('solution') or {}
        page_html = solution.get('response') or ''
        if not page_html:
            raise ExtractorError(
                'Bypass response missing solution body', expected=True)
        return (
            page_html,
            solution.get('cookies') or [],
            solution.get('userAgent') or solution.get('user_agent') or '',
        )

    def _nepu_inject_cookies(self, cookies):
        """Push Playwright-shaped cookies into yt-dlp's cookiejar.

        We only care about cookies whose domain is nepu.to (the bypass
        sometimes also returns cookies from other origins it touched
        during the solve, like hCaptcha; those would confuse the
        cookiejar's domain matching if blindly admitted).
        """
        try:
            jar = self._downloader.cookiejar
        except AttributeError:
            return
        for c in cookies:
            name = c.get('name')
            domain = c.get('domain') or ''
            if not name or 'nepu.to' not in domain:
                continue
            expires = c.get('expires')
            try:
                expires = int(expires) if expires and float(expires) > 0 else None
            except (TypeError, ValueError):
                expires = None
            ck = http.cookiejar.Cookie(
                version=0, name=name, value=c.get('value', ''),
                port=None, port_specified=False,
                domain=domain, domain_specified=True,
                domain_initial_dot=domain.startswith('.'),
                path=c.get('path', '/'), path_specified=True,
                secure=bool(c.get('secure', False)),
                expires=expires,
                discard=False, comment=None, comment_url=None, rest={},
                rfc2109=False,
            )
            jar.set_cookie(ck)

    @staticmethod
    def _nepu_format_cookie_header(cookies):
        if not cookies:
            return ''
        return '; '.join(
            f"{c['name']}={c['value']}" for c in cookies
            if c.get('name') and c.get('value') is not None
        )

    def _nepu_post_embed(self, url, video_id, embed_id, user_agent):
        """POST /ajax/embed and return the response body. Cookies must already
        be in yt-dlp's cookiejar (caller is responsible)."""
        post_headers = {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://nepu.to',
            'Referer': url,
            'Accept': '*/*',
        }
        if user_agent:
            post_headers['User-Agent'] = user_agent
        return self._download_webpage(
            _EMBED_API, video_id,
            data=urllib.parse.urlencode({'id': embed_id}).encode(),
            headers=post_headers,
            note='Resolving stream via /ajax/embed',
            errnote='Stream resolution failed')

    @staticmethod
    def _nepu_parse_m3u8_url(embed_html):
        mm = _PLAYERJS_FILE_RE.search(embed_html)
        if not mm:
            return None
        m3u8_url = mm.group(1)
        if m3u8_url.startswith('/'):
            m3u8_url = 'https://nepu.to' + m3u8_url
        return m3u8_url

    def _nepu_resolve(self, url, video_id):
        """Returns (page_html, m3u8_url, user_agent, cookie_header).

        Two paths:

          Fast path -- a cached bypass session exists and isn't stale.
          Skip the bypass GET, fetch the page through yt-dlp with the
          cached cookies + UA in the jar, POST /ajax/embed, parse m3u8.
          Any failure here (bad regex, 4xx on embed) is treated as
          cookie-expiry and falls through to the slow path. Wall-clock
          for a cache hit is ~1 s -- well inside the dispatcher's race
          deadline.

          Slow path -- no cache or cache expired/invalidated. Call the
          bypass service to acquire a fresh CF session, persist it to
          disk for the next ~30 minutes, then run the same /ajax/embed
          flow. Wall-clock ~14-25 s.

        Without the bypass env var the extractor falls back to a plain
        yt-dlp page fetch + embed POST; this succeeds when a manual
        --cookies-from-browser flow on a workstation that already
        cleared the challenge is in play.
        """
        fs_base = os.environ.get(_BYPASS_ENV)

        # Fast path: try the cached session before paying the bypass cost.
        if fs_base:
            cached = _nepu_load_cached_session()
            if cached:
                try:
                    return self._nepu_resolve_with_cached_session(
                        url, video_id, cached[0], cached[1])
                except ExtractorError as e:
                    # Anything goes wrong with the cached path -- expired
                    # cookies, IP rotation, server-side session purge --
                    # we invalidate and refresh via the bypass.
                    self.report_warning(
                        f'nepu cached session failed ({str(e)[:160]}); refreshing via bypass')
                    _nepu_invalidate_cache()

        # Slow path: bypass refresh.
        if fs_base:
            page_html, cookies, user_agent = self._nepu_fetch_via_bypass(
                fs_base, url, video_id)
            self._nepu_inject_cookies(cookies)
            _nepu_save_session(cookies, user_agent)
        else:
            page_html = self._download_webpage(url, video_id)
            cookies = []
            user_agent = ''

        m = _DATA_EMBED_RE.search(page_html)
        if not m:
            raise ExtractorError(
                'Unable to find embed id (data-embed) in page', expected=True)
        embed_id = m.group(1)
        embed_html = self._nepu_post_embed(url, video_id, embed_id, user_agent)
        m3u8_url = self._nepu_parse_m3u8_url(embed_html)
        if not m3u8_url:
            raise ExtractorError(
                'Unable to extract m3u8 URL from embed response', expected=True)
        cookie_header = self._nepu_format_cookie_header(
            [c for c in cookies if 'nepu.to' in (c.get('domain') or '')])
        return page_html, m3u8_url, user_agent, cookie_header

    def _nepu_resolve_with_cached_session(self, url, video_id, cookies, user_agent):
        """Cached-session fast path. Raises ExtractorError on any failure
        so the caller can invalidate and refresh."""
        self._nepu_inject_cookies(cookies)
        page_headers = {'User-Agent': user_agent} if user_agent else None
        page_html = self._download_webpage(
            url, video_id, headers=page_headers,
            note='Fetching page (cached bypass session)',
            errnote='Cached-session page fetch failed')

        m = _DATA_EMBED_RE.search(page_html)
        if not m:
            # CF likely served the challenge page because cookies expired.
            raise ExtractorError(
                'No data-embed in cached-session page response (cookies likely expired)',
                expected=True)
        embed_id = m.group(1)

        embed_html = self._nepu_post_embed(url, video_id, embed_id, user_agent)
        m3u8_url = self._nepu_parse_m3u8_url(embed_html)
        if not m3u8_url:
            raise ExtractorError(
                'No m3u8 in cached-session embed response (session likely stale)',
                expected=True)
        cookie_header = self._nepu_format_cookie_header(cookies)
        return page_html, m3u8_url, user_agent, cookie_header


def _http_headers_for(url, user_agent, cookie_header=''):
    """Build the per-format http_headers dict the extractor returns.

    The Referer is always the page URL (the segment CDN whitelists referrers
    from the page that issued the playlist). User-Agent and Cookie come from
    the bypass solver session when one ran. Downstream consumers (yt-dlp's
    own m3u8 download, WhyKnot.dev's MediaProxy) use this dict verbatim --
    Cookie carries cf_clearance + PHPSESSID so the m3u8 fetch validates
    server-side without a second bypass round-trip.
    """
    headers = {'Referer': url}
    if user_agent:
        headers['User-Agent'] = user_agent
    if cookie_header:
        headers['Cookie'] = cookie_header
    return headers


class NepuMovieIE(_NepuResolverMixin, InfoExtractor):
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
        page_html, m3u8_url, user_agent, cookie_header = self._nepu_resolve(url, video_id)

        title = self._html_search_regex(
            r'<h1[^>]*>([^<]+)</h1>', page_html, 'title',
            default=None, fatal=False)
        if not title:
            title = _strip_og_title_marketing(
                self._og_search_title(page_html, default=None))
        if not title:
            raise ExtractorError('Unable to determine movie title', expected=True)

        return {
            'id': video_id,
            'title': title.strip(),
            'url': m3u8_url,
            'ext': 'mp4',
            'protocol': 'm3u8_native',
            'http_headers': _http_headers_for(url, user_agent, cookie_header),
            'description': self._og_search_description(page_html, default=None),
            'thumbnail': self._og_search_thumbnail(page_html, default=None),
            'release_date': unified_strdate(self._html_search_regex(
                r'(?i)(?:release\s*date|released)[^<]*<[^>]+>\s*([0-9A-Za-z ,/-]+)',
                page_html, 'release date', default=None, fatal=False)),
            'duration': parse_duration(self._html_search_regex(
                r'(?i)(?:duration|runtime)[^<]*<[^>]+>\s*([0-9hms :]+)',
                page_html, 'duration', default=None, fatal=False)),
            'average_rating': float_or_none(self._html_search_regex(
                r'(?i)imdb[^<]*<[^>]+>\s*([0-9]+(?:\.[0-9]+)?)',
                page_html, 'imdb rating', default=None, fatal=False)),
        }


class NepuEpisodeIE(_NepuResolverMixin, InfoExtractor):
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
        page_html, m3u8_url, user_agent, cookie_header = self._nepu_resolve(url, video_id)

        series = self._html_search_regex(
            r'<h1[^>]*>([^<]+)</h1>', page_html, 'series',
            default=None, fatal=False)
        if not series:
            series = _strip_og_title_marketing(
                self._og_search_title(page_html, default=None))
        if series:
            series = series.strip()

        # On the live show page the episode title sits in the first h2.
        # A trailing "Watch History" h2 also exists; the `?<!Watch ` lookbehind
        # would be over-engineering -- the first h2 is the right one in
        # observed markup.
        episode_title = self._html_search_regex(
            r'<h2[^>]*>([^<]+)</h2>', page_html, 'episode title',
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
            'http_headers': _http_headers_for(url, user_agent, cookie_header),
            'series': series,
            'season_number': season,
            'episode_number': episode,
            'episode': episode_title,
            'description': self._og_search_description(page_html, default=None),
            'thumbnail': self._og_search_thumbnail(page_html, default=None),
            'release_date': unified_strdate(self._html_search_regex(
                r'(?i)(?:air\s*date|aired)[^<]*<[^>]+>\s*([0-9A-Za-z ,/-]+)',
                page_html, 'air date', default=None, fatal=False)),
        }
