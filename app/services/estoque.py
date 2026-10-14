"""
Estoque de obras — regras de negócio (pandas puro, testável).

Fonte: suprimentos.fato_estoque_posicao (centro de custo × insumo × detalhe × marca), carregada pela
DAG etl_suprimentos_rpa a partir do relatório paginado do Sienge.

* Valor em estoque = Σ valor_estoque (custo médio × quantidade apropriada), igual ao total do relatório.
* Quantidade NÃO é somada entre insumos diferentes (kg + m + un não faz sentido): a tela mostra
  quantidades só dentro de um mesmo insumo/unidade.
* "Insumos com saldo" = códigos de insumo distintos com quantidade > 0.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["grupo_rotulo"] = np.where(d["cod_grupo_insumo"].notna(),
                                 d["cod_grupo_insumo"].fillna("") + " - " + d["grupo_insumo"].fillna(""),
                                 d["grupo_insumo"].fillna("SEM GRUPO"))
    d["centro_rotulo"] = d["cod_centro_custo"].astype(str) + " - " + d["centro_custo"].fillna("")
    d["analista"] = d["analista"].fillna("(sem analista)")
    d["sem_obra"] = d["cod_obra"].isna()
    return d


def filtrar(df: pd.DataFrame, centros=None, segmentos=None, grupos=None, analistas=None, situacao=None,
            texto: str | None = None, so_saldo: bool = True) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    if centros:
        m &= df["cod_centro_custo"].isin(centros)
    if segmentos:
        m &= df["segmento"].isin(segmentos)
    if grupos:
        m &= df["grupo_rotulo"].isin(grupos)
    if analistas:
        m &= df["analista"].isin(analistas)
    if situacao:
        m &= df["situacao"].isin(situacao)
    if texto:
        t = str(texto).strip().lower()
        alvo = (df["cod_insumo"].astype(str) + " " + df["descricao_completa"].fillna("")).str.lower()
        for termo in t.split():
            m &= alvo.str.contains(termo, regex=False)
    if so_saldo:
        m &= df["com_saldo"]
    return df[m]


def resumo(d: pd.DataFrame, todos: pd.DataFrame) -> dict:
    s = d[d["com_saldo"]]
    valor = float(s["valor_estoque"].sum())
    top = s.sort_values("valor_estoque", ascending=False)
    n20 = max(1, int(np.ceil(len(top) * 0.2)))
    return {
        "valor": valor, "insumos": int(s["cod_insumo"].nunique()), "posicoes": int(len(s)),
        "centros": int(s["cod_centro_custo"].nunique()),
        "abaixo_minimo": int(d["abaixo_minimo"].sum()), "acima_maximo": int(d["acima_maximo"].sum()),
        "inativos": int((todos["situacao"] != "ATIVO").sum()),
        "inativos_com_saldo": int(((todos["situacao"] != "ATIVO") & todos["com_saldo"]).sum()),
        "valor_sem_obra": float(s.loc[s["sem_obra"], "valor_estoque"].sum()),
        "pct_top20": float(top["valor_estoque"].head(n20).sum() / valor * 100) if valor else np.nan,
        "top10_valor": float(top["valor_estoque"].head(10).sum()),
    }


def por(d: pd.DataFrame, coluna: str) -> pd.DataFrame:
    s = d[d["com_saldo"]]
    if s.empty:
        return pd.DataFrame(columns=[coluna, "valor", "posicoes", "insumos", "centros", "pct"])
    g = s.groupby(coluna, dropna=False).agg(valor=("valor_estoque", "sum"), posicoes=("id_posicao", "size"),
                                            insumos=("cod_insumo", "nunique"), centros=("cod_centro_custo", "nunique"))
    g["pct"] = g["valor"] / g["valor"].sum() * 100
    return g.sort_values("valor", ascending=False).reset_index()


def itens(d: pd.DataFrame) -> pd.DataFrame:
    """Posições com saldo, maiores valores primeiro (grade e decomposições)."""
    s = d[d["com_saldo"]].sort_values("valor_estoque", ascending=False).copy()
    s["pct_valor"] = s["valor_estoque"] / s["valor_estoque"].sum() * 100 if len(s) else 0
    s["pct_acumulado"] = s["pct_valor"].cumsum()
    return s


def mesmo_insumo_em_varios_centros(d: pd.DataFrame, minimo: int = 3) -> pd.DataFrame:
    """Insumo/detalhe com saldo em vários centros — candidato a remanejamento entre obras."""
    s = d[d["com_saldo"] & d["cod_obra"].notna()]
    g = s.groupby(["cod_insumo", "cod_detalhe", "descricao_completa", "unidade"], dropna=False).agg(
        centros=("cod_centro_custo", "nunique"), quantidade=("quantidade", "sum"), valor=("valor_estoque", "sum"))
    return g[g["centros"] >= minimo].sort_values("valor", ascending=False).reset_index()
