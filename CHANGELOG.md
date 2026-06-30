# Changelog

Manually-maintained notes for indie-beets releases.

**How this works:** add notable changes under **`## Unreleased`** during
development (plain bullet points). When a release is cut (the manual *Release*
workflow), the Unreleased entries become the release notes, together with an
auto-generated table of the bundled component versions (beets, ffmpeg,
GStreamer, …). After releasing, move the Unreleased entries under a heading for
the version that was just published, and leave a fresh empty `## Unreleased`.

Release versions are `<beets version>-<build>` (e.g. `2.10.0-1`); see the README.

## Unreleased

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
- Update to **beets 2.11.0** (unblocked by beets-filetote 1.3.5, which fixed its
  incompatibility with beets 2.11).
- Fix the **lastgenre** plugin: bundle its `pylast` dependency — it silently
  failed to load in earlier releases.
- Add the **vgmdb** metadata source plugin (`beets-vgmdb`, enabled as `VGMplug`)
  — fetches album/track metadata from VGMdb.

## 2.10.0-1

- Initial release tooling: standalone beets bundles for Windows, Linux (x86_64 +
  arm64) and macOS (universal2) with ffmpeg + fpcalc; GStreamer on Windows + Linux.
