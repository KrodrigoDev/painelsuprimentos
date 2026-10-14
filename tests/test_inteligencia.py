"""
Inteligência de compras no PAINEL: só leitura + filtros da tela sobre o que o ETL gravou.
(Os cenários do cálculo — fornecedor mais barato, aumento, atípicos, dupla contagem — foram para
airflow_api_sienge/repo/tests/test_inteligencia_compras.py, junto com o cálculo.)
DataFrames SINTÉTICOS montados no teste (sem banco).
"""
import pandas as pd
import pytest

from app.services import inteligencia as ig


def op(tipo, grupo="G1", forn=1, obra="10", pct=10.0, imp=1000.0, nivel=85, data="2026-05-01", prio=50.0, cat="CAT"):
    return dict(nivel_confianca=nivel, tipo=tipo, id_grupo=grupo, cod_fornecedor=forn, cod_obra=obra, diferenca_pct=pct,
                impacto=imp, data_atual=pd.Timestamp(data), prioridade=prio, categoria=cat, entra_no_total=False,
                obra_filtro=obra, fornecedor_filtro=float(forn) if forn is not None else None)


def test_limites_da_tela_filtram_a_e_c_mas_nao_o_aumento():
    ops = pd.DataFrame([op("fornecedor_mais_barato", pct=3), op("diferenca_obras", imp=100),
                        op("aumento_historico", pct=12, imp=50), op("fornecedor_mais_barato", grupo="G2", pct=8)])
    s = ig.selecionar(ops, cfg=ig.ConfigOportunidade(min_diferenca_pct=5, min_impacto=500))
    assert sorted(s["tipo"]) == ["aumento_historico", "fornecedor_mais_barato"]


def test_sem_dupla_contagem_recalculada_nas_linhas_filtradas():
    ops = pd.DataFrame([op("fornecedor_mais_barato"), op("aumento_historico", imp=2000),
                        op("aumento_historico", grupo="G2", imp=2000)])
    s = ig.selecionar(ops, cfg=ig.ConfigOportunidade(min_impacto=500)).set_index(["tipo", "id_grupo"])
    assert s.loc[("fornecedor_mais_barato", "G1"), "entra_no_total"]
    assert not s.loc[("aumento_historico", "G1"), "entra_no_total"]   # mesmo material e fornecedor: já contado
    assert s.loc[("aumento_historico", "G2"), "entra_no_total"]


def test_aumento_volta_a_somar_quando_o_fornecedor_mais_barato_sai_pelo_limite():
    ops = pd.DataFrame([op("fornecedor_mais_barato", pct=3), op("aumento_historico", imp=2000)])
    s = ig.selecionar(ops, cfg=ig.ConfigOportunidade(min_diferenca_pct=5, min_impacto=500))
    assert list(s["tipo"]) == ["aumento_historico"] and s["entra_no_total"].all()


def test_filtros_pela_compra_atual_e_nivel_de_confianca():
    ops = pd.DataFrame([op("fornecedor_mais_barato", obra="10", data="2026-01-10"),
                        op("fornecedor_mais_barato", grupo="G2", obra="20", data="2026-06-10"),
                        op("fornecedor_mais_barato", grupo="G3", nivel=95)])
    s = ig.selecionar(ops, ini="2026-03-01", cfg=ig.CFG_PADRAO)
    assert list(s["id_grupo"]) == ["G2"]
    s = ig.selecionar(ops, obras=["10"], cfg=ig.CFG_PADRAO)
    assert list(s["id_grupo"]) == ["G1"]
    assert list(ig.selecionar(ops, cfg=ig.ConfigOportunidade(confianca_minima=95))["id_grupo"]) == ["G3"]


@pytest.mark.parametrize("conf,nivel", [(85, 85), (88, 90), (90, 90), (95, 95), (100, 100)])
def test_nivel_gravado(conf, nivel):
    assert ig.nivel(ig.ConfigOportunidade(confianca_minima=conf)) == nivel


def test_evolucao_mensal_soma_o_excesso_do_nivel():
    d = pd.DataFrame({"ano_mes": ["2026-01", "2026-01", "2026-02"], "valor": [10.0, 20.0, 5.0],
                      "excesso_c85": [1.0, 2.0, 0.0], "excesso_c95": [0.0, 0.0, 0.0]})
    m = ig.evolucao_mensal(d, ig.CFG_PADRAO).set_index("ano_mes")
    assert m.loc["2026-01", "excesso"] == 3 and m.loc["2026-01", "valor"] == 30
    assert ig.evolucao_mensal(d, ig.ConfigOportunidade(confianca_minima=95))["excesso"].sum() == 0


def test_com_rastreio_solicitacao_e_pedido(monkeypatch):
    from app.repositories import rpa_repo
    from app.services import inteligencia as ig
    mapa = pd.DataFrame({"cod_pedido": [69343, 500], "cod_insumo": [10660, 7], "solicitacoes": ["120, 135", "88"]}
                        ).set_index(["cod_pedido", "cod_insumo"])
    monkeypatch.setattr(rpa_repo, "solicitacoes_por_pedido", lambda: mapa)
    ops = pd.DataFrame({
        "evidencia_atual": [{"pedido": 69343, "item": 2, "cod_insumo": 10660, "data": "2026-05-01"},
                            {"pedido": 70000, "item": 1, "cod_insumo": 1, "data": "2026-06-01"}],
        "evidencia_referencia": [{"pedido": 500, "item": 3, "cod_insumo": 7, "data": "2026-01-10"}, None]})
    r = ig.com_rastreio(ops)
    assert r["pedido_atual"].tolist() == ["69343", "70000"]          # texto: sem "69.343"
    assert r["solicitacao_atual"].tolist() == ["120, 135", None]      # pedido fora do painel de compras -> vazio
    assert r["pedido_ref"].tolist() == ["500", None] and r["solicitacao_ref"].tolist() == ["88", None]
    assert r["item_atual"].tolist() == ["2", "1"]
