"""Download and stage the bundled helper binaries (the "batteries").

Populates a ``bin/`` directory with ``ffmpeg``/``ffprobe`` (transcoding,
ReplayGain), ``fpcalc`` (acoustic fingerprinting for the chroma plugin) and
``metaflac`` (beets' FLAC-only ReplayGain backend).

Platforms:
- Windows / Linux: static ffmpeg from BtbN, fpcalc from Chromaprint.
- macOS: ffmpeg/ffprobe from eugeneware/ffmpeg-static (has both arm64 and x64),
  fpcalc from Chromaprint. With ``--universal`` (used in CI on the Apple Silicon
  runner) the two macOS arches are lipo-merged into universal2 binaries and the
  ready-made universal fpcalc is used, so one bundle runs on Intel + Apple Silicon.
- metaflac: prebuilt from Xiph on Windows (the only platform they publish
  binaries for), compiled from the release tarball everywhere else.

GStreamer is handled separately (later phase). All versions/URLs are pinned here.

Usage:
    python scripts/stage_binaries.py [--dest DIR] [--universal]
"""

from __future__ import annotations

import argparse
import io
import platform
import shutil
import subprocess
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
# Windows/Linux: BtbN static ffmpeg (does NOT build macOS).
FFMPEG_BTBN_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
FFMPEG_BTBN_VERSION = "n8.1"  # ffmpeg series used on Windows/Linux (for changelog)
# macOS: eugeneware/ffmpeg-static ships static arm64 + x64 ffmpeg AND ffprobe.
# (Lags upstream a little — currently ffmpeg 6.1.1 — which is fine for beets.)
FFMPEG_STATIC_TAG = "b6.1.1"
FFMPEG_MACOS_VERSION = "6.1.1"  # ffmpeg version on macOS (for changelog)
FFMPEG_STATIC_BASE = (
    f"https://github.com/eugeneware/ffmpeg-static/releases/download/{FFMPEG_STATIC_TAG}"
)
# metaflac (FLAC tools) — powers beets 2.13's `metaflac` ReplayGain backend, which
# beets locates through PATH (shutil.which), i.e. our staged bin/ directory.
# Xiph publishes prebuilt binaries for Windows ONLY, so the other platforms build
# it from the release tarball (see _build_metaflac).
FLAC_VERSION = "1.5.0"
FLAC_BASE = f"https://github.com/xiph/flac/releases/download/{FLAC_VERSION}"
FLAC_WIN_ZIP = f"{FLAC_BASE}/flac-{FLAC_VERSION}-win.zip"
FLAC_SRC_TARBALL = f"{FLAC_BASE}/flac-{FLAC_VERSION}.tar.xz"


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


# fpcalc archives per platform key (+ a ready-made universal macOS build).
FPCALC_ASSET = {
    "win64": f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-windows-x86_64.zip",
    "linux64": f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-linux-x86_64.tar.gz",
    "linuxarm64": f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-linux-arm64.tar.gz",
    "macos-x86_64": f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-macos-x86_64.tar.gz",
    "macos-arm64": f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-macos-arm64.tar.gz",
    "macos-universal": f"chromaprint-fpcalc-{CHROMAPRINT_VERSION}-macos-universal.tar.gz",
}

# ffmpeg/ffprobe archives for Windows/Linux (BtbN).
FFMPEG_BTBN_ASSET = {
    "win64": f"{FFMPEG_BTBN_BASE}/ffmpeg-n8.1-latest-win64-gpl-8.1.zip",
    "linux64": f"{FFMPEG_BTBN_BASE}/ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz",
    "linuxarm64": f"{FFMPEG_BTBN_BASE}/ffmpeg-n8.1-latest-linuxarm64-gpl-8.1.tar.xz",
}

# macOS raw static binaries (eugeneware), keyed by arch suffix.
_MACOS_FFMPEG_ARCH = {"arm64": "arm64", "x86_64": "x64"}


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


def _write_binary(data: bytes, path: Path) -> None:
    path.write_bytes(data)
    path.chmod(0o755)


def _lipo(inputs: list[Path], output: Path) -> None:
    """Merge per-arch Mach-O binaries into a single universal2 binary."""
    subprocess.run(
        ["lipo", "-create", *map(str, inputs), "-output", str(output)],
        check=True,
    )
    output.chmod(0o755)


def _stage_metaflac_windows(dest: Path) -> None:
    """Extract the official Win64 metaflac.exe + libFLAC.dll.

    The zip ships Win32/ and Win64/ copies with identical basenames, so this
    matches on the archive path prefix instead of reusing _extract_members
    (which flattens by basename and would let Win32 clobber Win64).
    metaflac.exe links libFLAC dynamically; the DLL sits next to it in bin/,
    which is the first place Windows looks for a program's dependent DLLs.
    """
    data = _download(FLAC_WIN_ZIP)
    wanted = {"metaflac.exe", "libFLAC.dll"}
    found: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            parts = Path(info.filename).parts
            if len(parts) >= 2 and parts[-2] == "Win64" and parts[-1] in wanted:
                with zf.open(info) as src, (dest / parts[-1]).open("wb") as out:
                    shutil.copyfileobj(src, out)
                found.add(parts[-1])
    if missing := wanted - found:
        raise RuntimeError(f"flac zip did not contain expected Win64 files: {missing}")


def _build_metaflac(dest: Path, *, universal: bool = False) -> None:
    """Build a static metaflac from the FLAC release tarball (Linux/macOS).

    Xiph ships no Linux/macOS binaries, so we compile the one tool we need.
    FLAC defaults to a static build (BUILD_SHARED_LIBS=OFF) and dropping Ogg
    support leaves no external dependencies, so the result is a self-contained
    binary. On macOS CMake can emit a universal2 binary directly via
    CMAKE_OSX_ARCHITECTURES, so no lipo step is needed here.
    """
    data = _download(FLAC_SRC_TARBALL)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            tf.extractall(tmpdir)  # noqa: S202 (pinned upstream release)
        src = tmpdir / f"flac-{FLAC_VERSION}"
        build = tmpdir / "build"
        configure = [
            "cmake", "-S", str(src), "-B", str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DBUILD_SHARED_LIBS=OFF",   # static libFLAC -> standalone binary
            "-DWITH_OGG=OFF",            # drops the only external dependency
            "-DBUILD_CXXLIBS=OFF",       # libFLAC++ is unused by metaflac
            "-DBUILD_EXAMPLES=OFF",
            "-DBUILD_TESTING=OFF",
            "-DBUILD_DOCS=OFF",
            "-DINSTALL_MANPAGES=OFF",
        ]
        if universal:
            configure.append("-DCMAKE_OSX_ARCHITECTURES=arm64;x86_64")
        print(f"  building metaflac {FLAC_VERSION} from source")
        subprocess.run(configure, check=True, capture_output=True, text=True)
        subprocess.run(
            ["cmake", "--build", str(build), "--config", "Release",
             "--target", "metaflac", "--parallel"],
            check=True, capture_output=True, text=True,
        )
        built = build / "src" / "metaflac" / "metaflac"
        if not built.exists():  # be forgiving about generator layout
            candidates = [p for p in build.rglob("metaflac") if p.is_file()]
            if not candidates:
                raise RuntimeError("metaflac build produced no binary")
            built = candidates[0]
        shutil.copy2(built, dest / "metaflac")
        (dest / "metaflac").chmod(0o755)


def _stage_metaflac(dest: Path, *, universal: bool, key: str) -> None:
    if key == "win64":
        _stage_metaflac_windows(dest)
    else:
        _build_metaflac(dest, universal=universal)


def _stage_macos(dest: Path, *, universal: bool, key: str) -> None:
    """Stage ffmpeg/ffprobe/fpcalc on macOS (per-arch or universal2)."""
    if universal:
        # fpcalc: ready-made universal build.
        _extract_members(
            _download(f"{CHROMAPRINT_BASE}/{FPCALC_ASSET['macos-universal']}"),
            ["fpcalc"],
            dest,
        )
        # ffmpeg/ffprobe: download both arches and lipo-merge.
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            for tool in ("ffmpeg", "ffprobe"):
                slices = []
                for arch_suffix in ("arm64", "x64"):
                    p = tmpdir / f"{tool}-darwin-{arch_suffix}"
                    _write_binary(
                        _download(f"{FFMPEG_STATIC_BASE}/{tool}-darwin-{arch_suffix}"), p
                    )
                    slices.append(p)
                _lipo(slices, dest / tool)
    else:
        arch = "arm64" if key == "macos-arm64" else "x86_64"
        _extract_members(
            _download(f"{CHROMAPRINT_BASE}/{FPCALC_ASSET[key]}"), ["fpcalc"], dest
        )
        suffix = _MACOS_FFMPEG_ARCH[arch]
        for tool in ("ffmpeg", "ffprobe"):
            _write_binary(
                _download(f"{FFMPEG_STATIC_BASE}/{tool}-darwin-{suffix}"), dest / tool
            )


def _stage_archive_platform(dest: Path, key: str) -> None:
    """Stage on Windows/Linux from BtbN + Chromaprint archives."""
    exe = ".exe" if key == "win64" else ""
    _extract_members(
        _download(f"{CHROMAPRINT_BASE}/{FPCALC_ASSET[key]}"), [f"fpcalc{exe}"], dest
    )
    _extract_members(
        _download(FFMPEG_BTBN_ASSET[key]), [f"ffmpeg{exe}", f"ffprobe{exe}"], dest
    )
    if exe == "":
        for f in dest.iterdir():
            f.chmod(0o755)


def stage(dest: Path, *, universal: bool = False) -> None:
    key = platform_key()
    dest.mkdir(parents=True, exist_ok=True)

    if universal and not key.startswith("macos"):
        raise RuntimeError("--universal is only supported on macOS")

    label = "macos-universal" if universal else key
    print(f"Staging batteries for '{label}' into {dest}")

    if key.startswith("macos"):
        _stage_macos(dest, universal=universal, key=key)
    else:
        _stage_archive_platform(dest, key)

    _stage_metaflac(dest, universal=universal, key=key)

    print("Staged:", ", ".join(sorted(p.name for p in dest.iterdir())))


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage bundled helper binaries.")
    parser.add_argument(
        "--dest",
        default=str(REPO_ROOT / "bin"),
        help="Directory to place binaries in (default: ./bin).",
    )
    parser.add_argument(
        "--universal",
        action="store_true",
        help="macOS only: produce universal2 (arm64+x86_64) binaries.",
    )
    args = parser.parse_args()
    stage(Path(args.dest), universal=args.universal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
