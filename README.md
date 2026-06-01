# indie-beets

**A standalone, batteries-included build of the [beets](https://beets.io) music
library manager.**

Download one archive for your operating system, unpack it, and run `beet`. No
Python installation, no `pip`, no manually hunting down `ffmpeg`, `fpcalc` or
other helpers — everything the bundled plugins need is already inside.

indie-beets is *just beets*: same commands, same configuration, same plugins.
It only changes how you get it onto your machine.

---

## How it works

beets is normally a Python package (`pip install beets`) that loads its plugins
dynamically at runtime and shells out to external tools for audio work. indie-beets
turns that into a self-contained program:

1. **Freeze.** [Nuitka](https://nuitka.net) compiles beets and its plugins into a
   native standalone folder — a real executable plus all its dependencies, no
   system Python required.
2. **Bundle the "batteries."** The external helper binaries (see below) are placed
   in a `bin/` folder next to the executable.
3. **Wire it up at startup.** A small launcher (`src/indie_beets/runtime_env.py`)
   prepends that `bin/` folder to `PATH` before beets starts, so the plugins find
   the bundled `ffmpeg`/`fpcalc` automatically — even though nothing is installed
   system-wide.
4. **Build everywhere.** A GitHub Actions matrix produces a build per operating
   system (builds can't be cross-compiled, so each OS builds on its own runner).

The result behaves exactly like the `beet` command you'd get from PyPI.

---

## Download & run

1. Grab the archive for your platform from the
   [Releases](../../releases) page.
2. Unpack it anywhere.
3. Run the `beet` executable inside (`beet.exe` on Windows).

A `config.example.yaml` is included in the archive showing the bundled defaults;
copy what you want into your own beets config. beets reads your personal config
from the usual location, so your settings survive upgrades.

> **Note on first launch:** the binaries are not code-signed yet, so macOS
> Gatekeeper and Windows SmartScreen may warn on first run. Signing/notarization
> is on the roadmap.

---

## Supported versions

> **Maintainers:** update this table whenever the pinned beets version is bumped.

| Component        | Version / target                              |
|------------------|-----------------------------------------------|
| **beets**        | **2.10.0** (the release number tracks this)   |
| Python (build)   | 3.12 in CI                                    |
| ffmpeg           | BtbN `n8.1` static build                      |
| fpcalc / Chromaprint | 1.6.0                                     |
| Platforms        | Windows x86_64 · Linux x86_64 · macOS x86_64 · macOS arm64 |

The indie-beets **release number is exactly the bundled beets version** (e.g.
`indie-beets-2.10.0`). It is taken straight from the frozen beets at packaging
time, so the number on the archive always matches the beets inside it.

### Why not beets 2.11.0 yet?

beets 2.11.0 is the latest upstream release, but it is **held back to 2.10.0 on
purpose**. beets 2.11.0 renamed/privatized the internal symbols
`MULTIDISC_MARKERS` and `MULTIDISC_PAT_FMT` in `beets.importer.tasks`, and the
current **beets-filetote** release (1.3.4) still imports them, so it fails to
load against 2.11.0. **2.10.0 is the newest beets version that all bundled
plugins — including the external ones — work with.** We will move to 2.11.x (and
beyond) as soon as beets-filetote ships a compatible release.

---

## Bundled plugins

All of these are enabled in the shipped `config.example.yaml` and ready to use.

### External / third-party plugins

These are the plugins that aren't part of beets itself and that you'd otherwise
have to install separately:

| Plugin | Package | What it does |
|--------|---------|--------------|
| **bandcamp** | [`beetcamp`](https://github.com/snejus/beetcamp) | Adds Bandcamp as an autotagger metadata source. |
| **filetote** | [`beets-filetote`](https://github.com/gtronset/beets-filetote) | Copies/moves non-music files (artwork, logs, cue sheets…) alongside your music on import. |

### Built-in beets plugins

Bundled and enabled by default: `chroma` (acoustic fingerprinting),
`convert` (transcoding), `replaygain` (loudness normalization), `fetchart`,
`lyrics`, `lastgenre`, `duplicates`, `info`, `missing`, `scrub`.

Any other built-in beets plugin can still be enabled in your config — these are
just the ones active out of the box. (Plugins needing extra native libraries
may require additional bundling work; open an issue if one you need is missing.)

### Helper binaries

| Tool | Used by | Purpose |
|------|---------|---------|
| `ffmpeg` / `ffprobe` | `convert`, `replaygain` | Transcoding and EBU R128 loudness analysis. |
| `fpcalc` (Chromaprint) | `chroma` | Acoustic fingerprinting for tag lookup. |

> GStreamer bundling (for the `gstreamer` ReplayGain backend and the `bpd`
> playback server) is planned but not yet included — ffmpeg covers transcoding
> and ReplayGain, and `fpcalc` decodes audio for fingerprinting on its own.

---

## Building from source

Requires Python 3.10+ and a C compiler (on Windows the build auto-activates MSVC
via Visual Studio's `vcvars64.bat`; Nuitka uses gcc/clang on Linux/macOS).

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Unix: source .venv/bin/activate
pip install -e ".[build]"

python scripts/build.py                                   # 1. freeze beets
python scripts/stage_binaries.py --dest build/indie_beets.dist/bin   # 2. add batteries
python scripts/package.py                                 # 3. make the archive
```

The standalone folder lands in `build/indie_beets.dist/`, and the distributable
archive in `dist/`.

## Repository layout

| Path | Purpose |
|------|---------|
| `src/indie_beets/__main__.py` | Frozen entry point → beets' CLI |
| `src/indie_beets/runtime_env.py` | Points beets at the bundled binaries at startup |
| `scripts/build.py` | Nuitka build driver |
| `scripts/stage_binaries.py` | Downloads/stages ffmpeg, fpcalc (pinned versions) |
| `scripts/package.py` | Builds the release archive (named after the beets version) |
| `config/default_config.yaml` | Sensible bundled defaults |
| `.github/workflows/build.yml` | Multi-OS CI matrix |

## Roadmap

- [x] Standalone beets build (Nuitka) with dynamic plugin loading
- [x] Bundled ffmpeg + fpcalc, wired up automatically at runtime
- [x] Multi-OS CI matrix and release archives
- [x] External plugins: beetcamp + beets-filetote
- [ ] GStreamer bundling (`gstreamer` ReplayGain backend, `bpd`)
- [ ] Code signing / notarization (macOS, Windows)
- [ ] Track beets 2.11.x once beets-filetote is compatible

---

## Licensing

indie-beets is a packaging project; each bundled component keeps its own license.
Notably, the bundled ffmpeg is a **GPL** static build, so the distributed
archives include GPL-licensed software. beets itself is MIT-licensed. Review the
individual components' licenses before redistributing.

## A note on how this was built

This project was created with substantial help from **AI** (Anthropic's Claude).
The architecture, build scripts, plugin integration, and this documentation were
developed in an AI-assisted workflow, with human direction and review of the
results.
