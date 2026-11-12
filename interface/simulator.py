"""
simulator.py
Simulador do firmware do medidor (mesmo protocolo de texto do STM32), para desenvolver e
testar a interface sem hardware.

Cada canal segue uma curva de producao de gas do tipo Gompertz modificada
    V(t) = Vmax * exp(-exp(Rm*e/Vmax * (lag - t) + 1))
com parametros sorteados. O volume real por basculamento de cada celula difere um pouco do
fator nominal (para exercitar a calibracao), e o intervalo entre basculamentos tem ruido.

Recursos de teste: aceleracao do tempo, desconexao temporaria, reinicio do "MCU",
perda de linhas pela USB e sensor ambiental (T e P) com variacao diaria.
"""
from __future__ import annotations

import math
import random
import time
from typing import Callable, List, Optional

NUM_CHANNELS = 9


class _SimChannel:
    def __init__(self, idx: int, rng: random.Random):
        self.idx = idx
        self.enabled = idx < 7 or rng.random() < 0.5         # alguns canais podem ficar vazios
        self.vmax = rng.uniform(300, 1500)                    # mL
        self.rm = rng.uniform(15, 80)                         # mL/h
        self.lag = rng.uniform(0.2, 3.0)                      # h
        self.true_tip_ml = 10.0 * rng.uniform(0.94, 1.06)     # volume real por basculamento
        self.next_tip = 1
        self.count = 0
        self.jitter = 0.0
        self._rng = rng

    def volume(self, t_h: float) -> float:
        if not self.enabled or t_h <= 0:
            return 0.0
        e = math.e
        return self.vmax * math.exp(-math.exp(self.rm * e / self.vmax * (self.lag - t_h) + 1.0))

    def tip_threshold(self) -> float:
        return self.next_tip * self.true_tip_ml + self.jitter


class SimulatedDevice:
    """
    Emula o STM32: chame tick() periodicamente; as linhas geradas sao entregues a on_line(str).
    Comandos do PC entram por write(str).
    """

    def __init__(self, seed: Optional[int] = None, speed: float = 60.0, line_loss: float = 0.0):
        self.rng = random.Random(seed)
        self.on_line: Callable[[str], None] = lambda s: None
        self.speed = speed                    # 60 = 1 minuto real corresponde a 1 hora simulada
        self.line_loss = line_loss            # probabilidade de perder uma linha EV (testa o GET)
        self._real0 = time.time()
        self._sim0 = time.time()
        self.lockout_ms = 2000
        # tres DS18B20 simulados no barramento 1-Wire (codigos ROM ficticios, familia 0x28)
        self.ds_roms = ["28FF4A1B2C0300A1", "28FF7C3D5E0400B2", "28FF9E5F700500C3"]
        self.ds_offset = [6.0, 6.8, 5.5]       # gas em fermentacao um pouco mais quente que o ar
        self.pol_mask = 0
        self._boot()
        self.connected = True
        self._disconnect_until = 0.0
        self._next_st = 0
        self._next_env = 0
        self._next_tmp = 0
        self._last_t_ms = 0

    # ------------------------------------------------------------------ relogio simulado
    def clock(self) -> float:
        """Tempo 'de parede' simulado (epoch s), acelerado por speed."""
        return self._sim0 + (time.time() - self._real0) * self.speed

    def set_speed(self, speed: float):
        now = self.clock()
        self._real0 = time.time()
        self._sim0 = now
        self.speed = max(0.1, float(speed))

    def _t_ms(self) -> int:
        return int((self.clock() - self._boot_wall) * 1000)

    # ------------------------------------------------------------------ estado do "MCU"
    def _boot(self):
        self._boot_wall = self.clock()
        self.channels: List[_SimChannel] = [_SimChannel(i, self.rng) for i in range(NUM_CHANNELS)]
        self._proc_t0 = getattr(self, "_proc_t0", self._boot_wall)   # o processo continua apos reset
        self.log: List[tuple] = []            # (seq, ch, count, t_ms)
        self.next_seq = 0
        self._next_st = 0
        self._next_env = 0
        self._next_tmp = 0

    def reset_mcu(self):
        """Simula reinicio do microcontrolador (contagens e numeracao voltam a zero)."""
        saved = [(c.vmax, c.rm, c.lag, c.true_tip_ml, c.enabled, c.next_tip) for c in self.channels]
        self._boot()
        for c, s in zip(self.channels, saved):
            c.vmax, c.rm, c.lag, c.true_tip_ml, c.enabled, c.next_tip = s
        self._emit(f"HELLO,TIPGAS,1.0.0-sim,{NUM_CHANNELS}", force=True)

    def disconnect_for(self, seconds_real: float):
        """Simula cabo USB desconectado / PC suspenso por alguns segundos (tempo real)."""
        self._disconnect_until = time.time() + seconds_real

    # ------------------------------------------------------------------ comunicacao
    def _emit(self, line: str, force: bool = False):
        if time.time() < self._disconnect_until and not force:
            return
        self.on_line(line)

    def write(self, cmd: str):
        for c in cmd.replace("\r", "\n").split("\n"):
            c = c.strip()
            if c:
                self._command(c)

    def _command(self, c: str):
        if time.time() < self._disconnect_until:
            return
        if c == "ID?":
            self._emit(f"ID,TIPGAS,1.0.0-sim,SIMULADOR000000000000000,{NUM_CHANNELS},"
                       f"{self.lockout_ms},BME280,{self.pol_mask},{len(self.ds_roms)}")
        elif c == "ST?":
            self._status()
        elif c.startswith("GET,"):
            frm = int(c[4:])
            oldest = max(0, self.next_seq - 2048)
            if frm < oldest:
                self._emit(f"LOST,{frm},{oldest}")
                frm = oldest
            end = self.next_seq
            for seq, ch, cnt, t in self.log:
                if frm <= seq < end:
                    self._emit(f"EV,{seq},{ch},{cnt},{t}")
            self._emit(f"GETEND,{end - 1}")
        elif c == "RST":
            for ch in self.channels:
                ch.count = 0
            self._emit("OK,RST")
            self._status()
        elif c.startswith("DEB,"):
            v = int(c[4:])
            if 20 <= v <= 10000:
                self.lockout_ms = v
                self._emit(f"OK,DEB,{v}")
            else:
                self._emit("ERR,DEB fora da faixa 20..10000")
        elif c.startswith("POL,"):
            try:
                v = int(c[4:])
            except ValueError:
                v = -1
            if 0 <= v < (1 << NUM_CHANNELS):
                self.pol_mask = v
                self._emit(f"OK,POL,{v}")
            else:
                self._emit("ERR,POL fora da faixa 0..511")
        else:
            self._emit(f"ERR,comando desconhecido: {c}")

    def _status(self):
        counts = ",".join(str(c.count) for c in self.channels)
        self._emit(f"ST,{self._t_ms()},{self.next_seq},{counts}")

    # ------------------------------------------------------------------ simulacao
    def tick(self):
        t_ms = self._t_ms()
        t_h = (self.clock() - self._proc_t0) / 3600.0
        prev_t_ms = self._last_t_ms if self._last_t_ms <= t_ms else 0
        new_events = []
        for ch in self.channels:
            v = ch.volume(t_h)
            while v >= ch.tip_threshold():
                # instante aproximado do basculamento (interpolacao linear no passo atual)
                vprev = ch.volume(t_h - (t_ms - prev_t_ms) / 3.6e6)
                frac = 1.0 if v <= vprev else (ch.tip_threshold() - vprev) / (v - vprev)
                t_ev = int(prev_t_ms + max(0.0, min(1.0, frac)) * (t_ms - prev_t_ms))
                ch.count += 1
                ch.next_tip += 1
                ch.jitter = self.rng.gauss(0, 0.04 * ch.true_tip_ml)
                new_events.append((t_ev, ch))
        new_events.sort(key=lambda x: x[0])
        for t_ev, ch in new_events:
            rec = (self.next_seq, ch.idx + 1, ch.count, t_ev)
            self.log.append(rec)
            if len(self.log) > 2048:
                self.log.pop(0)
            self.next_seq += 1
            if self.rng.random() >= self.line_loss:
                self._emit("EV,%d,%d,%d,%d" % rec)
        self._last_t_ms = t_ms

        if t_ms >= self._next_st:
            self._next_st = t_ms + 1000
            self._status()
        if t_ms >= self._next_env:
            self._next_env = t_ms + 5000
            day = (self.clock() % 86400) / 86400.0
            t_c = 24.0 + 3.0 * math.sin(2 * math.pi * (day - 0.375)) + self.rng.gauss(0, 0.05)
            p = 92500 + 300 * math.sin(2 * math.pi * day * 2) + self.rng.gauss(0, 5)
            rh = 55 + 10 * math.sin(2 * math.pi * day) + self.rng.gauss(0, 0.3)
            self._emit(f"ENV,{t_ms},{t_c:.2f},{p:.0f},{rh:.1f}")
        if t_ms >= self._next_tmp:
            self._next_tmp = t_ms + 2000
            day = (self.clock() % 86400) / 86400.0
            base = 24.0 + 3.0 * math.sin(2 * math.pi * (day - 0.375))
            for i, rom in enumerate(self.ds_roms):
                t = base + self.ds_offset[i] + self.rng.gauss(0, 0.03)
                self._emit(f"TMP,{t_ms},{i + 1},{rom},{t:.2f}")
