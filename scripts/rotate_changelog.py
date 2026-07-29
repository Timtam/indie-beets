"""Move the '## Unreleased' notes under a released version heading.

Release notes are written by hand under ``## Unreleased`` in CHANGELOG.md and
read from there by ``changelog.py`` when a release is cut. That only yields "what
changed in this release" if the section is emptied afterwards — otherwise entries
pile up and every release repeats the previous ones. Doing that by hand was
forgotten, so the release job runs this instead.

Renames ``## Unreleased`` to ``## <version>`` and inserts a fresh empty
``## Unreleased`` above it. Idempotent: if there is nothing to release (empty
section) or the version heading already exists, the file is left alone.

Usage:
    python scripts/rotate_changelog.py --version 2.13.0-2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UNRELEASED = "## Unreleased"


def rotate(text: str, version: str) -> tuple[str, str]:
    """Return (new_text, status). ``status`` is '' when the file was changed."""
    lines = text.splitlines()

    start = next(
        (i for i, ln in enumerate(lines) if ln.strip().lower() == UNRELEASED.lower()),
        None,
    )
    if start is None:
        return text, f"no '{UNRELEASED}' heading found"
    if any(ln.strip() == f"## {version}" for ln in lines):
        return text, f"'## {version}' already exists"

    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    body = "\n".join(lines[start + 1 : end]).strip()
    if not body:
        return text, "nothing to release (Unreleased section is empty)"

    rotated = [
        *lines[:start],
        UNRELEASED,
        "",
        f"## {version}",
        "",
        *body.splitlines(),
        "",
        *lines[end:],
    ]
    return "\n".join(rotated).rstrip() + "\n", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="Version just released, e.g. 2.13.0-2")
    ap.add_argument("--changelog", default=str(REPO_ROOT / "CHANGELOG.md"))
    args = ap.parse_args()

    path = Path(args.changelog)
    new_text, status = rotate(path.read_text(encoding="utf-8"), args.version)
    if status:
        print(f"rotate_changelog: nothing to do — {status}")
        return 0
    path.write_text(new_text, encoding="utf-8")
    print(f"rotate_changelog: moved Unreleased notes under '## {args.version}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
