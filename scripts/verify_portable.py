"""Verify that a built bundle keeps beets' state inside itself.

The whole point of the bundle is that it is self-contained: running it must not
write beets' config/database into the OS config directory (``%APPDATA%\\beets``,
``~/.config/beets``). This runs the frozen executable with no ``BEETSDIR`` set —
exactly how a user starts it — and checks that the portable directory appears
inside the bundle, that the shipped defaults were seeded, and that the OS config
directory was left alone.

The portable directory is removed afterwards so the CI artifact ships clean,
without a pre-populated library.

Usage:
    python scripts/verify_portable.py --dist build/indie_beets.dist
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PORTABLE_DIR_NAME = "beets-data"


def os_config_dir() -> Path:
    """Where beets would put its files without our override."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(base) / "beets"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "beets"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", required=True)
    args = ap.parse_args()

    dist = Path(args.dist).resolve()
    beet = dist / ("beet.exe" if sys.platform == "win32" else "beet")
    if not beet.exists():
        raise SystemExit(f"verify_portable: not found: {beet}")

    portable = dist / PORTABLE_DIR_NAME
    if portable.exists():
        shutil.rmtree(portable)

    # Note what the OS location looks like now, so we can prove we didn't touch it.
    osdir = os_config_dir()
    before = sorted(p.name for p in osdir.iterdir()) if osdir.is_dir() else None

    env = {k: v for k, v in os.environ.items() if k != "BEETSDIR"}
    proc = subprocess.run([str(beet), "version"], env=env, text=True,
                          capture_output=True)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"verify_portable: `beet version` failed ({proc.returncode})")

    problems = []
    if not (portable / "config.yaml").is_file():
        problems.append(f"{PORTABLE_DIR_NAME}/config.yaml was not created")
    if not (portable / "library.db").is_file():
        problems.append(f"{PORTABLE_DIR_NAME}/library.db was not created")
    # The seeded config must actually take effect, or the batteries are dead.
    if "plugins:" not in proc.stdout:
        problems.append("no plugins line in `beet version` output")
    elif "replaygain" not in proc.stdout:
        problems.append(f"bundled plugins not active: {proc.stdout.strip()!r}")

    after = sorted(p.name for p in osdir.iterdir()) if osdir.is_dir() else None
    if before != after:
        problems.append(f"the OS config dir {osdir} changed: {before} -> {after}")

    shutil.rmtree(portable, ignore_errors=True)  # keep the artifact clean

    if problems:
        for p in problems:
            print(f"PORTABLE CHECK FAILED: {p}", file=sys.stderr)
        return 1
    print(f"PORTABLE OK: state stayed in {PORTABLE_DIR_NAME}/, {osdir} untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
