from nepu_shared import *


@pytest.mark.parametrize(
    "url, expected_id",
    [
        ("https://nepu.to/movie/some-slug-12345", "some-slug-12345"),
        ("http://nepu.to/movie/some-slug-12345", "some-slug-12345"),
        ("https://www.nepu.to/movie/some-slug-12345", "some-slug-12345"),
        ("https://nepu.to/movie/a-b-c-d-99", "a-b-c-d-99"),
    ],
)
def test_movie_valid_url_matches(url, expected_id):
    assert NepuMovieIE.suitable(url)
    match = NepuMovieIE._match_valid_url(url)
    assert match is not None
    assert match.group("id") == expected_id


@pytest.mark.parametrize(
    "url",
    [
        "https://nepu.to/show/some-slug-12345/season/1/episode/1",  # show, not movie
        "https://example.com/movie/some-slug-12345",  # wrong host
        "https://nepu.to/movies/some-slug-12345",  # wrong path ("movies")
        "https://nepu.to/movie/",  # empty slug
        "https://nepu.to/",  # root
    ],
)
def test_movie_valid_url_rejects(url):
    assert not NepuMovieIE.suitable(url)


# ---------------------------------------------------------------------------
# URL regex tests -- episodes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, show, season, episode",
    [
        ("https://nepu.to/show/some-show-1/season/1/episode/1", "some-show-1", "1", "1"),
        ("https://www.nepu.to/show/some-show-99/season/12/episode/3", "some-show-99", "12", "3"),
        ("http://nepu.to/show/a-b-c-7/season/2/episode/15", "a-b-c-7", "2", "15"),
    ],
)
def test_episode_valid_url_matches(url, show, season, episode):
    assert NepuEpisodeIE.suitable(url)
    match = NepuEpisodeIE._match_valid_url(url)
    assert match is not None
    assert match.group("show") == show
    assert match.group("season") == season
    assert match.group("episode") == episode


@pytest.mark.parametrize(
    "url",
    [
        "https://nepu.to/movie/some-slug-12345",  # movie, not episode
        "https://nepu.to/show/some-show-1/season/1",  # missing /episode/N
        "https://nepu.to/show/some-show-1/episode/1",  # missing /season/N
        "https://nepu.to/show/some-show-1/season/abc/episode/1",  # non-numeric season
        "https://example.com/show/some-show-1/season/1/episode/1",  # wrong host
    ],
)
def test_episode_valid_url_rejects(url):
    assert not NepuEpisodeIE.suitable(url)


# ---------------------------------------------------------------------------
# IE identity sanity
# ---------------------------------------------------------------------------


def test_ie_names():
    assert NepuMovieIE.IE_NAME == "whyknot:nepu:movie"
