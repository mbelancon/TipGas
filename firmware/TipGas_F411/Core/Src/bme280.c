/**
 * bme280.c - driver minimo para BME280 / BMP280 (formulas de compensacao do datasheet Bosch)
 */
#include "bme280.h"

#define BME_TIMEOUT_MS 20U

static uint8_t rd(BME280_t *d, uint8_t reg, uint8_t *buf, uint16_t n)
{
  return HAL_I2C_Mem_Read(d->hi2c, d->addr, reg, I2C_MEMADD_SIZE_8BIT, buf, n, BME_TIMEOUT_MS) == HAL_OK;
}

static uint8_t wr(BME280_t *d, uint8_t reg, uint8_t val)
{
  return HAL_I2C_Mem_Write(d->hi2c, d->addr, reg, I2C_MEMADD_SIZE_8BIT, &val, 1, BME_TIMEOUT_MS) == HAL_OK;
}

static uint8_t probe(BME280_t *d, uint16_t addr7)
{
  uint8_t id = 0;
  d->addr = (uint16_t)(addr7 << 1);
  if (HAL_I2C_IsDeviceReady(d->hi2c, d->addr, 2, BME_TIMEOUT_MS) != HAL_OK) return 0;
  if (!rd(d, 0xD0, &id, 1)) return 0;
  if (id != 0x60 && id != 0x58) return 0;
  d->chip_id = id;
  return 1;
}

uint8_t BME280_Init(BME280_t *d, I2C_HandleTypeDef *hi2c)
{
  uint8_t c[26];
  d->hi2c = hi2c;
  d->present = 0;
  if (!probe(d, 0x76) && !probe(d, 0x77)) return 0;

  wr(d, 0xE0, 0xB6);            /* soft reset */
  HAL_Delay(5);

  if (!rd(d, 0x88, c, 26)) return 0;
  d->T1 = (uint16_t)(c[1] << 8 | c[0]);  d->T2 = (int16_t)(c[3] << 8 | c[2]);  d->T3 = (int16_t)(c[5] << 8 | c[4]);
  d->P1 = (uint16_t)(c[7] << 8 | c[6]);  d->P2 = (int16_t)(c[9] << 8 | c[8]);  d->P3 = (int16_t)(c[11] << 8 | c[10]);
  d->P4 = (int16_t)(c[13] << 8 | c[12]); d->P5 = (int16_t)(c[15] << 8 | c[14]); d->P6 = (int16_t)(c[17] << 8 | c[16]);
  d->P7 = (int16_t)(c[19] << 8 | c[18]); d->P8 = (int16_t)(c[21] << 8 | c[20]); d->P9 = (int16_t)(c[23] << 8 | c[22]);
  d->H1 = c[25];

  if (d->chip_id == 0x60) {
    uint8_t h[7];
    if (!rd(d, 0xE1, h, 7)) return 0;
    d->H2 = (int16_t)(h[1] << 8 | h[0]);
    d->H3 = h[2];
    d->H4 = (int16_t)(((int16_t)(int8_t)h[3] << 4) | (h[4] & 0x0F));
    d->H5 = (int16_t)(((int16_t)(int8_t)h[5] << 4) | (h[4] >> 4));
    d->H6 = (int8_t)h[6];
    wr(d, 0xF2, 0x01);          /* umidade x1 (precisa vir antes de 0xF4) */
  }
  wr(d, 0xF5, (5U << 5));        /* standby 1000 ms, filtro desligado */
  wr(d, 0xF4, (1U << 5) | (1U << 2) | 0x03); /* T x1, P x1, modo normal */
  d->present = 1;
  return 1;
}

uint8_t BME280_Read(BME280_t *d, int32_t *t_centi_c, uint32_t *p_pa, int32_t *rh_milli)
{
  uint8_t b[8];
  if (!d->present) return 0;
  if (!rd(d, 0xF7, b, (d->chip_id == 0x60) ? 8 : 6)) return 0;

  int32_t adc_P = (int32_t)(((uint32_t)b[0] << 12) | ((uint32_t)b[1] << 4) | (b[2] >> 4));
  int32_t adc_T = (int32_t)(((uint32_t)b[3] << 12) | ((uint32_t)b[4] << 4) | (b[5] >> 4));
  if (adc_T == 0x80000) return 0;

  /* temperatura */
  int32_t v1 = ((((adc_T >> 3) - ((int32_t)d->T1 << 1))) * ((int32_t)d->T2)) >> 11;
  int32_t v2 = (((((adc_T >> 4) - ((int32_t)d->T1)) * ((adc_T >> 4) - ((int32_t)d->T1))) >> 12) * ((int32_t)d->T3)) >> 14;
  d->t_fine = v1 + v2;
  *t_centi_c = (d->t_fine * 5 + 128) >> 8;

  /* pressao (64 bits) */
  int64_t p1 = ((int64_t)d->t_fine) - 128000;
  int64_t p2 = p1 * p1 * (int64_t)d->P6;
  p2 = p2 + ((p1 * (int64_t)d->P5) << 17);
  p2 = p2 + (((int64_t)d->P4) << 35);
  p1 = ((p1 * p1 * (int64_t)d->P3) >> 8) + ((p1 * (int64_t)d->P2) << 12);
  p1 = (((((int64_t)1) << 47) + p1)) * ((int64_t)d->P1) >> 33;
  if (p1 == 0) return 0;
  int64_t p = 1048576 - adc_P;
  p = (((p << 31) - p2) * 3125) / p1;
  p1 = (((int64_t)d->P9) * (p >> 13) * (p >> 13)) >> 25;
  p2 = (((int64_t)d->P8) * p) >> 19;
  p = ((p + p1 + p2) >> 8) + (((int64_t)d->P7) << 4);
  *p_pa = (uint32_t)(p / 256);

  /* umidade */
  if (d->chip_id == 0x60) {
    int32_t adc_H = (int32_t)(((uint32_t)b[6] << 8) | b[7]);
    int32_t x = d->t_fine - ((int32_t)76800);
    x = (((((adc_H << 14) - (((int32_t)d->H4) << 20) - (((int32_t)d->H5) * x)) + ((int32_t)16384)) >> 15) *
         (((((((x * ((int32_t)d->H6)) >> 10) * (((x * ((int32_t)d->H3)) >> 11) + ((int32_t)32768))) >> 10) +
            ((int32_t)2097152)) * ((int32_t)d->H2) + 8192) >> 14));
    x = (x - (((((x >> 15) * (x >> 15)) >> 7) * ((int32_t)d->H1)) >> 4));
    x = (x < 0) ? 0 : x;
    x = (x > 419430400) ? 419430400 : x;
    *rh_milli = (int32_t)(((uint32_t)(x >> 12)) * 1000U / 1024U);
  } else {
    *rh_milli = -1;
  }
  return 1;
}
