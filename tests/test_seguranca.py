"""Escopo de dados e guarda de telas (sem banco)."""
import pandas as pd

from app.seguranca.catalogo import ACOES, TELA_POR_PREFIXO, TELAS
from app.seguranca.escopo import Escopo, cobre_dataset, filtrar


DF = pd.DataFrame({"segmento": ["MCMV", "PÚBLICA", "MCMV"], "cod_obra": ["15", "224", 16.0], "cod_empresa": [1, 2, 1]})


def test_usuario_substitui_perfil_por_dimensao():
    e = Escopo.de_json({"segmentos": ["MCMV"], "empresas": [1], "dados_sem_dimensao": True},
                       {"obras": ["15"], "empresas": ["2"]})
    assert e.segmentos == {"MCMV"} and e.obras == {"15"} and e.empresas == {"2"} and e.dados_sem_dimensao


def test_filtra_por_todas_as_dimensoes_com_normalizacao():
    e = Escopo.de_json({"segmentos": ["publica"]})
    assert filtrar(DF, e, segmento="segmento")["cod_obra"].tolist() == ["224"]      # sem acento / caixa
    e = Escopo.de_json({"obras": [16]})
    assert len(filtrar(DF, e, obra="cod_obra")) == 1                                # 16.0 == "16"


def test_dataset_sem_a_dimensao_so_com_permissao():
    restrito = Escopo.de_json({"obras": ["15"], "dados_sem_dimensao": False})
    assert filtrar(DF, restrito, segmento="segmento").empty                         # não tem obra -> nada
    assert not cobre_dataset(restrito, segmento=True)
    liberado = Escopo.de_json({"obras": ["15"], "dados_sem_dimensao": True})
    assert len(filtrar(DF, liberado, segmento="segmento")) == 3
    assert cobre_dataset(liberado)


def test_sem_restricao_devolve_o_mesmo_objeto():
    assert filtrar(DF, Escopo(), segmento="segmento") is DF


def test_prefixos_de_tela_unicos_e_acoes_registradas():
    assert len(TELA_POR_PREFIXO) == len(TELAS)
    assert {"exportar", "gerar_relatorio", "administrar_usuarios"} <= set(ACOES)


def test_ids_de_callback_mapeiam_para_a_tela(monkeypatch):
    from app.seguranca import web
    assert web.tela_do_id("op-kpis") == "oportunidades"
    assert web.tela_do_id("adm-u-grade") == "admin"
    assert web.tela_do_id("sidebar-meta") is None and web.tela_do_id("nav") is None
