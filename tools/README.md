# vdog firmware release tooling (Stage 0.9)

Host-side Python 3.12 tools that turn a plain `pio run` build directory into
a validated, deterministic, self-contained installation ZIP for the vdog
XIAO ESP32S3 Sense prototype firmware, a stdlib-only installer CLI that end
users run against a real board, and the publish state machine that turns one
tested `main` build into an immutable tag plus a pre-release.

Specs: `docs/plans/0.9-firmware-ci-release.md` (sections 3–5), work packages
0.9.1–0.9.16; interface contracts in `docs/plans/0.9-round1-assignment.md` and
`docs/plans/0.9-round2-assignment.md`. The normative artifact rules live in
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
| `publish.py` | Immutable tag + pre-release state machine behind a small GitHub adapter protocol, with a `--dry-run` that performs no network calls |
| `installer/install.py` | Self-contained stdlib-only installer CLI shipped at the ZIP root (`check`/`ports`/`plan`/`inspect`/`install`) |
| `installer/install.sh`, `installer/install.ps1` | Setup wrappers: create/reuse the isolated `.venv-installer/`, install the locked dependencies with `--require-hashes`, then exec `install.py` inside it (master plan 0.9.6) |
| `installer/requirements-installer.{in,lock}` | Hashed end-user installer environment pins (`esptool==5.4.0`, pyserial) |
| `templates/THIRD_PARTY_NOTICES.md` | Third-party notices source shipped as `THIRD_PARTY_NOTICES.md` |
| `tests/` | pytest suite (367 tests), including the real-baseline build checks |

The release-notes source is `docs/release-notes-template.md` and the packaged
`INSTALL.md` comes from `docs/release-installation.md`; the CI workflows pass
both explicitly and `package.py: default_payload_sources` resolves the same two
paths for library callers (`--install-md`/`--release-notes-md` stay required on
the CLI). `dist/` (generated ZIPs), `installer/.venv-installer/` and Python
caches are gitignored.

## Host test environment (single documented command)

Run from the repository root; `uv` fetches the pinned CPython 3.12 and the
hashed dev dependencies from `requirements-dev.lock` (pytest, jsonschema,
PyYAML for the workflow invariants):

```sh
uv run --python 3.12 --with-requirements tools/firmware/requirements-dev.lock \
  pytest tools/firmware/tests
```

Qualified interpreter: **CPython 3.12.12** — the patch `uv python find 3.12`
resolves here (`cpython-3.12.12-macos-aarch64-none`), which is also the patch
recorded in the header of both lockfiles. The host `python3` is 3.14 and is not
a qualified interpreter for this suite; always go through `uv --python 3.12`.

The suite includes a real-baseline group that consumes (or produces, once) a
plain `pio run -d firmware -e vdog_xiao_sense_proto` build and cross-checks
the images with esptool's `image-info`. To skip it on hosts without the
pinned toolchain (the Stage 0.9 acceptance run must not skip):

```sh
VDOG_SKIP_REAL_BUILD=1 uv run --python 3.12 \
  --with-requirements tools/firmware/requirements-dev.lock \
  pytest tools/firmware/tests
```

Local tool availability, recorded honestly: `pio`, `uv`, `pytest`, `unzip`,
`shasum` and `git` are installed. `actionlint`/`yamllint` are not, so workflow
coverage is the structural parse and invariant assertions in
`tests/test_workflows.py`; `pwsh` is not, so `install.ps1` has structural
coverage only and was never executed; no GitHub credential or device is
available, so no workflow, tag or Release has been run from this checkout.

## End-user flow (what the ZIP provides)

```sh
unzip vdog-xiao-sense-<build-id>.zip && cd vdog-xiao-sense-<build-id>
sh ./install.sh check                        # offline validation, no port opened
sh ./install.sh ports                        # enumerate; never auto-selects
sh ./install.sh plan --board seeed-xiao-esp32s3-sense
sh ./install.sh inspect --port /dev/cu.usbmodem123
sh ./install.sh install --port /dev/cu.usbmodem123 \
  --board seeed-xiao-esp32s3-sense           # asks for consent before writing
```

The wrappers need `uv` and create `.venv-installer/` beside the script, then
install `requirements-installer.lock` into it with `--require-hashes` (first
setup needs network). They never touch a global Python, never use `sudo`, never
copy a virtual environment and never pipe a download into a shell. `install.py`
itself is stdlib-only; serial operations additionally require that locked
environment (or `--esptool-python` pointing at it). `VDOG_INSTALLER_UV`,
`VDOG_INSTALLER_VENV_DIR` and `VDOG_INSTALLER_PYTHON` override discovery.
The ZIP stores no executable bit, so invoke the wrapper through `sh` (or
`chmod +x` once).

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
  --install-md docs/release-installation.md \
  --release-notes-md docs/release-notes-template.md \
  --metadata firmware/.vdog-build-metadata.json   # path argument; never read from tools/
```

`--install-md` and `--release-notes-md` are required arguments (round-1
interface: an artifact's guide and notes are always an explicit, reviewable
choice); the two values above are what the CI workflows pass and what
`default_payload_sources` uses for library callers. The metadata file is
emitted by the firmware build itself (packet A) and is gitignored; packaging
hard-fails if it is missing or stale relative to the builder outputs — it may
only come from a plain `pio run` that exited 0. CI identities
(`--release-kind pr|main`) additionally require
`--base-sha`/`--pr-number`/`--run-id`/`--attempt` semantics per the plan;
local builds are always `build_id=local`, `tag=null`, `ci=null` (never
publishable). Validate any ZIP offline with:

```sh
python -m tools.firmware.validate_package tools/firmware/dist/<zip>.zip
```

## Publishing a main build (CI only)

```sh
python -m tools.firmware.publish \
  --zip tools/firmware/dist/vdog-xiao-sense-main-<sha12>.zip \
  --expected-sha <full-40-hex-main-sha> \
  --repo Zensor-lab/vdog --ref refs/heads/main --event-name push --dry-run
```

`publish.py` is the only component that talks to GitHub, and only through the
`GitHubAdapter` protocol; the workflow step just calls it. It refuses anything
but a `push` to `refs/heads/main` in the canonical repository, re-validates the
ZIP against its external digest, requires `manifest.json` to agree with the
requested SHA, then creates `firmware-main-<sha12>` at the full tested SHA,
peels the tag back and compares, creates a **draft** release with
`target_commitish` set to the full SHA, uploads the six assets derived from
that ZIP (ZIP, `.sha256`, `INSTALL.md`, `RELEASE_NOTES.md`,
`THIRD_PARTY_NOTICES.md`, `manifest.json`) and only then marks it published
with `prerelease=true`, `make_latest=false`. A rerun of an already-published
SHA reuses it; a conflicting tag or a published release whose manifest disagrees
is a hard failure. The adapter protocol exposes no tag update/delete/force and
no release delete, so overwriting is not reachable; partial drafts are repaired
by deleting the whole asset set and re-uploading. `--dry-run` uses a
`NoNetworkAdapter` that raises on any mutation, so the same code path proves the
plan without touching GitHub.

## Workflow files

`.github/workflows/firmware-pr.yml` and `firmware-main.yml` (master plan
0.9.9–0.9.14) carry the stable check names `firmware-build`,
`firmware-host-tests` and `firmware-package-tests`; only `firmware-main.yml`
has a `publish` job and it is the only job with `contents: write`. Both are
deliberately unfiltered by path, build the immutable event SHA, pin every
third-party action to a full commit SHA, and never persist checkout
credentials. `tests/test_workflows.py` asserts these invariants; the hosted run
is still the authoritative evidence.
