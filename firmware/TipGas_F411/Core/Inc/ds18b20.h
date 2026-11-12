/**
 * ds18b20.h - barramento 1-Wire (bit-bang) com varios sensores DS18B20
 *
 * Ligacao: DQ de todos os sensores no pino ONEWIRE (PB8), com resistor de 4,7 kOhm de DQ para 3,3 V.
 * Sensores alimentados (VDD = 3,3 V, GND); o modo parasita nao e suportado.
 * Os sensores sao identificados pelo codigo ROM de 64 bits, gravado de fabrica.
 */
#ifndef DS18B20_H
#define DS18B20_H

#include <stdint.h>

#define DS_MAX_SENSORS   12U

typedef struct {
  uint8_t  rom[8];
  int32_t  t_centi;        /* ultima temperatura em centesimos de grau C */
  uint8_t  valid;          /* 1 se a ultima leitura passou no CRC */
} ds_sensor_t;

void     DS_Init(void);                       /* habilita o contador de ciclos (DWT) para os atrasos em us */
uint8_t  DS_Search(ds_sensor_t *list, uint8_t max);   /* procura sensores; retorna quantos achou */
uint8_t  DS_StartConversion(void);            /* todos convertem ao mesmo tempo (750 ms em 12 bits) */
uint8_t  DS_ReadTemp(ds_sensor_t *s);         /* le o resultado de um sensor; 1 = ok (CRC valido) */
void     DS_RomToHex(const uint8_t rom[8], char out[17]);

#endif /* DS18B20_H */
