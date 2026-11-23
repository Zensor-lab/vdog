# Daytime recording and physical acceptance rubric (0.5)

Status: **DRAFT FOR OWNER / QUALIFIED REVIEW**, 2026-11-23.
Confirmed goal: objects on the ground during daytime walks, **0.5–1 m from
the camera**, using the selected Sense OV5640. Numeric scoring limits below
are engineering proposals, not owner-approved requirements or observed results.
Freeze their acceptance before measuring profiles; a poor result is not a
reason to change the rubric after testing.

Requirements: PR-03/11/16/19 and HWR-03/04/05/06. The
[product performance baseline](product.md#5-performance-and-capacity-targets)
and [validation methodology](../validation.md#3-quality-and-retention-methodology)
remain authoritative. [Prototype A](../../hardware/prototype-a/README.md)
owns actual electrical identity. Contract field names/bounds remain owned by
package 0.6's media/API specifications and fixtures.

## 1. Repeatable scene

Use harmless, reusable matte targets; no animal or hazardous object is needed
for bench image tests. Proposed primary targets: a **50 mm square, disc and
triangle** with distinct shape; repeat at **20 mm as a separately reported
stretch test**, without letting the stretch result redefine the primary pass.
Record exact dimensions/colors, material and target photo/identifier.

Measure lens-to-target-centre distances **0.50, 0.75 and 1.00 m**, including
the target path. Record camera height/angle/orientation and mounting jig so the ground
view is reproducible. Do not equate these distances with a guaranteed detection
radius or field of view. Use the stock fixed-focus lens; do not assume autofocus.

Required scene cells are each distance crossed with: diffuse daylight, direct
sunlight, and open shade; each on plain and textured backgrounds; each static
and at a repeatable bench walking-motion proxy. Record time/weather/shadows,
exposure/white-balance settings and lux if measured. A light cell not available
is UNVERIFIED, not replaced by a different cell. These daylight tests make no
night/indoor claim.

For the motion proxy, move a target along a marked arc centred on the lens at
the scene cell's measured radius, using a jig and proposed **1.0 m/s** path
speed. Run **10 repetitions per scene cell**, randomizing the three shapes.
Fix the evaluated arc and its entry/exit markers before capture, with the whole
target in the intended field of view; record window duration, target-centre
distance variation and speed per pass. A straight-path jig needs its own frozen
window/distance record before comparison. Record static cells as 10 separate
one-second windows with shuffled target order. Never discard an occluded,
missing or badly exposed window after viewing its footage. Report fixture
setup mistakes separately and retain the original result when repeating them.
This proxy is not evidence of actual dog/harness motion; field validation is
separate. Running is outside the initial daytime walking rubric.

## 2. Profiles and blind scoring

Compare **640×480 and 800×600, each at nominal 10 and 15 FPS**, as proposed by
the existing feasibility matrix. Use JPEG and no audio. Record exact sensor,
driver/build/configuration, compression settings, actual FPS, orientation and
card for every profile. Freeze the compression settings to compare before
collecting scored footage. No 5MP/HD/autofocus claim follows from the sensor.

Keep originals; evaluate at native image scale without EIS, generated frames,
upscaling or sharpening. Hide target identity and profile labels from the
scorer, who chooses square/disc/triangle/unknown and records each frame's score:

| Score | Observable result |
| --- | --- |
| 0 | Missing/occluded/unusable frame, or target cannot be located |
| 1 | Target located but shape cannot be identified reliably |
| 2 | Shape identified correctly against the hidden target record |

Denominator: all expected frame opportunities in each recorded evaluation
window at that profile's nominal FPS, including missing opportunities scored
0. Retain timestamps, target truth, individual scores, scorer and missing-frame
method; don't count duplicate frames twice. Disagreements get a second scorer
and a retained adjudication record. Scoring is object-shape readability, not
text reading, species/poison recognition or automated hazard detection.

Proposed primary readability threshold: **at least 80% score-2 opportunities
per window, in at least 9 of 10 windows in every required scene cell**.
Report each cell and each distance separately; do not pool good near/static
results to conceal poor far/moving results. Stretch-size results are separate.
The owner must agree that the target size and score represent useful footage
before these limits become acceptance criteria.

## 3. Cadence, gaps and capacity

| Metric | Proposed limit or required reporting |
| --- | --- |
| Actual delivered FPS | At least 90% of nominal FPS in every scored window; count unique valid frames |
| Drops / invalid frames | Report capture attempts, valid persisted frames, duplicates and failure reasons separately; proposed combined missing/invalid fraction ≤1% over each longer profile run |
| Long-run cadence | At least 10 minutes per candidate profile; report all gaps and max gap, not just mean FPS |
| Segment cutover gap | Existing proposed limit ≤2 nominal frame periods; report cutover gaps separately from ordinary gaps |
| Boot to first persisted frame | Existing proposed ≤10 s on a qualified healthy card; later Stage 1 device test |
| Normal gaps | Proposed no interval >3 nominal frame periods during steady recording, excluding declared boot/OTA; report any miss |
| Storage / resource load | JPEG mean/p95/p99/max, allocated bytes/s, SD write/sync p95/p99/max, heap/PSRAM minima, queue maximum and failure counters |
| Access workload | Re-run the selected profile with the later qualified timed-Wi-Fi/TLS workload; no recording claim from a radio-off-only test |

Missing frame opportunities and capture-attempt counters serve different
purposes: state how each is obtained. If counters or timestamps are unavailable,
that metric is UNVERIFIED. No full-segment buffering is implied by this rubric.
If a proposed profile violates 0.6's frozen media bounds, resolve the mismatch
before capture; this rubric does not authorize changing those bounds.

Useful image quality comes first. Apply the existing 32GB/allocated-growth
capacity calculation only to profiles that pass the agreed image rubric.
Publish actual quality, coverage and useful retained duration. **72h remains
unverified** until real capture/rollover proves it; a powered 72h run alone
does not pass. Do not silently lower quality/FPS or exclude indexes, catalog,
protected clips, allocation and headroom to reach the target.

## 4. Physical acceptance and wear gate

Before any wear, record the actual dog's weight/chest and harness dimensions,
complete assembly mass/dimensions, camera angle, target ground coverage,
strap/leg clearance, enclosure/pack retention, strain relief and exposed edges.
Use a representative jig for initial geometry; no live dog is needed for it.

Qualified electrical/mechanical review must set **numeric** acceptable
ambient/contact-temperature/time and assembly mass/retention limits, their
measurement method and stop conditions for this exact pack/case/dog. Those
values are **PENDING**; no universal safe dog temperature or body-mass
percentage is asserted. Available soldering tools do not supply this evidence.
Plan for a scale and temperature measurement; the exact instruments are pending.

Dry-weather wear is gated on approved electrical/power/thermal/basic-housing
checks and a supervised fit procedure, including an identified responsible
person, brief approved trial duration, inspection intervals and immediate stop
for heat, movement restriction, rubbing, loose parts or discomfort. No charging
while worn; remove/disconnect the pack for external charging. Passing a bench
scene does not pass fit, comfort, runtime or weather protection.

## 5. Freeze and result record

For each run record test ID/date, approved rubric revision/commit, actual unit,
firmware/config/card, geometry/scene/speed/light, raw footage references/hashes,
scorer records, metric denominators, failures and PASS/FAIL/UNVERIFIED per cell.
Do not put private footage or personal identifiers into Git.

| Closure item | Current status |
| --- | --- |
| Owner goal: daytime ground objects at 0.5–1 m | CONFIRMED |
| Proposed target size, scoring/FPS/drop/gap thresholds and scene matrix | PENDING OWNER ACCEPTANCE |
| Exact jig/light method and geometry | PENDING MEASUREMENTS |
| Qualified physical limits and wear procedure | PENDING REVIEW |
| Frozen rubric revision/date/owner/reviewer | NOT YET FROZEN |
| Captured/scored footage and measured results | UNVERIFIED; later Stage 1 |

Package 0.5 closes only after the rubric is accepted/frozen with reviewed
physical procedure, not when later recorder performance happens to pass.
