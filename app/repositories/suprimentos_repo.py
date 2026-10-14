"""Consultas ao DW (schema suprimentos / suprimentos_mock) — só leitura."""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import and_, func, select

from app.db import ler_sql
from app.models.dw import (dim_centro_custo, dim_fornecedor, dim_insumo, dim_pedido, dim_status_pedido,
                           fato_pedido_compra_item as fato)
from app.seguranca import escopo as _esc
from app.seguranca import sessao as _sessao


def insumos_com_compra() -> pd.DataFrame:
    """Insumos que têm ao menos 1 item com preço válido (base do índice de similaridade)."""
    agg = (
        select(fato.c.id_insumo,
               func.count().label("n_itens"),
               func.sum(fato.c.valor_liquido_item).label("total_gasto"))
        .where(fato.c.flag_preco_valido.is_(True))
        .group_by(fato.c.id_insumo)
        .subquery()
    )
    stmt = (
        select(dim_insumo.c.id_insumo, dim_insumo.c.cod_insumo, dim_insumo.c.cod_detalhe,
               dim_insumo.c.descricao_completa, dim_insumo.c.descricao_normalizada,
               dim_insumo.c.categoria, dim_insumo.c.unidade_padrao, dim_insumo.c.tipo_insumo,
               agg.c.n_itens, agg.c.total_gasto)
        .join(agg, agg.c.id_insumo == dim_insumo.c.id_insumo)
    )
    df = ler_sql(stmt)
    df["total_gasto"] = df["total_gasto"].astype(float)
    return df


def periodo_disponivel() -> tuple[date | None, date | None]:
    df = ler_sql(select(func.min(fato.c.data_pedido).label("ini"), func.max(fato.c.data_pedido).label("fim")))
    return (df.at[0, "ini"], df.at[0, "fim"]) if len(df) else (None, None)


def itens_dos_insumos(
        ids_insumo: list[int],
        data_ini: date | None = None,
        data_fim: date | None = None,
        cod_obras: list[str] | None = None,
        incluir_cancelados: bool = False,
) -> pd.DataFrame:
    """Linhas da fato (com descrições) dos insumos escolhidos, já filtradas."""
    if not ids_insumo:
        return pd.DataFrame()
    filtros = [fato.c.id_insumo.in_(ids_insumo), fato.c.preco_liquido > 0, fato.c.quantidade > 0]
    if not incluir_cancelados:
        filtros.append(fato.c.flag_cancelado.is_not(True))
    if data_ini:
        filtros.append(fato.c.data_pedido >= data_ini)
    if data_fim:
        filtros.append(fato.c.data_pedido <= data_fim)
    if cod_obras:
        filtros.append(fato.c.cod_obra.in_(cod_obras))

    stmt = (
        select(
            fato.c.data_pedido, fato.c.ano_mes, fato.c.cod_pedido, fato.c.numero_item, fato.c.cod_cotacao,
            fato.c.id_insumo, dim_insumo.c.cod_insumo, dim_insumo.c.descricao_completa, dim_insumo.c.categoria,
            func.coalesce(dim_insumo.c.unidade_padrao, fato.c.unidade).label("unidade"),
            fato.c.cod_fornecedor,
            func.coalesce(dim_fornecedor.c.nome_fornecedor, func.concat("FORNECEDOR ", fato.c.cod_fornecedor)).label("fornecedor"),
            fato.c.cod_obra,
            func.coalesce(dim_centro_custo.c.centro_de_custo_1, func.concat("CC ", fato.c.cod_obra)).label("obra"),
            dim_status_pedido.c.descricao.label("status"),
            fato.c.quantidade, fato.c.preco_liquido.label("preco"), fato.c.frete_unitario,
            fato.c.valor_liquido_item.label("valor_total"),
            func.coalesce(dim_centro_custo.c.vertical, "SEM SEGMENTO").label("segmento"),
            dim_pedido.c.cod_empresa_titulo.label("cod_empresa"),
        )
        .select_from(fato)
        .join(dim_insumo, dim_insumo.c.id_insumo == fato.c.id_insumo)
        .join(dim_status_pedido, dim_status_pedido.c.id_status == fato.c.id_status)
        .outerjoin(dim_fornecedor, dim_fornecedor.c.id_fornecedor == fato.c.id_fornecedor)
        .outerjoin(dim_centro_custo, dim_centro_custo.c.cod_obra == fato.c.cod_obra)
        .outerjoin(dim_pedido, dim_pedido.c.cod_pedido == fato.c.cod_pedido)
        .where(and_(*filtros))
        .order_by(fato.c.data_pedido.desc(), fato.c.cod_pedido, fato.c.numero_item)
    )
    df = ler_sql(stmt)
    for c in ("quantidade", "preco", "frete_unitario", "valor_total"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["data_pedido"] = pd.to_datetime(df["data_pedido"])
    return _esc.filtrar(df, _sessao.escopo(), segmento="segmento", obra="cod_obra", empresa="cod_empresa")


def obras() -> pd.DataFrame:
    stmt = (
        select(dim_centro_custo.c.cod_obra, dim_centro_custo.c.centro_de_custo_1.label("obra"),
               func.coalesce(dim_centro_custo.c.vertical, "SEM SEGMENTO").label("segmento"))
        .where(dim_centro_custo.c.cod_obra.in_(select(fato.c.cod_obra).distinct()))
        .order_by(dim_centro_custo.c.centro_de_custo_1)
    )
    esc = _sessao.escopo()
    return _esc.filtrar(ler_sql(stmt), esc if esc.empresas is None else
                        _esc.Escopo(esc.segmentos, esc.obras, None, esc.dados_sem_dimensao),
                        segmento="segmento", obra="cod_obra")
