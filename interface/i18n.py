"""
TipGas - interface translation (Portuguese / English).

The source strings in the code are Portuguese; tr() returns the English text when the
interface language is English. The language is chosen once, at import time:
  1. environment variable TIPGAS_LANG ("pt" or "en"), if set;
  2. "idioma" in the settings file (~/.tipgas.json), if not "auto";
  3. the operating-system language (Portuguese -> pt, anything else -> en).
Changing the language in Ajustes/Settings takes effect after restarting the program.
"""
import json
import locale
import os

SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".tipgas.json")
LANGUAGES = {"auto": "Automático / Automatic", "pt": "Português", "en": "English"}


def _system_language() -> str:
    code = ""
    try:
        if os.name == "nt":
            import ctypes
            code = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
        if not code:
            code = locale.getlocale()[0] or os.environ.get("LANG", "")
    except Exception:
        pass
    return "pt" if code.lower().startswith(("pt", "portuguese")) else "en"


def _choose() -> str:
    env = os.environ.get("TIPGAS_LANG", "").lower()
    if env in ("pt", "en"):
        return env
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            pref = json.load(f).get("idioma", "auto")
        if pref in ("pt", "en"):
            return pref
    except Exception:
        pass
    return _system_language()


LANG = _choose()


def tr(text: str) -> str:
    if LANG == "en":
        return EN.get(text, text)
    return text


EN = {
    ' basculamentos':
        ' tips',
    ' · P média {0:.3f} kPa':
        ' · mean P {0:.3f} kPa',
    ' · poucos basculamentos em {0} (incerteza alta)':
        ' · few tips on {0} (high uncertainty)',
    ' · sem pressão (use P_ref)':
        ' · no pressure (use P_ref)',
    ' · simulação {0:g}×':
        ' · simulation {0:g}×',
    ' — a placa continua contando':
        ' — the board keeps counting',
    ' — sem leitura':
        ' — no reading',
    '(nenhuma porta encontrada)':
        '(no port found)',
    '1× (tempo real)':
        '1× (real time)',
    '<b>Como calibrar</b><br>1. Marque os canais e clique em <b>Iniciar contagem</b>.<br>2. Injete em cada célula um volume conhecido de gás (seringa, bureta, controlador de vazão), de preferência numa vazão parecida com a dos experimentos.<br>3. Informe o volume injetado e clique em <b>Calcular</b>. Use volume suficiente para pelo menos <b>{0} basculamentos</b>: a contagem tem incerteza de ±1 basculamento.<br>4. <b>Aplicar</b> copia os k para os canais. A temperatura e a pressão médias da calibração podem virar a referência (T_ref, P_ref) da correção.':
        '<b>How to calibrate</b><br>1. Tick the channels and click <b>Start counting</b>.<br>2. Inject a known volume of gas into each cell (syringe, burette, flow controller), preferably at a flow rate similar to the experiments.<br>3. Enter the injected volume and click <b>Calculate</b>. Use enough volume for at least <b>{0} tips</b>: the count has an uncertainty of ±1 tip.<br>4. <b>Apply</b> copies the k values to the channels. The mean temperature and pressure of the calibration can become the reference (T_ref, P_ref) of the correction.',
    '<b>Condições da calibração</b> (referência da correção pelo método do artigo)':
        '<b>Calibration conditions</b> (reference of the correction by the article method)',
    '<b>Conectado</b> · pré-visualização (não está gravando){0}':
        '<b>Connected</b> · preview (not recording){0}',
    '<b>Correção:</b>':
        '<b>Correction:</b>',
    '<b>Desconectado</b>':
        '<b>Disconnected</b>',
    '<b>Experimento salvo:</b> {0} (Dados → Voltar ao vivo)':
        '<b>Saved experiment:</b> {0} (Data → Back to live)',
    '<b>Experimento:</b>':
        '<b>Experiment:</b>',
    '<b>Gravando</b> “{0}”{1}':
        '<b>Recording</b> “{0}”{1}',
    '<b>Porta:</b>':
        '<b>Port:</b>',
    '<b>Salvar em:</b>':
        '<b>Save to:</b>',
    '<b>Sem resposta do dispositivo há {0:.0f} s</b> — verifique o cabo USB{1}':
        '<b>No response from the device for {0:.0f} s</b> — check the USB cable{1}',
    '<b>{0}</b><br>Monitor de produção de gás com 9 células tipping-bucket, sensores Hall e STM32F411 (Black Pill).<br><br>Cada sensor tem seu arquivo (<i>S1_….csv</i> a <i>S9_….csv</i>) com tempo e volume; os dados completos de cada basculamento ficam em <i>detalhes/</i>. O volume é o número de basculamentos × fator de calibração (FC, mL por basculamento).<br><br>Dados e registro de eventos em:<br>{1}':
        '<b>{0}</b><br>Gas production monitor with 9 tipping-bucket cells, Hall sensors and STM32F411 (Black Pill).<br><br>Each sensor has its own file (<i>S1_….csv</i> to <i>S9_….csv</i>) with time and volume; the full data of every tip is kept in <i>detalhes/</i>. The volume is the number of tips × calibration factor (FC, mL per tip).<br><br>Data and event log in:<br>{1}',
    'A polaridade de cada sensor (↓/↑) fica no cabeçalho de cada canal.':
        'The polarity of each sensor (↓/↑) is in the header of each channel.',
    'AVISO: o firmware do dispositivo não suporta polaridade configurável (atualize para 1.1)':
        'WARNING: the device firmware does not support configurable polarity (update to 1.1)',
    'Abrir arquivo':
        'Open file',
    'Abrir experimento salvo…':
        'Open saved experiment…',
    'Abrir pasta':
        'Open folder',
    'Abrir pasta de dados':
        'Open data folder',
    'Abrir pasta de um experimento salvo':
        'Open the folder of a saved experiment',
    'Ainda não há leitura do sensor ambiental (BME280/BMP280).':
        'No reading from the ambient sensor (BME280/BMP280) yet.',
    'Ajustes':
        'Settings',
    'Ambiente:':
        'Ambient:',
    'Aplicar a todos':
        'Apply to all',
    'Aplicar aos canais':
        'Apply to channels',
    'Aplicar os novos fatores?\n\n{0}':
        'Apply the new factors?\n\n{0}',
    'Ar (BME280)':
        'Air (BME280)',
    'Arquivo: {0}':
        'File: {0}',
    'Arrastar: mover · roda do mouse: zoom · duplo clique ou botão “A”: autoscale':
        'Drag: pan · mouse wheel: zoom · double click or “A” button: autoscale',
    'Atualizar lista de portas':
        'Refresh port list',
    'BME280 (ar)':
        'BME280 (air)',
    'Basculamentos':
        'Tips',
    'Basculamentos exportados ({0} arquivos, um por sensor) em {1}':
        'Tips exported ({0} files, one per sensor) to {1}',
    'Basculamentos: 0':
        'Tips: 0',
    'Basculamentos: {0}':
        'Tips: {0}',
    'Bloqueio enviado ao dispositivo: {0} ms':
        'Lockout sent to the device: {0} ms',
    'Bloqueio:':
        'Lockout:',
    'Calibração':
        'Calibration',
    'Calibração aplicada (mL/basculamento): {0}':
        'Calibration applied (mL/tip): {0}',
    'Calibração dos fatores k':
        'Calibration of the k factors',
    'Calibração salva: {0}':
        'Calibration saved: {0}',
    'Calibração: contagem iniciada':
        'Calibration: counting started',
    'Canal':
        'Channel',
    'Clique em “Iniciar contagem” antes de injetar o gás.':
        'Click “Start counting” before injecting the gas.',
    'Clique para ativar/desativar este canal':
        'Click to enable/disable this channel',
    'Clique para ver o registro de eventos':
        'Click to see the event log',
    'Comunicação com o dispositivo restabelecida':
        'Communication with the device restored',
    'Conectado em {0}':
        'Connected on {0}',
    'Conectar':
        'Connect',
    'Conecte o medidor (ou a simulação) para calibrar.':
        'Connect the meter (or the simulation) to calibrate.',
    'Conecte o medidor (ou escolha a simulação) antes de iniciar.':
        'Connect the meter (or choose the simulation) before starting.',
    'Contando desde {0:%H:%M:%S} — injete o volume conhecido':
        'Counting since {0:%H:%M:%S} — inject the known volume',
    'Copia a temperatura e a pressão medidas agora para T_ref e P_ref':
        'Copies the temperature and pressure measured now to T_ref and P_ref',
    'Copiar para todos':
        'Copy to all',
    'Correção de cada basculamento por temperatura e pressão (sensor BME280/BMP280).\n“Condições da calibração” = método do artigo: leva cada basculamento às condições\n(T_ref, P_ref) em que o fator k foi medido. Ajuste T_ref e P_ref em Ajustes → Medição.':
        'Correction of each tip for temperature and pressure (BME280/BMP280 sensor).\n“Calibration conditions” = article method: brings each tip to the conditions\n(T_ref, P_ref) at which the k factor was measured. Set T_ref and P_ref in Settings → Measurement.',
    'Cálculo, dispositivo e simulação':
        'Calculation, device and simulation',
    'Dados':
        'Data',
    'Desconectado':
        'Disconnected',
    'Desconectar':
        'Disconnect',
    'Desconectar 5 s':
        'Disconnect 5 s',
    'Dispositivo':
        'Device',
    'Encerrar a gravação deste experimento?':
        'Stop recording this experiment?',
    'Encerre a gravação antes de trocar de dispositivo.':
        'Stop the recording before changing device.',
    'Escolher a pasta onde os experimentos são salvos':
        'Choose the folder where experiments are saved',
    'Experimento aberto para análise: {0}':
        'Experiment opened for analysis: {0}',
    'Experimento salvo reprocessado: S{0} com FC = {1:.3f} mL':
        'Saved experiment reprocessed: S{0} with FC = {1:.3f} mL',
    'Experimentos salvos, exportação e registro':
        'Saved experiments, export and log',
    'Exportar tabela a cada:':
        'Export table every:',
    'Exportar tabela em intervalos regulares (volume e vazão)…':
        'Export table at regular intervals (volume and flow)…',
    'Exportar tempo e volume (um arquivo por sensor)…':
        'Export time and volume (one file per sensor)…',
    'Exportar volume e vazão em intervalos regulares':
        'Export volume and flow at regular intervals',
    'Fator de calibração: mL por basculamento':
        'Calibration factor: mL per tip',
    'Fechar':
        'Close',
    'Firmware:':
        'Firmware:',
    'Fração de mensagens perdidas na USB (testa a recuperação automática)':
        'Fraction of messages lost on the USB (tests the automatic recovery)',
    'Gravação encerrada ({0} basculamentos, duração {1}): {2}':
        'Recording stopped ({0} tips, duration {1}): {2}',
    'Gravação iniciada: {0}':
        'Recording started: {0}',
    'Há uma gravação em andamento. Desconectar mesmo assim?\n(o MCU continua contando; ao reconectar os eventos são recuperados)':
        'A recording is in progress. Disconnect anyway?\n(the MCU keeps counting; events are recovered on reconnection)',
    'Há uma gravação em andamento. Fechar o programa?\nOs dados já gravados ficam salvos. O MCU continua contando e os eventos podem ser recuperados se o programa for reaberto em pouco tempo.':
        'A recording is in progress. Close the program?\nData already recorded stays saved. The MCU keeps counting and events can be recovered if the program is reopened soon.',
    'Incerteza':
        'Uncertainty',
    'Iniciar / encerrar a gravação do experimento':
        'Start / stop recording the experiment',
    'Iniciar contagem':
        'Start counting',
    'MCU:':
        'MCU:',
    'Medição':
        'Measurement',
    'Mesmo sensor para todos:':
        'Same sensor for all:',
    'Mesmo volume para todos:':
        'Same volume for all:',
    'Nenhuma porta serial encontrada.\nConecte o medidor pela USB ou escolha “Simulação (sem placa)”.':
        'No serial port found.\nConnect the meter via USB or choose “Simulation (no board)”.',
    'Nome do experimento (usado no nome da pasta de dados)':
        'Experiment name (used in the data folder name)',
    'Nome do reator / amostra':
        'Reactor / sample name',
    'Não foi possível abrir o experimento:\n{0}':
        'Could not open the experiment:\n{0}',
    'Não foi possível criar a pasta de dados:\n{0}':
        'Could not create the data folder:\n{0}',
    'Não foi possível salvar o registro da calibração:\n{0}':
        'Could not save the calibration record:\n{0}',
    'Não há dados para exportar.':
        'There is no data to export.',
    'O que os gráficos mostram':
        'What the graphs show',
    'Para simular, escolha “Simulação (sem placa)” na lista de portas e clique em Conectar.':
        'To simulate, choose “Simulation (no board)” in the port list and click Connect.',
    'Parado':
        'Stopped',
    'Pasta de dados alterada para {0}':
        'Data folder changed to {0}',
    'Pasta onde salvar um arquivo por sensor':
        'Folder where one file per sensor is saved',
    'Pasta para salvar os experimentos':
        'Folder for saving experiments',
    'Pasta: {0}':
        'Folder: {0}',
    'Pasta: –':
        'Folder: –',
    'Perda de mensagens:':
        'Message loss:',
    'Polaridade enviada ao dispositivo (máscara {0}: canais em nível alto = {1})':
        'Polarity sent to the device (mask {0}: channels active high = {1})',
    'Pressão atmosférica durante a calibração (Pato Branco, ~760 m: cerca de 92–93 kPa)':
        'Atmospheric pressure during calibration (sea level ≈ 101.3 kPa; about 92–93 kPa at ~760 m)',
    'Programa encerrado':
        'Program closed',
    'Programa iniciado (registro em {0})':
        'Program started (log in {0})',
    'Reator {0}':
        'Reactor {0}',
    'Referência definida pelas condições atuais: T_ref {0:.2f} °C, P_ref {1:.3f} kPa':
        'Reference set from current conditions: T_ref {0:.2f} °C, P_ref {1:.3f} kPa',
    'Registro de eventos':
        'Event log',
    'Registro de eventos…':
        'Event log…',
    'Reiniciar MCU':
        'Restart MCU',
    'Sem resposta do dispositivo — verifique o cabo USB':
        'No response from the device — check the USB cable',
    'Sem sensor de T/P: volumes sem correção':
        'No T/P sensor: volumes not corrected',
    'Sensor (código)':
        'Sensor (code)',
    'Sensores DS18B20 encontrados no barramento 1-Wire (pino PB8). Associe a cada canal o sensor que mede o gás daquela célula. No basculamento, a interface registra a leitura mais recente desse sensor (lida a cada 2 s) e usa essa temperatura na correção. Canais sem DS18B20 usam o BME280 (ar). Para identificar um sensor, segure-o na mão: o que esquentar é ele.':
        'DS18B20 sensors found on the 1-Wire bus (pin PB8). Assign to each channel the sensor that measures the gas of that cell. At each tip the interface records the latest reading of that sensor (read every 2 s) and uses that temperature in the correction. Channels without a DS18B20 use the BME280 (air). To identify a sensor, hold it in your hand: the one that warms up is it.',
    'Simulação':
        'Simulation',
    'Simulação (sem placa)':
        'Simulation (no board)',
    'Simulação em execução':
        'Simulation running',
    'Simulação parada':
        'Simulation stopped',
    'Sobre':
        'About',
    'Sobre o programa':
        'About the program',
    'Sobre – {0}':
        'About – {0}',
    'S{0}: temperatura do {1}':
        'S{0}: temperature from {1}',
    'S{0}: {1:.4f} → {2:.4f} mL/basc.':
        'S{0}: {1:.4f} → {2:.4f} mL/tip',
    'T média {0:.2f} °C ({1}){2}':
        'Mean T {0:.2f} °C ({1}){2}',
    'T/P médias: sem sensor de temperatura':
        'Mean T/P: no temperature sensor',
    'T/P médias: —':
        'Mean T/P: —',
    'Temperatura':
        'Temperature',
    'Temperatura em que os fatores k foram medidos':
        'Temperature at which the k factors were measured',
    'Tempo (h)':
        'Time (h)',
    'Tempo ({0})':
        'Time ({0})',
    'Tempo decorrido: 00:00:00':
        'Elapsed time: 00:00:00',
    'Tempo decorrido: {0}':
        'Elapsed time: {0}',
    'Tempo decorrido: –':
        'Elapsed time: –',
    'Tempo mínimo entre dois basculamentos do mesmo canal (filtra o quique mecânico).\nFica salvo na interface e é enviado à placa a cada conexão.':
        'Minimum time between two tips of the same channel (filters mechanical bounce).\nSaved in the interface and sent to the board on every connection.',
    'Testes:':
        'Tests:',
    'Unidade do eixo do tempo:':
        'Time axis unit:',
    'Usar':
        'Use',
    'Usar T e P atuais':
        'Use current T and P',
    'Usar a temperatura e a pressão médias da calibração como T_ref e P_ref':
        'Use the mean temperature and pressure of the calibration as T_ref and P_ref',
    'Vazão':
        'Flow',
    'Vazão ({0}/h)':
        'Flow ({0}/h)',
    'Vazão = volume dos últimos N basculamentos / tempo decorrido entre eles':
        'Flow = volume of the last N tips / time elapsed between them',
    'Vazão: média dos últimos':
        'Flow: average of the last',
    'Velocidade:':
        'Speed:',
    'Voltar ao vivo':
        'Back to live',
    'Volume (mL)':
        'Volume (mL)',
    'Volume ({0})':
        'Volume ({0})',
    'Volume acumulado':
        'Cumulative volume',
    'Volume acumulado ({0})':
        'Cumulative volume ({0})',
    'Volume injetado (mL)':
        'Injected volume (mL)',
    'basculamentos':
        'tips',
    'canal desativado':
        'channel disabled',
    'enviado à placa':
        'sent to the board',
    'experimento':
        'experiment',
    'há {0:.0f} s':
        '{0:.0f} s ago',
    'igual ao da placa':
        'same as the board',
    'k atual':
        'current k',
    'k medido (mL/basc.)':
        'measured k (mL/tip)',
    'ligado há {0} · {1} eventos desde o boot · sessão {2}':
        'up for {0} · {1} events since boot · session {2}',
    'nenhum':
        'none',
    'volume':
        'volume',
    '{0} basc. · {1:.1f} mL/h':
        '{0} tips · {1:.1f} mL/h',
    '{0} canal(is) calculado(s)':
        '{0} channel(s) calculated',
    '{0} · sensor ambiental: {1}\nUID {2}':
        '{0} · ambient sensor: {1}\nUID {2}',
    'Ímã = nível ALTO na saída do sensor (clique para trocar)':
        'Magnet = HIGH level at the sensor output (click to change)',
    'Ímã = nível BAIXO na saída do sensor (clique para trocar)':
        'Magnet = LOW level at the sensor output (click to change)',
    'Última leitura':
        'Last reading',
    'Único DS18B20 associado a todos os canais (altere em Ajustes → Temperatura)':
        'Single DS18B20 assigned to all channels (change in Settings → Temperature)',
    '– (pré-visualização: nada é gravado)':
        '– (preview: nothing is recorded)',
    '■  Encerrar':
        '■  Stop',
    '▶  Iniciar':
        '▶  Start',
    'Sem correção': 'No correction',
    'Condições da calibração (T_ref, P_ref)': 'Calibration conditions (T_ref, P_ref)',
    'CNTP, gás seco (0 °C; 101,325 kPa)': 'STP, dry gas (0 °C; 101.325 kPa)',
    'CNTP, gás úmido (0 °C; 101,325 kPa)': 'STP, wet gas (0 °C; 101.325 kPa)',
    'mL CNTP seco': 'mL STP dry',
    'mL CNTP úmido': 'mL STP wet',
    'Dispositivo conectado (firmware {0})': 'Device connected (firmware {0})',
    'AVISO: {0} evento(s) não recuperado(s) (seq {1}..{2})': 'WARNING: {0} event(s) not recovered (seq {1}..{2})',
    'AVISO: eventos {0}..{1} já foram descartados do buffer do MCU ({2} basculamento(s) perdidos)': 'WARNING: events {0}..{1} were already dropped from the MCU buffer ({2} tip(s) lost)',
    'ERRO do dispositivo: ': 'ERROR from device: ',
    'Reinício do microcontrolador detectado: recuperando eventos desde o boot': 'Microcontroller restart detected: recovering events since boot',
    'min': 'min',
    'h': 'h',
    'dias': 'days',
    'DS18B20 encontrado: {0} ({1:.2f} °C)': 'DS18B20 found: {0} ({1:.2f} °C)',
    ' · UR {0:.0f} %': ' · RH {0:.0f} %',
    'Idioma / Language:': 'Idioma / Language:',
    'Idioma alterado. Reinicie o programa para aplicar.': 'Language changed. Restart the program to apply it.',
    'Calcular': 'Calculate',
    'Reiniciar contagem': 'Restart counting',
    'Conecte o medidor primeiro.': 'Connect the meter first.',
    'Aplicado e salvo em {0}': 'Applied and saved in {0}',
    'Aplicado': 'Applied',
    'Calibrar fatores k…': 'Calibrate k factors…',
    '{0}: {1}. Tentando reconectar…': '{0}: {1}. Trying to reconnect…',
    'Tabela exportada: {0}': 'Table exported: {0}',
    'Conectando…': 'Connecting…',
    'EVENTO': 'EVENT ',
    'AVISO': 'WARN ',
    'ERRO ': 'ERROR',
}
