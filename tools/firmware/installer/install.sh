#!/bin/sh
# =============================================================================
# PLACEHOLDER — round-2 deliverable (master plan 0.9.6).
#
# This is NOT the qualified setup wrapper yet. The real install.sh will
# create/reuse an isolated local installer environment for a supported Python
# 3.12, install requirements-installer.lock (esptool 5.4.0 + pyserial, hashed)
# and invoke install.py in that environment, on Windows/macOS/Linux.
# Do not ship a release ZIP that claims end-user setup support from this file.
# =============================================================================
echo "install.sh: this prebuilt package ships a placeholder setup wrapper." >&2
echo "Round 2 (master plan 0.9.6) provides the qualified isolated-environment" >&2
echo "wrapper. Until then run install.py from a Python 3.12 environment that" >&2
echo "has the locked installer dependencies installed." >&2
exit 2
