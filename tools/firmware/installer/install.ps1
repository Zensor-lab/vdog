# =============================================================================
# PLACEHOLDER — round-2 deliverable (master plan 0.9.6).
#
# This is NOT the qualified setup wrapper yet. The real install.ps1 will
# create/reuse an isolated local installer environment for a supported Python
# 3.12 on Windows, install requirements-installer.lock (esptool 5.4.0 +
# pyserial, hashed) and invoke install.py in that environment.
# Do not ship a release ZIP that claims end-user setup support from this file.
# =============================================================================
Write-Error "install.ps1: this prebuilt package ships a placeholder setup wrapper."
Write-Error "Round 2 (master plan 0.9.6) provides the qualified isolated-environment"
Write-Error "wrapper. Until then run install.py from a Python 3.12 environment that"
Write-Error "has the locked installer dependencies installed."
exit 2
