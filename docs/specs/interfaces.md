# API and data contracts v1

Status: proposed wire contract. Generate OpenAPI/JSON schemas and fixtures from
this baseline in package 0.6 before consumer implementation. Routes below are
normative; software specs defer to this document for exact names.

## 1. Shared conventions

All JSON is UTF-8 and has `v:1` in top-level request/response objects. APIs are
under `/api/v1`; unknown major versions fail. JSON control request bodies are
≤16KiB except backend upload initialization ≤32KiB. Reject unknown write fields;
readers tolerate unknown response fields. Required fields, enums, ranges and
nullable clock values must be captured in schemas. Time units follow suffixes:
`*_us` microseconds, `*_ms` milliseconds, `*_s` seconds; sizes and offsets are
integer bytes. Hashes,
ID syntax and media bounds follow [media-format.md](media-format.md).

```json
{"v":1,"error":{"code":"STORAGE_FULL","message":"No evictable recording space","retryable":false,"request_id":"opaque-id"}}
```

Use 400 malformed/range, 401 missing/invalid token, 403 wrong privilege/physical
window, 404 never-known resource, 409 state/revision/offset conflict, 410 known
evicted clip/expired upload, 413 bound exceeded, 416 invalid byte range, 422
integrity/schema/media failure, 429 rate limit, 503 temporarily unavailable.
Include `Retry-After` where retry is meaningful. Do not expose secrets, paths,
FFmpeg command lines or raw internal errors. `message` is display-safe;
clients branch on stable `code`, never localized strings.

Cursor pagination returns `{v,items,next_cursor}`; cursors are opaque and bounded
to 256 characters. Defaults are 50 device items / 100 backend items; maximum 100.
An expired cursor returns 409 `CURSOR_EXPIRED`; restart the listing. No assumption
of a stable live catalog between pages; deduplicate by immutable IDs. Backend
ingest identity is `(device_id,clip_id)` and returns 409 if bytes differ.

## 2. Local device authentication and provisioning

During factory/development USB provisioning generate per-device TLS key/cert,
32-byte random setup secret, unique ≥16-character WPA2 SoftAP password and stable
device ID. QR payload is versioned JSON with `v`, `device_id`, `ap_ssid`,
`ap_password`, `cert_sha256` (SHA-256 of DER certificate), and `setup_secret`
(base64url without padding). Do not include TLS private key. Provisioning details
and secret artifacts stay out of Git and test logs.

The phone joins the AP through supported OS steps, connects to the documented
AP IP (baseline 192.168.4.1), and validates the exact QR certificate pin before
sending the setup secret. Router/hotspot address changes use the same pin; never
accept all certificates to solve discovery. Device TLS ports: 443. mDNS service
`_vdog._tcp` advertises ID/port only and is an unauthenticated hint.

| Method / path | Input and successful result | State rules |
| --- | --- | --- |
| POST `/pair` | `{v,setup_secret,client_name}` → 201 `{v,device_id,token_id,access_token}` | Physical button opens a 120s window; setup secret checked constant-time; one owner token initially; rate-limited to 5 failures/minute |
| POST `/tokens/revoke` | `{v,token_id}` → 200 `{v,revoked:true}` | Owner may revoke its token; adding another owner is outside v1 |
| GET `/capabilities` | `{v,device_id,firmware_version,hardware_revision,media_versions:[1],features:[...],limits:{...}}` | Requires token; reports implemented features, not planned ones |

`/pair` returns 409 `ALREADY_OWNED` while ownership exists, even in an open
physical window. It never replaces an owner token implicitly. Revoking the last
token leaves ownership locked; deliberate physical ownership reset is required
to claim again. Reset clears ownership/tokens but retains SD originals and the
device certificate; factory certificate replacement is a distinct provisioning
operation requiring a new QR pin. Document the physical gestures in board docs.

All routes except `/pair` require `Authorization: Bearer <token>` after pinned
TLS, including preview and file transfer. The token is 32 random bytes encoded
base64url, stored hashed on device and in OS secure storage on the phone. Pairing
does not transmit Wi-Fi credentials over plaintext. Transfer station credentials
via authenticated settings only. Changing network credentials does not revoke
ownership; ownership reset requires a separate deliberate physical procedure,
revokes phone tokens, and does not erase the SD card. A lost/replaced certificate
requires physical re-pairing, not remote trust-on-first-use.

## 3. Status, settings, preview and clock

| Method / path | Contract |
| --- | --- |
| GET `/status` | `{v,device_id,boot_id,state,fault_code,uptime_ms,recording:{clip_id,frames,dropped_frames},storage:{mounted,total_bytes,free_bytes,rolling_bytes,protected_bytes,retained_duration_s},power:{battery_mv,external_power},network:{mode,connected},settings_revision}` |
| GET `/settings` | `{v,revision,recording_profile,network:{mode,ssid},preview_enabled}`; no password returned |
| PUT `/settings` | `{v,expected_revision,recording_profile?,network?,preview_enabled?}` → `{v,revision,effective_from_clip_id}`; unsupported profile rejected; apply recording changes only at boundary |
| POST `/time` | `{v,utc,uncertainty_ms}` → `{v,applied:true}`; RFC3339 UTC; close current segment before changing UTC mapping |
| GET `/preview` | `multipart/x-mixed-replace; boundary=frame`; each part JPEG with Content-Length and X-Capture-Boot-Us; max one client at ≤2FPS |

`state` is `booting`, `recovering`, `recording`, `storage_fault`, `camera_fault`,
`storage_full`, `updating`, or `shutting_down`. `fault_code` is nullable; at least
`NO_CARD`, `UNSUPPORTED_FS`, `SD_IO`, `CAMERA_INIT`, `NO_EVICTABLE_SPACE`,
`LOW_POWER`, `RECOVERY_REQUIRED` are defined. `battery_mv` and `external_power`
are null if not measurable; do not derive a battery percentage from voltage
without characterization. `retained_duration_s` is sum of valid unprotected
recorded durations, not newest-minus-oldest UTC. `recording.clip_id` is null when
inactive. Storage totals are zero only for measured zero, otherwise null when
unmounted. Optional UI state never implies recording is healthy.

No remote stop-recording route in v1. Preview may close with 503 or disconnect
under recording pressure and must release camera buffers promptly. Settings
use revision compare-and-swap: stale writes return 409 `REVISION_CONFLICT` with
current revision. Secrets are write-only. A disruptive network change returns
an acknowledgment before scheduled reconnect; the app must reconnect by ID/pin.

## 4. Clip catalog, leases and resumable downloads

| Method / path | Contract |
| --- | --- |
| GET `/clips?cursor=...&limit=...` | Page of `{clip_id,start_utc,duration_us,frame_count,bytes,protected,recovered}` finalized valid clips only |
| GET `/clips/{clip_id}/manifest` | Exact immutable manifest from media contract, JSON |
| POST `/clips/{clip_id}/leases` | `{v}` → 201 `{v,lease_id,expires_in_s:300}`; 409 `LEASE_LIMIT` if quota exceeded |
| PUT `/leases/{lease_id}` | `{v}` → 200 `{v,lease_id,expires_in_s:300}`; 409 `STORAGE_PRESSURE` may deny renewal |
| DELETE `/leases/{lease_id}` | 204, idempotent |
| GET `/clips/{clip_id}/files/{name}` | `name` exactly `video.mjpg` or `frames.jsonl`; require `X-Clip-Lease`; immutable bytes with ETag and Range support |

Device max one downloading client and two clip leases total; default lease
300s. Expired lease returns 409 `LEASE_EXPIRED`; known evicted clip returns 410
`CLIP_GONE`. A pin is not a transfer lease. A new lease may be refused if it
would prevent recording from meeting free-space thresholds. Deletion and lease
grant are serialized, so there is no grant-versus-prune race.

Lease expiry is checked before each response chunk. On expiry, stop sending,
close the stream/file handle within a bounded 5s I/O timeout, then permit prune.
If headers were already sent, close the connection; the client treats this as
an incomplete transfer, reacquires a lease and resumes or reports `CLIP_GONE`.
An open HTTP response must not extend a lease indefinitely.

Support single `Range: bytes=start-end` or `bytes=start-` only. Return 206 with
`Content-Range`, `Accept-Ranges: bytes`, exact Content-Length and ETag equal to
the quoted SHA-256. No Range returns 200. Multipart/suffix ranges are rejected
with 416. On resume require `If-Match` with the original ETag; mismatch returns
412 `CONTENT_CHANGED`. Client writes a temporary local file, stores offset and
manifest, re-acquires a lease if necessary, and verifies full SHA-256 before
renaming to completed. Neither lease nor download changes original content.

## 5. OTA contract

POST `/ota` uses authenticated `application/octet-stream`, one signed firmware
envelope, no arbitrary URL fetch. Envelope schema in `contracts/ota-v1.json`
must contain envelope version, product/hardware compatibility, firmware version,
image length/SHA-256, signing-key ID, signature and image. Define the exact binary
encoding and signature coverage in package 2.10 before implementing it. Use
ESP-IDF-supported signing/verification primitives; do not invent cryptography.
Capability limits give the inactive-slot maximum image size. Reject unsigned,
oversized, wrong-hardware, disallowed downgrade or invalid-signature images
before activation. Successful staging returns 202 `{v,state:"reboot_pending"}`.

The phone warns that recording pauses for this explicit operation. Firmware
closes/syncs the active segment first, writes only the inactive slot, verifies
the complete image, persists pending status, and reboots. New image reports
healthy only after memory, configuration and recording-path checks. SDK rollback
must remain enabled and be bench-tested. Production eFuse/security policy and
signing-key custody are a separate manufacturing gate; do not burn eFuses as part
of ordinary tests. OTA envelope details remain the only intentionally unfrozen
wire portion of this baseline and block OTA implementation, not Stage 1.

Every pre-reboot rejection, timeout, cancellation or staging/write failure must
close/invalidate the partial inactive image, clear pending update metadata and
automatically resume recording on the current firmware. Report the update error
separately. A malformed update must not leave recording paused. Once reboot has
started, recovery follows the verified SDK rollback path.

## 6. Device events, Stage 3

POST `/events` accepts `{v,event_id,clip_ids,label}`; `event_id` is a client UUID,
label ≤120 characters, 1–10 finalized clip IDs. Same ID/same content is idempotent;
different content returns 409. Device computes newly protected bytes, then
atomically pins all requested clips or returns 409 `PROTECTION_QUOTA`. Maximum
protected size 8,000,000,000 bytes or the smaller configured safe pool bound.
GET `/events` lists event metadata; DELETE `/events/{event_id}` removes that
event's pins, preserving clips pinned by other events. Physical automatic impact
events are outside v1. Protection does not retroactively restore evicted clips.

## 7. Backend identity and authorization

Backend is a single-owner self-hosted instance. A bootstrap CLI creates a random
32-byte admin bearer credential once; no default credentials or open registration.
Admin creates/revokes separate scoped API tokens (`owner`, `device-upload`) via
POST `/tokens`, DELETE `/tokens/{id}`. Backend tokens are distinct from local
camera tokens. Owner can register `{device_id,label}` with POST `/devices`;
registration alone grants no access to a camera. A device-upload token is scoped
to one device and may ingest/status its own uploads only. All requests use
HTTPS outside localhost development. Flutter stores the token in OS secure
storage; backend stores only token hashes. No refresh-token/session-cookie flow
is required in v1; no auth through query strings.

## 8. Backend resumable ingestion

Only finalized bundles from the media contract are accepted. Exact original
manifest bytes are sent during initialization; media/index are streamed separately.

1. POST `/uploads` with `{v,manifest_base64url}` and `Idempotency-Key` (UUID).
   `manifest_base64url` is unpadded base64url of the exact UTF-8 `manifest.json`
   bytes; decoded length ≤16KiB. Validate its JSON and preserve the bytes unchanged.
   The encoded request must fit the 32KiB body limit. Return 201
   `{v,upload_id,state:"receiving",offsets:{"video.mjpg":0,"frames.jsonl":0},expires_in_s:86400}`.
   Scope device ID by token; enforce aggregate/reserved quota before allocation.
   Same key/same request returns existing upload; same key/different request 409.
2. PATCH `/uploads/{id}/files/{name}` with octet-stream, `Upload-Offset` and
   `Upload-Checksum: sha256 <64 lowercase hex>`. Body 1–1,048,576 bytes; only the
   two permitted file names. Exactly one in-flight writer per upload. Verify
   chunk length/hash, append at expected offset, sync, persist offset, then
   return 204 and new `Upload-Offset`. Wrong offset returns 409 with authoritative
   offset; never append repeated bytes implicitly.
3. HEAD the same file route returns authoritative `Upload-Offset` and
   `Upload-Length`. Crash before metadata commit truncates scratch bytes to the
   durable committed offset. Retrying after an ambiguous response starts with HEAD.
4. POST `/uploads/{id}/commit` with `{v}` validates both lengths/hashes and every
   index/frame bound, then publishes the clip through a recoverable DB/filesystem
   transaction. Return 201 `{v,clip_id,state:"stored"}` only after durability;
   repeated commit returns the same result. Integrity failure returns 422 and
   quarantines/rejects the upload without creating a catalog entry.
5. DELETE `/uploads/{id}` cancels receiving uploads idempotently. GET `/uploads/{id}`
   returns state, offsets and expiry for authorized clients. Inactive receiving
   uploads expire after 24h since last successfully committed chunk; return 410.

Whole-file integrity, not chunk acknowledgement, proves successful ingestion.
Existing `(device_id,clip_id)` is a deduplicated success only if SHA-256 of the
exact original manifest bytes and both declared data-file hashes all match.
Different manifest bytes, including clock/profile changes with identical JPEGs,
return 409 `CLIP_ID_COLLISION`, as do changed data hashes. Store the computed
manifest hash during initialization/commit; it is not self-embedded in the
manifest. Storage paths are server-generated.

## 9. Backend catalog, events and jobs

| Method / path | Result / request |
| --- | --- |
| GET `/devices`, GET `/clips` | Owner-scoped paginated catalogs; clips include device ID and original manifest summary |
| GET `/clips/{clip_id}?device_id=...` | Manifest plus upload time, integrity state and derivative metadata |
| GET `/clips/{clip_id}/files/{name}?device_id=...` | Authorized range download of original, same ETag/range semantics |
| DELETE `/clips/{clip_id}?device_id=...` | Owner deletion, 202 `{v,state:"deleting"}`; 409 `CLIP_PROTECTED` until all server event pins are removed; no SD effect |
| POST `/events` | `{v,event_id,device_id,clip_ids,label}`; server event association only, not a remote pin acknowledgement |
| GET `/events`, DELETE `/events/{id}` | Owner event list/removal; separate configured backend retention policy |
| POST `/jobs` | `{v,device_id,clip_id,type,preset}` with Idempotency-Key; type `transcode` or `stabilize`; approved preset enum only |
| GET `/jobs/{id}` | `{v,job_id,state,progress,error_code,derivative_id}`; progress nullable; no fabricated estimate |
| DELETE `/jobs/{id}` | Request cancellation; 202 while stopping; terminal cancellation only after child cleanup |
| GET `/derivatives/{id}` | Metadata and authorized Range file endpoint `/derivatives/{id}/file` |
| DELETE `/derivatives/{id}` | Owner deletion, 202 `{v,state:"deleting"}`; idempotent cleanup, no original or SD effect |
| GET `/health/live`, GET `/health/ready` | Minimal health only; ready verifies DB/storage/required worker dependencies |

`clip_id` is scoped by `device_id` in backend requests; include the query parameter
on GETs above. Job states: `queued`, `running`, `cancel_requested`, `succeeded`,
`failed`, `cancelled`, `interrupted`. On restart, stale running jobs become
`interrupted`; a bounded retry policy starts a new attempt without changing the
original. Deduplicate jobs by original hash/type/preset/version. A result is
`succeeded` only after output validation and durable publication. Notifications
are owner-configured completion/failure or manual-event messages, never an
assertion that a dog is in danger. A local event and a server event are distinct
acknowledged states; lack of network means no immediate remote notification.
