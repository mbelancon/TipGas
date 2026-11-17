# CONTEXTO — TipGas

Estado, histórico e decisões do projeto. Curto e atualizado; regras de trabalho e comandos ficam no
CLAUDE.md, e detalhes técnicos em `docs/`.

## Objetivo
Medidor de vazão/volume de gás tipping-bucket de 9 canais para fluxos baixos (biogás, fermentação,
respirometria; de alguns mL/h a alguns L/h por célula). Projeto sugerido por um amigo; a mecânica
(impressão 3D, ímã + Hall) já está resolvida. Usado na metodologia de um artigo em preparação.

## Hardware
- Black Pill STM32F411CEU6, USB CDC; gravação por DFU (sem ST-Link)
- 9 sensores Hall digitais a 3,3 V (KY-024), polaridade por canal
- Opcionais: DS18B20 por célula (1-Wire único em PB8), BME280/BMP280 ambiente (I²C PB6/PB7)

## Estrutura
- `firmware/TipGas_F411/` — STM32Cube (`.ioc`, HAL, USB CDC), Makefile
- `interface/` — `TipGas.py` (entrada), `tipgas_gui.py` (PySide6 + pyqtgraph), `tipgas_core.py`
  (DeviceLink, Experiment, correção), `calibration.py`, `simulator.py`, `i18n.py`, `tests/`
- `docs/` — hardware, gravação, firmware, métodos da interface, formato dos dados
- `packaging/` + `.github/workflows/release.yml` — zip portátil para Windows nas Releases

## Como funciona (resumo)
- Firmware: interrupção de borda + confirmação de 3 ms + lockout (padrão 2 s); timestamps de 1 ms
  em relógio de 64 bits; configurações na flash (setor 5)
- Buffer de 2048 eventos numerados; a interface recupera eventos perdidos (`GET`) ao reconectar e
  trata reinício da placa
- Um CSV por sensor (tempo, volume) + detalhes por tombo; T e P gravados em cada tombo

## Decisões
- STM32Cube/HAL em vez de stm32duino; DFU como gravação padrão
- Correção de volume: método do artigo de referência (vapor d'água por Antoine) ou CNTP seco/úmido
- Licença GPL v3 (HAL/middleware ST mantêm as licenças originais)
- Interface segue o idioma do Windows, com escolha manual em Ajustes (vale após reiniciar)

## Histórico
- 2026-11-12 — v1.0.0 publicada (primeira Release pública)
- 2026-11-17 — CLAUDE.md e CONTEXTO.md criados no repositório

## Pendências
- (preencher)
