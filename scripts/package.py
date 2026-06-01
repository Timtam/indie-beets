"""Package a built + staged bundle into a distributable archive.

Run order in CI (and locally):
    1. python scripts/build.py            -> build/indie_beets.dist/
    2. python scripts/stage_binaries.py --dest build/indie_beets.dist/bin
    3. python scripts/package.py          -> dist/indie-beets-<ver>-<plat>.<ext>

Produces a .zip on Windows and a .tar.gz on macOS/Linux containing the whole
standalone folder (executable + deps + bundled binaries), plus an example
config and the README.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = REPO_ROOT / "build" / "indie_beets.dist"


def project_version() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def platform_tag() -> str:
    import platform

    arch = platform.machine().lower()
    # Normalize so archive names match the CI matrix / stage_binaries keys.
    arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(arch, arch)
    if sys.platform == "win32":
        return f"windows-{arch}"
    if sys.platform == "darwin":
        return f"macos-{arch}"
    return f"linux-{arch}"


def add_extras(dist: Path) -> None:
    """Drop a usable example config and the README into the bundle root."""
    example = REPO_ROOT / "config" / "default_config.yaml"
    if example.is_file():
        shutil.copy2(example, dist / "config.example.yaml")
    readme = REPO_ROOT / "README.md"
    if readme.is_file():
        shutil.copy2(readme, dist / "README.md")


def make_archive(dist: Path, out_dir: Path, base_name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Everything lands under a top-level folder named after the archive.
    if sys.platform == "win32":
        archive = out_dir / f"{base_name}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in dist.rglob("*"):
                zf.write(path, Path(base_name) / path.relative_to(dist))
    else:
        archive = out_dir / f"{base_name}.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(dist, arcname=base_name)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Package the built bundle.")
    parser.add_argument("--dist", default=str(DEFAULT_DIST), help="Built .dist folder.")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "dist"), help="Where to write the archive.")
    args = parser.parse_args()

    dist = Path(args.dist)
    if not dist.is_dir():
        print(f"ERROR: dist folder not found: {dist}", file=sys.stderr)
        return 1

    add_extras(dist)
    base_name = f"indie-beets-{project_version()}-{platform_tag()}"
    archive = make_archive(dist, Path(args.out_dir), base_name)
    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"Packaged: {archive} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
