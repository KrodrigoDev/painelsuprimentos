"""Contratos: filtros e agregações (pandas puro, testável). Os campos derivados vêm prontos do ETL
(pct_medido, em_andamento, vencido_com_saldo, vence_em_breve, segmento, cod_obra)."""
from __future__ import annotations

import pandas as pd

SITUACOES = ["Pendente", "Parcialmente medido", "Totalmente medido", "Concluído", "Rescindido"]
ENCERRADOS = ("Concluído", "Rescindido")


def _rotulo(cod, nome) -> pd.Series:
    c = pd.to_numeric(pd.Series(cod), errors="coerce")
    n = pd.Series(nome).astype(object)
    out = []
    for ci, ni in zip(c, n):
        ni = "" if ni is None or (isinstance(ni, float) and pd.isna(ni)) else str(ni).strip()
        ci = "" if pd.isna(ci) else str(int(ci))
        out.append(" - ".join(x for x in (ci, ni) if x) or "(sem informação)")
    return pd.Series(out, index=pd.Series(cod).index)


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Só contratos em que a empresa é CONTRATANTE (fornecedores). Os de 'Contratada' (clientes) ficam fora."""
    d = df[df["sit_empresa"].fillna("Contratante") != "Contratada"].copy()
    d["fornecedor_rotulo"] = _rotulo(d["cod_fornecedor"], d["fornecedor"]).to_numpy()
    d["obra_rotulo"] = _rotulo(d["cod_obra"], d["obra"]).to_numpy()
    d["empresa_rotulo"] = _rotulo(d["cod_empresa"], d["empresa"]).to_numpy()
    d["tipo_contrato"] = d["tipo_contrato"].fillna("(sem tipo)")
    d["saldo_aberto"] = d["saldo"].fillna(0.0).where(d["em_andamento"], 0.0)
    d["nao_executado"] = (d["valor_total"].fillna(0) - d["valor_medido"].fillna(0)).where(
        d["situacao"].isin(ENCERRADOS), 0.0).clip(lower=0)
    d["ano_mes_contrato"] = d["data_contrato"].dt.strftime("%Y-%m")
    d["ano_mes_termino"] = d["data_termino"].dt.strftime("%Y-%m")
    return d


def filtrar(d: pd.DataFrame, ini=None, fim=None, situacoes=None, tipos=None, segmentos=None, obras=None,
            empresas=None, fornecedores=None, texto=None, autorizacao=None) -> pd.DataFrame:
    m = pd.Series(True, index=d.index)
    if ini:
        m &= d["data_contrato"] >= pd.Timestamp(ini)
    if fim:
        m &= d["data_contrato"] <= pd.Timestamp(fim)
    for col, val in (("situacao", situacoes), ("tipo_contrato", tipos), ("segmento", segmentos), ("cod_obra", obras),
                     ("cod_empresa", empresas), ("cod_fornecedor", fornecedores), ("situacao_autorizacao", autorizacao)):
        if val:
            m &= d[col].isin(val)
    if texto:
        t = str(texto).strip().lower()
        m &= (d["numero_contrato"].str.lower().str.contains(t, regex=False)
              | d["objeto"].fillna("").str.lower().str.contains(t, regex=False)
              | d["fornecedor"].fillna("").str.lower().str.contains(t, regex=False))
    return d[m]


def resumo(d: pd.DataFrame) -> dict:
    and_ = d[d["em_andamento"]]
    venc = d[d["vencido_com_saldo"]]
    breve = d[d["vence_em_breve"]]
    aguard = d[d["situacao_autorizacao"] == "Aguardando autorização"]
    enc = d[d["situacao"].isin(ENCERRADOS)]
    total = float(d["valor_total"].sum())
    medido = float(d["valor_medido"].sum())
    return {
        "contratos": len(d), "fornecedores": int(d["cod_fornecedor"].nunique()), "valor_total": total,
        "valor_medido": medido, "pct_medido": medido / total * 100 if total else 0.0,
        "em_andamento": len(and_), "saldo": float(and_["saldo_aberto"].sum()),
        "vencidos": len(venc), "saldo_vencidos": float(venc["saldo_aberto"].sum()),
        "vence_breve": len(breve), "saldo_breve": float(breve["saldo_aberto"].sum()),
        "aguardando": len(aguard), "valor_aguardando": float(aguard["valor_total"].sum()),
        "encerrados": len(enc), "nao_executado": float(enc["nao_executado"].sum()),
    }


def por(d: pd.DataFrame, chave: str, rotulo: str | None = None) -> pd.DataFrame:
    rotulo = rotulo or chave
    g = (d.assign(_sv=d["saldo_aberto"].where(d["vencido_com_saldo"], 0.0))
         .groupby([chave, rotulo] if rotulo != chave else [chave], dropna=False)
         .agg(contratos=("numero_contrato", "size"), valor_total=("valor_total", "sum"),
              valor_medido=("valor_medido", "sum"), saldo=("saldo_aberto", "sum"),
              vencidos=("vencido_com_saldo", "sum"), saldo_vencido=("_sv", "sum"))
         .reset_index())
    g["pct_medido"] = (g["valor_medido"] / g["valor_total"].where(g["valor_total"] > 0) * 100).fillna(0.0)
    return g.sort_values(["saldo", "valor_total"], ascending=False)


def assinados_mes(d: pd.DataFrame, meses: int = 24) -> pd.DataFrame:
    if d.empty or d["data_contrato"].isna().all():
        return pd.DataFrame(columns=["ano_mes", "contratos", "valor"])
    fim = d["data_contrato"].max().to_period("M")
    ini = fim - (meses - 1)
    g = (d[d["data_contrato"].dt.to_period("M") >= ini].groupby("ano_mes_contrato")
         .agg(contratos=("numero_contrato", "size"), valor=("valor_total", "sum")))
    todos = pd.period_range(ini, fim, freq="M").strftime("%Y-%m")
    return g.reindex(todos, fill_value=0).rename_axis("ano_mes").reset_index()


def vencimentos(d: pd.DataFrame, posicao: pd.Timestamp, meses: int = 12) -> pd.DataFrame:
    """Saldo a medir dos contratos em andamento pelo mês de término (vencidos agrupados numa barra)."""
    a = d[d["em_andamento"] & (d["saldo_aberto"] > 0)]
    if a.empty:
        return pd.DataFrame(columns=["periodo", "saldo", "contratos", "vencido"])
    p0 = pd.Timestamp(posicao).to_period("M")
    per = a["data_termino"].dt.to_period("M")
    linhas = [{"periodo": "Vencidos", "saldo": float(a.loc[a["vencido_com_saldo"], "saldo_aberto"].sum()),
               "contratos": int(a["vencido_com_saldo"].sum()), "vencido": True}]
    for i in range(meses):
        p = p0 + i
        sel = (per == p) & ~a["vencido_com_saldo"]
        linhas.append({"periodo": p.strftime("%m/%Y"), "saldo": float(a.loc[sel, "saldo_aberto"].sum()),
                       "contratos": int(sel.sum()), "vencido": False})
    depois = (per > p0 + (meses - 1)) | a["data_termino"].isna()
    linhas.append({"periodo": "Depois / sem data", "saldo": float(a.loc[depois & ~a["vencido_com_saldo"], "saldo_aberto"].sum()),
                   "contratos": int((depois & ~a["vencido_com_saldo"]).sum()), "vencido": False})
    return pd.DataFrame(linhas)
