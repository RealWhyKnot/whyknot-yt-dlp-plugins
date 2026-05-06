#!/usr/bin/env python3
"""
Generate the GitHub release body for a tag from the git-log slice plus per-repo
template sections plus an artifact integrity table for the wheel + sdist.

Spirit-port of WKVRCProxy/.github/scripts/Generate-ReleaseNotes.ps1, adapted
for a Python plugin repo: artifacts are wheel + sdist (not a single zip with
inner files), so the integrity table is a flat 2-line block instead of the
zip + indented-inner-files layout.

Section order (matches WKVRCProxy):

  1. Title (h1: "<repo> <tag>")
  2. What's Changed (auto-changelog from the commit slice between prev tag
     and this tag; bucketed by conventional-commit prefix)
  3. File integrity (wheel + sdist with size and SHA256)
  4. More (from .github/release-template/links.md, with token substitution)
  5. Install (from .github/release-template/install.md)
  6. Local development (from .github/release-template/local-dev.md)
  7. What you need to do (from .github/release-template/what-you-need-to-do.md)
  8. Optional extras (from .github/release-extras/<tag>.md if present;
     appended below with --- separator and ## Additional notes heading)

Slice composition: walks commits between prev tag and current tag. Skips
merge commits and commits containing "[skip changelog]". Strips trailing
version-stamp noise of the form " (YYYY.M.D.N)" that some commit messages
append to subjects. Groups by conventional-commit prefix when at least one
entry has one, otherwise emits a flat bullet list.

Prev-tag resolution is layered for resilience against history rewrites that
orphan the prior tag (rebase + force-push of main): describe + sanity gate,
then subject-match against the most recent published GitHub release, then
root-walk fallback. See resolve_prev_tag for details.

Templates and the optional extras file run through the same scrub gates as
commit subjects: ASCII normalisation pass, then non-ASCII fail, then a
voice / internal-vocab grep. Any violation in any input fails the workflow
and prints a remediation hint.

Outputs the markdown body to stdout. Exits non-zero on:
  * empty slice (no qualifying commits between prev and current tag)
  * voice or internal-only-vocabulary pattern in the final body
  * non-ASCII characters in the final body (after a normalisation pass)

Each failure prints a clear remediation hint so the operator knows whether
to amend a commit, mark one [skip changelog], or fix a template or extras.

Requires the checkout step to have used fetch-depth: 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CONVENTIONAL_RE = re.compile(
    r"^(?P<type>feat|fix|perf|refactor|revert|docs|style|test|ci|build|chore)"
    r"(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s+(?P<desc>.+)$"
)

CATEGORY_ORDER = [
    ("feat", "Features"),
    ("fix", "Bug Fixes"),
    ("perf", "Performance"),
    ("refactor", "Refactors"),
    ("revert", "Reverts"),
    ("docs", "Documentation"),
    ("style", "Style"),
    ("test", "Tests"),
    ("ci", "CI"),
    ("build", "Build"),
    ("chore", "Chores"),
]
CATEGORY_INDEX = {t: (i, name) for i, (t, name) in enumerate(CATEGORY_ORDER)}
OTHER_ORDER = len(CATEGORY_ORDER)

# Local git author -> GitHub @-handle. Auto-changelog emits "by @<author>" and
# GitHub @-mentions only resolve when the handle is the actual login. Local
# git config uses the brand "WhyKnot" but the GitHub login is "RealWhyKnot".
AUTHOR_HANDLE_MAP = {"WhyKnot": "RealWhyKnot"}

VERSION_STAMP_RE = re.compile(r"\s*\(\d{4}\.\d+\.\d+\.\d+(?:-[A-Fa-f0-9]+)?\)\s*")
WHITESPACE_RE = re.compile(r"\s{2,}")

# ASCII normalisation table. Applied silently before the strict scrub.
ASCII_SUBS = {
    "—": "--",        # em-dash
    "–": "-",         # en-dash
    "…": "...",       # ellipsis
    "“": '"',         # left double quote
    "”": '"',         # right double quote
    "‘": "'",         # left single quote
    "’": "'",         # right single quote
    " ": " ",         # non-breaking space
    "•": "*",         # bullet
    "×": "x",         # multiplication sign
    "→": "->",        # right arrow
    "←": "<-",        # left arrow
    "⇒": "=>",        # double right arrow
    "⇐": "<=",        # double left arrow
    "§": "section",   # section sign
    "¶": "paragraph", # pilcrow
}

# Voice + internal-only-vocabulary patterns. The release body is the public
# face of the repo; these patterns make it read like marketing prose or
# expose internal-only tooling references.
FORBIDDEN_PATTERNS = [
    r"\bcomprehensive\b",
    r"\bleveraging\b",
    r"\bwhether\s+you'?re\b",
    r"\bempowers?\b",
    r"\bstreamline\b",
    r"\belevate\b",
    r"\bcutting-edge\b",
    r"\bseamless(ly)?\b",
    r"\belegant\b",
    r"\binvestigator\b",
    r"\btriage\b",
    r"\bscope plan\b",
    r"\btier [0-9]\b",
    r"\bdiagnostic gap\b",
    r"\bship report\b",
    r"\bmemory entry\b",
    r"\bverification matrix\b",
    r"\borchestrator\b",
    r"\bcowork\b",
    r"\bfuture-you\b",
    r"\bfuture contributor\b",
    r"\bfuture spelunker\b",
    r"\b\d+ weeks of work\b",
    r"\bmonths of effort\b",
    r"\byears in the making\b",
]


def warn(msg: str) -> None:
    print(f"::warning::{msg}", file=sys.stderr)


def run_git(*args: str) -> tuple[int, str]:
    p = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "").strip()


def run_gh(*args: str) -> tuple[int, str]:
    p = subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "").strip()


def resolve_prev_tag(tag: str, repo: str | None) -> dict:
    """Return {tag, log_args, display, source} for the slice anchor."""
    # Layer 1: describe + 50-commit sanity gate.
    rc, prev_ref = run_git("describe", "--tags", "--abbrev=0", f"{tag}^")
    if rc == 0 and prev_ref:
        prev_tag = prev_ref
        rc2, count = run_git("rev-list", "--count", f"{prev_tag}..{tag}")
        if rc2 == 0 and count.isdigit() and int(count) <= 50:
            return {
                "tag": prev_tag,
                "log_args": [f"{prev_tag}..{tag}"],
                "display": f"{prev_tag}..{tag}",
                "source": "describe",
            }
        warn(
            f"Slice from {prev_tag}..{tag} is {count} commits (>50 cap). "
            "Falling back to subject-match against the most recent published release."
        )

    # Layer 2: subject-match the most recent published GitHub release.
    if repo:
        rc, list_json = run_gh(
            "release", "list", "--repo", repo, "--limit", "20",
            "--json", "tagName,publishedAt,isPrerelease",
        )
        if rc == 0 and list_json:
            try:
                releases = json.loads(list_json)
                non_pre = [
                    r for r in releases
                    if r.get("tagName") != tag and not r.get("isPrerelease")
                ]
                non_pre.sort(key=lambda r: r.get("publishedAt", ""), reverse=True)
                candidate = non_pre[0] if non_pre else None
            except (json.JSONDecodeError, KeyError) as exc:
                warn(f"Failed to parse 'gh release list' output: {exc}")
                candidate = None

            if candidate:
                cand_tag = candidate["tagName"]
                rc, orphan_sha = run_git("rev-parse", cand_tag)
                if rc == 0 and orphan_sha:
                    rc, orphan_subject = run_git(
                        "show", "-s", "--format=%s", orphan_sha
                    )
                    if rc == 0 and orphan_subject:
                        rc, log_lines = run_git(
                            "log", tag, "--format=%H%x09%s"
                        )
                        if rc == 0 and log_lines:
                            for line in log_lines.splitlines():
                                if "\t" not in line:
                                    continue
                                sha, _, subj = line.partition("\t")
                                if subj == orphan_subject:
                                    short = sha[:12]
                                    warn(
                                        f"Subject-matched slice: prev tag {cand_tag} "
                                        f"(orphan sha {orphan_sha[:12]}) matches "
                                        f"current-history sha {short} by subject; "
                                        f"using {short}..{tag}."
                                    )
                                    return {
                                        "tag": cand_tag,
                                        "log_args": [f"{sha}..{tag}"],
                                        "display": f"{cand_tag}..{tag} (subject-matched at {short})",
                                        "source": "subject-match",
                                    }
                            warn(
                                f"Prev tag {cand_tag} subject '{orphan_subject}' not "
                                f"found in current {tag} history. Falling back to root walk."
                            )
        else:
            warn(
                "'gh release list' produced no usable output (gh not authed or "
                "no releases yet). Falling back to root walk."
            )

    # Layer 3: root walk.
    rc, roots = run_git("rev-list", "--max-parents=0", "HEAD")
    root = roots.splitlines()[0] if roots else ""
    warn(f"No prior tag matched; walking from root {root}.")
    return {
        "tag": None,
        "log_args": [f"{root}..{tag}"],
        "display": f"{root}..{tag} (root walk)",
        "source": "root",
    }


def collect_entries(log_args: list[str]) -> list[dict]:
    """Pull commit slice and parse into entry dicts."""
    rc, raw = run_git(
        "log", *log_args, "--no-merges", "--pretty=format:%H\t%h\t%an\t%s"
    )
    if rc != 0 or not raw:
        return []

    entries = []
    for line in raw.splitlines():
        if "[skip changelog]" in line:
            continue
        parts = line.split("\t", 3)
        if len(parts) < 4:
            continue
        sha, short, author, subject = parts
        if author in AUTHOR_HANDLE_MAP:
            author = AUTHOR_HANDLE_MAP[author]
        subject = VERSION_STAMP_RE.sub(" ", subject)
        subject = WHITESPACE_RE.sub(" ", subject).strip()
        entries.append(
            {"sha": sha, "short": short, "author": author, "subject": subject}
        )
    return entries


def categorise(subject: str) -> tuple[int, str]:
    m = CONVENTIONAL_RE.match(subject)
    if m:
        type_ = m.group("type")
        if type_ in CATEGORY_INDEX:
            return CATEGORY_INDEX[type_]
    return (OTHER_ORDER, "Other Changes")


def format_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.2f} KB"
    return f"{n} B"


def expand_tokens(text: str, tokens: dict[str, str]) -> str:
    if not text:
        return text
    for k, v in tokens.items():
        text = text.replace(k, v)
    return text


def read_template(name: str, template_dir: Path, tokens: dict[str, str]) -> str | None:
    path = template_dir / f"{name}.md"
    if not path.exists():
        warn(f"Release-body template missing: {path}. Section '{name}' will not render.")
        return None
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return None
    return expand_tokens(content, tokens)


def scrub(body: str) -> str:
    for src, dst in ASCII_SUBS.items():
        body = body.replace(src, dst)

    offenders = []
    for ln, line in enumerate(body.split("\n"), start=1):
        for col, ch in enumerate(line, start=1):
            code = ord(ch)
            if not ((0x20 <= code <= 0x7E) or code == 9):
                offenders.append(
                    f"  line {ln} col {col}: U+{code:04X} in: {line}"
                )
    if offenders:
        joined = "\n".join(offenders)
        raise SystemExit(
            "Non-ASCII characters in release body after normalisation:\n"
            f"{joined}\n"
            "Fix: amend the offending commit subject (or extras file) to use "
            "ASCII equivalents. Common substitutes are pre-mapped in "
            "generate_release_notes.py; if a new character trips this, add it "
            "to ASCII_SUBS and try again."
        )

    matches = []
    for pat in FORBIDDEN_PATTERNS:
        for m in re.finditer(pat, body, re.IGNORECASE):
            matches.append(f"  pattern {pat} matched '{m.group(0)}' at index {m.start()}")
    if matches:
        joined = "\n".join(matches)
        raise SystemExit(
            "voice or internal-only-vocabulary patterns in release body:\n"
            f"{joined}\n"
            "Fix: amend the offending commit subject (or extras file) to use "
            "plainer language, or mark the commit [skip changelog] if the term "
            "is unavoidable."
        )
    return body


def compose(args: argparse.Namespace) -> str:
    repo = args.repo
    tag = args.tag
    if not tag:
        raise SystemExit("No tag provided (pass --tag or set TAG_NAME / GITHUB_REF_NAME).")

    owner_only, repo_short = "", ""
    if repo and "/" in repo:
        owner_only, repo_short = repo.split("/", 1)
    elif repo:
        repo_short = repo

    prev = resolve_prev_tag(tag, repo)
    entries = collect_entries(prev["log_args"])

    if not entries:
        if args.allow_empty:
            return "## What's Changed\n\n_First release; see commit log for details._\n"
        raise SystemExit(
            f"No commits found in range {prev['display']}. "
            "Either the previous tag is misdetected, every commit in the range "
            "carries [skip changelog], or the tag points at an empty branch. "
            "Pass --allow-empty for a first release. Otherwise amend the offending "
            "commits or push a real change before tagging."
        )

    # Conventional-commit coverage warning (do not fail).
    non_conforming = [
        e for e in entries if not CONVENTIONAL_RE.match(e["subject"])
    ]
    if non_conforming:
        warn(
            f"{len(non_conforming)} commit(s) in range {prev['display']} do not "
            "follow conventional-commit prefixes; bucketed under 'Other Changes':"
        )
        for e in non_conforming:
            warn(f"  {e['short']}  {e['subject']}")

    # Token map for templates. Resolver fills {commit-sha} from the tag's commit.
    rc, tag_sha = run_git("rev-parse", tag)
    tag_sha = tag_sha if rc == 0 else ""
    tokens = {
        "{tag}": tag,
        "{version}": re.sub(r"^v", "", tag),
        "{owner}": owner_only,
        "{repo}": repo_short,
        "{full-repo}": repo or "",
        "{commit-sha}": tag_sha,
        "{commit-sha-short}": tag_sha[:12] if tag_sha else "",
        "{prior-tag}": prev["tag"] or "",
        "{wheel-name}": Path(args.wheel).name if args.wheel else "",
        "{sdist-name}": Path(args.sdist).name if args.sdist else "",
    }

    # Compose body.
    out: list[str] = []
    if repo_short:
        out.append(f"# {repo_short} {tag}")
        out.append("")
    out.append("## What's Changed")
    out.append("")

    use_groups = any(CONVENTIONAL_RE.match(e["subject"]) for e in entries)
    if use_groups:
        bucketed: dict[tuple[int, str], list[dict]] = {}
        for e in entries:
            key = categorise(e["subject"])
            bucketed.setdefault(key, []).append(e)
        for (order, name) in sorted(bucketed.keys(), key=lambda k: k[0]):
            out.append(f"### {name}")
            for e in bucketed[(order, name)]:
                out.append(f"- {e['subject']} by @{e['author']} in {e['short']}")
            out.append("")
    else:
        for e in entries:
            out.append(f"- {e['subject']} by @{e['author']} in {e['short']}")
        out.append("")

    if repo and prev["tag"]:
        out.append(f"**Full Changelog**: https://github.com/{repo}/compare/{prev['tag']}...{tag}")

    # File integrity: wheel + sdist.
    if args.wheel and args.wheel_sha and args.wheel_size and args.sdist and args.sdist_sha and args.sdist_size:
        out.append("")
        out.append("## File integrity")
        out.append("")
        out.append("Verify with `sha256sum <file>` on Linux/macOS or `Get-FileHash <file> -Algorithm SHA256` on PowerShell.")
        out.append("")
        out.append("```")
        wheel_name = Path(args.wheel).name
        sdist_name = Path(args.sdist).name
        out.append(
            f"{wheel_name:<48}    {format_bytes(args.wheel_size):>10}    SHA256: {args.wheel_sha.upper()}"
        )
        out.append(
            f"{sdist_name:<48}    {format_bytes(args.sdist_size):>10}    SHA256: {args.sdist_sha.upper()}"
        )
        out.append("```")

    # Templated evergreen sections in fixed order.
    template_dir = Path(args.template_dir)
    for name in ("links", "install", "local-dev", "what-you-need-to-do"):
        section = read_template(name, template_dir, tokens)
        if section:
            out.append("")
            out.append(section)

    # Optional release-specific extras.
    extras_path = Path(args.extras) if args.extras else (
        Path.cwd() / ".github" / "release-extras" / f"{tag}.md"
    )
    if extras_path.exists():
        extras_content = extras_path.read_text(encoding="utf-8").strip()
        if extras_content:
            out.append("")
            out.append("---")
            out.append("")
            out.append("## Additional notes")
            out.append("")
            out.append(extras_content)

    body = "\n".join(out).rstrip()
    if not args.skip_scrub:
        body = scrub(body)
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default=os.environ.get("TAG_NAME") or os.environ.get("GITHUB_REF_NAME"))
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--wheel", default=None, help="Path to the .whl artifact")
    parser.add_argument("--wheel-sha", default=None)
    parser.add_argument("--wheel-size", type=int, default=0)
    parser.add_argument("--sdist", default=None, help="Path to the .tar.gz sdist artifact")
    parser.add_argument("--sdist-sha", default=None)
    parser.add_argument("--sdist-size", type=int, default=0)
    parser.add_argument("--template-dir", default=".github/release-template")
    parser.add_argument("--extras", default=None)
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--skip-scrub", action="store_true")
    args = parser.parse_args()
    body = compose(args)
    sys.stdout.write(body)
    if not body.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
