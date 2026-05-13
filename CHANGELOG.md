# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to CalVer `YYYY.M.D.N` (matching the wider WhyKnot
release versioning where N is the daily build counter starting at 0).

## Unreleased

_No notable changes since the last release._

---

## [v2026.5.13.2](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.13.2) - 2026-05-13
### Added
- **nepu:** Return Cookie + User-Agent + Referer in http_headers so the proxy carries the bypass session (4eaabc5)

---

## [v2026.5.13.1](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.13.1) - 2026-05-13
### Fixed
- **nepu:** Bump bypass HTTP timeout to 60 s so the ~14 s Byparr solve fits (92b8e3e)

---

## [v2026.5.13.0](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.13.0) - 2026-05-13
### Added
- **nepu:** Two-step resolve (page -> data-embed -> /ajax/embed) so the new player gets a real m3u8 (b405dd8)

---

## [v2026.5.12.1](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.12.1) - 2026-05-12
### Added
- **nepu:** Route fetches through FlareSolverr when WHYKNOT_FLARESOLVERR_URL is set (c536383)

---

## [v2026.5.12.0](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.12.0) - 2026-05-12
### Added
- **nepu:** Add extractor for nepu.to movies and show episodes (174a518)

---

## [v2026.5.8.0](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.8.0) - 2026-05-08
### Removed
- **tubi:** Removed the Tubi override extractor and its corpus. The package is now intentionally a placeholder with only the offline-safe plugin discovery sentinel.

### Changed
- **package:** Bumped version to `2026.5.8.0` so production update paths can observe a new package version.

### Fixed
- **build:** Write `pyproject.toml` as UTF-8 without BOM during local Windows PowerShell builds so Hatchling can parse it.

---

## [v2026.5.6.0](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.6.0) - 2026-05-06
### Added
- **tubi:** Override extractor that exposes per-resource audio renditions as language-tagged formats. Multi-language titles like `the-housemaid` are now selectable with `-f 'bv*+ba[language=ko]'`. Single-language titles inherit the resource-level language. Older `hlsv3` muxed catalog continues to work. Test corpus in `tests/tubi_corpus.md`.
- **tubi:** Override extractor with per-language audio tagging (fa93053)

### Changed
- **release:** Release body composer (`generate_release_notes.py`) replaces the inline-string release notes in `release.yml`. Composes title + auto-changelog slice + wheel/sdist integrity table + four templated sections + optional `release-extras/<tag>.md`. Same scrub gates (ASCII normalisation, voice + internal-vocabulary grep) as WKVRCProxy.
- **release:** Smoke step downloads the published wheel and verifies plugin discovery in a clean venv against the placeholder URL.
- **changelog-append:** Bot-authored append commit now goes through the GraphQL `createCommitOnBranch` mutation so the commit is signed server-side and lands `verified=true`. Required once branch protection requires signatures on `main`.
- **release:** Promotion of `## Unreleased` -> tagged section is now committed back to `main` via the same `createCommitOnBranch` path.

### Fixed
- **ci:** Use `-v --simulate` for plugin discovery (`--list-extractors` omits external plugin IEs) (b1438fc)

---

## [v2026.5.5.0](https://github.com/RealWhyKnot/whyknot-yt-dlp-plugins/releases/tag/v2026.5.5.0) - 2026-05-05

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
