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

> **macOS:** the build is a **universal2** binary that runs natively on both
> Apple Silicon and Intel Macs. (It's produced by building each architecture
> separately — arm64 natively, x86_64 under Rosetta — and fusing them with `lipo`,
> since Nuitka itself builds one architecture at a time.)
>
> **Windows on ARM:** use the **`windows-x86_64`** build — Windows 11 on ARM runs
> it transparently via x64 emulation. There is no native arm64 Windows build yet:
> Nuitka can't produce a Windows-arm64 *standalone* bundle (it lacks the binary
> dependency analysis for that target). We'll add one if that changes upstream.

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
| Python (build)   | 3.13 on Windows, 3.12 on Linux/macOS          |
| ffmpeg           | `n8.1` static (Windows/Linux, BtbN) · `6.1.1` static (macOS, ffmpeg-static) |
| fpcalc / Chromaprint | 1.6.0                                     |
| GStreamer        | 1.26.11 MSVC (Windows) · distro packages (Linux x86_64 + arm64) · **not on macOS** (see below) |
| Platforms        | Windows x86_64 · Linux x86_64 · Linux arm64 · macOS universal2 (Intel + Apple Silicon) |

### Version numbers & releases

An indie-beets release is versioned as **`<beets version>-<build>`**, e.g.
`indie-beets-2.10.0-1`. The first part is the frozen beets version (so it always
matches the beets inside the bundle); the `-<build>` suffix is an indie-beets
revision that **starts at 1 and increments** for each re-release of the *same*
beets version, and **resets to 1** when the beets version is bumped
(`2.10.0-3` → `2.11.0-1`).

Releases are cut by manually running the **build** workflow (the *Run workflow*
button — no inputs). It builds all platforms, then a release job computes the
next version automatically from existing `v<beets>-*` git tags, attaches the
per-platform archives, and publishes a GitHub Release whose notes include the
`## Unreleased` entries from [`CHANGELOG.md`](CHANGELOG.md) plus an
auto-generated table of every bundled component version (beets, ffmpeg,
GStreamer, fpcalc, plugins, …). Local `python scripts/package.py` builds are
suffixed `-dev` since they aren't numbered releases.

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
| **GStreamer** (Windows, Linux) | `gstreamer` ReplayGain backend, `bpd` | Full GStreamer runtime + plugins + PyGObject. |

> **GStreamer is bundled on Windows and Linux only.** The everyday workflow
> doesn't need it — ffmpeg covers transcoding and ReplayGain, and `fpcalc`
> decodes audio for fingerprinting on its own — so it stays opt-in via your
> config (`replaygain.backend: gstreamer` or the `bpd` plugin).
>
> **Why not on macOS?** Nuitka's macOS dependency scanner aborts when it walks
> the GStreamer Python bindings' link to `libglib`
> ([Nuitka #3628](https://github.com/Nuitka/Nuitka/issues/3628), unresolved) —
> and it fails whether that dependency is referenced via `@rpath` or rewritten
> to an absolute path, so no packaging workaround gets past it (the upstream
> `--noinclude-dlls` / `--nofollow-import-to` flags don't help either). macOS
> therefore ships ffmpeg-only (which still covers transcoding + ReplayGain); the
> only feature lost is the `bpd` server. We'll revisit once the Nuitka bug is fixed.

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

### Selective CI builds

By default a push builds every platform. To iterate on one platform without
rebuilding the others, put the marker **`[ci-only`** in the commit message plus a
token for each platform you want: **`+linux-x64`**, **`+linux-arm64`**,
**`+windows`**, **`+macos`**. For example:

```
fix gstreamer staging [ci-only +linux-arm64]
```

(The `[ci-only` bracket keeps normal commit prose from triggering it, and the
tokens don't overlap as substrings.)

This only affects `push` runs — pull requests and the release (manual *Run
workflow*) always build all platforms.

## Repository layout

| Path | Purpose |
|------|---------|
| `src/indie_beets/__main__.py` | Frozen entry point → beets' CLI |
| `src/indie_beets/runtime_env.py` | Points beets at the bundled binaries at startup |
| `scripts/build.py` | Nuitka build driver |
| `scripts/stage_binaries.py` | Downloads/stages ffmpeg, fpcalc (pinned versions) |
| `scripts/stage_gstreamer.py` | Wires the GStreamer MSVC runtime into the build + bundle (Windows) |
| `scripts/lipo_merge.py` | Fuses the arm64 + x86_64 builds into a macOS universal2 tree |
| `scripts/package.py` | Builds a local release archive (`-dev`) |
| `scripts/next_version.py` | Computes the next `<beets>-<build>` release version from git tags |
| `scripts/changelog.py` | Renders the bundled-component manifest for release notes |
| `CHANGELOG.md` | Manually-maintained release notes (`## Unreleased`) |
| `config/default_config.yaml` | Sensible bundled defaults |
| `.github/workflows/build.yml` | Multi-OS CI matrix |

## Roadmap

- [x] Standalone beets build (Nuitka) with dynamic plugin loading
- [x] Bundled ffmpeg + fpcalc, wired up automatically at runtime
- [x] Multi-OS CI matrix and release archives
- [x] External plugins: beetcamp + beets-filetote
- [x] GStreamer bundling on Windows + Linux (`gstreamer` ReplayGain backend, `bpd`)
- [ ] GStreamer bundling on macOS — blocked by [Nuitka #3628](https://github.com/Nuitka/Nuitka/issues/3628)
- [ ] Native Windows arm64 build — blocked: Nuitka has no Windows-arm64 standalone
      support (x64 build runs on Windows-on-ARM via emulation meanwhile)
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
