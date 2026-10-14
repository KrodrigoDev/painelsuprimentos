"""Regras das telas Adiantamento e Curva ABC (DataFrames sintéticos, sem banco)."""
import numpy as np
import pandas as pd
import pytest

from app.services import adiantamento as ad
from app.services import curva_abc as ca

_ID = iter(range(1, 10_000))


def mov(data, tipo, valor, doc="100", credor=1, empresa=1, vinculo="Pedido de compra"):
    sinal = {"Adiantamento": 1, "Abatimento": -1, "Realocação (Saída)": -1}[tipo]
    return dict(id_movimento=next(_ID), cod_empresa=empresa, empresa=f"E{empresa}", cod_credor=credor,
                credor=f"C{credor}", documento_vinculado=doc, numero_vinculo=doc, tipo_vinculo=vinculo,
                data_movimento=pd.Timestamp(data), tipo_movimento=tipo, valor=valor, efeito_saldo=sinal * valor)


BASE = pd.DataFrame([
    mov("2024-01-10", "Adiantamento", 1000), mov("2024-03-01", "Abatimento", 400),
    mov("2026-05-01", "Adiantamento", 500, doc="CTS /9", credor=2, vinculo="Contrato"),
    mov("2026-06-01", "Realocação (Saída)", 100, doc="CTS /9", credor=2, vinculo="Contrato"),
])


def test_saldo_e_posicao_nao_dependem_do_inicio_do_periodo():
    per, pos, ref = ad.filtrar(BASE, ini="2026-01-01", fim="2026-12-31")
    r = ad.resumo(per, pos, ref)
    assert r["adiantado"] == 500 and r["abatido"] == 0 and r["realocado"] == 100
    assert r["saldo"] == pytest.approx(600 + 400)      # posição: doc 100 (600) + doc CTS/9 (400)
    assert r["credores_com_saldo"] == 2


def test_documento_idade_e_situacao():
    _, pos, ref = ad.filtrar(BASE, fim="2026-06-30")
    d = ad.por_documento(pos, ref).set_index("documento_vinculado")
    assert d.at["100", "saldo"] == 600 and d.at["100", "dias_em_aberto"] == (ref - pd.Timestamp("2024-01-10")).days
    assert d.at["CTS /9", "situacao"] == "Em aberto"
    idade = ad.idade_saldo(ad.por_documento(pos, ref)).set_index("faixa")
    assert idade.at["mais de 1 ano", "saldo"] == 600 and idade.at["31 a 90 dias", "saldo"] == 400


def test_filtro_tipo_nao_altera_saldo():
    per, pos, ref = ad.filtrar(BASE, tipos=["Abatimento"])
    assert (per["tipo_movimento"] == "Abatimento").all()
    assert ad.resumo(per, pos, ref)["saldo"] == pytest.approx(1000)


def linha(ano, chave, det, q, v, un="un", nc=False):
    cod = int(chave.split("|")[1])
    return dict(ano=ano, chave_insumo=chave, cod_insumo=cod, insumo=f"INS {cod}", detalhe=det, tabela="T",
                cod_tabela=1, cod_grupo_insumo="02.014", grupo_insumo="EPI", origem_grupo="x", tipo_insumo="IM",
                unidade_padrao=un, quantidade=q, preco_total=v, qtd_nao_convertida=nc, classe_abc="A")


def test_variacao_sem_efeito_de_mix():
    # mesmo preço por detalhe nos dois anos, só o mix muda -> preço médio sobe, variação real = 0
    df = ca.preparar(pd.DataFrame([
        linha(2025, "1|10", "P", 90, 900), linha(2025, "1|10", "G", 10, 200),
        linha(2026, "1|10", "P", 10, 100), linha(2026, "1|10", "G", 90, 1800),
    ]))
    s, info = ca.serie_insumo(df, "1|10")
    assert s["var_yoy_pct"].iat[1] > 50                  # preço médio (com mix): 11 -> 19
    assert s["var_mesmos_pct"].iat[1] == pytest.approx(0)
    assert info["var_yoy"] == pytest.approx(0)
    rk = ca.ranking(df, 2026, 2025)
    assert rk["var_preco_pct"].iat[0] == pytest.approx(0) and rk["efeito_preco"].iat[0] == pytest.approx(0)


def test_preco_medio_ignora_quantidade_nao_convertida_e_outra_unidade():
    df = ca.preparar(pd.DataFrame([linha(2026, "1|20", "A", 10, 100), linha(2026, "1|20", "B", 1, 999, nc=True),
                                   linha(2026, "1|20", "C", 2, 5, un="cx")]))
    p, q, u = ca.preco_medio(df)
    assert (p, q, u) == (10.0, 10.0, "un")


def test_variacao_extrema_descartada():
    df = ca.preparar(pd.DataFrame([linha(2025, "1|30", "A", 1000, 2), linha(2026, "1|30", "A", 1, 500)]))
    assert ca.ranking(df, 2026, 2025)["var_preco_pct"].isna().all()   # 250x: provável erro de unidade


def test_classe_abc_no_recorte():
    v = pd.Series([70.0, 15.0, 10.0, 5.0], index=list("abcd"))
    _, acum, classe = ca.classificar(v)
    assert classe.tolist() == ["A", "A", "B", "C"] and acum["d"] == pytest.approx(100)
