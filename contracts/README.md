# vdog contracts (Stage 0.6)

The published wire contract for the recorder, the backend and the original
recording format: two OpenAPI 3.1 documents, three JSON Schema 2020-12 documents,
and 439 committed golden fixtures that say exactly what every accepted and refused
request and response looks like on the wire. Everything here is machine-checked
offline by `tools/validate_contracts.py`; nothing in this tree is prose-only.

Normative requirements stay in [`docs/specs/media-format.md`](../docs/specs/media-format.md)
and [`docs/specs/interfaces.md`](../docs/specs/interfaces.md). This directory is
those requirements expressed in a form a compiler, a test suite and a CI job can
consume. Where the two ever disagree, the specification wins and the contract
documents are corrected — and the validator is expected to fail loudly in between.

## Running the checks

The suite is 230 test functions; `tools/contracts/tests/test_corpus.py` fails if this
number and the corpus counts quoted below ever drift apart from the tree.

From the repository root, on the qualified interpreter (`uv` fetches CPython 3.12
and the hashed dependencies from `tools/contracts/requirements-dev.lock`):

```sh
uv run --python 3.12 --with-requirements tools/contracts/requirements-dev.lock \
  python tools/validate_contracts.py            # the corpus gate: exit 0 or 1
uv run --python 3.12 --with-requirements tools/contracts/requirements-dev.lock \
  pytest tools/contracts/tests                  # the suite that guards the gate
```

`tools/validate_contracts.py` takes no arguments, reads no environment variables,
opens no sockets and prints a deterministic report (banner, toolchain versions, one
line per fixture in sorted order, category counts, then every finding). Exit status
is `0` when every check passed, `1` when a contract or fixture check failed, and
`2` when the validator itself could not run. The system `python3` here is 3.14 and
is not a qualified interpreter for these commands.

Regenerate the committed fixtures after changing the schema set, the bounds or the
corpus definition — the committed bytes are always generator output:

```sh
uv run --python 3.12 --with-requirements tools/contracts/requirements-dev.lock \
  python -m tools.contracts.generate_fixtures   # writes contracts/fixtures
```

## Layout

| Path | Role |
| --- | --- |
| `device-v1.yaml` | OpenAPI 3.1 for the 18 operations the recorder serves (pairing, capabilities, status, settings, time, preview, clips, manifest, leases, clip files, OTA, events) |
| `backend-v1.yaml` | OpenAPI 3.1 for the 25 operations the backend serves (tokens, devices, clips, originals, chunked uploads, events, jobs, derivatives, health) |
| `media-v1/manifest.schema.json` | `manifest.json` of a finalized segment: identity, profile, clock, duration, count, close reason and the per-file hashes |
| `media-v1/frame-record.schema.json` | one `frames.jsonl` line: `v`, `seq`, `offset`, `size`, `t_us`, `crc32` and nothing else |
| `media-v1/active-record.schema.json` | `active.json` of an interrupted segment: the same identity without any completion claim |
| `fixtures/fixtures.json` | the fixture index: kind, contract, operation, direction, status, schema, expected outcome and expected diagnostic codes for all 439 vectors |
| `fixtures/media/valid/` | 18 finalized and in-progress segments a healthy recorder writes, including the clock, gap, boundary, notation and recovery shapes |
| `fixtures/media/invalid/` | 72 single-defect segments: every documented corruption class, one defect each |
| `fixtures/device/`, `fixtures/backend/` | 349 request/response vectors: every operation, every documented success status, every documented error status, and the malformed variants |
| `firmware-release-v1.schema.json` | **not part of this package** — the Stage 0.9 release-archive manifest, mirrored by `tools/firmware/contract.py` |

A media fixture is a directory of the real files (`video.mjpg`, `frames.jsonl`,
`manifest.json`, plus `checksums.json` where the vector is about hashes; `.part`
names while a segment is still interrupted). An API fixture is the pure wire body,
and header-only vectors carry a `.headers.json` sidecar; a response that claims to
answer a particular request carries that request beside it as a
`.request.headers.json` sidecar — the pair is judged together, so a `206` cannot
grant bytes for a specifier its own request never validly asked for — and the one
operation whose body is `application/octet-stream` (an upload `PATCH` chunk) ships
its body as a raw `.chunk` file rather than JSON. `checksums.json` is a
harness artifact beside a valid clip, never something the recorder writes.

## What the validator proves

1. **The documents are well-formed and structurally faithful.** Both OpenAPI files
   parse, declare every route `interfaces.md` assigns, name every operation in the
   executable operation table (`tools/contracts/api_model.py`, 43 operations),
   document only the status codes the specs assign to that operation, and carry
   bearer security where the specs require it — including the bearer challenge RFC
   9110 §15.5.2 demands of a 401, which both documents declare as a header component
   and the operation table requires on every documented 401. Each media schema
   validates against the Draft 2020-12 metaschema.
2. **Nothing drifts between the two notations.** The `Manifest` component of both
   OpenAPI documents is a byte-for-byte mirror of `media-v1/manifest.schema.json`;
   both documents share one error-envelope definition; the header components match
   the normative header rules. Any disagreement is `SPEC_COMPONENT_DRIFT`.
3. **Every valid vector is accepted.** Schema validation plus the explicit bounds
   and cross-field rules (CRC-32 recomputed over the exact payload slice, JPEG
   markers decoded with a real decoder and the marker chain walked to the first
   image's EOI, offsets walked, timestamps checked, hashes
   recomputed from bytes, a granted `Content-Range` compared with the `Range` its
   sidecar commits, an `Upload-Offset` that may not pass the `Upload-Length` beside
   it, and a derivative `crop` measured against the source clip's own manifest under
   the `(device_id, clip_id)` pair the record cites).
4. **Every invalid vector is refused, by name and only by the expected name.** A
   negative vector that passes, or that fails with a code nobody declared, is itself
   a finding — a detector that quietly stopped detecting cannot pass this gate.
5. **The corpus is complete and reproducible.** Every documented operation and
   status has a vector, no committed file is unreferenced, and re-running the
   generator reproduces every committed byte (`GENERATOR_DRIFT` otherwise).
6. **The deferred pieces stay deferred.** `POST /ota` carries no request schema, and
   shipping a guessed `contracts/ota-v1.json` is a failure (see below).

## The two error vocabularies

They are different registers and deliberately do not share a namespace.

**Validator diagnostics** (`tools/contracts/errors.py`, 105 codes) name *why the
contract or a fixture is wrong* — they appear in the validator report and in
`fixtures.json` as `expected_error_codes`, and never on the wire. The specs state
these conditions in prose but assign no identifiers, so this package named them;
the name is chosen so the condition is recognizable from the code alone
(`OFFSET_NOT_CONTIGUOUS`, `MANIFEST_SIZE_MISMATCH`, `ETAG_INVALID`). Four of them
are rules no single documented sentence states and the validator therefore adds:
`CLOCK_NULLITY_MISMATCH` (three conditions on `clock`: a `clock.source` of `unknown`
must carry neither `start_utc` nor `uncertainty_ms`; a known source must carry both; and
an `uncertainty_ms` that is present must be a nonnegative JSON integer no larger than the
shared 2^53−1 ceiling) and `RECOVERED_CLOSE_REASON_DISAGREE`, which enforces the biconditional
`recovered == (close_reason == "recovery")`: a segment that closed `duration`, `size`,
`settings`, `clock_change`, `shutdown`, `storage_fault` or `ota` cannot claim
`recovered: true`, and `recovered: true` may not arrive with any other close reason.
That is stricter than media-format.md §6 read alone, which only states that a
recovered segment always uses `recovery`. The other two are read off a *pair* of vectors
rather than one document: `IF_MATCH_ETAG_DISAGREE` refuses a 200 or 206 whose request
sidecar is conditional on an `ETag` the answer does not ship (interfaces.md §4 requires
412 `CONTENT_CHANGED` for that pairing), and `CHUNK_HASH_MISMATCH` refuses a chunk whose
committed bytes are not the `sha256` its well-formed `Upload-Checksum` declares (the 422
`INTEGRITY_FAILURE` the same section requires). Two more are consequences a field cannot
state and a walk can: `JPEG_TRAILING_DATA` refuses an indexed slice that is not exactly
one image — media-format.md §3 makes every record start where the preceding one ends and
the final one end at the payload's exact file size, so bytes beside the first image's
`EOI` are frame data no record and no playback time will ever reach, and the decoder
reads only the first image — and `DURATION_RECOVERED_MISMATCH` refuses a recovered
manifest whose `duration_us` is not the close time §4 fixes for it: last frame time plus
one nominal frame period, clamped to the segment maximum. Every registered code is exercised: by a committed
vector, by a mutation test, or — for the 256 MiB payload and 1.75 MiB index bounds
that cannot be committed — by a synthetic temporary vector.

**Wire error codes** are what a client actually receives in the one shared error
envelope both documents reuse: `{"v":1,"error":{"code":…,"message":…,"retryable":…,"request_id":…}}`
(`components/schemas/ErrorBody`, `additionalProperties: false`). The names a status may
carry are the codes the specification documents for that operation and status —
`STORAGE_FULL`, `ALREADY_OWNED`, `CURSOR_EXPIRED`, … — plus the twelve generic names
listed under "Illustrative choices" below, which are accepted for any documented
refusal; anything outside that set is `ERROR_CODE_UNDOCUMENTED`.

## Illustrative choices

Decisions this package had to make where the specification left room, recorded so a
later reviewer can reverse them deliberately rather than by accident:

1. **Twelve invented wire codes.** `interfaces.md` names twelve stable codes
   (`STORAGE_FULL`, `ALREADY_OWNED`, `CURSOR_EXPIRED`, `REVISION_CONFLICT`,
   `LEASE_LIMIT`, `STORAGE_PRESSURE`, `LEASE_EXPIRED`, `CLIP_GONE`,
   `CONTENT_CHANGED`, `PROTECTION_QUOTA`, `CLIP_ID_COLLISION`, `CLIP_PROTECTED`) and
   assigns statuses without names to the generic rejections. Those generic names —
   `MALFORMED_REQUEST`, `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`,
   `BOUND_EXCEEDED`, `RANGE_INVALID`, `INTEGRITY_FAILURE`, `RATE_LIMITED`,
   `UNAVAILABLE`, `IDEMPOTENCY_CONFLICT`, `OFFSET_CONFLICT`, `EXPIRED` — are chosen
   here and listed in `ILLUSTRATIVE_CODES`. The published `code` schema stays an open
   pattern, so adopting a different name later breaks no consumer contract.
2. **`STORAGE_FULL` on `POST /ota`.** `interfaces.md` §1 uses a `STORAGE_FULL` body
   as its worked example of the shared envelope but attaches no code to that route, so
   this contract assigns the code to the refusal it describes: an OTA staging request
   whose image cannot fit. `device.post_ota` therefore documents `503` with
   `UNAVAILABLE` *and* `STORAGE_FULL`, and `device/valid/error-envelope-storage-full`
   demonstrates that envelope verbatim as a **valid** vector, not a violation.
3. **The OTA envelope is deferred.** Stage 2.10 owns the firmware-image container, so
   `POST /ota` documents only the transport: `application/octet-stream` with no
   schema, plus an `x-deferred` note. `OTA_SCHEMA_PRESENT` fires if a guessed
   `ota-v1.json` appears and `OTA_DEFERRAL_MISSING` fires if the note or a schema on
   that body changes, so the deferral is enforced rather than remembered.
4. **Bounds live in two places.** Every limit in `tools/contracts/bounds.py` appears
   as a schema keyword, and each one a dedicated validator check replaces is named in
   `FRAME_DEDICATED_RULES` / `MANIFEST_DEDICATED_RULES` — a keyword may only be
   silenced by naming the check that reports it instead, and a test violates that
   keyword in a copy of the baseline segment to prove the check really fires. A schema
   keyword alone cannot prove the arithmetic (`offset + size` in unsigned 53-bit
   space) or produce the specific diagnostic the report needs; where the dedicated
   check speaks, the generic `*_SCHEMA` finding for the same field is suppressed so a
   vector fails with one honest code. Limits the documents express only as keywords
   (page size, event clip count, label length) are asserted equal to their
   `bounds.py` constant by `test_the_documents_and_the_bound_table_agree`.
5. **A checksum defect keeps its `checksums.json`.** Invalid clips ship no harness
   checksum file — except `checksum-hash-mismatch` and `checksum-size-mismatch`,
   which are *about* that file and therefore must carry it.
6. **`content-type` is a checked contract.** The documented set is `application/json`,
   `multipart/x-mixed-replace; boundary=frame` and `application/octet-stream`, so a
   preview vector that claims the streaming type is actually verified.
7. **Fixtures are generator output only.** `tools/contracts/fixture_spec.py` declares
   every vector; `generate_fixtures.py` writes it. Nobody hand-edits a committed
   fixture, and the validator re-derives the whole corpus and compares bytes, so a
   fixture that was "fixed" by hand fails the run.

## Working in the contract

- Change a requirement in `docs/specs/` first, then the schema or OpenAPI document,
  then `tools/contracts/bounds.py` / `fixture_spec.py`, then regenerate. The
  validator is the arbiter that all four moved together.
- Add a vector by adding a `_Negative(...)` or `out.add(...)` entry in
  `tools/contracts/fixture_spec.py` and running the generator. Keep a negative
  vector to exactly one defect so the expected code set stays a single honest name.
- Keep the corpus offline and deterministic: no clock reads, no environment
  variables, no sockets, no dependency outside pytest, jsonschema, PyYAML and
  Pillow (see `tools/contracts/requirements-dev.in`).

## Out of scope here

This package validates the contract and the host-side fixtures. It does not prove
that the ESP32 firmware writes these bytes, that the Flutter app or the Rust backend
parses them, or that any device, card or hosted backend behaves accordingly. Those
need DEVICE, app, backend and FIELD evidence from their own packages
([validation plan](../docs/validation.md)).
