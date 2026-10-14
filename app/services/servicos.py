"""Solicitações de serviço: filtros e agregações (pandas puro). Campos derivados vêm do ETL."""
from __future__ import annotations

import numpy as np
import pandas as pd

SITUACOES = ["Totalmente atendida", "Parcialmente atendida", "Pendente", "Cancelada"]
AUTORIZACOES = ["Aprovada", "Aguardando autorização", "Reprovada"]


def _rotulo(cod, nome):
    c = pd.to_numeric(pd.Series(cod), errors="coerce")
    n = pd.Series(nome).astype(object)
    return pd.Series([" - ".join(x for x in ("" if pd.isna(a) else str(int(a)),
                                              "" if b is None or (isinstance(b, float) and pd.isna(b)) else str(b)) if x)
                      or "(sem obra)" for a, b in zip(c, n)], index=pd.Series(cod).index)


def preparar(df: pd.DataFrame, dias_aut: int = 7, dias_aberto: int = 60) -> pd.DataFrame:
    d = df.copy()
    d["obra_rotulo"] = _rotulo(d["cod_obra"], d["obra"]).to_numpy()
    for c in ("solicitante", "autorizador", "departamento"):
        d[c] = d[c].fillna("(sem informação)")
    d["ano_mes"] = d["data_cadastro"].dt.strftime("%Y-%m")
    d["alerta_autorizacao"] = d["aguardando_dias"].fillna(-1) > dias_aut
    d["alerta_aberto"] = d["em_aberto"] & (d["idade_dias"].fillna(-1) > dias_aberto)
    d["alerta"] = np.select([d["alerta_autorizacao"], d["termino_vencido"], d["alerta_aberto"]],
                            [f"aguardando autorização > {dias_aut} d", "término previsto vencido",
                             f"em aberto > {dias_aberto} d"], default="")
    return d


def filtrar(d, ini=None, fim=None, obras=None, solicitantes=None, autorizadores=None, aut=None, situacoes=None,
            segmentos=None, texto=None) -> pd.DataFrame:
    m = pd.Series(True, index=d.index)
    if ini:
        m &= d["data_cadastro"] >= pd.Timestamp(ini)
    if fim:
        m &= d["data_cadastro"] <= pd.Timestamp(fim)
    for col, val in (("cod_obra", obras), ("solicitante", solicitantes), ("autorizador", autorizadores),
                     ("situacao_autorizacao", aut), ("situacao", situacoes), ("segmento", segmentos)):
        if val:
            m &= d[col].isin(val)
    if texto:
        t = str(texto).strip().lower()
        m &= (d["observacao"].fillna("").str.lower().str.contains(t, regex=False)
              | (d["cod_solicitacao"].astype(str) == t))
    return d[m]


def resumo(d: pd.DataFrame) -> dict:
    s, a = d["situacao"], d["situacao_autorizacao"]
    ab = d[d["em_aberto"]]
    return {
        "solicitado": len(d), "totalmente": int((s == "Totalmente atendida").sum()),
        "parcial": int((s == "Parcialmente atendida").sum()), "cancelado": int((s == "Cancelada").sum()),
        "pendente": int((s == "Pendente").sum()), "aprovado": int((a == "Aprovada").sum()),
        "aguardando": int((a == "Aguardando autorização").sum()), "reprovado": int((a == "Reprovada").sum()),
        "em_aberto": len(ab), "idade_mediana_aberto": ab["idade_dias"].median() if len(ab) else np.nan,
        "termino_vencido": int(d["termino_vencido"].sum()), "alerta_aut": int(d["alerta_autorizacao"].sum()),
        "alerta_aberto": int(d["alerta_aberto"].sum()),
        "duracao_media": d["dias_previstos"].mean(), "duracao_mediana": d["dias_previstos"].median(),
        "resposta_media": d["dias_cadastro_alteracao"].mean(), "resposta_mediana": d["dias_cadastro_alteracao"].median(),
        "pct_atendido": ((s == "Totalmente atendida").sum() / (len(d) - (s == "Cancelada").sum()) * 100
                         if len(d) - (s == "Cancelada").sum() else np.nan),
    }


def mensal(d: pd.DataFrame) -> pd.DataFrame:
    g = d.groupby("ano_mes").agg(solicitado=("cod_solicitacao", "size"),
                                 atendido=("situacao", lambda s: int((s == "Totalmente atendida").sum())),
                                 em_aberto=("em_aberto", "sum"))
    return g.reset_index()


def por(d: pd.DataFrame, dim: str) -> pd.DataFrame:
    g = d.groupby(dim, dropna=False).agg(
        solicitado=("cod_solicitacao", "size"),
        atendido=("situacao", lambda s: int((s == "Totalmente atendida").sum())),
        em_aberto=("em_aberto", "sum"), cancelado=("situacao", lambda s: int((s == "Cancelada").sum())),
        aguardando=("situacao_autorizacao", lambda s: int((s == "Aguardando autorização").sum())),
        termino_vencido=("termino_vencido", "sum"), idade_mediana=("idade_dias", "median"),
        resposta_mediana=("dias_cadastro_alteracao", "median")).reset_index()
    g["pct_atendido"] = g["atendido"] / (g["solicitado"] - g["cancelado"]).replace(0, np.nan) * 100
    return g.sort_values(["em_aberto", "solicitado"], ascending=False)
