"""Allows ``python -m gauntlet``, which is the entry point on Windows where
``make`` is usually absent. The console script and this path share ``cli.main``
so neither can drift from the other."""

from __future__ import annotations

from gauntlet.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
