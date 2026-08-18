"""Exercise the default plugins, rather than only checking that they load.

A plugin can import cleanly and still be broken: beets-filetote 1.3.6 loaded fine
against beets 2.13.0 but raised part-way through every import, and because our
checks only asked "does it load?", three releases shipped with it broken.

So this runs a real import through the shipped defaults, with an artifact file
present, and fails on any traceback. It is deliberately end-to-end: the frozen
executable, its own seeded config, a real audio file, real files on disk.

Usage:
    python scripts/verify_plugins.py --dist build/indie_beets.dist
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: Plugins whose default config we exercise. Anything needing credentials or a
#: network service is out of scope — this is about catching API breakage.
EXERCISED = "chroma convert replaygain fetchart lyrics lastgenre duplicates info missing scrub filetote"

#: Substrings that mean beets hit an internal error. beets prints these and then
#: carries on with exit status 0, so the exit code alone proves nothing.
ERROR_MARKERS = (
    "Traceback (most recent call last)",
    "error loading plugin",
    "** error",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", required=True)
    args = ap.parse_args()

    dist = Path(args.dist).resolve()
    exe = ".exe" if sys.platform == "win32" else ""
    beet = dist / f"beet{exe}"
    ffmpeg = dist / "bin" / f"ffmpeg{exe}"
    for p in (beet, ffmpeg):
        if not p.exists():
            raise SystemExit(f"verify_plugins: not found: {p}")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        music = work / "music"
        music.mkdir()
        subprocess.run(
            [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "anoisesrc=d=5:color=pink", "-metadata", "title=Verify",
             "-metadata", "artist=indie-beets", str(music / "track.mp3")],
            check=True,
        )
        # The artifact is the point: filetote only does real work when a
        # non-music file travels along with the album.
        (music / "cover.jpg").write_text("not really a jpeg", encoding="utf-8")

        (work / "config.yaml").write_text(
            f"directory: {work.as_posix()}/lib\n"
            f"library: {work.as_posix()}/lib.db\n"
            f"plugins: [{EXERCISED.replace(' ', ', ')}]\n"
            "replaygain:\n  backend: ffmpeg\n"
            "filetote:\n  extensions: .jpg\n",
            encoding="utf-8",
        )
        env = {**os.environ, "BEETSDIR": str(work)}

        output = []
        for cli in (("version",), ("import", "-A", "-q", str(music)), ("list", "-f", "$title")):
            r = subprocess.run([str(beet), *cli], env=env, text=True, capture_output=True)
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            output.append(r.stdout + r.stderr)
        joined = "\n".join(output)

        problems = [m for m in ERROR_MARKERS if m in joined]
        if "Verify" not in output[-1]:
            problems.append("the track was not imported into the library")
        # filetote must have carried the artifact across.
        if not list((work / "lib").rglob("*.jpg")):
            problems.append("filetote did not copy the artifact alongside the music")

        # Copy nothing out of the temp dir; it disappears with the context.
        shutil.rmtree(work / "lib", ignore_errors=True)

    if problems:
        for p in problems:
            print(f"PLUGIN CHECK FAILED: {p}", file=sys.stderr)
        return 1
    print("PLUGINS OK: default set imported a track and carried its artifact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
