"""Exercise the default plugins, rather than only checking that they load.

A plugin can import cleanly and still be broken: beets-filetote 1.3.6 loaded fine
against beets 2.13.0 but raised part-way through every import, and because our
checks only asked "does it load?", three releases shipped with it broken.

So this runs a real import through the shipped defaults, with an artifact file
present, and fails on any traceback. It is deliberately end-to-end: the frozen
executable, its own seeded config, a real audio file, real files on disk.

A quiet `import -q` never reaches the interactive prompt, and that is where
beets 2.14 broke twice without any load check noticing: beets 2.14.0 threw away
the result of its own "enter Id" choice (beets#7000), and VGMplug's prompt
choices crashed the whole import. So it also answers the prompt like a user
would, with a stand-in plugin that serves those lookups offline.

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

#: Serves the import prompt's manual lookups offline. It is loaded from
#: `pluginpath` as a plain .py file, next to the real, compiled VGMplug.
PROBE_PLUGIN = '''\
from beets.autotag.hooks import AlbumInfo, TrackInfo
from beets.metadata_plugins import MetadataSourcePlugin
from beetsplug import VGMplug


def _album(name, album_id, source):
    track = TrackInfo(title="Verify", artist="indie-beets", index=1, length=5.0,
                      track_id=f"{album_id}-1", data_source=source)
    return AlbumInfo(tracks=[track], album=name, artist="indie-beets",
                     album_id=album_id, data_source=source)


# VGMplug's own prompt choices ask vgmdb.info; answer them here instead.
VGMplug.VGMdbPlugin.album_for_id = lambda self, album_id: (
    _album("Probe vgmdb-id", "vgm-1", "VGMdb") if album_id == "vgm-1" else None
)
VGMplug.VGMdbPlugin._search_vgmdbinfo = lambda self, query: [
    _album("Probe vgmdb-query", "vgm-2", "VGMdb")
]


class Probe(MetadataSourcePlugin):
    """The metadata source behind beets' own "enter Id" choice."""

    def album_for_id(self, album_id):
        return _album("Probe enter-id", "probe-1", "Probe") if album_id == "probe-1" else None

    def track_for_id(self, track_id):
        return None

    def candidates(self, items, artist, album, va_likely):
        return []

    def item_candidates(self, item, artist, title):
        return []
'''

#: What a user types at the import prompt, and the album that must come of it.
PROMPT_RUNS = (
    ("i\nprobe-1\na\n", "Probe enter-id"),         # beets: enter Id
    ("v\nvgm-1\na\n", "Probe vgmdb-id"),           # VGMplug: type Vgmdb id
    ("q\nsome query\na\n", "Probe vgmdb-query"),   # VGMplug: type vgmdb Query
)


def check_import_prompt(beet: Path, work: Path, track: Path) -> list[str]:
    """Import through the interactive prompt's manual lookups."""
    home = work / "prompt"
    (home / "plugins").mkdir(parents=True)
    (home / "plugins" / "indie_probe.py").write_text(PROBE_PLUGIN, encoding="utf-8")
    (home / "config.yaml").write_text(
        f"directory: {home.as_posix()}/lib\n"
        f"library: {home.as_posix()}/lib.db\n"
        f"pluginpath: [{(home / 'plugins').as_posix()}]\n"
        "plugins: [VGMplug, indie_probe]\n"
        "ui:\n  color: no\n",
        encoding="utf-8",
    )
    env = {**os.environ, "BEETSDIR": str(home)}

    def beet_run(*cli: str, answers: str | None = None) -> str:
        r = subprocess.run([str(beet), *cli], input=answers, env=env, text=True,
                           errors="replace", capture_output=True, timeout=300)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        return r.stdout + r.stderr

    output = []
    for answers, album in PROMPT_RUNS:
        src = home / "in" / album
        src.mkdir(parents=True)
        shutil.copy(track, src)
        output.append(beet_run("import", str(src), answers=answers))
    listing = beet_run("list", "-a", "-f", "$album")

    problems = [f"import prompt: {m}" for m in ERROR_MARKERS if m in "\n".join(output)]
    for answers, album in PROMPT_RUNS:
        if album not in listing:
            problems.append(f"import prompt: answering {answers!r} did not import {album!r}")
    return problems


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

        problems += check_import_prompt(beet, work, music / "track.mp3")

        # Copy nothing out of the temp dir; it disappears with the context.
        shutil.rmtree(work / "lib", ignore_errors=True)

    if problems:
        for p in problems:
            print(f"PLUGIN CHECK FAILED: {p}", file=sys.stderr)
        return 1
    print("PLUGINS OK: default set imported a track and carried its artifact; "
          "the import prompt's manual lookups work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
