# ESP32-CAM and 1000mAh battery decision review

Reviewed 2026-11-09. This supersedes the earlier S3 prototype direction; the
replacement has not passed bench, storage, runtime or wearable tests.

## 1. Confirmed direction and recommendation

The owner selected **classic AI-Thinker ESP32-CAM + OV2640**, a nominal **3.7V
1000mAh single-cell battery**, approximately **1–2 hours per charge**, and
**mainly SD recording, enabling Wi-Fi when needed**. The 128GB card priority,
72-hour recorded-footage retention target and sub-CNY150 base-hardware target
remain unchanged. Exact PCB revision, supplier, pack SKU and power assembly
still need qualification.

The owner also confirmed external battery charging after removing the complete
camera from the harness and unplugging the pack; no onboard charging is needed.
Initial fit is a chest harness on the owner's dog, weighing below 8kg. Dry
weather is the first scope; weather protection comes later. This is not a claim
of suitability for every dog below 8kg or automatic fit on larger dogs.

Recommendation: use this as the first low-cost recorder prototype. Integrated
camera/card connections simplify assembly, while the older board offers less
flash margin than N16R8. The S3 pin map, 16MB/8MB expectation and build settings
are superseded, not configuration defaults for this board.

## 2. Changes and remaining gates

| Topic | New baseline | Remaining evidence |
| --- | --- | --- |
| MCU/camera | Original ESP32, classic ESP32-CAM, OV2640 JPEG | PCB/chip revision, lens, useful FPS/image quality |
| Memory | PlatformIO describes 4MB flash; legacy vendor spec describes 4MB PSRAM | Actual detected memory, variant and dual-OTA fit |
| Power | Removable protected 3.7V 1000mAh 1S pack and regulation; separate charger | Pack/charger compatibility, peak current, cutoff, keyed connector/polarity, heat |
| Radio | Off by default; physical timed local-access session | Qualified control pin, TLS load, transition/resume behavior |
| Card | 128GB remains first priority | FAT32/card qualification and 72h powered retention soak |
| Updates | Signed dual-slot OTA and rollback remain required for Stage 2 | Real build sizes/partitions; no silent security removal |

[PlatformIO](https://docs.platformio.org/en/latest/boards/espressif32/esp32cam.html)
identifies the original ESP32 and 4MB flash. The manufacturer-authored
[legacy specification mirror](https://lemariva.com/storage/app/media/uploaded-files/ESP32-CAM%20Product%20Specification.pdf)
is historical evidence, not current qualification of every seller's variant.
Its limited published card support neither establishes 128GB support nor proves
128GB impossible. Verify the actual board/card rather than generalizing a label.

## 3. Runtime calculation

Nominal energy is `3.7V × 1.0Ah = 3.7Wh`. For sensitivity analysis only, assume
80% usable capacity before shutdown and 85% conversion efficiency to board input:

```text
energy delivered to board = 3.7Wh × 0.80 × 0.85 = 2.516Wh
runtime_hours = 2.516Wh / measured_average_board_input_power_W
```

| Hypothetical board-input load | Calculated runtime |
| ---: | ---: |
| 0.5W | 5.0h |
| 1.0W | 2.5h |
| 1.5W | 1.7h |
| 2.0W | 1.3h |

These loads and efficiencies are assumptions, not measurements or guarantees.
Measure at the regulated board input; onboard regulator losses are already
included there. Do not omit them from a chip-only load or count them twice.
Under these assumptions, two hours requires average board-input power ≤1.258W.
Age, temperature, pack quality and Wi-Fi use can reduce runtime. Capacity in
mAh does not specify peak-current capability.

Proposed acceptance interpretation of “about 1–2 hours”: demonstrate at least
one hour of useful recording, target two, and publish conditions/results.
Record Wi-Fi-off and qualified Wi-Fi-session cases separately. Deep-sleep time
is not continuous recording. A 72-hour SD history may accumulate over multiple
charges; it does not imply three days per charge.

## 4. Power assembly

The [V1.6 schematic mirror](https://www.olimex.com/Products/IoT/ESP32/ESP32-CAM/resources/ESP32_CAM_V1.6.pdf)
shows a linear regulator and separate camera rails, without a charger. For a
matching stock board, start bench design around its regulated 5V input,
typically supplied by a reviewed boost stage from the pack. Measure the heat
and energy cost of the complete power path.

Do not connect a bare cell directly to 3V3: nominal 3.7V is not regulated 3.3V.
Do not assume that a cell connected to 5V meets the board's requirements across
discharge. A regulated direct-3.3V architecture requires its own regulator,
board and back-feed review.

The camera now needs only the protected pack's discharge path, a reviewed
service connector, switch/shutdown and regulated supply. Select pack protection,
voltage/cutoff limits, discharge rating, polarity/keying, strain relief and peak
margin together. No onboard charger, USB battery charging or load-sharing IC is
required. Programming/bench power is separately reviewed and isolated from the
pack; it must not become an accidental charging path.

Owner procedure: remove the camera from the harness, use its approved power-off
action, unplug the pack and connect it only to a compatible external 1S charger.
Choose that charger's voltage/current for the exact pack. Reconnect the pack to
resume automatic recording. Abrupt unplugging can still occur, so recovery tests
remain required; a final flush is not guaranteed. The required external charger
stays in required-kit costing: the existing budget excludes only SD and harness.

Dry-weather use still needs a basic protective case before wear, insulating and
restraining electronics/pack, securing connectors and providing suitable contact
surfaces. Weather sealing is later work with fresh thermal/ingress validation.
Chest geometry, strap spacing, ground view and movement need actual checks;
small-dog-first is a design priority, not universal larger-dog compatibility.

## 5. Required experiments

1. Verify actual board/pack identity, memory, rails, wiring and polarity.
2. Record to real 128GB FAT32 cards; validate JPEG/index/hash/recovery behavior.
   MCU replacement does not change the nominal ~3.36Mbit/s 72h capacity ceiling
   at an 85% recording pool, before further protection/headroom deductions.
3. Measure image usefulness, delivered FPS/gaps, bytes, SD stalls, current peaks,
   average board-input power, brownouts, heat and runtime.
4. Keep flash lamp off for baseline recording. Low-light blur remains a quality
   gate, not something to hide to achieve runtime/capacity numbers.
5. Qualify TLS+camera+SD before preview/download concurrency. Do not copy the
   S2/S3-only PSRAM-DMA setting onto original ESP32.
6. Prove two signed OTA slots and rollback fit; single-large-app partitions do
   not satisfy that requirement. Request a scope decision if they cannot fit.
7. Qualify enclosure/mount/power before wear and collect China quotes before a
   production-cost claim.

References: [camera driver](https://github.com/espressif/esp32-camera),
[PlatformIO manifest](https://github.com/platformio/platform-espressif32/blob/develop/boards/esp32cam.json),
[ESP-IDF OTA](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/ota.html).

## 6. Decisions still needed

- Exact board supplier/revision and pack SKU, dimensions, mass, protection,
  discharge rating and connector.
- Compatible external charger and removable connector/regulator assembly.
  External charging is settled; recording while charging is outside v1.
- Actual dog weight/chest/harness measurements before final mount/CAD and field
  signoff; these do not block host development or bench recording.
- Supported image profile after quality/rate/runtime measurement.
- Response if retention or signed OTA fails: explicitly revise scope, select
  a qualified larger-memory board, or return to S3 with owner direction.

Media/API and Flutter/Rust boundaries remain v1. Board configuration, runtime
tests, Wi-Fi policy and capability reporting change together. No purchase,
hardware operation or application implementation occurred during this review.
