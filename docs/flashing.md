# Flashing the firmware

The release contains `TipGas_F411.hex` (and `.bin`). The Black Pill has a USB bootloader (DFU) in ROM, so **no ST-Link is needed**.

## Over USB (DFU) — recommended

1. Install **[STM32CubeProgrammer](https://www.st.com/en/development-tools/stm32cubeprog.html)** (free, Windows/Linux/macOS). It installs the DFU driver on Windows.
2. Connect the Black Pill to the PC with a **data** USB-C cable.
3. Enter the bootloader:
   - press and hold **BOOT0**;
   - press and release **NRST**;
   - release **BOOT0**.

   The board now enumerates as *STM32 BOOTLOADER* (the LED stays off). If it doesn't, repeat holding BOOT0 a little longer, or unplug, hold BOOT0, plug in, release.
4. In STM32CubeProgrammer, choose **USB** in the connection panel (right side), click the refresh icon so a port such as `USB1` appears, then **Connect**.
5. Open **Erasing & Programming** (second icon on the left), browse to `TipGas_F411.hex`, tick **Verify programming** and click **Start Programming**.
6. When it reports success, click **Disconnect** and press **NRST**. The board starts the TipGas firmware and appears as a virtual COM port (*TipGas 9-channel gas meter*).

Command-line alternative:

```bash
STM32_Programmer_CLI -c port=USB1 -w TipGas_F411.hex -v -rst
```

Settings stored in the board (lockout and polarity) are kept in flash sector 5 and are rewritten by the app on the next connection, so re-flashing needs no extra step.

## With an ST-Link (SWD)

Wire SWDIO, SWCLK, GND and 3V3 to the 4-pin header at the end of the board and program the same `.hex` with STM32CubeProgrammer (*ST-LINK* connection) or `make flash`.

## Building from source

The firmware is an **STM32CubeIDE** project generated with STM32CubeMX (HAL + USB Device CDC).

- **STM32CubeIDE:** *File → New → STM32 Project from an Existing STM32CubeMX Configuration File (.ioc)* and choose `firmware/TipGas_F411/TipGas_F411.ioc`, then copy `Core/Src/app_flowmeter.c`, `ds18b20.c`, `bme280.c` and their headers into the new project if CubeIDE did not pick them up. Build with the hammer icon. User code lives in `Core/Src/app_flowmeter.c`, `ds18b20.c` and `bme280.c`, and the hooks in the generated files are inside `USER CODE` sections, so code can be regenerated from the `.ioc`.
- **Command line (Linux/macOS/WSL):** install `arm-none-eabi-gcc` and run

  ```bash
  cd firmware/TipGas_F411
  make            # -> build/TipGas_F411.hex / .bin / .elf
  ```

The linker script reserves 128 KB of flash for the program (sectors 0–4), so the same binary runs on the F411**CE** (512 KB) and F411**CC** (256 KB).
