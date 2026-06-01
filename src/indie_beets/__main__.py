"""Frozen entry point for indie-beets.

This is the module Nuitka compiles into the executable. It prepares the
bundled runtime environment (helper binaries, GStreamer) and then hands off to
beets' normal CLI ``main()`` — so the resulting executable behaves exactly like
the ``beet`` command, just self-contained.
"""

from __future__ import annotations

import sys

from . import runtime_env


def main() -> None:
    runtime_env.setup()
    # Imported after setup() so any import-time probing sees the bundled env.
    from beets.ui import main as beets_main

    beets_main()


if __name__ == "__main__":
    sys.exit(main())
