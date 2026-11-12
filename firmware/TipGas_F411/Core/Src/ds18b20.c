/**
 * ds18b20.c - 1-Wire bit-bang no pino ONEWIRE (open-drain) + DS18B20
 *
 * Temporizacao padrao do 1-Wire (Maxim AN126), atrasos com o contador de ciclos DWT.
 * Cada janela de bit (~70 us) roda com interrupcoes desligadas; entre os bits elas ficam ligadas,
 * entao a contagem dos basculamentos (EXTI) e a USB continuam funcionando normalmente.
 */
#include "ds18b20.h"
#include "main.h"

#define OW_PORT  ONEWIRE_GPIO_Port
#define OW_PIN   ONEWIRE_Pin

/* ------------------------------------------------------------------ atrasos em microssegundos */
static uint32_t s_cyc_per_us = 96;

void DS_Init(void)
{
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
  s_cyc_per_us = SystemCoreClock / 1000000U;
  OW_PORT->BSRR = OW_PIN;                         /* linha solta (nivel alto pelo pull-up) */
}

static inline void delay_us(uint32_t us)
{
  uint32_t start = DWT->CYCCNT;
  uint32_t ticks = us * s_cyc_per_us;
  while ((DWT->CYCCNT - start) < ticks) { }
}

static inline void ow_low(void)     { OW_PORT->BSRR = (uint32_t)OW_PIN << 16U; }
static inline void ow_release(void) { OW_PORT->BSRR = OW_PIN; }
static inline uint8_t ow_read(void) { return (OW_PORT->IDR & OW_PIN) ? 1U : 0U; }

/* ------------------------------------------------------------------ camada de bits */
static uint8_t ow_reset(void)
{
  uint8_t presence;
  ow_low();
  delay_us(480);
  uint32_t pm = __get_PRIMASK();
  __disable_irq();
  ow_release();
  delay_us(70);
  presence = (ow_read() == 0U);
  __set_PRIMASK(pm);
  delay_us(410);
  return presence;
}

static void ow_write_bit(uint8_t b)
{
  uint32_t pm = __get_PRIMASK();
  __disable_irq();
  ow_low();
  if (b) { delay_us(6);  ow_release(); delay_us(64); }
  else   { delay_us(60); ow_release(); delay_us(10); }
  __set_PRIMASK(pm);
}

static uint8_t ow_read_bit(void)
{
  uint8_t b;
  uint32_t pm = __get_PRIMASK();
  __disable_irq();
  ow_low();
  delay_us(6);
  ow_release();
  delay_us(9);
  b = ow_read();
  __set_PRIMASK(pm);
  delay_us(55);
  return b;
}

static void ow_write_byte(uint8_t v)
{
  for (uint8_t i = 0; i < 8; i++) { ow_write_bit(v & 1U); v >>= 1; }
}

static uint8_t ow_read_byte(void)
{
  uint8_t v = 0;
  for (uint8_t i = 0; i < 8; i++) { if (ow_read_bit()) v |= (uint8_t)(1U << i); }
  return v;
}

static uint8_t crc8(const uint8_t *d, uint8_t n)
{
  uint8_t crc = 0;
  while (n--) {
    uint8_t in = *d++;
    for (uint8_t i = 0; i < 8; i++) {
      uint8_t mix = (crc ^ in) & 0x01U;
      crc >>= 1;
      if (mix) crc ^= 0x8CU;
      in >>= 1;
    }
  }
  return crc;
}

/* ------------------------------------------------------------------ busca de ROM (Maxim AN187) */
uint8_t DS_Search(ds_sensor_t *list, uint8_t max)
{
  uint8_t rom[8] = {0};
  int last_discrepancy = -1;
  uint8_t found = 0;
  uint8_t done = 0;

  while (!done && found < max) {
    if (!ow_reset()) return found;
    ow_write_byte(0xF0);                          /* SEARCH ROM */
    int last_zero = -1;
    for (int bit = 0; bit < 64; bit++) {
      uint8_t b = ow_read_bit();
      uint8_t cb = ow_read_bit();
      uint8_t dir;
      if (b && cb) return found;                  /* ninguem respondeu */
      if (b != cb) {
        dir = b;
      } else {                                    /* discrepancia: ha sensores com 0 e com 1 aqui */
        if (bit < last_discrepancy)       dir = (rom[bit / 8] >> (bit % 8)) & 1U;
        else if (bit == last_discrepancy) dir = 1;
        else                              dir = 0;
        if (dir == 0) last_zero = bit;
      }
      if (dir) rom[bit / 8] |= (uint8_t)(1U << (bit % 8));
      else     rom[bit / 8] &= (uint8_t)~(1U << (bit % 8));
      ow_write_bit(dir);
    }
    last_discrepancy = last_zero;
    if (last_discrepancy < 0) done = 1;
    if (crc8(rom, 7) == rom[7] && rom[0] == 0x28) {   /* familia 0x28 = DS18B20 */
      for (uint8_t i = 0; i < 8; i++) list[found].rom[i] = rom[i];
      list[found].valid = 0;
      list[found].t_centi = 0;
      found++;
    }
  }
  return found;
}

uint8_t DS_StartConversion(void)
{
  if (!ow_reset()) return 0;
  ow_write_byte(0xCC);                            /* SKIP ROM: todos os sensores */
  ow_write_byte(0x44);                            /* CONVERT T */
  return 1;
}

uint8_t DS_ReadTemp(ds_sensor_t *s)
{
  uint8_t sp[9];
  if (!ow_reset()) { s->valid = 0; return 0; }
  ow_write_byte(0x55);                            /* MATCH ROM */
  for (uint8_t i = 0; i < 8; i++) ow_write_byte(s->rom[i]);
  ow_write_byte(0xBE);                            /* READ SCRATCHPAD */
  for (uint8_t i = 0; i < 9; i++) sp[i] = ow_read_byte();
  if (crc8(sp, 8) != sp[8]) { s->valid = 0; return 0; }
  int16_t raw = (int16_t)((uint16_t)sp[1] << 8 | sp[0]);
  if (raw == 0x0550) { s->valid = 0; return 0; }  /* 85,0 °C = valor de power-on (sem conversao) */
  s->t_centi = ((int32_t)raw * 100) / 16;         /* 12 bits: 1/16 °C por LSB */
  s->valid = 1;
  return 1;
}

void DS_RomToHex(const uint8_t rom[8], char out[17])
{
  static const char hx[] = "0123456789ABCDEF";
  for (uint8_t i = 0; i < 8; i++) {
    out[2 * i]     = hx[rom[i] >> 4];
    out[2 * i + 1] = hx[rom[i] & 0x0F];
  }
  out[16] = 0;
}
