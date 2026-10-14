"""
Visão geral: o resumo de TODAS as abas num lugar só (e o relatório geral).

Cada área é lida com as mesmas funções das telas (mesmos números, mesmo escopo de acesso) e
é independente: se uma fonte não estiver carregada, a área aparece como "indisponível" e o
resto continua.

Recortes:
  - segmento (vertical) e obra valem para compras, oportunidades, estoque, contratos, SLA e serviços;
  - adiantamentos (só empresa), avaliação de fornecedores e curva ABC não têm obra/vertical:
    aparecem sempre no total (marcados "todas as verticais");
  - o período vale para o que é FLUXO (compras, oportunidades, SLA, serviços); estoque, saldo de
    contratos e saldo de adiantamento são POSIÇÃO na data do relatório.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Area:
    chave: str
    nome: str
    rota: str
    ok: bool = True
    erro: str | None = None
    kpis: dict = field(default_factory=dict)
    dados: pd.DataFrame | None = None


def _obra_int(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("Int64")


def _filtrar(d: pd.DataFrame, segmentos, obras, col_seg="segmento", col_obra="cod_obra", col_data=None, ini=None,
             fim=None) -> pd.DataFrame:
    if d is None or d.empty:
        return d
    m = pd.Series(True, index=d.index)
    if segmentos and col_seg in d:
        m &= d[col_seg].isin(segmentos)
    if obras and col_obra in d:
        m &= _obra_int(d[col_obra]).isin([int(o) for o in obras])
    if col_data and ini:
        m &= d[col_data] >= pd.Timestamp(ini)
    if col_data and fim:
        m &= d[col_data] <= pd.Timestamp(fim)
    return d[m]


def _seguro(chave, nome, rota, fn) -> Area:
    a = Area(chave, nome, rota)
    try:
        fn(a)
    except Exception as exc:  # noqa: BLE001 — uma fonte fora do ar não derruba a visão geral
        logger.warning("Visão geral: %s indisponível: %s", nome, exc)
        a.ok, a.erro = False, str(exc).splitlines()[0][:160]
    return a


# ─────────────────────────────────────────────────────────────────────────────
# Áreas
# ─────────────────────────────────────────────────────────────────────────────
def area_compras(segmentos, obras, ini, fim) -> Area:
    def f(a: Area):
        from app.services import inteligencia as ig
        b = _filtrar(ig.base(), segmentos, obras, col_data="data_pedido", ini=ini, fim=fim)
        ops, _ = ig.oportunidades(ini, fim, None, None, None, ig.CFG_PADRAO)
        ops = _filtrar(ops, segmentos, obras, col_obra="obra_filtro")
        som = ops[ops["entra_no_total"].astype(bool)] if len(ops) else ops
        a.kpis = {"valor": float(b["valor"].sum()), "itens": len(b), "fornecedores": int(b["cod_fornecedor"].nunique()),
                  "economia": float(som["impacto"].sum()) if len(som) else 0.0,
                  "oportunidades": int((ops["tipo"] != "verificar_registro").sum()) if len(ops) else 0,
                  "atipicos": int((ops["tipo"] == "verificar_registro").sum()) if len(ops) else 0}
        a.dados = b.assign(_eco=0.0)
        a.kpis["_ops"] = som
    return _seguro("compras", "Compras e oportunidades", "/", f)


def area_estoque(segmentos, obras) -> Area:
    def f(a: Area):
        from app.pages import estoque as pg
        from app.services import estoque as es
        b = pg.base()
        d = _filtrar(b, segmentos, obras, col_obra="cod_centro_custo")
        r = es.resumo(d, d)
        a.kpis = {"valor": r["valor"], "insumos": r["insumos"], "centros": r["centros"],
                  "abaixo_minimo": r["abaixo_minimo"], "inativos_com_saldo": r["inativos_com_saldo"]}
        a.dados = d[d["com_saldo"]]
    return _seguro("estoque", "Estoque", "/estoque", f)


def area_contratos(segmentos, obras) -> Area:
    def f(a: Area):
        from app.pages import contratos as pg
        from app.services import contratos as ct
        d = _filtrar(pg.base(), segmentos, obras)
        a.kpis = ct.resumo(d)
        a.dados = d
    return _seguro("contratos", "Contratos", "/contratos", f)


def area_sla(segmentos, obras, ini, fim) -> Area:
    def f(a: Area):
        from app.pages import sla_insumos as pg
        from app.services import configuracoes as cf
        from app.services import sla
        d = _filtrar(pg.base(), segmentos, obras, col_data="data_solicitacao", ini=ini, fim=fim)
        contar = cf.parametro("sla.contar_abertos")
        r1, r2 = sla.resumo_fase(d, "f1", contar), sla.resumo_fase(d, "f2", contar)
        ent = d[d["atraso_obra"].notna()]
        a.kpis = {"pct_f1": r1["pct"], "pct_f2": r2["pct"], "vencidos_f1": r1["atrasados_abertos"],
                  "vencidos_f2": r2["atrasados_abertos"], "mediana_f1": r1["mediana_dias"],
                  "mediana_f2": r2["mediana_dias"],
                  "pct_apos_obra": float((ent["atraso_obra"] > 0).mean() * 100) if len(ent) else np.nan,
                  "gargalos": sla.gargalos(d, contar), "contar": contar}
        a.dados = d
    return _seguro("sla", "SLA de insumos", "/sla-insumos", f)


def area_servicos(segmentos, obras, ini, fim) -> Area:
    def f(a: Area):
        from app.pages import servicos as pg
        from app.services import servicos as sv
        d = _filtrar(pg.base(), segmentos, obras, col_data="data_cadastro", ini=ini, fim=fim)
        a.kpis = sv.resumo(d)
        a.dados = d
    return _seguro("servicos", "Serviços", "/servicos", f)


def area_adiantamento() -> Area:
    def f(a: Area):
        from app.repositories import rpa_repo
        from app.services import adiantamento as ad
        b = rpa_repo.adiantamentos()
        if b.empty:
            raise ValueError("sem dados no seu escopo de acesso")
        mov, pos, ref = ad.filtrar(b)
        r = ad.resumo(mov, pos, ref)
        a.kpis = {"saldo": r["saldo"], "credores_com_saldo": r["credores_com_saldo"],
                  "saldo_mais_1_ano": r["saldo_mais_1_ano"], "documentos_abertos": r["documentos_abertos"],
                  "ref": ref}
        a.dados = ad.por_documento(pos, ref)
    return _seguro("adiantamento", "Adiantamentos", "/adiantamento", f)


def area_avaliacao() -> Area:
    def f(a: Area):
        from app.repositories import rpa_repo
        from app.services import avaliacao as av
        b = rpa_repo.avaliacoes()
        if b.empty:
            raise ValueError("sem dados no seu escopo de acesso")
        fim = b["mes_referencia"].max()
        ini = (fim - pd.DateOffset(months=2)).to_period("M").to_timestamp()
        d = av.filtrar(b, ini, fim + pd.offsets.MonthEnd(0))
        forn = av.por_fornecedor(d, av.BASE_PADRAO, rpa_repo.compras_por_fornecedor())
        r = av.resumo(d, forn)
        a.kpis = {**r, "periodo": f"{ini:%m/%Y} a {fim:%m/%Y}"}
        a.dados = forn[forn["classe"] == "A"]
    return _seguro("avaliacao", "Avaliação de fornecedores", "/avaliacao-fornecedor", f)


def area_curva_abc() -> Area:
    def f(a: Area):
        from app.pages import curva_abc as pg
        from app.services import curva_abc as ca
        b = pg._base()
        if b.empty:
            raise ValueError("sem dados no seu escopo de acesso")
        anos = sorted(b["ano"].unique(), reverse=True)
        ano, ant = int(anos[0]), (int(anos[1]) if len(anos) > 1 else None)
        rank = ca.ranking(b, ano, ant)
        a.kpis = {**ca.resumo_ano(rank), "ano": ano, "ano_anterior": ant}
        a.dados = rank
    return _seguro("curva_abc", "Curva ABC", "/curva-abc", f)


def carregar(segmentos=None, obras=None, ini=None, fim=None) -> dict[str, Area]:
    areas = [area_compras(segmentos, obras, ini, fim), area_estoque(segmentos, obras), area_contratos(segmentos, obras),
             area_sla(segmentos, obras, ini, fim), area_servicos(segmentos, obras, ini, fim), area_adiantamento(),
             area_avaliacao(), area_curva_abc()]
    return {a.chave: a for a in areas}


# ─────────────────────────────────────────────────────────────────────────────
# Panoramas por vertical e por obra
# ─────────────────────────────────────────────────────────────────────────────
def _sla_por(d: pd.DataFrame, chave: str, contar: bool) -> pd.DataFrame:
    from app.services import sla
    if d is None or d.empty:
        return pd.DataFrame(columns=[chave, "sla_f1", "sla_f2", "sla_vencidos"])
    t = sla.por(d, chave, contar)
    return t.rename(columns={"pct_f1": "sla_f1", "pct_f2": "sla_f2"}).assign(
        sla_vencidos=t["atrasados_f1"] + t["atrasados_f2"])[[chave, "sla_f1", "sla_f2", "sla_vencidos"]]


def panorama(areas: dict[str, Area], por: str = "segmento") -> pd.DataFrame:
    """Uma linha por vertical (por='segmento') ou por obra (por='cod_obra') com o principal de cada área."""
    partes = []
    nomes = []

    def soma(area, col_chave, valor, nome_col, filtro=None):
        a = areas.get(area)
        if not a or not a.ok or a.dados is None or a.dados.empty or col_chave not in a.dados:
            return
        d = a.dados if filtro is None else a.dados[filtro(a.dados)]
        k = d[col_chave] if por == "segmento" else _obra_int(d[col_chave])
        partes.append(d.assign(_k=k).groupby("_k")[valor].sum().rename(nome_col)
                      if valor in d else d.assign(_k=k).groupby("_k").size().rename(nome_col))

    if por == "segmento":
        soma("compras", "segmento", "valor", "compras")
        soma("estoque", "segmento", "valor_estoque", "estoque")
        soma("contratos", "segmento", "saldo_aberto", "contratos_saldo")
        soma("contratos", "segmento", "saldo_aberto", "contratos_vencido", lambda x: x["vencido_com_saldo"])
        soma("servicos", "segmento", "em_aberto", "servicos_abertos")
    else:
        soma("compras", "cod_obra", "valor", "compras")
        soma("estoque", "cod_centro_custo", "valor_estoque", "estoque")
        soma("contratos", "cod_obra", "saldo_aberto", "contratos_saldo")
        soma("contratos", "cod_obra", "saldo_aberto", "contratos_vencido", lambda x: x["vencido_com_saldo"])
        soma("servicos", "cod_obra", "em_aberto", "servicos_abertos")
        for area, col, rot in (("compras", "cod_obra", "obra"), ("estoque", "cod_centro_custo", "centro_rotulo"),
                               ("contratos", "cod_obra", "obra_rotulo"), ("sla", "cod_obra", "obra_rotulo"),
                               ("servicos", "cod_obra", "obra_rotulo")):
            a = areas.get(area)
            if a and a.ok and a.dados is not None and rot in a.dados and len(a.dados):
                nomes.append(a.dados.assign(_k=_obra_int(a.dados[col])).dropna(subset=["_k"])
                             .drop_duplicates("_k").set_index("_k")[rot].astype(str).rename("nome"))
            seg = a.dados if a and a.ok and a.dados is not None else None
            if seg is not None and "segmento" in seg and len(seg):
                nomes.append(seg.assign(_k=_obra_int(seg[col])).dropna(subset=["_k"]).drop_duplicates("_k")
                             .set_index("_k")["segmento"].rename("segmento"))
    ops = areas.get("compras").kpis.get("_ops") if areas.get("compras") and areas["compras"].ok else None
    if ops is not None and len(ops):
        k = ops["segmento"] if por == "segmento" else _obra_int(ops["obra_filtro"])
        partes.append(ops.assign(_k=k).groupby("_k")["impacto"].sum().rename("economia"))
    a = areas.get("sla")
    if a and a.ok and a.dados is not None and len(a.dados):
        col = "segmento" if por == "segmento" else "cod_obra"
        t = _sla_por(a.dados.assign(_k=a.dados[col] if por == "segmento" else _obra_int(a.dados[col])), "_k",
                     a.kpis.get("contar", True)).set_index("_k")
        partes.append(t)
    if not partes:
        return pd.DataFrame()
    out = pd.concat(partes, axis=1)
    if por != "segmento":
        info = pd.DataFrame(index=out.index)
        for s in nomes:
            s = s[~s.index.duplicated()]
            if s.name in info:
                info[s.name] = info[s.name].fillna(s)
            else:
                info[s.name] = s
        out = info.join(out)
    for c in ("compras", "economia", "estoque", "contratos_saldo", "contratos_vencido", "servicos_abertos", "sla_vencidos"):
        if c not in out:
            out[c] = 0.0
        out[c] = out[c].fillna(0)
    for c in ("sla_f1", "sla_f2"):
        if c not in out:
            out[c] = np.nan
    out["exposicao"] = out["estoque"] + out["contratos_saldo"]
    # vertical/obra sem nenhum movimento em nenhuma área (ex.: "SEM SEGMENTO" vazio) só polui o panorama
    valores = out[["compras", "economia", "estoque", "contratos_saldo", "servicos_abertos", "sla_vencidos"]]
    out = out[valores.ne(0).any(axis=1) | out[["sla_f1", "sla_f2"]].notna().any(axis=1)]
    out = out.rename_axis(por).reset_index()
    return out.sort_values(["compras", "exposicao"], ascending=False).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Pontos de atenção (regras simples e explicáveis, com o número que as dispara)
# ─────────────────────────────────────────────────────────────────────────────
def pontos_de_atencao(areas: dict[str, Area], fontes: pd.DataFrame | None = None) -> list[dict]:
    from app.formatacao import brl_curto, num, pct
    p = []

    def add(nivel, area, texto, rota):
        p.append({"nivel": nivel, "area": area, "texto": texto, "rota": rota})

    c = areas.get("contratos")
    if c and c.ok and c.kpis.get("vencidos"):
        add("alta", "Contratos", f"{num(c.kpis['vencidos'])} contratos com término vencido e "
            f"{brl_curto(c.kpis['saldo_vencidos'])} ainda a medir — encerrar, aditar ou medir.", c.rota)
    s = areas.get("sla")
    if s and s.ok:
        v = s.kpis["vencidos_f1"] + s.kpis["vencidos_f2"]
        if v:
            add("alta", "SLA de insumos", f"{num(s.kpis['vencidos_f1'])} itens sem pedido e {num(s.kpis['vencidos_f2'])} "
                "pedidos sem entrega completa já passaram do prazo.", s.rota)
        if s.kpis["pct_apos_obra"] == s.kpis["pct_apos_obra"] and s.kpis["pct_apos_obra"] > 30:
            add("media", "SLA de insumos", f"{pct(s.kpis['pct_apos_obra'], 0)} das entregas completas chegaram depois "
                "da data pedida pela obra.", s.rota)
    co = areas.get("compras")
    if co and co.ok and co.kpis["economia"] > 0:
        add("media", "Compras", f"Economia potencial estimada de {brl_curto(co.kpis['economia'])} em "
            f"{num(co.kpis['oportunidades'])} oportunidades de negociação (preço acima do comparável).", co.rota)
    if co and co.ok and co.kpis["atipicos"]:
        add("baixa", "Compras", f"{num(co.kpis['atipicos'])} preços atípicos para conferir no pedido (provável erro "
            "de unidade/registro).", co.rota)
    av = areas.get("avaliacao")
    if av and av.ok and av.kpis.get("a"):
        add("alta" if av.kpis.get("criticos_com_compra") else "media", "Fornecedores",
            f"{num(av.kpis['a'])} fornecedores críticos (nota até 2,0) em {av.kpis['periodo']}; "
            f"{num(av.kpis.get('criticos_com_compra', 0))} com compras, {brl_curto(av.kpis.get('valor_criticos', 0))} "
            "comprados deles.", av.rota)
    ad = areas.get("adiantamento")
    if ad and ad.ok and ad.kpis.get("saldo_mais_1_ano", 0) > 0:
        add("media", "Adiantamentos", f"{brl_curto(ad.kpis['saldo_mais_1_ano'])} de adiantamentos com saldo há mais de "
            f"1 ano (total a abater {brl_curto(ad.kpis['saldo'])}).", ad.rota)
    sv = areas.get("servicos")
    if sv and sv.ok and (sv.kpis.get("alerta_aut") or sv.kpis.get("termino_vencido")):
        add("media", "Serviços", f"{num(sv.kpis['alerta_aut'])} solicitações aguardando autorização além do alerta e "
            f"{num(sv.kpis['termino_vencido'])} em aberto com término previsto vencido.", sv.rota)
    es = areas.get("estoque")
    if es and es.ok and es.kpis.get("inativos_com_saldo"):
        add("baixa", "Estoque", f"{num(es.kpis['inativos_com_saldo'])} itens inativos ainda com saldo; "
            f"{num(es.kpis['abaixo_minimo'])} abaixo do mínimo.", es.rota)
    ca = areas.get("curva_abc")
    if ca and ca.ok and ca.kpis.get("altas_ab"):
        add("media", "Curva ABC", f"{num(ca.kpis['altas_ab'])} insumos A/B ficaram mais caros em {ca.kpis['ano']} "
            f"(efeito preço {brl_curto(ca.kpis.get('efeito_preco_ab', 0))}, mesmos detalhes).", ca.rota)
    if fontes is not None and len(fontes):
        for r in fontes[fontes["situacao"] != "ok"].itertuples():
            add("alta", "Dados", f"{r.fonte}: {r.detalhe}", r.rota)
    ordem = {"alta": 0, "media": 1, "baixa": 2}
    return sorted(p, key=lambda x: ordem[x["nivel"]])


def fontes() -> pd.DataFrame:
    """Data de posição e situação de cada fonte (para saber se os números estão atualizados)."""
    from app.repositories import rpa_repo
    from app.services import inteligencia as ig
    linhas = []

    def add(fonte, rota, fn):
        try:
            pos, sit, det = fn()
        except Exception as exc:  # noqa: BLE001
            pos, sit, det = None, "indisponível", str(exc).splitlines()[0][:120]
        linhas.append({"fonte": fonte, "rota": rota, "posicao": pos, "situacao": sit, "detalhe": det})

    def ctl(fn, col="modificado_em", completo=None):
        def _f():
            c = fn()
            if c.empty:
                return None, "sem carga", "nenhum arquivo carregado"
            if completo and completo in c and not bool(c[completo].iat[0]):
                return c[col].max(), "incompleta", "carga marcada como incompleta (página vazia/faltando)"
            if "conciliado" in c and not c["conciliado"].all():
                return c[col].max(), "divergente", "arquivo não conferiu com o total impresso"
            return c[col].max(), "ok", ""
        return _f

    def intel():
        r = ig.ultimo_processamento()
        return (r["processado_em"], "ok", "") if r else (None, "sem carga", "etapa inteligencia_compras não rodou")

    add("Compras / oportunidades (ETL)", "/", intel)
    add("Estoque", "/estoque", ctl(rpa_repo.controle_estoque, completo="carga_completa"))
    add("Contratos", "/contratos", ctl(rpa_repo.controle_contrato))
    add("SLA (painel de compras)", "/sla-insumos", ctl(rpa_repo.controle_solicitacao, completo="carga_completa"))
    add("Serviços", "/servicos", ctl(rpa_repo.controle_servico))
    add("Adiantamentos", "/adiantamento", ctl(rpa_repo.controle_adiantamento, col="posicao_em"))
    add("Avaliação de fornecedores", "/avaliacao-fornecedor", ctl(rpa_repo.controle_avaliacao, col="posicao_em"))
    add("Curva ABC", "/curva-abc", ctl(rpa_repo.controle_curva_abc, col="posicao_em"))
    f = pd.DataFrame(linhas)
    f["posicao"] = pd.to_datetime(f["posicao"], errors="coerce")
    velho = f["posicao"].notna() & (f["posicao"] < pd.Timestamp.now() - pd.Timedelta(days=3)) & (f["situacao"] == "ok")
    f.loc[velho, "situacao"] = "desatualizada"
    f.loc[velho, "detalhe"] = "última carga há mais de 3 dias"
    return f
