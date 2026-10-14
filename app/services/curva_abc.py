"""
Curva ABC de apropriações — regras de negócio (pandas puro, testável).

Fonte: suprimentos.fato_curva_abc_insumo (relatório "Curva ABC de Apropriações"
do Sienge, 1 por ano, carregado pela DAG etl_suprimentos_rpa e conciliado com
o Total geral).

* Insumo = chave_insumo (cod_tabela|cod_insumo): o código só é único dentro da
  tabela de insumos. Cada insumo pode ter vários DETALHES (linhas).
* Preço unitário médio do ano = Σ preço total / Σ quantidade, só com linhas
  na mesma unidade e sem o "*" do Sienge (quantidade não convertida).
  Quando os detalhes estão em unidades diferentes, usa-se a unidade de maior
  valor e a tela avisa — misturar unidades distorce o preço.
* Classe ABC no recorte: recalculada sobre o que está filtrado (A até 80% do
  valor acumulado, B até 95%, C o resto). A classe "do ano" (carga) considera
  todas as linhas do ano.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

A_ATE, B_ATE = 80.0, 95.0


def rotulo_insumo(df: pd.DataFrame) -> pd.Series:
    return df["cod_insumo"].astype(str) + " - " + df["insumo"].fillna("")


def rotulo_grupo(df: pd.DataFrame) -> pd.Series:
    cod = df["cod_grupo_insumo"].fillna("")
    return np.where(cod != "", cod + " - " + df["grupo_insumo"].fillna(""), df["grupo_insumo"].fillna("SEM GRUPO"))


def filtrar(df: pd.DataFrame, anos=None, tabelas=None, grupos=None, tipos=None) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    if anos:
        m &= df["ano"].isin([int(a) for a in anos])
    if tabelas:
        m &= df["cod_tabela"].isin(tabelas)
    if grupos:
        m &= df["grupo_rotulo"].isin(grupos) if "grupo_rotulo" in df else df["grupo_insumo"].isin(grupos)
    if tipos:
        m &= df["tipo_insumo"].fillna("—").isin(tipos)
    return df[m]


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Colunas de apoio para as telas (uma vez, sobre a base em cache)."""
    d = df.copy()
    d["insumo_rotulo"] = rotulo_insumo(d)
    d["grupo_rotulo"] = rotulo_grupo(d)
    d["detalhe_rotulo"] = d["detalhe"].fillna("(sem detalhe)")
    return d


def classificar(valores: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(participação %, acumulado %, classe) na ordem decrescente de valor."""
    total = valores.sum()
    ordem = valores.sort_values(ascending=False, kind="mergesort")
    part = ordem / total * 100 if total else ordem * 0
    acum = part.cumsum()
    antes = acum - part
    classe = pd.Series(np.where(antes < A_ATE, "A", np.where(antes < B_ATE, "B", "C")), index=ordem.index)
    return part.reindex(valores.index), acum.reindex(valores.index), classe.reindex(valores.index)


def _unidade_principal(linhas: pd.DataFrame) -> str | None:
    if linhas.empty:
        return None
    return linhas.groupby("unidade_padrao")["preco_total"].sum().idxmax()


def preco_medio(linhas: pd.DataFrame, unidade: str | None = None) -> tuple[float, float, str | None]:
    """(preço médio ponderado, quantidade, unidade) — só linhas na unidade e com quantidade convertida."""
    unidade = unidade or _unidade_principal(linhas)
    ok = linhas[(linhas["unidade_padrao"] == unidade) & ~linhas["qtd_nao_convertida"] & (linhas["quantidade"] > 0)]
    q = float(ok["quantidade"].sum())
    return (float(ok["preco_total"].sum()) / q if q else np.nan), q, unidade


def _precos_vetor(linhas: pd.DataFrame, unidade_por_chave: pd.Series | None = None) -> pd.DataFrame:
    """Preço médio ponderado por chave_insumo, na unidade principal (ou na informada)."""
    if unidade_por_chave is None:
        v = linhas.groupby(["chave_insumo", "unidade_padrao"])["preco_total"].sum().reset_index()
        unidade_por_chave = (v.sort_values("preco_total", ascending=False)
                             .drop_duplicates("chave_insumo").set_index("chave_insumo")["unidade_padrao"])
    ok = linhas[(linhas["unidade_padrao"] == linhas["chave_insumo"].map(unidade_por_chave))
                & ~linhas["qtd_nao_convertida"] & (linhas["quantidade"] > 0)]
    g = ok.groupby("chave_insumo")[["preco_total", "quantidade"]].sum()
    out = pd.DataFrame({"unidade": unidade_por_chave})
    out["quantidade"] = g["quantidade"]
    out["preco_medio"] = g["preco_total"] / g["quantidade"]
    return out


RAZAO_EXTREMA = 10.0   # preço 10x maior/menor que no ano anterior = provável erro de unidade/registro


def _linhas_preco(linhas: pd.DataFrame) -> pd.DataFrame:
    ok = linhas[~linhas["qtd_nao_convertida"] & (linhas["quantidade"] > 0) & (linhas["preco_total"] > 0)]
    g = ok.groupby(["chave_insumo", "detalhe_rotulo", "unidade_padrao"], dropna=False)[["preco_total", "quantidade"]].sum()
    g["preco"] = g["preco_total"] / g["quantidade"]
    return g


def variacao_mesmos_detalhes(atual: pd.DataFrame, anterior: pd.DataFrame) -> pd.DataFrame:
    """
    Variação de preço SEM efeito de mix: compara só o mesmo detalhe, na mesma unidade, nos dois anos, e
    pondera pela quantidade do ano atual (índice de Paasche):
        var % = Σ p_atual·q_atual / Σ p_anterior·q_atual − 1
        efeito preço (R$) = Σ (p_atual − p_anterior)·q_atual
    Pares com razão de preço > 10x (ou < 1/10) são descartados como prováveis erros de unidade/registro.
    Retorna por chave_insumo: var_preco_pct, efeito_preco, cobertura_pct (% do valor do ano comparado).
    """
    a, b = _linhas_preco(atual), _linhas_preco(anterior)
    m = a.join(b[["preco"]].rename(columns={"preco": "preco_ant"}), how="inner")
    razao = m["preco"] / m["preco_ant"]
    m = m[(razao <= RAZAO_EXTREMA) & (razao >= 1 / RAZAO_EXTREMA)]
    m = m.assign(v_ant=m["preco_ant"] * m["quantidade"])
    g = m.groupby(level="chave_insumo")[["preco_total", "v_ant"]].sum()
    g["var_preco_pct"] = (g["preco_total"] / g["v_ant"] - 1) * 100
    g["efeito_preco"] = g["preco_total"] - g["v_ant"]
    total = atual.groupby("chave_insumo")["preco_total"].sum()
    g["cobertura_pct"] = g["preco_total"] / total.reindex(g.index) * 100
    return g[["var_preco_pct", "efeito_preco", "cobertura_pct"]]


def ranking(df: pd.DataFrame, ano: int, ano_anterior: int | None = None) -> pd.DataFrame:
    """Insumos do ano, com classe ABC no recorte e variação de preço vs ano anterior."""
    atual = df[df["ano"] == ano]
    if atual.empty:
        return pd.DataFrame()
    g = atual.groupby("chave_insumo").agg(
        insumo=("insumo_rotulo", "first"), grupo=("grupo_rotulo", "first"), tabela=("tabela", "first"),
        valor=("preco_total", "sum"), detalhes=("detalhe_rotulo", "nunique"),
        n_unidades=("unidade_padrao", "nunique"), nao_convertida=("qtd_nao_convertida", "any"))
    g["pct_part"], g["pct_acum"], g["classe"] = classificar(g["valor"])
    precos = _precos_vetor(atual)
    g = g.join(precos)
    for c in ("preco_anterior", "var_preco_pct", "efeito_preco", "cobertura_pct", "valor_anterior"):
        g[c] = np.nan
    if ano_anterior is not None:
        ant = df[(df["ano"] == ano_anterior) & df["chave_insumo"].isin(g.index)]
        if len(ant):
            g["preco_anterior"] = _precos_vetor(ant, g["unidade"])["preco_medio"]
            var = variacao_mesmos_detalhes(atual, ant)
            g[["var_preco_pct", "efeito_preco", "cobertura_pct"]] = var.reindex(g.index)
            g["valor_anterior"] = ant.groupby("chave_insumo")["preco_total"].sum()
    g = g.sort_values("valor", ascending=False)
    g["posicao"] = np.arange(1, len(g) + 1)
    return g.reset_index()


def serie_insumo(df: pd.DataFrame, chave: str, detalhes=None) -> tuple[pd.DataFrame, dict]:
    """Por ano: preço médio, quantidade, valor, % do ano e variação YoY (como a tabela do relatório)."""
    linhas = df[df["chave_insumo"] == chave]
    if detalhes:
        linhas = linhas[linhas["detalhe_rotulo"].isin(detalhes)]
    if linhas.empty:
        return pd.DataFrame(), {}
    unidade = _unidade_principal(linhas)
    unidades = sorted(set(linhas["unidade_padrao"].dropna()))
    total_ano = df.groupby("ano")["preco_total"].sum()
    out = []
    for ano, sub in linhas.groupby("ano"):
        p, q, _ = preco_medio(sub, unidade)
        out.append({"ano": int(ano), "preco_medio": p, "quantidade": q, "unidade": unidade,
                    "valor": float(sub["preco_total"].sum()),
                    "pct_ano": float(sub["preco_total"].sum() / total_ano.get(ano, np.nan) * 100),
                    "fora_da_media": float(sub.loc[(sub["unidade_padrao"] != unidade) | sub["qtd_nao_convertida"],
                                                   "preco_total"].sum())})
    s = pd.DataFrame(out).sort_values("ano").reset_index(drop=True)
    s["var_yoy_pct"] = (s["preco_medio"] / s["preco_medio"].shift(1) - 1) * 100   # como no relatório (com mix)
    s["var_qtd_pct"] = (s["quantidade"] / s["quantidade"].shift(1) - 1) * 100
    s["var_mesmos_pct"] = s["cobertura_pct"] = np.nan
    for i in range(1, len(s)):
        v = variacao_mesmos_detalhes(linhas[linhas["ano"] == s.at[i, "ano"]], linhas[linhas["ano"] == s.at[i - 1, "ano"]])
        if chave in v.index:
            s.at[i, "var_mesmos_pct"] = v.at[chave, "var_preco_pct"]
            s.at[i, "cobertura_pct"] = v.at[chave, "cobertura_pct"]
    # variação "oficial" da tela: mesmos detalhes quando existe; senão a do preço médio
    s["var_tela_pct"] = s["var_mesmos_pct"].fillna(s["var_yoy_pct"])
    validos = s.dropna(subset=["preco_medio"])
    info = {
        "unidade": unidade, "unidades": unidades, "mistura_unidades": len(unidades) > 1,
        "detalhes": int(linhas["detalhe_rotulo"].nunique()),
        "nao_convertida": bool(linhas["qtd_nao_convertida"].any()),
        "insumo": linhas["insumo_rotulo"].iat[0], "grupo": linhas["grupo_rotulo"].iat[0],
        "tabela": linhas["tabela"].iat[0], "origem_grupo": linhas["origem_grupo"].iat[0],
        "preco_atual": float(validos["preco_medio"].iat[-1]) if len(validos) else np.nan,
        "ano_atual": int(validos["ano"].iat[-1]) if len(validos) else None,
        "var_yoy": float(s["var_tela_pct"].iat[-1]) if len(s) > 1 else np.nan,
        "var_yoy_mix": float(s["var_yoy_pct"].iat[-1]) if len(s) > 1 else np.nan,
        "var_mesmos": bool(len(s) > 1 and s["var_mesmos_pct"].notna().iat[-1]),
        "amplitude": float(validos["preco_medio"].max() - validos["preco_medio"].min()) if len(validos) else np.nan,
        "ano_pico": int(validos.loc[validos["preco_medio"].idxmax(), "ano"]) if len(validos) else None,
        "valor_total": float(s["valor"].sum()),
    }
    return s, info


def detalhes_insumo(df: pd.DataFrame, chave: str, ano: int | None = None) -> pd.DataFrame:
    linhas = df[df["chave_insumo"] == chave]
    if ano:
        linhas = linhas[linhas["ano"] == ano]
    g = linhas.groupby(["detalhe_rotulo", "unidade_padrao"], dropna=False).agg(
        quantidade=("quantidade", "sum"), valor=("preco_total", "sum"), anos=("ano", "nunique"),
        nao_convertida=("qtd_nao_convertida", "any"), classe=("classe_abc", "min")).reset_index()
    g["preco_medio"] = np.where(g["quantidade"] > 0, g["valor"] / g["quantidade"], np.nan)
    return g.sort_values("valor", ascending=False)


def por_grupo(df: pd.DataFrame, ano: int) -> pd.DataFrame:
    a = df[df["ano"] == ano]
    g = a.groupby("grupo_rotulo").agg(valor=("preco_total", "sum"), insumos=("chave_insumo", "nunique"))
    g["pct"] = g["valor"] / g["valor"].sum() * 100 if len(g) else 0
    return g.sort_values("valor", ascending=False).reset_index()


def resumo_ano(rank: pd.DataFrame) -> dict:
    if rank.empty:
        return {}
    por_classe = rank.groupby("classe").agg(n=("chave_insumo", "size"), valor=("valor", "sum"))
    total = float(rank["valor"].sum())
    altas = rank[(rank["classe"].isin(["A", "B"])) & (rank["var_preco_pct"] > 0)]
    sobe = rank["efeito_preco"].fillna(0.0)
    return {
        "valor": total, "insumos": int(len(rank)),
        "a_n": int(por_classe["n"].get("A", 0)), "a_valor": float(por_classe["valor"].get("A", 0.0)),
        "b_n": int(por_classe["n"].get("B", 0)), "c_n": int(por_classe["n"].get("C", 0)),
        "a_pct_itens": float(por_classe["n"].get("A", 0) / len(rank) * 100),
        "altas_ab": int(len(altas)),
        # quanto a mais se pagou nos A/B que subiram (mesmos detalhes, quantidade do ano): efeito preço
        "efeito_preco_ab": float(altas["efeito_preco"].sum()),
        "efeito_preco_total": float(sobe.sum()),
    }


def pareto(rank: pd.DataFrame) -> pd.DataFrame:
    r = rank[["posicao", "pct_acum", "classe", "insumo", "valor"]].copy()
    r["pct_itens"] = r["posicao"] / len(r) * 100 if len(r) else 0
    return r
