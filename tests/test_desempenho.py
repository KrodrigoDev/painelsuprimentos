"""Otimizações: cache com recarga em segundo plano, gzip, janela com dados no servidor, SLA vetorizado."""
import gzip
import threading
import time

import numpy as np
import pandas as pd
from flask import Flask

from app import desempenho
from app.cache import CacheSWR
from app.components import detalhe
from app.services import sla


def test_cache_serve_anterior_e_recarrega_em_segundo_plano():
    c = CacheSWR("teste", ttl_padrao_min=0.0005)            # ~0,03 s
    versoes = iter(["v1", "v2"])
    lento = threading.Event()

    def carregar():
        v = next(versoes)
        if v == "v2":
            lento.wait(2)
        return v
    assert c.obter("k", carregar) == "v1"
    time.sleep(0.05)
    t0 = time.perf_counter()
    assert c.obter("k", carregar) == "v1"                   # vencido: devolve o anterior na hora
    assert time.perf_counter() - t0 < 0.5
    lento.set()
    for _ in range(50):
        if c.dados["k"][1] == "v2":
            break
        time.sleep(0.02)
    assert c.obter("k", carregar) == "v2"


def test_cache_trava_por_chave():
    c = CacheSWR("teste")
    liberar = threading.Event()
    threading.Thread(target=lambda: c.obter("lenta", lambda: (liberar.wait(2), "x")[1]), daemon=True).start()
    time.sleep(0.05)
    t0 = time.perf_counter()
    assert c.obter("rapida", lambda: "y") == "y"            # não espera a outra chave
    assert time.perf_counter() - t0 < 0.5
    liberar.set()


def test_gzip_comprime_json_grande():
    app = Flask(__name__)
    desempenho.instalar_compressao(app)
    corpo = '{"a": "' + "x" * 5000 + '"}'
    app.add_url_rule("/j", "j", lambda: app.response_class(corpo, mimetype="application/json"))
    app.add_url_rule("/p", "p", lambda: app.response_class("{}", mimetype="application/json"))
    cli = app.test_client()
    r = cli.get("/j", headers={"Accept-Encoding": "gzip, deflate"})
    assert r.headers["Content-Encoding"] == "gzip" and gzip.decompress(r.data).decode() == corpo
    assert len(r.data) < len(corpo) / 10
    assert "Content-Encoding" not in cli.get("/j").headers           # cliente sem gzip
    assert "Content-Encoding" not in cli.get("/p", headers={"Accept-Encoding": "gzip"}).headers  # pequeno


def test_janela_guarda_dados_no_servidor():
    df = pd.DataFrame({"a": range(5000), "v": np.arange(5000) * 1.5})
    cols = [{"campo": "a", "rotulo": "A", "formato": "texto"}, {"campo": "v", "rotulo": "Valor", "formato": "brl", "total": True}]
    estilo, titulo, sub, corpo, store = detalhe.abrir("T", "S", df, cols)
    assert set(store) == {"token"}                          # navegador só recebe o token
    t, s, c, guardado = detalhe._recuperar(store["token"])
    assert len(guardado) == 5000 and t == "T"
    grade = corpo.children[1]                               # [aviso de limite, grade]
    assert len(grade.rowData) == detalhe.LIMITE_TELA
    assert grade.dashGridOptions["pinnedBottomRowData"][0]["v"] == float(df["v"].sum())  # total de TODAS as linhas
    assert detalhe._recuperar("inexistente") is None


def _por_referencia(d, dim, contar):
    """Cálculo original (laço por grupo com resumo_fase) — referência para o vetorizado."""
    linhas = []
    for chave, g in d.groupby(dim, dropna=False):
        r1, r2 = sla.resumo_fase(g, "f1", contar), sla.resumo_fase(g, "f2", contar)
        linhas.append({dim: chave, "n_f1": r1["base_pct"], "pct_f1": r1["pct"], "mediana_f1": r1["mediana_dias"],
                       "n_f2": r2["base_pct"], "pct_f2": r2["pct"], "atrasados_f2": r2["atrasados_abertos"]})
    return pd.DataFrame(linhas).set_index(dim)


def test_sla_por_vetorizado_igual_ao_calculo_por_grupo():
    rng = np.random.default_rng(7)
    n = 600
    sit = ["no_prazo", "fora_prazo", "aberto_no_prazo", "em_risco", "atrasado", "sem_prazo", "fora"]
    d = pd.DataFrame({
        "g": rng.choice(["A", "B", "C", None], n), "f1": rng.choice(sit, n), "f2": rng.choice(sit, n),
        "dias_fase1": rng.integers(0, 40, n).astype(float), "dias_fase2": rng.integers(0, 60, n).astype(float),
        "lt_fase1": rng.choice([5.0, 10.0, np.nan], n), "lt_fase2": rng.choice([15.0, 30.0], n),
        "linha_do_item": rng.random(n) > .3, "atraso_obra": rng.normal(0, 10, n)})
    for contar in (True, False):
        novo = sla.por(d, "g", contar).set_index("g").sort_index()
        ref = _por_referencia(d, "g", contar).sort_index()
        for c in ref.columns:
            pd.testing.assert_series_equal(novo[c].astype(float), ref[c].astype(float), check_names=False)
