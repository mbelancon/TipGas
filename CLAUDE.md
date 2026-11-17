# CLAUDE.md — TipGas

Regras e comandos para o Claude neste repositório. Estado, histórico e decisões do projeto ficam em
CONTEXTO.md (importado abaixo); o README e `docs/` são para usuários. O git é a referência.

@CONTEXTO.md

## Comandos

```bash
# Interface (Python 3.12; no Windows use o Miniconda em C:\Users\mbelancon\miniconda3)
cd interface
pip install -r requirements.txt
python TipGas.py --sim        # app em modo simulação, sem placa
python tests/test_core.py     # testes (só precisam de numpy e pyserial)

# Firmware (alternativa ao STM32CubeIDE, que é o caminho principal)
cd firmware/TipGas_F411
make -j4                      # build/TipGas_F411.hex/.bin (arm-none-eabi-gcc)

# Pacote portátil (rodar no Windows)
python packaging/build_portable.py --firmware <hex> <bin>
```

A CI (`.github/workflows/release.yml`) compila o firmware, roda os testes e gera o zip portátil em
todo push na `main` e em toda PR; uma tag `v*` publica a Release.

## Regras

- **Testes antes de propor PR ou release**: `python tests/test_core.py` deve terminar com
  "todos os testes passaram". Mudou firmware? Rode também `make`.
- **Interface bilíngue**: as strings do código são em português, passadas por `tr()`; toda string
  nova visível ao usuário precisa da tradução no dicionário `EN` de `interface/i18n.py`.
  Mensagens comparadas nos testes estão em português (`TIPGAS_LANG=pt`).
- **Modo simulação sempre funcionando** (`simulator.py`); os testes dependem dele.
- **Firmware STM32Cube/HAL** (não stm32duino): código de usuário só entre `USER CODE BEGIN/END`
  nos arquivos gerados, porque o CubeMX regenera o resto a partir do `.ioc`. A lógica fica em
  `app_flowmeter.c`, `ds18b20.c`, `bme280.c`. Arquivo `.c` novo também entra no `Makefile`.
- **Protocolo USB**: mudou comando ou resposta? Atualize firmware, `tipgas_core.py`,
  `simulator.py` e `docs/firmware.md` juntos.
- **Versão**: ao lançar, atualize `APP_VERSION` (`interface/tipgas_core.py`), `FM_FW_VERSION`
  (`firmware/.../Core/Inc/app_flowmeter.h`) e adicione a seção `## x.y.z — data` no `CHANGELOG.md`
  (a Release usa esse texto).
- **Docs**: README e `docs/` em inglês; CONTEXTO.md e este arquivo em português.
- **Fim de sessão**: se algo mudou, proponha as alterações no CONTEXTO.md como diff curto.
- Não commitar `build/`, `dist/`, `build_portable/` nem arquivos do Drive; não fazer push na
  `main` sem pedido explícito.
