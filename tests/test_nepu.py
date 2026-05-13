# Offline tests for the nepu.to extractor.
#
# Three layers:
#
#   1. URL regex tests -- parametrised cases that walk the supported and
#      unsupported URL shapes and assert _VALID_URL captures the right
#      groups. Pure pattern matching, no extractor instance, no network.
#
#   2. Resolver / metadata tests -- build a real extractor instance with
#      a stubbed YoutubeDL, monkeypatch the page fetch and the
#      /ajax/embed POST to return inline HTML fixtures, then call
#      `_real_extract` and assert the returned info_dict has the m3u8
#      URL, ext, protocol, http_headers, and metadata we planted.
#
#   3. Bypass-path tests -- when WHYKNOT_FLARESOLVERR_URL is set, the
#      extractor must POST to <base>/v1 first, inject cookies into the
#      yt-dlp cookiejar, and only then POST /ajax/embed.
#
# All fixtures use synthetic slugs and m3u8 hashes so this file is
# self-contained and the tests pass without any live request.

from __future__ import annotations

import json
import re
import urllib.parse

import pytest

from yt_dlp import YoutubeDL

from yt_dlp_plugins.extractor.nepu import (
    NepuMovieIE,
    NepuEpisodeIE,
    _BYPASS_ENV,
    _CACHE_DIR_ENV,
    _CACHE_FILENAME,
    _CACHE_TTL_SECONDS,
    _EMBED_API,
)


# ---------------------------------------------------------------------------
# Inline HTML fixtures
# ---------------------------------------------------------------------------

_FIXTURE_EMBED_ID = '8675309'
_FIXTURE_M3U8_PATH = '/public/m3u8/0123456789.m3u8'
_FIXTURE_M3U8 = 'https://nepu.to' + _FIXTURE_M3U8_PATH

# The movie/episode page no longer carries the m3u8 URL directly. What it
# does carry is a hidden `data-embed="<id>"` on a player-source anchor +
# a play button; the extractor reads that id and POSTs it to /ajax/embed.
_MOVIE_HTML = f"""<!doctype html>
<html>
<head>
  <meta property="og:title" content="Watch Synthetic Movie Title (2024) Free Online in HD">
  <meta property="og:description" content="A synthetic plot summary used only by the test suite.">
  <meta property="og:image" content="https://nepu.to/static/img/synthetic-movie.jpg">
</head>
<body>
  <h1>Synthetic Movie Title (2024)</h1>
  <p>Release date: <span>March 4, 2024</span></p>
  <p>Duration: <span>1h 32m</span></p>
  <p>IMDB: <span>7.4</span></p>
  <div class="nav-player-select dropdown">
    <a class="dropdown-toggle btn-service selected" href="#" data-embed="{_FIXTURE_EMBED_ID}" id="videoSource">Server 1</a>
  </div>
  <div id="player"></div>
  <div class="play-btn" data-id="" data-embed="{_FIXTURE_EMBED_ID}"></div>
</body>
</html>
"""

_EPISODE_HTML = f"""<!doctype html>
<html>
<head>
  <meta property="og:title" content="Watch Synthetic Show (1962) Shows &amp; Cartoons Free in HD">
  <meta property="og:description" content="A synthetic episode description.">
  <meta property="og:image" content="https://nepu.to/static/img/synthetic-episode.jpg">
</head>
<body>
  <h1>Synthetic Show (1962)</h1>
  <h3>Season 1: Episode 1</h3>
  <h2>Pilot Episode</h2>
  <h2>Watch History</h2>
  <p>Air date: <span>September 26, 1962</span></p>
  <a data-embed="{_FIXTURE_EMBED_ID}" id="videoSource"></a>
</body>
</html>
"""

# The shape /ajax/embed actually returns. The setTimeout/delete block is
# included so the m3u8 regex has to skip past it to find the real "file"
# key inside the Playerjs config.
_EMBED_RESPONSE = f"""<script>
    var player = new Playerjs({{
        id: "player",
        file: [{{"file": "{_FIXTURE_M3U8_PATH}", poster: "https://image.tmdb.org/example.jpg"}}]
    }});
    setTimeout(function() {{
        fetch("/delete_file.php?file=0123456789.m3u8");
    }}, 8000);
</script>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extractor(cls, page_html, embed_html=_EMBED_RESPONSE):
    """Build a `cls` instance whose page fetch returns page_html and
    whose /ajax/embed POST returns embed_html.

    Uses a real YoutubeDL as the downloader so the extractor's calls
    into the downloader (logging, format helpers, etc) hit a real
    implementation. We monkeypatch `_download_webpage` to route based
    on the URL argument.
    """
    ydl = YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True})
    ie = cls(ydl)

    captured = {'webpage_calls': []}

    def fake_download_webpage(url_or_request, video_id, *args, **kwargs):
        # _download_webpage receives a URL string when called with a
        # plain url, or a Request object for POSTs. Normalise.
        url = url_or_request if isinstance(url_or_request, str) else url_or_request.url
        entry = {
            'url': url,
            'data': kwargs.get('data'),
            'headers': kwargs.get('headers') or {},
        }
        captured['webpage_calls'].append(entry)
        if _EMBED_API in url:
            return embed_html
        return page_html

    ie._download_webpage = fake_download_webpage  # type: ignore[assignment]
    return ie, captured


# ---------------------------------------------------------------------------
# URL regex tests -- movies
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('url, expected_id', [
    ('https://nepu.to/movie/some-slug-12345', 'some-slug-12345'),
    ('http://nepu.to/movie/some-slug-12345', 'some-slug-12345'),
    ('https://www.nepu.to/movie/some-slug-12345', 'some-slug-12345'),
    ('https://nepu.to/movie/a-b-c-d-99', 'a-b-c-d-99'),
])
def test_movie_valid_url_matches(url, expected_id):
    assert NepuMovieIE.suitable(url)
    match = NepuMovieIE._match_valid_url(url)
    assert match is not None
    assert match.group('id') == expected_id


@pytest.mark.parametrize('url', [
    'https://nepu.to/show/some-slug-12345/season/1/episode/1',  # show, not movie
    'https://example.com/movie/some-slug-12345',                 # wrong host
    'https://nepu.to/movies/some-slug-12345',                    # wrong path ("movies")
    'https://nepu.to/movie/',                                    # empty slug
    'https://nepu.to/',                                          # root
])
def test_movie_valid_url_rejects(url):
    assert not NepuMovieIE.suitable(url)


# ---------------------------------------------------------------------------
# URL regex tests -- episodes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('url, show, season, episode', [
    ('https://nepu.to/show/some-show-1/season/1/episode/1', 'some-show-1', '1', '1'),
    ('https://www.nepu.to/show/some-show-99/season/12/episode/3',
     'some-show-99', '12', '3'),
    ('http://nepu.to/show/a-b-c-7/season/2/episode/15', 'a-b-c-7', '2', '15'),
])
def test_episode_valid_url_matches(url, show, season, episode):
    assert NepuEpisodeIE.suitable(url)
    match = NepuEpisodeIE._match_valid_url(url)
    assert match is not None
    assert match.group('show') == show
    assert match.group('season') == season
    assert match.group('episode') == episode


@pytest.mark.parametrize('url', [
    'https://nepu.to/movie/some-slug-12345',                          # movie, not episode
    'https://nepu.to/show/some-show-1/season/1',                      # missing /episode/N
    'https://nepu.to/show/some-show-1/episode/1',                     # missing /season/N
    'https://nepu.to/show/some-show-1/season/abc/episode/1',          # non-numeric season
    'https://example.com/show/some-show-1/season/1/episode/1',        # wrong host
])
def test_episode_valid_url_rejects(url):
    assert not NepuEpisodeIE.suitable(url)


# ---------------------------------------------------------------------------
# IE identity sanity
# ---------------------------------------------------------------------------

def test_ie_names():
    assert NepuMovieIE.IE_NAME == 'whyknot:nepu:movie'
    assert NepuEpisodeIE.IE_NAME == 'whyknot:nepu:episode'


# ---------------------------------------------------------------------------
# Resolver tests -- _real_extract against inline HTML fixtures (no env var)
# ---------------------------------------------------------------------------

def test_movie_extract_posts_embed_id_and_returns_m3u8(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    url = 'https://nepu.to/movie/synthetic-movie-1'
    ie, captured = _make_extractor(NepuMovieIE, _MOVIE_HTML)

    info = ie._real_extract(url)

    # Two webpage fetches: the movie page, then the /ajax/embed POST.
    assert len(captured['webpage_calls']) == 2
    assert captured['webpage_calls'][0]['url'] == url
    embed_call = captured['webpage_calls'][1]
    assert embed_call['url'] == _EMBED_API
    # POST body carries the embed id pulled from data-embed.
    assert embed_call['data'] == urllib.parse.urlencode({'id': _FIXTURE_EMBED_ID}).encode()
    # The XHR header is required server-side; Origin/Referer too.
    headers = embed_call['headers']
    assert headers['X-Requested-With'] == 'XMLHttpRequest'
    assert headers['Origin'] == 'https://nepu.to'
    assert headers['Referer'] == url
    assert headers['Content-Type'].startswith('application/x-www-form-urlencoded')

    # Info dict shape.
    assert info['id'] == 'synthetic-movie-1'
    assert info['url'] == _FIXTURE_M3U8
    assert info['ext'] == 'mp4'
    assert info['protocol'] == 'm3u8_native'
    # http_headers carries at least Referer for the m3u8 fetch.
    assert info['http_headers'].get('Referer') == url


def test_movie_pulls_title_and_metadata_from_page(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    ie, _ = _make_extractor(NepuMovieIE, _MOVIE_HTML)
    info = ie._real_extract('https://nepu.to/movie/synthetic-movie-1')

    assert info['title'] == 'Synthetic Movie Title (2024)'
    assert info['description'] == 'A synthetic plot summary used only by the test suite.'
    assert info['thumbnail'] == 'https://nepu.to/static/img/synthetic-movie.jpg'


def test_movie_falls_back_to_cleaned_og_title_when_h1_missing(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    html = (
        '<html><head>'
        '<meta property="og:title" content="Watch Fallback Movie (2020) Free Online in HD">'
        f'</head><body><a data-embed="{_FIXTURE_EMBED_ID}"></a></body></html>'
    )
    ie, _ = _make_extractor(NepuMovieIE, html)
    info = ie._real_extract('https://nepu.to/movie/fallback-movie-1')
    assert info['title'] == 'Fallback Movie (2020)'


def test_movie_raises_when_data_embed_missing(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    ie, _ = _make_extractor(
        NepuMovieIE,
        '<html><head><title>x</title></head><body>no embed</body></html>',
    )
    with pytest.raises(Exception):
        ie._real_extract('https://nepu.to/movie/no-embed-here-1')


def test_movie_raises_when_embed_response_lacks_m3u8(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    ie, _ = _make_extractor(
        NepuMovieIE, _MOVIE_HTML,
        embed_html='<script>var x = "nothing useful here";</script>',
    )
    with pytest.raises(Exception):
        ie._real_extract('https://nepu.to/movie/no-m3u8-1')


def test_episode_extract_returns_m3u8_and_metadata(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    url = 'https://nepu.to/show/synthetic-show-7/season/3/episode/4'
    ie, _ = _make_extractor(NepuEpisodeIE, _EPISODE_HTML)
    info = ie._real_extract(url)

    assert info['id'] == 'synthetic-show-7-s3e4'
    assert info['url'] == _FIXTURE_M3U8
    assert info['ext'] == 'mp4'
    assert info['protocol'] == 'm3u8_native'
    assert info['season_number'] == 3
    assert info['episode_number'] == 4
    # series comes from h1 (preserves the year suffix).
    assert info['series'] == 'Synthetic Show (1962)'
    # episode title comes from the FIRST h2 -- the "Watch History" h2 that
    # follows must not win.
    assert info['episode'] == 'Pilot Episode'
    # Combined title shape when both series and episode title are present.
    assert info['title'] == 'Synthetic Show (1962) - Pilot Episode'


def test_episode_id_format_zero_pads_in_title_only(monkeypatch):
    # The synthesised `id` field uses unpadded numbers so it stays stable
    # across single- and double-digit episodes (s1e1 not s01e01). The
    # `title` fallback (when og:title is missing) is the only place that
    # zero-pads. Lock both behaviours.
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    url = 'https://nepu.to/show/x-1/season/12/episode/9'
    ie, _ = _make_extractor(
        NepuEpisodeIE,
        f'<html><body><h1>X</h1><a data-embed="{_FIXTURE_EMBED_ID}"></a></body></html>',
    )
    info = ie._real_extract(url)
    assert info['id'] == 'x-1-s12e9'
    # Title falls back to "Series S{NN}E{NN}" when og:title is missing.
    assert info['title'] == 'X S12E09'


# ---------------------------------------------------------------------------
# Bypass-path tests -- WHYKNOT_FLARESOLVERR_URL is set.
#
# The bypass returns the rendered page HTML, the cookies it acquired
# during the CF solve, and the user-agent it used. The extractor must:
#   1. POST to <base>/v1 with cmd=request.get
#   2. Inject cookies whose domain contains nepu.to into the YoutubeDL
#      cookiejar
#   3. Send the user-agent on the subsequent /ajax/embed POST so the
#      cf_clearance cookie validates server-side
#   4. Raise on a non-ok bypass envelope
# ---------------------------------------------------------------------------

def _make_extractor_with_bypass(cls, response_body=_MOVIE_HTML, status='ok',
                                 message=None, cookies=None, user_agent=None,
                                 embed_html=_EMBED_RESPONSE):
    ydl = YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True})
    ie = cls(ydl)

    captured = {'bypass_call': None, 'webpage_calls': []}

    def fake_download_json(url_or_request, video_id, *args, **kwargs):
        # The extractor passes a yt_dlp.networking.Request so it can
        # attach an extended socket timeout. Normalise so the tests can
        # introspect either path.
        if hasattr(url_or_request, 'url'):
            captured['bypass_call'] = {
                'url': url_or_request.url,
                'video_id': video_id,
                'data': url_or_request.data,
                'headers': dict(url_or_request.headers),
                'extensions': dict(getattr(url_or_request, 'extensions', {}) or {}),
                'method': url_or_request.method,
            }
        else:
            captured['bypass_call'] = {
                'url': url_or_request,
                'video_id': video_id,
                'data': kwargs.get('data') or (args[0] if args else None),
                'headers': kwargs.get('headers'),
                'extensions': {},
                'method': 'GET',
            }
        envelope = {
            'status': status,
            'solution': {
                'response': response_body,
                'cookies': cookies or [],
                'userAgent': user_agent or '',
            },
        }
        if message is not None:
            envelope['message'] = message
        return envelope

    def fake_download_webpage(url_or_request, video_id, *args, **kwargs):
        url = url_or_request if isinstance(url_or_request, str) else url_or_request.url
        captured['webpage_calls'].append({
            'url': url,
            'data': kwargs.get('data'),
            'headers': kwargs.get('headers') or {},
        })
        if _EMBED_API in url:
            return embed_html
        return response_body

    ie._download_json = fake_download_json  # type: ignore[assignment]
    ie._download_webpage = fake_download_webpage  # type: ignore[assignment]
    return ie, captured


def test_bypass_drives_v1_then_embed_post(monkeypatch):
    monkeypatch.setenv(_BYPASS_ENV, 'http://byparr:8191')
    ie, captured = _make_extractor_with_bypass(
        NepuMovieIE,
        cookies=[
            {'name': 'cf_clearance', 'value': 'abc', 'domain': '.nepu.to', 'path': '/', 'secure': True},
            {'name': 'PHPSESSID', 'value': 'xyz', 'domain': 'nepu.to', 'path': '/'},
        ],
        user_agent='Mozilla/5.0 (X11; Linux x86_64) Firefox/135.0',
    )

    info = ie._real_extract('https://nepu.to/movie/synthetic-movie-1')

    # 1. Bypass POST -- correct endpoint + request.get payload.
    bc = captured['bypass_call']
    assert bc['url'] == 'http://byparr:8191/v1'
    body = json.loads(bc['data'].decode('utf-8'))
    assert body['cmd'] == 'request.get'
    assert body['url'] == 'https://nepu.to/movie/synthetic-movie-1'

    # 2. /ajax/embed POST -- the only _download_webpage call.
    assert len(captured['webpage_calls']) == 1
    embed_call = captured['webpage_calls'][0]
    assert embed_call['url'] == _EMBED_API
    # User-Agent from bypass forwarded onto the POST.
    assert embed_call['headers']['User-Agent'] == 'Mozilla/5.0 (X11; Linux x86_64) Firefox/135.0'

    # 3. Cookies injected into the cookiejar.
    jar = ie._downloader.cookiejar
    names = {c.name for c in jar if 'nepu.to' in c.domain}
    assert 'cf_clearance' in names
    assert 'PHPSESSID' in names

    # 4. Info dict
    assert info['url'] == _FIXTURE_M3U8
    assert info['http_headers']['User-Agent'] == 'Mozilla/5.0 (X11; Linux x86_64) Firefox/135.0'


def test_bypass_skips_non_nepu_cookies(monkeypatch):
    # Some bypass services also return cookies from other origins they
    # touched during the solve (e.g. hcaptcha). Those must not land in
    # the jar -- they would confuse domain matching on the /ajax/embed
    # POST and on the m3u8 fetch.
    monkeypatch.setenv(_BYPASS_ENV, 'http://byparr:8191')
    ie, _ = _make_extractor_with_bypass(
        NepuMovieIE,
        cookies=[
            {'name': 'cf_clearance', 'value': 'abc', 'domain': '.nepu.to', 'path': '/'},
            {'name': '__cf_bm', 'value': 'foo', 'domain': '.hcaptcha.com', 'path': '/'},
        ],
        user_agent='UA',
    )
    ie._real_extract('https://nepu.to/movie/synthetic-movie-1')
    jar = ie._downloader.cookiejar
    domains = {c.domain for c in jar}
    assert '.nepu.to' in domains
    assert '.hcaptcha.com' not in domains


def test_bypass_non_ok_status_raises(monkeypatch):
    monkeypatch.setenv(_BYPASS_ENV, 'http://byparr:8191')
    ie, _ = _make_extractor_with_bypass(
        NepuMovieIE, response_body='', status='error',
        message='challenge timed out',
    )
    with pytest.raises(Exception) as excinfo:
        ie._real_extract('https://nepu.to/movie/synthetic-movie-1')
    assert 'challenge timed out' in str(excinfo.value)


def test_bypass_unset_skips_v1_path(monkeypatch):
    # No env var -- the extractor must use _download_webpage twice
    # (page + embed) and NEVER call _download_json.
    monkeypatch.delenv(_BYPASS_ENV, raising=False)

    ydl = YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True})
    ie = NepuMovieIE(ydl)

    def fake_download_webpage(url_or_request, video_id, *args, **kwargs):
        url = url_or_request if isinstance(url_or_request, str) else url_or_request.url
        if _EMBED_API in url:
            return _EMBED_RESPONSE
        return _MOVIE_HTML

    def _should_not_be_called(*a, **kw):
        raise AssertionError('_download_json must not be called without the env var')

    ie._download_webpage = fake_download_webpage  # type: ignore[assignment]
    ie._download_json = _should_not_be_called  # type: ignore[assignment]

    info = ie._real_extract('https://nepu.to/movie/synthetic-movie-1')
    assert info['url'] == _FIXTURE_M3U8


def test_bypass_request_uses_extended_socket_timeout(monkeypatch):
    # Byparr/Camoufox solves take ~14 s end-to-end; yt-dlp's default
    # socket_timeout is 20 s which is tight. The extractor must attach
    # extensions['timeout'] to bump the per-request budget.
    monkeypatch.setenv(_BYPASS_ENV, 'http://byparr:8191')
    ie, captured = _make_extractor_with_bypass(NepuMovieIE)
    ie._real_extract('https://nepu.to/movie/synthetic-movie-1')
    extensions = captured['bypass_call'].get('extensions') or {}
    assert extensions.get('timeout', 0) >= 60
    assert captured['bypass_call']['method'] == 'POST'


def test_bypass_url_trailing_slash_tolerated(monkeypatch):
    monkeypatch.setenv(_BYPASS_ENV, 'http://byparr:8191/')
    ie, captured = _make_extractor_with_bypass(
        NepuEpisodeIE, response_body=_EPISODE_HTML,
    )
    ie._real_extract('https://nepu.to/show/synthetic-show-7/season/3/episode/4')
    assert captured['bypass_call']['url'] == 'http://byparr:8191/v1'


# ---------------------------------------------------------------------------
# Lower-level regex sanity for the m3u8 path extraction.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('snippet, expected', [
    ('"file": "/public/m3u8/abc123.m3u8"', '/public/m3u8/abc123.m3u8'),
    ('"file"  :  "https://nepu.to/public/m3u8/abc123.m3u8"',
     'https://nepu.to/public/m3u8/abc123.m3u8'),
    ('something else', None),
])
def test_playerjs_file_regex(snippet, expected):
    from yt_dlp_plugins.extractor.nepu import _PLAYERJS_FILE_RE
    m = _PLAYERJS_FILE_RE.search(snippet)
    assert (m.group(1) if m else None) == expected


# ---------------------------------------------------------------------------
# Session cache -- skips the bypass when a fresh cache exists.
#
# The first /v1 solve costs ~14 s; the cache lets every subsequent resolve
# inside the cookie's lifetime (default 30 min) POST /ajax/embed directly
# in ~1 s. The fast path falls through to the slow path on any signal that
# the cookies are stale.
# ---------------------------------------------------------------------------

def _write_cache(dir_path, cookies, user_agent='UA-cache', saved_at=None):
    import json as _json
    import time as _time
    import os as _os
    payload = {
        'saved_at': saved_at if saved_at is not None else int(_time.time()),
        'user_agent': user_agent,
        'cookies': cookies,
    }
    _os.makedirs(dir_path, exist_ok=True)
    with open(_os.path.join(dir_path, _CACHE_FILENAME), 'w', encoding='utf-8') as f:
        _json.dump(payload, f)


def _make_extractor_with_bypass_and_webpage(cls, response_body, cookies, user_agent='UA-bypass',
                                             embed_html=_EMBED_RESPONSE,
                                             page_html_override=None):
    """Build an extractor that:
       - returns `response_body` (and `cookies`, `user_agent`) from the bypass /v1 call
       - returns `embed_html` from a /ajax/embed POST
       - returns `page_html_override or response_body` from a direct page GET
       Captures every call so tests can assert which paths fired.
    """
    ydl = YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True})
    ie = cls(ydl)

    captured = {'bypass_calls': 0, 'webpage_calls': [], 'cookies_seeded': cookies}

    def fake_download_json(url_or_request, video_id, *args, **kwargs):
        captured['bypass_calls'] += 1
        return {
            'status': 'ok',
            'solution': {
                'response': response_body,
                'cookies': cookies,
                'userAgent': user_agent,
            },
        }

    def fake_download_webpage(url_or_request, video_id, *args, **kwargs):
        url = url_or_request if isinstance(url_or_request, str) else url_or_request.url
        captured['webpage_calls'].append({'url': url, 'data': kwargs.get('data'),
                                          'headers': kwargs.get('headers') or {}})
        if _EMBED_API in url:
            return embed_html
        return page_html_override if page_html_override is not None else response_body

    ie._download_json = fake_download_json  # type: ignore[assignment]
    ie._download_webpage = fake_download_webpage  # type: ignore[assignment]
    return ie, captured


def test_cache_hit_skips_bypass(monkeypatch, tmp_path):
    monkeypatch.setenv(_BYPASS_ENV, 'http://byparr:8191')
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))

    cookies = [
        {'name': 'cf_clearance', 'value': 'cached_clearance', 'domain': '.nepu.to', 'path': '/'},
        {'name': 'PHPSESSID', 'value': 'cached_session', 'domain': 'nepu.to', 'path': '/'},
    ]
    _write_cache(str(tmp_path), cookies, user_agent='UA-cache')

    ie, captured = _make_extractor_with_bypass_and_webpage(
        NepuMovieIE, _MOVIE_HTML, cookies=cookies)

    info = ie._real_extract('https://nepu.to/movie/synthetic-movie-1')

    # No /v1 call -- cache hit bypassed the solver entirely.
    assert captured['bypass_calls'] == 0
    # Two webpage calls: page GET + /ajax/embed POST.
    assert len(captured['webpage_calls']) == 2
    page_call, embed_call = captured['webpage_calls']
    assert page_call['url'] == 'https://nepu.to/movie/synthetic-movie-1'
    assert embed_call['url'] == _EMBED_API
    # UA from the cache forwarded to both calls.
    assert embed_call['headers']['User-Agent'] == 'UA-cache'
    assert info['url'] == _FIXTURE_M3U8


def test_cache_expired_falls_through_to_bypass(monkeypatch, tmp_path):
    monkeypatch.setenv(_BYPASS_ENV, 'http://byparr:8191')
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))

    stale_cookies = [{'name': 'cf_clearance', 'value': 'old', 'domain': '.nepu.to', 'path': '/'}]
    # Saved_at older than TTL -> treated as missing.
    import time as _time
    _write_cache(str(tmp_path), stale_cookies, user_agent='UA-stale',
                 saved_at=int(_time.time()) - (_CACHE_TTL_SECONDS + 60))

    fresh_cookies = [
        {'name': 'cf_clearance', 'value': 'fresh', 'domain': '.nepu.to', 'path': '/'},
        {'name': 'PHPSESSID', 'value': 'fresh_session', 'domain': 'nepu.to', 'path': '/'},
    ]
    ie, captured = _make_extractor_with_bypass_and_webpage(
        NepuMovieIE, _MOVIE_HTML, cookies=fresh_cookies, user_agent='UA-fresh')

    info = ie._real_extract('https://nepu.to/movie/synthetic-movie-1')

    # Bypass fired exactly once for the refresh.
    assert captured['bypass_calls'] == 1
    # Embed POST headers carry the fresh UA, not the stale one.
    embed_call = next(c for c in captured['webpage_calls'] if c['url'] == _EMBED_API)
    assert embed_call['headers']['User-Agent'] == 'UA-fresh'
    assert info['url'] == _FIXTURE_M3U8

    # Cache file is now refreshed -- check the value reflects the new cookies.
    import json as _json
    saved = _json.load(open(tmp_path / _CACHE_FILENAME, 'r', encoding='utf-8'))
    assert any(c['value'] == 'fresh' for c in saved['cookies'])
    assert saved['user_agent'] == 'UA-fresh'


def test_cache_missing_cf_clearance_treated_as_no_cache(monkeypatch, tmp_path):
    # Cache file exists but has no cf_clearance cookie -- treat as no cache,
    # go through the bypass refresh path.
    monkeypatch.setenv(_BYPASS_ENV, 'http://byparr:8191')
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))
    _write_cache(str(tmp_path), [{'name': 'PHPSESSID', 'value': 'x', 'domain': 'nepu.to'}],
                 user_agent='UA-old')

    fresh_cookies = [
        {'name': 'cf_clearance', 'value': 'new', 'domain': '.nepu.to', 'path': '/'},
    ]
    ie, captured = _make_extractor_with_bypass_and_webpage(
        NepuMovieIE, _MOVIE_HTML, cookies=fresh_cookies, user_agent='UA-new')
    ie._real_extract('https://nepu.to/movie/synthetic-movie-1')
    assert captured['bypass_calls'] == 1


def test_cache_save_filters_to_nepu_cookies(monkeypatch, tmp_path):
    monkeypatch.setenv(_BYPASS_ENV, 'http://byparr:8191')
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))

    # Bypass returns nepu + hcaptcha cookies. Save should drop the hcaptcha
    # one so the file isn't polluted with off-origin state.
    mixed_cookies = [
        {'name': 'cf_clearance', 'value': 'abc', 'domain': '.nepu.to', 'path': '/'},
        {'name': 'PHPSESSID', 'value': 'xyz', 'domain': 'nepu.to', 'path': '/'},
        {'name': '__cf_bm', 'value': 'hcap', 'domain': '.hcaptcha.com', 'path': '/'},
    ]
    ie, _ = _make_extractor_with_bypass_and_webpage(
        NepuMovieIE, _MOVIE_HTML, cookies=mixed_cookies)
    ie._real_extract('https://nepu.to/movie/synthetic-movie-1')

    import json as _json
    saved = _json.load(open(tmp_path / _CACHE_FILENAME, 'r', encoding='utf-8'))
    domains = {c['domain'] for c in saved['cookies']}
    assert '.hcaptcha.com' not in domains
    assert any('nepu.to' in d for d in domains)


def test_cached_session_page_fetch_failure_falls_back(monkeypatch, tmp_path):
    # Cache exists with cookies, but the page response doesn't have a
    # data-embed (simulating an expired cf_clearance -> CF challenge page).
    # The extractor should invalidate the cache and retry via the bypass.
    monkeypatch.setenv(_BYPASS_ENV, 'http://byparr:8191')
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))

    cookies = [{'name': 'cf_clearance', 'value': 'expired', 'domain': '.nepu.to', 'path': '/'}]
    _write_cache(str(tmp_path), cookies, user_agent='UA-stale')

    cf_challenge_page = '<html><head><title>Just a moment...</title></head><body></body></html>'
    fresh_cookies = [{'name': 'cf_clearance', 'value': 'fresh', 'domain': '.nepu.to', 'path': '/'}]

    ydl = YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True})
    ie = NepuMovieIE(ydl)

    state = {'bypass_calls': 0, 'page_calls': 0}

    def fake_download_json(url_or_request, video_id, *args, **kwargs):
        state['bypass_calls'] += 1
        return {'status': 'ok', 'solution': {
            'response': _MOVIE_HTML, 'cookies': fresh_cookies, 'userAgent': 'UA-fresh'}}

    def fake_download_webpage(url_or_request, video_id, *args, **kwargs):
        url = url_or_request if isinstance(url_or_request, str) else url_or_request.url
        state['page_calls'] += 1
        if _EMBED_API in url:
            return _EMBED_RESPONSE
        # First page call (cached session) -> CF challenge page.
        # Second page call (bypass refresh) is short-circuited by the bypass
        # which returned _MOVIE_HTML in its solution -- but the extractor
        # actually re-fetches the page through _download_webpage for the
        # non-cached path too. Both return _MOVIE_HTML for the second hit.
        if state['page_calls'] == 1:
            return cf_challenge_page
        return _MOVIE_HTML

    ie._download_json = fake_download_json  # type: ignore[assignment]
    ie._download_webpage = fake_download_webpage  # type: ignore[assignment]

    info = ie._real_extract('https://nepu.to/movie/synthetic-movie-1')

    assert state['bypass_calls'] == 1, 'must refresh via bypass after cached-session failure'
    assert info['url'] == _FIXTURE_M3U8
    # The cache file should have been invalidated, then re-written with the
    # fresh session.
    import json as _json
    saved = _json.load(open(tmp_path / _CACHE_FILENAME, 'r', encoding='utf-8'))
    assert any(c['value'] == 'fresh' for c in saved['cookies'])


def test_cache_dir_env_override(monkeypatch, tmp_path):
    # WHYKNOT_PLUGIN_STATE_DIR should be honoured.
    from yt_dlp_plugins.extractor.nepu import _nepu_cache_dir
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path / 'custom'))
    assert _nepu_cache_dir() == str(tmp_path / 'custom')
