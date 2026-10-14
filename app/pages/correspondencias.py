"""Análise e correspondência de insumos: revisão humana do motor de similaridade e catálogo de equivalências."""
from __future__ import annotations

import json

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

from app.components.ui import brl, cabecalho, cartao, dropdown, filtro, kpi, nota, num, selo, vazio
from app.matching.config import CONFIG
from app.matching.pontuacao import perfil, pontuar
from app.pages.comparativo import F_DATA
from app.pages.oportunidades import F_BRL, F_NUM
from app.repositories import catalogo_repo as repo
from app.seguranca import sessao
from app.services import inteligencia as ig

ROTULO_STATUS = {"pendente": "Pendente", "revisar_mudanca": "Revisar (descrição mudou)", "auto_aprovado": "Automático",
                 "aprovado": "Aprovado", "rejeitado": "Rejeitado", "incompativel": "Conflito técnico",
                 "nao_comparavel": "Não comparável", "baixa": "Baixa confiança"}
VISOES = {
    "fila": ("Fila de revisão", ["pendente", "revisar_mudanca"]),
    "aprovados": ("Aprovados por pessoa", ["aprovado"]),
    "auto": ("Aprovados automaticamente", ["auto_aprovado"]),
    "rejeitados": ("Rejeitados", ["rejeitado"]),
    "conflitos": ("Conflitos técnicos", ["incompativel"]),
    "naocomp": ("Não comparáveis", ["nao_comparavel"]),
}
NOMES_COMP = {"texto": "Edição (texto)", "tokens": "Tokens", "tfidf": "TF-IDF caracteres", "atributos": "Atributos técnicos",
              "unidade": "Unidade"}

COLUNAS = [
    {"field": "valor_em_jogo", "headerName": "Valor em jogo", "width": 130, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned", "headerTooltip": "Se aprovado: diferença entre os preços medianos × volume do mais caro"},
    {"field": "score", "headerName": "Score", "width": 86, "cellClass": "num", "type": "rightAligned"},
    {"field": "nivel", "headerName": "Nível", "width": 110},
    {"field": "status_rotulo", "headerName": "Situação", "width": 150},
    {"field": "descricao_a", "headerName": "Descrição A", "minWidth": 260, "flex": 2, "tooltipField": "descricao_a"},
    {"field": "descricao_b", "headerName": "Descrição B", "minWidth": 260, "flex": 2, "tooltipField": "descricao_b"},
    {"field": "unidades", "headerName": "Un.", "width": 90},
    {"field": "categoria", "headerName": "Categoria", "minWidth": 170, "flex": 1, "tooltipField": "categoria"},
    {"field": "motivos_txt", "headerName": "Motivos", "minWidth": 240, "flex": 1, "tooltipField": "motivos_txt"},
    {"field": "decidido_por", "headerName": "Decidido por", "width": 130},
]


def layout(**_):
    try:
        cats = sorted(ig.base()["categoria"].dropna().unique())
    except Exception as exc:  # noqa: BLE001
        return html.Div([cabecalho("Correspondências", ""), vazio(f"Erro de conexão: {exc}")])
    return html.Div([
        cabecalho("Análise e correspondência de insumos",
                  "Revise o que o motor de similaridade encontrou. Decisões aprovadas passam a valer nas comparações "
                  "de preço; rejeições não voltam a ser sugeridas enquanto as descrições não mudarem.",
                  html.Div(id="co-etl-info", className="cv-nota", style={"maxWidth": 260}),
                  relatorio="co"),
        html.Div(id="co-kpis"),
        dcc.Tabs(id="co-aba", value="pares", className="adm-abas", children=[
            dcc.Tab(label="Pares", value="pares", className="adm-aba", selected_className="adm-aba-sel"),
            dcc.Tab(label="Comparar / equivalência manual", value="manual", className="adm-aba",
                    selected_className="adm-aba-sel"),
            dcc.Tab(label="Histórico de decisões", value="historico", className="adm-aba",
                    selected_className="adm-aba-sel"),
            dcc.Tab(label="Vocabulário (sinônimos e abreviações)", value="vocab", className="adm-aba",
                    selected_className="adm-aba-sel"),
        ]),
        # ── pares ──
        html.Div([
            html.Div([
                html.Div([html.Span("Visão", className="rc-chips-rot"),
                          dcc.RadioItems(id="co-visao", value="fila", className="rc-chips", inline=True,
                                         options=[{"label": html.Span(v[0], className="rc-chip"), "value": k}
                                                  for k, v in VISOES.items()])], className="rc-chips-linha"),
                html.Div([
                    filtro("Categoria", dropdown("co-categoria", [{"label": c, "value": c} for c in cats])),
                    filtro("Buscar no catálogo (descrição ou código)", dcc.Input(
                        id="co-texto", className="cv-input", debounce=True, placeholder="ex.: cimento cp ii, 1421")),
                ], className="filtros", style={"marginTop": 10}),
            ]),
            dag.AgGrid(id="co-grade", columnDefs=COLUNAS, rowData=[], className="ag-theme-quartz",
                       defaultColDef={"sortable": True, "resizable": True, "filter": True},
                       dashGridOptions={"rowSelection": {"mode": "singleRow", "checkboxes": False,
                                                         "enableClickSelection": True},
                                        "tooltipShowDelay": 300, "localeText": {"noRowsToShow": "Nada nesta visão"}},
                       style={"height": 420}),
            html.Span(id="co-grade-nota", className="cv-nota"),
            html.Div(id="co-decisao-msg", style={"marginTop": 10}),
            html.Div(cartao("Decisão", dcc.Textarea(
                id="co-obs", className="resumo-input", style={"minHeight": 60},
                placeholder="Observação (obrigatória para rejeitar)"),
                html.Div([] if sessao.pode("decidir_equivalencia") else [html.Div(
                    "Seu perfil permite consultar, mas não decidir equivalências.", className="cv-nota")],
                    style={"marginBottom": 6}),
                html.Div([html.Button("Aprovar equivalência", id="co-aprovar", className="btn btn-ok btn-p", n_clicks=0),
                          html.Button("Rejeitar", id="co-rejeitar", className="btn btn-nok btn-p", n_clicks=0),
                          html.Button("Devolver para revisão", id="co-devolver", className="btn btn-sec btn-p",
                                      n_clicks=0)], className="acoes", style={"justifyContent": "flex-start"} | (
                    {} if sessao.pode("decidir_equivalencia") else {"display": "none"}))),
                id="co-acoes", style={"display": "none", "marginTop": 14}),
            dcc.Store(id="co-par-id"),
            html.Div(id="co-detalhe", style={"marginTop": 14}),
        ], id="co-sec-pares"),
        # ── manual ──
        html.Div([
            cartao("Comparar dois insumos", html.Div([
                filtro("Buscar insumo A (palavras ou código)", dcc.Input(id="co-man-busca-a", className="cv-input",
                                                                          debounce=True, placeholder="ex.: cimento cp ii")),
                filtro("Insumo A", dcc.Dropdown(id="co-man-a", placeholder="← busque e escolha", optionHeight=40,
                                                searchable=False), "largo"),
                filtro("Buscar insumo B (palavras ou código)", dcc.Input(id="co-man-busca-b", className="cv-input",
                                                                          debounce=True, placeholder="ex.: cimento cp-ii")),
                filtro("Insumo B", dcc.Dropdown(id="co-man-b", placeholder="← busque e escolha", optionHeight=40,
                                                searchable=False), "largo"),
            ], className="filtros"), html.Div(id="co-man-resultado"),
                html.Div([dcc.Textarea(id="co-man-obs", placeholder="Justificativa (obrigatória)",
                                       className="resumo-input", style={"minHeight": 60, "marginTop": 12}),
                          html.Div([html.Button("Registrar como equivalentes", id="co-man-sim",
                                                className="btn btn-ok btn-p", n_clicks=0),
                                    html.Button("Registrar como NÃO equivalentes", id="co-man-nao",
                                                className="btn btn-nok btn-p", n_clicks=0)], className="acoes",
                                   style={"justifyContent": "flex-start"} | (
                                       {} if sessao.pode("criar_equivalencia") else {"display": "none"})),
                          html.Div(id="co-man-msg")], id="co-man-acoes", style={"display": "none"}),
                dcc.Store(id="co-man-res")),
        ], id="co-sec-manual", style={"display": "none"}),
        # ── histórico ──
        html.Div(id="co-sec-historico", style={"display": "none"}),
        # ── vocabulário ──
        html.Div([
            cartao("Adicionar ou corrigir termo", html.Div([
                filtro("Termo como aparece", dcc.Input(id="co-voc-termo", className="cv-input", placeholder="ex.: sold")),
                filtro("Significa", dcc.Input(id="co-voc-subst", className="cv-input", placeholder="ex.: soldavel")),
                filtro("Tipo", dropdown("co-voc-tipo", [{"label": "Abreviação", "value": "abreviacao"},
                                                        {"label": "Sinônimo", "value": "sinonimo"},
                                                        {"label": "Correção de digitação", "value": "correcao"}],
                                        valor="abreviacao", clearable=False), "estreito"),
                html.Div(html.Button("Salvar termo", id="co-voc-salvar", className="btn btn-pri btn-p", n_clicks=0,
                                     disabled=not sessao.pode("editar_vocabulario"),
                                     title=None if sessao.pode("editar_vocabulario") else
                                     "Seu perfil não permite editar o vocabulário"),
                         className="filtro-acoes"),
            ], className="filtros"), html.Div(id="co-voc-msg"),
                html.Span("Alterações no vocabulário valem a partir da próxima execução do ETL (etapa "
                          f"inteligencia_compras, de hora em hora · regras {CONFIG.versao}). O vocabulário padrão do "
                          "código continua valendo; termos daqui têm prioridade.", className="cv-nota")),
            html.Div(id="co-voc-lista"),
        ], id="co-sec-vocab", style={"display": "none"}),
        dcc.Store(id="co-refresh", data=0),
    ])


dash.register_page(__name__, path="/correspondencias", name="Correspondências", title="Correspondências · Suprimentos",
                   layout=layout)


# ── auxiliares ───────────────────────────────────────────────────────────────
def _valor_em_jogo(pares: pd.DataFrame) -> pd.Series:
    """Diferença entre preços medianos (mesma unidade) × volume do insumo mais caro — prioriza a revisão."""
    try:
        b = ig.base()
    except Exception:  # noqa: BLE001
        return pd.Series(0.0, index=pares.index)
    agg = b.groupby(["chave", "unidade"]).agg(med=("preco", "median"), qtd=("quantidade", "sum")).reset_index()
    agg = agg.sort_values("qtd", ascending=False).drop_duplicates("chave").set_index("chave")
    ma, mb = pares["chave_a"].map(agg["med"]), pares["chave_b"].map(agg["med"])
    ua, ub = pares["chave_a"].map(agg["unidade"]), pares["chave_b"].map(agg["unidade"])
    qa, qb = pares["chave_a"].map(agg["qtd"]), pares["chave_b"].map(agg["qtd"])
    caro_q = qa.where(ma >= mb, qb)
    v = (ma - mb).abs() * caro_q
    return v.where(ua == ub, 0.0).fillna(0.0)


def _metricas(componentes: dict):
    return html.Div([html.Div([html.Span(NOMES_COMP.get(k, k)),
                               html.Div(html.Div(className="cheio", style={"width": f"{float(v) * 100:.0f}%"}),
                                        className="trilho"),
                               html.B(f"{float(v):.2f}")], className="metrica")
                     for k, v in (componentes or {}).items()], className="metricas")


def _tabela_atributos(desc_a, desc_b, comparacao: dict, ua, ub):
    pa, pb = perfil("a", 0, desc_a, "", ua), perfil("b", 0, desc_b, "", ub)
    va, vb = pa.atributos.as_dict(), pb.atributos.as_dict()
    conflitos = {c["atributo"] for c in (comparacao or {}).get("conflitos", [])}
    emb = {c["atributo"] for c in (comparacao or {}).get("embalagem", [])}
    parc = set((comparacao or {}).get("parciais", []))
    iguais = set((comparacao or {}).get("iguais", []))
    linhas = []
    for k in sorted(set(va) | set(vb)):
        if k == "numeros" and k not in conflitos and k not in parc:
            continue
        fmt = lambda v: "—" if v is None else (", ".join(map(str, v)) if isinstance(v, list) else str(v))  # noqa: E731
        if k in conflitos:
            res = html.Span("conflito crítico", className="atr-conf")
        elif k in emb:
            res = html.Span("embalagem diferente", className="atr-parc")
        elif k in parc:
            res = html.Span("só em um lado / parcial", className="atr-parc")
        elif k in iguais:
            res = html.Span("igual", className="atr-ok")
        else:
            res = html.Span("informativo", className="muted")
        linhas.append(html.Tr([html.Td(k.replace("_", " ")), html.Td(fmt(va.get(k)), className="mono"),
                               html.Td(fmt(vb.get(k)), className="mono"), html.Td(res)]))
    return html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Atributo", "A", "B", "Resultado")])),
                       html.Tbody(linhas or [html.Tr(html.Td("Nenhum atributo técnico identificado", colSpan=4))])],
                      className="tabela"), pa, pb


def _painel_par(desc_a, desc_b, ua, ub, score, nivel, componentes, comparacao, motivos, cab_extra=None, acoes=None):
    tabela, pa, pb = _tabela_atributos(desc_a, desc_b, comparacao, ua, ub)
    return cartao(None,
                  html.Div([selo(f"score {float(score):.1f}", "info"), " ", selo(nivel, nivel), " ",
                            *(cab_extra if isinstance(cab_extra, list) else [cab_extra or ""])]),
                  html.Div([html.Div([html.Div("A", className="cv-mini-l"), html.Div(desc_a, className="par-desc"),
                                      html.Div(pa.canonico, className="par-canon"), html.Div(f"unidade: {ua or '—'}",
                                                                                            className="obs")],
                                     className="cv-mini"),
                            html.Div([html.Div("B", className="cv-mini-l"), html.Div(desc_b, className="par-desc"),
                                      html.Div(pb.canonico, className="par-canon"), html.Div(f"unidade: {ub or '—'}",
                                                                                            className="obs")],
                                     className="cv-mini")], className="par-grade", style={"margin": "12px 0"}),
                  html.Div([html.Div([html.Div("Métricas (0–1)", className="cv-mini-l"), _metricas(componentes)]),
                            html.Div([html.Div("Motivos", className="cv-mini-l"),
                                      html.Ul([html.Li(m) for m in (motivos or ["sem ressalvas"])],
                                              className="lista-motivos")])], className="par-grade"),
                  html.Div("Atributos técnicos extraídos", className="tabela-legenda", style={"marginTop": 12}),
                  tabela, acoes)


def _status_json(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


# ── callbacks ────────────────────────────────────────────────────────────────
@callback(Output("co-sec-pares", "style"), Output("co-sec-manual", "style"), Output("co-sec-historico", "style"),
          Output("co-sec-vocab", "style"), Input("co-aba", "value"))
def trocar_aba(aba):
    mostra, esconde = {"display": "block", "marginTop": 14}, {"display": "none"}
    return [mostra if aba == x else esconde for x in ("pares", "manual", "historico", "vocab")]


@callback(Output("co-kpis", "children"), Input("co-refresh", "data"))
def kpis(_):
    try:
        st = repo.contagem_status().set_index("status")["n"]
    except Exception:  # noqa: BLE001
        return vazio("Catálogo ainda não criado: rode `alembic upgrade head` no painel e a etapa "
                     "inteligencia_compras no ETL.")
    ult = repo.ultimo_processamento()
    g = lambda k: int(st.get(k, 0))  # noqa: E731
    return html.Div([
        kpi("Fila de revisão", num(g("pendente") + g("revisar_mudanca")),
            f"{num(g('revisar_mudanca'))} por mudança de descrição", "kpi-oport neutro"),
        kpi("Aprovados por pessoa", num(g("aprovado")), "reutilizados nas próximas cargas", "neutro"),
        kpi("Aprovados automaticamente", num(g("auto_aprovado")), "alta confiança, sem conflito técnico", "neutro"),
        kpi("Rejeitados", num(g("rejeitado")), "não voltam a ser sugeridos", "neutro"),
        kpi("Conflitos técnicos", num(g("incompativel")), "textos parecidos, especificação diferente", "neutro"),
        kpi("Último processamento", ult["fim"].strftime("%d/%m/%Y %H:%M") if ult and ult.get("fim") is not None else "—",
            f"regras {CONFIG.versao}", "neutro"),
    ], className="port-kpi-grid", style={"marginBottom": 8})


@callback(Output("co-etl-info", "children"), Input("co-refresh", "data"))
def info_etl(_):
    """O catálogo é processado no ETL (antes: botão 'Reprocessar' aqui)."""
    ult = repo.ultimo_processamento()
    quando = ult["fim"].strftime("%d/%m/%Y %H:%M") if ult and ult.get("fim") is not None else "ainda não processado"
    return [html.B("Catálogo processado pelo ETL: "), quando, html.Br(),
            "Decisões e termos novos entram nas comparações de preço na próxima execução (de hora em hora)."]


@callback(Output("co-grade", "rowData"), Output("co-grade-nota", "children"), Input("co-visao", "value"),
          Input("co-categoria", "value"), Input("co-texto", "value"), Input("co-refresh", "data"))
def listar(visao, categoria, texto, _):
    status = VISOES.get(visao, VISOES["fila"])[1]
    try:
        df = repo.listar_pares(status=status, categoria=categoria, texto=texto, limite=3000)
    except Exception as exc:  # noqa: BLE001
        return [], f"Erro: {exc}"
    if visao == "conflitos":
        df = df[df["score"] >= 60]   # textualmente parecidos: são as ambiguidades que importam
    if df.empty:
        return [], "Nada nesta visão."
    df["valor_em_jogo"] = _valor_em_jogo(df)
    df = df.sort_values(["valor_em_jogo", "score"], ascending=False) if visao == "fila" else df
    df["status_rotulo"] = df["status"].map(ROTULO_STATUS)
    df["unidades"] = df["unidade_a"].fillna("?") + " / " + df["unidade_b"].fillna("?")
    df["motivos_txt"] = df["motivos"].map(lambda m: "; ".join(_status_json(m) or []))
    df["decidido_em"] = df["decidido_em"].astype(str)
    ordem = "maior valor em jogo primeiro" if visao == "fila" else "maior score primeiro"
    return df.head(1500).to_dict("records"), f"{num(min(len(df), 1500))} de {num(len(df))} pares ({ordem})."


@callback(Output("co-detalhe", "children"), Output("co-par-id", "data"), Output("co-obs", "value"),
          Output("co-acoes", "style"), Input("co-grade", "selectedRows"), Input("co-refresh", "data"))
def detalhe(linhas, _):
    esconde = {"display": "none"}
    if not linhas:
        return vazio("Selecione um par para ver métricas, atributos e decidir."), None, "", esconde
    par = repo.detalhe_par(int(linhas[0]["id"]))
    if not par:
        return vazio("Par não encontrado."), None, "", esconde
    hist = repo.historico(int(par["id"]))
    acoes = html.Div([
        html.Div("Histórico deste par", className="tabela-legenda", style={"marginTop": 12}),
        html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Quando", "Quem", "De", "Para", "Observação", "Regras")])),
                    html.Tbody([html.Tr([html.Td(pd.Timestamp(h.quando).strftime("%d/%m/%Y %H:%M")), html.Td(h.usuario),
                                         html.Td(ROTULO_STATUS.get(h.status_anterior, h.status_anterior or "—")),
                                         html.Td(ROTULO_STATUS.get(h.status_novo, h.status_novo)),
                                         html.Td(h.observacao or ""), html.Td(h.versao_regras)])
                                for h in hist.itertuples()] or [html.Tr(html.Td("Sem decisões registradas", colSpan=6))])],
                   className="tabela"),
    ])
    extra = [selo(ROTULO_STATUS.get(par["status"], par["status"]), par["status"]),
             html.Span(f"  método: {par['metodo']} · regras {par['versao_regras']}", className="obs")]
    painel = _painel_par(par["descricao_a"], par["descricao_b"], par["unidade_a"], par["unidade_b"], par["score"],
                         par["nivel"], _status_json(par["componentes"]), _status_json(par["comparacao"]),
                         _status_json(par["motivos"]), extra, acoes)
    return painel, int(par["id"]), par.get("observacao") or "", {"display": "block"}


@callback(Output("co-decisao-msg", "children"), Output("co-refresh", "data", allow_duplicate=True),
          Input("co-aprovar", "n_clicks"), Input("co-rejeitar", "n_clicks"), Input("co-devolver", "n_clicks"),
          State("co-par-id", "data"), State("co-obs", "value"), State("co-refresh", "data"), prevent_initial_call=True)
def decidir(_a, _r, _d, par_id, obs, ref):
    status = {"co-aprovar": "aprovado", "co-rejeitar": "rejeitado", "co-devolver": "pendente"}.get(ctx.triggered_id)
    if not status or not par_id:
        return no_update, no_update
    if status == "rejeitado" and not (obs or "").strip():
        return html.Div("Informe o motivo da rejeição na observação.", className="adm-msg erro"), no_update
    u = sessao.exigir("decidir_equivalencia")
    repo.decidir(int(par_id), status, u.login, (obs or "").strip() or None)
    return (html.Div(f"Decisão registrada ({ROTULO_STATUS[status]}) por {u.login}. Os grupos de material e as "
                     "oportunidades são atualizados na próxima execução do ETL (de hora em hora).",
                     className="adm-msg ok"), (ref or 0) + 1)


# ── comparação manual ────────────────────────────────────────────────────────
def _buscar_insumos(texto: str):
    """Todas as palavras da busca (normalizadas, sem acento) precisam aparecer; ou código do insumo."""
    if not texto or len(texto.strip()) < 2:
        return []
    from app.matching.normalizacao import canonico
    try:
        perf = repo.perfis_salvos()
    except Exception:  # noqa: BLE001
        return []
    t = texto.strip()
    if t.split("|")[0].isdigit():
        m = perf[perf["chave"].str.startswith(t.split("|")[0] + "|")]
    else:
        palavras = canonico(t).split()
        m = perf
        for w in palavras:
            m = m[m["descricao_canonica"].str.contains(rf"\b{w}", regex=True)]
    return [{"label": f"{r.descricao_original[:90]}  ·  cód. {r.chave}  ·  {r.unidade}", "value": r.chave}
            for r in m.head(60).itertuples()]


@callback(Output("co-man-a", "options"), Input("co-man-busca-a", "value"), prevent_initial_call=True)
def busca_a(texto):
    return _buscar_insumos(texto)


@callback(Output("co-man-b", "options"), Input("co-man-busca-b", "value"), prevent_initial_call=True)
def busca_b(texto):
    return _buscar_insumos(texto)


@callback(Output("co-man-res", "data"), Output("co-man-acoes", "style"), Output("co-man-resultado", "children"),
          Input("co-man-a", "value"), Input("co-man-b", "value"))
def comparar_manual(a, b):
    esconde = {"display": "none"}
    if not a or not b:
        return None, esconde, html.Span("Escolha dois insumos para ver a pontuação, os atributos e registrar uma "
                                        "decisão manual.", className="cv-nota")
    if a == b:
        return None, esconde, vazio("Escolha insumos diferentes.")
    perf = repo.perfis_salvos([a, b]).set_index("chave")
    ra, rb = perf.loc[a], perf.loc[b]
    voc = repo.carregar_vocabulario()
    pa = perfil(a, ra.id_insumo, ra.descricao_original, ra.categoria, ra.unidade, voc)
    pb = perfil(b, rb.id_insumo, rb.descricao_original, rb.categoria, rb.unidade, voc)
    res = pontuar(pa, pb).as_dict()
    aviso = (html.Div("O motor encontrou CONFLITO TÉCNICO. Aprovar mesmo assim exige justificativa e fica registrado.",
                      className="adm-msg erro") if res["nivel"] == "incompativel" else None)
    acoes = html.Div([aviso])
    return res, {"display": "block"}, _painel_par(pa.descricao, pb.descricao, pa.unidade, pb.unidade, res["score"], res["nivel"],
                       res["componentes"], res["comparacao"], res["motivos"],
                       html.Span("  (cálculo na hora, versão das regras " + CONFIG.versao + ")", className="obs"), acoes)


@callback(Output("co-man-msg", "children"), Output("co-refresh", "data", allow_duplicate=True),
          Input("co-man-sim", "n_clicks"), Input("co-man-nao", "n_clicks"), State("co-man-a", "value"),
          State("co-man-b", "value"), State("co-man-obs", "value"), State("co-man-res", "data"),
          State("co-refresh", "data"), prevent_initial_call=True)
def registrar_manual(_s, _n, a, b, obs, res, ref):
    status = {"co-man-sim": "aprovado", "co-man-nao": "rejeitado"}.get(ctx.triggered_id)
    if not status or not res or not a or not b:
        return no_update, no_update
    if not (obs or "").strip():
        return html.Div("Justificativa obrigatória.", className="adm-msg erro"), no_update
    u = sessao.exigir("criar_equivalencia")
    perf = repo.perfis_salvos([a, b]).set_index("chave")
    pa = perfil(a, perf.loc[a].id_insumo, perf.loc[a].descricao_original, perf.loc[a].categoria, perf.loc[a].unidade)
    pb = perfil(b, perf.loc[b].id_insumo, perf.loc[b].descricao_original, perf.loc[b].categoria, perf.loc[b].unidade)
    repo.criar_par_manual(pa, pb, res, u.login, obs.strip(), status)
    return html.Div(f"Registrado como {ROTULO_STATUS[status].lower()}. Vale nas comparações de preço a partir da "
                    "próxima execução do ETL.", className="adm-msg ok"), (ref or 0) + 1


# ── histórico e vocabulário ──────────────────────────────────────────────────
@callback(Output("co-sec-historico", "children"), Input("co-aba", "value"), Input("co-refresh", "data"))
def historico(aba, _):
    if aba != "historico":
        return no_update
    h = repo.historico(limite=1000)
    if h.empty:
        return vazio("Nenhuma decisão registrada ainda.")
    h = h.assign(quando=pd.to_datetime(h["quando"]).dt.strftime("%Y-%m-%d %H:%M"),
                 de=h["status_anterior"].map(ROTULO_STATUS).fillna("—"), para=h["status_novo"].map(ROTULO_STATUS))
    return cartao("Últimas 1.000 decisões", dag.AgGrid(
        rowData=h.to_dict("records"), className="ag-theme-quartz", style={"height": 520},
        defaultColDef={"sortable": True, "resizable": True, "filter": True},
        csvExportParams={"fileName": "decisoes_equivalencia.csv", "columnSeparator": ";"},
        columnDefs=[{"field": "quando", "headerName": "Quando", "width": 140}, {"field": "usuario", "headerName": "Quem",
                                                                                 "width": 130},
                    {"field": "de", "headerName": "De", "width": 150}, {"field": "para", "headerName": "Para", "width": 150},
                    {"field": "descricao_a", "headerName": "Descrição A", "flex": 2, "tooltipField": "descricao_a"},
                    {"field": "descricao_b", "headerName": "Descrição B", "flex": 2, "tooltipField": "descricao_b"},
                    {"field": "observacao", "headerName": "Observação", "flex": 1, "tooltipField": "observacao"},
                    {"field": "versao_regras", "headerName": "Regras", "width": 100}]))


@callback(Output("co-voc-lista", "children"), Output("co-voc-msg", "children"), Input("co-voc-salvar", "n_clicks"),
          Input("co-aba", "value"), State("co-voc-termo", "value"), State("co-voc-subst", "value"),
          State("co-voc-tipo", "value"))
def vocabulario(n, aba, termo, subst, tipo):
    msg = None
    if ctx.triggered_id == "co-voc-salvar" and n:
        if not (termo or "").strip() or not (subst or "").strip():
            msg = html.Div("Preencha o termo e o significado.", className="adm-msg erro")
        else:
            u = sessao.exigir("editar_vocabulario")
            repo.salvar_termo(termo, subst, tipo, u.login)
            msg = html.Div("Termo salvo. Vale a partir da próxima execução do ETL (de hora em hora).",
                           className="adm-msg ok")
    if aba != "vocab" and msg is None:
        return no_update, no_update
    v = repo.listar_vocabulario()
    from app.matching.normalizacao import VOCABULARIO_PADRAO
    padrao = pd.DataFrame({"termo": list(VOCABULARIO_PADRAO), "substituto": list(VOCABULARIO_PADRAO.values()),
                           "tipo": "padrão do sistema", "ativo": True, "criado_por": "—"})
    tudo = pd.concat([v.assign(tipo=v["tipo"]) if len(v) else v, padrao], ignore_index=True)
    return cartao(f"Vocabulário em uso ({num(len(tudo))} termos)", dag.AgGrid(
        rowData=tudo[["termo", "substituto", "tipo", "ativo", "criado_por"]].to_dict("records"),
        className="ag-theme-quartz", style={"height": 420}, defaultColDef={"sortable": True, "filter": True,
                                                                           "resizable": True, "flex": 1},
        columnDefs=[{"field": c, "headerName": h} for c, h in (("termo", "Termo"), ("substituto", "Significa"),
                                                               ("tipo", "Tipo"), ("ativo", "Ativo"),
                                                               ("criado_por", "Criado por"))])), msg


# ── Relatório em PowerPoint (botão "Gerar relatório") ────────────────────────
@callback(Output("co-rel-down", "data"), Input("co-rel", "n_clicks"),
          State("co-visao", "value"),
          State("co-categoria", "value"),
          State("co-texto", "value"), prevent_initial_call=True)
def gerar_relatorio(n, visao, categoria, texto):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    return dcc.send_bytes(rel.correspondencias(visao, categoria, texto), nome_arquivo("correspondencias"))
