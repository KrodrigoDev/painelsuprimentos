"""
Inteligência de compras — LEITURA do que o ETL calculou + filtros da tela.

O processamento pesado (catálogo de equivalências, unidade-base e conversões,
atípicos por mediana/MAD, referência de cada compra, oportunidades) roda no
airflow_api_sienge, etapa `inteligencia_compras` (stage/transform/inteligencia/).
Aqui só:
  - lemos suprimentos.fato_compra_analise e fato_oportunidade_compra (cache);
  - aplicamos o escopo de dados do usuário (segmento, obra, empresa);
  - aplicamos os filtros da tela (período, obra, fornecedor, categoria) e os limites
    escolhidos (confiança, diferença %, impacto), refazendo o "entra no total"
    (no máximo uma oportunidade por material e fornecedor) sobre as linhas filtradas.

Semântica dos filtros: as oportunidades são calculadas sobre TODO o histórico
carregado; período/obra/fornecedor/categoria selecionam quais oportunidades
mostrar pela COMPRA ATUAL de cada uma (a referência pode ser de outra obra ou de
fora do período, desde que dentro da janela de dias do ETL).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import pandas as pd
from sqlalchemy import select

from app.cache import CacheSWR
from app.config import SETTINGS
from app.db import ler_sql
from app.models.dw import ctl_inteligencia_compras, fato_compra_analise, fato_oportunidade_compra
from app.seguranca import escopo as esc_mod
from app.seguranca import sessao


@dataclass(frozen=True)
class ConfigOportunidade:
    """Limites que a TELA aplica. Janela e regras de atípico/aumento são do ETL (ver `config_etl()`)."""
    confianca_minima: float = 85.0
    min_diferenca_pct: float = 5.0
    min_impacto: float = 500.0
    janela_referencia_dias: int = 180   # informativo (vem do ETL)


CFG_PADRAO = ConfigOportunidade()
NIVEIS = (85, 90, 95, 100)

TIPOS = {
    "fornecedor_mais_barato": "Fornecedor alternativo com preço menor",
    "aumento_historico": "Aumento sobre o histórico do mesmo fornecedor",
    "diferenca_obras": "Diferença de preço entre obras",
    "volume_consolidacao": "Compra recorrente: negociar volume / consolidar demanda",
    "verificar_registro": "Preço atípico: conferir registro (não é economia)",
}

_NUM_BASE = ("quantidade", "preco", "preco_unitario", "frete_unitario", "pct_ipi", "pct_icms", "desconto_item", "valor",
             "confianca_membro")


# ─────────────────────────────────────────────────────────────────────────────
# Cache (dados completos; o escopo do usuário é aplicado em cada leitura)
# ─────────────────────────────────────────────────────────────────────────────
_CACHE = CacheSWR("inteligencia", SETTINGS.cache_minutos)


def limpar_cache() -> None:
    _CACHE.limpar()


def _carregar_base() -> pd.DataFrame:
    df = ler_sql(select(fato_compra_analise))
    for c in _NUM_BASE:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    for c in ("data_pedido", "data_referencia"):
        df[c] = pd.to_datetime(df[c])
    df["n_membros"] = df["n_membros"].astype(int)
    df["comparavel"] = df["comparavel"].astype(bool)
    df["atipico"] = df["atipico"].astype(bool)
    return df


def _json(v):
    if v is None or isinstance(v, (dict, list)):
        return v
    return json.loads(v)


def _carregar_oportunidades() -> pd.DataFrame:
    df = ler_sql(select(fato_oportunidade_compra))
    for c in ("evidencia_atual", "evidencia_referencia", "ressalvas"):
        df[c] = df[c].map(_json)
    df["data_atual"] = pd.to_datetime(df["data_atual"])
    df["entra_no_total"] = df["entra_no_total"].astype(bool)
    # filtros por obra/fornecedor também valem para tipos sem esses campos (usa a compra atual da evidência)
    ev = df["evidencia_atual"]
    df["obra_filtro"] = df["cod_obra"].where(df["cod_obra"].notna(), ev.map(lambda e: (e or {}).get("cod_obra")))
    df["fornecedor_filtro"] = df["cod_fornecedor"].where(
        df["cod_fornecedor"].notna(), ev.map(lambda e: (e or {}).get("cod_fornecedor"))).astype(float)
    return df


def _int_ou_none(v):
    try:
        return None if v is None or pd.isna(v) else int(v)
    except (TypeError, ValueError):
        return None


def com_rastreio(df: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta os códigos para achar o caso no ERP: pedido/item e solicitação da compra atual e da
    referência (quando a referência é uma compra; mediana/histórico não tem pedido).

    Pedido e item vêm da evidência gravada pelo ETL; a solicitação vem do painel de compras (RPA),
    casando pedido + insumo — vazia quando o pedido não está no painel de compras (ex.: antes de 2025)."""
    from app.repositories import rpa_repo
    if df is None or df.empty:
        return (df if df is not None else pd.DataFrame()).assign(
            pedido_atual=None, item_atual=None, solicitacao_atual=None, pedido_ref=None, item_ref=None,
            data_ref=None, solicitacao_ref=None)
    sol = rpa_repo.solicitacoes_por_pedido()["solicitacoes"].to_dict()

    def campos(e):
        e = e or {}
        ped, ins, item = _int_ou_none(e.get("pedido")), _int_ou_none(e.get("cod_insumo")), _int_ou_none(e.get("item"))
        # códigos como texto: sem separador de milhar na tela, no CSV e no PDF
        return (None if ped is None else str(ped), None if item is None else str(item),
                sol.get((ped, ins)) if ped is not None and ins is not None else None)

    at = [campos(e) for e in df["evidencia_atual"]]
    rf = [campos(e) for e in df["evidencia_referencia"]]
    col = lambda v: pd.Series(v, index=df.index, dtype=object)  # noqa: E731 — None continua None (não NaN)
    return df.assign(
        pedido_atual=col([a[0] for a in at]), item_atual=col([a[1] for a in at]),
        solicitacao_atual=col([a[2] for a in at]), pedido_ref=col([r[0] for r in rf]), item_ref=col([r[1] for r in rf]),
        solicitacao_ref=col([r[2] for r in rf]),
        data_ref=pd.to_datetime([(e or {}).get("data") for e in df["evidencia_referencia"]], errors="coerce"))


def _escopar(df: pd.DataFrame) -> pd.DataFrame:
    return esc_mod.filtrar(df, sessao.escopo(), segmento="segmento", obra="cod_obra", empresa="cod_empresa")


def base() -> pd.DataFrame:
    """Compras analisadas (já com grupo, unidade-base, atípico, referência) visíveis para o usuário."""
    return _escopar(_CACHE.obter("base", _carregar_base))


def ultimo_processamento() -> dict | None:
    try:
        df = ler_sql(select(ctl_inteligencia_compras).order_by(ctl_inteligencia_compras.c.processado_em.desc())
                     .limit(1))
    except Exception:  # noqa: BLE001 — tabela ainda não criada pelo ETL
        return None
    if df.empty:
        return None
    r = df.iloc[0].to_dict()
    r["config"] = _json(r.get("config")) or {}
    r["resumo_catalogo"] = _json(r.get("resumo_catalogo")) or {}
    return r


def config_etl() -> dict:
    r = ultimo_processamento()
    return (r or {}).get("config") or {}


def filtrar(df: pd.DataFrame, ini=None, fim=None, obras=None, fornecedores=None, categorias=None,
            grupos=None) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    if ini:
        m &= df["data_pedido"] >= pd.Timestamp(ini)
    if fim:
        m &= df["data_pedido"] <= pd.Timestamp(fim)
    if obras:
        m &= df["cod_obra"].isin(obras)
    if fornecedores:
        m &= df["cod_fornecedor"].isin(fornecedores)
    if categorias:
        m &= df["categoria"].isin(categorias)
    if grupos:
        m &= df["id_grupo"].isin(grupos)
    return df[m]


# ─────────────────────────────────────────────────────────────────────────────
# Oportunidades (pré-calculadas) + limites da tela
# ─────────────────────────────────────────────────────────────────────────────
def nivel(cfg: ConfigOportunidade) -> int:
    """Nível gravado pelo ETL mais próximo (para cima) da confiança escolhida."""
    for n in NIVEIS:
        if cfg.confianca_minima <= n:
            return n
    return NIVEIS[-1]


def passa_limites(ops: pd.DataFrame, min_pct: float, min_imp: float) -> pd.Series:
    """Mesmos cortes do ETL: 'fornecedor mais barato' e 'diferença entre obras' exigem diferença % e impacto."""
    ac = ops["tipo"].isin(["fornecedor_mais_barato", "diferenca_obras"])
    return ~ac | ((ops["diferenca_pct"] >= min_pct) & (ops["impacto"] >= min_imp))


def entra_no_total(ops: pd.DataFrame, min_imp: float) -> pd.Series:
    """Sem dupla contagem: por (material, fornecedor) soma o 'fornecedor mais barato'; se não houver, o aumento."""
    if ops.empty:
        return pd.Series(dtype=bool)
    chave = ops["id_grupo"].astype(str) + "§" + ops["cod_fornecedor"].astype(str)
    a = ops["tipo"] == "fornecedor_mais_barato"
    b = (ops["tipo"] == "aumento_historico") & ~chave.isin(set(chave[a])) & (ops["impacto"] >= min_imp)
    return a | b


def selecionar(ops: pd.DataFrame, ini=None, fim=None, obras=None, fornecedores=None, categorias=None,
               cfg: ConfigOportunidade = CFG_PADRAO) -> pd.DataFrame:
    d = ops[ops["nivel_confianca"] == nivel(cfg)]
    d = d[passa_limites(d, cfg.min_diferenca_pct, cfg.min_impacto)]
    if ini:
        d = d[d["data_atual"] >= pd.Timestamp(ini)]
    if fim:
        d = d[d["data_atual"] <= pd.Timestamp(fim)]
    if obras:
        d = d[d["obra_filtro"].isin(obras)]
    if fornecedores:
        d = d[d["fornecedor_filtro"].isin([float(f) for f in fornecedores])]
    if categorias:
        d = d[d["categoria"].isin(categorias)]
    d = d.assign(entra_no_total=entra_no_total(d, cfg.min_impacto))
    return d.sort_values(["entra_no_total", "prioridade"], ascending=[False, False]).reset_index(drop=True)


def oportunidades(ini=None, fim=None, obras=None, fornecedores=None, categorias=None,
                  cfg: ConfigOportunidade = CFG_PADRAO) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(oportunidades, compras filtradas) — só leitura + filtros; nada é recalculado aqui."""
    ops = _escopar(_CACHE.obter("oportunidades", _carregar_oportunidades))
    return selecionar(ops, ini, fim, obras, fornecedores, categorias, cfg), filtrar(base(), ini, fim, obras,
                                                                                   fornecedores, categorias)


def evolucao_mensal(df: pd.DataFrame, cfg: ConfigOportunidade = CFG_PADRAO) -> pd.DataFrame:
    """Por mês: valor comprado e excesso sobre o menor preço comparável do mesmo mês (calculado no ETL)."""
    if df.empty:
        return pd.DataFrame(columns=["ano_mes", "valor", "excesso"])
    col = f"excesso_c{nivel(cfg)}"
    return (df.assign(excesso=pd.to_numeric(df[col], errors="coerce").fillna(0.0))
            .groupby("ano_mes", as_index=False).agg(valor=("valor", "sum"), excesso=("excesso", "sum")))


def config_dict(cfg: ConfigOportunidade = CFG_PADRAO) -> dict:
    return asdict(cfg)


# ─────────────────────────────────────────────────────────────────────────────
# Consultas por material (Comparativo / Histórico) — colunas já calculadas no ETL
# ─────────────────────────────────────────────────────────────────────────────
def opcoes_materiais(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Materiais (grupos) com mais de uma compra, ordenados por valor comprado."""
    d = base() if df is None else df
    g = (d[d["comparavel"]].groupby("id_grupo")
         .agg(nome=("nome_grupo", "first"), categoria=("categoria", "first"), unidade=("unidade_base", "first"),
              n=("cod_pedido", "size"), fornecedores=("cod_fornecedor", "nunique"), obras=("cod_obra", "nunique"),
              insumos=("chave", "nunique"), valor=("valor", "sum")).reset_index())
    return g[g["n"] >= 2].sort_values("valor", ascending=False)


def detalhe_material(id_grupo: str, ini=None, fim=None, obras=None, cfg: ConfigOportunidade = CFG_PADRAO) -> pd.DataFrame:
    """Compras do material com referência (menor preço de OUTRO fornecedor na janela, calculada no ETL sobre todo o
    histórico), diferenças e economia potencial por linha."""
    d = filtrar(base(), ini, fim, obras, grupos=[id_grupo])
    if d.empty:
        return d
    d = d.sort_values("data_pedido").reset_index(drop=True)
    d["economia_potencial"] = pd.to_numeric(d["economia_potencial"], errors="coerce").fillna(0.0)
    return d


def resumo_por(d: pd.DataFrame, chave: list[str]) -> pd.DataFrame:
    ok = d[d["comparavel"] & ~d["atipico"]]
    if ok.empty:
        return pd.DataFrame()
    g = ok.groupby(chave)
    out = g.agg(n=("cod_pedido", "size"), valor=("valor", "sum"), qtd=("qtd_base", "sum"), minimo=("preco_base", "min"),
                maximo=("preco_base", "max"), mediana=("preco_base", "median"), ultima=("data_pedido", "max")).reset_index()
    out["preco_medio"] = (ok.assign(v=ok["preco_base"] * ok["qtd_base"]).groupby(chave)["v"].sum().to_numpy()
                          / out["qtd"].to_numpy())   # média ponderada pela quantidade (unidade-base)
    ult = ok.sort_values("data_pedido").groupby(chave).tail(1).set_index(chave)["preco_base"]
    out["ultimo_preco"] = out.set_index(chave).index.map(ult)
    return out


def estatisticas_mensais(d: pd.DataFrame) -> pd.DataFrame:
    ok = d[d["comparavel"] & ~d["atipico"]]
    if ok.empty:
        return pd.DataFrame()
    g = ok.assign(v=ok["preco_base"] * ok["qtd_base"]).groupby("ano_mes")
    return pd.DataFrame({"mediana": g["preco_base"].median(), "minimo": g["preco_base"].min(),
                         "media_pond": g["v"].sum() / g["qtd_base"].sum(), "n": g.size(),
                         "qtd": g["qtd_base"].sum()}).reset_index()

