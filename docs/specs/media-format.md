# Original recording format v1

Status: proposed contract to freeze with golden fixtures in package 0.6. This
document owns file names, timestamps, bounds, integrity, and recovery semantics.
It deliberately avoids requiring an AVI muxer on the microcontroller or assuming
that a phone's native video player can play raw MJPEG.

## 1. Layout and identity

```text
/vdog/v1/clips/<clip_id>/
  video.mjpg          concatenated complete JPEG payloads, no separators
  frames.jsonl        one compact UTF-8 JSON object per complete line
  manifest.json       immutable completion record; absent while active
```

Device-internal active names use `.part` suffixes. Finalization renames payload
and index first and writes `manifest.json.tmp` followed by `manifest.json` last.
Catalog readers expose a clip only after full validation of this completion
record. An interrupted rename sequence is recoverable, not proof of completion.
Event pins, leases and upload acknowledgements live outside these three files.

`device_id` is 32 lowercase hexadecimal characters provisioned once.
`boot_id` is 32 random lowercase hexadecimal characters per boot; it does not
reveal a MAC address. `clip_id` is `<boot_id>-<sequence>` where sequence is exactly
eight lowercase hexadecimal digits, starting at zero. Rotate boot/session ID
before sequence overflow. Validate IDs against this syntax before path lookup;
never turn a user-supplied path into a filesystem path.

## 2. Version, units and bounds

| Item | v1 rule |
| --- | --- |
| Version | JSON field `v: 1`; reject unsupported major versions |
| Segment duration | Target 60s; hard maximum 120s; early split allowed for faults/settings/time |
| Dimensions | Positive width/height; each ≤1600; JPEG SOF dimensions must match manifest |
| FPS | Nominal integer 1–30; actual rate may be lower and is derived from timestamps |
| Frame size | 1–2,097,152 bytes; oversized frames dropped with a counter |
| Frames/clip | At most 3,600 |
| Payload size | At most 268,435,456 bytes (256MiB), close before next frame crosses it |
| Index line | At most 512 bytes including newline; index ≤1,843,200 bytes |
| Manifest | At most 16,384 bytes |
| JSON integer range | Nonnegative ≤2^53−1 for numeric fields shared with Dart/JSON tools |
| Character encoding | UTF-8; JSONL uses LF; no BOM or blank lines |
| Hash | SHA-256, 64 lowercase hexadecimal characters over exact file bytes |
| CRC | CRC-32/ISO-HDLC, polynomial 0x04C11DB7, reflected, init/final xor 0xffffffff |

The limits bound hostile inputs; they are not recommended recording settings.
Split before hitting any bound. Reject overflowing offset+size calculations
before reading or allocating. No ZIP/TAR bundle is accepted in v1 ingestion.

## 3. Frame index

Example of a first record (CRC shown illustratively; fixtures must use real CRCs):

```json
{"v":1,"seq":0,"offset":0,"size":24576,"t_us":0,"crc32":"12345678"}
```

`seq` is consecutive from zero. `offset` is the byte offset of the JPEG SOI;
`size` includes SOI and EOI. Each record starts exactly at the preceding record's
`offset + size`, and the final record ends at the payload's exact file size.
CRC covers the exact JPEG payload bytes. Every referenced JPEG must decode;
marker checks alone are not sufficient backend validation.

`t_us` is capture time in microseconds relative to the first retained frame of
this segment. First record is zero; following values strictly increase. Use the
camera acquisition timestamp, not the later SD write time. Capture gaps are
represented by larger timestamp differences. They are not filled with invented
index records. At a hardware timestamp tie, drop the duplicate-time frame and
increment the drop counter rather than falsifying capture time.

## 4. Manifest

Normative example shape; values and hashes are illustrative, not a valid fixture:

```json
{
  "v": 1,
  "device_id": "0123456789abcdef0123456789abcdef",
  "boot_id": "11111111111111111111111111111111",
  "clip_id": "11111111111111111111111111111111-00000000",
  "capture_order": 42,
  "firmware_version": "0.1.0",
  "hardware_revision": "prototype-a",
  "profile": {"width":640,"height":480,"nominal_fps":15,"jpeg_quality":20},
  "clock": {"source":"unknown","start_utc":null,"uncertainty_ms":null},
  "start_boot_us": 1000000,
  "duration_us": 60000000,
  "frame_count": 900,
  "dropped_frames": 0,
  "close_reason": "duration",
  "recovered": false,
  "files": {
    "video.mjpg": {"bytes":22118400,"sha256":"<64 lowercase hex characters>"},
    "frames.jsonl": {"bytes":97200,"sha256":"<64 lowercase hex characters>"}
  }
}
```

Required keys are as shown; `profile.jpeg_quality` is the esp32-camera driver
parameter (lower commonly means higher quality, verify the pinned driver), not
a generic percentage. `duration_us` is an exclusive media end: it must exceed
the final `t_us` and be ≤120,000,000. While running, use measured segment close
time. After recovery, use last frame time plus one nominal frame period, clamped
to the maximum duration, and mark `recovered:true`. Record dropped acquisition
frames only when observed; unknown losses across reset cannot be counted and
are described by recovery status.

`capture_order` is a card-local increasing integer used for eviction ordering
even when UTC is unknown. Reserve it durably in the card catalog before capture;
on recovery continue above the largest reserved or valid manifest value. Gaps
are allowed. It is not a global ordering across different cards or devices.

`clock.source` is `unknown`, `phone`, or `sntp`; `start_utc` is nullable RFC3339
UTC with millisecond precision and trailing `Z`. When known, `uncertainty_ms`
is required and nonnegative; phone/SNTP time is an estimate, not trusted proof.
`start_boot_us` is the monotonic first-frame time for that boot. Unknown UTC
remains unknown; backend upload time is a separate property and never replaces it.

`close_reason` is one of `duration`, `size`, `settings`, `clock_change`, `shutdown`,
`storage_fault`, `recovery`, `ota`. A recovered segment always uses `recovery`.
Empty segments are discarded rather than finalized.

## 5. Writer and durability algorithm

The active-state record is `/vdog/v1/clips/<clip_id>/active.json`, UTF-8 JSON
≤16KiB with `{v:1,device_id,boot_id,clip_id,capture_order,firmware_version,
hardware_revision,profile,clock,start_boot_us}` using the manifest field rules.
Before the first payload append, atomically publish and sync it using the first
accepted frame's timestamp/clock mapping, then set that frame's `t_us` to zero.
If this record cannot be persisted, do not record frames under that clip ID.
Normal finalization removes it only after the completed manifest is durable.

1. Create a new ID and active directory; reject existing IDs. Store provisional
   profile/clock/start information in a bounded recoverable active-state record.
2. For each valid frame, append payload, then append its index line. Maintain
   rolling SHA-256 contexts for both files and count bytes/gaps. Release camera
   ownership exactly once after consumption or an explicit drop.
3. At least once a second, flush the media file and synchronize it, then flush
   and synchronize the index. Acknowledge persisted progress only afterward.
4. At cutover stop appending to that segment, sync and close both, check sizes,
   finalize hashes, rename payload/index, then publish the completed manifest.
   The next segment may capture through a bounded queue while close completes.
5. Persist the catalog transaction only after the completion record; on boot it
   must be possible to rebuild the catalog from valid clip directories.

FAT/SD controller behavior can still corrupt previously written sectors after
power failure. No fsync ordering, CRC or rename makes the card transactional.
Measure actual loss/corruption and treat an unreadable filesystem as a fault;
never automatically format it to resume recording.

## 6. Recovery algorithm

Mount without formatting. Enumerate active/incomplete records in bounded pages.
For each index, parse complete lines until the first malformed, oversized,
nonconsecutive, out-of-range, nonmonotonic or CRC-failing entry. Keep the maximal
validated prefix only; ignore all later entries. Truncate payload to the end of
that prefix and index to its final newline only if the files are known to be
this recorder's active files. Never truncate immutable finalized originals.

For interrupted finalization, accept either `.part` or final name for each of
the two files when `active.json` exists and no valid final manifest exists. If
both names exist for one file, quarantine the clip as ambiguous rather than
selecting one. A valid completed manifest takes precedence; validate its final
file names and remove stale active metadata only after verification. If no
active metadata and no valid manifest exist, quarantine rather than guessing.

Validate JPEG bounds and CRC before rebuilding a manifest. If active-state
profile/clock is missing or JPEG dimensions disagree, quarantine for manual
inspection rather than guessing. With no valid frames remove/quarantine the
empty active segment. Recompute hashes and publish a recovered manifest for a
valid prefix. Corrupt finalized clips are marked unavailable/quarantined, never
silently rewritten under their old ID. Continue recording to a new ID only if
the remaining filesystem is writable and validated.

Interrupted pruning uses a tombstone outside the clip directory. Replay deletion
for unprotected, unleased clips; never resurrect a partially deleted clip into
the catalog. Bound boot recovery time and show `recovering` while work remains.

## 7. Playback, export and validation

Flutter indexes the JSONL on a worker isolate, performs bounded range reads,
decodes JPEGs, and schedules presentation using `t_us`. It should drop display
frames if decoding lags without changing the original. Pause/seek releases
buffers and uses a binary search over frame times. Do not load an entire clip
or the entire card into memory.

The backend validates bounds, IDs, record continuity, CRCs, decoded dimensions,
manifest counts/duration and SHA-256 before committing the original. It extracts
frames into a private quota-limited workspace for a validated FFmpeg input list;
durations come from consecutive timestamps and the manifest's final duration.
If exporting constant-rate MP4, explicitly document frame duplication/drop and
retain the original timing metadata. A derivative records original hashes,
encoder/filter versions, parameters, output dimensions, crop and its own hash.

Source timestamp/index validation is exact integer validation; do not round
timestamps in originals. For deterministic player tests, the selected frame at
playback time T is the greatest `t_us ≤ T`, with duration ending at manifest
`duration_us`. Real rendering may skip late display frames while keeping that
clock mapping. Report skipped display frames separately from recorded drops.
For CFR MP4 export, fix an output FPS ≤the nominal source FPS and test first
presentation at zero, sampled source mapping and total duration error no greater
than one output frame period plus 5ms for muxer rounding. Include fixtures with
long gaps and final-frame duration; record duplication/drop in derivative metadata.

Golden fixtures must include a real tiny valid JPEG sequence, a gap, unknown
UTC, early close, recovered prefix, corrupt CRC, truncated index/payload,
overflow, invalid ID, oversized dimensions, and unsupported version. All three
implementations consume the same fixtures; examples above are not test vectors.
