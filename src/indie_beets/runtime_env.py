"""Runtime environment setup for the frozen indie-beets bundle.

The whole point of indie-beets is that the downloaded bundle ships its own
``ffmpeg``, ``fpcalc`` and (later) GStreamer runtime, so the user never has to
install anything. beets discovers those helpers via ``PATH`` and GStreamer via
a handful of ``GST_*``/``GI_*`` environment variables. ``setup()`` wires those
up *before* beets starts, pointing at the binaries we shipped next to the
executable.

In a normal dev checkout (not frozen) this is a near no-op: if the staged
directories don't exist yet, we leave the ambient environment untouched so the
developer's system tools keep working.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running inside a Nuitka/PyInstaller standalone build."""
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def bundle_root() -> Path:
    """Directory that contains the executable and the staged ``bin/`` etc.

    Frozen: the folder of the executable. Dev checkout: the repo root, so the
    same layout (``bin/``, ``gstreamer/``) can be staged locally for testing.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # src/indie_beets/runtime_env.py -> repo root is two parents up from src/.
    return Path(__file__).resolve().parents[2]


def _prepend_path(var: str, value: Path) -> None:
    """Prepend ``value`` to a ``os.pathsep``-separated env var, de-duplicated."""
    entry = str(value)
    existing = os.environ.get(var, "")
    parts = [p for p in existing.split(os.pathsep) if p and p != entry]
    os.environ[var] = os.pathsep.join([entry, *parts])


def setup() -> None:
    """Point beets at the bundled helper binaries and libraries."""
    root = bundle_root()

    # ffmpeg, fpcalc, ... — beets finds these by searching PATH.
    bin_dir = root / "bin"
    if bin_dir.is_dir():
        _prepend_path("PATH", bin_dir)

    # GStreamer runtime (staged in Phase 2). Setting these is harmless when the
    # directories are absent, but we guard anyway to keep the env clean.
    gst_root = root / "gstreamer"
    if gst_root.is_dir():
        plugin_dir = gst_root / "lib" / "gstreamer-1.0"
        typelib_dir = gst_root / "lib" / "girepository-1.0"
        gst_lib = gst_root / "lib"
        gst_bin = gst_root / "bin"

        if plugin_dir.is_dir():
            # Use the system path var so we override, not append to, any host install.
            os.environ["GST_PLUGIN_SYSTEM_PATH"] = str(plugin_dir)
            os.environ["GST_PLUGIN_PATH"] = str(plugin_dir)
        if typelib_dir.is_dir():
            _prepend_path("GI_TYPELIB_PATH", typelib_dir)
        if gst_bin.is_dir():
            _prepend_path("PATH", gst_bin)
            # On Windows, PATH alone is NOT enough: since Python 3.8 the loader
            # ignores PATH when resolving an extension module's dependent DLLs.
            # _gi.pyd needs glib/gobject DLLs from the GStreamer bin, so register
            # it explicitly. (PATH is still needed too: typelib-referenced DLLs
            # are loaded by GModule, which does use PATH.)
            if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(gst_bin))
        # Shared libraries the plugins link against. On Linux the gst/glib core
        # libs live in the bundle root (Nuitka pulled them in via gi), and the
        # dlopen'd plugins must resolve against them, so put the root on the path.
        # NOTE: we deliberately do NOT rely on LD_LIBRARY_PATH/DYLD_LIBRARY_PATH
        # for the bundled gst/glib libs — glibc reads them only at process start,
        # so setting them here would be too late. Instead the libs carry baked-in
        # relocatable rpaths ($ORIGIN-relative), set at staging time. We still set
        # the vars as a harmless belt-and-suspenders for any tool that re-reads them.
        if sys.platform == "darwin":
            _prepend_path("DYLD_LIBRARY_PATH", root)
            if gst_lib.is_dir():
                _prepend_path("DYLD_LIBRARY_PATH", gst_lib)
        elif sys.platform.startswith("linux"):
            _prepend_path("LD_LIBRARY_PATH", root)
            if gst_lib.is_dir():
                _prepend_path("LD_LIBRARY_PATH", gst_lib)
