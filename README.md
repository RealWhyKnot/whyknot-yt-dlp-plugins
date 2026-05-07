# whyknot-yt-dlp-plugins

**Custom yt-dlp extractors for sites WhyKnot.dev resolves.**

When a site isn't natively supported by yt-dlp but [WhyKnot.dev](https://whyknot.dev) needs to play it through VRChat, the extractor lives here. Production WhyKnot.dev nodes pick up new commits within seconds via a push webhook (cron-fallback within 24h), validate via smoke, and roll back on failure.

> **Status: alpha.** Plugin discovery + auto-update plumbing are stable; the extractor catalogue is bootstrap-thin until real sites land.

**[Latest release](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/latest)** -- **[Changelog](CHANGELOG.md)** -- **[Report a bug](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/issues/new)**

---

## What it does

1. Ships extractors in the `yt_dlp_plugins.extractor` namespace -- yt-dlp's plugin loader walks any installed package for that exact path.
2. Each WhyKnot.dev container installs this package at image build via `uv pip install` from the GitHub tarball URL.
3. A nightly cron at 01:00 UTC re-runs the same install with `-U` to pull `main`. A push webhook from this repo can trigger the same refresh within seconds.
4. Update flow snapshots installed versions, runs a smoke (placeholder extractor + `--simulate`), and rolls back to the snapshot on smoke failure. So a broken commit on `main` lives in production for the time between webhook fire and smoke fail (sub-second), and never replaces a working version.
5. `/health` on each WhyKnot.dev node surfaces `binaries.whyknot_yt_dlp_plugins.{version, last_update, smoke_outcome}` for out-of-band visibility.

The plugin contract: **only co-residency in the venv is required**. yt-dlp is intentionally NOT a runtime dependency in `pyproject.toml` -- listing it would cause pip/uv to fix the installed yt-dlp version on plugin install, clobbering nightly tracks.

---

## Get a new extractor in production

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

3. Bump version via `./build.ps1 -Version <YYYY.M.D.N>` or run `./build.ps1` to auto-derive a date-based version.
4. Add a `CHANGELOG.md` entry under `## Unreleased`.
5. Push to `main`. CI runs the test workflow on Python 3.10-3.13; on green, the next nightly cron (or the immediate webhook) lands it on each WhyKnot.dev node.

For the full extractor API, see the [yt-dlp Plugin Development wiki](https://github.com/yt-dlp/yt-dlp/wiki/Plugin-Development).

---

## Going deeper

- **Container integration:** the WhyKnot.dev Dockerfile installs this package at image build via `uv pip install "whyknot-yt-dlp-plugins @ https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/archive/refs/heads/main.tar.gz"`.
- **Auto-update script:** `whyknot-update-binaries.sh` lives in the WhyKnot.dev repo and does snapshot + upgrade + smoke + rollback for yt-dlp + streamlink + this plugin in one resolver pass.
- **Webhook receiver:** `POST /api/internal/plugin-update` on each node accepts GitHub webhook pushes (HMAC-verified) and triggers an immediate refresh.
- **Versioning:** CalVer `YYYY.M.D.N`. Daily build counter, no `-XXXX` suffix (no local-rebuild disambiguation needed for a server-deployed plugin).
- **Repository structure rules:** files anywhere outside `yt_dlp_plugins/extractor/` are not discovered by yt-dlp. Don't move modules; the namespace is hard-coded in yt-dlp's loader.

---

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

---

## License

Licensed under the GNU General Public License v3.0 or later. See [LICENSE](LICENSE) for the full text.
