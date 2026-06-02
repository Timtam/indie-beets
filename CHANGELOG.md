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

- Add the **vgmdb** metadata source plugin (`beets-vgmdb`, enabled as `VGMplug`)
  — fetches album/track metadata from VGMdb.

## 2.10.0-1

- Initial release tooling: standalone beets bundles for Windows, Linux (x86_64 +
  arm64) and macOS (universal2) with ffmpeg + fpcalc; GStreamer on Windows + Linux.
