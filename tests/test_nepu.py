# Offline tests for the nepu.to extractor.
#
# Two layers:
#
#   1. URL regex tests -- parametrised cases that walk the supported and
#      unsupported URL shapes and assert _VALID_URL captures the right
#      groups. Pure pattern matching, no extractor instance, no network.
#
#   2. Parse tests -- build a real extractor instance with a stubbed
#      YoutubeDL, monkeypatch `_download_webpage` to return an inline
#      HTML fixture (a string defined in this file -- avoids checking in
#      page snapshots that could drift or include site-identifying
#      structure), then call `_real_extract` and assert the returned
#      info_dict has the m3u8 URL, ext, protocol, and metadata we
#      planted in the fixture.
#
# The fixture HTML uses synthetic slugs and m3u8 hashes so this file is
# self-contained and the tests pass without any live request.

from __future__ import annotations

import re

import pytest

from yt_dlp import YoutubeDL

from yt_dlp_plugins.extractor.nepu import (
    NepuMovieIE,
    NepuEpisodeIE,
    _FLARESOLVERR_ENV,
)


# ---------------------------------------------------------------------------
# Inline HTML fixtures
# ---------------------------------------------------------------------------

_FIXTURE_M3U8 = 'https://nepu.to/public/m3u8/0123456789abcdef0123456789abcdef.m3u8'

# Fixture shapes mirror real nepu.to markup:
#   - og:title is marketing copy with a "Watch ... Free Online in HD"
#     envelope (movies) or "Watch ... Shows & Cartoons Free in HD"
#     envelope (shows). Never the clean title.
#   - h1 carries the clean title (movies) or the series name (episodes).
#   - The episode page has a real-content h2 (episode title) followed by
#     a "Watch History" h2; the extractor must pick the first h2.

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
  <script>
    const player = new Player({{
      source: "{_FIXTURE_M3U8}"
    }});
  </script>
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
  <video data-src="{_FIXTURE_M3U8}"></video>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extractor(cls, html):
    """Build a `cls` instance whose `_download_webpage` returns `html`.

    Uses a real YoutubeDL as the downloader so the extractor's calls
    into the downloader (logging, format helpers, etc) hit a real
    implementation. Stubbing the downloader surface area by hand turned
    out to be a moving target across yt-dlp versions.
    """
    ydl = YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True})
    ie = cls(ydl)
    ie._download_webpage = lambda *a, **kw: html  # type: ignore[assignment]
    return ie


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
# Parse tests -- _real_extract against inline HTML fixtures
# ---------------------------------------------------------------------------

def test_movie_real_extract_returns_m3u8():
    url = 'https://nepu.to/movie/synthetic-movie-1'
    ie = _make_extractor(NepuMovieIE, _MOVIE_HTML)

    info = ie._real_extract(url)

    assert info['id'] == 'synthetic-movie-1'
    assert info['url'] == _FIXTURE_M3U8
    assert info['ext'] == 'mp4'
    assert info['protocol'] == 'm3u8_native'


def test_movie_real_extract_pulls_title_and_description():
    url = 'https://nepu.to/movie/synthetic-movie-1'
    ie = _make_extractor(NepuMovieIE, _MOVIE_HTML)

    info = ie._real_extract(url)

    # Title comes from the clean h1, not the marketing-copy og:title.
    assert info['title'] == 'Synthetic Movie Title (2024)'
    assert info['description'] == 'A synthetic plot summary used only by the test suite.'
    assert info['thumbnail'] == 'https://nepu.to/static/img/synthetic-movie.jpg'


def test_movie_falls_back_to_cleaned_og_title_when_h1_missing():
    # If a future markup change removes the h1, the og:title fallback
    # must strip the "Watch ... Free Online in HD" envelope.
    html = (
        '<html><head>'
        '<meta property="og:title" content="Watch Fallback Movie (2020) Free Online in HD">'
        f'</head><body><video src="{_FIXTURE_M3U8}"></video></body></html>'
    )
    ie = _make_extractor(NepuMovieIE, html)
    info = ie._real_extract('https://nepu.to/movie/fallback-movie-1')
    assert info['title'] == 'Fallback Movie (2020)'


def test_movie_real_extract_raises_when_no_m3u8():
    url = 'https://nepu.to/movie/no-stream-here-1'
    ie = _make_extractor(NepuMovieIE, '<html><head><title>x</title></head><body>no stream</body></html>')

    with pytest.raises(Exception):
        ie._real_extract(url)


def test_episode_real_extract_returns_m3u8_and_metadata():
    url = 'https://nepu.to/show/synthetic-show-7/season/3/episode/4'
    ie = _make_extractor(NepuEpisodeIE, _EPISODE_HTML)

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


def test_episode_id_format_zero_pads_in_title_only():
    # The synthesised `id` field uses unpadded numbers so it stays stable
    # across single- and double-digit episodes (s1e1 not s01e01). The
    # `title` fallback (when og:title is missing) is the only place that
    # zero-pads. Lock both behaviours.
    url = 'https://nepu.to/show/x-1/season/12/episode/9'
    ie = _make_extractor(
        NepuEpisodeIE,
        f'<html><body><h1>X</h1><video src="{_FIXTURE_M3U8}"></video></body></html>',
    )

    info = ie._real_extract(url)
    assert info['id'] == 'x-1-s12e9'
    # Title falls back to "Series S{NN}E{NN}" when og:title is missing.
    assert info['title'] == 'X S12E09'


# ---------------------------------------------------------------------------
# Regex sanity: the m3u8 detector should never match unrelated nepu URLs.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('html, should_match', [
    (f'<a href="{_FIXTURE_M3U8}">x</a>', True),
    ('<a href="https://nepu.to/public/m3u8/xyz.m3u8">x</a>', False),  # non-hex char
    ('<a href="https://nepu.to/public/m3u8/123.mpd">x</a>', False),  # wrong ext
    ('<a href="https://other.example/public/m3u8/abc123.m3u8">x</a>', False),
])
def test_m3u8_regex(html, should_match):
    from yt_dlp_plugins.extractor.nepu import _M3U8_RE
    assert bool(re.search(_M3U8_RE, html)) is should_match


# ---------------------------------------------------------------------------
# FlareSolverr fetch path -- behaviour gated on WHYKNOT_FLARESOLVERR_URL.
#
# The plain `_download_webpage` path is already exercised by the parse
# tests above. The tests below assert that when the env var is set the
# extractor:
#
#   1. POSTs to `<base>/v1` with `cmd=request.get`
#   2. Reads the rendered HTML out of `solution.response`
#   3. Returns the same info_dict shape as the direct-fetch path
#   4. Raises on a non-ok FlareSolverr envelope
#
# `_download_json` is stubbed so the tests stay offline; we capture the
# request arguments to verify the wire shape.
# ---------------------------------------------------------------------------

def _make_extractor_with_flaresolverr_response(cls, response_body, status='ok',
                                                message=None):
    ydl = YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True})
    ie = cls(ydl)

    captured = {}

    def fake_download_json(url, video_id, *args, **kwargs):
        captured['url'] = url
        captured['video_id'] = video_id
        captured['data'] = kwargs.get('data') or (args[0] if args else None)
        captured['headers'] = kwargs.get('headers')
        envelope = {'status': status, 'solution': {'response': response_body}}
        if message is not None:
            envelope['message'] = message
        return envelope

    ie._download_json = fake_download_json  # type: ignore[assignment]
    return ie, captured


def test_movie_uses_flaresolverr_when_env_set(monkeypatch):
    monkeypatch.setenv(_FLARESOLVERR_ENV, 'http://flaresolverr:8191')

    ie, captured = _make_extractor_with_flaresolverr_response(
        NepuMovieIE, _MOVIE_HTML)

    info = ie._real_extract('https://nepu.to/movie/synthetic-movie-1')

    # FlareSolverr endpoint shape: base + /v1, JSON body with request.get.
    assert captured['url'] == 'http://flaresolverr:8191/v1'
    assert captured['headers'] == {'Content-Type': 'application/json'}
    import json as _json
    body = _json.loads(captured['data'].decode('utf-8'))
    assert body['cmd'] == 'request.get'
    assert body['url'] == 'https://nepu.to/movie/synthetic-movie-1'
    assert body['maxTimeout'] == 30000

    # The rendered HTML parses the same way the direct-fetch HTML does.
    assert info['id'] == 'synthetic-movie-1'
    assert info['url'] == _FIXTURE_M3U8
    assert info['title'] == 'Synthetic Movie Title (2024)'


def test_episode_uses_flaresolverr_when_env_set(monkeypatch):
    monkeypatch.setenv(_FLARESOLVERR_ENV, 'http://flaresolverr:8191/')

    ie, captured = _make_extractor_with_flaresolverr_response(
        NepuEpisodeIE, _EPISODE_HTML)

    info = ie._real_extract(
        'https://nepu.to/show/synthetic-show-7/season/3/episode/4')

    # Trailing slash on the base URL is tolerated -- the helper strips it.
    assert captured['url'] == 'http://flaresolverr:8191/v1'
    assert info['id'] == 'synthetic-show-7-s3e4'
    assert info['url'] == _FIXTURE_M3U8
    assert info['series'] == 'Synthetic Show (1962)'


def test_flaresolverr_non_ok_status_raises(monkeypatch):
    monkeypatch.setenv(_FLARESOLVERR_ENV, 'http://flaresolverr:8191')

    ie, _ = _make_extractor_with_flaresolverr_response(
        NepuMovieIE, '', status='error', message='challenge timed out')

    with pytest.raises(Exception) as excinfo:
        ie._real_extract('https://nepu.to/movie/synthetic-movie-1')
    assert 'challenge timed out' in str(excinfo.value)


def test_flaresolverr_unset_env_falls_back_to_direct_fetch(monkeypatch):
    # No WHYKNOT_FLARESOLVERR_URL -- the extractor must use _download_webpage,
    # not _download_json. We assert this by stubbing _download_json to raise
    # if it gets called.
    monkeypatch.delenv(_FLARESOLVERR_ENV, raising=False)

    ydl = YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True})
    ie = NepuMovieIE(ydl)
    ie._download_webpage = lambda *a, **kw: _MOVIE_HTML  # type: ignore[assignment]

    def _should_not_be_called(*a, **kw):
        raise AssertionError('_download_json must not be called without the env var')
    ie._download_json = _should_not_be_called  # type: ignore[assignment]

    info = ie._real_extract('https://nepu.to/movie/synthetic-movie-1')
    assert info['url'] == _FIXTURE_M3U8
