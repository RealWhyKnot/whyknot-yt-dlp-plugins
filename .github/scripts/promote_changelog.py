#!/usr/bin/env python3
"""
Promote-on-tag CHANGELOG maintenance for whyknot-yt-dlp-plugins.

Spirit-port of WKVRCProxy/.github/scripts/Update-Changelog.ps1's Promote and
Notes modes. Rewrites the "## Unreleased" heading to a versioned heading
linked to the GitHub release page, inserts a fresh empty "## Unreleased"
section above. With --notes-only, prints the section body to stdout instead
of mutating the file.

Invoked by .github/workflows/release.yml on `v*` tag push.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

CHANGELOG = Path("CHANGELOG.md")


def find_unreleased(text: str) -> tuple[int, int]:
    """Return (start_of_body, end_of_body) for the '## Unreleased' section."""
    m = re.search(r"(?m)^## +Unreleased\s*$", text)
    if not m:
        raise SystemExit("CHANGELOG.md missing '## Unreleased' heading")
    start = m.end()
    tail = text[start:]
    end_m = re.search(r"(?m)^(---|## )", tail)
    end = start + (end_m.start() if end_m else len(tail))
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="Tag name e.g. v2026.5.5.0")
    parser.add_argument("--notes-only", action="store_true",
                        help="Print the Unreleased body to stdout, don't mutate the file.")
    args = parser.parse_args()

    text = CHANGELOG.read_text(encoding="utf-8")
    start, end = find_unreleased(text)
    body = text[start:end].strip("\n")

    if args.notes_only:
        # Strip the "_No notable changes_" placeholder if present
        if body.strip() in ("", "_No notable changes since the last release._"):
            print("")
        else:
            print(body)
        return 0

    today = dt.date.today().isoformat()
    repo = os.environ.get("GITHUB_REPOSITORY", "RealWhyKnot/whyknot-yt-dlp-plugins")
    new_heading = f"## [{args.tag}](https://github.com/{repo}/releases/tag/{args.tag}) - {today}"

    # Replace the "## Unreleased" line with the versioned heading, and prepend
    # a fresh "## Unreleased" section + separator above it.
    fresh_unreleased = (
        "## Unreleased\n"
        "\n"
        "_No notable changes since the last release._\n"
        "\n"
        "---\n"
        "\n"
    )
    # Find the literal "## Unreleased" line and rewrite it.
    new_text = re.sub(
        r"(?m)^## +Unreleased\s*$",
        fresh_unreleased + new_heading,
        text,
        count=1,
    )

    CHANGELOG.write_text(new_text, encoding="utf-8")
    print(f"Promoted Unreleased -> {args.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
