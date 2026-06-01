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
    ap.add_argument("--backend", default="ffmpeg", choices=["ffmpeg", "gstreamer"])
    args = ap.parse_args()

    dist = Path(args.dist).resolve()
    beet = _exe(dist, "beet")
    ffmpeg = _exe(dist / "bin", "ffmpeg")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        music = work / "music"
        music.mkdir()
        # 15 s of pink noise = real, fingerprintable/analyzable content.
        subprocess.run(
            [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "anoisesrc=d=15:color=pink", "-metadata", "title=Smoke",
             "-metadata", "artist=indie-beets", str(music / "smoke.mp3")],
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

        def run(*cli: str) -> str:
            r = subprocess.run([str(beet), *cli], env=env, text=True,
                               capture_output=True)
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            return r.stdout

        run("version")
        run("import", "-A", "-q", str(music))
        run("replaygain")
        out = run("list", "-f", "$rg_track_gain")

    gains = [tok for tok in out.split() if tok.replace("-", "").replace(".", "").isdigit()]
    if not gains:
        print(f"SMOKE FAILED: no ReplayGain computed via {args.backend} backend",
              file=sys.stderr)
        return 1
    print(f"SMOKE OK: {args.backend} backend computed rg_track_gain={gains[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
