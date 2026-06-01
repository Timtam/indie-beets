# indie-beets

Standalone, **batteries-included** executable builds of the
[beets](https://beets.io) music library manager.

The goal: download an archive for your OS, unpack it, and run `beet` — no Python
install, no `pip`, no hunting down `ffmpeg`, `fpcalc` or GStreamer. Everything
the popular plugins need is bundled.

> Status: early development. See the build plan for the phased roadmap.

## What's inside

- **beets** (pinned) compiled to a standalone executable with [Nuitka](https://nuitka.net).
- **ffmpeg** — transcoding (`convert`) and ReplayGain analysis.
- **fpcalc / Chromaprint** — acoustic fingerprinting (`chroma`).
- **GStreamer** — audio decoding and the `gstreamer` ReplayGain backend.

## Building locally

Requires Python 3.10+ and a C compiler (Nuitka can fetch MinGW64 on Windows).

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Unix: source .venv/bin/activate
pip install -e .[build]
python scripts/build.py            # add --with-gstreamer for the full bundle
```

The result lands in `build/__main__.dist/` (a folder containing `beet` and all
its dependencies).

## Repository layout

| Path | Purpose |
|------|---------|
| `src/indie_beets/__main__.py` | Frozen entry point → beets' CLI |
| `src/indie_beets/runtime_env.py` | Points beets at the bundled binaries |
| `scripts/build.py` | Nuitka build driver |
| `scripts/stage_binaries.py` | Downloads/stages ffmpeg, fpcalc, GStreamer |
| `config/default_config.yaml` | Sensible bundled defaults |
| `.github/workflows/build.yml` | Multi-OS CI matrix |
