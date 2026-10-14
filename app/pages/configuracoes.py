"""Configurações gerais das abas: prazos de SLA por grupo de insumo, parâmetros e histórico de alterações."""
from __future__ import annotations

import json

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import ALL, Input, Output, State, callback, dcc, html, no_update

from app.components.ui import cabecalho, cartao, nota, num, vazio
from app.seguranca import sessao
from app.services import configuracoes as cf

F_DIAS = {"function": "params.value == null || params.value === '' ? '' : Math.round(params.value) + ' d'"}


def _grade_prazos(pode: bool):
    p = cf.prazos_sla()
    ed = {"editable": pode, "cellClass": "num cfg-editavel" if pode else "num", "type": "rightAligned",
          "valueFormatter": F_DIAS, "cellDataType": "number", "width": 120}
    cols = [{"field": "id_grupo", "headerName": "Cód.", "width": 80, "pinned": "left"},
            {"field": "grupo_insumo", "headerName": "Grupo de insumo", "minWidth": 280, "flex": 2, "pinned": "left",
             "tooltipField": "grupo_insumo"},
            {"field": "tipo_grupo", "headerName": "Tipo", "width": 170},
            {"field": "curva_abc_grupo", "headerName": "Curva", "width": 80},
            {"field": "itens", "headerName": "Linhas no período carregado", "width": 150, "cellClass": "num",
             "type": "rightAligned"},
            {"field": "lt_fase1", "headerName": "Prazo fase 1 (sol.→pedido)", **ed},
            {"field": "lt_fase2", "headerName": "Prazo fase 2 (pedido→entrega)", **ed},
            {"field": "lt_total", "headerName": "Prazo fluxo inteiro", **ed},
            {"field": "ref_fase1", "headerName": "Planilha F1", "width": 105, "valueFormatter": F_DIAS,
             "cellClass": "num", "type": "rightAligned"},
            {"field": "ref_fase2", "headerName": "Planilha F2", "width": 105, "valueFormatter": F_DIAS,
             "cellClass": "num", "type": "rightAligned"},
            {"field": "origem", "headerName": "Origem", "width": 150,
             "cellStyle": {"function": "params.value == 'sem prazo' ? {color: '#B42318', fontWeight: 600} : "
                                       "params.value == 'editado no painel' ? {color: '#1B365D', fontWeight: 600} : {}"}},
            {"field": "alterado_por", "headerName": "Alterado por", "width": 130},
            {"field": "alterado_em", "headerName": "Em", "width": 140}]
    linhas = p[["id_grupo", "grupo_insumo", "tipo_grupo", "curva_abc_grupo", "itens", "lt_fase1", "lt_fase2", "lt_total",
                "ref_fase1", "ref_fase2", "origem", "alterado_por", "alterado_em"]].copy()
    linhas["alterado_em"] = pd.to_datetime(linhas["alterado_em"], utc=True, errors="coerce").dt.tz_convert(
        "America/Maceio").dt.strftime("%d/%m/%Y %H:%M")
    return dag.AgGrid(id="cfg-grade", rowData=linhas.astype(object).where(linhas.notna(), None).to_dict("records"),
                      columnDefs=cols, className="ag-theme-quartz", style={"height": 560},
                      defaultColDef={"sortable": True, "resizable": True, "filter": True},
                      dashGridOptions={"tooltipShowDelay": 300, "singleClickEdit": True,
                                       "stopEditingWhenCellsLoseFocus": True, "animateRows": False})


def _parametros(pode: bool):
    itens = []
    for r in cf.parametros().itertuples():
        if r.tipo == "bool":
            campo = dcc.Checklist(id={"type": "cfg-param", "k": r.chave}, options=[{"label": " sim", "value": "sim"}],
                                  value=["sim"] if r.valor else [], inputStyle={"marginRight": 6})
        else:
            campo = dcc.Input(id={"type": "cfg-param", "k": r.chave}, type="number", value=r.valor, min=r.minimo,
                              max=r.maximo, step=1, className="cv-input", disabled=not pode, style={"maxWidth": 140})
        itens.append(html.Div([html.Div([html.B(r.rotulo), html.Div(r.descricao, className="cv-nota"),
                                         html.Div(f"padrão: {r.padrao}", className="cv-nota")], style={"flex": 1}),
                               campo], style={"display": "flex", "gap": 18, "alignItems": "center",
                                              "padding": "10px 0", "borderBottom": "1px solid var(--border, #e3e9f1)"}))
    return html.Div(itens)


def layout(**_):
    pode = sessao.pode("editar_configuracoes")
    aviso = None if pode else html.Div("Seu perfil pode consultar, mas não alterar as configurações.",
                                       className="adm-msg erro")
    try:
        grade = _grade_prazos(pode)
    except Exception as exc:  # noqa: BLE001
        grade = vazio(f"Prazos indisponíveis (rode `alembic upgrade head` e a etapa sla_insumo do ETL): {exc}")
    acoes = html.Div([
        dcc.Input(id="cfg-obs", className="cv-input", placeholder="Motivo da alteração (fica no histórico)",
                  style={"minWidth": 360}),
        html.Button("Salvar prazos alterados", id="cfg-salvar", className="btn btn-pri btn-p", n_clicks=0,
                    disabled=not pode),
    ], className="acoes", style={"justifyContent": "flex-start", "marginTop": 10})
    return html.Div([
        cabecalho("Configurações", "Parâmetros gerais das abas, num lugar só. Alterações valem na hora e ficam "
                  "registradas com quem e quando."),
        aviso,
        dcc.Tabs(id="cfg-aba", value="sla", className="adm-abas", children=[
            dcc.Tab(label="Prazos de SLA (insumos)", value="sla", className="adm-aba", selected_className="adm-aba-sel"),
            dcc.Tab(label="Parâmetros das abas", value="param", className="adm-aba", selected_className="adm-aba-sel"),
            dcc.Tab(label="Histórico de alterações", value="hist", className="adm-aba", selected_className="adm-aba-sel"),
        ]),
        html.Div([cartao("Prazo por grupo de insumo (dias corridos)", grade,
                         html.Span("Clique na célula azul para editar. Vazio = sem prazo (o grupo fica fora do % de "
                                   "SLA). Voltar ao valor da planilha remove a edição. Grupos 'sem prazo' existem nas "
                                   "compras mas não estão na planilha de Suprimentos.", className="cv-nota"),
                         acoes, html.Div(id="cfg-msg"))], id="cfg-sec-sla"),
        html.Div([cartao("Parâmetros", _parametros(pode),
                         html.Div(html.Button("Salvar parâmetros", id="cfg-param-salvar", className="btn btn-pri btn-p",
                                              n_clicks=0, disabled=not pode), className="acoes",
                                  style={"justifyContent": "flex-start", "marginTop": 10}),
                         html.Div(id="cfg-param-msg"))], id="cfg-sec-param", style={"display": "none"}),
        html.Div(id="cfg-sec-hist", style={"display": "none"}),
        nota(html.B("De onde vem: "), "a referência dos prazos é a planilha de grupos de insumo de Suprimentos (a mesma "
             "dos analistas), carregada pelo ETL; o que é editado aqui sobrepõe a planilha só no painel. Para mudar a "
             "referência de vez, atualize a planilha — a próxima carga traz o valor novo e a edição pode ser removida."),
    ])


dash.register_page(__name__, path="/configuracoes", name="Configurações", title="Configurações · Suprimentos",
                   layout=layout)


@callback(Output("cfg-sec-sla", "style"), Output("cfg-sec-param", "style"), Output("cfg-sec-hist", "style"),
          Input("cfg-aba", "value"))
def trocar_aba(aba):
    m, e = {"display": "block", "marginTop": 14}, {"display": "none"}
    return [m if aba == x else e for x in ("sla", "param", "hist")]


@callback(Output("cfg-msg", "children"), Output("cfg-grade", "rowData"), Input("cfg-salvar", "n_clicks"),
          State("cfg-grade", "rowData"), State("cfg-obs", "value"), prevent_initial_call=True)
def salvar(n, linhas, obs):
    if not n or not linhas:
        return no_update, no_update
    u = sessao.exigir("editar_configuracoes")
    try:
        qtd = cf.salvar_prazos(linhas, u.login, (obs or "").strip() or None)
    except cf.ErroConfiguracao as e:
        return html.Div(str(e), className="adm-msg erro"), no_update
    msg = (f"{num(qtd)} grupo(s) atualizado(s). A tela de SLA já usa os prazos novos." if qtd
           else "Nenhuma alteração para salvar.")
    return html.Div(msg, className="adm-msg ok"), _grade_prazos(True).rowData


@callback(Output("cfg-param-msg", "children"), Input("cfg-param-salvar", "n_clicks"),
          State({"type": "cfg-param", "k": ALL}, "value"), State({"type": "cfg-param", "k": ALL}, "id"),
          prevent_initial_call=True)
def salvar_parametros(n, valores, ids):
    if not n:
        return no_update
    u = sessao.exigir("editar_configuracoes")
    tipos = cf.parametros().set_index("chave")["tipo"]
    try:
        for v, i in zip(valores, ids):
            k = i["k"]
            cf.salvar_parametro(k, bool(v) if tipos[k] == "bool" else v, u.login)
    except cf.ErroConfiguracao as e:
        return html.Div(str(e), className="adm-msg erro")
    return html.Div("Parâmetros salvos. Recarregue as abas abertas para ver o efeito.", className="adm-msg ok")


@callback(Output("cfg-sec-hist", "children"), Input("cfg-aba", "value"), Input("cfg-msg", "children"),
          Input("cfg-param-msg", "children"))
def historico(aba, *_):
    if aba != "hist":
        return no_update
    h = cf.historico(500)
    if h.empty:
        return vazio("Nenhuma alteração registrada.")
    nomes = cf.prazos_sla().set_index("id_grupo")["grupo_insumo"].to_dict()
    h["quando"] = pd.to_datetime(h["quando"], utc=True).dt.tz_convert("America/Maceio").dt.strftime("%d/%m/%Y %H:%M")
    h["item"] = [nomes.get(int(c), c) if a == "sla_grupo" and str(c).isdigit() else c for a, c in zip(h["area"], h["chave"])]
    h["de"] = h["valor_anterior"].map(lambda v: json.dumps(v, ensure_ascii=False))
    h["para"] = h["valor_novo"].map(lambda v: json.dumps(v, ensure_ascii=False))
    return cartao("Últimas 500 alterações", dag.AgGrid(
        rowData=h[["quando", "por", "area", "item", "de", "para", "observacao"]].astype(object)
        .where(h[["quando", "por", "area", "item", "de", "para", "observacao"]].notna(), None).to_dict("records"),
        className="ag-theme-quartz", style={"height": 480},
        defaultColDef={"sortable": True, "resizable": True, "filter": True},
        columnDefs=[{"field": "quando", "headerName": "Quando", "width": 140}, {"field": "por", "headerName": "Quem",
                                                                               "width": 130},
                    {"field": "area", "headerName": "Área", "width": 110},
                    {"field": "item", "headerName": "Item", "flex": 1, "tooltipField": "item"},
                    {"field": "de", "headerName": "Antes", "flex": 1, "tooltipField": "de"},
                    {"field": "para", "headerName": "Depois", "flex": 1, "tooltipField": "para"},
                    {"field": "observacao", "headerName": "Motivo", "flex": 1, "tooltipField": "observacao"}]))
