#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MODULE_PATH = SCRIPT_DIR / "generate_release_notes.py"


def load_module():
    spec = importlib.util.spec_from_file_location("generate_release_notes", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def commit_file(repo: Path, name: str, content: str, subject: str) -> None:
    path = repo / name
    path.write_text(content, encoding="utf-8")
    run("git", "add", name, cwd=repo)
    run("git", "commit", "-m", subject, cwd=repo)


def compose_for(module, repo: Path, tag: str) -> str:
    args = argparse.Namespace(
        tag=tag,
        repo="WhyKnot/whyknot-yt-dlp-plugins",
        wheel=None,
        wheel_sha=None,
        wheel_size=0,
        sdist=None,
        sdist_sha=None,
        sdist_size=0,
        template_dir=str(repo / ".github" / "release-template"),
        extras=None,
        allow_empty=False,
        skip_scrub=True,
    )
    old_cwd = Path.cwd()
    try:
        os.chdir(repo)
        return module.compose(args)
    finally:
        os.chdir(old_cwd)


def main() -> int:
    module = load_module()

    with tempfile.TemporaryDirectory(prefix="release-notes-test-") as tmp:
        repo = Path(tmp)
        run("git", "init", "-q", cwd=repo)
        run("git", "config", "user.email", "release-test@example.com", cwd=repo)
        run("git", "config", "user.name", "Release Test", cwd=repo)
        (repo / ".github" / "release-template").mkdir(parents=True)
        for name in ("links", "install", "local-dev", "what-you-need-to-do"):
            (repo / ".github" / "release-template" / f"{name}.md").write_text("", encoding="utf-8")

        commit_file(repo, "sample.txt", "base\n", "chore: base")
        run("git", "tag", "v2026.5.1.0", cwd=repo)

        commit_file(repo, "sample.txt", "beta\n", "feat: beta patch")
        run("git", "tag", "v2026.5.2.0-beta", cwd=repo)

        commit_file(repo, "sample.txt", "stable\n", "fix: stable patch")
        run("git", "tag", "v2026.5.3.0", cwd=repo)

        stable = compose_for(module, repo, "v2026.5.3.0")
        if "feat: beta patch" not in stable:
            raise AssertionError("stable release notes did not include beta patch")
        if "fix: stable patch" not in stable:
            raise AssertionError("stable release notes did not include stable patch")
        if "compare/v2026.5.1.0...v2026.5.3.0" not in stable:
            raise AssertionError("stable release did not compare from previous stable tag")
        if "compare/v2026.5.2.0-beta...v2026.5.3.0" in stable:
            raise AssertionError("stable release compared from beta tag")

        beta = compose_for(module, repo, "v2026.5.2.0-beta")
        if "feat: beta patch" not in beta:
            raise AssertionError("beta release notes did not include beta patch")
        if "fix: stable patch" in beta:
            raise AssertionError("beta release notes included a later stable patch")
        if "compare/v2026.5.1.0...v2026.5.2.0-beta" not in beta:
            raise AssertionError("beta release did not compare from nearest previous tag")

    print("generate_release_notes tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
