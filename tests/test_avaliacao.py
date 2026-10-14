"""Avaliação de fornecedores: classificação 0-4 (A até 2,0 · B 2,1-3,4 · C 3,5-4,0), bases e delta."""
import pandas as pd
import pytest

from app.services import avaliacao as av


def lin(cod, mes, n, nota, atual=3.0):
    m = pd.Timestamp(mes)
    return dict(cod_fornecedor=cod, fornecedor=f"F{cod}", mes_referencia=m, ano_mes=m.strftime("%Y-%m"),
                numero_avaliacoes=n, avaliacao_periodo=nota, avaliacao_atual=atual)


BASE = pd.DataFrame([lin(1, "2026-06-01", 5, 3.0), lin(1, "2026-08-01", 5, 3.8), lin(1, "2026-10-01", 1, 2.0),
                     lin(2, "2026-08-01", 10, 4.0, 3.9), lin(3, "2026-09-01", 2, 2.04, 2.4)])


@pytest.mark.parametrize("nota,classe", [(0, "A"), (2.0, "A"), (2.04, "A"), (2.05, "B"), (2.1, "B"), (3.4, "B"),
                                         (3.45, "C"), (3.5, "C"), (4.0, "C")])
def test_faixas(nota, classe):
    assert av.classificar([nota]).iat[0] == classe


def test_bases_de_classificacao():
    d = av.filtrar(BASE, "2026-08-01", "2026-10-31")
    pior = av.por_fornecedor(d, "pior").set_index("cod_fornecedor")
    media = av.por_fornecedor(d, "media").set_index("cod_fornecedor")
    assert pior.at[1, "classe"] == "A"                      # teve um mês com 2,0
    assert media.at[1, "nota"] == pytest.approx((5 * 3.8 + 2.0) / 6) and media.at[1, "classe"] == "C"
    assert av.por_fornecedor(d, "atual").set_index("cod_fornecedor").at[3, "classe"] == "B"


def test_media_geral_e_ponderada():
    d = av.filtrar(BASE, "2026-08-01", "2026-10-31")
    r = av.resumo(d, av.por_fornecedor(d))
    assert r["avaliacoes"] == 18
    assert r["media"] == pytest.approx((5 * 3.8 + 1 * 2.0 + 10 * 4.0 + 2 * 2.04) / 18)


def test_delta_usa_mes_avaliado_anterior_fora_do_filtro():
    d = av.filtrar(BASE, "2026-08-01", "2026-10-31")
    m, meses = av.matriz(BASE, d, [1])
    r = m.iloc[0]
    assert r["d_2026_08"] == pytest.approx(0.8)              # vs junho (fora do filtro; julho sem avaliação)
    assert r["d_2026_10"] == pytest.approx(-1.8)
    assert meses == ["2026-08", "2026-09", "2026-10"]
