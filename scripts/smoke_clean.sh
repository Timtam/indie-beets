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

# The metaflac backend only handles FLAC; the others are format-agnostic.
if [[ "$BACKEND" == "metaflac" ]]; then EXT=flac; else EXT=mp3; fi

"$BUNDLE/bin/ffmpeg" -hide_banner -loglevel error -f lavfi \
  -i "anoisesrc=d=15:color=pink" -metadata title=Smoke -metadata artist=indie-beets \
  "$work/music/s.$EXT"

export BEETSDIR="$work/bd"
mkdir -p "$BEETSDIR"
printf 'directory: %s/lib\nlibrary: %s/lib.db\nplugins: [replaygain]\nreplaygain:\n  backend: %s\n' \
  "$work" "$work" "$BACKEND" > "$BEETSDIR/config.yaml"

# Capture the output too: a plugin that fails to load still exits 0, and the
# backend then silently does nothing, which used to read as a pass.
log="$work/beets.log"
"$BUNDLE/beet" import -A -q "$work/music" 2>&1 | tee -a "$log"
"$BUNDLE/beet" replaygain 2>&1 | tee -a "$log"
gain="$("$BUNDLE/beet" list -f '$rg_track_gain' 2>>"$log")"

echo "computed rg_track_gain='$gain'"
if grep -q "error loading plugin" "$log"; then
  echo "CLEAN-ROOM SMOKE FAILED: a plugin failed to load" >&2
  exit 1
fi
if [[ ! "$gain" =~ [0-9] ]]; then
  echo "CLEAN-ROOM SMOKE FAILED: no ReplayGain computed via $BACKEND backend" >&2
  exit 1
fi
# 15 s of pink noise never genuinely measures 0.0 (real backends land near -2 dB);
# beets reports 0.0 for a track it never analysed.
if [[ "$gain" == "0.0" || "$gain" == "0" ]]; then
  echo "CLEAN-ROOM SMOKE FAILED: $BACKEND reported 0.0 — it did not analyse the file" >&2
  exit 1
fi
echo "CLEAN-ROOM SMOKE OK ($BACKEND backend): $gain"
