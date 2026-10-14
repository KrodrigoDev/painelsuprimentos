"""Visão geral: panorama por vertical/obra e pontos de atenção com áreas sintéticas (sem banco)."""
import numpy as np
import pandas as pd

from app.services import visao_geral as vg
from app.services.visao_geral import Area


def _areas():
    compras = pd.DataFrame({"segmento": ["MCMV", "MCMV", "PÚBLICA"], "cod_obra": [137, 120, 1806],
                            "obra": ["137 - A", "120 - B", "1806 - C"], "valor": [100.0, 50.0, 30.0]})
    ops = pd.DataFrame({"segmento": ["MCMV", "PÚBLICA"], "obra_filtro": [137, 1806], "impacto": [10.0, 4.0]})
    estoque = pd.DataFrame({"segmento": ["MCMV", "SEM SEGMENTO"], "cod_centro_custo": [137, 999],
                            "centro_rotulo": ["137 - A", "999 - X"], "valor_estoque": [20.0, 0.0]})
    contratos = pd.DataFrame({"segmento": ["MCMV", "PÚBLICA"], "cod_obra": [120, 1806], "obra_rotulo": ["120 - B", "1806 - C"],
                              "saldo_aberto": [40.0, 60.0], "vencido_com_saldo": [True, False]})
    return {
        "compras": Area("compras", "Compras", "/", kpis={"_ops": ops, "economia": 14.0, "oportunidades": 2,
                                                          "atipicos": 0}, dados=compras),
        "estoque": Area("estoque", "Estoque", "/estoque", kpis={"inativos_com_saldo": 3, "abaixo_minimo": 1},
                        dados=estoque),
        "contratos": Area("contratos", "Contratos", "/contratos", kpis={"vencidos": 1, "saldo_vencidos": 40.0},
                          dados=contratos),
        "sla": Area("sla", "SLA", "/sla-insumos", ok=False, erro="sem carga"),
    }


def test_panorama_por_vertical_soma_e_descarta_vazias():
    p = vg.panorama(_areas(), "segmento").set_index("segmento")
    assert list(p.index) == ["MCMV", "PÚBLICA"]            # SEM SEGMENTO só com zeros sai
    assert p.loc["MCMV", "compras"] == 150 and p.loc["MCMV", "economia"] == 10
    assert p.loc["MCMV", "contratos_vencido"] == 40 and p.loc["PÚBLICA", "contratos_vencido"] == 0
    assert p.loc["MCMV", "exposicao"] == 20 + 40
    assert p["sla_f1"].isna().all()                          # área indisponível não quebra o panorama


def test_panorama_por_obra_traz_nome_e_vertical():
    p = vg.panorama(_areas(), "cod_obra").set_index("cod_obra")
    assert set(p.index) == {137, 120, 1806}
    assert p.loc[137, "estoque"] == 20 and p.loc[120, "contratos_saldo"] == 40
    assert p.loc[1806, "segmento"] == "PÚBLICA" and str(p.loc[137, "nome"]).startswith("137")


def test_pontos_de_atencao_ordem_e_fontes():
    fontes = pd.DataFrame({"fonte": ["Estoque", "Contratos"], "rota": ["/estoque", "/contratos"],
                           "posicao": [pd.Timestamp("2026-10-01")] * 2, "situacao": ["incompleta", "ok"],
                           "detalhe": ["página faltando", ""]})
    pts = vg.pontos_de_atencao(_areas(), fontes)
    niveis = [p["nivel"] for p in pts]
    assert niveis == sorted(niveis, key={"alta": 0, "media": 1, "baixa": 2}.get)
    areas = [p["area"] for p in pts]
    assert "Contratos" in areas and "Dados" in areas and "SLA de insumos" not in areas
    assert sum(1 for p in pts if p["area"] == "Dados") == 1   # só a fonte que não está ok
    assert all(p["rota"] for p in pts)


def test_panorama_sem_areas():
    assert vg.panorama({"sla": Area("sla", "SLA", "/sla-insumos", ok=False)}, "segmento").empty
