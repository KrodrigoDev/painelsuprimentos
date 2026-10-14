"""
Cálculos da aba Possível Saving (pandas puro, sem acesso a banco).

Conceitos:
  preço médio ponderado = Σ valor / Σ quantidade
  saving vs menor do mês = Σ (preço − menor preço do mesmo mês) × quantidade
      -> referência JUSTA: compara com o melhor preço praticado no mesmo mês
         (evita comparar compra de janeiro com preço de setembro)
  saving vs menor do período = Σ (preço − menor preço do período) × quantidade
      -> teto teórico (ignora variação de preço ao longo do tempo)
  saving vs média = Σ max(preço − média ponderada, 0) × quantidade
      -> quanto foi pago ACIMA da média

Todos os cálculos assumem UMA unidade de medida — o painel filtra por
unidade antes de chamar (comparar R$/kg com R$/saco não faz sentido).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Resumo:
    total_gasto: float = 0.0
    quantidade: float = 0.0
    preco_medio_pond: float = 0.0
    menor_preco: float = 0.0
    maior_preco: float = 0.0
    n_fornecedores: int = 0
    n_obras: int = 0
    n_pedidos: int = 0
    n_itens: int = 0
    saving_menor_mes: float = 0.0
    saving_menor_periodo: float = 0.0
    saving_acima_media: float = 0.0
    fornecedor_menor_preco: str = ""
    obra_menor_preco: str = ""


def enriquecer(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona referências de preço e saving por linha."""
    if df.empty:
        return df
    df = df.copy()
    media = df["valor_total"].sum() / df["quantidade"].sum()
    df["menor_preco_mes"] = df.groupby("ano_mes")["preco"].transform("min")
    df["menor_preco_obra"] = df.groupby("cod_obra")["preco"].transform("min")
    df["menor_preco_fornecedor"] = df.groupby("cod_fornecedor")["preco"].transform("min")
    df["dif_vs_menor_mes_pct"] = (df["preco"] / df["menor_preco_mes"] - 1) * 100
    df["saving_menor_mes"] = (df["preco"] - df["menor_preco_mes"]) * df["quantidade"]
    df["saving_menor_periodo"] = (df["preco"] - df["preco"].min()) * df["quantidade"]
    df["saving_acima_media"] = np.maximum(df["preco"] - media, 0) * df["quantidade"]
    return df


def resumo(df: pd.DataFrame) -> Resumo:
    if df.empty:
        return Resumo()
    qtd = df["quantidade"].sum()
    total = df["valor_total"].sum()
    i_min = df["preco"].idxmin()
    return Resumo(
        total_gasto=float(total),
        quantidade=float(qtd),
        preco_medio_pond=float(total / qtd) if qtd else 0.0,
        menor_preco=float(df["preco"].min()),
        maior_preco=float(df["preco"].max()),
        n_fornecedores=int(df["cod_fornecedor"].nunique()),
        n_obras=int(df["cod_obra"].nunique()),
        n_pedidos=int(df["cod_pedido"].nunique()),
        n_itens=int(len(df)),
        saving_menor_mes=float(df["saving_menor_mes"].sum()),
        saving_menor_periodo=float(df["saving_menor_periodo"].sum()),
        saving_acima_media=float(df["saving_acima_media"].sum()),
        fornecedor_menor_preco=str(df.at[i_min, "fornecedor"]),
        obra_menor_preco=str(df.at[i_min, "obra"]),
    )


def _agrupar(df: pd.DataFrame, chave: list[str]) -> pd.DataFrame:
    """Métricas de preço por grupo + quem praticou o menor preço."""
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(chave, dropna=False)
    out = g.agg(
        pedidos=("cod_pedido", "nunique"),
        quantidade=("quantidade", "sum"),
        total_gasto=("valor_total", "sum"),
        menor_preco=("preco", "min"),
        maior_preco=("preco", "max"),
        saving_menor_mes=("saving_menor_mes", "sum"),
    ).reset_index()
    out["preco_medio_pond"] = out["total_gasto"] / out["quantidade"]
    idx_min = g["preco"].idxmin()
    extras = [c for c in ("fornecedor", "obra", "data_pedido") if c not in chave]
    melhor = df.loc[idx_min.values, chave + extras]
    melhor = melhor.rename(columns={c: f"{c}_menor_preco" if c != "data_pedido" else "data_menor_preco"
                                    for c in extras})
    out = out.merge(melhor, on=chave, how="left")
    return out


def por_obra(df: pd.DataFrame) -> pd.DataFrame:
    out = _agrupar(df, ["cod_obra", "obra"])
    if out.empty:
        return out
    out["fornecedores"] = out["cod_obra"].map(df.groupby("cod_obra")["cod_fornecedor"].nunique())
    return out.sort_values("total_gasto", ascending=False)


def por_fornecedor(df: pd.DataFrame) -> pd.DataFrame:
    out = _agrupar(df, ["cod_fornecedor", "fornecedor"])
    if out.empty:
        return out
    out["obras"] = out["cod_fornecedor"].map(df.groupby("cod_fornecedor")["cod_obra"].nunique())
    return out.sort_values("preco_medio_pond")


def por_mes(df: pd.DataFrame) -> pd.DataFrame:
    out = _agrupar(df, ["ano_mes"])
    return out.sort_values("ano_mes") if not out.empty else out


def por_insumo(df: pd.DataFrame) -> pd.DataFrame:
    out = _agrupar(df, ["id_insumo", "cod_insumo", "descricao_completa"])
    return out.sort_values("total_gasto", ascending=False) if not out.empty else out
