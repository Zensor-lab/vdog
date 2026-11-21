"""Host-side firmware release tooling (stage 0.9).

Modules:
    contract              Executable release/layout contracts.
    metadata              Build identity, VERSION.json, git verification.
    export_flash_layout   Builder-output normalization (vdog-flash-layout-v1).
    package               Deterministic safe installation ZIP assembly.
    validate_package      Offline full archive validation.
    check_lockfiles       CI lockfile drift checks (component + installer locks).
    installer/install.py  End-user installer CLI (stdlib-only, shipped in ZIP).
"""
