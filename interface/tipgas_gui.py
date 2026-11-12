"""
tipgas_gui.py - TipGas graphical interface (9-channel tipping-bucket gas meter, STM32F411 Black Pill).

Run:   python TipGas.py          (or  python TipGas.py --sim  to start in simulation mode)
Requisitos: pip install -r requirements.txt   (PySide6, pyqtgraph, pyserial, numpy)
"""
from __future__ import annotations

import json
from collections import deque
import os
import sys
import threading
import time
from datetime import datetime
from typing import Optional

import numpy as np
import pyqtgraph as pg
import serial
import serial.tools.list_ports
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QObject, QUrl, QSize
from PySide6.QtGui import QColor, QFont, QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
    QStyle, QFrame, QTabWidget, QDialog, QDialogButtonBox, QGridLayout, QToolButton, QMenu, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from tipgas_core import (
    APP_VERSION,
    NUM_CHANNELS, ChannelConfig, DeviceLink, EnvSample, Experiment, TipEvent, default_channels, pol_mask,
    Correction, CORRECTION_MODES, TempSample,
)
from i18n import tr, LANGUAGES
from calibration import CalibrationDialog
from simulator import SimulatedDevice

APP_NAME = "TipGas"
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".tipgas.json")
OLD_SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".medidor_vazao_gas.json")   # versoes de teste
COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
          "#8c564b", "#e377c2", "#17becf", "#bcbd22"]
TIME_UNITS = {"min": 60.0, "h": 1.0, "dias": 1.0 / 24.0}   # multiplicador a partir de horas
# cores de fundo das mensagens na barra de status
ST_OK = "#e6ffe6"       # conectado, tudo normal
ST_REC = "#d9f2ff"      # gravando
ST_WARN = "#fff3cd"     # aviso
ST_ALERT = "#ffd6d6"    # erro / sem comunicacao
ST_IDLE = "#eeeeee"     # desconectado
ST_VIEW = "#ece6ff"     # visualizando experimento salvo
FLASH_S = {"event": 4.0, "warn": 10.0, "error": 15.0}
FLASH_COLOR = {"event": ST_OK, "warn": ST_WARN, "error": ST_ALERT}
DEFAULT_LOCKOUT_MS = 2000      # bloqueio padrao entre basculamentos do mesmo canal
LEVEL_TAG = {"info": "INFO ", "event": tr("EVENTO"), "warn": tr("AVISO"), "error": tr("ERRO ")}

SIM_SPEEDS = [(tr('1× (tempo real)'), 1), ("10×", 10), ("60× (1 min = 1 h)", 60),
              ("600× (1 min = 10 h)", 600), ("3600× (1 s = 1 h)", 3600)]


# =========================================================================== transportes
class SerialTransport(QThread):
    """Le a porta serial em uma thread; reconecta sozinho se o cabo for desconectado."""
    line = Signal(str)
    state = Signal(bool, str)          # conectado?, mensagem

    def __init__(self, port: str):
        super().__init__()
        self.port = port
        self._stop = False
        self._ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()

    def run(self):
        buf = b""
        while not self._stop:
            try:
                with self._lock:
                    self._ser = serial.Serial(self.port, 115200, timeout=0.2)
                    self._ser.dtr = True
                self.state.emit(True, tr('Conectado em {0}').format(self.port))
                buf = b""
                while not self._stop:
                    data = self._ser.read(4096)
                    if data:
                        buf += data
                        while b"\n" in buf:
                            ln, buf = buf.split(b"\n", 1)
                            self.line.emit(ln.decode("ascii", "replace").strip())
            except (serial.SerialException, OSError) as e:
                self.state.emit(False, tr("{0}: {1}. Tentando reconectar…").format(self.port, e))
            finally:
                with self._lock:
                    if self._ser:
                        try:
                            self._ser.close()
                        except Exception:
                            pass
                    self._ser = None
            for _ in range(20):                     # espera 2 s antes de tentar de novo
                if self._stop:
                    break
                time.sleep(0.1)
        self.state.emit(False, tr('Desconectado'))

    def write(self, text: str):
        with self._lock:
            if self._ser and self._ser.is_open:
                try:
                    self._ser.write((text + "\n").encode("ascii"))
                except (serial.SerialException, OSError):
                    pass

    def stop(self):
        self._stop = True
        self.wait(3000)


class SimTransport(QObject):
    """Mesmo papel do SerialTransport, mas alimentado pelo simulador."""
    line = Signal(str)
    state = Signal(bool, str)

    def __init__(self, sim: SimulatedDevice):
        super().__init__()
        self.sim = sim
        self.sim.on_line = self.line.emit
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.sim.tick)

    def start(self):
        self.timer.start(50)
        self.state.emit(True, tr('Simulação em execução'))
        self.line.emit("HELLO,TIPGAS,1.0.0-sim,9")

    def write(self, text: str):
        self.sim.write(text)

    def stop(self):
        self.timer.stop()
        self.state.emit(False, tr('Simulação parada'))


# =========================================================================== estilo
STYLE = """
QMainWindow { background: #eef2f7; }
QFrame#topPanel { background: #f8fafc; border: 1px solid #c9d3df; border-radius: 8px; }
QFrame#chPanel { background: #ffffff; border: 1px solid #c9d3df; border-radius: 8px; }
QFrame#chPanel[off="true"] { background: #f4f4f4; }
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox { padding: 2px 4px; }
QPushButton#badge { background: #1f5fae; color: white; font-weight: 700; border: none;
                    border-radius: 4px; padding: 2px 8px; min-width: 28px; }
QPushButton#badge:!checked { background: #9aa5b1; }
QLabel#readout { background: #eef3fb; border: 1px solid #c9d3df; border-radius: 4px; padding: 2px 6px;
                 font-weight: 600; }
QPushButton#connect { background: #dbe8fb; border: 1px solid #5b8fd6; border-radius: 5px;
                      padding: 4px 14px; font-weight: 600; color: #1f4f96; }
QPushButton#connect:checked { background: #1f5fae; color: white; }
QPushButton#startBtn { background: #1e9e3e; color: white; font-size: 12pt; font-weight: 700;
                       border: none; border-radius: 6px; padding: 8px 22px; }
QPushButton#startBtn:hover { background: #22b347; }
QPushButton#startBtn:disabled { background: #9fd3ad; }
QPushButton#startBtn[rec="true"] { background: #c0392b; }
QPushButton#startBtn[rec="true"]:hover { background: #d64535; }
QToolButton#tool { border: 1px solid #c9d3df; border-radius: 6px; background: #ffffff; padding: 4px 10px; }
QToolButton#tool:hover { background: #eef3fb; }
QToolButton#pol { border: 1px solid #c9d3df; border-radius: 4px; background: #ffffff; min-width: 22px; }
QStatusBar { background: #f8fafc; border-top: 1px solid #c9d3df; }
QStatusBar::item { border: none; }
"""

GRAPH_MODES = [(tr('Volume acumulado'), "vol"), (tr('Vazão'), "flow")]


def _vline():
    f = QFrame()
    f.setFrameShape(QFrame.VLine)
    f.setStyleSheet("color:#c9d3df;")
    return f


# =========================================================================== painel de um canal
class ChannelPanel(QFrame):
    """Cabecalho (S1, nome, volume, fator de calibracao, polaridade) + grafico do canal."""
    changed = Signal(int, str)          # (indice, campo alterado)

    def __init__(self, idx: int, cfg: ChannelConfig):
        super().__init__()
        self.idx = idx
        self.setObjectName("chPanel")
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 4)
        v.setSpacing(2)

        h = QHBoxLayout()
        h.setSpacing(5)
        self.badge = QPushButton(f"S{idx + 1}")
        self.badge.setObjectName("badge")
        self.badge.setCheckable(True)
        self.badge.setToolTip(tr('Clique para ativar/desativar este canal'))
        self.badge.toggled.connect(lambda on: self._emit("enabled"))
        h.addWidget(self.badge)
        self.name = QLineEdit()
        self.name.setMinimumWidth(70)
        self.name.setToolTip(tr('Nome do reator / amostra'))
        self.name.editingFinished.connect(lambda: self._emit("name"))
        h.addWidget(self.name, 1)
        self.readout = QLabel("0.0 mL")
        self.readout.setObjectName("readout")
        self.readout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.readout.setMinimumWidth(78)
        self.readout.setToolTip(tr('Volume acumulado'))
        h.addWidget(self.readout)
        lbl = QLabel("FC:")
        lbl.setToolTip(tr('Fator de calibração: mL por basculamento'))
        h.addWidget(lbl)
        self.cf = QDoubleSpinBox()
        self.cf.setDecimals(3)
        self.cf.setRange(0.001, 10000)
        self.cf.setSingleStep(0.1)
        self.cf.setKeyboardTracking(False)
        self.cf.setToolTip(tr('Fator de calibração: mL por basculamento'))
        self.cf.valueChanged.connect(lambda _: self._emit("cf"))
        h.addWidget(self.cf)
        self.pol = QToolButton()
        self.pol.setObjectName("pol")
        self.pol.setCheckable(True)
        self.pol.toggled.connect(self._pol_toggled)
        h.addWidget(self.pol)
        v.addLayout(h)

        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(120)
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        f = QFont()
        f.setPointSize(8)
        for ax in ("left", "bottom"):
            a = self.plot.getAxis(ax)
            a.enableAutoSIPrefix(False)
            a.setTickFont(f)
            a.setTextPen("#333")
        self.plot.setLabel("left", tr('Volume (mL)'), **{"font-size": "8pt"})
        self.plot.setLabel("bottom", tr('Tempo (h)'), **{"font-size": "8pt"})
        self.plot.setMouseEnabled(x=True, y=True)     # arrastar = mover, roda = zoom
        color = QColor(COLORS[idx])
        fill = QColor(color)
        fill.setAlpha(40)
        self.curve = self.plot.plot([], [], pen=pg.mkPen(color, width=2), fillLevel=0, brush=fill)
        self.points = self.plot.plot([], [], pen=pg.mkPen(color, width=1.5), symbol="o", symbolSize=4,
                                     symbolBrush=color, symbolPen=None)
        self.info = pg.TextItem("", color="#555", anchor=(0, 0))
        self.info.setFont(f)
        self.plot.addItem(self.info, ignoreBounds=True)
        # pontos invisiveis em (0, 0) e (0, 10): o autoscale sempre comeca no zero e um canal sem dados
        # mostra uma escala razoavel em vez de colapsar num ponto
        self.floor = pg.ScatterPlotItem([0, 0], [0, 10], size=1, pen=None, brush=pg.mkBrush(0, 0, 0, 0))
        self.plot.addItem(self.floor)
        vb = self.plot.getViewBox()
        vb.setDefaultPadding(0.03)
        vb.enableAutoRange(enable=True)         # autoscale nativo; arrastar/zoom desliga ate o duplo clique
        vb.sigRangeChanged.connect(self._place_info)
        self.plot.scene().sigMouseClicked.connect(self._mouse_clicked)
        self.plot.setToolTip(tr('Arrastar: mover · roda do mouse: zoom · duplo clique ou botão “A”: autoscale'))
        v.addWidget(self.plot, 1)

        self._loading = False
        self.load(cfg)

    def _mouse_clicked(self, ev):
        if ev.double():
            self.plot.getViewBox().enableAutoRange(enable=True)
            ev.accept()

    def _place_info(self, *_):
        (x0, _x1), (_y0, y1) = self.plot.getViewBox().viewRange()
        self.info.setPos(x0, y1)

    def _pol_toggled(self, high: bool):
        self.pol.setText("↑" if high else "↓")
        self.pol.setToolTip(tr('Ímã = nível ALTO na saída do sensor (clique para trocar)') if high else
                            tr('Ímã = nível BAIXO na saída do sensor (clique para trocar)'))
        self._emit("pol")

    def _emit(self, what: str):
        self.setProperty("off", "false" if self.badge.isChecked() else "true")
        self.style().unpolish(self)
        self.style().polish(self)
        if not self._loading:
            self.changed.emit(self.idx, what)

    def load(self, cfg: ChannelConfig, pol_editable: bool = True):
        self._loading = True
        self.badge.setChecked(cfg.enabled)
        self.name.setText(cfg.name)
        self.cf.setValue(cfg.ml_per_tip)
        self.pol.setChecked(cfg.active_high)
        self._pol_toggled(cfg.active_high)
        self.pol.setEnabled(pol_editable)
        self._loading = False
        self._emit("load")   # so atualiza o estilo (nao propaga: _loading foi reposto antes)

    def apply_to(self, cfg: ChannelConfig):
        cfg.enabled = self.badge.isChecked()
        cfg.name = self.name.text().strip() or tr('Reator {0}').format(self.idx + 1)
        cfg.ml_per_tip = float(self.cf.value())
        cfg.active_high = self.pol.isChecked()


# =========================================================================== janela principal
class MainWindow(QMainWindow):
    def __init__(self, start_sim: bool = False):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1500, 900)

        self.settings = self._load_settings()
        fields = set(ChannelConfig.__dataclass_fields__)
        self.channels = [ChannelConfig(**{k: v for k, v in c.items() if k in fields})
                         for c in self.settings.get("canais", [])] or default_channels()
        self.data_dir = self.settings.get("pasta_dados") or os.path.join(os.path.expanduser("~"), "Documents",
                                                                          "TipGas")
        self.transport = None
        self.sim: Optional[SimulatedDevice] = None
        self.link: Optional[DeviceLink] = None
        self.live_exp: Optional[Experiment] = None      # pre-visualizacao ou gravacao em curso
        self.recording = False
        self.view_exp: Optional[Experiment] = None      # experimento salvo aberto para analise
        self.last_env: Optional[EnvSample] = None
        self.last_status_wall = 0.0
        self.log_lines = deque(maxlen=3000)              # (datahora, nivel, mensagem)
        self._last_log_msg = None
        self._comm_lost = False
        self._flash = None                               # (texto, nivel, expira_em)
        self._log_view = None

        self.setStyleSheet(STYLE)
        self._build_settings_dialog()
        self._build_ui()
        self._refresh_ports()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_view)
        self.refresh_timer.start(1000)

        self._log(tr('Programa iniciado (registro em {0})').format(self._log_path()), "info")
        self._correction_changed()

        if start_sim:
            self.port_combo.setCurrentIndex(self.port_combo.findData("sim"))
            self._toggle_connection()

    # ------------------------------------------------------------------ configuracao persistente
    def _load_settings(self) -> dict:
        for path in (SETTINGS_PATH, OLD_SETTINGS_PATH):     # migra as preferencias das versoes de teste
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                continue
        return {}

    def _language_changed(self, *_):
        self.settings["idioma"] = self.lang_combo.currentData()
        self._save_settings()
        QMessageBox.information(self, APP_NAME, tr('Idioma alterado. Reinicie o programa para aplicar.'))

    def _save_settings(self):
        self.settings["canais"] = [c.__dict__ for c in self.channels]
        self.settings["pasta_dados"] = self.data_dir
        self.settings["n_media"] = self.navg_spin.value()
        self.settings["unidade_tempo"] = self.tunit_combo.currentData()
        self.settings["correcao_modo"] = self.corr_combo.currentData()
        self.settings["t_ref_c"] = self.tref_spin.value()
        self.settings["p_ref_kpa"] = self.pref_spin.value()
        self.settings["grafico"] = self.graph_combo.currentData()
        self.settings["exportar_min"] = self.export_int.value()
        self.settings["bloqueio_ms"] = self.lock_spin.value()
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ------------------------------------------------------------------ construcao da interface
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 6)
        root.setSpacing(8)

        # --- painel superior de controles
        top = QFrame()
        top.setObjectName("topPanel")
        g = QGridLayout(top)
        g.setContentsMargins(14, 8, 14, 8)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(6)

        g.addWidget(QLabel(tr('<b>Porta:</b>')), 0, 0, Qt.AlignRight)
        prow = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(230)
        prow.addWidget(self.port_combo, 1)
        self.refresh_btn = QToolButton()
        self.refresh_btn.setObjectName("tool")
        self.refresh_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.refresh_btn.setToolTip(tr('Atualizar lista de portas'))
        self.refresh_btn.clicked.connect(self._refresh_ports)
        prow.addWidget(self.refresh_btn)
        g.addLayout(prow, 0, 1)
        self.connect_btn = QPushButton(tr('Conectar'))
        self.connect_btn.setObjectName("connect")
        self.connect_btn.setCheckable(True)
        self.connect_btn.setMinimumWidth(130)
        self.connect_btn.clicked.connect(self._toggle_connection)
        g.addWidget(self.connect_btn, 0, 2)

        g.addWidget(QLabel(tr('<b>Experimento:</b>')), 1, 0, Qt.AlignRight)
        self.exp_name = QLineEdit(self.settings.get("ultimo_nome", "biogas"))
        self.exp_name.setToolTip(tr('Nome do experimento (usado no nome da pasta de dados)'))
        g.addWidget(self.exp_name, 1, 1)
        self.graph_combo = QComboBox()
        for label, key in GRAPH_MODES:
            self.graph_combo.addItem(label, key)
        gi = self.graph_combo.findData(self.settings.get("grafico", "vol"))
        self.graph_combo.setCurrentIndex(max(0, gi))
        self.graph_combo.setToolTip(tr('O que os gráficos mostram'))
        g.addWidget(self.graph_combo, 1, 2)

        g.addWidget(_vline(), 0, 3, 2, 1)

        g.addWidget(QLabel(tr('<b>Salvar em:</b>')), 0, 4, Qt.AlignRight)
        drow = QHBoxLayout()
        self.dir_edit = QLineEdit(self.data_dir)
        self.dir_edit.setReadOnly(True)
        self.dir_edit.setMinimumWidth(260)
        drow.addWidget(self.dir_edit, 1)
        dbtn = QToolButton()
        dbtn.setObjectName("tool")
        dbtn.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        dbtn.setToolTip(tr('Escolher a pasta onde os experimentos são salvos'))
        dbtn.clicked.connect(self._choose_dir)
        drow.addWidget(dbtn)
        g.addLayout(drow, 0, 5)
        crow = QHBoxLayout()
        crow.addWidget(QLabel(tr('<b>Correção:</b>')))
        self.corr_combo = QComboBox()
        for key, label in CORRECTION_MODES.items():
            self.corr_combo.addItem(tr(label), key)
        ci = self.corr_combo.findData(self.settings.get("correcao_modo", "none"))
        self.corr_combo.setCurrentIndex(max(0, ci))
        self.corr_combo.setToolTip(tr('Correção de cada basculamento por temperatura e pressão (sensor BME280/BMP280).\n“Condições da calibração” = método do artigo: leva cada basculamento às condições\n(T_ref, P_ref) em que o fator k foi medido. Ajuste T_ref e P_ref em Ajustes → Medição.'))
        crow.addWidget(self.corr_combo)
        self.ref_label = QLabel("")
        self.ref_label.setStyleSheet("color:#555;")
        crow.addWidget(self.ref_label)
        crow.addStretch(1)
        g.addLayout(crow, 1, 5)
        g.setColumnStretch(5, 1)

        self.start_btn = QPushButton(tr('▶  Iniciar'))
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setMinimumWidth(170)
        self.start_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.start_btn.setToolTip(tr('Iniciar / encerrar a gravação do experimento'))
        self.start_btn.clicked.connect(self._start_stop)
        g.addWidget(self.start_btn, 0, 6, 2, 1)

        g.addWidget(_vline(), 0, 7, 2, 1)

        def toolbtn(text, icon, tip):
            b = QToolButton()
            b.setObjectName("tool")
            b.setText(text)
            b.setIcon(self.style().standardIcon(icon))
            b.setIconSize(QSize(22, 22))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setToolTip(tip)
            b.setMinimumWidth(78)
            b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            return b

        self.data_btn = toolbtn(tr('Dados'), QStyle.SP_DirIcon, tr('Experimentos salvos, exportação e registro'))
        self.data_btn.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(self.data_btn)
        m.addAction(tr('Abrir experimento salvo…'), self._open_saved)
        self.live_act = m.addAction(tr('Voltar ao vivo'), self._back_to_live)
        self.live_act.setEnabled(False)
        m.addSeparator()
        m.addAction(tr('Exportar tabela em intervalos regulares (volume e vazão)…'), self._export)
        m.addAction(tr('Exportar tempo e volume (um arquivo por sensor)…'), self._export_events)
        m.addSeparator()
        m.addAction(tr("Calibrar fatores k…"), self._show_calibration)
        m.addAction(tr('Abrir pasta de dados'), lambda: self._open_path(self.data_dir))
        m.addSeparator()
        m.addAction(tr('Registro de eventos…'), self._show_log)
        self.data_btn.setMenu(m)
        g.addWidget(self.data_btn, 0, 8, 2, 1)
        sbtn = toolbtn(tr('Ajustes'), QStyle.SP_FileDialogDetailedView, tr('Cálculo, dispositivo e simulação'))
        sbtn.clicked.connect(self._show_settings)
        g.addWidget(sbtn, 0, 9, 2, 1)
        abtn = toolbtn(tr('Sobre'), QStyle.SP_MessageBoxInformation, tr('Sobre o programa'))
        abtn.clicked.connect(self._about)
        g.addWidget(abtn, 0, 10, 2, 1)
        root.addWidget(top)

        # --- grade 3x3 de canais (S1-S3 na primeira coluna, como na bancada)
        pg.setConfigOptions(antialias=True, background="w", foreground="#333")
        grid = QGridLayout()
        grid.setSpacing(8)
        self.panels = []
        for i in range(NUM_CHANNELS):
            p = ChannelPanel(i, self.channels[i])
            p.changed.connect(self._panel_changed)
            grid.addWidget(p, i % 3, i // 3)
            self.panels.append(p)
        root.addLayout(grid, 1)

        self.corr_combo.currentIndexChanged.connect(self._correction_changed)
        self.graph_combo.currentIndexChanged.connect(lambda *_: (self._save_settings(), self._refresh_view()))

        # --- barra de status inferior
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.st_dot = QLabel("●")
        self.st_dot.setStyleSheet("color:#888; font-size:15pt; padding-left:6px;")
        sb.addWidget(self.st_dot)
        self.st_text = QLabel(tr('Desconectado'))
        self.st_text.setTextFormat(Qt.RichText)
        self.st_text.setMinimumWidth(320)
        self.st_text.setCursor(Qt.PointingHandCursor)
        self.st_text.setToolTip(tr('Clique para ver o registro de eventos'))
        self.st_text.mousePressEvent = lambda ev: self._show_log()
        sb.addWidget(self.st_text, 3)
        self.st_elapsed = QLabel(tr('Tempo decorrido: 00:00:00'))
        self.st_tips = QLabel(tr('Basculamentos: 0'))
        self.st_file = QLabel(tr('Pasta: –'))
        self.st_env = QLabel("")
        for w in (self.st_elapsed, self.st_tips, self.st_file, self.st_env):
            sb.addWidget(_vline())
            w.setStyleSheet("padding: 0 8px;")
            sb.addWidget(w, 1 if w is self.st_file else 0)
        self.st_clock = QLabel("")
        self.st_clock.setStyleSheet("padding: 0 8px;")
        sb.addPermanentWidget(self.st_clock)
        self._status_key = None

    # ------------------------------------------------------------------ dialogo de ajustes
    def _build_settings_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('Ajustes'))
        dlg.setMinimumWidth(460)
        v = QVBoxLayout(dlg)
        tabs = QTabWidget()
        v.addWidget(tabs)

        t = QWidget()
        f = QFormLayout(t)
        self.navg_spin = QSpinBox()
        self.navg_spin.setRange(1, 50)
        self.navg_spin.setValue(int(self.settings.get("n_media", 3)))
        self.navg_spin.setSuffix(tr(' basculamentos'))
        self.navg_spin.setToolTip(tr('Vazão = volume dos últimos N basculamentos / tempo decorrido entre eles'))
        f.addRow(tr('Vazão: média dos últimos'), self.navg_spin)
        self.tunit_combo = QComboBox()
        for key in TIME_UNITS:
            self.tunit_combo.addItem(tr(key), key)
        self.tunit_combo.setCurrentIndex(max(0, self.tunit_combo.findData(self.settings.get("unidade_tempo", "h"))))
        f.addRow(tr('Unidade do eixo do tempo:'), self.tunit_combo)
        self.export_int = QDoubleSpinBox()
        self.export_int.setRange(0.1, 1440)
        self.export_int.setValue(float(self.settings.get("exportar_min", 10)))
        self.export_int.setSuffix(" min")
        f.addRow(tr('Exportar tabela a cada:'), self.export_int)
        self.lang_combo = QComboBox()
        for key, label in LANGUAGES.items():
            self.lang_combo.addItem(label, key)
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(self.settings.get("idioma", "auto"))))
        self.lang_combo.currentIndexChanged.connect(self._language_changed)
        f.addRow(tr('Idioma / Language:'), self.lang_combo)
        for w, sig in ((self.navg_spin, "valueChanged"), (self.tunit_combo, "currentTextChanged"),
                       (self.export_int, "valueChanged")):
            getattr(w, sig).connect(lambda *_: (self._save_settings(), self._refresh_view()))

        sep = QLabel(tr('<b>Condições da calibração</b> (referência da correção pelo método do artigo)'))
        sep.setWordWrap(True)
        f.addRow(sep)
        self.tref_spin = QDoubleSpinBox()
        self.tref_spin.setRange(0.0, 60.0)
        self.tref_spin.setDecimals(2)
        self.tref_spin.setSuffix(" °C")
        self.tref_spin.setValue(float(self.settings.get("t_ref_c", 25.0)))
        self.tref_spin.setToolTip(tr('Temperatura em que os fatores k foram medidos'))
        f.addRow("T_ref:", self.tref_spin)
        self.pref_spin = QDoubleSpinBox()
        self.pref_spin.setRange(50.0, 120.0)
        self.pref_spin.setDecimals(3)
        self.pref_spin.setSuffix(" kPa")
        self.pref_spin.setValue(float(self.settings.get("p_ref_kpa", 101.325)))
        self.pref_spin.setToolTip(tr('Pressão atmosférica durante a calibração (Pato Branco, ~760 m: cerca de 92–93 kPa)'))
        f.addRow("P_ref:", self.pref_spin)
        rrow = QHBoxLayout()
        b_now = QPushButton(tr('Usar T e P atuais'))
        b_now.setToolTip(tr('Copia a temperatura e a pressão medidas agora para T_ref e P_ref'))
        b_now.clicked.connect(self._ref_from_now)
        b_cal = QPushButton(tr("Calibrar fatores k…"))
        b_cal.clicked.connect(self._show_calibration)
        rrow.addWidget(b_now)
        rrow.addWidget(b_cal)
        rrow.addStretch(1)
        f.addRow(rrow)
        for w, sig in ((self.tref_spin, "valueChanged"), (self.pref_spin, "valueChanged")):
            getattr(w, sig).connect(self._correction_changed)
        tabs.addTab(t, tr('Medição'))

        t = QWidget()
        f = QFormLayout(t)
        self.lock_spin = QSpinBox()
        self.lock_spin.setRange(20, 10000)
        self.lock_spin.setSingleStep(100)
        self.lock_spin.setValue(int(self.settings.get("bloqueio_ms", DEFAULT_LOCKOUT_MS)))
        self.lock_spin.setSuffix(" ms")
        self.lock_spin.setKeyboardTracking(False)
        self.lock_spin.setToolTip(tr('Tempo mínimo entre dois basculamentos do mesmo canal (filtra o quique mecânico).\nFica salvo na interface e é enviado à placa a cada conexão.'))
        # envia a placa 1,5 s depois da ultima alteracao (evita regravar a flash a cada clique na setinha)
        self._lock_timer = QTimer(self)
        self._lock_timer.setSingleShot(True)
        self._lock_timer.setInterval(1500)
        self._lock_timer.timeout.connect(self._send_lockout)
        self.lock_spin.valueChanged.connect(lambda *_: (self._save_settings(), self._lock_timer.start()))
        lrow = QHBoxLayout()
        lrow.addWidget(self.lock_spin)
        self.lock_state = QLabel("")
        self.lock_state.setStyleSheet("color:#666;")
        lrow.addWidget(self.lock_state, 1)
        f.addRow(tr('Bloqueio:'), lrow)
        self.dev_info = QLabel("—")
        self.dev_info.setWordWrap(True)
        self.dev_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f.addRow(tr('Firmware:'), self.dev_info)
        self.dev_env = QLabel("—")
        f.addRow(tr('Ambiente:'), self.dev_env)
        self.dev_mcu = QLabel("—")
        self.dev_mcu.setWordWrap(True)
        f.addRow(tr('MCU:'), self.dev_mcu)
        hint = QLabel(tr('A polaridade de cada sensor (↓/↑) fica no cabeçalho de cada canal.'))
        hint.setStyleSheet("color:#666;")
        hint.setWordWrap(True)
        f.addRow(hint)
        tabs.addTab(t, tr('Dispositivo'))

        # aba Temperatura: DS18B20 no barramento 1-Wire (PB8) e associacao sensor -> canal
        t = QWidget()
        tv = QVBoxLayout(t)
        hint = QLabel(tr('Sensores DS18B20 encontrados no barramento 1-Wire (pino PB8). Associe a cada canal o sensor que mede o gás daquela célula. No basculamento, a interface registra a leitura mais recente desse sensor (lida a cada 2 s) e usa essa temperatura na correção. Canais sem DS18B20 usam o BME280 (ar). Para identificar um sensor, segure-o na mão: o que esquentar é ele.'))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#555;")
        tv.addWidget(hint)
        self.ds_table = QTableWidget(0, 3)
        self.ds_table.setHorizontalHeaderLabels([tr('Sensor (código)'), tr('Temperatura'), tr('Última leitura')])
        self.ds_table.verticalHeader().setVisible(False)
        self.ds_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.ds_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ds_table.setMaximumHeight(150)
        tv.addWidget(self.ds_table)
        grid_w = QWidget()
        tg = QGridLayout(grid_w)
        tg.setContentsMargins(0, 0, 0, 0)
        self.temp_combos = []
        for i in range(NUM_CHANNELS):
            lbl = QLabel(f"S{i + 1}")
            cb = QComboBox()
            cb.currentIndexChanged.connect(lambda _=0, ch=i: self._temp_src_changed(ch))
            self.temp_combos.append(cb)
            tg.addWidget(lbl, i % 5, (i // 5) * 2)
            tg.addWidget(cb, i % 5, (i // 5) * 2 + 1)
        tv.addWidget(grid_w)
        arow = QHBoxLayout()
        arow.addWidget(QLabel(tr('Mesmo sensor para todos:')))
        self.temp_all = QComboBox()
        arow.addWidget(self.temp_all, 1)
        b_all = QPushButton(tr('Aplicar a todos'))
        b_all.clicked.connect(self._temp_apply_all)
        arow.addWidget(b_all)
        tv.addLayout(arow)
        tv.addStretch(1)
        tabs.addTab(t, tr('Temperatura'))
        self.ds_latest = {}                                   # rom -> TempSample mais recente
        self.ds_known = list(self.settings.get("ds18b20_conhecidos", []))
        self._rebuild_temp_combos()

        self.sim_tab = QWidget()
        f = QFormLayout(self.sim_tab)
        self.speed_combo = QComboBox()
        for label, val in SIM_SPEEDS:
            self.speed_combo.addItem(label, val)
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.currentIndexChanged.connect(self._sim_speed)
        f.addRow(tr('Velocidade:'), self.speed_combo)
        self.loss_spin = QSpinBox()
        self.loss_spin.setRange(0, 80)
        self.loss_spin.setSuffix(" %")
        self.loss_spin.setToolTip(tr('Fração de mensagens perdidas na USB (testa a recuperação automática)'))
        self.loss_spin.valueChanged.connect(lambda val: self.sim and setattr(self.sim, "line_loss", val / 100.0))
        f.addRow(tr('Perda de mensagens:'), self.loss_spin)
        srow = QHBoxLayout()
        b1 = QPushButton(tr('Desconectar 5 s'))
        b1.clicked.connect(lambda: self.sim and self.sim.disconnect_for(5))
        b2 = QPushButton(tr('Reiniciar MCU'))
        b2.clicked.connect(lambda: self.sim and self.sim.reset_mcu())
        srow.addWidget(b1)
        srow.addWidget(b2)
        f.addRow(tr('Testes:'), srow)
        hint = QLabel(tr('Para simular, escolha “Simulação (sem placa)” na lista de portas e clique em Conectar.'))
        hint.setStyleSheet("color:#666;")
        hint.setWordWrap(True)
        f.addRow(hint)
        tabs.addTab(self.sim_tab, tr('Simulação'))

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText(tr('Fechar'))
        bb.rejected.connect(dlg.hide)
        v.addWidget(bb)
        self.settings_dlg = dlg
        self.settings_tabs = tabs

    def _show_settings(self):
        if self.sim is not None:
            self.settings_tabs.setCurrentWidget(self.sim_tab)
        self.settings_dlg.show()
        self.settings_dlg.raise_()

    def _about(self):
        QMessageBox.about(self, tr('Sobre – {0}').format(APP_NAME),
                          tr('<b>{0}</b><br>Monitor de produção de gás com 9 células tipping-bucket, sensores Hall e STM32F411 (Black Pill).<br><br>Cada sensor tem seu arquivo (<i>S1_….csv</i> a <i>S9_….csv</i>) com tempo e volume; os dados completos de cada basculamento ficam em <i>detalhes/</i>. O volume é o número de basculamentos × fator de calibração (FC, mL por basculamento).<br><br>Dados e registro de eventos em:<br>{1}').format(APP_NAME, self._esc(self.data_dir)))

    # ------------------------------------------------------------------ canais
    def _panel_changed(self, i: int, what: str):
        p = self.panels[i]
        if self.view_exp is not None:
            # reprocessa o experimento salvo com o novo nome/fator (a polaridade nao se aplica)
            cfg = self.view_exp.channels[i]
            p.apply_to(cfg)
            if what in ("cf", "name", "enabled"):
                self.view_exp.save_config()
                if what == "cf":
                    self._log(tr('Experimento salvo reprocessado: S{0} com FC = {1:.3f} mL').format(i + 1, cfg.ml_per_tip), "info")
            self._refresh_view()
            return
        p.apply_to(self.channels[i])
        self._save_settings()
        if self.live_exp is not None and self.live_exp.folder:
            self.live_exp.save_config()
        if what == "pol":
            self._send_polarity()
        self._refresh_view()

    def _send_polarity(self):
        if self.transport is not None and self.link is not None:
            m = pol_mask(self.channels)
            self._send(f"POL,{m}")
            self._log(tr('Polaridade enviada ao dispositivo (máscara {0}: canais em nível alto = {1})').format(m, [i + 1 for i, c in enumerate(self.channels) if c.active_high] or 'nenhum'))

    def _load_panels(self, channels, pol_editable: bool):
        for p, c in zip(self.panels, channels):
            p.load(c, pol_editable)

    # ------------------------------------------------------------------ conexao
    def _refresh_ports(self):
        cur = self.port_combo.currentData()
        self.port_combo.clear()
        best = -1
        for i, p in enumerate(sorted(serial.tools.list_ports.comports(), key=lambda x: x.device)):
            desc = p.description or ""
            self.port_combo.addItem(f"{p.device} — {desc}", p.device)
            if (p.vid == 0x0483 and p.pid == 0x5740) or "TipGas" in desc or "Vazao" in desc:
                best = i
        if self.port_combo.count() == 0:
            self.port_combo.addItem(tr('(nenhuma porta encontrada)'), None)
        self.port_combo.insertSeparator(self.port_combo.count())
        self.port_combo.addItem(tr('Simulação (sem placa)'), "sim")
        if cur is not None and self.port_combo.findData(cur) >= 0:
            self.port_combo.setCurrentIndex(self.port_combo.findData(cur))
        elif best >= 0:
            self.port_combo.setCurrentIndex(best)

    def _toggle_connection(self):
        if self.transport is not None:
            self._disconnect()
            return
        kind = self.port_combo.currentData()
        if not kind:
            self.connect_btn.setChecked(False)
            QMessageBox.information(self, APP_NAME, tr('Nenhuma porta serial encontrada.\nConecte o medidor pela USB ou escolha “Simulação (sem placa)”.'))
            return
        # Reaproveita o DeviceLink (e o simulador) ao reconectar no mesmo dispositivo: assim os
        # eventos ja recebidos nao sao duplicados e os perdidos na desconexao sao recuperados.
        if self.link is None or getattr(self, "_link_kind", None) != kind:
            if self.recording:
                self.connect_btn.setChecked(False)
                QMessageBox.warning(self, APP_NAME, tr('Encerre a gravação antes de trocar de dispositivo.'))
                return
            if kind == "sim":
                self.sim = SimulatedDevice(speed=self.speed_combo.currentData(),
                                           line_loss=self.loss_spin.value() / 100.0)
                self.link = DeviceLink(clock=self.sim.clock, time_scale=self.sim.speed)
            else:
                self.sim = None
                self.link = DeviceLink()
            self._link_kind = kind
            self.live_exp = None
            self.last_env = None
        self.transport = SimTransport(self.sim) if kind == "sim" else SerialTransport(kind)
        self.link.send = self._send
        self.link.on_event = self._on_event
        self.link.on_env = self._on_env
        self.link.on_temp = self._on_temp
        self.link.on_status = self._on_status
        self.link.on_info = self._on_info
        self.link.on_log = self._log
        self.transport.line.connect(self.link.handle_line)
        self.transport.state.connect(self._on_transport_state)
        if self.live_exp is None:
            self.live_exp = Experiment("pre-visualizacao", None, self.channels, start_wall=self.link.clock())
            self._set_temp_age()
        self.transport.start()
        self.connect_btn.setChecked(True)
        self.connect_btn.setText(tr('Desconectar'))
        self.port_combo.setEnabled(False)
        self.refresh_btn.setEnabled(False)

    def _disconnect(self):
        if self.recording:
            r = QMessageBox.question(self, APP_NAME, tr('Há uma gravação em andamento. Desconectar mesmo assim?\n(o MCU continua contando; ao reconectar os eventos são recuperados)'))
            if r != QMessageBox.Yes:
                self.connect_btn.setChecked(True)
                return
        t, self.transport = self.transport, None
        t.stop()
        self.connect_btn.setChecked(False)
        self.connect_btn.setText(tr('Conectar'))
        self.port_combo.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self._refresh_view()

    def _on_transport_state(self, ok: bool, msg: str):
        self.conn_ok = ok
        if ok:
            self.last_status_wall = 0.0          # espera o primeiro ST antes de vigiar silencio
            self._comm_lost = False
        self.conn_msg = msg
        if ok:
            self._log(msg, "event")
        elif self.transport is not None:
            self._log(msg, "error" if self.recording else "warn")
        else:
            self._log(msg, "info")
        if ok and self.link:
            self.link.connection_opened()
        self._update_status()

    def _send(self, cmd: str):
        if self.transport is not None:
            self.transport.write(cmd)

    # ------------------------------------------------------------------ dados recebidos
    def _on_event(self, ev: TipEvent):
        if self.live_exp is not None and ev.wall >= self.live_exp.start_wall:
            self.live_exp.add_event(ev)
        if getattr(self, "calib_dlg", None) is not None:
            self.calib_dlg.on_event(ev)

    def _on_temp(self, t: TempSample):
        new = t.rom not in self.ds_latest and t.rom not in self.ds_known
        self.ds_latest[t.rom] = t
        if self.live_exp is not None:
            self.live_exp.add_temp(t)
        if getattr(self, "calib_dlg", None) is not None:
            self.calib_dlg.on_temp(t)
        if new:
            self.ds_known.append(t.rom)
            self.settings["ds18b20_conhecidos"] = self.ds_known
            self._log(tr("DS18B20 encontrado: {0} ({1:.2f} °C)").format(t.rom, t.t_c), "event")
            # a placa informou que ha exatamente um DS18B20 e nenhum canal tem sensor: usa ele em todos
            if getattr(self, "_ds_count", None) == 1 and len(self.ds_known) == 1 \
                    and not any(c.temp_sensor for c in self.channels):
                for c in self.channels:
                    c.temp_sensor = t.rom
                self._log(tr('Único DS18B20 associado a todos os canais (altere em Ajustes → Temperatura)'), "info")
            self._rebuild_temp_combos()
            self._save_settings()

    def _ds_label(self, rom: str) -> str:
        t = self.ds_latest.get(rom)
        idx = self.ds_known.index(rom) + 1 if rom in self.ds_known else 0
        tt = f" — {t.t_c:.2f} °C" if t else tr(' — sem leitura')
        return f"DS18B20 #{idx} (…{rom[-6:-2]}){tt}"

    def _rebuild_temp_combos(self):
        self._temp_loading = True
        for i, cb in enumerate(self.temp_combos):
            cb.clear()
            cb.addItem(tr('Ar (BME280)'), "")
            for rom in self.ds_known:
                cb.addItem(self._ds_label(rom), rom)
            j = cb.findData(self.channels[i].temp_sensor)
            cb.setCurrentIndex(max(0, j))
        self.temp_all.clear()
        self.temp_all.addItem(tr('Ar (BME280)'), "")
        for rom in self.ds_known:
            self.temp_all.addItem(self._ds_label(rom), rom)
        self._temp_loading = False

    def _refresh_temp_tab(self):
        roms = self.ds_known
        self.ds_table.setRowCount(len(roms))
        for r, rom in enumerate(roms):
            t = self.ds_latest.get(rom)
            age = ""
            if t is not None and self.link is not None:
                scale = max(1.0, self.link.time_scale)
                age = tr('há {0:.0f} s').format(max(0.0, (self.link.clock() - t.wall) / scale))
            vals = [f"#{r + 1}  {rom}", f"{t.t_c:.2f} °C" if t else "—", age or "—"]
            for c, v in enumerate(vals):
                it = self.ds_table.item(r, c)
                if it is None:
                    it = QTableWidgetItem()
                    self.ds_table.setItem(r, c, it)
                it.setText(v)
        # atualiza a temperatura mostrada nas opcoes, sem mexer na selecao
        for cb in self.temp_combos + [self.temp_all]:
            for k in range(1, cb.count()):
                cb.setItemText(k, self._ds_label(cb.itemData(k)))

    def _temp_src_changed(self, i: int):
        if getattr(self, "_temp_loading", False):
            return
        rom = self.temp_combos[i].currentData() or ""
        self.channels[i].temp_sensor = rom
        self._save_settings()
        if self.live_exp is not None and self.live_exp.folder:
            self.live_exp.save_config()
        self._log(tr('S{0}: temperatura do {1}').format(i + 1, 'DS18B20 ' + rom if rom else 'BME280 (ar)'), "info")

    def _temp_apply_all(self):
        rom = self.temp_all.currentData() or ""
        for i, cb in enumerate(self.temp_combos):
            cb.setCurrentIndex(max(0, cb.findData(rom)))

    def _channel_temp(self, i: int) -> Optional[float]:
        rom = self.channels[i].temp_sensor
        if rom and rom in self.ds_latest:
            return self.ds_latest[rom].t_c
        return self.last_env.t_c if self.last_env else None

    def _on_env(self, s: EnvSample):
        self.last_env = s
        if getattr(self, "calib_dlg", None) is not None:
            self.calib_dlg.on_env(s)
        if self.live_exp is not None and s.wall >= self.live_exp.start_wall:
            self.live_exp.add_env(s)

    def _on_status(self, st: dict):
        self.last_status_wall = self.link.clock() if self.link else 0

    def _send_lockout(self):
        if self.transport is not None and self.link is not None:
            self._send(f"DEB,{self.lock_spin.value()}")
            self._log(tr('Bloqueio enviado ao dispositivo: {0} ms').format(self.lock_spin.value()), "info")
            self.lock_state.setText(tr('enviado à placa'))

    def _on_info(self, info: dict):
        self._ds_count = info.get("n_ds18b20")
        # a interface guarda o bloqueio e a polaridade; a placa recebe esses valores a cada conexao
        dev_lock = info.get("lockout_ms")
        if dev_lock != self.lock_spin.value():
            self._send_lockout()
        else:
            self.lock_state.setText(tr('igual ao da placa'))
        dev_mask = info.get("pol_mask")
        if dev_mask is None:
            if pol_mask(self.channels):
                self._log(tr('AVISO: o firmware do dispositivo não suporta polaridade configurável (atualize para 1.1)'))
        elif dev_mask != pol_mask(self.channels):
            self._send_polarity()
        self.dev_info.setText(tr('{0} · sensor ambiental: {1}\nUID {2}').format(info.get('version'), info.get('sensor'), info.get('uid')))

    # ------------------------------------------------------------------ registro de eventos
    def _log_path(self) -> str:
        return os.path.join(self.data_dir, "registro", f"registro_{datetime.now():%Y-%m-%d}.log")

    @staticmethod
    def _classify(msg: str) -> str:
        m = msg.lower()
        if m.startswith(("erro", "error")):
            return "error"
        if m.startswith(("aviso", "warning")) or any(w in m for w in ("reinicio", "reinício", "restart")):
            return "warn"
        if m.startswith(("dispositivo conectado", "device connected")):
            return "event"
        return "info"

    def _log(self, msg: str, level: Optional[str] = None):
        """Registra um evento: arquivo diario em <pasta de dados>/registro, copia na pasta do
        experimento (se gravando) e, se for importante, destaque na barra de status."""
        level = level or self._classify(msg)
        now = datetime.now()
        repeated = (msg == self._last_log_msg)
        self._last_log_msg = msg
        if repeated and level in ("info", "warn"):
            return                                  # evita repetir "tentando reconectar..." a cada 2 s
        self.log_lines.append((now, level, msg))
        line = f"{now:%Y-%m-%d %H:%M:%S}  {LEVEL_TAG.get(level, level)}  {msg}\n"
        paths = [self._log_path()]
        if self.recording and self.live_exp is not None and self.live_exp.folder:
            paths.append(os.path.join(self.live_exp.folder, "registro.log"))
        for p in paths:
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                pass
        if level in FLASH_S:
            self._flash = (msg, level, time.time() + FLASH_S[level])
            if hasattr(self, "st_text"):
                self._update_status()
        if self._log_view is not None:
            self._log_view.appendPlainText(line.rstrip("\n"))

    def _show_log(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('Registro de eventos'))
        dlg.resize(820, 460)
        v = QVBoxLayout(dlg)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setFont(QFont("Consolas", 9))
        view.setPlainText("\n".join(f"{t:%Y-%m-%d %H:%M:%S}  {LEVEL_TAG.get(l, l)}  {m}" for t, l, m in self.log_lines))
        view.moveCursor(QTextCursor.End)
        v.addWidget(view)
        info = QLabel(tr('Arquivo: {0}').format(self._log_path()))
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(info)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText(tr('Fechar'))
        b_file = bb.addButton(tr('Abrir arquivo'), QDialogButtonBox.ActionRole)
        b_dir = bb.addButton(tr('Abrir pasta'), QDialogButtonBox.ActionRole)
        b_file.clicked.connect(lambda: self._open_path(self._log_path()))
        b_dir.clicked.connect(lambda: self._open_path(os.path.dirname(self._log_path())))
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        self._log_view = view
        dlg.finished.connect(lambda *_: setattr(self, "_log_view", None))
        dlg.show()

    def _open_path(self, path: str):
        if not os.path.exists(path):
            try:
                os.makedirs(path if not os.path.splitext(path)[1] else os.path.dirname(path), exist_ok=True)
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------ barra de status (inferior)
    def _check_comm(self) -> float:
        """Detecta perda/retorno da comunicacao. Retorna ha quantos segundos (reais) o MCU esta mudo."""
        if not (self.link and self.transport is not None and getattr(self, "conn_ok", False)
                and self.last_status_wall):
            return 0.0
        scale = max(1.0, self.link.time_scale)
        silent = (self.link.clock() - self.last_status_wall) / scale
        if silent > 5 and not self._comm_lost:
            self._comm_lost = True
            self._log(tr('Sem resposta do dispositivo — verifique o cabo USB'), "error" if self.recording else "warn")
        elif silent <= 5 and self._comm_lost:
            self._comm_lost = False
            self._log(tr('Comunicação com o dispositivo restabelecida'), "event")
        return silent

    def _set_status(self, dot: str, text: str, bg: Optional[str] = None):
        key = (dot, text, bg)
        if key == self._status_key:
            return
        self._status_key = key
        self.st_dot.setStyleSheet(f"color:{dot}; font-size:15pt; padding-left:6px;")
        self.st_text.setText(text)
        self.st_text.setStyleSheet(f"background:{bg}; border-radius:4px; padding:2px 8px;" if bg
                                   else "padding:2px 8px;")

    def _update_status(self):
        now_real = time.time()
        silent = self._check_comm()
        if self._comm_lost and self.view_exp is None:
            extra = tr(' — a placa continua contando') if self.recording else ""
            self._set_status("#c0392b", tr('<b>Sem resposta do dispositivo há {0:.0f} s</b> — verifique o cabo USB{1}').format(silent, extra), ST_ALERT)
            return
        if self._flash and now_real < self._flash[2]:
            msg, level, _ = self._flash
            dot = {"event": "#1e9e3e", "warn": "#d4a017", "error": "#c0392b"}[level]
            self._set_status(dot, f"<b>{self._esc(msg)}</b>", FLASH_COLOR[level])
            return
        self._flash = None
        if self.view_exp is not None:
            self._set_status("#7b61c9", tr('<b>Experimento salvo:</b> {0} (Dados → Voltar ao vivo)').format(self._esc(self.view_exp.name)), ST_VIEW)
        elif self.transport is None:
            self._set_status("#888888", tr('<b>Desconectado</b>'))
        elif not getattr(self, "conn_ok", False):
            self._set_status("#d4a017", f"<b>{self._esc(getattr(self, 'conn_msg', tr('Conectando…')))}</b>", ST_WARN)
        elif self.recording:
            sim = tr(' · simulação {0:g}×').format(self.sim.speed) if self.sim is not None else ""
            self._set_status("#c0392b", tr('<b>Gravando</b> “{0}”{1}').format(self._esc(self.live_exp.name), sim))
        else:
            sim = tr(' · simulação {0:g}×').format(self.sim.speed) if self.sim is not None else ""
            self._set_status("#1e9e3e", tr('<b>Conectado</b> · pré-visualização (não está gravando){0}').format(sim))

    @staticmethod
    def _esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # ------------------------------------------------------------------ experimento
    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr('Pasta para salvar os experimentos'), self.data_dir)
        if d:
            self.data_dir = d
            self.dir_edit.setText(d)
            self._save_settings()
            self._log(tr('Pasta de dados alterada para {0}').format(d), "info")

    def _start_stop(self):
        if self.recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _set_rec_button(self):
        self.start_btn.setText(tr('■  Encerrar') if self.recording else tr('▶  Iniciar'))
        self.start_btn.setProperty("rec", "true" if self.recording else "false")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self.exp_name.setEnabled(not self.recording)

    def _start_recording(self):
        if self.transport is None or self.link is None:
            QMessageBox.information(self, APP_NAME, tr('Conecte o medidor (ou escolha a simulação) antes de iniciar.'))
            return
        if self.view_exp is not None:
            self._back_to_live()
        name = self.exp_name.text().strip() or tr('experimento')
        start = self.link.clock()
        try:
            folder = Experiment.make_folder(self.data_dir, name, start)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, tr('Não foi possível criar a pasta de dados:\n{0}').format(e))
            return
        self.live_exp = Experiment(name, folder, self.channels, start_wall=start)
        self.live_exp.correction = self._current_corr()
        self._set_temp_age()
        # leituras de temperatura ja recebidas: a primeira basculada ja tem T do seu sensor
        for t in self.ds_latest.values():
            self.live_exp.temps.setdefault(t.rom, []).append(t)
        self.live_exp.open_files()
        if self.last_env is not None:
            self.live_exp.add_env(self.last_env)     # ultima leitura de T/P, para os primeiros basculamentos
        self.recording = True
        self.settings["ultimo_nome"] = name
        self._save_settings()
        self._set_rec_button()
        self._log(tr('Gravação iniciada: {0}').format(folder), "event")
        self._refresh_view()

    def _stop_recording(self):
        if not self.recording:
            return
        r = QMessageBox.question(self, APP_NAME, tr('Encerrar a gravação deste experimento?'))
        if r != QMessageBox.Yes:
            return
        exp = self.live_exp
        exp.end_wall = self.link.clock() if self.link else time.time()
        n = sum(len(l) for l in exp.events.values())
        self._log(tr('Gravação encerrada ({0} basculamentos, duração {1}): {2}').format(n, self._fmt_td(exp.end_wall - exp.start_wall), exp.folder), "event")
        exp.close_files()
        exp.save_config()
        self.recording = False
        self._set_rec_button()
        # continua mostrando o experimento encerrado como "salvo" (com copia propria dos canais)
        exp.channels = [ChannelConfig(**c.__dict__) for c in exp.channels]
        self.view_exp = exp
        self.live_act.setEnabled(True)
        self._load_panels(exp.channels, pol_editable=False)
        self.live_exp = Experiment("pre-visualizacao", None, self.channels,
                                   start_wall=self.link.clock() if self.link else time.time())
        self._set_temp_age()
        self._refresh_view()

    def _open_saved(self):
        d = QFileDialog.getExistingDirectory(self, tr('Abrir pasta de um experimento salvo'), self.data_dir)
        if not d:
            return
        try:
            exp = Experiment.load(d)
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, APP_NAME, tr('Não foi possível abrir o experimento:\n{0}').format(e))
            return
        self.view_exp = exp
        self.live_act.setEnabled(True)
        self._load_panels(exp.channels, pol_editable=False)
        self._log(tr('Experimento aberto para análise: {0}').format(d), "event")
        self._refresh_view()

    def _back_to_live(self):
        self.view_exp = None
        self.live_act.setEnabled(False)
        self._load_panels(self.channels, pol_editable=True)
        self._refresh_view()

    def _shown_exp(self) -> Optional[Experiment]:
        return self.view_exp if self.view_exp is not None else self.live_exp

    def _export(self):
        exp = self._shown_exp()
        if exp is None or not any(exp.events.values()):
            QMessageBox.information(self, APP_NAME, tr('Não há dados para exportar.'))
            return
        corr = self._corr_for(exp)
        base = exp.folder or self.data_dir
        path, _ = QFileDialog.getSaveFileName(self, tr('Exportar volume e vazão em intervalos regulares'),
                                              os.path.join(base, f"resultado_{corr.unit_tag()}.csv"), "CSV (*.csv)")
        if not path:
            return
        end = exp.end_wall or (self.link.clock() if self.link else None)
        exp.export_resampled(path, self.export_int.value(), corr, end_wall=end)
        self._log(tr("Tabela exportada: {0}").format(path), "event")

    def _export_events(self):
        exp = self._shown_exp()
        if exp is None or not any(exp.events.values()):
            QMessageBox.information(self, APP_NAME, tr('Não há dados para exportar.'))
            return
        corr = self._corr_for(exp)
        base = exp.folder or self.data_dir
        folder = QFileDialog.getExistingDirectory(self, tr('Pasta onde salvar um arquivo por sensor'), base)
        if not folder:
            return
        files = exp.export_events(folder, corr, prefix=tr('volume'))
        self._log(tr('Basculamentos exportados ({0} arquivos, um por sensor) em {1}').format(len(files), folder), "event")

    # ------------------------------------------------------------------ correcao e calibracao
    def _current_corr(self) -> Correction:
        return Correction(mode=self.corr_combo.currentData(), t_ref_c=self.tref_spin.value(),
                          p_ref_kpa=self.pref_spin.value())

    def _corr_for(self, exp: Optional[Experiment]) -> Correction:
        """Correcao a aplicar: o modo escolhido na tela; num experimento salvo, a referencia (T_ref, P_ref)
        gravada nele, para que os volumes fiquem consistentes com a calibracao da epoca."""
        c = self._current_corr()
        if exp is not None and exp is self.view_exp and exp.correction is not None:
            r = exp.correction
            c = Correction(c.mode, r.t_ref_c, r.p_ref_kpa)
        return c

    def _correction_changed(self, *_):
        c = self._current_corr()
        self.ref_label.setText(f"T_ref {c.t_ref_c:.1f} °C · P_ref {c.p_ref_kpa:.2f} kPa" if c.mode == "ref" else "")
        self._save_settings()
        if self.recording and self.live_exp is not None:
            self.live_exp.correction = c
            self.live_exp.save_config()
        self._refresh_view()

    def _ref_from_now(self):
        if self.last_env is None:
            QMessageBox.information(self, APP_NAME, tr('Ainda não há leitura do sensor ambiental (BME280/BMP280).'))
            return
        self.tref_spin.setValue(round(self.last_env.t_c, 2))
        self.pref_spin.setValue(round(self.last_env.p_pa / 1000.0, 3))
        self._log(tr('Referência definida pelas condições atuais: T_ref {0:.2f} °C, P_ref {1:.3f} kPa').format(self.tref_spin.value(), self.pref_spin.value()), "event")

    def _show_calibration(self):
        if self.transport is None:
            QMessageBox.information(self, APP_NAME, tr('Conecte o medidor (ou a simulação) para calibrar.'))
            return
        if getattr(self, "calib_dlg", None) is None:
            self.calib_dlg = CalibrationDialog(self)
        self.calib_dlg.show()
        self.calib_dlg.raise_()

    def apply_calibration(self, ks: dict, t_ref: Optional[float], p_ref: Optional[float]):
        """Chamado pelo assistente: aplica os k medidos e (opcionalmente) a nova referencia T/P."""
        for ch, k in ks.items():
            self.channels[ch - 1].ml_per_tip = k
            self.panels[ch - 1].load(self.channels[ch - 1], pol_editable=self.view_exp is None)
        if t_ref is not None:
            self.tref_spin.setValue(round(t_ref, 2))
        if p_ref is not None:
            self.pref_spin.setValue(round(p_ref, 3))
        self._save_settings()
        if self.recording and self.live_exp is not None:
            self.live_exp.correction = self._current_corr()
            self.live_exp.save_config()
        txt = ", ".join(f"S{ch} = {k:.4f}" for ch, k in sorted(ks.items()))
        self._log(tr('Calibração aplicada (mL/basculamento): {0}').format(txt), "event")
        self._refresh_view()

    # ------------------------------------------------------------------ atualizacao periodica
    def _sim_speed(self):
        if self.sim is not None:
            self.sim.set_speed(self.speed_combo.currentData())
            if self.link:
                self.link.time_scale = self.sim.speed
            self._set_temp_age()

    def _set_temp_age(self):
        """Idade maxima da leitura de temperatura usada num basculamento: 60 s em tempo real; na simulacao
        acelerada as leituras chegam espacadas no tempo simulado, entao o limite cresce com a velocidade."""
        scale = self.link.time_scale if self.link else 1.0
        for exp in (self.live_exp,):
            if exp is not None:
                exp.temp_max_age = 60.0 * max(1.0, scale / 10.0)

    def _refresh_view(self, *_):
        exp = self._shown_exp()
        now = self.link.clock() if self.link else time.time()
        self._update_status()
        if self.settings_dlg.isVisible():
            self._refresh_temp_tab()
        self.st_clock.setText(datetime.now().strftime("%d/%m/%Y  %H:%M:%S"))

        # informacoes do dispositivo (dialogo de ajustes) e ambiente
        if self.last_env and self.view_exp is None:
            e = self.last_env
            rh = tr(" · UR {0:.0f} %").format(e.rh) if e.rh >= 0 else ""
            self.st_env.setText(f"T {e.t_c:.1f} °C · P {e.p_pa / 1000:.2f} kPa{rh}")
            self.st_env.setStyleSheet("padding: 0 8px;")
            self.dev_env.setText(f"T {e.t_c:.2f} °C · P {e.p_pa / 1000:.3f} kPa{rh}")
        elif exp is not None and not exp.has_env() and self.corr_combo.currentData() != "none" \
                and (self.transport is not None or self.view_exp is not None):
            self.st_env.setText(tr('Sem sensor de T/P: volumes sem correção'))
            self.st_env.setStyleSheet(f"padding: 0 8px; background:{ST_WARN}; border-radius:4px;")
        else:
            self.st_env.setText("")
            self.st_env.setStyleSheet("padding: 0 8px;")
        if self.link and self.transport is not None and self.link.last_status:
            st = self.link.last_status
            self.dev_mcu.setText(tr('ligado há {0} · {1} eventos desde o boot · sessão {2}').format(self._fmt_td(st.get('t_ms', 0) / 1000), st.get('next_seq', 0), st.get('session', 0)))

        # tempo decorrido, total de basculamentos e pasta
        if exp is not None and (self.recording or self.view_exp is not None):
            end = exp.end_wall or (now if self.view_exp is None else
                                   max([exp.start_wall] + [l[-1].wall for l in exp.events.values() if l]))
            self.st_elapsed.setText(tr('Tempo decorrido: {0}').format(self._fmt_td(end - exp.start_wall)))
            folder = exp.folder or "–"
        else:
            self.st_elapsed.setText(tr('Tempo decorrido: –'))
            folder = tr('– (pré-visualização: nada é gravado)')
        n_tot = sum(len(l) for l in exp.events.values()) if exp is not None else 0
        self.st_tips.setText(tr('Basculamentos: {0}').format(n_tot))
        self.st_file.setText(tr('Pasta: {0}').format(self._short(folder, 60)))
        self.st_file.setToolTip(folder)

        corr = self._corr_for(exp)
        navg = self.navg_spin.value()
        tunit = tr(self.tunit_combo.currentData())
        k = TIME_UNITS[self.tunit_combo.currentData()]
        mode = self.graph_combo.currentData()
        unit = corr.unit()
        live = self.view_exp is None
        end_h = ((exp.end_wall or now) - exp.start_wall) / 3600.0 if exp is not None else 0.0

        for i, p in enumerate(self.panels):
            ch = i + 1
            if exp is None:
                p.curve.setData([], [])
                p.points.setData([], [])
                p.readout.setText("0.0 mL")
                p.info.setText("")
                continue
            cfg = exp.channels[i]
            t, v = exp.volume_series(ch, corr)
            qnow = exp.current_flow(ch, now if live else (exp.end_wall or now), navg, corr)
            p.readout.setText(f"{v[-1]:.1f} mL")
            p.readout.setToolTip(tr('Volume acumulado ({0})').format(unit))
            tch = self._channel_temp(i) if live else (exp.events[ch][-1].t_c if exp.events[ch] else None)
            p.info.setText(tr('{0} basc. · {1:.1f} mL/h').format(exp.tip_count(ch), qnow)
                           + (f" · {tch:.1f} °C" if tch is not None else ""))
            # o autoscale sempre inclui de t = 0 ate o instante atual (ou o fim do experimento)
            p.floor.setData([0, max(end_h, t[-1], 1e-3) * k], [0, 10])
            p.plot.setLabel("bottom", tr('Tempo ({0})').format(tunit), **{"font-size": "8pt"})
            if not cfg.enabled:
                p.curve.setData([], [])
                p.points.setData([], [])
                p.info.setText(tr('canal desativado'))
                continue
            if mode == "vol":
                p.plot.setLabel("left", tr('Volume ({0})').format(unit), **{"font-size": "8pt"})
                tt = np.append(t, max(end_h, t[-1])) if live else t
                vv = np.append(v, v[-1]) if live else v
                p.curve.setData(tt * k, vv)
                p.points.setData([], [])
            else:
                p.plot.setLabel("left", tr('Vazão ({0}/h)').format(unit), **{"font-size": "8pt"})
                tq, q = exp.flow_series(ch, navg, corr)
                p.curve.setData([], [])
                p.points.setData(tq * k, q)
            # a escala e feita pelo autoscale do grafico (desligado enquanto o usuario arrasta/da zoom)

    @staticmethod
    def _short(path, n=38):
        return path if len(path) <= n else "…" + path[-(n - 1):]

    @staticmethod
    def _fmt_td(sec: float) -> str:
        sec = max(0, int(sec))
        d, r = divmod(sec, 86400)
        h, r = divmod(r, 3600)
        m, s = divmod(r, 60)
        return (f"{d} d " if d else "") + f"{h:02d}:{m:02d}:{s:02d}"

    # ------------------------------------------------------------------ fechamento
    def closeEvent(self, ev):
        if self.recording:
            r = QMessageBox.question(self, APP_NAME, tr('Há uma gravação em andamento. Fechar o programa?\nOs dados já gravados ficam salvos. O MCU continua contando e os eventos podem ser recuperados se o programa for reaberto em pouco tempo.'))
            if r != QMessageBox.Yes:
                ev.ignore()
                return
            self.live_exp.end_wall = self.link.clock() if self.link else time.time()
            self.live_exp.close_files()
            self.live_exp.save_config()
        if self.transport is not None:
            self.transport.stop()
        self._save_settings()
        self._log(tr('Programa encerrado'), "info")
        ev.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    w = MainWindow(start_sim="--sim" in sys.argv)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
