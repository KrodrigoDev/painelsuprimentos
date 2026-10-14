"""Estoque (regras) e gerador de PowerPoint (smoke test, sem banco)."""
import io

import pandas as pd
import pytest

from app.services import estoque as es


def pos(i, centro, insumo, q, v, situacao="ATIVO", minimo=0, obra=1):
    return dict(id_posicao=i, cod_centro_custo=centro, centro_custo=f"C{centro}", cod_obra=obra, segmento="MCMV",
                cod_grupo_insumo="02.034", grupo_insumo="FERRAGENS", analista=None, cod_insumo=insumo, cod_detalhe=0,
                descricao_completa=f"{insumo} - X", situacao=situacao, unidade="kg", quantidade=q, custo_medio=v / q if q else 0,
                valor_estoque=v, estoque_minimo=minimo, estoque_maximo=0, com_saldo=q > 0,
                abaixo_minimo=minimo > 0 and q < minimo, acima_maximo=False)


BASE = es.preparar(pd.DataFrame([pos(1, 10, 100, 5, 50), pos(2, 11, 100, 3, 30, minimo=10), pos(3, 12, 200, 0, 0, "INATIVO"),
                                 pos(4, 10, 300, 1, 920, obra=None)]))


def test_resumo_nao_soma_insumos_diferentes_e_conta_saldo():
    r = es.resumo(BASE, BASE)
    assert r["valor"] == 1000 and r["insumos"] == 2 and r["posicoes"] == 3
    assert r["abaixo_minimo"] == 1 and r["inativos"] == 1 and r["valor_sem_obra"] == 920


def test_filtros_e_remanejamento():
    assert len(es.filtrar(BASE, texto="300")) == 1
    assert es.filtrar(BASE, so_saldo=False).shape[0] == 4
    rem = es.mesmo_insumo_em_varios_centros(BASE, minimo=2)
    assert rem["cod_insumo"].tolist() == [100] and rem["quantidade"].iat[0] == 8


def test_pptx_abre_e_tem_os_slides():
    pptx = pytest.importorskip("pptx")
    from app.relatorios.apresentacao import Apresentacao
    ap = Apresentacao("Teste", "sub", "fonte")
    ap.capa([("valor", "R$ 1 mi")])
    ap.kpis("KPIs", [("a", "1", "x"), ("b", "2", "y", "alerta")])
    ap.barras("Barras", ["a", "b"], [1.0, 2.0])
    ap.linhas("Linhas", ["jan", "fev"], {"s": [1.0, 2.0]}, eixo=(0, 4))
    ap.tabela("Tabela", pd.DataFrame({"t": ["x" * 200, "y"], "v": [1.0, 2.0]}),
              [{"campo": "t", "rotulo": "Texto", "formato": "texto"}, {"campo": "v", "rotulo": "Valor", "formato": "brl",
                                                                      "total": True}])
    ap.notas("Notas", ["um", "dois"])
    prs = pptx.Presentation(io.BytesIO(ap.salvar()))
    assert len(prs.slides) == 6
