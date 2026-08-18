"""End-to-end smoke test for a built bundle.

Goes beyond `beet version`: generates a short audio file with the *bundled*
ffmpeg, imports it, and runs ReplayGain with a chosen backend — exercising the
real plumbing (helper-binary discovery via runtime_env, and on the gstreamer
backend the whole gi -> GStreamer -> beets chain). Fails loudly if no gain is
computed.

Usage:
    python scripts/smoke.py --dist build/indie_beets.dist --backend gstreamer
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _exe(dist: Path, name: str) -> Path:
    p = dist / (name + (".exe" if sys.platform == "win32" else ""))
    if not p.exists():
        raise SystemExit(f"smoke: not found in bundle: {p}")
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", required=True)
    ap.add_argument(
        "--backend", default="ffmpeg", choices=["ffmpeg", "gstreamer", "metaflac"]
    )
    args = ap.parse_args()

    dist = Path(args.dist).resolve()
    beet = _exe(dist, "beet")
    ffmpeg = _exe(dist / "bin", "ffmpeg")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        music = work / "music"
        music.mkdir()
        # 15 s of pink noise = real, fingerprintable/analyzable content.
        # The metaflac backend only handles FLAC (SUPPORTED_FORMATS={"FLAC"}),
        # so give it a FLAC file; the other backends are format-agnostic.
        ext = "flac" if args.backend == "metaflac" else "mp3"
        subprocess.run(
            [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "anoisesrc=d=15:color=pink", "-metadata", "title=Smoke",
             "-metadata", "artist=indie-beets", str(music / f"smoke.{ext}")],
            check=True,
        )
        (work / "config.yaml").write_text(
            "directory: {d}/lib\n"
            "library: {d}/lib.db\n"
            "plugins: [replaygain]\n"
            "replaygain:\n  backend: {b}\n".format(
                d=work.as_posix(), b=args.backend
            ),
            encoding="utf-8",
        )
        env = {**os.environ, "BEETSDIR": str(work)}

        problems: list[str] = []

        def run(*cli: str) -> str:
            r = subprocess.run([str(beet), *cli], env=env, text=True,
                               capture_output=True)
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            # A plugin that fails to load still lets beets exit 0, and the
            # backend then silently does nothing — which used to look like a
            # pass. Treat it as the failure it is.
            if "error loading plugin" in (r.stdout + r.stderr):
                problems.append(f"a plugin failed to load during `beet {cli[0]}`")
            return r.stdout

        run("version")
        run("import", "-A", "-q", str(music))
        run("replaygain")
        out = run("list", "-f", "$rg_track_gain")

    gains = [tok for tok in out.split() if tok.replace("-", "").replace(".", "").isdigit()]
    if not gains:
        problems.append(f"no ReplayGain computed via the {args.backend} backend")
    elif float(gains[0]) == 0.0:
        # beets reports 0.0 for a track it never analysed, and 15 s of pink noise
        # never genuinely measures 0.0 (the other backends land around -2 dB).
        # Without this check a completely broken backend reads as a pass.
        problems.append(
            f"the {args.backend} backend reported rg_track_gain=0.0, which means "
            f"it did not analyse the file"
        )

    if problems:
        for p in problems:
            print(f"SMOKE FAILED: {p}", file=sys.stderr)
        return 1
    print(f"SMOKE OK: {args.backend} backend computed rg_track_gain={gains[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
