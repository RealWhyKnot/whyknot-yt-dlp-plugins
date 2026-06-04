# Placeholder extractor that exists to prove the plugin namespace is
# discovered + loaded by yt-dlp at runtime while this repo has no real-site
# extractors. Matches a hostname under a WhyKnot-controlled subdomain that
# does not host real content (`plugin-test.whyknot.dev/test/<id>`), so it
# never fights with a real extractor and never sees real traffic.
#
# Smoke check used by the container's auto-update cron:
#   yt-dlp --simulate --skip-download \
#     "https://plugin-test.whyknot.dev/test/sample"
# expected: title="WhyKnot Plugin Loaded", id="sample".
#
# Keep this file while the repository is a placeholder. If real extractors are
# added later, either keep this sentinel for server update smoke or replace the
# smoke target with an equally offline-safe extractor test.

from yt_dlp.extractor.common import InfoExtractor


class WhyKnotPluginPlaceholderIE(InfoExtractor):
    IE_NAME = "whyknot:placeholder"
    IE_DESC = "WhyKnot plugin discovery sentinel"
    _VALID_URL = r"https?://plugin-test\.whyknot\.dev/test/(?P<id>[A-Za-z0-9_-]+)"
    _TESTS = [
        {
            "url": "https://plugin-test.whyknot.dev/test/sample",
            "info_dict": {
                "id": "sample",
                "title": "WhyKnot Plugin Loaded",
                "ext": "mp4",
            },
            "params": {"skip_download": True},
        }
    ]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        # No real network fetch -- this extractor's purpose is end-to-end
        # plugin-discovery proof, not media resolution. Returning a static
        # info_dict satisfies the yt-dlp test-runner contract while staying
        # offline-safe for CI.
        return {
            "id": video_id,
            "title": "WhyKnot Plugin Loaded",
            "ext": "mp4",
            "url": "https://plugin-test.whyknot.dev/static/empty.mp4",
        }
