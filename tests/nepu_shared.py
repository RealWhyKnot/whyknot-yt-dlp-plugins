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
    _CACHE_SUBDIR,
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

def _write_cache(dir_path, cookies, user_agent='UA-cache', saved_at=None):
    import json as _json
    import time as _time
    import os as _os
    from yt_dlp_plugins.extractor.nepu import _CACHE_SUBDIR
    payload = {
        'saved_at': saved_at if saved_at is not None else int(_time.time()),
        'user_agent': user_agent,
        'cookies': cookies,
    }
    subdir = _os.path.join(dir_path, _CACHE_SUBDIR)
    _os.makedirs(subdir, exist_ok=True)
    with open(_os.path.join(subdir, _CACHE_FILENAME), 'w', encoding='utf-8') as f:
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

__all__ = [name for name in globals() if not name.startswith('__')]
