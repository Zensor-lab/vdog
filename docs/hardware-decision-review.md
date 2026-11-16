# XIAO ESP32S3 Sense and 32GB decision review

Reviewed 2026-11-16. The active board/card replace the earlier classic
AI-Thinker ESP32-CAM/128GB baseline. This is a documentation/source review;
no vdog firmware build, upload, card, runtime or wearable test has run.

## 1. Confirmed direction

Use **Seeed Studio XIAO ESP32S3 Sense**, including its Sense expansion board,
and **32GB FAT32 first**. Keep the nominal **3.7V 1000mAh removable protected
pack**, approximately **1–2h per charge**, mainly SD recording and Wi-Fi enabled
through physical local access. Camera type is the acquired unit's sensor, not
an assumed OV2640 replacement part.

Remove the whole camera from the harness, unplug the pack and charge it using
a compatible external charger. The first fit subject is the owner's dog
reported below 8kg, using a chest harness in dry weather. A basic protective
case precedes wear; weather sealing and larger-dog fit require later validation.
China procurement and required-kit BOM <CNY150 excluding SD/harness, including
external charger, remain unquoted goals.

## 2. PlatformIO conclusion

**Yes: upstream PlatformIO officially lists this XIAO base-board target with
both ESP-IDF and Arduino support**, using `board = seeed_xiao_esp32s3`. Keep the
ESP-IDF C++ proposal. Official platform 8.0.0 is a candidate for package 0.2;
no vdog build has qualified it yet. The manifest's Arduino memory/partition
settings are not ESP-IDF configuration. The Sense camera, octal PSRAM, SPI SD,
USB and signed OTA still need explicit setup and tests.

See [PlatformIO support](platformio-support.md) for the candidate configuration,
versioned primary sources and remaining build/hardware acceptance.

## 3. Board-specific changes

| Topic | Active baseline | Gate |
| --- | --- | --- |
| MCU/memory | XIAO ESP32S3 Sense, documented 8MB flash/8MB PSRAM | Detect actual memory; do not copy classic 4MB, N16R8 16MB or Plus assumptions |
| Camera | Current Seeed transition may ship fixed-focus OV5640 or OV3660; OV2640 historical | Sensor/revision/lens inventory and pinned driver; VGA/SVGA tests, not 5MP performance claims |
| Storage | Sense SPI socket, genuine 32GB SDHC FAT32 | Actual CS/revision/LED sharing, latency, allocated bytes, recovery/rollover |
| Microphone | Hardware is present, audio recording remains excluded | Do not initialize an audio capture pipeline |
| Power | Reviewed removable pack connection to XIAO BAT input and onboard regulation | Onboard charger exists; external-charge policy and USB/pack isolation remain |
| Networking | Radio-off default, physical timed access, one TLS connection initially | Recorder/heap/power concurrency measured before expansion |
| OTA | Signed two-slot update and rollback in actual flash | Binary/partition sizing and real fault tests, not automatic success from 8MB |

The current [Seeed guide](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)
and [Sense card guide](https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/)
are hardware-family references; reconcile the acquired base/expansion revisions.
The card socket is not the old SDMMC slot. GPIO21 CS/user-LED interaction means
an independent heartbeat blink must not toggle the active card-select line.

## 4. 32GB retention consequence

The 72h recorded-footage goal is retained but **unverified on 32GB**. Nominal
capacity arithmetic, before actual allocation/active-bundle headroom:

```text
32000000000 bytes * 0.85 recording pool = 27200000000 bytes
72h = 259200 seconds
27200000000 * 8 / 259200 = 839506.17 bit/s total recording ceiling
with 2000000000 protected bytes inside pool:
25200000000 * 8 / 259200 = 777777.78 bit/s
```

Proposed capacity screening target: ≤0.75Mbit/s total allocated recording growth,
including indexes/manifests/catalog. At 15fps that is only 6,250 bytes per frame
including overhead; useful high-motion JPEG may not fit. At that rate 72h uses
24.3GB, leaving 0.9GB of the pool after full 2GB event protection, before complete
bundle headroom. This is a narrow feasibility margin, not a supported profile.

At 1/2/3Mbit/s, the nominal unprotected pool holds about 60.4/30.2/20.1h before
headroom. Report actual useful captured duration; no silent FPS/resolution/
quality reduction and no fixed 72h UI claim. If agreed image usefulness and
72h cannot coexist, return measured alternatives for an explicit decision.
Larger cards are future qualification; 128GB is not the current requirement.
A working 32GB loop recorder does not by itself pass the 72h criterion.

## 5. Battery and charging policy

The prior stock-board 5V boost proposal is superseded. Review the actual XIAO
BAT+/BAT− circuit, pack limits, keyed service connector, switch/shutdown,
undervoltage behavior and onboard regulation. Do not add a boost stage solely
because the previous board required it. Native USB-C can power/program this
board and can also charge a connected pack through onboard hardware: unplug
the pack before USB service unless an isolation procedure is reviewed.
Firmware cannot make that physical charger disappear.

Runtime remains a measured gate. For a simple battery-side sensitivity example:

```text
nominal battery energy = 3.7V * 1.0Ah = 3.7Wh
hypothetical usable battery energy = 3.7Wh * 0.80 = 2.96Wh
runtime_hours = 2.96Wh / measured_average_battery_input_power_W
```

Hypothetical battery-side loads of 1/1.5/2W imply about 2.96/1.97/1.48h.
The 80% allowance is assumed, not measured. Battery-input power includes all
board/converter losses; do not multiply an extra 85% conversion factor on top.
If measuring a downstream load instead, record the applicable efficiency and
apply it once. Neither examples nor advertised low-power sleep prove recording
runtime. Proposed minimum is 1h, target 2h, with actual conditions disclosed.

A 72h history may accumulate across charging cycles. Unpowered time is a coverage
gap and cannot count as recording. Validate abrupt disconnect/reconnect and
media recovery; use an approved shutdown action when available, without assuming
there is enough energy to flush after unplugging. Charge only the disconnected
pack off-harness using the matched external charger.

## 6. Work still needed

- Inventory base/Sense revisions, sensor, antenna, pack/connector and genuine
  32GB card. Approve the pin map/control/USB isolation before physical use.
- Pin a compatible platform/SDK/compiler/camera release and produce a clean build;
  then authorize and perform detection/camera/SPI SD/OTA tests on an identified unit.
- Measure image usefulness, gaps/FPS, SPI stalls, allocated growth, heap/PSRAM,
  current peaks, runtime and enclosed heat. Preserve original recordings.
- Obtain current CN quotes for the complete Sense assembly and required kit;
  the prior classic-board allocation is not evidence of this board's price.
- Obtain exact dog/chest/harness measurements for final mount/CAD and dry-use
  wear signoff; these do not block software contracts or desk recording tests.

Media/API v1 remain JPEG/index-based and independent of sensor/board name.
The draft device protection ceiling changes to 2GB for the smaller card; backend
storage quotas remain separately configured. Stage 0 is still incomplete.
