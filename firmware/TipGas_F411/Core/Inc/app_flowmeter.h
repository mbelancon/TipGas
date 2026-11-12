/**
 * app_flowmeter.h
 * TipGas - medidor de vazao/volume de gas por tipping-bucket, 9 canais (Black Pill STM32F411)
 *
 * Camada de aplicacao: deteccao dos basculamentos (EXTI + confirmacao + bloqueio),
 * registro de eventos com carimbo de tempo, protocolo USB CDC (texto) e sensor
 * ambiental opcional (BME280/BMP280 no I2C1).
 */
#ifndef APP_FLOWMETER_H
#define APP_FLOWMETER_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

#define FM_FW_VERSION        "1.0.0"
#define FM_NUM_CHANNELS      9U

/* Tempo minimo entre dois basculamentos aceitos no mesmo canal (ms). Ajustavel por comando DEB. */
#define FM_DEFAULT_LOCKOUT_MS   2000U
/* Tempo apos a borda em que o pino precisa continuar no nivel ativo para o evento ser aceito (ms). */
#define FM_CONFIRM_MS           3U
/* Polaridade padrao: bit n = 1 -> canal n+1 ativo em nivel ALTO; 0 -> ativo em nivel BAIXO.
   Ajustavel pelo comando POL e gravada na flash junto com o tempo de bloqueio. */
#define FM_DEFAULT_POL_MASK     0x000U
/* Configuracao persistente no setor 5 da flash (128 KB em 0x08020000). Esse setor existe tanto no
   STM32F411CEU6 (512 KB) quanto no STM32F411CCU6 (256 KB); o programa ocupa so os primeiros ~26 KB. */
#define FM_CFG_FLASH_SECTOR     FLASH_SECTOR_5
#define FM_CFG_FLASH_ADDR       0x08020000UL
/* Numero de eventos guardados para reenvio (comando GET). Potencia de 2. */
#define FM_EVENT_LOG_SIZE       2048U
/* Periodo das mensagens de estado (ms) e das leituras ambientais (ms). */
#define FM_STATUS_PERIOD_MS     1000U
#define FM_ENV_PERIOD_MS        5000U
/* Periodo de leitura dos DS18B20 (ms): a interface usa a leitura mais recente no instante de cada basculamento. */
#define FM_DS_PERIOD_MS         2000U

void     FM_Init(void);                 /* chamar apos MX_*_Init() */
void     FM_Process(void);              /* chamar continuamente no laco principal */
void     FM_OnExti(uint16_t gpio_pin);  /* chamar de HAL_GPIO_EXTI_Callback */
uint64_t FM_Millis(void);               /* tempo desde o boot em ms (64 bits, nao estoura) */

/* Ganchos da USB (chamados a partir de usbd_cdc_if.c) */
void     FM_UsbRx(const uint8_t *buf, uint32_t len);
void     FM_UsbLineState(uint8_t dtr);

#ifdef __cplusplus
}
#endif

#endif /* APP_FLOWMETER_H */
