# Plane Radar — Firmware Releases

Official firmware updates for **Plane Radar** devices (ESP32-S3, 3.5" touch display).

This repository contains only signed firmware binaries. Devices check here
automatically once a day and install updates on their own — no action needed.
You can also trigger a check manually on the device under
**Settings → System → Check for update**.

Each release contains:

| File | Purpose |
|---|---|
| `firmware.bin` | The firmware image |
| `firmware.sig` | ECDSA P-256 signature — devices verify this before installing |

Devices refuse any image whose signature does not verify, so only releases
published here by the author will ever install.

## License

Copyright © 2026 Raoul Woodruff & Lockline Studio LTD. All rights reserved.

This firmware is provided solely for updating genuine Plane Radar devices.
Copying, redistribution, modification, or installation on other hardware is
not permitted. No license, express or implied, is granted by the availability
of these files.

## Third-party components

This firmware is built with open-source components, used under their
respective licenses: ESP-IDF / Arduino-ESP32 (Apache-2.0), LovyanGFX (MIT),
WiFiManager (MIT), ArduinoJson (MIT), mbedTLS (Apache-2.0).
