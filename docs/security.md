# Security and privacy design

Status: requirements for implementation, not an assessment of working software.
Exact endpoint behavior is in [interfaces](specs/interfaces.md).

## 1. Assets and trust boundaries

Assets are owner footage, camera control, Wi-Fi credentials, device identity,
backend tokens, OTA signing keys and original media integrity. Boundaries are
camera/SD, local Wi-Fi/phone, phone/backend, uploaded media/worker, and release
signing/provisioning. A shared router, nearby phone, QR image or uploaded file
is not automatically trusted.

| Threat | Required control | Residual limitation / test |
| --- | --- | --- |
| Nearby control or footage theft | Unique AP password, pinned HTTPS, token auth, physical pairing window | Verify all routes including preview/files; AP password alone is not ownership |
| Rogue device/discovery response | Exact QR certificate fingerprint; ID matching; discovery is only a hint | Certificate change requires physical re-pair, not accept-all TLS |
| Unauthorized owner replacement | `ALREADY_OWNED`, deliberate ownership reset, rate limiting | Physical access permits ownership reset; document it |
| Stolen phone/token | OS secure credential storage, token hashes, revocation/reset | Unlocked/compromised phone remains a risk |
| Stolen SD card | Disclose plaintext originals; minimize identifying metadata | v1 does not encrypt SD; TLS/flash encryption do not solve this |
| Malicious/corrupt upload | Bounds/IDs/offsets/CRC/SHA/schema and decoder checks | Hashes verify bytes, not authenticity of a claimed scene |
| Media parser or FFmpeg exploit | Pinned updated builds, nonroot worker, network disabled, resource limits | Host isolation and adversarial tests required |
| Path traversal / shell injection | Server-generated paths, exact file whitelist, argv subprocess API, no shell | Test encoded traversal, symlinks, newlines, hostile labels |
| Bad update / stolen signing key | Signed hardware-compatible images, version policy, rollback, key custody | Bench checks are not production secure-boot provisioning |
| Storage exhaustion / denial of service | Quotas, bounded leases, upload expiry, rate limits | Availability cannot be guaranteed against physical disruption |

## 2. Data handling

Do not capture audio, location or personal identifiers beyond required opaque
device IDs. Do not publish raw walk recordings as fixtures: they can contain
people, homes and routes. Use synthetic or consented redacted test imagery.
Do not log tokens, provisioning QR contents, Wi-Fi passwords, private keys or
frame payloads. Logs use correlation IDs, counts, states and safe error codes.
Diagnostic export is owner initiated. No external analytics SDK is required.

Phone storage distinguishes incomplete downloads, verified originals and
derivatives. Deleting a local copy must not imply deletion from SD/backend.
Backend retention and backup behavior must be explicit; an event pin is not an
unlimited-retention guarantee. Backend and camera credentials are independent.

## 3. Backend and worker controls

Expose authenticated APIs except minimal health checks. No public media
directory, unrestricted CORS, default token or public signup. Bind localhost
for development; document HTTPS and private-network deployment for self-hosting.
The phone uses authorization headers, not token-bearing shared media URLs.

Worker input/output directories are private and server-generated. Run FFmpeg
with argv, no shell, no arbitrary client filter strings, remote URL inputs or
network protocols. Bound duration, resolution, frame count, decoded memory,
CPU/wall time, process count and scratch quota. Kill and reap children on
timeout/cancel; validate output before publishing. Do not decode media inside
the API request executor. Reject symlinks; cleanup cannot escape the storage root.

Back up SQLite and blobs as a consistent set; exercise restore/hash verification.
Document token/signing-key rotation and revocation. Keep production secrets out
of example deployment files and images.

## 4. Release requirements

The existing [MIT LICENSE](../LICENSE) covers repository materials in its scope.
Track dependency notices separately. Review FFmpeg build flags, codec dependencies,
vid.stab inclusion and distribution obligations before shipping binaries; the
repository license does not relicense dependencies. Document hardware-design
license scope before publishing PCB/CAD artifacts. No license text changes here.

Production flash encryption, secure boot and eFuse settings need a reviewed
manufacturing/recovery procedure, identified devices, key custody and explicit
authorization. Do not perform irreversible provisioning as a test shortcut.
