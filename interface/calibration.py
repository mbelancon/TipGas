"""
calibration.py
Assistente de calibracao do fator k (mL por basculamento) de cada celula.

Procedimento:
  1. Escolher os canais e clicar em "Iniciar contagem".
  2. Injetar em cada celula um volume conhecido de gas (seringa, bureta invertida, controlador de
     vazao), de preferencia a uma vazao parecida com a dos experimentos.
  3. Informar o volume injetado em cada canal e clicar em "Calcular".
     k = V_injetado / n_basculamentos;   incerteza de contagem ~ +/- 1 basculamento (1/n).
  4. "Aplicar" copia os k para os canais e, opcionalmente, define T_ref e P_ref como a media
     medida durante a calibracao (referencia da correcao pelo metodo do artigo).
Cada calibracao aplicada e salva em <pasta de dados>/calibracoes/calibracao_AAAAMMDD_HHMMSS.csv.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from i18n import tr
from tipgas_core import NUM_CHANNELS, EnvSample, TempSample, TipEvent

MIN_TIPS_RECOMMENDED = 20


class CalibrationDialog(QDialog):
    COL_USE, COL_CH, COL_N, COL_V, COL_K, COL_UNC, COL_KOLD = range(7)

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(tr('Calibração dos fatores k'))
        self.resize(760, 520)
        self.running = False
        self.t0: Optional[float] = None
        self.counts: Dict[int, int] = {c: 0 for c in range(1, NUM_CHANNELS + 1)}
        self.env: List[EnvSample] = []
        self.ds: List[TempSample] = []
        self.results: Dict[int, float] = {}

        v = QVBoxLayout(self)
        intro = QLabel(
            tr('<b>Como calibrar</b><br>1. Marque os canais e clique em <b>Iniciar contagem</b>.<br>2. Injete em cada célula um volume conhecido de gás (seringa, bureta, controlador de vazão), de preferência numa vazão parecida com a dos experimentos.<br>3. Informe o volume injetado e clique em <b>Calcular</b>. Use volume suficiente para pelo menos <b>{0} basculamentos</b>: a contagem tem incerteza de ±1 basculamento.<br>4. <b>Aplicar</b> copia os k para os canais. A temperatura e a pressão médias da calibração podem virar a referência (T_ref, P_ref) da correção.').format(MIN_TIPS_RECOMMENDED))
        intro.setWordWrap(True)
        v.addWidget(intro)

        self.table = QTableWidget(NUM_CHANNELS, 7)
        self.table.setHorizontalHeaderLabels([tr('Usar'), tr('Canal'), tr('Basculamentos'), tr('Volume injetado (mL)'),
                                              tr('k medido (mL/basc.)'), tr('Incerteza'), tr('k atual')])
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(self.COL_CH, QHeaderView.Stretch)
        self.vol_spins = []
        for i in range(NUM_CHANNELS):
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            use.setCheckState(Qt.Checked if main.channels[i].enabled else Qt.Unchecked)
            self.table.setItem(i, self.COL_USE, use)
            for col in (self.COL_CH, self.COL_N, self.COL_K, self.COL_UNC, self.COL_KOLD):
                it = QTableWidgetItem("")
                it.setFlags(Qt.ItemIsEnabled)
                if col != self.COL_CH:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, col, it)
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 100000.0)
            sp.setDecimals(2)
            sp.setValue(200.0)
            self.vol_spins.append(sp)
            self.table.setCellWidget(i, self.COL_V, sp)
        v.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr('Mesmo volume para todos:')))
        self.all_vol = QDoubleSpinBox()
        self.all_vol.setRange(0.0, 100000.0)
        self.all_vol.setDecimals(2)
        self.all_vol.setValue(200.0)
        self.all_vol.setSuffix(" mL")
        row.addWidget(self.all_vol)
        b_all = QPushButton(tr('Copiar para todos'))
        b_all.clicked.connect(lambda: [sp.setValue(self.all_vol.value()) for sp in self.vol_spins])
        row.addWidget(b_all)
        row.addStretch(1)
        self.env_lbl = QLabel(tr('T/P médias: —'))
        row.addWidget(self.env_lbl)
        v.addLayout(row)

        self.ref_check = QCheckBox(tr('Usar a temperatura e a pressão médias da calibração como T_ref e P_ref'))
        self.ref_check.setChecked(True)
        v.addWidget(self.ref_check)

        brow = QHBoxLayout()
        self.state_lbl = QLabel(tr('Parado'))
        self.state_lbl.setStyleSheet("font-weight:600;")
        brow.addWidget(self.state_lbl, 1)
        self.b_start = QPushButton(tr('Iniciar contagem'))
        self.b_start.clicked.connect(self.start)
        self.b_calc = QPushButton(tr("Calcular"))
        self.b_calc.clicked.connect(self.calculate)
        self.b_apply = QPushButton(tr('Aplicar aos canais'))
        self.b_apply.clicked.connect(self.apply)
        self.b_apply.setEnabled(False)
        b_close = QPushButton(tr('Fechar'))
        b_close.clicked.connect(self.hide)
        for b in (self.b_start, self.b_calc, self.b_apply, b_close):
            brow.addWidget(b)
        v.addLayout(brow)
        self.refresh()

    # ------------------------------------------------------------------ dados ao vivo
    def on_event(self, ev: TipEvent):
        if self.running and self.t0 is not None and ev.wall >= self.t0:
            self.counts[ev.channel] += 1
            self.refresh()

    def on_env(self, s: EnvSample):
        if self.running:
            self.env.append(s)
            self.refresh()

    def on_temp(self, t: TempSample):
        if self.running:
            self.ds.append(t)

    def _env_means(self):
        """T media: dos DS18B20 associados aos canais calibrados (temperatura do gas); sem eles, do BME280.
        P media: do BME280."""
        roms = {self.main.channels[ch - 1].temp_sensor for ch in self._selected()} - {""}
        ds = [d.t_c for d in self.ds if d.rom in roms]
        t = sum(ds) / len(ds) if ds else (sum(e.t_c for e in self.env) / len(self.env) if self.env else None)
        p = sum(e.p_pa for e in self.env) / len(self.env) / 1000.0 if self.env else None
        self._t_src = "DS18B20" if ds else "BME280"
        return t, p

    def refresh(self):
        for i in range(NUM_CHANNELS):
            ch = i + 1
            cfg = self.main.channels[i]
            self.table.item(i, self.COL_CH).setText(f"S{ch} – {cfg.name}")
            self.table.item(i, self.COL_N).setText(str(self.counts[ch]))
            self.table.item(i, self.COL_KOLD).setText(f"{cfg.ml_per_tip:.4f}")
        t, p = self._env_means()
        if t is None:
            self.env_lbl.setText(tr('T/P médias: sem sensor de temperatura'))
        else:
            ptxt = tr(' · P média {0:.3f} kPa').format(p) if p is not None else tr(' · sem pressão (use P_ref)')
            self.env_lbl.setText(tr('T média {0:.2f} °C ({1}){2}').format(t, self._t_src, ptxt))

    # ------------------------------------------------------------------ acoes
    def start(self):
        if self.main.link is None:
            QMessageBox.information(self, tr('Calibração'), tr("Conecte o medidor primeiro."))
            return
        self.t0 = self.main.link.clock()
        self.counts = {c: 0 for c in range(1, NUM_CHANNELS + 1)}
        self.env = [self.main.last_env] if self.main.last_env is not None else []
        self.ds = list(getattr(self.main, "ds_latest", {}).values())
        self.results = {}
        for i in range(NUM_CHANNELS):
            for col in (self.COL_K, self.COL_UNC):
                self.table.item(i, col).setText("")
        self.running = True
        self.b_start.setText(tr("Reiniciar contagem"))
        self.b_apply.setEnabled(False)
        self.state_lbl.setText(tr('Contando desde {0:%H:%M:%S} — injete o volume conhecido').format(datetime.now()))
        self.main._log(tr('Calibração: contagem iniciada'), "info")
        self.refresh()

    def _selected(self):
        return [i + 1 for i in range(NUM_CHANNELS)
                if self.table.item(i, self.COL_USE).checkState() == Qt.Checked]

    def calculate(self):
        if self.t0 is None:
            QMessageBox.information(self, tr('Calibração'), tr('Clique em “Iniciar contagem” antes de injetar o gás.'))
            return
        self.results = {}
        few = []
        for ch in self._selected():
            i = ch - 1
            n = self.counts[ch]
            vol = self.vol_spins[i].value()
            if n <= 0 or vol <= 0:
                self.table.item(i, self.COL_K).setText("—")
                self.table.item(i, self.COL_UNC).setText("")
                continue
            k = vol / n
            self.results[ch] = k
            self.table.item(i, self.COL_K).setText(f"{k:.4f}")
            self.table.item(i, self.COL_UNC).setText(f"±{100.0 / n:.1f} %")
            if n < MIN_TIPS_RECOMMENDED:
                few.append(f"S{ch}")
        self.b_apply.setEnabled(bool(self.results))
        msg = tr('{0} canal(is) calculado(s)').format(len(self.results))
        if few:
            msg += tr(' · poucos basculamentos em {0} (incerteza alta)').format(', '.join(few))
        self.state_lbl.setText(msg)

    def apply(self):
        if not self.results:
            return
        t, p = self._env_means()
        use_ref = self.ref_check.isChecked() and t is not None
        if p is None:
            p = self.main.pref_spin.value()       # sem BME280: mantem o P_ref atual
        txt = "\n".join(tr('S{0}: {1:.4f} → {2:.4f} mL/basc.').format(ch, self.main.channels[ch - 1].ml_per_tip, k)
                        for ch, k in sorted(self.results.items()))
        if use_ref:
            txt += f"\n\nT_ref = {t:.2f} °C · P_ref = {p:.3f} kPa"
        if QMessageBox.question(self, tr('Calibração'), tr('Aplicar os novos fatores?\n\n{0}').format(txt)) != QMessageBox.Yes:
            return
        path = self._save_record(t, p)
        self.main.apply_calibration(dict(self.results), t if use_ref else None, p if use_ref else None)
        self.running = False
        self.state_lbl.setText(tr("Aplicado e salvo em {0}").format(os.path.basename(path)) if path else tr("Aplicado"))
        self.b_apply.setEnabled(False)
        self.refresh()

    def _save_record(self, t: Optional[float], p: Optional[float]) -> Optional[str]:
        folder = os.path.join(self.main.data_dir, "calibracoes")
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"calibracao_{datetime.now():%Y%m%d_%H%M%S}.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["data_hora", "canal", "nome", "basculamentos", "volume_injetado_mL", "k_mL_por_basc",
                            "incerteza_contagem_pct", "k_anterior", "T_media_C", "P_media_kPa", "leituras_T_P"])
                for ch, k in sorted(self.results.items()):
                    n = self.counts[ch]
                    w.writerow([datetime.now().isoformat(timespec="seconds"), ch, self.main.channels[ch - 1].name,
                                n, f"{self.vol_spins[ch - 1].value():.2f}", f"{k:.5f}", f"{100.0 / n:.2f}",
                                f"{self.main.channels[ch - 1].ml_per_tip:.5f}",
                                f"{t:.2f}" if t is not None else "", f"{p:.3f}" if p is not None else "",
                                len(self.env)])
            self.main._log(tr('Calibração salva: {0}').format(path), "info")
            return path
        except OSError as e:
            QMessageBox.warning(self, tr('Calibração'), tr('Não foi possível salvar o registro da calibração:\n{0}').format(e))
            return None
