#!/usr/bin/env bash
# Clean-room smoke test: run the FROZEN bundle in an environment that has NO
# system GStreamer/Python (e.g. a bare ubuntu container), to prove the bundle is
# truly self-contained — an on-host smoke can be silently satisfied by the
# build machine's installed GStreamer.
#
# Usage: bash smoke_clean.sh /path/to/indie_beets.dist [backend]
set -euo pipefail

BUNDLE="${1:?usage: smoke_clean.sh <bundle-dir> [backend]}"
BACKEND="${2:-gstreamer}"

work="$(mktemp -d)"
mkdir -p "$work/music"

"$BUNDLE/bin/ffmpeg" -hide_banner -loglevel error -f lavfi \
  -i "anoisesrc=d=15:color=pink" -metadata title=Smoke -metadata artist=indie-beets \
  "$work/music/s.mp3"

export BEETSDIR="$work/bd"
mkdir -p "$BEETSDIR"
printf 'directory: %s/lib\nlibrary: %s/lib.db\nplugins: [replaygain]\nreplaygain:\n  backend: %s\n' \
  "$work" "$work" "$BACKEND" > "$BEETSDIR/config.yaml"

"$BUNDLE/beet" import -A -q "$work/music"
"$BUNDLE/beet" replaygain
gain="$("$BUNDLE/beet" list -f '$rg_track_gain')"

echo "computed rg_track_gain='$gain'"
if [[ "$gain" =~ [0-9] ]]; then
  echo "CLEAN-ROOM SMOKE OK ($BACKEND backend): $gain"
else
  echo "CLEAN-ROOM SMOKE FAILED: no ReplayGain computed via $BACKEND backend" >&2
  exit 1
fi
