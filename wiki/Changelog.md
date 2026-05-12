# Changelog

All notable user-visible changes to whyknot-yt-dlp-plugins. Mirrors the root [CHANGELOG.md](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/blob/main/CHANGELOG.md) and is mirrored into the GitHub Wiki by `.github/workflows/wiki-sync.yml`.

## Unreleased

_No notable changes since the last release._

---

## [v2026.5.12.0](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.12.0) - 2026-05-12

### Added
- **nepu:** Add extractor for nepu.to movies and show episodes.

---

## [v2026.5.8.0](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.8.0) - 2026-05-08

### Removed
- **tubi:** Tubi override extractor and its corpus. The package is now intentionally a placeholder with only the offline-safe plugin discovery sentinel.

### Changed
- **package:** Version bumped to `2026.5.8.0` so production update paths can observe a new package version.

### Fixed
- **build:** Write `pyproject.toml` as UTF-8 without BOM during local Windows PowerShell builds so Hatchling can parse it.

---

## [v2026.5.6.0](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.6.0) - 2026-05-06

### Added
- **tubi:** Override extractor with per-language audio tagging.

### Changed
- **release:** Release body composer replaces the inline-string release notes. Composes title + auto-changelog slice + wheel/sdist integrity table + four templated sections + optional `release-extras/<tag>.md`.
- **release:** Smoke step downloads the published wheel and verifies plugin discovery in a clean venv against the placeholder URL.
- **changelog-append:** Bot-authored append commit now goes through the GraphQL `createCommitOnBranch` mutation so the commit is signed server-side and lands `verified=true`.

---

## [v2026.5.5.0](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.5.0) - 2026-05-05

### Added
- Initial scaffold of the plugin namespace `yt_dlp_plugins.extractor`.
- Placeholder extractor `WhyKnotPluginPlaceholderIE` matching `https://plugin-test.whyknot.dev/test/<id>` to prove plugin discovery end-to-end.
- CI workflow verifying the plugin namespace is discovered by yt-dlp and the placeholder extract simulation passes across Python 3.10 to 3.13.

### Changed
- Versioning aligned to the wider WhyKnot CalVer scheme `YYYY.M.D.N`.

### Fixed
- `yt-dlp` removed from the runtime `dependencies` list. Listing it caused pip/uv to resolve to the latest stable yt-dlp on plugin install, which clobbered production nodes' `--pre` (nightly) yt-dlp back down to stable.
