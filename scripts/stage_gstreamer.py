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

# The official universal GStreamer .pkg installs here (set up by the CI workflow).
_MACOS_FRAMEWORK = Path("/Library/Frameworks/GStreamer.framework/Versions/1.0")


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


# glibc / loader libs every Linux already provides — bundling these can break
# things, so we never copy them. Everything else (glib, gst, codecs) we DO bundle.
_LINUX_SYSTEM_LIBS = (
    "linux-vdso", "ld-linux", "libc.so", "libm.so", "libdl.so", "libpthread",
    "librt.so", "libresolv", "libutil", "libcrypt", "libnsl", "libgcc_s",
    "libstdc++",
)


def _ldd_deps(path: Path) -> set[str]:
    """Absolute paths of the shared libs `path` links against (via ldd)."""
    try:
        out = subprocess.run(["ldd", str(path)], capture_output=True, text=True).stdout
    except FileNotFoundError:
        raise RuntimeError("ldd not found — Linux staging needs binutils/libc-bin")
    deps: set[str] = set()
    for line in out.splitlines():
        # lines look like:  libfoo.so.1 => /usr/lib/.../libfoo.so.1 (0x...)
        if "=>" in line:
            rhs = line.split("=>", 1)[1].strip()
            p = rhs.split(" (")[0].strip()
            if p.startswith("/"):
                deps.add(p)
    return deps


def _bundle_linux(dist: Path) -> None:
    """Stage the distro GStreamer plugins AND their shared-library closure.

    Nuitka does NOT bundle glib/gst core libs (it treats them as system libs), so
    a build host's system GStreamer would silently satisfy them — but an end user
    without GStreamer installed would have a broken bundle. So we walk the ldd
    closure of the plugins (+ the gi extension) and copy every non-glibc .so into
    the bundle. runtime_env.py puts that dir on LD_LIBRARY_PATH at startup.
    """
    plug_src = _linux_plugin_dir()
    libdir = dist / "gstreamer" / "lib"
    plug_dst = libdir / "gstreamer-1.0"
    if plug_dst.exists():
        shutil.rmtree(plug_dst)
    plug_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(plug_src, plug_dst)
    n_plug = len(list(plug_dst.glob("*.so")))

    # Seed the closure with the plugins and the bundled gi extension(s).
    seeds = list(plug_dst.glob("*.so")) + list(dist.rglob("_gi*.so"))
    seen: set[str] = set()
    worklist = [Path(s) for s in seeds]
    to_copy: set[str] = set()
    while worklist:
        item = worklist.pop()
        for dep in _ldd_deps(item):
            if dep in seen:
                continue
            seen.add(dep)
            base = Path(dep).name
            if any(base.startswith(p) for p in _LINUX_SYSTEM_LIBS):
                continue
            # Skip libs Nuitka already placed in the bundle root (avoid dupes).
            if (dist / base).exists():
                continue
            to_copy.add(dep)
            worklist.append(Path(dep))  # recurse into this lib's own deps

    for dep in sorted(to_copy):
        # copy2 follows the symlink, writing the real content under the soname.
        shutil.copy2(dep, libdir / Path(dep).name)

    # Bake relocatable rpaths so the loader finds everything WITHOUT
    # LD_LIBRARY_PATH (which glibc only reads at process start). This is the
    # standard relocatable-bundle approach (cf. auditwheel/linuxdeploy):
    #   - staged libs find their siblings in the same dir        -> $ORIGIN
    #   - plugins (in gstreamer-1.0/) find the libs one dir up    -> $ORIGIN/..
    #   - the bundled gi extension finds the libs                 -> $ORIGIN/../gstreamer/lib
    for so in libdir.glob("*.so*"):
        _set_rpath(so, "$ORIGIN")
    for so in plug_dst.glob("*.so"):
        _set_rpath(so, "$ORIGIN/..")
    gi_dir = dist / "gi"
    if gi_dir.is_dir():
        for so in gi_dir.rglob("*.so"):
            _set_rpath(so, "$ORIGIN/../gstreamer/lib")

    print(f"Staged {n_plug} plugins + {len(to_copy)} shared libs into {libdir}")


def _set_rpath(sofile: Path, rpath: str) -> None:
    try:
        subprocess.run(
            ["patchelf", "--set-rpath", rpath, str(sofile)],
            check=True, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  patchelf skipped {sofile.name}: {e}")


def _otool_deps(path: Path) -> list[str]:
    """Dependency install-names of a Mach-O file (via `otool -L`).

    Skips the file's own id line and the `... (architecture x86_64):` headers
    that appear for fat binaries; returns the raw install-names (which for the
    GStreamer framework are all `@rpath/<basename>`, plus some `/usr/lib` ones).
    """
    out = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True).stdout
    deps: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        # Real dep lines start with the install-name path; headers don't.
        if not (line.startswith("@") or line.startswith("/")):
            continue
        dep = line.split(" (", 1)[0].strip()
        if dep and Path(dep).name != path.name:  # drop self-id
            deps.append(dep)
    return deps


def _resolve_mac_dep(dep: str, fwlib: Path) -> Path | None:
    """Map an otool install-name to a real file in the framework, or None to skip.

    OS-provided libs (/usr/lib, /System) are left to the system. Everything the
    framework provides is referenced as @rpath/<basename> (or, rarely, by an
    absolute framework path), which we resolve to <framework>/lib/<basename>.
    """
    if dep.startswith(("/usr/lib/", "/System/")):
        return None
    base = Path(dep).name
    if dep.startswith("@"):  # @rpath / @loader_path / @executable_path
        cand = fwlib / base
        return cand if cand.exists() else None
    p = Path(dep)
    if str(p).startswith(str(_MACOS_FRAMEWORK)) and p.exists():
        return p
    return None  # foreign absolute path (e.g. homebrew) — don't bundle


def _fix_mac(binary: Path, *rpaths: str) -> None:
    """Add relocatable @loader_path rpaths, then ad-hoc re-sign.

    install_name_tool invalidates a Mach-O's code signature, and arm64 refuses to
    load a dylib with a broken/absent signature, so every touched file must be
    re-signed (ad-hoc, `-s -`). -add_rpath errors if the rpath already exists;
    we tolerate that (idempotent re-runs). Signing happens once, after all rpaths.
    """
    for rpath in rpaths:
        subprocess.run(
            ["install_name_tool", "-add_rpath", rpath, str(binary)],
            capture_output=True, text=True,
        )
    subprocess.run(
        ["codesign", "--force", "--sign", "-", str(binary)],
        capture_output=True, text=True,
    )


def _bundle_macos(dist: Path) -> None:
    """Stage the GStreamer framework plugins + their dylib closure (macOS).

    Mirrors the Linux path: Nuitka bundles gi/_gi.so but treats glib/gst core
    libs as system (@rpath, unresolved), so we copy the plugins AND walk the otool
    closure of (plugins + gi) to bring every framework dylib into the bundle, then
    bake @loader_path rpaths so the loader resolves the @rpath/<basename> refs
    WITHOUT DYLD_LIBRARY_PATH (which dyld reads only at process start, and which
    SIP strips anyway). This is the macOS analogue of the $ORIGIN patchelf step.
    """
    fw = _MACOS_FRAMEWORK
    fwlib = fw / "lib"
    if not fwlib.is_dir():
        raise RuntimeError(f"GStreamer framework not found at {fw}")

    libdir = dist / "gstreamer" / "lib"
    plug_dst = libdir / "gstreamer-1.0"
    if plug_dst.exists():
        shutil.rmtree(plug_dst)
    plug_dst.mkdir(parents=True, exist_ok=True)

    # Plugins (dlopen'd at runtime; Nuitka never sees them). .dylib only, no .a.
    for p in (fwlib / "gstreamer-1.0").glob("*.dylib"):
        shutil.copy2(p, plug_dst / p.name)
    n_plug = len(list(plug_dst.glob("*.dylib")))

    # Typelibs: Nuitka's gi plugin bundles these too, but stage a copy where
    # runtime_env points GI_TYPELIB_PATH (belt-and-suspenders, harmless).
    tl_src = fwlib / "girepository-1.0"
    if tl_src.is_dir():
        tl_dst = libdir / "girepository-1.0"
        if tl_dst.exists():
            shutil.rmtree(tl_dst)
        shutil.copytree(tl_src, tl_dst)

    # Closure: seed with the plugins + the bundled gi extension(s).
    seeds = list(plug_dst.glob("*.dylib")) + list(dist.rglob("_gi*.so"))
    seen: set[str] = set()
    worklist = list(seeds)
    to_copy: dict[str, Path] = {}
    while worklist:
        item = worklist.pop()
        for dep in _otool_deps(item):
            if dep in seen:
                continue
            seen.add(dep)
            src = _resolve_mac_dep(dep, fwlib)
            if src is None:
                continue
            base = src.name
            # Skip libs Nuitka already placed in the bundle root (avoid dupes).
            if (dist / base).exists() or base in to_copy:
                continue
            to_copy[base] = src
            worklist.append(src)

    for base, src in sorted(to_copy.items()):
        shutil.copy2(src, libdir / base)

    # Bake @loader_path rpaths (the macOS $ORIGIN), then re-sign. Each binary gets
    # both the gstreamer/lib location (where we stage the closure) AND the bundle
    # root (where Nuitka stages libpython + image/codec libs), so a dep resolves
    # wherever it actually landed:
    #   - staged libs (gstreamer/lib/)        -> @loader_path , @loader_path/../..
    #   - plugins     (gstreamer/lib/gstreamer-1.0/) -> @loader_path/.. , @loader_path/../../..
    #   - bundled gi  (gi/)                    -> @loader_path/../gstreamer/lib , @loader_path/..
    for dy in libdir.glob("*.dylib"):
        _fix_mac(dy, "@loader_path", "@loader_path/../..")
    for dy in plug_dst.glob("*.dylib"):
        _fix_mac(dy, "@loader_path/..", "@loader_path/../../..")
    gi_dir = dist / "gi"
    if gi_dir.is_dir():
        for so in gi_dir.rglob("_gi*.so"):
            _fix_mac(so, "@loader_path/../gstreamer/lib", "@loader_path/..")

    print(f"Staged {n_plug} plugins + {len(to_copy)} dylibs into {libdir}")


def bundle(dist: Path) -> None:
    if sys.platform.startswith("linux"):
        _bundle_linux(dist)
        return
    if sys.platform == "darwin":
        _bundle_macos(dist)
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
