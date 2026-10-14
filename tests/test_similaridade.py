"""Testes da busca por similaridade (sem banco: o repositório é substituído por dados fixos)."""
import pandas as pd
import pytest

from app.services import similaridade
from app.services.texto import normalizar_texto

INSUMOS = pd.DataFrame([
    # id, descrição, categoria, unidade
    (1, "CIMENTO PORTLAND CP II-F-32 SACO 50KG", "AGLOMERANTES", "sc"),
    (2, "CIMENTO CP-II F 32 50 KG", "AGLOMERANTES", "sc"),
    (3, "CIMENTO BRANCO ESTRUTURAL 25KG", "AGLOMERANTES", "sc"),
    (4, "CAL HIDRATADA CH-III 20KG", "AGLOMERANTES", "sc"),
    (5, "SACO DE LIXO PRETO 100L", "LIMPEZA", "pct"),
    (6, "VERGALHÃO AÇO CA-50 10MM", "FERRAGENS", "kg"),
    (7, "CABO FLEXIVEL 2,5MM 750V AZUL", "ELETRICA", "m"),
    (8, "CABO FLEXIVEL 10MM 750V PRETO", "ELETRICA", "m"),
], columns=["id_insumo", "descricao_completa", "categoria", "unidade_padrao"]).assign(
    cod_insumo=lambda d: d.id_insumo, cod_detalhe=0, tipo_insumo="IM", n_itens=5, total_gasto=1000.0,
    descricao_normalizada=lambda d: d.descricao_completa.map(normalizar_texto))


@pytest.fixture
def indice(monkeypatch):
    monkeypatch.setattr(similaridade.suprimentos_repo, "insumos_com_compra", lambda: INSUMOS.copy())
    return similaridade.IndiceSimilaridade(ttl_minutos=60)


def test_busca_fica_na_categoria(indice):
    res = indice.buscar("saco", "FERRAGENS", score_minimo=0)
    assert set(res["categoria"]) <= {"FERRAGENS"}
    assert 5 not in res["id_insumo"].tolist()  # "saco" nunca traz item de outra categoria


def test_variantes_do_mesmo_item_no_topo(indice):
    res = indice.buscar("cimento cp ii 50kg", "AGLOMERANTES", score_minimo=0)
    assert set(res.head(2)["id_insumo"]) == {1, 2}
    assert res.iloc[-1]["id_insumo"] == 4  # cal fica por último


def test_medida_diferente_e_penalizada(indice):
    res = indice.buscar("cabo flexivel 2,5mm", "ELETRICA", score_minimo=0)
    assert res.iloc[0]["id_insumo"] == 7
    assert res.set_index("id_insumo").at[8, "numeros_ausentes"] >= 1


def test_normalizacao():
    assert normalizar_texto("Vergalhão AÇO CA-50 1,25mm") == "vergalhao aco ca 50 1.25mm"
    assert normalizar_texto(None) == ""


def test_sugerir_descobre_categoria(indice):
    sug = indice.sugerir("cal hidratada")
    assert sug.iloc[0]["categoria"] == "AGLOMERANTES"
