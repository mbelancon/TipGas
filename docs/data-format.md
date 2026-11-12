# Data format

File and column names are the same in both interface languages (they are in Portuguese, as in the original lab protocol), so scripts that read them work regardless of the language chosen.

## Experiment folder

Each recording (**▶ Start**) creates `YYYYMMDD_HHMMSS_<name>` inside the folder chosen in **Save to** (default `Documents/TipGas`).

| File | Contents |
|---|---|
| `S1_<channel name>.csv` … `S9_<…>.csv` | **One file per sensor with two columns: time and volume** |
| `detalhes/basculamentos.csv` | Every tip of every sensor with all details (below). The app reopens and recomputes experiments from this file |
| `detalhes/temperaturas_ds18b20.csv` | All DS18B20 readings (every 2 s): `data_hora`, `t_h`, `sensor` (probe code), `T_C` |
| `ambiente.csv` | BME280/BMP280 every 5 s: `data_hora`, `t_h`, `T_C`, `P_Pa`, `UR_pct` (relative humidity, −1 on BMP280) |
| `config.json` | Experiment name, start/end; name, k, polarity and temperature probe of each channel; correction mode, T_ref, P_ref; file of each channel |
| `registro.log` | Events during the recording (connections, MCU restarts, sensors found, warnings) |

Outside experiment folders:

- `registro/registro_YYYY-MM-DD.log` — daily event log, also when not recording;
- `calibracoes/calibracao_YYYYMMDD_HHMMSS.csv` — each calibration applied.

Files of active channels are created when the recording starts, even before the first tip. The file name uses the channel name at that moment.

## Sensor files `S<n>_….csv`

One row per tip of that channel:

| Column | Meaning |
|---|---|
| `tempo_h` | Time since the start of the recording, hours |
| `volume_mL` | Cumulative gas volume up to that tip, mL (V = k · ΣFᵢ with the correction chosen when the recording started; V = n · k without correction) |

## `detalhes/basculamentos.csv`

| Column | Meaning |
|---|---|
| `data_hora` | Date and time of the tip (PC clock mapped from the board clock, ms precision) |
| `t_h` | Hours since the start of the recording |
| `canal` | Channel 1–9 (= S1–S9) |
| `nome` | Channel name |
| `n` | Cumulative tip count of this channel |
| `T_C` | Temperature recorded at the tip, °C (assigned DS18B20, else BME280) |
| `fonte_T` | Source of `T_C`: 16-hex-digit DS18B20 code or `BME280` |
| `P_kPa` | Ambient pressure at the tip (empty without BME280) |
| `k_mL` | Calibration factor, mL per tip |
| `F_i` | Correction factor of this tip (1 without correction or temperature) |
| `V_mL` | Cumulative uncorrected volume, n · k |
| `V_cor_mL` | Cumulative corrected volume, k · ΣFᵢ |
| `sessao`, `seq`, `contagem_mcu`, `t_mcu_ms` | Board bookkeeping: session (changes if the board restarts), event number, board's count for the channel, board time in ms |

To recompute with other k values or another correction: **Data → Open saved experiment…**, change FC and/or the correction, then export again.

## Exports (menu *Data*)

| Export | File | Contents |
|---|---|---|
| Time and volume (one file per sensor) | `volume_S1_<name>.csv` … (prefix `volume` follows the interface language) | `tempo_h`, `volume_<unit>`, recomputed with the current k and correction, using the temperature recorded at each tip |
| Table at regular intervals | `resultado_<unit>.csv` | `t_h`, then `V<n>_<unit> (<name>)` and `Q<n>_<unit>_por_h (<name>)` for all channels every N minutes |

`<unit>`: `mL` (no correction), `mL_Tref25C` (calibration conditions at 25 °C), `mL_CNTP_seco` / `mL_CNTP_umido` (STP dry / wet; CNTP = STP in Portuguese).

## Settings file

`~/.tipgas.json` (Windows: `C:\Users\<user>\.tipgas.json`). Copy it to another PC to take the settings along. Settings from the pre-release name (`.medidor_vazao_gas.json`) are imported automatically on first run.
