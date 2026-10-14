"""Testes dos cálculos de saving (pandas puro)."""
import pandas as pd
import pytest

from app.services import saving


@pytest.fixture
def compras():
    return pd.DataFrame({
        "ano_mes": ["2026-01", "2026-01", "2026-02", "2026-02"],
        "cod_obra": ["A", "B", "A", "B"], "obra": ["Obra A", "Obra B", "Obra A", "Obra B"],
        "cod_fornecedor": [1, 2, 1, 2], "fornecedor": ["F1", "F2", "F1", "F2"],
        "cod_pedido": [10, 11, 12, 13], "data_pedido": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-02-01", "2026-02-02"]),
        "id_insumo": 1, "cod_insumo": 1, "descricao_completa": "CIMENTO",
        "quantidade": [10.0, 10.0, 10.0, 10.0], "preco": [20.0, 25.0, 22.0, 30.0],
    }).assign(valor_total=lambda d: d.quantidade * d.preco)


def test_resumo(compras):
    r = saving.resumo(saving.enriquecer(compras))
    assert r.total_gasto == pytest.approx(970)
    assert r.preco_medio_pond == pytest.approx(24.25)
    assert (r.menor_preco, r.maior_preco) == (20, 30)
    # jan: (25-20)*10 = 50 ; fev: (30-22)*10 = 80
    assert r.saving_menor_mes == pytest.approx(130)
    # período: (0+5+2+10)*10
    assert r.saving_menor_periodo == pytest.approx(170)
    assert r.fornecedor_menor_preco == "F1"


def test_por_fornecedor_ordena_pelo_preco(compras):
    t = saving.por_fornecedor(saving.enriquecer(compras))
    assert t["fornecedor"].tolist() == ["F1", "F2"]
    assert t.set_index("fornecedor").at["F2", "preco_medio_pond"] == pytest.approx(27.5)


def test_por_mes_aponta_quem_fez_menor_preco(compras):
    t = saving.por_mes(saving.enriquecer(compras))
    assert t["fornecedor_menor_preco"].tolist() == ["F1", "F1"]
