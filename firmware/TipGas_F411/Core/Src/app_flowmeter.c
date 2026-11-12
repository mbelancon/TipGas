/**
 * app_flowmeter.c
 * TipGas - medidor de vazao/volume de gas por tipping-bucket, 9 canais (Black Pill STM32F411)
 *
 * Deteccao de basculamento
 *   - Sensor Hall digital (ex.: modulo KY-024, saida DO do comparador) ou chave Hall.
 *   - Cada canal tem polaridade configuravel: ativo em nivel BAIXO (padrao) ou ALTO.
 *   - A EXTI dispara nas duas bordas; quando o pino vai para o nivel ativo, registra um
 *     "candidato" com o tempo da borda.
 *   - No laco principal, apos FM_CONFIRM_MS, o pino precisa continuar no nivel ativo
 *     (filtra picos de ruido em cabos longos e oscilacao do comparador).
 *   - Depois de um evento aceito o canal fica bloqueado por lockout_ms (quique mecanico).
 *
 * Protocolo USB CDC (texto ASCII, uma mensagem por linha terminada em '\n')
 *   Dispositivo -> PC
 *     HELLO,TIPGAS,<versao>,<nch>                    ao abrir a porta (DTR)
 *     ID,TIPGAS,<versao>,<uid>,<nch>,<lockout_ms>,<sensor_amb>,<pol_mask>,<n_ds18b20>
 *     EV,<seq>,<canal 1..9>,<contagem_do_canal>,<t_ms>  basculamento detectado
 *     ST,<t_ms>,<prox_seq>,<c1>,...,<c9>               estado, a cada 1 s
 *     ENV,<t_ms>,<T_C>,<P_Pa>,<UR_%>                    ambiente, a cada 5 s (se houver sensor; UR=-1 se BMP280)
 *     TMP,<t_ms>,<i>,<rom>,<T_C>                        DS18B20 no barramento 1-Wire (PB8), a cada 2 s,
 *                                                       um por sensor; <rom> = codigo unico de 16 hex
 *     GETEND,<ultimo_seq_enviado>
 *     LOST,<seq_pedido>,<seq_mais_antigo_disponivel>    eventos ja descartados do buffer
 *     OK,<comando>   /   ERR,<motivo>
 *   PC -> dispositivo
 *     ID?          identificacao
 *     ST?          estado imediato
 *     GET,<seq>    reenvia todos os eventos com numero >= seq que ainda estao no buffer
 *     RST          zera as contagens por canal (a numeracao seq continua)
 *     DEB,<ms>     tempo de bloqueio entre basculamentos (20..10000 ms)
 *     POL,<mask>   polaridade dos canais: bit n = 1 -> canal n+1 ativo em nivel ALTO
 *                  (0..511, decimal). DEB e POL ficam gravados na flash.
 *
 *   t_ms = milissegundos desde o boot do microcontrolador (64 bits).
 *   seq  = numero sequencial global do evento desde o boot (permite recuperar eventos
 *          perdidos quando o PC desconecta, suspende ou o programa e fechado).
 */
#include "app_flowmeter.h"
#include "main.h"
#include "usbd_cdc_if.h"
#include "bme280.h"
#include "ds18b20.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>

extern USBD_HandleTypeDef hUsbDeviceFS;
extern I2C_HandleTypeDef hi2c1;

/* ------------------------------------------------------------------ canais */
typedef struct {
  GPIO_TypeDef *port;
  uint16_t      pin;
} fm_chan_hw_t;

/* Mapeamento definido no .ioc (rotulos HALL1..HALL9 em main.h) */
static const fm_chan_hw_t s_hw[FM_NUM_CHANNELS] = {
  { HALL1_GPIO_Port, HALL1_Pin }, /* PB0  EXTI0 */
  { HALL2_GPIO_Port, HALL2_Pin }, /* PB1  EXTI1 */
  { HALL3_GPIO_Port, HALL3_Pin }, /* PA2  EXTI2 */
  { HALL4_GPIO_Port, HALL4_Pin }, /* PA3  EXTI3 */
  { HALL5_GPIO_Port, HALL5_Pin }, /* PA4  EXTI4 */
  { HALL6_GPIO_Port, HALL6_Pin }, /* PA5  EXTI5 */
  { HALL7_GPIO_Port, HALL7_Pin }, /* PA6  EXTI6 */
  { HALL8_GPIO_Port, HALL8_Pin }, /* PA7  EXTI7 */
  { HALL9_GPIO_Port, HALL9_Pin }, /* PA8  EXTI8 */
};

typedef struct {
  volatile uint8_t  pending;     /* 0 = nada, 1 = candidato aguardando confirmacao, 2 = confirmado */
  volatile uint64_t t_edge;      /* tempo da borda do candidato */
  uint64_t          t_last;      /* tempo do ultimo evento aceito */
  uint8_t           has_last;
  uint32_t          count;       /* contagem desde o boot ou ultimo RST */
} fm_chan_t;

static fm_chan_t s_ch[FM_NUM_CHANNELS];
static volatile uint32_t s_lockout_ms = FM_DEFAULT_LOCKOUT_MS;
static volatile uint32_t s_pol_mask   = FM_DEFAULT_POL_MASK;

/* Nivel do pino indica "ima presente" neste canal? */
static inline uint8_t chan_active(uint32_t i)
{
  GPIO_PinState lv = HAL_GPIO_ReadPin(s_hw[i].port, s_hw[i].pin);
  uint8_t high = (s_pol_mask >> i) & 1U;
  return high ? (lv == GPIO_PIN_SET) : (lv == GPIO_PIN_RESET);
}

/* ------------------------------------------------------------------ configuracao na flash */
#define FM_CFG_MAGIC  0x464D4346UL   /* "FMCF" */
typedef struct {
  uint32_t magic;
  uint32_t lockout_ms;
  uint32_t pol_mask;
  uint32_t check;                    /* ~(magic ^ lockout ^ pol) */
} fm_cfg_t;

static void cfg_load(void)
{
  const fm_cfg_t *c = (const fm_cfg_t *)FM_CFG_FLASH_ADDR;
  if (c->magic != FM_CFG_MAGIC) return;
  if (c->check != ~(c->magic ^ c->lockout_ms ^ c->pol_mask)) return;
  if (c->lockout_ms >= 20U && c->lockout_ms <= 10000U) s_lockout_ms = c->lockout_ms;
  s_pol_mask = c->pol_mask & ((1UL << FM_NUM_CHANNELS) - 1UL);
}

/* Apaga o setor de configuracao (128 KB, ~1-2 s) e grava a configuracao. As interrupcoes continuam ativas:
   as bordas que ocorrerem nesse intervalo ficam como candidatos e sao confirmadas depois. */
static uint8_t cfg_save(void)
{
  const fm_cfg_t *cur = (const fm_cfg_t *)FM_CFG_FLASH_ADDR;
  fm_cfg_t c = { FM_CFG_MAGIC, s_lockout_ms, s_pol_mask, 0 };
  c.check = ~(c.magic ^ c.lockout_ms ^ c.pol_mask);
  if (memcmp(cur, &c, sizeof(c)) == 0) return 1;        /* nada mudou */

  FLASH_EraseInitTypeDef er = {0};
  uint32_t sector_error = 0;
  er.TypeErase    = FLASH_TYPEERASE_SECTORS;
  er.Sector       = FM_CFG_FLASH_SECTOR;
  er.NbSectors    = 1;
  er.VoltageRange = FLASH_VOLTAGE_RANGE_3;
  uint8_t ok = 0;
  HAL_FLASH_Unlock();
  if (HAL_FLASHEx_Erase(&er, &sector_error) == HAL_OK) {
    const uint32_t *w = (const uint32_t *)&c;
    ok = 1;
    for (uint32_t i = 0; i < sizeof(c) / 4U; i++) {
      if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, FM_CFG_FLASH_ADDR + 4U * i, w[i]) != HAL_OK) { ok = 0; break; }
    }
  }
  HAL_FLASH_Lock();
  return ok;
}

/* ------------------------------------------------------------------ tempo */
static volatile uint64_t s_ms64 = 0;

/* Substitui a funcao fraca da HAL: mantem uwTick e um contador de 64 bits */
extern __IO uint32_t uwTick;
extern HAL_TickFreqTypeDef uwTickFreq;
void HAL_IncTick(void)
{
  uwTick += (uint32_t)uwTickFreq;
  s_ms64 += (uint32_t)uwTickFreq;
  /* Confirmacao dos candidatos feita aqui (a cada 1 ms), independente do laco principal:
     mesmo que o laco fique ocupado (ex.: lendo os DS18B20), o nivel e conferido na hora certa. */
  for (uint32_t i = 0; i < FM_NUM_CHANNELS; i++) {
    fm_chan_t *c = &s_ch[i];
    if (c->pending == 1U && (s_ms64 - c->t_edge) >= FM_CONFIRM_MS) {
      c->pending = chan_active(i) ? 2U : 0U;
    }
  }
}

uint64_t FM_Millis(void)
{
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  uint64_t t = s_ms64;
  __set_PRIMASK(primask);
  return t;
}

/* ------------------------------------------------------------------ registro de eventos */
typedef struct {
  uint64_t t_ms;
  uint32_t seq;
  uint32_t count;
  uint8_t  ch;
} fm_event_t;

static fm_event_t s_log[FM_EVENT_LOG_SIZE];
static uint32_t   s_next_seq = 0;          /* proximo numero de evento */

static const fm_event_t *log_get(uint32_t seq)
{
  if (seq >= s_next_seq) return NULL;
  if (s_next_seq - seq > FM_EVENT_LOG_SIZE) return NULL;
  return &s_log[seq & (FM_EVENT_LOG_SIZE - 1U)];
}

static uint32_t log_oldest(void)
{
  return (s_next_seq > FM_EVENT_LOG_SIZE) ? (s_next_seq - FM_EVENT_LOG_SIZE) : 0U;
}

/* ------------------------------------------------------------------ USB TX (fila circular) */
#define TX_RING_SIZE  8192U
#define TX_CHUNK      512U
static uint8_t  s_tx_ring[TX_RING_SIZE];
static uint32_t s_tx_head = 0, s_tx_tail = 0;   /* head: escrita, tail: leitura */
static uint8_t  s_tx_buf[TX_CHUNK];
static volatile uint8_t s_dtr = 0;
static volatile uint8_t s_hello_pending = 0;
static uint32_t s_tx_dropped = 0;

static uint8_t usb_ready(void)
{
  return (hUsbDeviceFS.dev_state == USBD_STATE_CONFIGURED) && s_dtr;
}

static uint32_t tx_free(void)
{
  return TX_RING_SIZE - 1U - ((s_tx_head - s_tx_tail) & (TX_RING_SIZE - 1U));
}

/* Enfileira uma linha inteira (ou nada, se nao couber) */
static void tx_line(const char *s, uint32_t n)
{
  if (!usb_ready()) return;
  if (n > tx_free()) { s_tx_dropped++; return; }
  for (uint32_t i = 0; i < n; i++) {
    s_tx_ring[s_tx_head] = (uint8_t)s[i];
    s_tx_head = (s_tx_head + 1U) & (TX_RING_SIZE - 1U);
  }
}

static void tx_printf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void tx_printf(const char *fmt, ...)
{
  char line[160];
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(line, sizeof(line) - 1, fmt, ap);
  va_end(ap);
  if (n <= 0) return;
  if (n > (int)sizeof(line) - 2) n = (int)sizeof(line) - 2;
  line[n++] = '\n';
  tx_line(line, (uint32_t)n);
}

static void tx_flush(void)
{
  if (hUsbDeviceFS.dev_state != USBD_STATE_CONFIGURED) { s_tx_tail = s_tx_head; return; }
  if (s_tx_head == s_tx_tail) return;
  USBD_CDC_HandleTypeDef *hcdc = (USBD_CDC_HandleTypeDef *)hUsbDeviceFS.pClassData;
  if (hcdc == NULL || hcdc->TxState != 0U) return;

  uint32_t n = 0, t = s_tx_tail;
  while (t != s_tx_head && n < TX_CHUNK) {
    s_tx_buf[n++] = s_tx_ring[t];
    t = (t + 1U) & (TX_RING_SIZE - 1U);
  }
  if (CDC_Transmit_FS(s_tx_buf, (uint16_t)n) == USBD_OK) {
    s_tx_tail = t;
  }
}

/* uint64 -> texto (o printf da newlib-nano nao formata %llu) */
static char *u64str(uint64_t v, char *buf)
{
  char tmp[21];
  int i = 0;
  do { tmp[i++] = (char)('0' + (v % 10U)); v /= 10U; } while (v);
  int j = 0;
  while (i) buf[j++] = tmp[--i];
  buf[j] = 0;
  return buf;
}

static void send_event(const fm_event_t *e)
{
  char ts[21];
  tx_printf("EV,%lu,%u,%lu,%s", (unsigned long)e->seq, (unsigned)(e->ch + 1U),
            (unsigned long)e->count, u64str(e->t_ms, ts));
}

static void send_status(void)
{
  char ts[21];
  char line[160];
  int n = snprintf(line, sizeof(line), "ST,%s,%lu", u64str(FM_Millis(), ts), (unsigned long)s_next_seq);
  for (uint32_t i = 0; i < FM_NUM_CHANNELS && n < (int)sizeof(line) - 12; i++) {
    n += snprintf(line + n, sizeof(line) - (size_t)n, ",%lu", (unsigned long)s_ch[i].count);
  }
  line[n++] = '\n';
  tx_line(line, (uint32_t)n);
}

/* ------------------------------------------------------------------ DS18B20: lista de sensores */
static ds_sensor_t s_ds[DS_MAX_SENSORS];
static uint8_t  s_ds_n = 0;

/* ------------------------------------------------------------------ sensor ambiental */
static BME280_t s_bme;
static uint32_t s_env_last = 0;
static uint32_t s_env_retry = 0;

static void env_process(uint32_t now)
{
  if (!s_bme.present) {
    if (now - s_env_retry >= 30000U) {      /* tenta detectar de novo a cada 30 s */
      s_env_retry = now;
      BME280_Init(&s_bme, &hi2c1);
    }
    return;
  }
  if (now - s_env_last < FM_ENV_PERIOD_MS) return;
  s_env_last = now;

  int32_t t_c; uint32_t p; int32_t rh;
  if (BME280_Read(&s_bme, &t_c, &p, &rh)) {
    char ts[21];
    const char *sg = (t_c < 0) ? "-" : "";
    int32_t ta = abs(t_c);
    if (rh >= 0) {
      tx_printf("ENV,%s,%s%ld.%02ld,%lu,%ld.%01ld", u64str(FM_Millis(), ts), sg, (long)(ta / 100), (long)(ta % 100),
                (unsigned long)p, (long)(rh / 1000), (long)((rh % 1000) / 100));
    } else {
      tx_printf("ENV,%s,%s%ld.%02ld,%lu,-1", u64str(FM_Millis(), ts), sg, (long)(ta / 100), (long)(ta % 100),
                (unsigned long)p);
    }
  } else {
    s_bme.present = 0;                      /* perdeu o sensor: volta a procurar */
    s_env_retry = now;
  }
}

/* ------------------------------------------------------------------ comandos (USB RX) */
#define RX_RING_SIZE 256U
static uint8_t  s_rx_ring[RX_RING_SIZE];
static volatile uint32_t s_rx_head = 0;
static uint32_t s_rx_tail = 0;
static char     s_cmd[64];
static uint32_t s_cmd_len = 0;

/* GET em andamento: envia aos poucos para nao estourar a fila de TX */
static uint8_t  s_get_active = 0;
static uint32_t s_get_seq = 0;
static uint32_t s_get_end = 0;

void FM_UsbRx(const uint8_t *buf, uint32_t len)   /* contexto de interrupcao USB */
{
  for (uint32_t i = 0; i < len; i++) {
    uint32_t nh = (s_rx_head + 1U) & (RX_RING_SIZE - 1U);
    if (nh == s_rx_tail) break;                    /* cheio: descarta */
    s_rx_ring[s_rx_head] = buf[i];
    s_rx_head = nh;
  }
}

void FM_UsbLineState(uint8_t dtr)                  /* contexto de interrupcao USB */
{
  if (dtr && !s_dtr) s_hello_pending = 1;
  s_dtr = dtr ? 1U : 0U;
}

static void cmd_execute(char *c)
{
  if (strcmp(c, "ID?") == 0) {
    uint32_t uid0 = HAL_GetUIDw0(), uid1 = HAL_GetUIDw1(), uid2 = HAL_GetUIDw2();
    tx_printf("ID,TIPGAS,%s,%08lX%08lX%08lX,%u,%lu,%s,%lu,%u", FM_FW_VERSION,
              (unsigned long)uid2, (unsigned long)uid1, (unsigned long)uid0,
              (unsigned)FM_NUM_CHANNELS, (unsigned long)s_lockout_ms,
              s_bme.present ? ((s_bme.chip_id == 0x60) ? "BME280" : "BMP280") : "NONE",
              (unsigned long)s_pol_mask, (unsigned)s_ds_n);
  } else if (strcmp(c, "ST?") == 0) {
    send_status();
  } else if (strncmp(c, "GET,", 4) == 0) {
    uint32_t from = (uint32_t)strtoul(c + 4, NULL, 10);
    uint32_t oldest = log_oldest();
    if (from < oldest) {
      tx_printf("LOST,%lu,%lu", (unsigned long)from, (unsigned long)oldest);
      from = oldest;
    }
    s_get_seq = from;
    s_get_end = s_next_seq;          /* eventos novos continuam saindo ao vivo */
    s_get_active = 1;
  } else if (strcmp(c, "RST") == 0) {
    __disable_irq();
    for (uint32_t i = 0; i < FM_NUM_CHANNELS; i++) s_ch[i].count = 0;
    __enable_irq();
    tx_printf("OK,RST");
    send_status();
  } else if (strncmp(c, "DEB,", 4) == 0) {
    long v = strtol(c + 4, NULL, 10);
    if (v >= 20 && v <= 10000) {
      s_lockout_ms = (uint32_t)v;
      if (cfg_save()) tx_printf("OK,DEB,%lu", (unsigned long)s_lockout_ms);
      else            tx_printf("ERR,DEB aplicado mas nao gravado na flash");
    } else {
      tx_printf("ERR,DEB fora da faixa 20..10000");
    }
  } else if (strncmp(c, "POL,", 4) == 0) {
    char *end = NULL;
    unsigned long v = strtoul(c + 4, &end, 10);
    if (end != c + 4 && v < (1UL << FM_NUM_CHANNELS)) {
      __disable_irq();
      s_pol_mask = (uint32_t)v;
      for (uint32_t i = 0; i < FM_NUM_CHANNELS; i++) s_ch[i].pending = 0;  /* descarta candidatos antigos */
      __enable_irq();
      if (cfg_save()) tx_printf("OK,POL,%lu", (unsigned long)s_pol_mask);
      else            tx_printf("ERR,POL aplicado mas nao gravado na flash");
    } else {
      tx_printf("ERR,POL fora da faixa 0..511");
    }
  } else if (c[0] != 0) {
    tx_printf("ERR,comando desconhecido: %s", c);
  }
}

static void cmd_process(void)
{
  while (s_rx_tail != s_rx_head) {
    char ch = (char)s_rx_ring[s_rx_tail];
    s_rx_tail = (s_rx_tail + 1U) & (RX_RING_SIZE - 1U);
    if (ch == '\r' || ch == '\n') {
      s_cmd[s_cmd_len] = 0;
      if (s_cmd_len) cmd_execute(s_cmd);
      s_cmd_len = 0;
    } else if (s_cmd_len < sizeof(s_cmd) - 1U) {
      s_cmd[s_cmd_len++] = ch;
    }
  }
}

static void get_process(void)
{
  if (!s_get_active) return;
  while (s_get_seq < s_get_end && tx_free() > 200U) {
    const fm_event_t *e = log_get(s_get_seq);
    if (e) send_event(e);
    s_get_seq++;
  }
  if (s_get_seq >= s_get_end && tx_free() > 64U) {
    tx_printf("GETEND,%ld", (long)s_get_end - 1L);
    s_get_active = 0;
  }
  if (!usb_ready()) s_get_active = 0;
}

/* ------------------------------------------------------------------ deteccao */
void FM_OnExti(uint16_t gpio_pin)        /* contexto de interrupcao EXTI */
{
  uint64_t now = s_ms64;                 /* SysTick tem prioridade menor que a EXTI: leitura segura */
  for (uint32_t i = 0; i < FM_NUM_CHANNELS; i++) {
    if (s_hw[i].pin != gpio_pin) continue;
    fm_chan_t *c = &s_ch[i];
    if (c->pending) return;
    if (!chan_active(i)) return;           /* borda de saida do nivel ativo: ignora */
    if (c->has_last && (now - c->t_last) < s_lockout_ms) return;
    c->t_edge = now;
    c->pending = 1;
    return;
  }
}

static void detect_process(void)
{
  for (uint32_t i = 0; i < FM_NUM_CHANNELS; i++) {
    fm_chan_t *c = &s_ch[i];
    if (c->pending != 2U) continue;      /* confirmado no SysTick (HAL_IncTick) */
    {
      fm_event_t *e = &s_log[s_next_seq & (FM_EVENT_LOG_SIZE - 1U)];
      __disable_irq();                   /* t_last tambem e lido na EXTI */
      c->count++;
      c->t_last = c->t_edge;
      c->has_last = 1;
      __enable_irq();
      e->t_ms  = c->t_edge;
      e->seq   = s_next_seq;
      e->count = c->count;
      e->ch    = (uint8_t)i;
      s_next_seq++;
      send_event(e);
      HAL_GPIO_TogglePin(LED_GPIO_Port, LED_Pin);
    }
    c->pending = 0;
  }
}

/* ------------------------------------------------------------------ DS18B20 (1-Wire em PB8) */
static uint8_t  s_ds_state = 0;          /* 0 = ocioso, 1 = convertendo, 2 = lendo */
static uint8_t  s_ds_idx = 0;
static uint32_t s_ds_t = 0, s_ds_last_conv = 0, s_ds_last_search = 0;
static uint8_t  s_ds_searched = 0;

static void ds_process(uint32_t now)
{
  if (s_ds_state == 0U) {
    /* procura sensores no inicio, a cada 10 s se nao houver nenhum e a cada 60 s se houver (troca a quente) */
    uint32_t every = s_ds_n ? 60000U : 10000U;
    if (!s_ds_searched || (now - s_ds_last_search) >= every) {
      s_ds_searched = 1;
      s_ds_last_search = now;
      s_ds_n = DS_Search(s_ds, DS_MAX_SENSORS);
      return;
    }
    if (s_ds_n && (now - s_ds_last_conv) >= FM_DS_PERIOD_MS) {
      s_ds_last_conv = now;
      if (DS_StartConversion()) { s_ds_state = 1; s_ds_t = now; }
    }
  } else if (s_ds_state == 1U) {
    if ((now - s_ds_t) >= 800U) { s_ds_state = 2; s_ds_idx = 0; }   /* 750 ms em 12 bits */
  } else {
    /* um sensor por passada do laco, para nao segurar o laco principal por muito tempo */
    if (s_ds_idx < s_ds_n) {
      ds_sensor_t *d = &s_ds[s_ds_idx];
      if (DS_ReadTemp(d)) {
        char ts[21], rom[17];
        int32_t ta = d->t_centi < 0 ? -d->t_centi : d->t_centi;
        DS_RomToHex(d->rom, rom);
        tx_printf("TMP,%s,%u,%s,%s%ld.%02ld", u64str(FM_Millis(), ts), (unsigned)(s_ds_idx + 1U), rom,
                  d->t_centi < 0 ? "-" : "", (long)(ta / 100), (long)(ta % 100));
      }
      s_ds_idx++;
    }
    if (s_ds_idx >= s_ds_n) s_ds_state = 0;
  }
}

/* ------------------------------------------------------------------ API */
void FM_Init(void)
{
  memset(s_ch, 0, sizeof(s_ch));
  cfg_load();
  HAL_GPIO_WritePin(LED_GPIO_Port, LED_Pin, GPIO_PIN_SET);   /* LED apagado (ativo em baixo) */
  BME280_Init(&s_bme, &hi2c1);
  s_env_retry = HAL_GetTick();
  DS_Init();
}

void FM_Process(void)
{
  static uint32_t st_last = 0;
  uint32_t now = HAL_GetTick();

  detect_process();
  cmd_process();

  if (s_hello_pending) {
    s_hello_pending = 0;
    tx_printf("HELLO,TIPGAS,%s,%u", FM_FW_VERSION, (unsigned)FM_NUM_CHANNELS);
  }

  get_process();

  if (now - st_last >= FM_STATUS_PERIOD_MS) {
    st_last = now;
    send_status();
  }

  env_process(now);
  ds_process(now);
  tx_flush();
}
