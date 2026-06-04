from nepu_shared import *


def test_bypass_drives_v1_then_embed_post(monkeypatch):
    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191")
    ie, captured = _make_extractor_with_bypass(
        NepuMovieIE,
        cookies=[
            {"name": "cf_clearance", "value": "abc", "domain": ".nepu.to", "path": "/", "secure": True},
            {"name": "PHPSESSID", "value": "xyz", "domain": "nepu.to", "path": "/"},
        ],
        user_agent="Mozilla/5.0 (X11; Linux x86_64) Firefox/135.0",
    )

    info = ie._real_extract("https://nepu.to/movie/synthetic-movie-1")

    # 1. Bypass POST -- correct endpoint + request.get payload.
    bc = captured["bypass_call"]
    assert bc["url"] == "http://byparr:8191/v1"
    body = json.loads(bc["data"].decode("utf-8"))
    assert body["cmd"] == "request.get"
    assert body["url"] == "https://nepu.to/movie/synthetic-movie-1"

    # 2. /ajax/embed POST -- the only _download_webpage call.
    assert len(captured["webpage_calls"]) == 1
    embed_call = captured["webpage_calls"][0]
    assert embed_call["url"] == _EMBED_API
    # User-Agent from bypass forwarded onto the POST.
    assert embed_call["headers"]["User-Agent"] == "Mozilla/5.0 (X11; Linux x86_64) Firefox/135.0"

    # 3. Cookies injected into the cookiejar.
    jar = ie._downloader.cookiejar
    names = {c.name for c in jar if "nepu.to" in c.domain}
    assert "cf_clearance" in names
    assert "PHPSESSID" in names

    # 4. Info dict
    assert info["url"] == _FIXTURE_M3U8
    assert info["http_headers"]["User-Agent"] == "Mozilla/5.0 (X11; Linux x86_64) Firefox/135.0"


def test_bypass_skips_non_nepu_cookies(monkeypatch):
    # Some bypass services also return cookies from other origins they
    # touched during the solve (e.g. hcaptcha). Those must not land in
    # the jar -- they would confuse domain matching on the /ajax/embed
    # POST and on the m3u8 fetch.
    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191")
    ie, _ = _make_extractor_with_bypass(
        NepuMovieIE,
        cookies=[
            {"name": "cf_clearance", "value": "abc", "domain": ".nepu.to", "path": "/"},
            {"name": "__cf_bm", "value": "foo", "domain": ".hcaptcha.com", "path": "/"},
        ],
        user_agent="UA",
    )
    ie._real_extract("https://nepu.to/movie/synthetic-movie-1")
    jar = ie._downloader.cookiejar
    domains = {c.domain for c in jar}
    assert ".nepu.to" in domains
    assert ".hcaptcha.com" not in domains


def test_bypass_non_ok_status_raises(monkeypatch):
    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191")
    ie, _ = _make_extractor_with_bypass(
        NepuMovieIE,
        response_body="",
        status="error",
        message="challenge timed out",
    )
    with pytest.raises(Exception) as excinfo:
        ie._real_extract("https://nepu.to/movie/synthetic-movie-1")
    assert "challenge timed out" in str(excinfo.value)


def test_bypass_unset_skips_v1_path(monkeypatch):
    # No env var -- the extractor must use _download_webpage twice
    # (page + embed) and NEVER call _download_json.
    monkeypatch.delenv(_BYPASS_ENV, raising=False)

    ydl = YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True})
    ie = NepuMovieIE(ydl)

    def fake_download_webpage(url_or_request, video_id, *args, **kwargs):
        url = url_or_request if isinstance(url_or_request, str) else url_or_request.url
        if _EMBED_API in url:
            return _EMBED_RESPONSE
        return _MOVIE_HTML

    def _should_not_be_called(*a, **kw):
        raise AssertionError("_download_json must not be called without the env var")

    ie._download_webpage = fake_download_webpage  # type: ignore[assignment]
    ie._download_json = _should_not_be_called  # type: ignore[assignment]

    info = ie._real_extract("https://nepu.to/movie/synthetic-movie-1")
    assert info["url"] == _FIXTURE_M3U8


def test_bypass_request_uses_extended_socket_timeout(monkeypatch):
    # Byparr/Camoufox solves take ~14 s end-to-end; yt-dlp's default
    # socket_timeout is 20 s which is tight. The extractor must attach
    # extensions['timeout'] to bump the per-request budget.
    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191")
    ie, captured = _make_extractor_with_bypass(NepuMovieIE)
    ie._real_extract("https://nepu.to/movie/synthetic-movie-1")
    extensions = captured["bypass_call"].get("extensions") or {}
    assert extensions.get("timeout", 0) >= 60
    assert captured["bypass_call"]["method"] == "POST"


def test_bypass_url_trailing_slash_tolerated(monkeypatch):
    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191/")
    ie, captured = _make_extractor_with_bypass(
        NepuEpisodeIE,
        response_body=_EPISODE_HTML,
    )
    ie._real_extract("https://nepu.to/show/synthetic-show-7/season/3/episode/4")
    assert captured["bypass_call"]["url"] == "http://byparr:8191/v1"


def test_bypass_slow_path_retries_after_embed_post_failure(monkeypatch, tmp_path):
    # Byparr/Camoufox occasionally crashes its browser context mid-solve and
    # returns a degraded cf_clearance: the homepage GET passes, but the
    # /ajax/embed POST 403s on the stricter bot-score gate. The slow path
    # must retry once with a fresh solve before giving up. A real-world
    # transient crash usually clears on the next /v1 because Express
    # respawns the browser context.
    from yt_dlp_plugins.extractor.nepu import _CACHE_FILENAME, _CACHE_SUBDIR

    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191")
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))

    ydl = YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True})
    ie = NepuMovieIE(ydl)

    captured = {"bypass_calls": 0, "embed_calls": 0}

    def fake_download_json(url_or_request, video_id, *args, **kwargs):
        captured["bypass_calls"] += 1
        return {
            "status": "ok",
            "solution": {
                "response": _MOVIE_HTML,
                "cookies": [
                    {
                        "name": "cf_clearance",
                        "value": f"fresh-{captured['bypass_calls']}",
                        "domain": ".nepu.to",
                        "path": "/",
                    },
                ],
                "userAgent": "UA-test",
            },
        }

    def fake_download_webpage(url_or_request, video_id, *args, **kwargs):
        url = url_or_request if isinstance(url_or_request, str) else url_or_request.url
        if _EMBED_API in url:
            captured["embed_calls"] += 1
            if captured["embed_calls"] == 1:
                # Simulate the 403 the degraded cf_clearance produces.
                from yt_dlp.utils import ExtractorError as _ExtractorError

                raise _ExtractorError("Stream resolution failed: HTTP Error 403: Forbidden", expected=True)
            return _EMBED_RESPONSE
        # Page GET (non-bypass path) should not be hit; bypass returns the HTML.
        return _MOVIE_HTML

    ie._download_json = fake_download_json  # type: ignore[assignment]
    ie._download_webpage = fake_download_webpage  # type: ignore[assignment]

    info = ie._real_extract("https://nepu.to/movie/synthetic-movie-1")

    # Two bypass /v1 calls: first produced the degraded session, second was
    # the retry that succeeded.
    assert captured["bypass_calls"] == 2
    # Two embed POSTs: the first 403'd, the retry succeeded.
    assert captured["embed_calls"] == 2
    # Final info dict carries the resolved m3u8.
    assert info["url"] == _FIXTURE_M3U8
    # Cache should now contain the SECOND (fresh-2) solve, not the failed first one.
    cache_path = tmp_path / _CACHE_SUBDIR / _CACHE_FILENAME
    assert cache_path.exists()
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    saved_cf = next(c["value"] for c in payload["cookies"] if c.get("name") == "cf_clearance")
    assert saved_cf == "fresh-2"


def test_bypass_slow_path_gives_up_after_second_failure(monkeypatch, tmp_path):
    # Two failures in a row indicate something more than a transient
    # browser-context crash. The extractor must surface the failure rather
    # than retrying indefinitely.
    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191")
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))

    ydl = YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True})
    ie = NepuMovieIE(ydl)
    captured = {"bypass_calls": 0, "embed_calls": 0}

    def fake_download_json(url_or_request, video_id, *args, **kwargs):
        captured["bypass_calls"] += 1
        return {
            "status": "ok",
            "solution": {
                "response": _MOVIE_HTML,
                "cookies": [{"name": "cf_clearance", "value": "degraded", "domain": ".nepu.to", "path": "/"}],
                "userAgent": "UA",
            },
        }

    def fake_download_webpage(url_or_request, video_id, *args, **kwargs):
        url = url_or_request if isinstance(url_or_request, str) else url_or_request.url
        if _EMBED_API in url:
            captured["embed_calls"] += 1
            from yt_dlp.utils import ExtractorError as _ExtractorError

            raise _ExtractorError("Stream resolution failed: HTTP Error 403", expected=True)
        return _MOVIE_HTML

    ie._download_json = fake_download_json  # type: ignore[assignment]
    ie._download_webpage = fake_download_webpage  # type: ignore[assignment]

    with pytest.raises(Exception) as excinfo:
        ie._real_extract("https://nepu.to/movie/synthetic-movie-1")
    assert "403" in str(excinfo.value)
    # Exactly two attempts; not a third.
    assert captured["bypass_calls"] == 2
    assert captured["embed_calls"] == 2


# ---------------------------------------------------------------------------
# Lower-level regex sanity for the m3u8 path extraction.
# ---------------------------------------------------------------------------
