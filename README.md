# ESP32-S3 sketches

Small Arduino sketches for a generic ESP32-S3 dev board. Each sketch is its own folder. Flash one at a time.

Shared parts on this board:

| Part | GPIO |
| --- | --- |
| RGB LED | 48 |
| Fallback single LED | 2 |
| BOOT button | 0 |
| Passive buzzer | 42, other leg to GND. Used by BuzzerMelody and AgentLamp. |

Serial is 115200. Board package is `esp32:esp32:esp32s3`.

## Sketches

| Sketch | What it does |
| --- | --- |
| [AgentLamp](AgentLamp/README.md) | BLE desk lamp. The RGB LED shows whether Cursor, CodeBuddy, or Codex is working, has failed, or is waiting on you. Design, protocol, and setup are in that folder’s README. |
| [DiscoOracle](DiscoOracle/DiscoOracle.ino) | USB fortune teller. Serial: `?` prophecy, `d` disco, `q` quiet glow. |
| [USBSuperpowers](USBSuperpowers/USBSuperpowers.ino) | Native USB keyboard, mouse, and MIDI at the same time as the serial port. Serial: `k` keyboard, `m` mouse, `n` MIDI, `h` help. BOOT plays all three. The sketch comments require USB-OTG (TinyUSB), not the default CDC upload mode. |
| [BuzzerMelody](BuzzerMelody/BuzzerMelody.ino) | Plays the Tetris theme on the passive buzzer. Serial: `p` play, `l` loop, `h` help. BOOT replays. The RGB LED flashes with each note. |

## Flash

From this directory, with [arduino-cli](https://arduino.github.io/arduino-cli/) and the ESP32 core installed:

```bash
arduino-cli compile --fqbn "esp32:esp32:esp32s3:USBMode=default,CDCOnBoot=cdc,UploadMode=cdc,UploadSpeed=921600" AgentLamp
arduino-cli upload -p /dev/cu.usbmodemXXXX --fqbn "esp32:esp32:esp32s3:USBMode=default,CDCOnBoot=cdc,UploadMode=cdc,UploadSpeed=921600" AgentLamp
```

Replace `AgentLamp` with `DiscoOracle`, `USBSuperpowers`, or `BuzzerMelody`. The modem port comes from `ls /dev/cu.usbmodem*`.
