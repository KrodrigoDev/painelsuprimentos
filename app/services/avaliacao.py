"""
Avaliação de fornecedores — regras de negócio (pandas puro, testável).

Fonte: suprimentos.fato_avaliacao_fornecedor (fornecedor × mês, relatório "Avaliações
de Fornecedor" do Sienge, conferido com total e média de cada mês).

Escala 0 a 4. Classificação (nota arredondada a 1 casa):
    A (crítico) até 2,0 · B de 2,1 a 3,4 · C de 3,5 a 4,0

A nota usada para classificar o fornecedor no período filtrado é escolhida na tela:
    pior    pior mês do período: teve algum mês na faixa A -> crítico (padrão; critério do Power BI)
    media   média ponderada pelo nº de avaliações no período
    ultima  avaliação do último mês avaliado no período
    atual   nota acumulada do Sienge (último relatório do período)

Médias agregadas são PONDERADAS pelo número de avaliações (um fornecedor com
40 avaliações pesa mais que um com 1). O Power BI usava média simples das médias.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

A_ATE, C_DESDE = 2.0, 3.5
BASES = {
    "pior": "Pior mês no período (critério atual)",
    "media": "Média ponderada no período",
    "ultima": "Última avaliação no período",
    "atual": "Nota atual do Sienge",
}
BASE_PADRAO = "pior"
ROTULO_CLASSE = {"A": "A · até 2,0 (crítico)", "B": "B · 2,1 a 3,4", "C": "C · 3,5 a 4,0"}


def classificar(nota) -> pd.Series:
    n = pd.to_numeric(pd.Series(nota), errors="coerce")
    n = np.floor(n * 10 + 0.5 + 1e-9) / 10   # arredonda 1 casa "para cima" no meio (2,05 -> 2,1), como o Sienge
    return pd.Series(np.where(n <= A_ATE, "A", np.where(n >= C_DESDE, "C", "B")), index=n.index).where(n.notna())


def filtrar(df: pd.DataFrame, ini=None, fim=None, fornecedores=None) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    if ini:
        m &= df["mes_referencia"] >= pd.Timestamp(ini).to_period("M").to_timestamp()
    if fim:
        m &= df["mes_referencia"] <= pd.Timestamp(fim).to_period("M").to_timestamp()
    if fornecedores:
        m &= df["cod_fornecedor"].isin(fornecedores)
    return df[m & (df["numero_avaliacoes"] > 0)]


def _media_pond(d: pd.DataFrame) -> float:
    n = d["numero_avaliacoes"].sum()
    return float((d["numero_avaliacoes"] * d["avaliacao_periodo"]).sum() / n) if n else np.nan


def por_fornecedor(d: pd.DataFrame, base: str = BASE_PADRAO, compras: pd.DataFrame | None = None) -> pd.DataFrame:
    """1 linha por fornecedor no período, com a nota-base e a classe."""
    if d.empty:
        return pd.DataFrame(columns=["cod_fornecedor", "fornecedor", "avaliacoes", "nota_media", "nota_ultima",
                                     "nota_pior", "nota_atual", "nota", "classe", "meses", "meses_criticos"])
    d = d.sort_values("mes_referencia").assign(_p=d["numero_avaliacoes"] * d["avaliacao_periodo"])
    d["_critico"] = (classificar(d["avaliacao_periodo"]).values == "A").astype(int)   # 1 vez, vetorizado
    g = d.groupby("cod_fornecedor")
    out = pd.DataFrame({
        "fornecedor": g["fornecedor"].last(),
        "avaliacoes": g["numero_avaliacoes"].sum(),
        "nota_media": g["_p"].sum() / g["numero_avaliacoes"].sum(),
        "nota_ultima": g["avaliacao_periodo"].last(),
        "mes_ultima": g["mes_referencia"].last(),
        "nota_pior": g["avaliacao_periodo"].min(),
        "nota_atual": g["avaliacao_atual"].last(),
        "meses": g["mes_referencia"].nunique(),
        "meses_criticos": g["_critico"].sum().astype(int),
    })
    out["nota"] = out[{"media": "nota_media", "ultima": "nota_ultima", "pior": "nota_pior",
                       "atual": "nota_atual"}.get(base, "nota_pior")]
    out["classe"] = classificar(out["nota"]).values
    # tendência: última nota − média dos meses anteriores do período
    ant = d[d["mes_referencia"] < d["cod_fornecedor"].map(out["mes_ultima"])]
    if len(ant):
        ga = ant.groupby("cod_fornecedor")
        out["tendencia"] = out["nota_ultima"] - (ga["_p"].sum() / ga["numero_avaliacoes"].sum())
    else:
        out["tendencia"] = np.nan
    out = out.reset_index()
    if compras is not None and len(compras):
        out = out.merge(compras, on="cod_fornecedor", how="left")
    for c in ("valor_comprado", "itens_comprados", "pedidos"):
        if c not in out:
            out[c] = np.nan
    out["rotulo"] = out["cod_fornecedor"].astype(str) + " - " + out["fornecedor"].fillna("")
    return out.sort_values(["nota", "avaliacoes"], ascending=[True, False]).reset_index(drop=True)


def resumo(d: pd.DataFrame, forn: pd.DataFrame) -> dict:
    n_forn = len(forn)
    cont = forn["classe"].value_counts()
    crit = forn[forn["classe"] == "A"]
    return {
        "fornecedores": n_forn, "avaliacoes": int(d["numero_avaliacoes"].sum()),
        "media": _media_pond(d), "mediana": float(forn["nota_media"].median()) if n_forn else np.nan,
        "a": int(cont.get("A", 0)), "b": int(cont.get("B", 0)), "c": int(cont.get("C", 0)),
        "pct_a": float(cont.get("A", 0) / n_forn * 100) if n_forn else np.nan,
        "valor_criticos": float(crit["valor_comprado"].fillna(0).sum()),
        "criticos_com_compra": int((crit["valor_comprado"].fillna(0) > 0).sum()),
    }


def mensal(d: pd.DataFrame) -> pd.DataFrame:
    if d.empty:
        return pd.DataFrame(columns=["ano_mes", "avaliacoes", "media", "fornecedores", "criticos"])
    d = d.assign(_p=d["numero_avaliacoes"] * d["avaliacao_periodo"],
                 _crit=classificar(d["avaliacao_periodo"]).values == "A")
    g = d.groupby("ano_mes").agg(avaliacoes=("numero_avaliacoes", "sum"), _p=("_p", "sum"),
                                 fornecedores=("cod_fornecedor", "nunique"), criticos=("_crit", "sum"))
    g["media"] = g["_p"] / g["avaliacoes"]
    return g.drop(columns="_p").reset_index()


def matriz(base_total: pd.DataFrame, d: pd.DataFrame, fornecedores: list[int]) -> tuple[pd.DataFrame, list[str]]:
    """
    Fornecedor × mês (avaliações, média, delta) para a grade. O delta compara com o mês AVALIADO anterior
    do fornecedor, em todo o histórico (mesmo fora do filtro), como no Power BI.
    """
    meses = sorted(d["ano_mes"].unique())
    h = base_total[base_total["cod_fornecedor"].isin(fornecedores) & (base_total["numero_avaliacoes"] > 0)]
    h = h.sort_values(["cod_fornecedor", "mes_referencia"]).copy()
    h["delta"] = h["avaliacao_periodo"] - h.groupby("cod_fornecedor")["avaliacao_periodo"].shift(1)
    h = h[h["ano_mes"].isin(meses)]
    linhas = []
    for cod, sub in h.groupby("cod_fornecedor"):
        r = {"cod_fornecedor": int(cod)}
        for x in sub.itertuples():
            k = x.ano_mes.replace("-", "_")
            r[f"n_{k}"], r[f"m_{k}"] = int(x.numero_avaliacoes), float(x.avaliacao_periodo)
            r[f"d_{k}"] = None if pd.isna(x.delta) else round(float(x.delta), 2)
        linhas.append(r)
    return pd.DataFrame(linhas), meses


def total_matriz(d: pd.DataFrame, fornecedores: list[int], meses: list[str]) -> dict:
    sub = d[d["cod_fornecedor"].isin(fornecedores)]
    r = {"rotulo": "Total (média ponderada)"}
    for m in meses:
        s = sub[sub["ano_mes"] == m]
        k = m.replace("-", "_")
        r[f"n_{k}"] = int(s["numero_avaliacoes"].sum())
        r[f"m_{k}"] = None if s.empty else round(_media_pond(s), 2)
    return r
