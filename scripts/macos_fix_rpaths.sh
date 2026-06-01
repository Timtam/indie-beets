#!/usr/bin/env bash
# Rewrite @rpath/<name> dependency references to absolute paths under a given
# GStreamer framework lib dir. Nuitka's macOS dependency scanner FATALs when it
# can't resolve an @rpath/... dependency (Nuitka#3628); making the references
# absolute lets it resolve, follow, and bundle them (Nuitka then relocates the
# copies it bundles itself).
#
# Usage: macos_fix_rpaths.sh <framework-lib-dir> <file-or-glob> ...
set -uo pipefail

FWLIB="${1:?usage: macos_fix_rpaths.sh <fwlib> <files...>}"
shift

for f in "$@"; do
  [ -f "$f" ] || continue
  otool -L "$f" 2>/dev/null | awk 'NR>1 {print $1}' | grep '^@rpath/' | while read -r dep; do
    name="${dep#@rpath/}"
    if [ -f "$FWLIB/$name" ]; then
      install_name_tool -change "$dep" "$FWLIB/$name" "$f" 2>/dev/null || true
    fi
  done
done
