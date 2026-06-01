"""Merge two single-arch Nuitka standalone trees into one universal2 tree.

macOS only. Nuitka builds for one architecture at a time, so to ship a single
bundle that runs on both Intel and Apple Silicon we build twice (arm64 natively,
x86_64 under Rosetta) and then fuse the results here:

- every Mach-O file (the executable + all .so/.dylib) is `lipo -create`d from its
  arm64 and x86_64 counterparts into a fat binary,
- everything else (compiled .pyc, data files, etc., which are arch-independent)
  is copied from the arm64 tree,
- symlinks are recreated.

Usage:
    python scripts/lipo_merge.py --arm64 build/arm64/indie_beets.dist \
        --x86_64 build/x86_64/indie_beets.dist --out build/indie_beets.dist
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Mach-O / universal magic numbers (first 4 bytes, either byte order).
_MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe",  # 64-bit LE
    b"\xfe\xed\xfa\xcf",  # 64-bit BE
    b"\xce\xfa\xed\xfe",  # 32-bit LE
    b"\xfe\xed\xfa\xce",  # 32-bit BE
    b"\xca\xfe\xba\xbe",  # fat/universal
    b"\xbe\xba\xfe\xca",  # fat/universal (swapped)
}


def is_macho(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    try:
        with path.open("rb") as fh:
            return fh.read(4) in _MACHO_MAGICS
    except OSError:
        return False


def lipo_create(a: Path, b: Path, out: Path) -> None:
    subprocess.run(["lipo", "-create", str(a), str(b), "-output", str(out)], check=True)
    shutil.copymode(a, out)


def merge(arm64: Path, x86_64: Path, out: Path) -> tuple[int, int, int]:
    merged = copied = missing = 0
    if out.exists():
        shutil.rmtree(out)

    for src in sorted(arm64.rglob("*")):
        rel = src.relative_to(arm64)
        dst = out / rel
        counterpart = x86_64 / rel

        if src.is_symlink():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(src.readlink())
            copied += 1
            continue
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        if is_macho(src):
            if is_macho(counterpart):
                lipo_create(src, counterpart, dst)
                merged += 1
            else:
                # No x86_64 counterpart — ship the arm64 slice and warn.
                print(f"WARNING: no x86_64 match for Mach-O {rel}; copying arm64 only",
                      file=sys.stderr)
                shutil.copy2(src, dst)
                missing += 1
        else:
            shutil.copy2(src, dst)
            copied += 1

    return merged, copied, missing


def main() -> int:
    parser = argparse.ArgumentParser(description="lipo-merge two Nuitka dist trees.")
    parser.add_argument("--arm64", required=True, help="arm64 .dist directory")
    parser.add_argument("--x86_64", required=True, help="x86_64 .dist directory")
    parser.add_argument("--out", required=True, help="output universal .dist directory")
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("ERROR: lipo_merge only runs on macOS", file=sys.stderr)
        return 1

    merged, copied, missing = merge(Path(args.arm64), Path(args.x86_64), Path(args.out))
    print(f"Merged {merged} Mach-O files, copied {copied} others, {missing} arm64-only.")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
