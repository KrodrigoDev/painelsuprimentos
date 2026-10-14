"""
SLA de insumos: prazos (editáveis) × dias medidos no ETL. Pandas puro, testável.

Fase 1 = autorização da solicitação -> 1º pedido do item (grão: item; linhas com linha_do_item).
Fase 2 = pedido -> última entrega do item completo (grão: item × pedido).

Situação de cada linha numa fase (coluna f1 / f2):
    no_prazo        concluída em até o prazo
    fora_prazo      concluída depois do prazo
    aberto_no_prazo em aberto, idade abaixo do alerta
    em_risco        em aberto, idade ≥ alerta% do prazo (ainda dentro)
    atrasado        em aberto, idade > prazo (backlog que já estourou)
    sem_prazo       grupo sem prazo configurado
    fora            cancelada / aguardando autorização / sem pedido (não entra)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SITUACOES = ["no_prazo", "fora_prazo", "aberto_no_prazo", "em_risco", "atrasado", "sem_prazo", "fora"]
ROTULO = {"no_prazo": "Atendido no prazo", "fora_prazo": "Atendido fora do prazo",
          "aberto_no_prazo": "Em aberto no prazo", "em_risco": "Em aberto em risco", "atrasado": "Em aberto atrasado",
          "sem_prazo": "Sem prazo configurado", "fora": "Não se aplica"}
ETAPAS = [("dias_aprovacao_solicitacao", "Aprovação da solicitação"), ("dias_fase1", "Compra (fase 1)"),
          ("dias_autorizacao_pedido", "Autorização do pedido"), ("dias_fornecedor", "Entrega do fornecedor")]
DIMENSOES = {"grupo_insumo": "Grupo de insumo", "tipo_grupo": "Tipo de grupo", "analista": "Analista",
             "comprador": "Comprador", "fornecedor": "Fornecedor", "obra_rotulo": "Obra", "segmento": "Segmento"}


def _situacao(status, dias, idade, prazo, risco_pct) -> np.ndarray:
    concl = status == "concluida"
    aberto = status.isin(["aberta", "parcial"])
    tem = prazo.notna()
    return np.select(
        [~(concl | aberto), ~tem, concl & (dias <= prazo), concl & (dias > prazo), concl & dias.isna(),
         aberto & (idade > prazo), aberto & (idade >= prazo * risco_pct / 100), aberto],
        ["fora", "sem_prazo", "no_prazo", "fora_prazo", "fora", "atrasado", "em_risco", "aberto_no_prazo"],
        default="fora")


def preparar(df: pd.DataFrame, prazos: pd.DataFrame, risco_pct: float = 80) -> pd.DataFrame:
    p = prazos[["id_grupo", "lt_fase1", "lt_fase2", "lt_total", "origem"]].rename(columns={"origem": "origem_prazo"})
    d = df.merge(p, on="id_grupo", how="left")
    d["f1"] = _situacao(d["status_fase1"], d["dias_fase1"], d["idade_fase1"], d["lt_fase1"], risco_pct)
    d.loc[~d["linha_do_item"], "f1"] = "fora"                 # fase 1 conta 1x por item
    d["f2"] = _situacao(d["status_fase2"], d["dias_fase2"], d["idade_fase2"], d["lt_fase2"], risco_pct)
    d["excesso_f1"] = (d["dias_fase1"] - d["lt_fase1"]).where(d["f1"] == "fora_prazo")
    d["excesso_f2"] = (d["dias_fase2"] - d["lt_fase2"]).where(d["f2"] == "fora_prazo")
    d["atraso_aberto_f1"] = (d["idade_fase1"] - d["lt_fase1"]).where(d["f1"] == "atrasado")
    d["atraso_aberto_f2"] = (d["idade_fase2"] - d["lt_fase2"]).where(d["f2"] == "atrasado")
    cod = d["cod_obra"].astype("Int64").astype(str).replace("<NA>", "")
    d["obra_rotulo"] = (cod + " - " + d["obra"].fillna("").str.replace(r"^\d+\s*-\s*", "", regex=True)).str.strip(" -")
    d["ano_mes"] = d["data_solicitacao"].dt.strftime("%Y-%m")
    # sem pedido ainda: o responsável é o comprador distribuído na solicitação
    d["comprador"] = d["comprador"].fillna(d["comprador_distribuido"])
    for c in ("analista", "comprador", "fornecedor", "grupo_insumo"):
        d[c] = d[c].fillna("(sem informação)")
    return d


def filtrar(d: pd.DataFrame, ini=None, fim=None, obras=None, grupos=None, tipos=None, analistas=None,
            compradores=None, segmentos=None, curvas=None, sit_sol=None, sit_ped=None, texto=None) -> pd.DataFrame:
    m = pd.Series(True, index=d.index)
    if ini:
        m &= d["data_solicitacao"] >= pd.Timestamp(ini)
    if fim:
        m &= d["data_solicitacao"] <= pd.Timestamp(fim)
    for col, val in (("cod_obra", obras), ("id_grupo", grupos), ("tipo_grupo", tipos), ("analista", analistas),
                     ("comprador", compradores), ("segmento", segmentos), ("curva_abc_grupo", curvas),
                     ("situacao_solicitacao", sit_sol), ("situacao_pedido", sit_ped)):
        if val:
            m &= d[col].isin(val)
    if texto:
        t = str(texto).strip().lower()
        num = t.isdigit()
        m &= (d["insumo"].fillna("").str.lower().str.contains(t, regex=False)
              | (d["cod_solicitacao"].astype(str) == t if num else False)
              | (d["cod_insumo"].astype(str) == t if num else False))
    return d[m]


def resumo_fase(d: pd.DataFrame, fase: str, contar_abertos: bool = True) -> dict:
    s = d[fase]
    concl = s.isin(["no_prazo", "fora_prazo"])
    dias = d["dias_fase1" if fase == "f1" else "dias_fase2"][concl]
    prazo = d["lt_fase1" if fase == "f1" else "lt_fase2"][concl]
    no, fora, atras = int((s == "no_prazo").sum()), int((s == "fora_prazo").sum()), int((s == "atrasado").sum())
    base = no + fora + (atras if contar_abertos else 0)
    return {
        "mensuraveis": no + fora, "atendidos": no, "nao_atendidos": fora, "atrasados_abertos": atras,
        "em_risco": int((s == "em_risco").sum()), "abertos_no_prazo": int((s == "aberto_no_prazo").sum()),
        "sem_prazo": int((s == "sem_prazo").sum()), "base_pct": base,
        "pct": no / base * 100 if base else np.nan,
        "pct_concluidos": no / (no + fora) * 100 if (no + fora) else np.nan,
        "media_dias": float(dias.mean()) if len(dias) else np.nan,
        "mediana_dias": float(dias.median()) if len(dias) else np.nan,
        "p80_dias": float(dias.quantile(.8)) if len(dias) else np.nan,
        "prazo_medio": float(prazo.mean()) if len(prazo) else np.nan,
    }


def mensal(d: pd.DataFrame, contar_abertos: bool = True) -> pd.DataFrame:
    linhas = []
    for mes, g in d.groupby("ano_mes"):
        r1, r2 = resumo_fase(g, "f1", contar_abertos), resumo_fase(g, "f2", contar_abertos)
        linhas.append({"ano_mes": mes, "pct_f1": r1["pct"], "pct_f2": r2["pct"], "n_f1": r1["base_pct"],
                       "n_f2": r2["base_pct"], "mediana_f1": r1["mediana_dias"], "mediana_f2": r2["mediana_dias"]})
    return pd.DataFrame(linhas)


def etapas(d: pd.DataFrame) -> pd.DataFrame:
    """Mediana e P80 de cada etapa (itens com as datas daquela etapa) — onde o tempo é gasto."""
    out = []
    base = d[d["linha_do_item"]]
    for col, nome in ETAPAS:
        s = (d if col in ("dias_autorizacao_pedido", "dias_fornecedor") else base)[col].dropna()
        s = s[s >= 0]
        out.append({"etapa": nome, "coluna": col, "n": len(s), "mediana": s.median() if len(s) else np.nan,
                    "media": s.mean() if len(s) else np.nan, "p80": s.quantile(.8) if len(s) else np.nan})
    return pd.DataFrame(out)


def _fase_por(d: pd.DataFrame, chave: pd.Series, fase: str, contar_abertos: bool) -> pd.DataFrame:
    """Mesmo cálculo de resumo_fase, para todos os grupos de uma vez (groupby vetorizado)."""
    s = d[fase]
    concl = s.isin(["no_prazo", "fora_prazo"])
    dias = d["dias_fase1" if fase == "f1" else "dias_fase2"].where(concl)
    prazo = d["lt_fase1" if fase == "f1" else "lt_fase2"].where(concl)
    t = pd.DataFrame({"_k": chave.values, "no": (s == "no_prazo").values, "fora": (s == "fora_prazo").values,
                      "atras": (s == "atrasado").values, "dias": dias.values, "prazo": prazo.values})
    g = t.groupby("_k", dropna=False, sort=True)
    out = pd.DataFrame({"no": g["no"].sum(), "fora": g["fora"].sum(), "atras": g["atras"].sum(),
                        "mediana": g["dias"].median(), "prazo_medio": g["prazo"].mean()})
    out["base"] = out["no"] + out["fora"] + (out["atras"] if contar_abertos else 0)
    out["pct"] = (out["no"] / out["base"].where(out["base"] > 0) * 100).astype(float)
    return out


def por(d: pd.DataFrame, dim: str, contar_abertos: bool = True, minimo: int = 1) -> pd.DataFrame:
    if d.empty:
        return pd.DataFrame()
    chave = d[dim]
    f1, f2 = _fase_por(d, chave, "f1", contar_abertos), _fase_por(d, chave, "f2", contar_abertos)
    ao = d["atraso_obra"]
    t = pd.DataFrame({"_k": chave.values, "item": d["linha_do_item"].astype(int).values, "ao": ao.values,
                      "apos": (ao > 0).astype(int).values, "tem_ao": ao.notna().astype(int).values})
    g = t.groupby("_k", dropna=False, sort=True)
    tem = g["tem_ao"].sum()
    out = pd.DataFrame({
        dim: f1.index, "itens": g["item"].sum().values.astype(int),
        "n_f1": f1["base"].values.astype(int), "mediana_f1": f1["mediana"].values, "prazo_f1": f1["prazo_medio"].values,
        "pct_f1": f1["pct"].values, "atrasados_f1": f1["atras"].values.astype(int),
        "n_f2": f2["base"].values.astype(int), "mediana_f2": f2["mediana"].values, "prazo_f2": f2["prazo_medio"].values,
        "pct_f2": f2["pct"].values, "atrasados_f2": f2["atras"].values.astype(int),
        "atraso_obra_mediano": g["ao"].median().values,
        "pct_entregue_apos_obra": (g["apos"].sum() / tem.where(tem > 0) * 100).values,
        "nao_atendidos": (f1["fora"] + f2["fora"] + f1["atras"] + f2["atras"]).values.astype(int),
    })
    out = out[(out["n_f1"] + out["n_f2"]) >= minimo].reset_index(drop=True)
    return out.sort_values("nao_atendidos", ascending=False) if len(out) else out


def gargalos(d: pd.DataFrame, contar_abertos: bool = True, top: int = 8) -> list[str]:
    """Frases objetivas sobre onde está o atraso (para a tela e o relatório)."""
    if d.empty:
        return []
    frases = []
    et = etapas(d).dropna(subset=["mediana"])
    if len(et):
        m = et.sort_values("p80", ascending=False).iloc[0]
        frases.append(f"Etapa mais lenta: {m['etapa'].lower()} — mediana {m['mediana']:.0f} dias, 20% dos itens "
                      f"levam {m['p80']:.0f}+ dias.")
    for fase, nome in (("f1", "fase 1 (compra)"), ("f2", "fase 2 (entrega)")):
        g = por(d, "grupo_insumo", contar_abertos, minimo=30)
        if len(g):
            col = "pct_f1" if fase == "f1" else "pct_f2"
            n = "n_f1" if fase == "f1" else "n_f2"
            g = g[g[n] >= 30].assign(perdidos=lambda x: x[n] * (100 - x[col]) / 100).sort_values("perdidos",
                                                                                                    ascending=False)
            if len(g):
                r = g.iloc[0]
                frases.append(f"Maior volume fora do prazo na {nome}: {r['grupo_insumo']} "
                              f"({r[col]:.0f}% no prazo em {int(r[n])} itens).")
    a1, a2 = int((d["f1"] == "atrasado").sum()), int((d["f2"] == "atrasado").sum())
    if a1 or a2:
        frases.append(f"Backlog já fora do prazo: {a1} item(ns) sem pedido e {a2} pedido(s) sem entrega completa.")
    sp = d[d["f1"].eq("sem_prazo") | d["f2"].eq("sem_prazo")]["grupo_insumo"].nunique()
    if sp:
        frases.append(f"{sp} grupo(s) de insumo sem prazo configurado — defina em Configurações.")
    return frases[:top]


def abertos_atrasados(d: pd.DataFrame) -> pd.DataFrame:
    a = d[(d["f1"] == "atrasado") | (d["f2"] == "atrasado")].copy()
    a["fase"] = np.where(a["f1"] == "atrasado", "1 · sem pedido", "2 · sem entrega completa")
    a["dias_em_aberto"] = np.where(a["f1"] == "atrasado", a["idade_fase1"], a["idade_fase2"])
    a["prazo"] = np.where(a["f1"] == "atrasado", a["lt_fase1"], a["lt_fase2"])
    a["dias_alem_prazo"] = a["dias_em_aberto"] - a["prazo"]
    return a.sort_values("dias_alem_prazo", ascending=False)
