# Changelog

## 1.0.0 — 2026-11-12

First public release.

- Firmware for STM32F411 Black Pill: 9 Hall channels with edge interrupt, 3 ms confirmation and configurable lockout (default 2000 ms); per-channel polarity; 2048-event buffer with recovery (`GET`); settings in flash; DS18B20 probes on a 1-Wire bus (PB8) read every 2 s; optional BME280/BMP280; USB CDC text protocol.
- Desktop app: 3×3 live graphs of cumulative volume or flow with pan/zoom/autoscale; event recovery and board-restart handling; temperature and pressure stamped on every tip; correction to calibration conditions (Antoine water-vapour term) or STP dry/wet; calibration assistant; one two-column CSV per sensor plus full details; export at regular intervals; event log; simulation mode; English and Portuguese interface.
- Windows portable build (no Python installation required).
