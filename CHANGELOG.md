# Changelog

Manually-maintained notes for indie-beets releases.

**How this works:** add notable changes under **`## Unreleased`** during
development (plain bullet points). When a release is cut (the manual *Release*
workflow), those entries become that release's notes, together with an
auto-generated table of the bundled component versions (beets, ffmpeg,
GStreamer, …). The release job then moves them under a heading for the version it
just published and leaves a fresh empty `## Unreleased`
(`scripts/rotate_changelog.py`), so each release lists only its own changes.

Release versions are `<beets version>-<build>` (e.g. `2.10.0-1`); see the README.

## Unreleased

- **Update to beets 2.13.1 and beets-filetote 1.3.7 — this fixes a broken plugin
  in the 2.13.0-x releases.** beets 2.13.0 changed two things filetote 1.3.6 relies
  on (`DefaultTemplateFunctions` lost its default arguments, and
  `MULTIDISC_PATTERNS` became `str` instead of `bytes`), so importing anything with
  filetote enabled crashed part-way through. The plugin still *loaded*, which is
  why our checks missed it — they only verified that plugins load, not that they
  work. filetote 1.3.7 is the fix, and the two versions now move together.
- Correct the plugin availability documentation. `metasync` was listed as
  impossible to bundle, but it needs no extra dependency at all — its iTunes
  source works everywhere and its Amarok source degrades gracefully without
  D-Bus, so it has in fact been usable all along. `absubmit` remains excluded,
  now for the real reason: AcousticBrainz stopped accepting submissions in 2022
  and beets refuses to run it against the public service. `autobpm` also remains
  excluded, and the deciding factor is not the macOS wheels but that Nuitka does
  not support numba in standalone builds at all.
- **Fix the `lyrics` plugin's language detection.** `langdetect` keeps its 55
  language profiles and `messages.properties` as package data, and Nuitka was not
  bundling them, so the plugin raised `FileNotFoundError` as soon as it inspected
  a lyric. Like the filetote break, it imported fine and only failed in use.
- Add a check that *exercises* the default plugins instead of only loading them
  (`scripts/verify_plugins.py`, run on every platform in CI): it imports a real
  track with an artifact file alongside it and fails on any traceback. Both bugs
  above were invisible to a load-only check — this is what found the langdetect one.
- Pin the bundled third-party plugins (`beetcamp`, `beets-filetote`, `beets-vgmdb`)
  and `httpx2` explicitly. Windows and Linux install from `pyproject.toml` while
  macOS installs the frozen closure, so anything left unpinned could ship at
  different versions on different platforms from the very same commit.

- **Fix the `gstreamer` ReplayGain backend on Windows.** It never actually ran in
  release builds: the bundled `gi` derives its DLL directory by assuming a
  `Lib/site-packages/gi` layout and walking three levels up, which lands outside
  the frozen bundle, so importing it failed with "Could not deduce DLL
  directories" and the plugin silently did not load. The bundle now sets
  `PYGI_DLL_DIRS`, gi's documented override, to its own GStreamer `bin`. This
  fixes the `bpd` plugin too, which loads gi the same way.
- **Stop the smoke tests from passing on a broken backend.** The failure above
  went unnoticed for several releases because beets still exited 0 and reported
  `rg_track_gain=0.0`, which the test accepted as a number. The smokes now fail
  if any plugin fails to load, or if the computed gain is 0.0 — which means the
  file was never analysed.

## 2.13.0-3

- **Every beets plugin is now usable from the bundle.** The optional
  dependencies behind all of beets' plugin extras are included, so any built-in
  plugin can be enabled by simply listing it in the config — `web`/`aura`,
  `beatport`, `tidal`, `mpdstats`, `sonosupdate`, `titlecase`, `thumbnails`,
  `bpd` (playback via the bundled GStreamer) and more. Importing straight from
  `.rar` archives works too (`.zip`/`.tar` already did).
  Three plugins could not be bundled: `autobpm` (numba/llvmlite publish no
  x86_64 macOS wheels and would break the universal2 build), `metasync`
  (`dbus-python` needs native dbus headers) and `absubmit` (needs an external
  extractor binary upstream no longer ships). `.7z` import is also left out:
  beets calls an API (`archive.infolist()`) that no py7zr release provides, so
  it would crash rather than work.
- Enable the **deezer** and **spotify** metadata sources by default, and bundle
  **discogs** as well. `discogs` ships but stays off: it authenticates as soon as
  it loads, so without a token it would start an interactive OAuth login on every
  beets command — add a `user_token` to your config and enable it there. The same
  applies to `tidal`. All of them store their tokens inside the bundle's
  `beets-data/`, like the rest of beets' state.

## 2.13.0-2

- **The bundle is now portable.** beets used to keep its configuration, database
  and database backups in the OS config directory (`%APPDATA%\beets` on Windows,
  `~/.config/beets` elsewhere), so the program was portable but its state was
  not. It now keeps all of that in a `beets-data/` folder inside the bundle, so
  moving or deleting the bundle takes everything with it. Set `BEETSDIR` to
  override, or give absolute paths in the config; on read-only media it falls
  back to beets' normal locations. Every CI build verifies that starting the
  bundle leaves the OS config directory untouched.
- **The shipped defaults are actually used now.** They were only copied in as a
  `config.example.yaml` for the user to merge by hand, which meant the bundled
  plugins were *not* enabled out of the box. They are now seeded into
  `beets-data/config.yaml` on first run (and never overwritten afterwards), so a
  fresh bundle starts with all 13 bundled plugins active.
- Release notes now cover only the release they belong to. The `## Unreleased`
  section was never emptied after a release, so every release repeated all
  earlier entries; the release job now rotates it automatically.

## 2.13.0-1

- Update to **beets 2.13.0** (all 13 bundled plugins verified). No plugin updates
  were needed — beets-filetote 1.3.6, beets-vgmdb 1.3.5 and beetcamp 0.24.3 all
  work unchanged on 2.13.
- Bundle **metaflac 1.5.0** on every platform, so beets 2.13's new `metaflac`
  ReplayGain backend works out of the box (`replaygain.backend: metaflac`). It is
  Xiph's reference FLAC tagger and writes native FLAC ReplayGain tags, but only
  processes FLAC files — `ffmpeg` remains the default backend. It is compiled from
  the FLAC release tarball on every platform as a single static binary with no
  companion libraries (on macOS each architecture is built separately and
  lipo-merged into universal2). The build verifies that the result links against
  nothing outside the OS and runs on its own, so a stray package-manager
  dependency can't slip into a release unnoticed.

## 2.12.0-1

- Update to **beets 2.12.0** and **beets-filetote 1.3.6** (all 13 bundled plugins
  verified loading on 2.12). Also picks up **pylast 7.1.0** (the lastgenre
  dependency), which moves to a new `httpx2`-based HTTP stack — pinned to the
  evaluated version. beets-vgmdb (1.3.5) and beetcamp (0.24.3) unchanged.
- **GStreamer is now bundled on macOS too** (universal2), so the `gstreamer`
  ReplayGain backend and the `bpd` server work on every platform. Unblocked by
  upgrading to Nuitka 4.1.3, which fixed the macOS dependency-scan bug
  ([#3628](https://github.com/Nuitka/Nuitka/issues/3628)). Self-containment is
  verified in CI by running the gstreamer smoke with the system framework hidden.
- Upgrade the build to **Nuitka 4.1.3** (from 2.8); the Windows runner is back on
  `windows-latest` (Nuitka 4.1.3 supports Visual Studio 2026).

## 2.11.0-1

- Update to **beets 2.11.0** (unblocked by beets-filetote 1.3.5, which fixed its
  incompatibility with beets 2.11).
- Fix the **lastgenre** plugin: bundle its `pylast` dependency — it silently
  failed to load in earlier releases.

## 2.10.0-2

- Add the **vgmdb** metadata source plugin (`beets-vgmdb`, enabled as `VGMplug`)
  — fetches album/track metadata from VGMdb.

## 2.10.0-1

- Initial release tooling: standalone beets bundles for Windows, Linux (x86_64 +
  arm64) and macOS (universal2) with ffmpeg + fpcalc; GStreamer on Windows + Linux.
