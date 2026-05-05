# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-05-05

### Fixed

- Drop `yt-dlp` from runtime `dependencies`. Listing it caused pip/uv to
  resolve to the latest stable yt-dlp on plugin install, which clobbered
  production nodes' `--pre` (nightly) yt-dlp back down to stable. The
  plugin loader only requires co-residency of yt-dlp in the same Python
  environment, not a pinned version, so removing the dependency is the
  correct fix. Verified on a production container: nightly survives
  plugin upgrade.

## [0.1.0] - 2026-05-05

### Added

- Initial scaffold of the plugin namespace `yt_dlp_plugins.extractor`.
- Placeholder extractor `WhyKnotPluginPlaceholderIE` matching
  `https://plugin-test.whyknot.dev/test/<id>` to prove plugin discovery
  end-to-end. Delete once the first real extractor lands.
- CI workflow `.github/workflows/test.yml` verifying the plugin namespace
  is discovered by yt-dlp and the placeholder extract simulation passes.
