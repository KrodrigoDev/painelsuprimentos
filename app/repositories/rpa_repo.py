"""
Leitura das tabelas carregadas a partir dos relatórios do RPA (DAG etl_suprimentos_rpa
do airflow_api_sienge): adiantamentos e curva ABC de apropriações. Só leitura.

As tabelas são pequenas (milhares de linhas): são lidas inteiras e mantidas em
cache por CACHE_MINUTOS; os filtros das telas rodam em pandas.

Escopo de acesso: cada leitura pública aplica o escopo do usuário logado
(segmento, obra, empresa — app/seguranca/escopo.py). Dataset sem a dimensão
restrita só aparece se o perfil liberar "dados sem a dimensão".
"""
from __future__ import annotations


import pandas as pd
from sqlalchemy import func, select

from app.cache import CacheSWR
from app.config import SETTINGS
from app.db import ler_sql
from app.seguranca import escopo as _esc
from app.seguranca import sessao as _sessao
from app.models.dw import (ctl_arquivo_adiantamento, ctl_arquivo_avaliacao, ctl_arquivo_curva_abc,
                           ctl_arquivo_estoque, dim_empresa, fato_adiantamento, fato_avaliacao_fornecedor,
                           fato_curva_abc_insumo, fato_estoque_posicao, fato_pedido_compra_item,
                           ctl_arquivo_contrato, fato_contrato, ctl_arquivo_servico, ctl_arquivo_solicitacao,
                           fato_servico, fato_sla_item)


_CACHE = CacheSWR("rpa", SETTINGS.cache_minutos)


def limpar_cache() -> None:
    _CACHE.limpar()


def _num(df: pd.DataFrame, colunas) -> pd.DataFrame:
    for c in colunas:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df


def _datas(df: pd.DataFrame, colunas) -> pd.DataFrame:
    for c in colunas:
        if c in df:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def _escopo(df: pd.DataFrame, segmento=None, obra=None, empresa=None) -> pd.DataFrame:
    return _esc.filtrar(df, _sessao.escopo(), segmento=segmento, obra=obra, empresa=empresa)


# ── Adiantamentos ────────────────────────────────────────────────────────────
def _carregar_adiantamento() -> pd.DataFrame:
    f, e = fato_adiantamento, dim_empresa
    df = ler_sql(select(f, e.c.empresa).join(e, e.c.cod_empresa == f.c.cod_empresa, isouter=True))
    df = _num(df, ["valor", "efeito_saldo", "saldo_documento"])
    df = _datas(df, ["data_movimento", "data_vencimento", "carregado_em"])
    df["empresa"] = df["empresa"].fillna(df["cod_empresa"].astype(str))
    return df


def adiantamentos(ttl_min: int = SETTINGS.cache_minutos) -> pd.DataFrame:
    return _escopo(_CACHE.obter("adiantamento", _carregar_adiantamento, ttl_min), empresa="cod_empresa")


def controle_adiantamento() -> pd.DataFrame:
    df = _escopo(ler_sql(select(ctl_arquivo_adiantamento)), empresa="cod_empresa")
    return _datas(_num(df, ["total_relatorio", "saldo_calculado", "diferenca"]), ["posicao_em", "carregado_em"])


# ── Curva ABC ────────────────────────────────────────────────────────────────
def _carregar_curva_abc() -> pd.DataFrame:
    df = ler_sql(select(fato_curva_abc_insumo))
    df = _num(df, ["quantidade", "preco_unitario_medio", "preco_total", "pct_participacao", "pct_acumulado"])
    df = _datas(df, ["posicao_em", "carregado_em"])
    df["ano"] = df["ano"].astype(int)
    return df


def curva_abc_bruta(ttl_min: int = SETTINGS.cache_minutos) -> pd.DataFrame:
    """SEM escopo — só para preparar/cachear; aplique `escopar_curva_abc` antes de mostrar."""
    return _CACHE.obter("curva_abc", _carregar_curva_abc, ttl_min)


def escopar_curva_abc(df: pd.DataFrame) -> pd.DataFrame:
    return _escopo(df)   # sem obra/empresa/segmento: só com "dados sem a dimensão" liberado


def curva_abc(ttl_min: int = SETTINGS.cache_minutos) -> pd.DataFrame:
    return escopar_curva_abc(curva_abc_bruta(ttl_min))


def controle_curva_abc() -> pd.DataFrame:
    df = ler_sql(select(ctl_arquivo_curva_abc))
    return _datas(_num(df, ["total_relatorio", "total_calculado", "diferenca"]), ["posicao_em", "carregado_em"])


# ── Avaliação de fornecedores ────────────────────────────────────────────────
def _carregar_avaliacoes() -> pd.DataFrame:
    df = ler_sql(select(fato_avaliacao_fornecedor))
    df = _num(df, ["avaliacao_periodo", "avaliacao_atual"])
    df = _datas(df, ["mes_referencia", "posicao_em", "carregado_em"])
    df["numero_avaliacoes"] = df["numero_avaliacoes"].astype(int)
    return df


def avaliacoes(ttl_min: int = SETTINGS.cache_minutos) -> pd.DataFrame:
    return _escopo(_CACHE.obter("avaliacoes", _carregar_avaliacoes, ttl_min))


def controle_avaliacao() -> pd.DataFrame:
    df = ler_sql(select(ctl_arquivo_avaliacao))
    return _datas(_num(df, ["total_relatorio", "total_calculado", "media_relatorio", "media_calculada"]),
                  ["posicao_em", "carregado_em", "periodo_inicio"])


def _carregar_compras_fornecedor() -> pd.DataFrame:
    f = fato_pedido_compra_item
    stmt = (select(f.c.cod_fornecedor, func.sum(f.c.valor_total_item).label("valor_comprado"),
                   func.count().label("itens_comprados"), func.count(func.distinct(f.c.cod_pedido)).label("pedidos"),
                   func.max(f.c.data_pedido).label("ultima_compra"))
            .where(f.c.flag_cancelado.isnot(True)).group_by(f.c.cod_fornecedor))
    df = ler_sql(stmt)
    df = _num(df, ["valor_comprado"])
    return _datas(df, ["ultima_compra"])


def compras_por_fornecedor(ttl_min: int = SETTINGS.cache_minutos) -> pd.DataFrame:
    """Valor comprado por fornecedor nos pedidos da API (vazio se a fato de pedidos não existir)."""
    try:
        return _escopo(_CACHE.obter("compras_fornecedor", _carregar_compras_fornecedor, ttl_min))
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=["cod_fornecedor", "valor_comprado", "itens_comprados", "pedidos", "ultima_compra"])


# ── Estoque ──────────────────────────────────────────────────────────────────
def _carregar_estoque() -> pd.DataFrame:
    df = ler_sql(select(fato_estoque_posicao))
    df = _num(df, ["quantidade", "custo_medio", "valor_estoque", "quantidade_apropriada", "quantidade_reservada",
                   "estoque_minimo", "estoque_maximo"])
    return _datas(df, ["carregado_em"])


def estoque_bruto(ttl_min: int = SETTINGS.cache_minutos) -> pd.DataFrame:
    """SEM escopo — só para preparar/cachear; aplique `escopar_estoque` antes de mostrar."""
    return _CACHE.obter("estoque", _carregar_estoque, ttl_min)


def escopar_estoque(df: pd.DataFrame) -> pd.DataFrame:
    return _escopo(df, segmento="segmento", obra="cod_centro_custo", empresa="cod_empresa")


def estoque(ttl_min: int = SETTINGS.cache_minutos) -> pd.DataFrame:
    return escopar_estoque(estoque_bruto(ttl_min))


def controle_estoque() -> pd.DataFrame:
    df = ler_sql(select(ctl_arquivo_estoque))
    return _datas(_num(df, ["total_pagina", "soma_linhas", "diferenca"]), ["modificado_em", "carregado_em"])


# ── Contratos ────────────────────────────────────────────────────────────────
def _carregar_contratos() -> pd.DataFrame:
    df = ler_sql(select(fato_contrato))
    df = _num(df, ["valor_total", "valor_medido", "saldo", "total_mao_obra", "total_material", "total_em_aberto",
                   "total_sinal", "total_fat_direto", "total_fat_direto_vinculado", "pct_medido"])
    df = _datas(df, ["data_contrato", "data_inicio", "data_termino", "data_alteracao_situacao", "posicao_em",
                     "carregado_em"])
    for c in ("em_andamento", "vencido_com_saldo", "vence_em_breve"):
        df[c] = df[c].astype(bool)
    return df


def contratos(ttl_min: int = SETTINGS.cache_minutos) -> pd.DataFrame:
    return _escopo(_CACHE.obter("contratos", _carregar_contratos, ttl_min), segmento="segmento", obra="cod_obra",
                   empresa="cod_empresa")


def controle_contrato() -> pd.DataFrame:
    df = ler_sql(select(ctl_arquivo_contrato))
    return _datas(_num(df, ["total_relatorio", "soma_linhas", "medido_relatorio", "soma_medido", "diferenca"]),
                  ["modificado_em", "carregado_em"])


# ── SLA de insumos ───────────────────────────────────────────────────────────
_DATAS_SLA = ["data_solicitacao", "data_aut_solicitacao", "data_necessidade", "data_primeiro_pedido", "data_pedido",
              "data_aut_pedido", "previsao_entrega", "data_primeira_nf", "data_primeira_entrega",
              "data_ultima_entrega", "posicao_em", "carregado_em"]
_DIAS_SLA = ["dias_aprovacao_solicitacao", "dias_fase1", "dias_autorizacao_pedido", "dias_fase2",
             "dias_ate_primeira_entrega", "dias_fornecedor", "dias_total", "atraso_fornecedor", "atraso_obra",
             "idade_fase1", "idade_fase2"]


def _carregar_sla() -> pd.DataFrame:
    df = ler_sql(select(fato_sla_item))
    df = _num(df, ["qtd_solicitada", "qtd_entregue", "valor_notas"] + _DIAS_SLA)
    df = _datas(df, _DATAS_SLA)
    for c in ("linha_do_item", "entrega_completa"):
        df[c] = df[c].astype(bool)
    return df


def sla_bruto(ttl_min: int = SETTINGS.cache_minutos) -> pd.DataFrame:
    """SEM escopo — só para preparar/cachear; aplique `escopar_sla` antes de mostrar."""
    return _CACHE.obter("sla", _carregar_sla, ttl_min)


def _carregar_solicitacoes_pedido() -> pd.DataFrame:
    q = (select(fato_sla_item.c.cod_pedido, fato_sla_item.c.cod_insumo, fato_sla_item.c.cod_solicitacao)
         .where(fato_sla_item.c.cod_pedido.is_not(None)).distinct())
    df = ler_sql(q)
    if df.empty:
        return pd.DataFrame(columns=["cod_pedido", "cod_insumo", "solicitacoes"]).set_index(["cod_pedido", "cod_insumo"])
    df = df.astype({"cod_pedido": "int64", "cod_insumo": "int64", "cod_solicitacao": "int64"})
    # consulta já é DISTINCT. Quase todo pedido × insumo tem 1 solicitação: só os poucos com 2+ passam
    # pelo groupby (agrupar 55 mil grupos em Python levava ~2 s)
    df = df.sort_values(["cod_pedido", "cod_insumo", "cod_solicitacao"]).assign(
        solicitacoes=lambda x: x["cod_solicitacao"].astype(str))
    chave = ["cod_pedido", "cod_insumo"]
    multi = df.duplicated(chave, keep=False)
    unicos = df.loc[~multi].set_index(chave)["solicitacoes"]
    varios = df.loc[multi].groupby(chave, sort=False)["solicitacoes"].agg(", ".join)
    return pd.concat([unicos, varios]).rename("solicitacoes").to_frame()


def solicitacoes_por_pedido(ttl_min: int = SETTINGS.cache_minutos) -> pd.DataFrame:
    """(cod_pedido, cod_insumo) -> solicitação(ões) que o pedido atendeu, pelo painel de compras do RPA.

    O item do pedido no Sienge (API) não traz a solicitação; o vínculo vem de fato_sla_item. Um pedido
    pode atender mais de uma solicitação do mesmo insumo (lista "123, 456"). Sem escopo: só é usado para
    completar linhas que o usuário já pode ver."""
    try:
        return _CACHE.obter("solicitacoes_pedido", _carregar_solicitacoes_pedido, ttl_min)
    except Exception:  # noqa: BLE001 — tabela do SLA ainda não carregada: segue sem a solicitação
        return _carregar_vazio_solicitacoes()


def _carregar_vazio_solicitacoes() -> pd.DataFrame:
    return pd.DataFrame(columns=["cod_pedido", "cod_insumo", "solicitacoes"]).set_index(["cod_pedido", "cod_insumo"])


def escopar_sla(df: pd.DataFrame) -> pd.DataFrame:
    return _escopo(df, segmento="segmento", obra="cod_obra")   # o painel de compras não traz empresa


def controle_solicitacao() -> pd.DataFrame:
    return _datas(ler_sql(select(ctl_arquivo_solicitacao)), ["modificado_em", "carregado_em"])


# ── Solicitações de serviço ──────────────────────────────────────────────────
def _carregar_servicos() -> pd.DataFrame:
    df = ler_sql(select(fato_servico))
    df = _num(df, ["dias_previstos", "dias_cadastro_alteracao", "idade_dias", "aguardando_dias"])
    df = _datas(df, ["data_cadastro", "data_solicitacao", "data_alteracao", "data_inicio", "data_termino",
                     "posicao_em", "carregado_em"])
    for c in ("em_aberto", "termino_vencido"):
        df[c] = df[c].astype(bool)
    return df


def servicos(ttl_min: int = SETTINGS.cache_minutos) -> pd.DataFrame:
    return _escopo(_CACHE.obter("servicos", _carregar_servicos, ttl_min), segmento="segmento", obra="cod_obra",
                   empresa="cod_empresa")


def controle_servico() -> pd.DataFrame:
    return _datas(ler_sql(select(ctl_arquivo_servico)), ["modificado_em", "carregado_em"])
