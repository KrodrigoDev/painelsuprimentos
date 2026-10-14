"""SLA de insumos: prazos de compra (solicitação → pedido) e de entrega (pedido → obra), gargalos e backlog."""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from app.components import detalhe, graficos
from app.components.ui import cabecalho, cartao, dropdown, filtro, kpi, nota, num, pct, periodo, vazio
from app.pages.oportunidades import F_PCT
from app.repositories import rpa_repo
from app.services import configuracoes as cf
from app.services import sla

P = "sla-dm"
F_DATA = {"function": "params.value ? new Date(params.value).toLocaleDateString('pt-BR', {timeZone: 'UTC'}) : ''"}
F_DIAS = {"function": "params.value == null ? '' : Math.round(params.value) + ' d'"}


def _c(campo, rotulo, formato="texto", total=False, peso=None):
    d = {"campo": campo, "rotulo": rotulo, "formato": formato, "total": total}
    if peso:
        d["peso"] = peso
    return d


_PREP: dict = {}


def base() -> pd.DataFrame:
    """Prepara (prazos vigentes × dias do ETL) uma vez por carga/edição; o escopo é aplicado a cada chamada."""
    bruta, prazos, risco = rpa_repo.sla_bruto(), cf.prazos_sla(), cf.parametro("sla.em_risco_pct")
    chave = (id(bruta), id(prazos), risco)
    if _PREP.get("chave") != chave or _PREP.get("bruta") is not bruta:
        _PREP.update(chave=chave, bruta=bruta, pronta=sla.preparar(bruta, prazos, risco))
    return rpa_repo.escopar_sla(_PREP["pronta"])


def _fonte():
    try:
        ctl = rpa_repo.controle_solicitacao()
    except Exception:  # noqa: BLE001
        return None, None
    if ctl.empty:
        return None, None
    pos = ctl["modificado_em"].max()
    fonte = html.Div([html.Div(f"painel de compras do Sienge de {pos:%d/%m/%Y %H:%M}"),
                      html.Div(f"{len(ctl)} arquivo(s) · {num(int(ctl['linhas'].sum()))} linhas")])
    aviso = None
    if not bool(ctl["carga_completa"].iat[0]):
        susp = ", ".join(ctl.loc[ctl["suspeita_incompleta"], "arquivo"])
        aviso = html.Div([html.B("Carga possivelmente incompleta: "),
                          f"{susp} — a última página do ano veio cheia (5.000 linhas) ou falta página. Rode de novo o "
                          "extract do painel de compras no projeto legado."], className="alerta-carga")
    return fonte, aviso


def _opcoes(serie_val, serie_rot=None):
    d = pd.DataFrame({"v": serie_val, "l": serie_rot if serie_rot is not None else serie_val}).dropna(subset=["v"])
    d = d.drop_duplicates("v").sort_values("l")
    num_ = pd.api.types.is_numeric_dtype(d["v"])
    return [{"label": str(r.l), "value": int(r.v) if num_ else str(r.v)} for r in d.itertuples()]


def layout(**_):
    try:
        b = base()
    except Exception as exc:  # noqa: BLE001
        return html.Div([cabecalho("SLA - Insumos", ""),
                         vazio("Tabela suprimentos.fato_sla_item indisponível. Rode a DAG etl_suprimentos_rpa (task "
                               f"sla_insumo) ou python main.py --etapa sla_insumo. Detalhe: {str(exc).splitlines()[0]}")])
    if b.empty:
        return html.Div([cabecalho("SLA - Insumos", ""), vazio("Nenhum item no seu escopo de acesso.")])
    fonte, aviso = _fonte()
    fim = b["data_solicitacao"].max()
    ini = pd.Timestamp(fim.year, 1, 1) if pd.notna(fim) else None
    filtros = html.Div([
        filtro("Data da solicitação", periodo("sla-periodo", ini.date() if ini is not None else None,
                                              fim.date() if pd.notna(fim) else None), "largo"),
        filtro("Obra", dropdown("sla-obras", _opcoes(b["cod_obra"], b["obra_rotulo"]), multi=True), "largo"),
        filtro("Segmento", dropdown("sla-segmentos", _opcoes(b["segmento"]), multi=True)),
        filtro("Grupo de insumo", dropdown("sla-grupos", _opcoes(b["id_grupo"], b["grupo_insumo"]), multi=True), "largo"),
        filtro("Tipo de grupo", dropdown("sla-tipos", _opcoes(b["tipo_grupo"]), multi=True)),
        filtro("Analista", dropdown("sla-analistas", _opcoes(b["analista"]), multi=True)),
        filtro("Comprador", dropdown("sla-compradores", _opcoes(b["comprador"]), multi=True)),
        filtro("Curva ABC do grupo", dropdown("sla-curvas", _opcoes(b["curva_abc_grupo"]), multi=True), "estreito"),
        filtro("Situação da solicitação", dropdown("sla-sitsol", _opcoes(b["situacao_solicitacao"]), multi=True)),
        filtro("Situação do pedido", dropdown("sla-sitped", _opcoes(b["situacao_pedido"]), multi=True)),
        filtro("Insumo ou nº da solicitação", dcc.Input(id="sla-texto", debounce=True, className="cv-input",
                                                        placeholder="ex.: cimento, 84564"), "largo"),
    ], className="filtros")
    contar = cf.parametro("sla.contar_abertos")
    return html.Div([
        cabecalho("SLA - Insumos", "Prazo de compra (autorização da solicitação → pedido) e de entrega (pedido → "
                  "entrega completa na obra) por grupo de insumo, com o backlog que já estourou e onde o tempo é gasto.",
                  fonte, relatorio="sla"),
        aviso, filtros,
        dcc.Loading(html.Div(id="sla-conteudo"), type="dot", color="#1B365D"),
        nota(html.B("Como ler: "), "fonte = painel de compras do Sienge exportado pelo RPA. Fase 1 conta cada ITEM uma "
             "vez (até o 1º pedido); fase 2 conta cada pedido do item até a ÚLTIMA entrega (entrega parcial = ainda em "
             "aberto). Prazos por grupo vêm da planilha de Suprimentos e podem ser alterados em Configurações — a "
             "mudança vale na hora. " + ("Itens em aberto que já passaram do prazo CONTAM como não atendidos "
             "(o Power BI ignorava o que ainda não tinha pedido/entrega). " if contar else
             "Só itens concluídos entram no % (como o Power BI). ") +
             "‘Em risco’ = em aberto com idade a partir de " + f"{cf.parametro('sla.em_risco_pct')}% do prazo. "
             "Dias corridos."),
        *detalhe.modal(P),
    ])


dash.register_page(__name__, path="/sla-insumos", name="SLA - Insumos", title="SLA - Insumos · Suprimentos",
                   layout=layout)
detalhe.registrar(P)

ENTRADAS = [Input("sla-periodo", "start_date"), Input("sla-periodo", "end_date"), Input("sla-obras", "value"),
            Input("sla-grupos", "value"), Input("sla-tipos", "value"), Input("sla-analistas", "value"),
            Input("sla-compradores", "value"), Input("sla-segmentos", "value"), Input("sla-curvas", "value"),
            Input("sla-sitsol", "value"), Input("sla-sitped", "value"), Input("sla-texto", "value")]


def dados(*f) -> pd.DataFrame:
    return sla.filtrar(base(), *f)


def _kpis_fase(fase: str, r: dict, contar: bool):
    titulo = "Fase 1 · Solicitação → Pedido" if fase == "f1" else "Fase 2 · Pedido → Entrega"

    def k(chave, *a, **kw):
        return detalhe.kpi_clicavel({"type": "sla-kpi", "k": f"{fase}:{chave}"}, kpi(*a, **kw))

    nao = r["nao_atendidos"] + (r["atrasados_abertos"] if contar else 0)
    return html.Div([
        html.Div(titulo, className="sla-fase-titulo"),
        html.Div([
            k("base", "Itens com SLA mensurável", num(r["base_pct"]),
              f"{num(r['mensuraveis'])} concluídos" + (f" + {num(r['atrasados_abertos'])} em aberto vencidos"
                                                        if contar else ""), "neutro"),
            k("atendidos", "SLA atendido", num(r["atendidos"]), pct(r["pct"], 1), "destaque"),
            k("nao", "SLA não atendido", num(nao), pct(100 - r["pct"], 1) if r["base_pct"] else "—",
              "alerta" if nao else "neutro"),
            k("atrasados", "Em aberto já vencidos", num(r["atrasados_abertos"]),
              f"{num(r['em_risco'])} em risco · {num(r['abertos_no_prazo'])} no prazo", "neutro"),
            k("tempo", "Real × prazo (dias)", f"{num(r['mediana_dias'])} | {num(r['prazo_medio'])}",
              f"mediana real | prazo médio · média {num(r['media_dias'], 1)} · 80% até {num(r['p80_dias'])}",
              "neutro"),
        ], className="port-kpi-grid", style={"gridTemplateColumns": "repeat(5, minmax(0, 1fr))"}),
    ], style={"marginBottom": 12})


@callback(Output("sla-conteudo", "children"), *ENTRADAS)
def atualizar(*filtros):
    d = dados(*filtros)
    if d.empty:
        return vazio("Nenhum item com os filtros atuais.")
    contar = cf.parametro("sla.contar_abertos")
    r1, r2 = sla.resumo_fase(d, "f1", contar), sla.resumo_fase(d, "f2", contar)
    ent = d[d["atraso_obra"].notna()]
    apos_obra = int((ent["atraso_obra"] > 0).sum())
    forn = d[d["atraso_fornecedor"].notna()]
    forn_atr = int((forn["atraso_fornecedor"] > 0).sum())
    sem = d[d["f1"].eq("sem_prazo") | d["f2"].eq("sem_prazo")]

    def k(chave, *a, **kw):
        return detalhe.kpi_clicavel({"type": "sla-kpi", "k": chave}, kpi(*a, **kw))

    extras = html.Div([
        k("obra", "Entregue depois da data pedida pela obra", pct(apos_obra / len(ent) * 100 if len(ent) else 0, 1),
          f"{num(apos_obra)} de {num(len(ent))} entregas completas · mediana {num(ent['atraso_obra'].median())} d",
          "alerta" if apos_obra else "neutro"),
        k("fornecedor", "Fornecedor atrasou vs previsão do pedido", pct(forn_atr / len(forn) * 100 if len(forn) else 0, 1),
          f"{num(forn_atr)} de {num(len(forn))} · atraso mediano {num(forn.loc[forn['atraso_fornecedor'] > 0, 'atraso_fornecedor'].median())} d",
          "neutro"),
        k("sem_prazo", "Grupos sem prazo configurado", num(sem["grupo_insumo"].nunique()),
          f"{num(len(sem))} linhas fora do cálculo · ajuste em Configurações", "neutro"),
    ], className="port-kpi-grid", style={"gridTemplateColumns": "repeat(3, minmax(0, 1fr))", "marginBottom": 14})

    frases = sla.gargalos(d, contar)
    cfg = {"displaylogo": False}
    gargalo = html.Div([
        cartao("Onde está o gargalo", html.Ul([html.Li(f) for f in frases] or [html.Li("Sem dados suficientes.")],
                                              className="lista-motivos"),
               dcc.Graph(figure=graficos.etapas_sla(sla.etapas(d)), config=cfg),
               html.Span("Mediana de cada etapa (barra) e o tempo em que 80% dos itens terminam (traço vermelho). "
                         "Aprovação e autorização são tempos internos; compra é o SLA da fase 1; entrega do fornecedor "
                         "vai da autorização do pedido à última entrega.", className="cv-nota"), classe="grafico-card"),
        cartao("% no prazo por mês da solicitação", dcc.Graph(figure=graficos.sla_mensal(sla.mensal(d, contar)),
                                                               config=cfg),
               html.Span("Meses recentes ainda têm muitos itens em aberto dentro do prazo, que não entram no % — "
                         "o percentual desses meses tende a cair até as compras/entregas terminarem.",
                         className="cv-nota"), classe="grafico-card"),
    ], className="cv-grid", style={"gridTemplateColumns": "minmax(0,1fr) minmax(0,1fr)"})

    tabela = cartao("SLA por", html.Div([
        dcc.RadioItems(id="sla-dim", value="grupo_insumo", inline=True, className="rc-chips",
                       options=[{"label": html.Span(v, className="rc-chip"), "value": k_} for k_, v in
                                sla.DIMENSOES.items()]),
    ], className="rc-chips-linha"), html.Div(id="sla-tabela"))

    atr = sla.abertos_atrasados(d)
    lista = cartao(f"Em aberto já fora do prazo ({num(len(atr))})", dag.AgGrid(
        id="sla-atrasados", rowData=_linhas_atrasados(atr.head(2000)), className="ag-theme-quartz",
        columnDefs=[{"field": "fase", "headerName": "Fase", "width": 170, "pinned": "left"},
                    {"field": "cod_solicitacao", "headerName": "Solicitação", "width": 110},
                    {"field": "cod_pedido", "headerName": "Pedido", "width": 95},
                    {"field": "insumo", "headerName": "Insumo", "flex": 2, "minWidth": 240, "tooltipField": "insumo"},
                    {"field": "grupo_insumo", "headerName": "Grupo", "minWidth": 180, "tooltipField": "grupo_insumo"},
                    {"field": "obra_rotulo", "headerName": "Obra", "minWidth": 180, "tooltipField": "obra_rotulo"},
                    {"field": "comprador", "headerName": "Comprador", "width": 150},
                    {"field": "fornecedor", "headerName": "Fornecedor", "minWidth": 180, "tooltipField": "fornecedor"},
                    {"field": "dias_em_aberto", "headerName": "Em aberto", "width": 105, "valueFormatter": F_DIAS,
                     "cellClass": "num", "type": "rightAligned"},
                    {"field": "prazo", "headerName": "Prazo", "width": 90, "valueFormatter": F_DIAS, "cellClass": "num",
                     "type": "rightAligned"},
                    {"field": "dias_alem_prazo", "headerName": "Além do prazo", "width": 125, "valueFormatter": F_DIAS,
                     "cellClass": "num", "type": "rightAligned", "sort": "desc"}],
        defaultColDef={"sortable": True, "resizable": True, "filter": True}, style={"height": 420},
        dashGridOptions={"tooltipShowDelay": 300, "animateRows": False}),
        html.Span("Backlog para cobrar: itens sem pedido além do prazo de compra e pedidos sem entrega completa além do "
                  "prazo de entrega (mostra até 2.000; a decomposição dos cards exporta todos).", className="cv-nota"))
    return [_kpis_fase("f1", r1, contar), _kpis_fase("f2", r2, contar), extras, gargalo, tabela, lista]


def _linhas_atrasados(a: pd.DataFrame) -> list[dict]:
    cols = ["fase", "cod_solicitacao", "cod_pedido", "insumo", "grupo_insumo", "obra_rotulo", "comprador", "fornecedor",
            "dias_em_aberto", "prazo", "dias_alem_prazo"]
    return a[cols].astype(object).where(a[cols].notna(), None).to_dict("records")


COL_DIM = [
    {"field": "n_f1", "headerName": "Itens F1", "width": 95, "cellClass": "num", "type": "rightAligned"},
    {"field": "mediana_f1", "headerName": "Mediana F1", "width": 105, "valueFormatter": F_DIAS, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "prazo_f1", "headerName": "Prazo F1", "width": 95, "valueFormatter": F_DIAS, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "pct_f1", "headerName": "% no prazo F1", "width": 120, "valueFormatter": F_PCT, "cellClass": "num",
     "type": "rightAligned", "cellStyle": {"function": "params.value != null && params.value < 70 ? {color: '#B42318', fontWeight: 600} : {}"}},
    {"field": "atrasados_f1", "headerName": "Vencidos F1", "width": 105, "cellClass": "num", "type": "rightAligned"},
    {"field": "n_f2", "headerName": "Pedidos F2", "width": 100, "cellClass": "num", "type": "rightAligned"},
    {"field": "mediana_f2", "headerName": "Mediana F2", "width": 105, "valueFormatter": F_DIAS, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "prazo_f2", "headerName": "Prazo F2", "width": 95, "valueFormatter": F_DIAS, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "pct_f2", "headerName": "% no prazo F2", "width": 120, "valueFormatter": F_PCT, "cellClass": "num",
     "type": "rightAligned", "cellStyle": {"function": "params.value != null && params.value < 70 ? {color: '#B42318', fontWeight: 600} : {}"}},
    {"field": "atrasados_f2", "headerName": "Vencidos F2", "width": 105, "cellClass": "num", "type": "rightAligned"},
    {"field": "pct_entregue_apos_obra", "headerName": "Após data da obra", "width": 140, "valueFormatter": F_PCT,
     "cellClass": "num", "type": "rightAligned"},
    {"field": "atraso_obra_mediano", "headerName": "Atraso p/ obra (med.)", "width": 155, "valueFormatter": F_DIAS,
     "cellClass": "num", "type": "rightAligned"},
]


@callback(Output("sla-tabela", "children"), Input("sla-dim", "value"), *[State(i.component_id, i.component_property)
                                                                         for i in ENTRADAS])
def tabela_dim(dim, *filtros):
    d = dados(*filtros)
    t = sla.por(d, dim or "grupo_insumo", cf.parametro("sla.contar_abertos"))
    if t.empty:
        return vazio("Sem dados.")
    cols = [{"field": dim, "headerName": sla.DIMENSOES[dim], "minWidth": 240, "flex": 2, "pinned": "left",
             "tooltipField": dim}] + COL_DIM
    return dag.AgGrid(rowData=t.round(1).astype(object).where(t.notna(), None).to_dict("records"), columnDefs=cols,
                      className="ag-theme-quartz", style={"height": 420},
                      defaultColDef={"sortable": True, "resizable": True, "filter": True},
                      dashGridOptions={"tooltipShowDelay": 300})


# ── decomposição dos cards ───────────────────────────────────────────────────
COLS_ITENS = [_c("cod_solicitacao", "Solicitação", peso=0.8), _c("cod_pedido", "Pedido", peso=0.7),
              _c("insumo", "Insumo", peso=3), _c("grupo_insumo", "Grupo", peso=2), _c("obra_rotulo", "Obra", peso=2),
              _c("comprador", "Comprador", peso=1.3)]


def _decompor(chave: str, d: pd.DataFrame):
    contar = cf.parametro("sla.contar_abertos")
    if ":" in chave:
        fase, k = chave.split(":")
        dias, prazo, idade = (("dias_fase1", "lt_fase1", "idade_fase1") if fase == "f1"
                              else ("dias_fase2", "lt_fase2", "idade_fase2"))
        nome = "Fase 1 (solicitação → pedido)" if fase == "f1" else "Fase 2 (pedido → entrega)"
        s = d[fase]
        filtro_ = {"base": s.isin(["no_prazo", "fora_prazo"] + (["atrasado"] if contar else [])),
                   "atendidos": s.eq("no_prazo"),
                   "nao": s.isin(["fora_prazo"] + (["atrasado"] if contar else [])),
                   "atrasados": s.isin(["atrasado", "em_risco"]), "tempo": s.isin(["no_prazo", "fora_prazo"])}[k]
        sub = d[filtro_].assign(situacao=lambda x: x[fase].map(sla.ROTULO), dias_=lambda x: x[dias].fillna(x[idade]))
        sub = sub.assign(excesso=sub["dias_"] - sub[prazo]).sort_values("excesso", ascending=False)
        cols = COLS_ITENS + [_c("situacao", "Situação", peso=1.4), _c("dias_", "Dias", "int", peso=0.6),
                             _c(prazo, "Prazo", "int", peso=0.6), _c("excesso", "Além do prazo", "int", peso=0.8)]
        titulos = {"base": "Itens com SLA mensurável", "atendidos": "SLA atendido", "nao": "SLA não atendido",
                   "atrasados": "Em aberto vencidos ou em risco", "tempo": "Real × prazo"}
        return f"{titulos[k]} — {nome}", f"{num(len(sub))} linha(s)", sub, cols
    if chave == "obra":
        sub = d[d["atraso_obra"].notna()].sort_values("atraso_obra", ascending=False)
        cols = COLS_ITENS + [_c("data_necessidade", "Obra pediu para", "data"),
                             _c("data_ultima_entrega", "Entregue em", "data"), _c("atraso_obra", "Dias de atraso", "int")]
        return "Entrega × data pedida pela obra", f"{num(len(sub))} entrega(s) completa(s)", sub, cols
    if chave == "fornecedor":
        sub = d[d["atraso_fornecedor"].notna()]
        sub = (sub.groupby("fornecedor").agg(entregas=("atraso_fornecedor", "size"),
                                             atrasadas=("atraso_fornecedor", lambda s: int((s > 0).sum())),
                                             atraso_mediano=("atraso_fornecedor", "median"),
                                             prazo_entrega_mediano=("dias_fase2", "median")).reset_index())
        sub["pct_atrasadas"] = sub["atrasadas"] / sub["entregas"] * 100
        sub = sub.sort_values(["atrasadas", "pct_atrasadas"], ascending=False)
        cols = [_c("fornecedor", "Fornecedor", peso=3), _c("entregas", "Entregas", "int", True),
                _c("atrasadas", "Atrasadas", "int", True), _c("pct_atrasadas", "% atrasadas", "pct"),
                _c("atraso_mediano", "Atraso mediano (d)", "num"), _c("prazo_entrega_mediano", "Pedido→entrega (med.)", "num")]
        return "Pontualidade dos fornecedores (vs previsão do pedido)", f"{num(len(sub))} fornecedor(es)", sub, cols
    if chave == "sem_prazo":
        sub = (d[d["f1"].eq("sem_prazo") | d["f2"].eq("sem_prazo")].groupby(["id_grupo", "grupo_insumo"])
               .size().rename("linhas").reset_index().sort_values("linhas", ascending=False))
        return ("Grupos sem prazo configurado", "defina o prazo em Configurações → SLA de insumos", sub,
                [_c("id_grupo", "Código", peso=0.6), _c("grupo_insumo", "Grupo", peso=3), _c("linhas", "Linhas", "int", True)])
    return None


@callback(*detalhe.saidas(P), Input({"type": "sla-kpi", "k": ALL}, "n_clicks"),
          *[State(i.component_id, i.component_property) for i in ENTRADAS], prevent_initial_call=True)
def abrir_decomposicao(_c_, *filtros):
    if not ctx.triggered or not ctx.triggered[0].get("value") or not isinstance(ctx.triggered_id, dict):
        return (no_update,) * 5
    r = _decompor(ctx.triggered_id["k"], dados(*filtros))
    if r is None:
        return (no_update,) * 5
    return detalhe.abrir(*r)


@callback(Output("sla-rel-down", "data"), Input("sla-rel", "n_clicks"),
          *[State(i.component_id, i.component_property) for i in ENTRADAS], prevent_initial_call=True)
def gerar_relatorio(n, *filtros):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    nomes = ["obra", "grupo", "tipo", "analista", "comprador", "segmento", "curva", "situação sol.", "situação ped.",
             "busca"]
    ativos = [n_ for n_, v in zip(nomes, filtros[2:]) if v]
    per = f"{pd.Timestamp(filtros[0]):%d/%m/%Y} a {pd.Timestamp(filtros[1]):%d/%m/%Y}" if filtros[0] and filtros[1] else ""
    txt = " · ".join([x for x in [per, ", ".join(ativos)] if x]) or "sem filtros"
    return dcc.send_bytes(rel.sla_insumos(dados(*filtros), txt, cf.parametro("sla.contar_abertos")),
                          nome_arquivo("sla_insumos"))
