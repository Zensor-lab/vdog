# vdog firmware release tooling (Stage 0.9, round 1)

Host-side Python 3.12 tools that turn a plain `pio run` build directory into
a validated, deterministic, self-contained installation ZIP for the vdog
XIAO ESP32S3 Sense prototype firmware, and a stdlib-only installer CLI that
end users run against a real board.

Specs: `docs/plans/0.9-firmware-ci-release.md` (sections 3–4), work packages
0.9.1–0.9.5 and the round-1 part of 0.9.8; interface contract in
`docs/plans/0.9-round1-assignment.md`. The normative artifact rules live in
`contract.py`; `contracts/firmware-release-v1.schema.json` is the
human-reviewable mirror (the test suite enforces they agree).

## Layout

| Path | Role |
| --- | --- |
| `contract.py` | Executable release/layout contract: manifest, flash layout, partition table (CSV + binary), ESP image container, path safety, frozen constants |
| `metadata.py` | Consumes `vdog-build-metadata-v1` (never produces it), derives source identity, VERSION.json, git clean/HEAD verification, build-dir metadata freshness gate |
| `export_flash_layout.py` | Normalizes builder outputs into `vdog-flash-layout-v1` |
| `package.py` | Deterministic safe ZIP assembly + `manifest.json` + `SHA256SUMS` + external `.sha256` |
| `validate_package.py` | Full offline archive validation, including running the ZIP's own `install.py check` in an isolated clean directory |
| `installer/install.py` | Self-contained stdlib-only installer CLI shipped at the ZIP root (`check`/`ports`/`plan`/`inspect`/`install`) |
| `installer/install.sh`, `installer/install.ps1` | Clearly-marked round-2 placeholders (master plan 0.9.6) |
| `installer/requirements-installer.{in,lock}` | Hashed end-user installer environment pins (`esptool==5.4.0`, pyserial) |
| `templates/` | Round-1 placeholder release notes / third-party notices sources |
| `tests/` | pytest suite (277 tests), including the real-baseline build checks |

`dist/` (generated ZIPs) and Python caches are gitignored.

## Host test environment (single documented command)

Run from the repository root; `uv` fetches the pinned CPython 3.12 and the
hashed dev dependencies from `requirements-dev.lock` (pytest, jsonschema):

```sh
uv run --python 3.12 --with-requirements tools/firmware/requirements-dev.lock \
  pytest tools/firmware/tests
```

The suite includes a real-baseline group that consumes (or produces, once) a
plain `pio run -d firmware -e vdog_xiao_sense_proto` build and cross-checks
the images with esptool's `image-info`. To skip it on hosts without the
pinned toolchain (the Stage 0.9 acceptance run must not skip):

```sh
VDOG_SKIP_REAL_BUILD=1 uv run --python 3.12 \
  --with-requirements tools/firmware/requirements-dev.lock \
  pytest tools/firmware/tests
```

## End-user flow (what the ZIP provides)

```sh
unzip vdog-xiao-sense-<build-id>.zip && cd vdog-xiao-sense-<build-id>
python install.py check                      # offline validation
python install.py ports                      # enumerate; never auto-selects
python install.py plan --board seeed-xiao-esp32s3-sense
python install.py inspect --port /dev/cu.usbmodem123
python install.py install --port /dev/cu.usbmodem123 \
  --board seeed-xiao-esp32s3-sense            # asks for consent before writing
```

`install.py` is stdlib-only; serial operations additionally require the
locked installer environment (`pip install -r
requirements-installer.lock`, hash-pinned `esptool==5.4.0` + pyserial;
network access on first setup). The qualified wrapper scripts arrive with
master plan 0.9.6; until then run `install.py` from a Python 3.12
environment that has the lock installed (or pass `--esptool-python`).

Safety guarantees (CI-T08): explicit `--port` always required; chip must be
esp32s3 and flash 8MB before any write; pinned esptool 5.4.0 verified and
never silently substituted; writes go only to the four manifest-approved
ranges (verified by read-back hashes); no erase/eFuse/security/NVS/SD
operations exist in the CLI; provisioned or unknown-layout boards are
refused, never assumed blank.

## Building a package (maintainer/CI)

```sh
uv run --python 3.12 --with-requirements tools/firmware/requirements-dev.lock \
  python -m tools.firmware.package \
  --install-md docs/installation.md \
  --release-notes-md tools/firmware/templates/RELEASE_NOTES.md \
  --metadata firmware/.vdog-build-metadata.json   # path argument; never read from tools/
```

The metadata file is emitted by the firmware build itself (Packet A) and is
gitignored; packaging hard-fails if it is missing or stale relative to the
builder outputs — it may only come from a plain `pio run` that exited 0.
CI identities (`--release-kind pr|main`) additionally require
`--base-sha`/`--pr-number`/`--run-id`/`--attempt` semantics per the plan;
local builds are always `build_id=local`, `tag=null`, `ci=null` (never
publishable). Validate any ZIP offline with:

```sh
python -m tools.firmware.validate_package tools/firmware/dist/<zip>.zip
```
