from nepu_shared import *


def test_movie_extract_posts_embed_id_and_returns_m3u8(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    url = "https://nepu.to/movie/synthetic-movie-1"
    ie, captured = _make_extractor(NepuMovieIE, _MOVIE_HTML)

    info = ie._real_extract(url)

    # Two webpage fetches: the movie page, then the /ajax/embed POST.
    assert len(captured["webpage_calls"]) == 2
    assert captured["webpage_calls"][0]["url"] == url
    embed_call = captured["webpage_calls"][1]
    assert embed_call["url"] == _EMBED_API
    # POST body carries the embed id pulled from data-embed.
    assert embed_call["data"] == urllib.parse.urlencode({"id": _FIXTURE_EMBED_ID}).encode()
    # The XHR header is required server-side; Origin/Referer too.
    headers = embed_call["headers"]
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["Origin"] == "https://nepu.to"
    assert headers["Referer"] == url
    assert headers["Content-Type"].startswith("application/x-www-form-urlencoded")

    # Info dict shape.
    assert info["id"] == "synthetic-movie-1"
    assert info["url"] == _FIXTURE_M3U8
    assert info["ext"] == "mp4"
    assert info["protocol"] == "m3u8_native"
    # http_headers carries at least Referer for the m3u8 fetch.
    assert info["http_headers"].get("Referer") == url


def test_movie_pulls_title_and_metadata_from_page(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    ie, _ = _make_extractor(NepuMovieIE, _MOVIE_HTML)
    info = ie._real_extract("https://nepu.to/movie/synthetic-movie-1")

    assert info["title"] == "Synthetic Movie Title (2024)"
    assert info["description"] == "A synthetic plot summary used only by the test suite."
    assert info["thumbnail"] == "https://nepu.to/static/img/synthetic-movie.jpg"


def test_movie_falls_back_to_cleaned_og_title_when_h1_missing(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    html = (
        "<html><head>"
        '<meta property="og:title" content="Watch Fallback Movie (2020) Free Online in HD">'
        f'</head><body><a data-embed="{_FIXTURE_EMBED_ID}"></a></body></html>'
    )
    ie, _ = _make_extractor(NepuMovieIE, html)
    info = ie._real_extract("https://nepu.to/movie/fallback-movie-1")
    assert info["title"] == "Fallback Movie (2020)"


def test_movie_raises_when_data_embed_missing(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    ie, _ = _make_extractor(
        NepuMovieIE,
        "<html><head><title>x</title></head><body>no embed</body></html>",
    )
    with pytest.raises(Exception):
        ie._real_extract("https://nepu.to/movie/no-embed-here-1")


def test_movie_raises_when_embed_response_lacks_m3u8(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    ie, _ = _make_extractor(
        NepuMovieIE,
        _MOVIE_HTML,
        embed_html='<script>var x = "nothing useful here";</script>',
    )
    with pytest.raises(Exception):
        ie._real_extract("https://nepu.to/movie/no-m3u8-1")


def test_episode_extract_returns_m3u8_and_metadata(monkeypatch):
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    url = "https://nepu.to/show/synthetic-show-7/season/3/episode/4"
    ie, _ = _make_extractor(NepuEpisodeIE, _EPISODE_HTML)
    info = ie._real_extract(url)

    assert info["id"] == "synthetic-show-7-s3e4"
    assert info["url"] == _FIXTURE_M3U8
    assert info["ext"] == "mp4"
    assert info["protocol"] == "m3u8_native"
    assert info["season_number"] == 3
    assert info["episode_number"] == 4
    # series comes from h1 (preserves the year suffix).
    assert info["series"] == "Synthetic Show (1962)"
    # episode title comes from the FIRST h2 -- the "Watch History" h2 that
    # follows must not win.
    assert info["episode"] == "Pilot Episode"
    # Combined title shape when both series and episode title are present.
    assert info["title"] == "Synthetic Show (1962) - Pilot Episode"


def test_episode_id_format_zero_pads_in_title_only(monkeypatch):
    # The synthesised `id` field uses unpadded numbers so it stays stable
    # across single- and double-digit episodes (s1e1 not s01e01). The
    # `title` fallback (when og:title is missing) is the only place that
    # zero-pads. Lock both behaviours.
    monkeypatch.delenv(_BYPASS_ENV, raising=False)
    url = "https://nepu.to/show/x-1/season/12/episode/9"
    ie, _ = _make_extractor(
        NepuEpisodeIE,
        f'<html><body><h1>X</h1><a data-embed="{_FIXTURE_EMBED_ID}"></a></body></html>',
    )
    info = ie._real_extract(url)
    assert info["id"] == "x-1-s12e9"
    # Title falls back to "Series S{NN}E{NN}" when og:title is missing.
    assert info["title"] == "X S12E09"


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


@pytest.mark.parametrize(
    "snippet, expected",
    [
        ('"file": "/public/m3u8/abc123.m3u8"', "/public/m3u8/abc123.m3u8"),
        ('"file"  :  "https://nepu.to/public/m3u8/abc123.m3u8"', "https://nepu.to/public/m3u8/abc123.m3u8"),
        ("something else", None),
    ],
)
def test_playerjs_file_regex(snippet, expected):
    from yt_dlp_plugins.extractor.nepu import _PLAYERJS_FILE_RE

    m = _PLAYERJS_FILE_RE.search(snippet)
    assert (m.group(1) if m else None) == expected
