"""Compute the next indie-beets release version: "<beets version>-<build>".

The beets part is the pinned version from pyproject.toml. The build number is
derived from existing git tags: the highest N among `v<beets>-<N>` tags plus one,
or 1 if no release exists for the current beets version yet. So `2.10.0-3` is
followed by `2.10.0-4`, but after a beets bump the first release is `2.11.0-1`.

Prints the version to stdout. Run after `git fetch --tags` so all tags are local.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def beets_version() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        deps = tomllib.load(fh)["project"]["dependencies"]
    for dep in deps:
        m = re.match(r"\s*beets==([0-9][0-9.]*)\s*$", dep)
        if m:
            return m.group(1)
    raise SystemExit("could not find a pinned 'beets==<version>' in pyproject.toml")


def next_build(beets_ver: str) -> int:
    tags = subprocess.run(
        ["git", "tag", "--list", f"v{beets_ver}-*"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    ).stdout.split()
    pat = re.compile(rf"^v{re.escape(beets_ver)}-(\d+)$")
    builds = [int(m.group(1)) for t in tags if (m := pat.match(t))]
    return max(builds) + 1 if builds else 1


def main() -> int:
    bv = beets_version()
    print(f"{bv}-{next_build(bv)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
