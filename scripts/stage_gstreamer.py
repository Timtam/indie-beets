"""Wire the GStreamer MSVC runtime into the build and the bundle (Windows).

GStreamer is the trickiest battery. On Windows the official MSVC *runtime*
package conveniently ships prebuilt PyGObject (gi) + pycairo for CPython 3.13,
so no source build is needed. This script automates the two jobs:

  prepare --venv DIR   Download + extract the GStreamer runtime, copy the gi/
                       cairo bindings into the build venv, and drop a .pth that
                       (at interpreter startup) registers the GStreamer bin as a
                       DLL directory and sets GI_TYPELIB_PATH / GST_PLUGIN_PATH /
                       PATH. After this, `python scripts/build.py --with-gstreamer`
                       can import gi so Nuitka's gi plugin bundles the typelibs.

  bundle --dist DIR    Copy the GStreamer bin (DLLs) and the plugins into
                       DIR/gstreamer/ so the frozen bundle is self-contained.
                       runtime_env.py points the app at them at startup.

Pinned to a single GStreamer version. Currently Windows-only (Linux/macOS use
their platform GStreamer and are handled separately).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE = REPO_ROOT / ".gststage"

GSTREAMER_VERSION = "1.26.11"
_BASE = f"https://gstreamer.freedesktop.org/data/pkg/windows/{GSTREAMER_VERSION}/msvc"
RUNTIME_MSI = f"gstreamer-1.0-msvc-x86_64-{GSTREAMER_VERSION}.msi"
RUNTIME_URL = f"{_BASE}/{RUNTIME_MSI}"

# Where the GStreamer tree lands inside an `msiexec /a` administrative install.
_REL_ROOT = Path("PFiles64") / "gstreamer" / "1.0" / "msvc_x86_64"


def _download(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"  cached: {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "indie-beets"})
    with urllib.request.urlopen(req) as resp, dest.open("wb") as out:  # noqa: S310
        shutil.copyfileobj(resp, out)


def gst_root() -> Path:
    """Download + extract the runtime MSI (cached) and return the GStreamer root."""
    if sys.platform != "win32":
        raise RuntimeError("stage_gstreamer currently supports Windows only")
    msi = CACHE / RUNTIME_MSI
    _download(RUNTIME_URL, msi)
    extract_dir = CACHE / "runtime"
    root = extract_dir / _REL_ROOT
    if not root.is_dir():
        print(f"  extracting {msi.name} (msiexec /a) ...")
        subprocess.run(
            ["msiexec", "/a", str(msi), "/qn", f"TARGETDIR={extract_dir}"],
            check=True,
        )
    if not root.is_dir():
        raise RuntimeError(f"expected GStreamer root not found: {root}")
    return root


def _linux_plugin_dir() -> Path:
    """Locate the distro GStreamer plugin directory (apt-installed)."""
    for cand in sorted(Path("/usr/lib").glob("*/gstreamer-1.0")):
        if cand.is_dir():
            return cand
    raise RuntimeError("GStreamer plugin dir not found under /usr/lib/*/gstreamer-1.0")


def prepare(venv: Path) -> None:
    if sys.platform.startswith("linux"):
        # gi + GStreamer come from distro packages; the build uses the system
        # python via `venv --system-site-packages`, so nothing to copy here.
        print("Linux: gi provided by system packages (apt python3-gi); prepare is a no-op.")
        return
    root = gst_root()
    site = venv / "Lib" / "site-packages"
    if not site.is_dir():
        raise RuntimeError(f"venv site-packages not found: {site}")

    # Copy the prebuilt cp313 gi + cairo bindings into the build venv.
    src_site = root / "lib" / "site-packages"
    for name in ("gi", "cairo"):
        dst = site / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src_site / name, dst)
    for extra in list(src_site.glob("*.pyd")) + list(src_site.glob("*.dist-info")):
        target = site / extra.name
        if extra.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(extra, target)
        else:
            shutil.copy2(extra, target)

    # A .pth whose code runs at every interpreter startup in this venv. It makes
    # `import gi` work for the build (Nuitka's gi plugin imports gi): registers
    # the DLL dir and points gi/GStreamer at the bundled typelibs + plugins.
    gbin = root / "bin"
    typelibs = root / "lib" / "girepository-1.0"
    plugins = root / "lib" / "gstreamer-1.0"
    line = (
        "import os; os.add_dll_directory(r'{bin}'); "
        "os.environ['GI_TYPELIB_PATH']=r'{tl}'; "
        "os.environ['GST_PLUGIN_PATH']=r'{pl}'; "
        "os.environ['PATH']=r'{bin}'+os.pathsep+os.environ.get('PATH','')"
    ).format(bin=gbin, tl=typelibs, pl=plugins)
    (site / "_indie_gst.pth").write_text(line + "\n", encoding="ascii")
    print(f"Prepared build venv: gi/cairo installed, _indie_gst.pth written.")
    print(f"  GStreamer root: {root}")


def _bundle_linux(dist: Path) -> None:
    """Copy the distro GStreamer plugins into the bundle (Linux).

    Only the plugins are staged; the core gst/glib shared libs they need are
    already bundled in the dist root by Nuitka (pulled in via gi + the typelibs),
    and runtime_env.py puts the bundle root on LD_LIBRARY_PATH so the dlopen'd
    plugins resolve against them.
    """
    plug_src = _linux_plugin_dir()
    plug_dst = dist / "gstreamer" / "lib" / "gstreamer-1.0"
    if plug_dst.exists():
        shutil.rmtree(plug_dst)
    plug_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(plug_src, plug_dst)
    n = len(list(plug_dst.glob("*.so")))
    print(f"Staged {n} GStreamer plugins from {plug_src} into {plug_dst}")


def bundle(dist: Path) -> None:
    if sys.platform.startswith("linux"):
        _bundle_linux(dist)
        return
    root = gst_root()
    dest = dist / "gstreamer"
    (dest / "lib").mkdir(parents=True, exist_ok=True)
    print(f"Staging GStreamer runtime into {dest}")
    # bin: the GLib/GStreamer DLLs the frozen _gi.pyd and typelibs link against.
    if (dest / "bin").exists():
        shutil.rmtree(dest / "bin")
    shutil.copytree(root / "bin", dest / "bin")
    # plugins: the actual codec/element .dll files (rganalysis, decoders, ...).
    plug_dst = dest / "lib" / "gstreamer-1.0"
    if plug_dst.exists():
        shutil.rmtree(plug_dst)
    shutil.copytree(root / "lib" / "gstreamer-1.0", plug_dst)
    n_dll = len(list((dest / "bin").glob("*.dll")))
    n_plug = len(list(plug_dst.glob("*.dll")))
    print(f"  staged {n_dll} DLLs + {n_plug} plugins")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage GStreamer for build/bundle.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="install gi into the build venv")
    p.add_argument("--venv", default=str(REPO_ROOT / ".venv"))
    b = sub.add_parser("bundle", help="copy GStreamer runtime into the bundle")
    b.add_argument("--dist", default=str(REPO_ROOT / "build" / "indie_beets.dist"))
    args = parser.parse_args()

    if args.cmd == "prepare":
        prepare(Path(args.venv))
    elif args.cmd == "bundle":
        bundle(Path(args.dist))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
