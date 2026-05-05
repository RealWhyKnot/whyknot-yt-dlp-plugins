# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to CalVer `YYYY.M.D.N` (matching the wider WhyKnot
release versioning where N is the daily build counter starting at 0).

## Unreleased

_No notable changes since the last release._

---

## [v2026.5.5.0] - 2026-05-05

### Added

- Initial scaffold of the plugin namespace `yt_dlp_plugins.extractor`.
- Placeholder extractor `WhyKnotPluginPlaceholderIE` matching
  `https://plugin-test.whyknot.dev/test/<id>` to prove plugin discovery
  end-to-end. Delete once the first real extractor lands.
- CI workflow verifying the plugin namespace is discovered by yt-dlp and
  the placeholder extract simulation passes across Python 3.10 to 3.13.

### Changed

- Versioning aligned to the wider WhyKnot CalVer scheme `YYYY.M.D.N`.
  Dropped the `0.1.x` semver track that was used during the bootstrap
  pre-alignment commits.

### Fixed

- `yt-dlp` removed from the runtime `dependencies` list. Listing it
  caused pip/uv to resolve to the latest stable yt-dlp on plugin
  install, which clobbered production nodes' `--pre` (nightly) yt-dlp
  back down to stable. The plugin loader only requires co-residency of
  yt-dlp in the same Python environment, not a pinned version.
