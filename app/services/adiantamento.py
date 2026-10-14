"""
Adiantamentos a fornecedores — regras de negócio (pandas puro, testável).

Fonte: suprimentos.fato_adiantamento (1 linha por movimentação, carregada pela
DAG etl_suprimentos_rpa e conciliada com o "Total de adiantamentos" do Sienge).

Definições usadas na tela
-------------------------
* Adiantado / abatido / realocado: soma de `valor` por tipo de movimento,
  DENTRO do período filtrado (fluxo).
* Saldo a abater: Σ efeito_saldo (+adiantamento −abatimento −realocação de
  saída) de TODO o histórico até a data final do filtro (posição). Assim o
  saldo não muda só porque o período começou depois do adiantamento.
* Documento em aberto: documento vinculado (pedido/contrato) com saldo > R$ 0,01.
  Dias em aberto = data de referência − data do primeiro adiantamento.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TOL = 0.01
FAIXAS_IDADE = [(-1, 30, "até 30 dias"), (30, 90, "31 a 90 dias"), (90, 180, "91 a 180 dias"),
                (180, 365, "181 a 365 dias"), (365, 10 ** 6, "mais de 1 ano")]
CHAVE_DOC = ["cod_empresa", "empresa", "cod_credor", "credor", "documento_vinculado", "tipo_vinculo"]


def _tipo(df: pd.DataFrame) -> pd.Series:
    t = df["tipo_movimento"].fillna("").str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii")
    return t.str.lower()


def filtrar(df: pd.DataFrame, ini=None, fim=None, empresas=None, credores=None, tipos=None, vinculos=None,
            documento: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """
    Retorna (movimentos do período, posição até a data final, data de referência).
    `tipos` (tipo de movimento) só restringe a lista de movimentos — não o saldo.
    """
    m = pd.Series(True, index=df.index)
    if empresas:
        m &= df["cod_empresa"].isin(empresas)
    if credores:
        m &= df["cod_credor"].isin(credores)
    if vinculos:
        m &= df["tipo_vinculo"].isin(vinculos)
    if documento:
        alvo = str(documento).strip().upper()
        m &= (df["documento_vinculado"].fillna("").str.upper().str.contains(alvo, regex=False)
              | df["numero_vinculo"].fillna("").eq(alvo))
    base = df[m]
    ref = pd.Timestamp(fim) if fim else (base["data_movimento"].max() if len(base) else pd.Timestamp.today())
    posicao = base[base["data_movimento"] <= ref]
    per = posicao
    if ini:
        per = per[per["data_movimento"] >= pd.Timestamp(ini)]
    if tipos:
        per = per[per["tipo_movimento"].isin(tipos)]
    return per, posicao, ref.normalize()


def resumo(mov: pd.DataFrame, posicao: pd.DataFrame, ref: pd.Timestamp | None = None) -> dict:
    t = _tipo(mov)
    adiant = mov.loc[t == "adiantamento", "valor"]
    abat = mov.loc[t == "abatimento", "valor"]
    realoc = mov.loc[t.str.startswith("realocacao"), "valor"]
    docs = por_documento(posicao, ref)
    abertos = docs[docs["saldo"] > TOL]
    total = float(adiant.sum())
    return {
        "adiantado": total, "n_adiantamentos": int(len(adiant)), "abatido": float(abat.sum()),
        "n_abatimentos": int(len(abat)), "realocado": float(realoc.sum()),
        "pct_abatido": float(abat.sum() / total * 100) if total else np.nan,
        "saldo": float(posicao["efeito_saldo"].sum()),
        "credores": int(mov["cod_credor"].nunique()), "lancamentos": int(len(mov)),
        "credores_com_saldo": int(abertos["cod_credor"].nunique()),
        "documentos_abertos": int(len(abertos)),
        "saldo_mais_1_ano": float(abertos.loc[abertos["dias_em_aberto"] > 365, "saldo"].sum()),
    }


def por_documento(posicao: pd.DataFrame, ref: pd.Timestamp | None = None) -> pd.DataFrame:
    """1 linha por documento vinculado: adiantado, abatido, realocado, saldo, idade."""
    if posicao.empty:
        return pd.DataFrame(columns=CHAVE_DOC + ["adiantado", "abatido", "realocado", "saldo", "primeiro_adiantamento",
                                                 "ultimo_movimento", "movimentos", "dias_em_aberto", "situacao"])
    p = posicao.assign(_t=_tipo(posicao))
    p = p.assign(_ad=np.where(p["_t"] == "adiantamento", p["valor"], 0.0),
                 _ab=np.where(p["_t"] == "abatimento", p["valor"], 0.0),
                 _re=np.where(p["_t"].str.startswith("realocacao"), p["valor"], 0.0),
                 _dad=p["data_movimento"].where(p["_t"] == "adiantamento"))
    g = p.groupby(CHAVE_DOC, dropna=False).agg(
        adiantado=("_ad", "sum"), abatido=("_ab", "sum"), realocado=("_re", "sum"), saldo=("efeito_saldo", "sum"),
        primeiro_adiantamento=("_dad", "min"), ultimo_movimento=("data_movimento", "max"),
        movimentos=("id_movimento", "size")).reset_index()
    ref = ref if ref is not None else posicao["data_movimento"].max()
    inicio = g["primeiro_adiantamento"].fillna(g["ultimo_movimento"])
    g["dias_em_aberto"] = np.where(g["saldo"] > TOL, (ref - inicio).dt.days, np.nan)
    g["situacao"] = np.select([g["saldo"] > TOL, g["saldo"] < -TOL], ["Em aberto", "Abatido acima do adiantado"],
                              "Quitado")
    g["pct_abatido"] = np.where(g["adiantado"] > 0, (g["abatido"] + g["realocado"]) / g["adiantado"] * 100, np.nan)
    return g.sort_values("saldo", ascending=False).reset_index(drop=True)


def idade_saldo(docs: pd.DataFrame) -> pd.DataFrame:
    abertos = docs[docs["saldo"] > TOL]
    linhas = []
    for lo, hi, rot in FAIXAS_IDADE:
        sel = abertos[(abertos["dias_em_aberto"] > lo) & (abertos["dias_em_aberto"] <= hi)]
        linhas.append({"faixa": rot, "saldo": float(sel["saldo"].sum()), "documentos": int(len(sel)),
                       "credores": int(sel["cod_credor"].nunique())})
    return pd.DataFrame(linhas)


def por_credor(docs: pd.DataFrame) -> pd.DataFrame:
    if docs.empty:
        return pd.DataFrame(columns=["cod_credor", "credor", "documentos", "adiantado", "abatido", "saldo",
                                     "pct_abatido", "maior_idade"])
    g = docs.groupby(["cod_credor", "credor"], dropna=False).agg(
        documentos=("documento_vinculado", "size"), adiantado=("adiantado", "sum"), abatido=("abatido", "sum"),
        realocado=("realocado", "sum"), saldo=("saldo", "sum"), maior_idade=("dias_em_aberto", "max")).reset_index()
    g["pct_abatido"] = np.where(g["adiantado"] > 0, (g["abatido"] + g["realocado"]) / g["adiantado"] * 100, np.nan)
    return g.sort_values("saldo", ascending=False).reset_index(drop=True)


def por_empresa(mov: pd.DataFrame, docs: pd.DataFrame) -> pd.DataFrame:
    t = _tipo(mov)
    ad = mov[t == "adiantamento"].groupby(["cod_empresa", "empresa"])["valor"].sum().rename("adiantado")
    sal = docs.groupby(["cod_empresa", "empresa"])["saldo"].sum().rename("saldo")
    g = pd.concat([ad, sal], axis=1).fillna(0.0).reset_index()
    return g[(g["adiantado"] > 0) | (g["saldo"].abs() > TOL)].sort_values("adiantado", ascending=False)


def por_vinculo(mov: pd.DataFrame, docs: pd.DataFrame) -> pd.DataFrame:
    t = _tipo(mov)
    m = mov.assign(_ad=np.where(t == "adiantamento", mov["valor"], 0.0),
                   _ab=np.where(t == "abatimento", mov["valor"], 0.0))
    g = m.groupby("tipo_vinculo").agg(adiantado=("_ad", "sum"), abatido=("_ab", "sum"),
                                      lancamentos=("id_movimento", "size"))
    g["saldo"] = docs.groupby("tipo_vinculo")["saldo"].sum()
    g["documentos_abertos"] = docs[docs["saldo"] > TOL].groupby("tipo_vinculo").size()
    g = g.fillna(0.0).reset_index()
    g["pct_abatido"] = np.where(g["adiantado"] > 0, g["abatido"] / g["adiantado"] * 100, np.nan)
    return g


def mensal(mov: pd.DataFrame) -> pd.DataFrame:
    if mov.empty:
        return pd.DataFrame(columns=["ano_mes", "adiantado", "abatido"])
    t = _tipo(mov)
    m = mov.assign(ano_mes=mov["data_movimento"].dt.strftime("%Y-%m"),
                   adiantado=np.where(t == "adiantamento", mov["valor"], 0.0),
                   abatido=np.where(t == "abatimento", mov["valor"], 0.0))
    g = m.groupby("ano_mes")[["adiantado", "abatido"]].sum()
    meses = pd.period_range(g.index.min(), g.index.max(), freq="M").strftime("%Y-%m")
    return g.reindex(meses, fill_value=0.0).rename_axis("ano_mes").reset_index()
