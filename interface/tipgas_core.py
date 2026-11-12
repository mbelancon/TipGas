"""
tipgas_core.py - TipGas core (no GUI)
Tipping-bucket gas meter: device protocol, clock sync, event recovery, volume/flow and correction math.

- DeviceLink: interpreta o protocolo do STM32, sincroniza o relogio do MCU com o do PC,
  remove duplicatas, detecta eventos perdidos (pede GET) e reinicios do microcontrolador.
- Experiment: guarda configuracao dos canais, eventos e dados ambientais, grava CSV e
  calcula volume acumulado e vazao (com correcao opcional para condicoes padrao).

Protocolo (ver firmware/TipGas_F411/Core/Src/app_flowmeter.c):
  HELLO,TIPGAS,<versao>,<nch>
  ID,TIPGAS,<versao>,<uid>,<nch>,<lockout_ms>,<sensor>[,<pol_mask>]
  EV,<seq>,<canal>,<contagem>,<t_ms>
  ST,<t_ms>,<prox_seq>,<c1>,...,<c9>
  ENV,<t_ms>,<T_C>,<P_Pa>,<UR>
  GETEND,<ultimo_seq>   LOST,<pedido>,<mais_antigo>   OK,...   ERR,...
"""
from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Callable, Dict, List, Optional

import numpy as np

from i18n import tr

NUM_CHANNELS = 9
APP_VERSION = "1.0.0"

# Condicoes padrao (CNTP / "normal"): 0 °C e 101,325 kPa
T_STD_K = 273.15
P_STD_PA = 101325.0


# --------------------------------------------------------------------------- dados
@dataclass
class TipEvent:
    channel: int          # 1..9
    wall: float           # tempo do evento (epoch, s) no relogio do PC
    session: int          # sessao do MCU (muda a cada reinicio do microcontrolador)
    seq: int              # numero do evento no MCU
    mcu_count: int        # contagem do canal no MCU
    mcu_t_ms: int         # tempo do MCU (ms desde o boot)
    t_c: Optional[float] = None      # temperatura registrada no basculamento (DS18B20 do canal ou BME280)
    p_kpa: Optional[float] = None    # pressao registrada no basculamento (BME280)
    t_src: str = ""                  # origem da temperatura: codigo ROM do DS18B20, "BME280" ou ""


@dataclass
class TempSample:
    wall: float
    rom: str              # codigo unico do DS18B20 (16 hex)
    t_c: float


@dataclass
class EnvSample:
    wall: float
    t_c: float
    p_pa: float
    rh: float             # -1 se o sensor nao mede umidade


@dataclass
class ChannelConfig:
    name: str
    enabled: bool = True
    ml_per_tip: float = 10.0      # fator de calibracao (mL por basculamento)
    active_high: bool = False     # True: sensor indica ima com nivel ALTO (ex.: alguns KY-024)
    temp_sensor: str = ""         # ROM do DS18B20 associado ao canal; "" = temperatura do BME280 (ar)


def pol_mask(channels: List["ChannelConfig"]) -> int:
    """Mascara de polaridade para o comando POL (bit n = canal n+1 ativo em nivel alto)."""
    return sum(1 << i for i, c in enumerate(channels) if c.active_high)


# Equacao de Antoine para a agua (NIST/Linstrom), valida de ~1 a 100 °C:
#   P [kPa] = A * 10^(B - C / (D + T)),  T em °C   (A converte mmHg -> kPa)
ANTOINE_A, ANTOINE_B, ANTOINE_C, ANTOINE_D = 0.133322368, 8.07131, 1730.63, 233.426


def p_h2o_kpa(t_c):
    """Pressao de vapor de saturacao da agua (kPa) pela equacao de Antoine. Aceita escalar ou array."""
    t = np.asarray(t_c, dtype=float)
    return ANTOINE_A * np.power(10.0, ANTOINE_B - ANTOINE_C / (ANTOINE_D + t))


def saturation_vapor_pressure_pa(t_c: float) -> float:
    """Pressao de vapor de saturacao da agua (Pa), equacao de Antoine."""
    return float(p_h2o_kpa(t_c)) * 1000.0


CORRECTION_MODES = {
    "none": "Sem correção",
    "ref": "Condições da calibração (T_ref, P_ref)",
    "stp_dry": "CNTP, gás seco (0 °C; 101,325 kPa)",
    "stp_wet": "CNTP, gás úmido (0 °C; 101,325 kPa)",
}


@dataclass
class Correction:
    """
    Correcao de volume aplicada a cada basculamento i:  V_cor = k * soma(F_i).

    mode = "ref" (metodo do artigo): leva cada basculamento as condicoes em que k foi calibrado,
        F_i = (T_ref + 273,15)/(T_i + 273,15) * (P_ref - P_H2O(T_i)) / (P_ref - P_H2O(T_ref))
        com a pressao atmosferica constante = P_ref, como no artigo.
    mode = "stp_dry": volume de gas seco em CNTP,  F_i = (P_i - P_H2O(T_i))/101,325 * 273,15/(T_i + 273,15)
    mode = "stp_wet": volume de gas umido em CNTP, F_i = P_i/101,325 * 273,15/(T_i + 273,15)
    Sem leitura de temperatura, F_i = 1.
    """
    mode: str = "none"
    t_ref_c: float = 25.0
    p_ref_kpa: float = 101.325

    def unit(self) -> str:
        return {"none": "mL", "ref": f"mL @{self.t_ref_c:.1f} °C", "stp_dry": tr("mL CNTP seco"),
                "stp_wet": tr("mL CNTP úmido")}.get(self.mode, "mL")

    def unit_tag(self) -> str:
        """Unidade sem espacos/simbolos, para cabecalhos de CSV."""
        return {"none": "mL", "ref": f"mL_Tref{self.t_ref_c:g}C", "stp_dry": "mL_CNTP_seco",
                "stp_wet": "mL_CNTP_umido"}.get(self.mode, "mL")

    def factors(self, t_c: np.ndarray, p_kpa: Optional[np.ndarray]) -> np.ndarray:
        t_c = np.asarray(t_c, dtype=float)
        # modo "ref": pressao constante = P_ref (metodo do artigo); CNTP: pressao medida (ou P_ref sem sensor)
        p = np.asarray(p_kpa, dtype=float) if (p_kpa is not None and self.mode != "ref") \
            else np.full_like(t_c, self.p_ref_kpa)
        tk = t_c + 273.15
        if self.mode == "ref":
            tr = self.t_ref_c + 273.15
            return (tr / tk) * (p - p_h2o_kpa(t_c)) / (self.p_ref_kpa - p_h2o_kpa(self.t_ref_c))
        if self.mode == "stp_dry":
            return (p - p_h2o_kpa(t_c)) / (P_STD_PA / 1000.0) * (T_STD_K / tk)
        if self.mode == "stp_wet":
            return p / (P_STD_PA / 1000.0) * (T_STD_K / tk)
        return np.ones_like(t_c)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Correction":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# --------------------------------------------------------------------------- protocolo
class DeviceLink:
    """
    Recebe linhas do dispositivo (real ou simulado) e gera eventos ja sincronizados.

    Callbacks (atribuir funcoes):
      on_event(TipEvent)   on_env(EnvSample)   on_status(dict)   on_info(dict)
      on_log(str)          on_reset()          send(str)  <- envia comando ao dispositivo
    clock: funcao que retorna o tempo atual (epoch s). No modo simulacao e o relogio
           (possivelmente acelerado) do simulador.
    """

    # Reinicio do MCU e detectado quando o tempo do MCU ou a numeracao voltam para tras, ou quando
    # o relogio do MCU deixa de bater com o do PC por mais que esta tolerancia (caso de um reinicio
    # durante uma desconexao longa). A tolerancia e larga para nao confundir com ajustes do relogio
    # do PC (NTP); no modo simulacao ela e multiplicada pela aceleracao do tempo.
    RESET_TOLERANCE_S = 120.0
    DRIFT_PPM = 500.0            # tolerancia adicional proporcional ao tempo decorrido

    def __init__(self, clock: Callable[[], float] = time.time, time_scale: float = 1.0):
        self.clock = clock
        self.time_scale = time_scale     # aceleracao do relogio (simulacao)
        self.send: Callable[[str], None] = lambda s: None
        self.on_event: Callable[[TipEvent], None] = lambda e: None
        self.on_env: Callable[[EnvSample], None] = lambda e: None
        self.on_temp: Callable[[TempSample], None] = lambda t: None
        self.on_status: Callable[[dict], None] = lambda s: None
        self.on_info: Callable[[dict], None] = lambda s: None
        self.on_log: Callable[[str], None] = lambda s: None
        self.on_reset: Callable[[], None] = lambda: None
        self.reset_state()

    def reset_state(self):
        self.session = 0
        self.wall_offset: Optional[float] = None   # wall = wall_offset + t_mcu/1000
        self.last_t_ms = -1
        self.contiguous = -1                       # todos os seq <= contiguous ja recebidos
        self.received: set = set()                 # seq > contiguous ja recebidos
        self.get_in_progress = False
        self.info: dict = {}
        self.last_status: dict = {}

    # chamado quando a porta e (re)aberta
    def connection_opened(self):
        self.get_in_progress = False
        self.send("ID?")

    # ------------------------------------------------------------------ util
    def _wall(self, t_ms: int) -> float:
        return (self.wall_offset or 0.0) + t_ms / 1000.0

    def _mark_received(self, seq: int):
        if seq <= self.contiguous:
            return
        self.received.add(seq)
        while (self.contiguous + 1) in self.received:
            self.contiguous += 1
            self.received.discard(self.contiguous)

    def _new_session(self, t_ms: int, now: float):
        self.session += 1
        self.wall_offset = now - t_ms / 1000.0
        self.last_t_ms = t_ms
        self.received.clear()
        self.get_in_progress = False

    # ------------------------------------------------------------------ entrada
    def handle_line(self, line: str):
        line = line.strip()
        if not line:
            return
        parts = line.split(",")
        kind = parts[0]
        try:
            if kind == "EV":
                self._handle_ev(parts)
            elif kind == "ST":
                self._handle_st(parts)
            elif kind == "ENV":
                self._handle_env(parts)
            elif kind == "TMP":
                if self.wall_offset is not None:
                    self.on_temp(TempSample(self._wall(int(parts[1])), parts[3].upper(), float(parts[4])))
            elif kind == "ID":
                self.info = {"version": parts[2], "uid": parts[3], "nch": int(parts[4]),
                             "lockout_ms": int(parts[5]), "sensor": parts[6],
                             "n_ds18b20": int(parts[8]) if len(parts) > 8 else None,
                             "pol_mask": int(parts[7]) if len(parts) > 7 else None}
                self.on_info(self.info)
            elif kind == "HELLO":
                self.on_log(tr("Dispositivo conectado (firmware {0})").format(parts[2]))
                self.send("ID?")
            elif kind == "GETEND":
                self.get_in_progress = False
                last = int(parts[1])
                missing = [s for s in range(self.contiguous + 1, last + 1) if s not in self.received]
                if missing:
                    self.on_log(tr("AVISO: {0} evento(s) não recuperado(s) (seq {1}..{2})").format(len(missing), missing[0], missing[-1]))
                    for s in missing:
                        self._mark_received(s)
            elif kind == "LOST":
                req, oldest = int(parts[1]), int(parts[2])
                self.on_log(tr("AVISO: eventos {0}..{1} já foram descartados do buffer do MCU ({2} basculamento(s) perdidos)")
                            .format(req, oldest - 1, oldest - req))
                for s in range(req, oldest):
                    self._mark_received(s)
            elif kind == "OK":
                self.on_log("OK " + ",".join(parts[1:]))
            elif kind == "ERR":
                self.on_log(tr("ERRO do dispositivo: ") + ",".join(parts[1:]))
            else:
                self.on_log("? " + line)
        except (IndexError, ValueError):
            self.on_log("Linha invalida: " + line)

    def _handle_st(self, p: List[str]):
        t_ms, next_seq = int(p[1]), int(p[2])
        counts = [int(x) for x in p[3:3 + NUM_CHANNELS]]
        now = self.clock()

        if self.wall_offset is None:
            # primeiro contato: pede todo o historico guardado no MCU (GET,0); quem decide o que
            # entra no experimento e o filtro por horario de inicio
            self._new_session(t_ms, now)
            self.contiguous = -1
        else:
            expected = self._wall(t_ms)
            elapsed = t_ms / 1000.0
            tol = self.RESET_TOLERANCE_S * max(1.0, self.time_scale) + elapsed * self.DRIFT_PPM * 1e-6
            if t_ms < self.last_t_ms or next_seq < self.contiguous + 1 or abs(now - expected) > tol:
                self.on_log(tr("Reinício do microcontrolador detectado: recuperando eventos desde o boot"))
                self._new_session(t_ms, now)
                self.contiguous = -1
                self.on_reset()
            else:
                # usa a menor latencia observada para o mapeamento de relogio
                self.wall_offset = min(self.wall_offset, now - t_ms / 1000.0)
        self.last_t_ms = t_ms

        if next_seq - 1 > self.contiguous and not self.get_in_progress:
            self.get_in_progress = True
            self.send(f"GET,{self.contiguous + 1}")

        self.last_status = {"t_ms": t_ms, "next_seq": next_seq, "counts": counts, "session": self.session}
        self.on_status(self.last_status)

    def _handle_ev(self, p: List[str]):
        seq, ch, cnt, t_ms = int(p[1]), int(p[2]), int(p[3]), int(p[4])
        if self.wall_offset is None:
            return            # ainda sem sincronismo; sera recuperado via GET apos o primeiro ST
        if seq <= self.contiguous or seq in self.received:
            return            # duplicado
        self._mark_received(seq)
        if not 1 <= ch <= NUM_CHANNELS:
            return
        self.on_event(TipEvent(channel=ch, wall=self._wall(t_ms), session=self.session,
                               seq=seq, mcu_count=cnt, mcu_t_ms=t_ms))

    def _handle_env(self, p: List[str]):
        if self.wall_offset is None:
            return
        t_ms = int(p[1])
        self.on_env(EnvSample(wall=self._wall(t_ms), t_c=float(p[2]), p_pa=float(p[3]), rh=float(p[4])))


# --------------------------------------------------------------------------- experimento
# Arquivos de um experimento:
#   S<n>_<nome>.csv               um por sensor, so duas colunas: tempo (h) e volume acumulado (mL, corrigido
#                                 conforme a correcao escolhida no inicio da gravacao)
#   detalhes/basculamentos.csv    todos os basculamentos com todos os dados (canal, n, T, P, k, F_i, ...);
#                                 e o arquivo usado para reabrir e reprocessar o experimento
CHANNEL_FIELDS = ["tempo_h", "volume_mL"]
DETAIL_DIR, DETAIL_FILE = "detalhes", "basculamentos.csv"
EVENT_FIELDS = ["data_hora", "t_h", "canal", "nome", "n", "T_C", "fonte_T", "P_kPa", "k_mL", "F_i", "V_mL",
                "V_cor_mL", "sessao", "seq", "contagem_mcu", "t_mcu_ms"]
ENV_FIELDS = ["data_hora", "t_h", "T_C", "P_Pa", "UR_pct"]
TEMP_FIELDS = ["data_hora", "t_h", "sensor", "T_C"]
TEMP_MAX_AGE_S = 60.0     # leitura de DS18B20 mais antiga que isso nao e usada num basculamento


def default_channels() -> List[ChannelConfig]:
    return [ChannelConfig(name=tr("Reator {0}").format(i + 1)) for i in range(NUM_CHANNELS)]


class Experiment:
    def __init__(self, name: str, folder: Optional[str], channels: List[ChannelConfig],
                 start_wall: float, notes: str = ""):
        self.name = name
        self.folder = folder
        self.channels = channels
        self.start_wall = start_wall
        self.end_wall: Optional[float] = None
        self.notes = notes
        self.correction: Optional[Correction] = None    # correcao/calibracao usada (salva no config.json)
        self.events: Dict[int, List[TipEvent]] = {c: [] for c in range(1, NUM_CHANNELS + 1)}
        self.env: List[EnvSample] = []
        self.temps: Dict[str, List[TempSample]] = {}      # leituras dos DS18B20 por sensor (ROM)
        self.temp_max_age = TEMP_MAX_AGE_S                # idade maxima da leitura usada num basculamento (s)
        self._temp_file = None
        self._temp_writer = None
        self._vcor: Dict[int, float] = {c: 0.0 for c in range(1, NUM_CHANNELS + 1)}
        self._ch_files: Dict[int, object] = {}         # um arquivo por canal (S1_<nome>.csv ...)
        self._ch_writers: Dict[int, object] = {}
        self._det_file = None                           # detalhes/basculamentos.csv
        self._det_writer = None
        self.channel_files: Dict[int, str] = {}         # canal -> nome do arquivo (salvo no config.json)
        self._env_file = None
        self._env_writer = None

    # ------------------------------------------------------------------ arquivos
    @staticmethod
    def make_folder(base_dir: str, name: str, start_wall: float) -> str:
        stamp = datetime.fromtimestamp(start_wall).strftime("%Y%m%d_%H%M%S")
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.strip()) or "experimento"
        folder = os.path.join(base_dir, f"{stamp}_{safe}")
        os.makedirs(folder, exist_ok=True)
        return folder

    @staticmethod
    def _safe(name: str) -> str:
        return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.strip()) or "canal"

    def _channel_writer(self, ch: int):
        """Abre (ou cria) o arquivo do canal: S<n>_<nome>.csv, uma linha por basculamento daquele sensor."""
        if ch in self._ch_writers:
            return self._ch_writers[ch]
        fname = self.channel_files.get(ch) or f"S{ch}_{self._safe(self.channels[ch - 1].name)}.csv"
        path = os.path.join(self.folder, fname)
        new = not os.path.exists(path)
        f = open(path, "a", newline="", encoding="utf-8")
        w = csv.writer(f)
        if new:
            w.writerow(CHANNEL_FIELDS if (self.correction is None or self.correction.mode == "none")
                       else ["tempo_h", f"volume_{self.correction.unit_tag()}"])
            f.flush()
        self._ch_files[ch], self._ch_writers[ch] = f, w
        if self.channel_files.get(ch) != fname:
            self.channel_files[ch] = fname
            self.save_config()
        return w

    def open_files(self):
        if not self.folder:
            return
        env_path = os.path.join(self.folder, "ambiente.csv")
        new_env = not os.path.exists(env_path)
        self._env_file = open(env_path, "a", newline="", encoding="utf-8")
        self._env_writer = csv.writer(self._env_file)
        if new_env:
            self._env_writer.writerow(ENV_FIELDS)
        det_dir = os.path.join(self.folder, DETAIL_DIR)
        os.makedirs(det_dir, exist_ok=True)
        det_path = os.path.join(det_dir, DETAIL_FILE)
        new_det = not os.path.exists(det_path)
        self._det_file = open(det_path, "a", newline="", encoding="utf-8")
        self._det_writer = csv.writer(self._det_file)
        if new_det:
            self._det_writer.writerow(EVENT_FIELDS)
        temp_path = os.path.join(det_dir, "temperaturas_ds18b20.csv")
        new_temp = not os.path.exists(temp_path)
        self._temp_file = open(temp_path, "a", newline="", encoding="utf-8")
        self._temp_writer = csv.writer(self._temp_file)
        if new_temp:
            self._temp_writer.writerow(TEMP_FIELDS)
        # um arquivo por canal ativo ja no inicio (canais desativados ganham arquivo se basculharem)
        for ch in range(1, NUM_CHANNELS + 1):
            if self.channels[ch - 1].enabled:
                self._channel_writer(ch)
        self.save_config()

    def close_files(self):
        """Fecha os arquivos. Os arquivos de 2 colunas dos sensores sao regravados em ordem de tempo
        (eventos recuperados apos uma desconexao podem ter chegado fora de ordem)."""
        writing = self._env_writer is not None and self.folder
        for f in list(self._ch_files.values()) + [self._env_file, self._temp_file, self._det_file]:
            if f:
                f.close()
        self._ch_files.clear()
        self._ch_writers.clear()
        self._env_file = None
        self._env_writer = None
        self._temp_file = None
        self._temp_writer = None
        self._det_file = None
        self._det_writer = None
        if writing:
            for ch, fname in self.channel_files.items():
                corr = self.correction
                t, v = self.volume_series(ch, corr)
                with open(os.path.join(self.folder, fname), "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(CHANNEL_FIELDS if (corr is None or corr.mode == "none")
                               else ["tempo_h", f"volume_{corr.unit_tag()}"])
                    for ti, vi in zip(t[1:], v[1:]):
                        w.writerow([f"{ti:.6f}", f"{vi:.3f}"])

    def save_config(self):
        if not self.folder:
            return
        cfg = {
            "nome": self.name,
            "inicio": datetime.fromtimestamp(self.start_wall).isoformat(timespec="seconds"),
            "inicio_epoch": self.start_wall,
            "fim_epoch": self.end_wall,
            "observacoes": self.notes,
            "canais": [asdict(c) for c in self.channels],
            "arquivos_canais": {str(ch): fn for ch, fn in sorted(self.channel_files.items())},
        }
        if self.correction is not None:
            cfg["correcao"] = self.correction.to_dict()
        with open(os.path.join(self.folder, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, folder: str) -> "Experiment":
        with open(os.path.join(folder, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        fields = set(ChannelConfig.__dataclass_fields__)
        chans = [ChannelConfig(**{k: v for k, v in c.items() if k in fields}) for c in cfg["canais"]]
        exp = cls(cfg.get("nome", os.path.basename(folder)), folder, chans, cfg["inicio_epoch"],
                  cfg.get("observacoes", ""))
        exp.end_wall = cfg.get("fim_epoch")
        if "correcao" in cfg:
            exp.correction = Correction.from_dict(cfg["correcao"])
        exp.channel_files = {int(k): v for k, v in cfg.get("arquivos_canais", {}).items()}
        # fonte dos dados: detalhes/basculamentos.csv; versoes anteriores: S<n>_*.csv completos ou eventos.csv
        det = os.path.join(folder, DETAIL_DIR, DETAIL_FILE)
        if os.path.exists(det):
            paths = [det]
        else:
            import glob
            paths = [os.path.join(folder, fn) for fn in exp.channel_files.values()] or \
                sorted(glob.glob(os.path.join(folder, "S[1-9]_*.csv")))
            if not paths and os.path.exists(os.path.join(folder, "eventos.csv")):
                paths = [os.path.join(folder, "eventos.csv")]
        for ev_path in paths:
            if not os.path.exists(ev_path):
                continue
            with open(ev_path, encoding="utf-8") as f:
                rd = csv.DictReader(f)
                if "canal" not in (rd.fieldnames or []):
                    continue                     # arquivo de 2 colunas (tempo, volume): nao tem os dados brutos
                for r in rd:
                    wall = exp.start_wall + float(r["t_h"]) * 3600.0
                    ev = TipEvent(int(r["canal"]), wall, int(r["sessao"]), int(r["seq"]),
                                  int(r["contagem_mcu"]), int(r["t_mcu_ms"]))
                    try:
                        ev.t_c = float(r["T_C"]) if r.get("T_C") else None
                        ev.p_kpa = float(r["P_kPa"]) if r.get("P_kPa") else None
                    except ValueError:
                        pass
                    ev.t_src = r.get("fonte_T", "") or ""
                    exp.events[ev.channel].append(ev)
        temp_path = os.path.join(folder, DETAIL_DIR, "temperaturas_ds18b20.csv")
        if os.path.exists(temp_path):
            with open(temp_path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    exp.temps.setdefault(r["sensor"], []).append(
                        TempSample(exp.start_wall + float(r["t_h"]) * 3600.0, r["sensor"], float(r["T_C"])))
        env_path = os.path.join(folder, "ambiente.csv")
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    exp.env.append(EnvSample(exp.start_wall + float(r["t_h"]) * 3600.0,
                                             float(r["T_C"]), float(r["P_Pa"]), float(r["UR_pct"])))
        for lst in exp.events.values():
            lst.sort(key=lambda e: e.wall)
        return exp

    # ------------------------------------------------------------------ entrada de dados
    def _nearest(self, samples, wall: float, max_age: float):
        """Leitura mais proxima no tempo (ate max_age s de distancia) ou None."""
        best = None
        for smp in samples[-200:]:
            d = abs(smp.wall - wall)
            if d <= max_age and (best is None or d < abs(best.wall - wall)):
                best = smp
        return best

    def stamp_event(self, ev: TipEvent):
        """Registra no basculamento a temperatura e a pressao daquele instante:
        T = leitura mais recente do DS18B20 associado ao canal (ou do BME280, se o canal nao tem DS18B20
        ou ele nao respondeu no ultimo minuto); P = BME280. Esses valores sao os usados na correcao."""
        cfg = self.channels[ev.channel - 1]
        if ev.t_c is None and cfg.temp_sensor and cfg.temp_sensor in self.temps:
            t = self._nearest(self.temps[cfg.temp_sensor], ev.wall, self.temp_max_age)
            if t is not None:
                ev.t_c, ev.t_src = t.t_c, cfg.temp_sensor
        e = self._nearest(self.env, ev.wall, 3 * self.temp_max_age) if self.env else None
        if e is not None:
            if ev.t_c is None:
                ev.t_c, ev.t_src = e.t_c, "BME280"
            if ev.p_kpa is None:
                ev.p_kpa = e.p_pa / 1000.0

    def add_event(self, ev: TipEvent):
        self.stamp_event(ev)
        lst = self.events[ev.channel]
        # eventos recuperados (GET) podem chegar fora de ordem
        if lst and ev.wall < lst[-1].wall:
            i = len(lst)
            while i > 0 and lst[i - 1].wall > ev.wall:
                i -= 1
            lst.insert(i, ev)
        else:
            lst.append(ev)
        if self._env_writer is not None:        # gravando
            writer = self._channel_writer(ev.channel)
            cfg = self.channels[ev.channel - 1]
            n = len(lst)
            k = cfg.ml_per_tip
            f_i = float(self._factors_for([ev], self.correction)[0])
            self._vcor[ev.channel] += k * f_i
            t_h = (ev.wall - self.start_wall) / 3600.0
            writer.writerow([f"{t_h:.6f}", f"{self._vcor[ev.channel]:.3f}"])
            self._det_writer.writerow([
                datetime.fromtimestamp(ev.wall).isoformat(timespec="milliseconds"),
                f"{t_h:.7f}",
                ev.channel, cfg.name, n,
                f"{ev.t_c:.2f}" if ev.t_c is not None else "", ev.t_src,
                f"{ev.p_kpa:.3f}" if ev.p_kpa is not None else "",
                f"{k:.4f}", f"{f_i:.5f}", f"{n * k:.3f}", f"{self._vcor[ev.channel]:.3f}",
                ev.session, ev.seq, ev.mcu_count, ev.mcu_t_ms])
            self._ch_files[ev.channel].flush()
            self._det_file.flush()

    def add_temp(self, t: TempSample):
        self.temps.setdefault(t.rom, []).append(t)
        if self._temp_writer is not None:
            self._temp_writer.writerow([datetime.fromtimestamp(t.wall).isoformat(timespec="seconds"),
                                        f"{(t.wall - self.start_wall) / 3600.0:.7f}", t.rom, f"{t.t_c:.2f}"])
            self._temp_file.flush()

    def add_env(self, s: EnvSample):
        self.env.append(s)
        if self._env_writer:
            self._env_writer.writerow([
                datetime.fromtimestamp(s.wall).isoformat(timespec="seconds"),
                f"{(s.wall - self.start_wall) / 3600.0:.7f}",
                f"{s.t_c:.2f}", f"{s.p_pa:.0f}", f"{s.rh:.1f}"])
            self._env_file.flush()

    # ------------------------------------------------------------------ calculos
    def tip_count(self, ch: int) -> int:
        return len(self.events[ch])

    def has_env(self) -> bool:
        """Ha alguma fonte de temperatura (BME280 ou DS18B20) neste experimento?"""
        return bool(self.env) or bool(self.temps) or any(e.t_c is not None for l in self.events.values() for e in l)

    @staticmethod
    def _factors_for(evs: List[TipEvent], corr: Optional[Correction]) -> np.ndarray:
        """F_i de cada basculamento com a T e a P REGISTRADAS nele (1 se nao ha correcao ou temperatura)."""
        n = len(evs)
        if corr is None or corr.mode == "none" or n == 0:
            return np.ones(n)
        t = np.array([e.t_c if e.t_c is not None else np.nan for e in evs], dtype=float)
        p = np.array([e.p_kpa if e.p_kpa is not None else corr.p_ref_kpa for e in evs], dtype=float)
        ok = ~np.isnan(t)
        F = np.ones(n)
        if ok.any():
            F[ok] = corr.factors(t[ok], p[ok])
        return F

    def correction_factors(self, ch: int, corr: Optional[Correction]) -> np.ndarray:
        return self._factors_for(self.events[ch], corr)

    def volume_series(self, ch: int, corr: Optional[Correction] = None):
        """(t_h, V acumulado) com um ponto por basculamento, comecando em 0:  V(t_n) = k * soma(F_i)."""
        evs = self.events[ch]
        k = self.channels[ch - 1].ml_per_tip
        walls = np.array([e.wall for e in evs], dtype=float)
        dv = k * self.correction_factors(ch, corr)
        t = np.concatenate([[0.0], (walls - self.start_wall) / 3600.0])
        v = np.concatenate([[0.0], np.cumsum(dv)])
        return t, v

    def flow_series(self, ch: int, n_avg: int = 3, corr: Optional[Correction] = None):
        """
        Vazao (mL/h) por media movel de n_avg basculamentos:
        Q_i = soma(dV dos ultimos n_avg) / (t_i - t_{i-n_avg}). Ponto plotado no meio do intervalo.
        """
        t, v = self.volume_series(ch, corr)
        t_ev, v_ev = t[1:], v[1:]
        n = max(1, int(n_avg))
        if len(t_ev) <= n:
            return np.array([]), np.array([])
        dt = t_ev[n:] - t_ev[:-n]
        dv = v_ev[n:] - v_ev[:-n]
        ok = dt > 0
        tm = 0.5 * (t_ev[n:] + t_ev[:-n])
        return tm[ok], dv[ok] / dt[ok]

    def current_flow(self, ch: int, now: float, n_avg: int = 3, corr: Optional[Correction] = None) -> float:
        """Vazao atual estimada (mL/h). Se o ultimo basculamento esta 'atrasado', usa o tempo ate agora."""
        evs = self.events[ch]
        if len(evs) < 2:
            return 0.0
        n = min(max(1, n_avg), len(evs) - 1)
        t, v = self.volume_series(ch, corr)
        dt_h = (evs[-1].wall - evs[-1 - n].wall) / 3600.0
        q = (v[-1] - v[-1 - n]) / dt_h if dt_h > 0 else 0.0
        since_last_h = (now - evs[-1].wall) / 3600.0
        mean_interval_h = dt_h / n if n else 0
        if mean_interval_h > 0 and since_last_h > mean_interval_h:
            # sem basculamento ha mais tempo que o intervalo medio: limite superior da vazao atual
            q = min(q, (v[-1] - v[-2]) / since_last_h)
        return q

    # ------------------------------------------------------------------ exportacao
    def export_resampled(self, path: str, interval_min: float, corr: Optional[Correction] = None,
                         end_wall: Optional[float] = None):
        """CSV com volume acumulado de todos os canais numa grade de tempo regular."""
        end = end_wall or self.end_wall or max(
            [self.start_wall] + [e[-1].wall for e in self.events.values() if e])
        t_end_h = max(0.0, (end - self.start_wall) / 3600.0)
        step_h = interval_min / 60.0
        grid = np.arange(0.0, t_end_h + 1e-9, step_h)
        cols = {}
        for ch in range(1, NUM_CHANNELS + 1):
            t, v = self.volume_series(ch, corr)
            # volume acumulado e uma funcao degrau: ultimo valor <= instante
            idx = np.searchsorted(t, grid, side="right") - 1
            cols[ch] = v[np.clip(idx, 0, len(v) - 1)]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            unit = corr.unit_tag() if corr is not None else "mL"
            hdr = ["t_h"]
            for ch in range(1, NUM_CHANNELS + 1):
                nm = self.channels[ch - 1].name
                hdr += [f"V{ch}_{unit} ({nm})", f"Q{ch}_{unit}_por_h ({nm})"]
            w.writerow(hdr)
            for i, tg in enumerate(grid):
                row = [f"{tg:.4f}"]
                for ch in range(1, NUM_CHANNELS + 1):
                    v_now = cols[ch][i]
                    v_prev = cols[ch][i - 1] if i > 0 else 0.0
                    q = (v_now - v_prev) / step_h if i > 0 else 0.0
                    row += [f"{v_now:.3f}", f"{q:.3f}"]
                w.writerow(row)

    def export_events(self, folder: str, corr: Optional[Correction] = None, prefix: str = "volume") -> List[str]:
        """
        Um CSV por canal (<prefix>_S<n>_<nome>.csv) com duas colunas: tempo (h) e volume acumulado,
        recalculado com os k e a correcao informados (uma linha por basculamento). Retorna os arquivos.
        """
        os.makedirs(folder, exist_ok=True)
        unit = corr.unit_tag() if corr is not None else "mL"
        out = []
        for ch in range(1, NUM_CHANNELS + 1):
            if not self.events[ch]:
                continue
            t, v = self.volume_series(ch, corr)
            path = os.path.join(folder, f"{prefix}_S{ch}_{self._safe(self.channels[ch - 1].name)}.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["tempo_h", f"volume_{unit}"])
                for ti, vi in zip(t[1:], v[1:]):
                    w.writerow([f"{ti:.6f}", f"{vi:.3f}"])
            out.append(path)
        return out
