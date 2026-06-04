from nepu_shared import *


def test_cache_hit_skips_bypass(monkeypatch, tmp_path):
    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191")
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))

    cookies = [
        {"name": "cf_clearance", "value": "cached_clearance", "domain": ".nepu.to", "path": "/"},
        {"name": "PHPSESSID", "value": "cached_session", "domain": "nepu.to", "path": "/"},
    ]
    _write_cache(str(tmp_path), cookies, user_agent="UA-cache")

    ie, captured = _make_extractor_with_bypass_and_webpage(NepuMovieIE, _MOVIE_HTML, cookies=cookies)

    info = ie._real_extract("https://nepu.to/movie/synthetic-movie-1")

    # No /v1 call -- cache hit bypassed the solver entirely.
    assert captured["bypass_calls"] == 0
    # Two webpage calls: page GET + /ajax/embed POST.
    assert len(captured["webpage_calls"]) == 2
    page_call, embed_call = captured["webpage_calls"]
    assert page_call["url"] == "https://nepu.to/movie/synthetic-movie-1"
    assert embed_call["url"] == _EMBED_API
    # UA from the cache forwarded to both calls.
    assert embed_call["headers"]["User-Agent"] == "UA-cache"
    assert info["url"] == _FIXTURE_M3U8


def test_cache_expired_falls_through_to_bypass(monkeypatch, tmp_path):
    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191")
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))

    stale_cookies = [{"name": "cf_clearance", "value": "old", "domain": ".nepu.to", "path": "/"}]
    # Saved_at older than TTL -> treated as missing.
    import time as _time

    _write_cache(
        str(tmp_path), stale_cookies, user_agent="UA-stale", saved_at=int(_time.time()) - (_CACHE_TTL_SECONDS + 60)
    )

    fresh_cookies = [
        {"name": "cf_clearance", "value": "fresh", "domain": ".nepu.to", "path": "/"},
        {"name": "PHPSESSID", "value": "fresh_session", "domain": "nepu.to", "path": "/"},
    ]
    ie, captured = _make_extractor_with_bypass_and_webpage(
        NepuMovieIE, _MOVIE_HTML, cookies=fresh_cookies, user_agent="UA-fresh"
    )

    info = ie._real_extract("https://nepu.to/movie/synthetic-movie-1")

    # Bypass fired exactly once for the refresh.
    assert captured["bypass_calls"] == 1
    # Embed POST headers carry the fresh UA, not the stale one.
    embed_call = next(c for c in captured["webpage_calls"] if c["url"] == _EMBED_API)
    assert embed_call["headers"]["User-Agent"] == "UA-fresh"
    assert info["url"] == _FIXTURE_M3U8

    # Cache file is now refreshed -- check the value reflects the new cookies.
    import json as _json

    saved = _json.load(open(tmp_path / _CACHE_SUBDIR / _CACHE_FILENAME, encoding="utf-8"))
    assert any(c["value"] == "fresh" for c in saved["cookies"])
    assert saved["user_agent"] == "UA-fresh"


def test_cache_missing_cf_clearance_treated_as_no_cache(monkeypatch, tmp_path):
    # Cache file exists but has no cf_clearance cookie -- treat as no cache,
    # go through the bypass refresh path.
    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191")
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))
    _write_cache(str(tmp_path), [{"name": "PHPSESSID", "value": "x", "domain": "nepu.to"}], user_agent="UA-old")

    fresh_cookies = [
        {"name": "cf_clearance", "value": "new", "domain": ".nepu.to", "path": "/"},
    ]
    ie, captured = _make_extractor_with_bypass_and_webpage(
        NepuMovieIE, _MOVIE_HTML, cookies=fresh_cookies, user_agent="UA-new"
    )
    ie._real_extract("https://nepu.to/movie/synthetic-movie-1")
    assert captured["bypass_calls"] == 1


def test_cache_save_filters_to_nepu_cookies(monkeypatch, tmp_path):
    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191")
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))

    # Bypass returns nepu + hcaptcha cookies. Save should drop the hcaptcha
    # one so the file isn't polluted with off-origin state.
    mixed_cookies = [
        {"name": "cf_clearance", "value": "abc", "domain": ".nepu.to", "path": "/"},
        {"name": "PHPSESSID", "value": "xyz", "domain": "nepu.to", "path": "/"},
        {"name": "__cf_bm", "value": "hcap", "domain": ".hcaptcha.com", "path": "/"},
    ]
    ie, _ = _make_extractor_with_bypass_and_webpage(NepuMovieIE, _MOVIE_HTML, cookies=mixed_cookies)
    ie._real_extract("https://nepu.to/movie/synthetic-movie-1")

    import json as _json

    saved = _json.load(open(tmp_path / _CACHE_SUBDIR / _CACHE_FILENAME, encoding="utf-8"))
    domains = {c["domain"] for c in saved["cookies"]}
    assert ".hcaptcha.com" not in domains
    assert any("nepu.to" in d for d in domains)


def test_cached_session_page_fetch_failure_falls_back(monkeypatch, tmp_path):
    # Cache exists with cookies, but the page response doesn't have a
    # data-embed (simulating an expired cf_clearance -> CF challenge page).
    # The extractor should invalidate the cache and retry via the bypass.
    monkeypatch.setenv(_BYPASS_ENV, "http://byparr:8191")
    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path))

    cookies = [{"name": "cf_clearance", "value": "expired", "domain": ".nepu.to", "path": "/"}]
    _write_cache(str(tmp_path), cookies, user_agent="UA-stale")

    cf_challenge_page = "<html><head><title>Just a moment...</title></head><body></body></html>"
    fresh_cookies = [{"name": "cf_clearance", "value": "fresh", "domain": ".nepu.to", "path": "/"}]

    ydl = YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True})
    ie = NepuMovieIE(ydl)

    state = {"bypass_calls": 0, "page_calls": 0}

    def fake_download_json(url_or_request, video_id, *args, **kwargs):
        state["bypass_calls"] += 1
        return {
            "status": "ok",
            "solution": {"response": _MOVIE_HTML, "cookies": fresh_cookies, "userAgent": "UA-fresh"},
        }

    def fake_download_webpage(url_or_request, video_id, *args, **kwargs):
        url = url_or_request if isinstance(url_or_request, str) else url_or_request.url
        state["page_calls"] += 1
        if _EMBED_API in url:
            return _EMBED_RESPONSE
        # First page call (cached session) -> CF challenge page.
        # Second page call (bypass refresh) is short-circuited by the bypass
        # which returned _MOVIE_HTML in its solution -- but the extractor
        # actually re-fetches the page through _download_webpage for the
        # non-cached path too. Both return _MOVIE_HTML for the second hit.
        if state["page_calls"] == 1:
            return cf_challenge_page
        return _MOVIE_HTML

    ie._download_json = fake_download_json  # type: ignore[assignment]
    ie._download_webpage = fake_download_webpage  # type: ignore[assignment]

    info = ie._real_extract("https://nepu.to/movie/synthetic-movie-1")

    assert state["bypass_calls"] == 1, "must refresh via bypass after cached-session failure"
    assert info["url"] == _FIXTURE_M3U8
    # The cache file should have been invalidated, then re-written with the
    # fresh session.
    import json as _json

    saved = _json.load(open(tmp_path / _CACHE_SUBDIR / _CACHE_FILENAME, encoding="utf-8"))
    assert any(c["value"] == "fresh" for c in saved["cookies"])


def test_cache_dir_env_override(monkeypatch, tmp_path):
    # WHYKNOT_PLUGIN_STATE_DIR should be honoured.
    from yt_dlp_plugins.extractor.nepu import _nepu_cache_dir

    monkeypatch.setenv(_CACHE_DIR_ENV, str(tmp_path / "custom"))
    assert _nepu_cache_dir() == str(tmp_path / "custom")
