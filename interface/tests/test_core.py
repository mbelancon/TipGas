"""
Testes do nucleo usando o simulador (executar: python -m pytest tests  ou  python tests/test_core.py)
Verifica: recuperacao de linhas perdidas (GET), desconexao temporaria, reinicio do MCU,
calculo de volume/vazao e gravacao/leitura do experimento.
"""
import os
import sys
import tempfile
import time

os.environ["TIPGAS_LANG"] = "pt"       # mensagens comparadas nos testes estao em portugues
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tipgas_core import DeviceLink, Experiment, default_channels, NUM_CHANNELS, Correction, p_h2o_kpa  # noqa: E402
from simulator import SimulatedDevice  # noqa: E402


def run(sim, link, seconds, step=0.01):
    t_end = time.time() + seconds
    while time.time() < t_end:
        sim.tick()
        time.sleep(step)


def make(line_loss=0.0, speed=20000.0, folder=None):
    sim = SimulatedDevice(seed=1, speed=speed, line_loss=line_loss)
    link = DeviceLink(clock=sim.clock, time_scale=speed)
    sim.on_line = link.handle_line
    link.send = sim.write
    got = []
    logs = []
    link.on_log = logs.append
    exp = Experiment("teste", folder, default_channels(), start_wall=sim.clock())
    if folder:
        exp.open_files()

    def on_ev(ev):
        got.append(ev)
        exp.add_event(ev)
    link.on_event = on_ev
    link.on_env = exp.add_env
    link.on_temp = exp.add_temp
    link.connection_opened()
    return sim, link, exp, got, logs


def check_complete(sim, got):
    seqs = sorted((e.session, e.seq) for e in got)
    assert len(seqs) == len(set(seqs)), "eventos duplicados"
    per_ch = {c: 0 for c in range(1, NUM_CHANNELS + 1)}
    for e in got:
        per_ch[e.channel] += 1
    return per_ch


def test_line_loss_recovered():
    sim, link, exp, got, logs = make(line_loss=0.3)
    run(sim, link, 2.5)
    sim.write("ST?")
    per_ch = check_complete(sim, got)
    for i, ch in enumerate(sim.channels):
        assert per_ch[i + 1] == ch.count, (i, per_ch[i + 1], ch.count)
    assert sum(per_ch.values()) > 50


def test_disconnect_and_reset():
    sim, link, exp, got, logs = make()
    run(sim, link, 1.0)
    sim.disconnect_for(0.5)
    run(sim, link, 1.0)
    before_reset = {c: 0 for c in range(1, 10)}
    for e in got:
        before_reset[e.channel] += 1
    for i, ch in enumerate(sim.channels):
        assert before_reset[i + 1] == ch.count, "falhou recuperar apos desconexao"
    total_before = dict(before_reset)
    sim.reset_mcu()
    run(sim, link, 1.0)
    assert any("Reinício" in s for s in logs), logs
    per_ch = check_complete(sim, got)
    for i, ch in enumerate(sim.channels):
        assert per_ch[i + 1] == total_before[i + 1] + ch.count
    assert link.session == 2


def test_volume_flow_and_files():
    with tempfile.TemporaryDirectory() as d:
        sim, link, exp, got, logs = make(folder=d)
        run(sim, link, 2.0)
        exp.end_wall = sim.clock()
        exp.close_files()
        exp.save_config()
        ch = max(range(1, 10), key=exp.tip_count)
        t, v = exp.volume_series(ch)
        assert abs(v[-1] - exp.tip_count(ch) * 10.0) < 1e-6
        tq, q = exp.flow_series(ch, n_avg=3)
        assert len(q) > 0 and (q > 0).all()
        _, vs = exp.volume_series(ch, Correction("stp_dry"))
        assert vs[-1] < v[-1]           # 92.5 kPa e ~24 °C: volume padrao seco menor
        exp.export_resampled(os.path.join(d, "res.csv"), 30, Correction("ref", 20.0, 92.5))
        files = exp.export_events(os.path.join(d, "exp"), Correction("ref", 20.0, 92.5))
        assert len(files) == sum(1 for c in range(1, 10) if exp.tip_count(c))
        assert sum(sum(1 for _ in open(f)) - 1 for f in files) == sum(exp.tip_count(c) for c in range(1, 10))
        # gravacao: um arquivo por canal com 2 colunas (tempo, volume) + detalhes/basculamentos.csv
        import glob, csv as _csv
        per = glob.glob(os.path.join(d, "S[1-9]_*.csv"))
        assert len(per) == 9                      # todos os canais ativos tem arquivo
        for f in per:
            rows = list(_csv.reader(open(f)))
            assert rows[0] == ["tempo_h", "volume_mL"] and all(len(r) == 2 for r in rows)
            ch_f = int(os.path.basename(f)[1])
            assert len(rows) - 1 == exp.tip_count(ch_f)
            if len(rows) > 1:
                assert abs(float(rows[-1][1]) - exp.tip_count(ch_f) * 10.0) < 1e-6
        det = list(_csv.DictReader(open(os.path.join(d, "detalhes", "basculamentos.csv"))))
        assert len(det) == sum(exp.tip_count(c) for c in range(1, 10))
        exp2 = Experiment.load(d)
        assert exp2.tip_count(ch) == exp.tip_count(ch)
        assert len(exp2.env) == len(exp.env)
        assert abs(exp2.events[ch][-1].wall - exp.events[ch][-1].wall) < 0.01


def test_correction_formulas():
    import numpy as np
    assert abs(p_h2o_kpa(25.0) - 3.158) < 0.005          # Antoine com (D + T)
    assert abs(p_h2o_kpa(100.0) - 101.3) < 0.3
    c = Correction("ref", t_ref_c=25.0, p_ref_kpa=93.0)
    assert abs(c.factors(np.array([25.0]), None)[0] - 1.0) < 1e-12     # nas condicoes da calibracao, F = 1
    # mais quente que a calibracao -> bolha maior que a de referencia -> F < 1
    f30 = c.factors(np.array([30.0]), None)[0]
    expected = (298.15 / 303.15) * (93.0 - p_h2o_kpa(30.0)) / (93.0 - p_h2o_kpa(25.0))
    assert abs(f30 - expected) < 1e-12 and f30 < 1
    # modo "ref": a pressao medida nao entra (P constante = P_ref, como no artigo)
    assert abs(c.factors(np.array([25.0]), np.array([95.0]))[0] - 1.0) < 1e-12
    s = Correction("stp_dry").factors(np.array([0.0]), np.array([101.325 + p_h2o_kpa(0.0)]))[0]
    assert abs(s - 1.0) < 1e-9


def test_ds18b20_temperature_per_tip():
    with tempfile.TemporaryDirectory() as d:
        # 600x: cada passo de 10 ms do teste = 6 s simulados (o DS18B20 le a cada 2 s)
        sim, link, exp, got, logs = make(folder=d, speed=600.0)
        rom = sim.ds_roms[0]
        for c in exp.channels[:4]:
            c.temp_sensor = rom                   # S1-S4 com DS18B20; S5-S9 usam o BME280
        exp.correction = Correction("ref", 25.0, 92.5)
        run(sim, link, 4.0)
        exp.close_files()
        assert rom in exp.temps and len(exp.temps[rom]) > 3
        t_first = exp.temps[rom][0].wall          # antes da primeira leitura do DS18B20 vale o BME280
        ds_tips = [e for ch in range(1, 5) for e in exp.events[ch] if e.wall >= t_first + 1]
        bme_tips = [e for ch in range(5, 10) for e in exp.events[ch]]
        assert ds_tips and all(e.t_src == rom for e in ds_tips)
        assert all(e.t_src == "BME280" for e in bme_tips if e.t_c is not None)
        # a temperatura registrada e a ultima leitura do DS18B20 disponivel no instante do basculamento
        for e in ds_tips[:20]:
            before = [t for t in exp.temps[rom] if t.wall <= e.wall]
            near = min(exp.temps[rom], key=lambda t: abs(t.wall - e.wall))
            assert e.t_c in (before[-1].t_c if before else None, near.t_c)
        # F_i usa exatamente a temperatura registrada
        import numpy as np
        ch = max(range(1, 10), key=exp.tip_count)
        F = exp.correction_factors(ch, exp.correction)
        has_t = np.array([e.t_c is not None for e in exp.events[ch]])
        Fexp = exp.correction.factors(np.array([e.t_c for e in exp.events[ch] if e.t_c is not None]), None)
        assert np.allclose(F[has_t], Fexp) and np.all(F[~has_t] == 1.0)
        # gravado no arquivo do sensor e relido igual
        exp2 = Experiment.load(d)
        assert [e.t_c for e in exp2.events[ch]] == [round(e.t_c, 2) if e.t_c is not None else None
                                                    for e in exp.events[ch]]
        assert len(exp2.temps[rom]) == len(exp.temps[rom])


if __name__ == "__main__":
    test_ds18b20_temperature_per_tip()
    test_correction_formulas()
    test_line_loss_recovered()
    test_disconnect_and_reset()
    test_volume_flow_and_files()
    print("todos os testes passaram")
