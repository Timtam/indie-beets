"""Download and stage the bundled helper binaries (the "batteries").

Populates ``bin/`` next to the build with ``ffmpeg``/``ffprobe`` (transcoding,
ReplayGain) and ``fpcalc`` (acoustic fingerprinting for the chroma plugin), for
the platform this script runs on. GStreamer is handled separately in Phase 2.

All versions/URLs are pinned here so this is the single source of truth. Run it
before packaging; the build's runtime_env.py adds ``bin/`` to PATH at startup.

Usage:
    python scripts/stage_binaries.py [--dest DIR]
"""

from __future__ import annotations

import argparse
import io
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# --- Pinned versions ---------------------------------------------------------
CHROMAPRINT_VERSION = "1.6.0"
CHROMAPRINT_BASE = (
    f"https://github.com/acoustid/chromaprint/releases/download/v{CHROMAPRINT_VERSION}"
)
# BtbN provides reproducible-ish per-release ffmpeg builds for Windows/Linux.
# NOTE: BtbN does NOT build macOS; macOS uses evermeet.cx (verified in CI).
FFMPEG_BTBN_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"


def platform_key() -> str:
    """Normalized (os, arch) key used to select assets."""
    system = sys.platform
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if system == "win32":
        return "win64"
    if system == "darwin":
        return "macos-arm64" if arm else "macos-x86_64"
    if system.startswith("linux"):
        return "linuxarm64" if arm else "linux64"
    raise RuntimeError(f"Unsupported platform: {system}/{machine}")


# --- Asset tables ------------------------------------------------------------
# fpcalc archives per platform key.
FPCALC_ASSET = {
    "win64": f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-windows-x86_64.zip",
    "linux64": f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-linux-x86_64.tar.gz",
    "linuxarm64": f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-linux-arm64.tar.gz",
    "macos-x86_64": f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-macos-x86_64.tar.gz",
    "macos-arm64": f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-macos-arm64.tar.gz",
}

# ffmpeg archives. macOS pulls a static build from evermeet.cx instead of BtbN.
FFMPEG_ASSET = {
    "win64": f"{FFMPEG_BTBN_BASE}/ffmpeg-n8.1-latest-win64-gpl-8.1.zip",
    "linux64": f"{FFMPEG_BTBN_BASE}/ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz",
    "linuxarm64": f"{FFMPEG_BTBN_BASE}/ffmpeg-n8.1-latest-linuxarm64-gpl-8.1.tar.xz",
    # evermeet serves the latest static build directly as a zip.
    "macos-x86_64": "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
    "macos-arm64": "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
}
FFPROBE_MACOS = "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"


def _download(url: str) -> bytes:
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "indie-beets"})
    with urllib.request.urlopen(req) as resp:  # noqa: S310 (pinned hosts)
        return resp.read()


def _extract_members(data: bytes, names: list[str], dest: Path) -> None:
    """Extract files whose basename is in ``names`` (flattened into ``dest``)."""
    wanted = set(names)
    found: set[str] = set()
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                base = Path(info.filename).name
                if base in wanted:
                    with zf.open(info) as src, (dest / base).open("wb") as out:
                        shutil.copyfileobj(src, out)
                    found.add(base)
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:  # handles .gz/.xz
            for member in tf.getmembers():
                base = Path(member.name).name
                if member.isfile() and base in wanted:
                    src = tf.extractfile(member)
                    if src is not None:
                        with src, (dest / base).open("wb") as out:
                            shutil.copyfileobj(src, out)
                        found.add(base)
    missing = wanted - found
    if missing:
        raise RuntimeError(f"archive did not contain expected files: {missing}")


def stage(dest: Path) -> None:
    key = platform_key()
    dest.mkdir(parents=True, exist_ok=True)
    exe = ".exe" if key == "win64" else ""

    print(f"Staging batteries for '{key}' into {dest}")

    print("- fpcalc")
    _extract_members(
        _download(f"{CHROMAPRINT_BASE}/{FPCALC_ASSET[key]}"),
        [f"fpcalc{exe}"],
        dest,
    )

    print("- ffmpeg / ffprobe")
    _extract_members(
        _download(FFMPEG_ASSET[key]),
        [f"ffmpeg{exe}", f"ffprobe{exe}"],
        dest,
    )
    if key.startswith("macos"):
        # evermeet ships ffmpeg and ffprobe as separate archives.
        _extract_members(_download(FFPROBE_MACOS), ["ffprobe"], dest)

    # Make the binaries executable on POSIX.
    if exe == "":
        for f in dest.iterdir():
            f.chmod(0o755)

    print("Staged:", ", ".join(sorted(p.name for p in dest.iterdir())))


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage bundled helper binaries.")
    parser.add_argument(
        "--dest",
        default=str(REPO_ROOT / "bin"),
        help="Directory to place binaries in (default: ./bin).",
    )
    args = parser.parse_args()
    stage(Path(args.dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
