"""Nuitka build driver for indie-beets.

Produces a standalone (folder) build of beets with our launcher entry point.
The same script runs on Windows, macOS and Linux; platform differences are kept
to a minimum here and handled by Nuitka itself.

Usage:
    python scripts/build.py [--with-gstreamer] [--onefile] [--output-dir DIR]

Run it from inside the build virtualenv (the one that has beets + nuitka
installed). The bundled plugin list is read from pyproject.toml so there is a
single source of truth.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Nuitka wants the *package directory* (which contains __main__.py), not the
# __main__.py file itself, to build a runnable package.
ENTRY_POINT = REPO_ROOT / "src" / "indie_beets"

# Optional third-party imports that some bundled plugins reach for lazily.
# Nuitka's static analysis can miss lazy imports, so we force the ones that
# matter for our shipped plugins. Keyed by plugin name.
PLUGIN_RUNTIME_DEPS: dict[str, list[str]] = {
    "chroma": ["acoustid"],
    "lyrics": ["bs4"],
    "VGMplug": ["lxml", "bs4"],  # beets-vgmdb: BeautifulSoup(..., "lxml")
}

# Modules we deliberately keep Nuitka from following into:
# - numba/scipy: beets *declares* them but its code never imports them (verified
#   by grepping installed beets + beetsplug, and lap's internals). Heavy, and
#   numba/llvmlite are notoriously hard to freeze. NOTE: lap and numpy ARE used
#   (beets/autotag/match.py: lap.lapjv on a numpy array drives track-to-item
#   assignment during import) — do not exclude them.
# - tkinter: beets is a CLI with no GUI. It gets pulled in transitively (e.g.
#   via PIL.ImageTk), and on the uv python-build-standalone macOS interpreter its
#   _tkinter.so links Tcl/Tk 9.0 through an @rpath Nuitka can't resolve, which is
#   fatal. Excluding it is harmless everywhere and slims the bundle.
# If a future beets version starts importing numba/scipy, the smoke test catches it.
UNUSED_HEAVY_DEPS = ["numba", "llvmlite", "scipy", "tkinter"]


def find_vcvars() -> Path | None:
    """Locate vcvars64.bat for the latest VS with the C++ toolchain.

    Nuitka 2.8 can't auto-detect very recent Visual Studio versions (e.g. VS 18)
    via the registry, so we activate the MSVC environment ourselves and run the
    build inside it. Returns None if no suitable VS install is found.
    """
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(program_files_x86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        return None
    try:
        install_path = subprocess.check_output(
            [
                str(vswhere), "-latest", "-products", "*",
                "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property", "installationPath",
            ],
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    if not install_path:
        return None
    vcvars = Path(install_path) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    return vcvars if vcvars.exists() else None


def read_bundled_plugins() -> list[str]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("tool", {}).get("indie-beets", {}).get("bundled-plugins", [])


def build_command(args: argparse.Namespace, plugins: list[str]) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        # Run the entry as `python -m indie_beets` so __main__ keeps its package
        # context and `from . import runtime_env` resolves at runtime.
        "--python-flag=-m",
        f"--output-dir={args.output_dir}",
        "--output-filename=beet",
        # beets core (our launcher package is the compiled entry point itself).
        "--include-package=beets",
        # All beets plugins live under this namespace package and are loaded by
        # name at runtime, so static analysis never sees them — force them in.
        "--include-package=beetsplug",
        # Core deps that use data files / dynamic bits Nuitka likes spelled out.
        "--include-package=mediafile",
        "--include-package=confuse",
        "--include-package-data=beets",
        "--include-package-data=beetsplug",  # plugin data files, e.g. lastgenre/genres.txt
        "--include-package-data=confuse",
        # requests imports its charset detector lazily, so Nuitka's analysis
        # drops it and requests falls back to no encoding detection. Force it in
        # (needed by fetchart/lyrics and any network plugin handling text).
        "--include-package=charset_normalizer",
    ]

    for module in UNUSED_HEAVY_DEPS:
        cmd.append(f"--nofollow-import-to={module}")

    # On Windows, use MSVC. Nuitka's MinGW path doesn't support Python 3.13+,
    # and MSVC produces better-integrated Windows binaries anyway.
    if sys.platform == "win32":
        cmd.append("--msvc=latest")

    for plugin in plugins:
        for module in PLUGIN_RUNTIME_DEPS.get(plugin, []):
            if importlib.util.find_spec(module) is not None:
                cmd.append(f"--include-module={module}")
            else:
                print(
                    f"WARNING: plugin '{plugin}' wants '{module}' but it is not "
                    f"installed; skipping force-include (plugin may be degraded).",
                    file=sys.stderr,
                )

    if args.with_gstreamer:
        # Handles PyGObject: copies typelibs and sets up the gi search path.
        cmd.append("--enable-plugin=gi")
        cmd.append("--include-module=gi")

    if args.onefile:
        cmd.append("--onefile")

    cmd.append(str(ENTRY_POINT))
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the indie-beets executable.")
    parser.add_argument(
        "--with-gstreamer",
        action="store_true",
        help="Enable the Nuitka gi plugin for GStreamer/PyGObject (Phase 2).",
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Produce a single-file executable instead of a folder.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "build"),
        help="Where Nuitka writes the build (default: ./build).",
    )
    args = parser.parse_args()

    plugins = read_bundled_plugins()
    cmd = build_command(args, plugins)

    print("Bundled plugins:", ", ".join(plugins) or "(none)")

    if sys.platform == "win32":
        vcvars = find_vcvars()
        if vcvars is None:
            print(
                "WARNING: could not locate vcvars64.bat; relying on Nuitka's own "
                "compiler detection (may fail or fall back to MinGW).",
                file=sys.stderr,
            )
            print("Running:", " ".join(cmd))
            return subprocess.call(cmd, cwd=str(REPO_ROOT))
        # Activate MSVC, then run Nuitka in the same cmd session.
        shell_cmd = f'"{vcvars}" && {subprocess.list2cmdline(cmd)}'
        print(f"Running (via {vcvars.name}):", subprocess.list2cmdline(cmd))
        return subprocess.call(shell_cmd, cwd=str(REPO_ROOT), shell=True)

    print("Running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(REPO_ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
