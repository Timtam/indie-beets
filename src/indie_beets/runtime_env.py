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
import shutil
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


#: Directory (inside the bundle) that holds the user's beets state when running
#: portably: config.yaml, library.db, state.pickle and beets' database backups.
#: Not named "beets" because the frozen bundle already ships a `beets/` package.
PORTABLE_DIR_NAME = "beets-data"


def _setup_portable_beetsdir(root: Path) -> None:
    """Keep beets' config and database inside the bundle instead of the OS.

    beets otherwise stores everything in the platform config directory
    (``%APPDATA%\\beets`` on Windows, ``~/.config/beets`` elsewhere), which
    defeats the point of a download-and-run bundle: the program is portable but
    its state is not. Pointing ``BEETSDIR`` at a folder inside the bundle moves
    the whole set — beets resolves the relative ``library``/``statefile``
    defaults against the config directory, so the database, the import state and
    the schema-migration ``.bak`` files follow along.

    This is beets' own supported override, so nothing is patched or guessed:
      * if the user already set ``BEETSDIR``, we leave it alone;
      * anything given an absolute path in config.yaml still wins.

    If the bundle is not writable (read-only media, installed under Program
    Files) we silently leave beets on its normal locations rather than failing.
    """
    if os.environ.get("BEETSDIR"):
        return  # the user chose a location; respect it

    beetsdir = root / PORTABLE_DIR_NAME
    try:
        beetsdir.mkdir(parents=True, exist_ok=True)
        # Confirm we can actually write here, not just that the path exists.
        probe = beetsdir / ".write-test"
        probe.touch()
        probe.unlink()
    except OSError:
        return  # read-only bundle: fall back to beets' standard directories

    os.environ["BEETSDIR"] = str(beetsdir)

    # Seed the shipped defaults on first run, so the bundled plugins are active
    # out of the box. Never overwrite: after this the file belongs to the user.
    config = beetsdir / "config.yaml"
    default = root / "default_config.yaml"
    if not config.exists() and default.is_file():
        try:
            shutil.copyfile(default, config)
        except OSError:
            pass  # a missing config just means beets uses its own defaults


def _preload_macos_gstreamer(gst_lib: Path) -> None:
    """macOS: preload the GLib/GStreamer core dylibs by absolute path.

    GObject-Introspection typelibs record their shared library by *bare* leaf
    name (e.g. ``libgstreamer-1.0.0.dylib``), and girepository loads it with a
    plain ``dlopen()``. On macOS a bare-name dlopen does NOT consult ``@rpath``
    and only searches ``DYLD_*_LIBRARY_PATH`` — which dyld caches at process
    launch, so the value we set above is too late to help. It would therefore
    miss our bundled copies and the ``import gi.repository.Gst`` would fail.

    But once a dylib is resident, a later dlopen by leaf name returns the loaded
    image. So we load the core libs from their absolute bundle path up front
    (each pulls in its siblings via the baked ``@loader_path`` rpath); the
    bare-name typelib loads then resolve to these. Plugin-specific gst libs
    (audio/base/...) are pulled in afterwards by ``Gst.init()``'s registry scan.
    """
    import ctypes

    for pattern in ("libg*-2.0*.dylib", "libgst*-1.0*.dylib"):
        for lib in sorted(gst_lib.glob(pattern)):
            try:
                ctypes.CDLL(str(lib))
            except OSError:
                # A lib that can't load standalone (unmet leaf dep) is fine —
                # what matters is that the typelib targets become resident.
                pass


def setup() -> None:
    """Point beets at the bundled helper binaries and libraries."""
    root = bundle_root()

    # Keep beets' own state (config, database, import state) inside the bundle.
    _setup_portable_beetsdir(root)

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
                # gi itself also insists on locating a DLL directory before it
                # will import, and it guesses one by walking three levels up
                # from the gi package — which assumes a Lib/site-packages/gi
                # layout. In the frozen bundle gi sits at the top level, so that
                # guess lands outside the bundle and gi raises "Could not deduce
                # DLL directories". PYGI_DLL_DIRS is its documented override.
                os.environ["PYGI_DLL_DIRS"] = str(gst_bin)
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
                # rpath isn't enough on macOS: girepository dlopens typelib
                # libraries by bare name, which ignores @rpath. Preload them.
                _preload_macos_gstreamer(gst_lib)
        elif sys.platform.startswith("linux"):
            _prepend_path("LD_LIBRARY_PATH", root)
            if gst_lib.is_dir():
                _prepend_path("LD_LIBRARY_PATH", gst_lib)
