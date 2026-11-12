/**
 * bme280.h - driver minimo para BME280 / BMP280 via HAL I2C
 * Usado para corrigir os volumes de gas para condicoes padrao (temperatura e pressao).
 */
#ifndef BME280_H
#define BME280_H

#include "stm32f4xx_hal.h"
#include <stdint.h>

typedef struct {
  I2C_HandleTypeDef *hi2c;
  uint16_t addr;        /* endereco de 8 bits (0x76<<1 ou 0x77<<1) */
  uint8_t  chip_id;     /* 0x60 = BME280, 0x58 = BMP280 */
  uint8_t  present;
  /* calibracao */
  uint16_t T1; int16_t T2, T3;
  uint16_t P1; int16_t P2, P3, P4, P5, P6, P7, P8, P9;
  uint8_t  H1, H3; int16_t H2, H4, H5; int8_t H6;
  int32_t  t_fine;
} BME280_t;

/* Procura o sensor em 0x76 e 0x77. Retorna 1 se encontrado. */
uint8_t BME280_Init(BME280_t *dev, I2C_HandleTypeDef *hi2c);

/* Le temperatura (centesimos de grau C), pressao (Pa) e umidade (milesimos de %UR; -1 se BMP280).
   Retorna 1 em caso de sucesso. */
uint8_t BME280_Read(BME280_t *dev, int32_t *t_centi_c, uint32_t *p_pa, int32_t *rh_milli);

#endif /* BME280_H */
