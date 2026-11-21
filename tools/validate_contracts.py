#!/usr/bin/env python3
"""Offline validation of the frozen vdog media and API contracts (package 0.6).

Thin shim onto :func:`tools.contracts.cli.main`, so the documented command can be
run as a script path from the repository root::

    uv run --python 3.12 --with-requirements tools/contracts/requirements-dev.lock \\
      python tools/validate_contracts.py

Exit status: 0 when every check passes, 1 when a contract or fixture check fails,
2 on a usage or internal error. No network, no device, no clock or environment read.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # allow direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.contracts.cli import main

if __name__ == "__main__":
    sys.exit(main())
