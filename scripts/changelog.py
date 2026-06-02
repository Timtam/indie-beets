"""Generate the bundled-component manifest (markdown) for a release.

Lists the pinned versions of everything in the bundle — beets, the build Python,
ffmpeg, fpcalc/Chromaprint, GStreamer, and the bundled plugins (incl. the
external beetcamp/beets-filetote) — per platform, since ffmpeg/GStreamer differ.
Sourced from the repo's single-source-of-truth pins (pyproject.toml,
requirements-build.txt, and the constants in stage_binaries/stage_gstreamer).

Usage: python scripts/changelog.py --version 2.10.0-1
"""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

# Run as `python scripts/changelog.py`, so this dir is on sys.path[0].
import stage_binaries
import stage_gstreamer

REPO_ROOT = Path(__file__).resolve().parents[1]

# Build Python per platform (kept in sync with .github/workflows/build.yml).
PY_WINDOWS, PY_LINUX, PY_MACOS = "3.13", "3.12", "3.12"


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def _beets_version(data: dict) -> str:
    for dep in data["project"]["dependencies"]:
        m = re.match(r"\s*beets==([0-9][0-9.]*)\s*$", dep)
        if m:
            return m.group(1)
    return "?"


def _req_versions(*names: str) -> dict[str, str]:
    """Pinned versions of given packages from requirements-build.txt."""
    out: dict[str, str] = {}
    text = (REPO_ROOT / "requirements-build.txt").read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if "==" in line and not line.startswith("#"):
            name, _, ver = line.partition("==")
            if name.lower() in {n.lower() for n in names}:
                out[name.lower()] = ver
    return out


def unreleased_notes(changelog: Path) -> str:
    """Extract the manually-maintained '## Unreleased' section of CHANGELOG.md."""
    if not changelog.is_file():
        return ""
    capturing = False
    out: list[str] = []
    for ln in changelog.read_text(encoding="utf-8").splitlines():
        if ln.strip().lower().startswith("## unreleased"):
            capturing = True
            continue
        if capturing and ln.startswith("## "):
            break
        if capturing:
            out.append(ln)
    return "\n".join(out).strip()


def render(version: str, notes: str = "") -> str:
    data = _pyproject()
    beets = _beets_version(data)
    plugins = data["tool"]["indie-beets"]["bundled-plugins"]
    ext = _req_versions("beetcamp", "beets-filetote", "beets-vgmdb")

    rows = [
        ("beets", beets, beets, beets),
        ("Python (build)", PY_WINDOWS, PY_LINUX, PY_MACOS),
        ("ffmpeg", stage_binaries.FFMPEG_BTBN_VERSION,
         stage_binaries.FFMPEG_BTBN_VERSION, stage_binaries.FFMPEG_MACOS_VERSION),
        ("fpcalc (Chromaprint)", stage_binaries.CHROMAPRINT_VERSION,
         stage_binaries.CHROMAPRINT_VERSION, stage_binaries.CHROMAPRINT_VERSION),
        ("GStreamer", stage_gstreamer.GSTREAMER_VERSION,
         "distro (1.26.x)", "— (not bundled)"),
        ("beetcamp (bandcamp)", ext.get("beetcamp", "?"),
         ext.get("beetcamp", "?"), ext.get("beetcamp", "?")),
        ("beets-filetote (filetote)", ext.get("beets-filetote", "?"),
         ext.get("beets-filetote", "?"), ext.get("beets-filetote", "?")),
        ("beets-vgmdb (VGMplug)", ext.get("beets-vgmdb", "?"),
         ext.get("beets-vgmdb", "?"), ext.get("beets-vgmdb", "?")),
    ]

    lines: list[str] = []
    if notes:
        lines += ["## Changes", "", notes, ""]
    lines += [
        f"## Bundled components — indie-beets {version}",
        "",
        "| Component | Windows | Linux | macOS |",
        "|-----------|---------|-------|-------|",
    ]
    lines += [f"| {c} | {w} | {l} | {m} |" for c, w, l, m in rows]
    lines += [
        "",
        f"**Bundled beets plugins:** {', '.join(plugins)}.",
        "",
        "_GStreamer (and the `bpd` plugin / `gstreamer` ReplayGain backend) is "
        "bundled on Windows + Linux only; macOS is ffmpeg-only (Nuitka #3628)._",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--changelog", default=str(REPO_ROOT / "CHANGELOG.md"),
                    help="CHANGELOG.md to read the '## Unreleased' notes from.")
    args = ap.parse_args()
    notes = unreleased_notes(Path(args.changelog))
    print(render(args.version, notes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
