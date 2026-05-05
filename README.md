# whyknot-yt-dlp-plugins

Custom yt-dlp extractors for sites that yt-dlp doesn't natively support but [WhyKnot.dev](https://whyknot.dev) needs to resolve for VRChat playback.

This package gets installed into the production WhyKnot nodes' yt-dlp venv, and yt-dlp picks it up automatically at startup. New extractors land here and ship to production within 24 hours via the nightly auto-update cron.

## Repository structure

```
yt_dlp_plugins/
  extractor/
    __init__.py
    placeholder.py          # delete once a real extractor lands
    <yoursite>.py           # one file per site, snake_case the host
pyproject.toml               # package metadata + version
CHANGELOG.md                 # bump version here on each change
.github/workflows/test.yml   # CI: install + verify plugin loads
```

The `yt_dlp_plugins/extractor/` path is **mandatory**. yt-dlp's plugin loader specifically searches the namespace `yt_dlp_plugins.extractor.*` across every installed Python package. Files placed anywhere else are not discovered.

## How the auto-install works

The WhyKnot.dev container Dockerfile installs this package into `/opt/yt-dlp-venv` at image build:

```
uv pip install --no-cache "whyknot-yt-dlp-plugins @ git+https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins.git@main"
```

A nightly cron at 01:00 UTC re-runs the same install with `-U` to pull the latest commit on `main`. The container's update script snapshots versions before each upgrade, runs a smoke (`yt-dlp --list-extractors | grep -i whyknot` + a placeholder extract simulation), and rolls back to the snapshot on smoke failure. So a broken commit on `main` lands in production for at most 24 hours before the next nightly cron tries again, and never replaces a working version unless the smoke passes.

The current production version surfaces in `/health`:

```
"binaries": {
  "whyknot_yt_dlp_plugins": {
    "version": "0.1.0",
    "last_update": "2026-05-05T01:00:13Z",
    "smoke_outcome": "ok"
  }
}
```

## How to add a new extractor

1. Create `yt_dlp_plugins/extractor/<hostname>.py` (use the host as the file stem, snake_case if needed).
2. Implement an `InfoExtractor` subclass:

   ```python
   from yt_dlp.extractor.common import InfoExtractor

   class ExampleSiteIE(InfoExtractor):
       IE_NAME = "examplesite"
       _VALID_URL = r"https?://(?:www\.)?example\.com/video/(?P<id>[0-9]+)"
       _TESTS = [{
           "url": "https://example.com/video/12345",
           "info_dict": {"id": "12345", "title": "Test", "ext": "mp4"},
           "params": {"skip_download": True},
       }]

       def _real_extract(self, url):
           video_id = self._match_id(url)
           webpage = self._download_webpage(url, video_id)
           title = self._html_extract_title(webpage)
           video_url = self._search_regex(
               r'<video[^>]+src="([^"]+)"', webpage, "video url")
           return {"id": video_id, "title": title, "url": video_url}
   ```

3. Bump `version` in `pyproject.toml` (semver: patch for fixes, minor for new sites, major for breaking changes).
4. Add a `CHANGELOG.md` entry.
5. Push to `main`. CI runs the test workflow; on green, the next nightly cron picks it up on each WhyKnot node.

The yt-dlp Plugin Development wiki has the full extractor API reference: <https://github.com/yt-dlp/yt-dlp/wiki/Plugin-Development>.

## Versioning + changelog

Every change to the plugin set bumps the version in `pyproject.toml` and adds a `CHANGELOG.md` entry. The version surfaces in the WhyKnot.dev `/health` payload, so an operator can correlate playback regressions against a specific plugin release without ssh'ing into a node.

## Local development

```
git clone https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins.git
cd whyknot-yt-dlp-plugins
python -m venv .venv && source .venv/bin/activate    # or .venv\Scripts\activate on Windows
pip install --upgrade pip
pip install --pre "yt-dlp[default]"
pip install -e .
yt-dlp -v --list-extractors | grep -i whyknot         # confirm plugin discovered
yt-dlp --simulate --skip-download \
  "https://plugin-test.whyknot.dev/test/sample"        # confirm placeholder extracts
```

## License

MIT. See [LICENSE](LICENSE).
