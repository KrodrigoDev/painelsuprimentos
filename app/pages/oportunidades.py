"""Página executiva: oportunidades de negociação (ranking explicável e rastreável)."""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from app.components import detalhe, graficos
from app.components.ui import (brl, brl_curto, cabecalho, cartao, dropdown, filtro, gaveta, kpi, nota, num, pct,
                               periodo, selo, vazio)
from app.config import SETTINGS
from app.repositories import catalogo_repo
from app.services import inteligencia as ig

ROTULO_TIPO = ig.TIPOS
LIMITE_GRADE = 500

F_BRL = {"function": "params.value == null ? '' : Number(params.value).toLocaleString('pt-BR', {style:'currency', currency:'BRL', maximumFractionDigits: (Math.abs(params.value) < 10 ? 4 : 2)})"}
F_PCT = {"function": "params.value == null ? '' : Number(params.value).toLocaleString('pt-BR', {maximumFractionDigits: 1}) + '%'"}
F_NUM = {"function": "params.value == null ? '' : Number(params.value).toLocaleString('pt-BR', {maximumFractionDigits: 1})"}

COLUNAS = [
    {"field": "prioridade", "headerName": "Prior.", "width": 92, "sort": "desc", "cellClass": "num",
     "valueFormatter": F_NUM, "type": "rightAligned"},
    {"field": "faixa_prioridade", "headerName": "Faixa", "width": 90},
    {"field": "tipo_rotulo", "headerName": "Tipo", "minWidth": 210, "flex": 1, "tooltipField": "tipo_rotulo"},
    {"field": "material", "headerName": "Material", "minWidth": 240, "flex": 2, "tooltipField": "material"},
    {"field": "fornecedor", "headerName": "Fornecedor atual", "minWidth": 180, "flex": 1, "tooltipField": "fornecedor"},
    {"field": "solicitacao_atual", "headerName": "Solicitação", "width": 112, "tooltipField": "solicitacao_atual"},
    {"field": "pedido_atual", "headerName": "Pedido", "width": 92},
    {"field": "solicitacao_ref", "headerName": "Solic. ref.", "width": 112, "tooltipField": "solicitacao_ref"},
    {"field": "pedido_ref", "headerName": "Pedido ref.", "width": 100},
    {"field": "obra", "headerName": "Obra", "minWidth": 160, "flex": 1, "tooltipField": "obra"},
    {"field": "preco_atual", "headerName": "Preço atual", "width": 125, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "preco_referencia", "headerName": "Referência", "width": 125, "valueFormatter": F_BRL,
     "cellClass": "num", "type": "rightAligned"},
    {"field": "unidade", "headerName": "Un.", "width": 64},
    {"field": "diferenca_pct", "headerName": "Dif.", "width": 86, "valueFormatter": F_PCT, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "impacto", "headerName": "Impacto est.", "width": 135, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "no_total", "headerName": "Soma no total", "width": 112},
    {"field": "confianca", "headerName": "Confiança", "width": 100, "valueFormatter": F_NUM, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "explicacao_prioridade", "headerName": "Por que está nesta posição", "minWidth": 300, "flex": 2,
     "tooltipField": "explicacao_prioridade"},
]


def _opcoes():
    try:
        b = ig.base()
    except Exception as exc:  # noqa: BLE001
        return None, str(exc).splitlines()[0]
    obras = (b.drop_duplicates("cod_obra").sort_values("obra")[["cod_obra", "obra"]])
    forn = (b.groupby(["cod_fornecedor", "fornecedor"])["valor"].sum().reset_index()
            .sort_values("valor", ascending=False))
    return {
        "obras": [{"label": r.obra, "value": r.cod_obra} for r in obras.itertuples()],
        "fornecedores": [{"label": r.fornecedor, "value": int(r.cod_fornecedor)} for r in forn.itertuples()],
        "categorias": [{"label": c, "value": c} for c in sorted(b["categoria"].dropna().unique())],
        "ini": b["data_pedido"].min().date() if len(b) else None,
        "fim": b["data_pedido"].max().date() if len(b) else None,
    }, None


def _info_etl() -> str:
    r = ig.ultimo_processamento()
    if not r:
        return "o ETL ainda não calculou a análise de compras (etapa inteligencia_compras)."
    return (f"calculado pelo ETL em {r['processado_em']:%d/%m/%Y %H:%M} sobre {num(r['compras'])} compras "
            f"(regras {r['versao_regras']}).")


def layout(**_):
    op, erro = _opcoes()
    if erro:
        return html.Div([cabecalho("Oportunidades de negociação", "Não foi possível ler o DW."),
                         vazio(f"Erro de conexão: {erro}")])
    filtros = html.Div([
        filtro("Período do pedido", periodo("op-periodo", op["ini"], op["fim"]), "largo"),
        filtro("Obra / centro de custo", dropdown("op-obras", op["obras"], multi=True)),
        filtro("Fornecedor", dropdown("op-fornecedores", op["fornecedores"], multi=True)),
        filtro("Categoria de insumo", dropdown("op-categorias", op["categorias"], multi=True)),
        html.Details([html.Summary("Limites mínimos e confiança"), html.Div([
            filtro("Confiança mínima da equivalência", dropdown(
                "op-confianca", [{"label": "Alta (≥ 85)", "value": 85}, {"label": "≥ 90", "value": 90},
                                 {"label": "≥ 95", "value": 95}, {"label": "Só mesmo código ou validada por pessoa",
                                                                 "value": 100}], valor=85, clearable=False)),
            filtro("Diferença mínima (%)", dcc.Input(id="op-min-pct", debounce=0.6, type="number", value=5, min=0, step=1,
                                                     className="cv-input"), "estreito"),
            filtro("Impacto mínimo (R$)", dcc.Input(id="op-min-imp", debounce=0.6, type="number", value=500, min=0, step=100,
                                                    className="cv-input"), "estreito"),
            filtro("Janela da referência (dias · definida no ETL)", html.Div(dcc.Input(
                id="op-janela", type="number", value=int(ig.config_etl().get("janela_referencia_dias", 180)),
                disabled=True, className="cv-input"),
                title="InteligenciaComprasConfig.janela_referencia_dias no airflow_api_sienge"), "estreito"),
        ], className="filtros-linha")], className="mais-filtros"),
    ], className="filtros")

    selo_mock = html.Span("DADOS SINTÉTICOS", className="selo-sintetico") if SETTINGS.dw_schema != "suprimentos" else None
    return html.Div([
        cabecalho("Oportunidades de negociação",
                  "Onde o mesmo material (ou equivalente validado) foi comprado mais caro — com a compra de "
                  "referência que sustenta cada caso.", selo_mock, relatorio="op"),
        filtros,
        dcc.Loading(html.Div(id="op-kpis"), type="dot", color="#1B365D"),
        html.Div([
            cartao("Excesso pago acima do menor preço do mês", dcc.Graph(id="op-g-mes", config={"displaylogo": False},
                                                                         figure=graficos.vazio("Carregando…")),
                   html.Span("Por mês: (preço − menor preço comparável do mesmo mês) × quantidade, só em materiais "
                             "com 2+ fornecedores no mês e sem preços atípicos. Mostra a tendência; não é o total "
                             "de economia.", className="cv-nota"), fonte="pedidos de compra", classe="grafico-card"),
            cartao("Oportunidades por tipo", html.Div(id="op-tipos")),
        ], className="cv-grid", style={"gridTemplateColumns": "minmax(0,2fr) minmax(0,1fr)"}),
        cartao("Ranking priorizado", html.Div([
            dcc.Input(id="op-busca", placeholder="Filtrar o ranking (material, fornecedor, obra…)", className="cv-input",
                      debounce=True),
            dropdown("op-tipo", [{"label": v, "value": k} for k, v in ROTULO_TIPO.items()], multi=True,
                     placeholder="Todos os tipos", style={"minWidth": 300}),
        ], className="lx-busca"),
            dag.AgGrid(id="op-grade", columnDefs=COLUNAS, rowData=[], className="ag-theme-quartz",
                       defaultColDef={"sortable": True, "resizable": True, "filter": True},
                       dashGridOptions={"rowSelection": {"mode": "singleRow", "checkboxes": False,
                                                         "enableClickSelection": True},
                                        "tooltipShowDelay": 300, "animateRows": False,
                                        "localeText": {"noRowsToShow": "Nenhuma oportunidade com os filtros atuais"}},
                       style={"height": 520}),
            html.Span(id="op-nota-grade", className="cv-nota")),
        nota(html.B("Processamento: "), _info_etl(), " Os filtros escolhem as oportunidades pela compra atual; a "
             "referência pode ser de outra obra ou de fora do período, desde que dentro da janela."),
        nota(html.B("Como ler: "), "economia potencial é uma ESTIMATIVA — diferença de preço unitário × volume já "
             "comprado (hipótese de repetir a compra). Não é economia negociada nem realizada. Só entram materiais "
             "com equivalência de alta confiança (ou validada por pessoa), na mesma unidade ou com conversão "
             "rastreável; preços atípicos ficam fora e aparecem como 'conferir registro'. O total soma no máximo "
             "uma oportunidade por material e fornecedor (sem dupla contagem)."),
        gaveta("op-gaveta", "op-gaveta-titulo", "op-gaveta-corpo"),
        *detalhe.modal("op-dm"),
    ])


dash.register_page(__name__, path="/", name="Oportunidades", title="Oportunidades · Suprimentos", layout=layout)


def _cfg(conf, min_pct, min_imp, janela):
    return ig.ConfigOportunidade(confianca_minima=float(conf or 85), min_diferenca_pct=float(min_pct or 0),
                                 min_impacto=float(min_imp or 0), janela_referencia_dias=int(janela or 180))


@callback(
    Output("op-kpis", "children"), Output("op-g-mes", "figure"), Output("op-tipos", "children"),
    Output("op-grade", "rowData"), Output("op-nota-grade", "children"),
    Input("op-periodo", "start_date"), Input("op-periodo", "end_date"), Input("op-obras", "value"),
    Input("op-fornecedores", "value"), Input("op-categorias", "value"), Input("op-confianca", "value"),
    Input("op-min-pct", "value"), Input("op-min-imp", "value"), Input("op-janela", "value"),
    Input("op-tipo", "value"), Input("op-busca", "value"),
)
def atualizar(ini, fim, obras, fornecedores, categorias, conf, min_pct, min_imp, janela, tipos, busca):
    cfg = _cfg(conf, min_pct, min_imp, janela)
    ops, base_f = ig.oportunidades(ini, fim, obras, fornecedores, categorias, cfg)
    try:
        st = catalogo_repo.contagem_status().set_index("status")["n"]
    except Exception:  # noqa: BLE001
        st = pd.Series(dtype=int)

    if ops.empty:
        ops = pd.DataFrame({"tipo": pd.Series(dtype=str), "impacto": pd.Series(dtype=float),
                            "entra_no_total": pd.Series(dtype=bool), "id_grupo": pd.Series(dtype=str),
                            "prioridade": pd.Series(dtype=float)})
    no_total = ops[ops["entra_no_total"].astype(bool)]
    economia = float(no_total["impacto"].sum())
    comerciais = ops[ops["tipo"] != "verificar_registro"]
    mat_dif = ops[ops["tipo"].isin(["fornecedor_mais_barato", "aumento_historico", "diferenca_obras"])]["id_grupo"].nunique()
    comparaveis = base_f["comparavel"].mean() * 100 if len(base_f) else 0
    def k(chave, *a, **kw):
        return detalhe.kpi_clicavel({"type": "op-kpi", "k": chave}, kpi(*a, **kw))

    kpis = html.Div([
        k("economia", "Economia potencial estimada", brl_curto(economia),
          f"{len(no_total)} oportunidades somadas · base: volume histórico", "destaque", tag="estimativa",
          titulo="Soma por material e fornecedor (sem dupla contagem). Hipótese: repetir o volume comprado."),
        k("oportunidades", "Oportunidades identificadas", num(len(comerciais)),
          f"{num((comerciais['prioridade'] >= 60).sum())} de prioridade alta", "neutro"),
        k("materiais", "Materiais com diferença relevante", num(mat_dif), "fornecedor, histórico ou entre obras",
          "neutro"),
        k("fornecedores", "Fornecedores analisados", num(base_f["cod_fornecedor"].nunique()),
          f"{num(base_f['cod_obra'].nunique())} obras", "neutro"),
        k("compras", "Compras analisadas", brl_curto(float(base_f["valor"].sum())),
          f"{num(len(base_f))} itens · {pct(comparaveis, 0)} com preço comparável", "neutro"),
        k("aprovadas", "Equivalências aprovadas", num(int(st.get("aprovado", 0) + st.get("auto_aprovado", 0))),
          f"{num(int(st.get('aprovado', 0)))} por pessoa · {num(int(st.get('auto_aprovado', 0)))} automáticas",
          "neutro"),
        k("pendentes", "Pendentes de validação", num(int(st.get("pendente", 0) + st.get("revisar_mudanca", 0))),
          "pares aguardando revisão humana", "kpi-oport neutro"),
        k("atipicos", "Preços atípicos para conferir", num(int((ops["tipo"] == "verificar_registro").sum())),
          "operacional — não é economia", "neutro"),
    ], className="port-kpi-grid", style={"marginBottom": 14, "gridTemplateColumns": "repeat(4, minmax(0, 1fr))"})

    fig = graficos.barras_mes(ig.evolucao_mensal(base_f, cfg), "excesso", "Excesso pago")

    resumo_tipo = (ops.groupby("tipo").agg(n=("tipo", "size"), impacto=("impacto", "sum"),
                                           soma=("entra_no_total", "sum")).reindex(list(ROTULO_TIPO)).dropna(how="all"))
    tipos_html = [html.Div([html.Div([html.Span(ROTULO_TIPO[t]), html.Small(
        "soma no total" if r.soma else ("informativo" if t != "verificar_registro" else "operacional"))],
        className="cv-linha-l"), html.Span(f"{int(r.n)} · " + ("—" if t == "verificar_registro" else
                         (f"{brl_curto(r.impacto)} comprados" if t == "volume_consolidacao" else brl_curto(r.impacto))),
                                           className="cv-linha-v")], className="cv-linha")
        for t, r in resumo_tipo.iterrows()] or [vazio("Sem oportunidades")]

    g = ops.copy()
    if tipos:
        g = g[g["tipo"].isin(tipos)]
    if busca:
        b = busca.lower()
        g = g[g[["material", "fornecedor", "obra", "categoria"]].astype(str).apply(
            lambda c: c.str.lower().str.contains(b, regex=False)).any(axis=1)]
    total = len(g)
    g = _codigos(g.sort_values("prioridade", ascending=False).head(LIMITE_GRADE))
    g = g.assign(tipo_rotulo=g["tipo"].map(ROTULO_TIPO), no_total=g["entra_no_total"].map({True: "sim", False: "não"}))
    nota_grade = (f"Mostrando {min(total, LIMITE_GRADE)} de {total} oportunidades (maior prioridade primeiro). "
                  "Clique numa linha para ver a justificativa e os documentos.")
    return kpis, fig, tipos_html, g.to_dict("records"), nota_grade


def _bloco_evidencia(titulo, e, unidade, solicitacao=None):
    if not e:
        return html.Div([html.H4(titulo), html.Div("Referência estatística (mediana) — sem compra única.",
                                                   className="muted")], className="evid")
    linhas = [("Preço comparável", f"{brl(e['preco'])}/{unidade}"), ("Data", pd.Timestamp(e["data"]).strftime("%d/%m/%Y")),
              ("Solicitação", solicitacao or "não localizada no painel de compras"),
              ("Pedido / item", f"{e['pedido']} / {e['item']}"), ("Cotação", e.get("cotacao") or "—"),
              ("Fornecedor", e["fornecedor"]), ("Obra", e["obra"]), ("Insumo", f"{e['cod_insumo']} · {e['insumo']}"),
              ("Condição de pagamento", e.get("condicao_pagamento") or "—"),
              ("Frete unitário", brl(e.get("frete_unitario") or 0)),
              ("Nota fiscal", "não disponível na fonte atual"),
              ("Confiança da equivalência", num(e.get("confianca"), 0))]
    return html.Div([html.H4(titulo), html.Div(f"{brl(e['preco'])}/{unidade}", className="v")] +
                    [html.Div([html.Span(k), html.Span(str(v))], className="l") for k, v in linhas[1:]],
                    className="evid")


@callback(
    Output("op-gaveta", "is_open"), Output("op-gaveta-titulo", "children"), Output("op-gaveta-corpo", "children"),
    Input("op-grade", "selectedRows"), prevent_initial_call=True,
)
def detalhar(linhas):
    if not linhas:
        return no_update, no_update, no_update
    o = linhas[0]
    u = o.get("unidade") or "un"
    corpo = html.Div([
        html.Div([selo(o["tipo_rotulo"], "info"), " ", selo(f"prioridade {o['prioridade']:.0f} · {o['faixa_prioridade']}",
                                                             "alta" if o["faixa_prioridade"] == "alta" else "media")]),
        html.P(o["justificativa"], style={"marginTop": 12, "fontSize": 14}),
        html.Div([
            kpi("Preço atual", f"{brl(o['preco_atual'])}/{u}", "", "neutro"),
            kpi("Referência", f"{brl(o['preco_referencia'])}/{u}", "", "neutro"),
            kpi("Diferença", f"{brl(o.get('diferenca_unit'))}/{u}", pct(o.get("diferenca_pct")), "neutro"),
            kpi("Impacto estimado", brl(o["impacto"], 2), o["base_impacto"],
                "destaque" if o["entra_no_total"] else "neutro"),
        ], className="port-kpi-grid", style={"margin": "12px 0"}),
        html.Div([_bloco_evidencia("Compra atual", o.get("evidencia_atual"), u, o.get("solicitacao_atual")),
                  _bloco_evidencia("Compra de referência", o.get("evidencia_referencia"), u, o.get("solicitacao_ref"))],
                 className="evid-grade"),
        html.Div([html.B("Ressalvas de comparabilidade"),
                  html.Ul([html.Li(r) for r in (o.get("ressalvas") or ["nenhuma identificada"])],
                          className="lista-motivos")], className="nota-metodo"),
        html.Div([html.B("Por que esta prioridade: "), o["explicacao_prioridade"]], className="nota-metodo"),
        html.Div([dcc.Link("Ver comparativo do material →", href=f"/comparativo?grupo={o['id_grupo']}",
                           className="btn btn-pri btn-p"), " ",
                  dcc.Link("Ver histórico de preços →", href=f"/historico?grupo={o['id_grupo']}",
                           className="btn btn-sec btn-p")], className="acoes", style={"justifyContent": "flex-start"}),
    ])
    return True, o["material"], corpo


# ── Decomposição dos cards ───────────────────────────────────────────────────
detalhe.registrar("op-dm")


def _c(campo, rotulo, formato="texto", total=False, peso=None):
    d = {"campo": campo, "rotulo": rotulo, "formato": formato, "total": total}
    if peso:
        d["peso"] = peso
    return d


def _periodo_txt(ini, fim):
    f = lambda d: pd.Timestamp(d).strftime("%d/%m/%Y") if d else "…"  # noqa: E731
    return f"período {f(ini)} a {f(fim)}"


def _codigos(d: pd.DataFrame) -> pd.DataFrame:
    """Solicitação e pedido da compra atual e da referência, como texto (sem separador de milhar)."""
    return ig.com_rastreio(d)


COLS_CODIGOS = [_c("solicitacao_atual", "Solicitação atual", peso=0.9), _c("pedido_atual", "Pedido atual", peso=0.8),
                _c("solicitacao_ref", "Solicitação ref.", peso=0.9), _c("pedido_ref", "Pedido ref.", peso=0.8)]
NOTA_CODIGOS = (" Solicitação e pedido permitem abrir o caso no Sienge; a solicitação vem do painel de compras "
                "(pedidos de 2025 em diante) e fica vazia quando a referência é mediana/histórico.")


def _ref_fornecedor(o):
    e = o.get("evidencia_referencia") if isinstance(o, dict) else None
    return (e or {}).get("fornecedor") or "mediana / histórico"


def _decompor(chave, ops, base_f, cfg, ini, fim):
    per = _periodo_txt(ini, fim)
    if ops.empty:
        ops = pd.DataFrame(columns=["tipo", "impacto", "entra_no_total", "id_grupo", "prioridade", "material",
                                    "fornecedor", "obra", "categoria", "diferenca_pct", "preco_atual",
                                    "preco_referencia", "unidade", "volume_base", "faixa_prioridade"])
    ops = ops.assign(tipo_rotulo=ops["tipo"].map(ROTULO_TIPO),
                     impacto_somado=ops["impacto"].where(ops["entra_no_total"].astype(bool), 0.0))

    if chave == "economia":
        d = ops[ops["entra_no_total"].astype(bool)].sort_values("impacto", ascending=False)
        d = _codigos(d.assign(fornecedor_ref=[_ref_fornecedor(o) for o in d.to_dict("records")]))
        cols = [_c("material", "Material", peso=2.6), _c("fornecedor", "Fornecedor atual", peso=2),
                COLS_CODIGOS[0], COLS_CODIGOS[1], _c("fornecedor_ref", "Fornecedor ref.", peso=2),
                COLS_CODIGOS[2], COLS_CODIGOS[3], _c("tipo_rotulo", "Tipo", peso=1.8), _c("obra", "Obra", peso=1.8),
                _c("preco_atual", "Preço atual", "brl4"), _c("preco_referencia", "Referência", "brl4"),
                _c("unidade", "Un.", peso=0.6), _c("diferenca_pct", "Dif.", "pct", peso=0.8),
                _c("volume_base", "Volume base", "num2"), _c("impacto", "Economia potencial", "brl", True, 1.3)]
        return ("Economia potencial estimada", f"{len(d)} oportunidade(s) somada(s) · {per} · sem dupla contagem "
                "(1 por material e fornecedor)", d, cols,
                "Estimativa = (preço atual − referência) × volume base. Não é economia negociada nem realizada." + NOTA_CODIGOS)

    if chave == "oportunidades":
        d = _codigos(ops[ops["tipo"] != "verificar_registro"].sort_values("prioridade", ascending=False))
        cols = [_c("prioridade", "Prior.", "num", peso=0.6), _c("faixa_prioridade", "Faixa", peso=0.7),
                _c("material", "Material", peso=2.6), _c("fornecedor", "Fornecedor", peso=2)] + COLS_CODIGOS + [
                _c("tipo_rotulo", "Tipo", peso=1.8), _c("obra", "Obra", peso=1.8),
                _c("diferenca_pct", "Dif.", "pct", peso=0.8), _c("impacto", "Impacto est.", "brl"),
                _c("impacto_somado", "Entra no total", "brl", True)]
        return ("Oportunidades identificadas", f"{len(d)} oportunidade(s) · {per}", d, cols,
                "A coluna 'Entra no total' soma só o que compõe a economia potencial (informativas ficam em zero)."
                + NOTA_CODIGOS)

    if chave == "materiais":
        m = ops[ops["tipo"].isin(["fornecedor_mais_barato", "aumento_historico", "diferenca_obras"])]
        d = (m.groupby(["id_grupo", "material", "categoria"], dropna=False)
             .agg(n=("tipo", "size"), tipos=("tipo_rotulo", lambda s: ", ".join(sorted(set(s.dropna())))),
                  maior_dif=("diferenca_pct", "max"), impacto=("impacto_somado", "sum"))
             .reset_index().sort_values("impacto", ascending=False))
        cols = [_c("material", "Material", peso=3), _c("categoria", "Categoria", peso=1.6),
                _c("tipos", "Tipos de oportunidade", peso=2.6), _c("n", "Oportunidades", "int", peso=0.8),
                _c("maior_dif", "Maior dif.", "pct", peso=0.8), _c("impacto", "Economia potencial", "brl", True)]
        return ("Materiais com diferença relevante", f"{len(d)} material(is) · {per}", d, cols, None)

    if chave in ("fornecedores", "compras"):
        por = ["cod_fornecedor", "fornecedor"] if chave == "fornecedores" else ["cod_obra", "obra"]
        d = (base_f.groupby(por, dropna=False)
             .agg(itens=("valor", "size"), valor=("valor", "sum"), materiais=("id_grupo", "nunique"),
                  outros=("cod_obra" if chave == "fornecedores" else "cod_fornecedor", "nunique"),
                  comparavel=("comparavel", "mean"))
             .reset_index())
        d["comparavel"] = d["comparavel"] * 100
        eco = ops[ops["entra_no_total"].astype(bool)].groupby(por[0])["impacto"].sum()
        d["economia"] = d[por[0]].map(eco).fillna(0.0)
        d = d.sort_values("valor", ascending=False)
        nome = "Fornecedor" if chave == "fornecedores" else "Obra / centro de custo"
        outros = "Obras" if chave == "fornecedores" else "Fornecedores"
        cols = [_c(por[1], nome, peso=3), _c("itens", "Itens", "int", True, 0.7), _c("materiais", "Materiais", "int", peso=0.8),
                _c("outros", outros, "int", peso=0.7), _c("valor", "Valor comprado", "brl", True, 1.3),
                _c("comparavel", "% comparável", "pct", peso=0.9), _c("economia", "Economia potencial", "brl", True, 1.2)]
        titulo = "Fornecedores analisados" if chave == "fornecedores" else "Compras analisadas por obra"
        rot = "fornecedor(es)" if chave == "fornecedores" else "obra(s)"
        return (titulo, f"{num(len(d))} {rot} · {num(len(base_f))} itens · {per}", d, cols,
                "% comparável = itens com unidade/conversão segura e equivalência confiável.")

    if chave in ("aprovadas", "pendentes"):
        status = ["aprovado", "auto_aprovado"] if chave == "aprovadas" else ["pendente", "revisar_mudanca"]
        d = catalogo_repo.listar_pares(status=status, limite=50000)
        d["status"] = d["status"].str.replace("_", " ")
        cols = [_c("descricao_a", "Insumo A", peso=3), _c("descricao_b", "Insumo B", peso=3),
                _c("categoria", "Categoria", peso=1.5), _c("score", "Score", "num", peso=0.6),
                _c("status", "Situação", peso=1.1), _c("decidido_por", "Decidido por", peso=1.1),
                _c("decidido_em", "Em", "data", peso=0.9)]
        titulo = "Equivalências aprovadas" if chave == "aprovadas" else "Pendentes de validação"
        nota_ = ("Revise e decida na tela Correspondências." if chave == "pendentes"
                 else "Aprovadas por pessoa ou automaticamente (alta confiança, sem conflito técnico).")
        return titulo, f"{len(d)} par(es) de insumos · catálogo de equivalências", d, cols, nota_

    if chave == "atipicos":
        d = _codigos(ops[ops["tipo"] == "verificar_registro"].copy())
        d["data"] = [(o.get("evidencia_atual") or {}).get("data") for o in d.to_dict("records")]
        cols = [_c("material", "Material", peso=3), _c("fornecedor", "Fornecedor", peso=2), _c("obra", "Obra", peso=2),
                _c("solicitacao_atual", "Solicitação", peso=0.9), _c("pedido_atual", "Pedido", peso=0.8),
                _c("item_atual", "Item", peso=0.5), _c("data", "Data", "data", peso=0.9),
                _c("preco_atual", "Preço registrado", "brl4"), _c("preco_referencia", "Mediana do material", "brl4"),
                _c("unidade", "Un.", peso=0.6), _c("diferenca_pct", "Dif.", "pct", peso=0.8)]
        return ("Preços atípicos para conferir", f"{len(d)} registro(s) · {per}", d, cols,
                "Fora dos cálculos de economia: provável erro de unidade/registro. Conferir no pedido.")
    return None


@callback(
    *detalhe.saidas("op-dm"),
    Input({"type": "op-kpi", "k": ALL}, "n_clicks"),
    State("op-periodo", "start_date"), State("op-periodo", "end_date"), State("op-obras", "value"),
    State("op-fornecedores", "value"), State("op-categorias", "value"), State("op-confianca", "value"),
    State("op-min-pct", "value"), State("op-min-imp", "value"), State("op-janela", "value"),
    prevent_initial_call=True,
)
def abrir_decomposicao(cliques, ini, fim, obras, fornecedores, categorias, conf, min_pct, min_imp, janela):
    if not ctx.triggered or not ctx.triggered[0].get("value") or not isinstance(ctx.triggered_id, dict):
        return (no_update,) * 5
    cfg = _cfg(conf, min_pct, min_imp, janela)
    ops, base_f = ig.oportunidades(ini, fim, obras, fornecedores, categorias, cfg)
    r = _decompor(ctx.triggered_id["k"], ops, base_f, cfg, ini, fim)
    if r is None:
        return (no_update,) * 5
    titulo, sub, d, cols, nota_ = r
    return detalhe.abrir(titulo, sub, d, cols, nota_)


# ── Relatório em PowerPoint (botão "Gerar relatório") ────────────────────────
@callback(Output("op-rel-down", "data"), Input("op-rel", "n_clicks"),
          State("op-periodo", "start_date"),
          State("op-periodo", "end_date"),
          State("op-obras", "value"),
          State("op-fornecedores", "value"),
          State("op-categorias", "value"),
          State("op-confianca", "value"),
          State("op-min-pct", "value"),
          State("op-min-imp", "value"),
          State("op-janela", "value"), prevent_initial_call=True)
def gerar_relatorio(n, ini, fim, obras, fornecedores, categorias, conf, min_pct, min_imp, janela):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    return dcc.send_bytes(rel.oportunidades(ini, fim, obras, fornecedores, categorias, _cfg(conf, min_pct, min_imp, janela)), nome_arquivo("oportunidades"))
