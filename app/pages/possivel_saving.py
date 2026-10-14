"""
Busca por similaridade (livre): encontra insumos parecidos dentro da categoria e compara preços.

Diferente das Oportunidades (que usam o catálogo validado), aqui o usuário monta a
comparação na hora. Mesmo assim, cada item similar é checado pelo motor de
correspondência contra o item de referência: conflito técnico ou unidade sem
conversão NÃO vêm pré-marcados.
"""
from __future__ import annotations

from datetime import date

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import Input, Output, State, callback, dcc, html, no_update

from app.components import graficos
from app.components.ui import (brl, brl_curto, cabecalho, cartao, dropdown, filtro, kpi, nota, num, pct, periodo,
                               vazio)
from app.matching.pontuacao import perfil, pontuar
from app.pages.comparativo import F_DATA
from app.pages.oportunidades import F_BRL, F_NUM, F_PCT
from app.repositories import painel_repo, suprimentos_repo
from app.services import saving
from app.services.similaridade import INDICE

F_SCORE = {"function": "params.value == null ? '' : Math.round(params.value * 100) + '%'"}

COLS_SIMILARES = [
    {"field": "descricao_completa", "headerName": "Descrição do insumo", "flex": 3, "minWidth": 280,
     "tooltipField": "descricao_completa"},
    {"field": "cod_insumo", "headerName": "Cód.", "width": 86},
    {"field": "unidade_padrao", "headerName": "Un.", "width": 70},
    {"field": "score", "headerName": "Similaridade", "width": 116, "valueFormatter": F_SCORE, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "nivel_motor", "headerName": "Compatibilidade técnica", "width": 170},
    {"field": "motivos_motor", "headerName": "Motivo", "flex": 2, "minWidth": 220, "tooltipField": "motivos_motor"},
    {"field": "n_itens", "headerName": "Compras", "width": 92, "valueFormatter": F_NUM, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "total_gasto", "headerName": "Total gasto", "width": 135, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
]
COLS_DETALHE = [
    {"field": "data_pedido", "headerName": "Data", "width": 104, "valueFormatter": F_DATA, "sort": "desc"},
    {"field": "cod_pedido", "headerName": "Pedido", "width": 90}, {"field": "cod_cotacao", "headerName": "Cotação", "width": 90},
    {"field": "descricao_completa", "headerName": "Descrição", "minWidth": 230, "flex": 2, "tooltipField": "descricao_completa"},
    {"field": "fornecedor", "headerName": "Fornecedor", "minWidth": 180, "flex": 1, "tooltipField": "fornecedor"},
    {"field": "obra", "headerName": "Obra", "minWidth": 170, "flex": 1, "tooltipField": "obra"},
    {"field": "quantidade", "headerName": "Qtd", "width": 90, "valueFormatter": F_NUM, "cellClass": "num", "type": "rightAligned"},
    {"field": "unidade", "headerName": "Un.", "width": 62},
    {"field": "preco", "headerName": "Preço unit.", "width": 120, "valueFormatter": F_BRL, "cellClass": "num", "type": "rightAligned"},
    {"field": "menor_preco_mes", "headerName": "Menor do mês", "width": 125, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "dif_vs_menor_mes_pct", "headerName": "Acima do menor", "width": 120, "valueFormatter": F_PCT,
     "cellClass": "num", "type": "rightAligned"},
    {"field": "saving_menor_mes", "headerName": "Diferença × qtd", "width": 135, "valueFormatter": F_BRL,
     "cellClass": "num", "type": "rightAligned"},
]


def layout(**_):
    try:
        cats = INDICE.categorias()
        ini, fim = suprimentos_repo.periodo_disponivel()
        obras = suprimentos_repo.obras()
    except Exception as exc:  # noqa: BLE001
        return html.Div([cabecalho("Busca por similaridade", ""), vazio(f"Erro de conexão: {exc}")])
    return html.Div([
        cabecalho("Busca por similaridade",
                  "Procure um item pela descrição, dentro da categoria, e monte a comparação de preços na hora. "
                  "O motor de correspondência marca conflitos técnicos e unidades incompatíveis.", relatorio="ps"),
        html.Div([
            filtro("Categoria", dropdown("ps-categoria", [{"label": f"{r.categoria}  ({r.n_insumos})",
                                                           "value": r.categoria} for r in cats.itertuples()],
                                         placeholder="Escolha (ou busque sem categoria)")),
            filtro("Item a buscar", html.Div([dcc.Input(id="ps-consulta", placeholder="ex.: cimento cp ii 50kg",
                                                        className="cv-input", n_submit=0, style={"minWidth": 0}),
                                              html.Button("Buscar", id="ps-buscar", className="btn btn-pri", n_clicks=0)],
                                             style={"display": "flex", "gap": 8}), "largo"),
            filtro("Unidade", dropdown("ps-unidade", placeholder="—", clearable=False), "estreito"),
            filtro("Período", periodo("ps-periodo", ini, fim), "largo"),
            filtro("Obras", dropdown("ps-obras", [{"label": r.obra or r.cod_obra, "value": r.cod_obra}
                                                  for r in obras.itertuples()], multi=True)),
            filtro("Similaridade mínima", dcc.Slider(id="ps-score", min=0.2, max=0.9, step=0.05, value=0.35,
                                                     marks={0.2: "20%", 0.5: "50%", 0.9: "90%"}), "estreito"),
        ], className="filtros"),
        html.Div(cartao("Não sabe a categoria? Clique num item para usar a categoria dele", dag.AgGrid(
            id="ps-sugestoes", rowData=[], className="ag-theme-quartz", style={"height": 250},
            columnDefs=[{"field": "descricao_completa", "headerName": "Descrição", "flex": 3},
                        {"field": "categoria", "headerName": "Categoria", "flex": 2},
                        {"field": "unidade_padrao", "headerName": "Un.", "width": 80},
                        {"field": "n_itens", "headerName": "Compras", "width": 100}],
            dashGridOptions={"rowSelection": {"mode": "singleRow", "checkboxes": False, "enableClickSelection": True}})),
            id="ps-sugestoes-box", style={"display": "none"}),
        cartao("Itens similares — marque os que entram na comparação", html.Span(id="ps-info-busca", className="cv-nota"),
               dag.AgGrid(id="ps-similares", columnDefs=COLS_SIMILARES, rowData=[], className="ag-theme-quartz",
                          defaultColDef={"sortable": True, "resizable": True, "filter": True},
                          dashGridOptions={"rowSelection": {"mode": "multiRow", "checkboxes": True, "headerCheckbox": True,
                                                            "enableClickSelection": False}, "tooltipShowDelay": 300,
                                           "rowClassRules": {"linha-atipica": "params.data.nivel_motor === 'conflito técnico'"},
                                           "localeText": {"noRowsToShow": "Faça uma busca"}},
                          style={"height": 320})),
        html.Div(id="ps-aviso"),
        dcc.Loading(html.Div(id="ps-resultado"), type="dot", color="#1B365D"),
    ])


dash.register_page(__name__, path="/busca", name="Busca por similaridade", title="Busca · Suprimentos", layout=layout)

ROTULO_NIVEL = {"alta": "compatível (alta)", "media": "revisar (média)", "baixa": "baixa confiança",
                "incompativel": "conflito técnico", "nao_comparavel": "não comparável", "referencia": "item de referência"}


@callback(Output("ps-categoria", "value"), Input("ps-sugestoes", "selectedRows"), prevent_initial_call=True)
def usar_sugestao(linhas):
    return linhas[0]["categoria"] if linhas else no_update


@callback(
    Output("ps-similares", "rowData"), Output("ps-similares", "selectedRows"), Output("ps-unidade", "options"),
    Output("ps-unidade", "value"), Output("ps-info-busca", "children"), Output("ps-sugestoes", "rowData"),
    Output("ps-sugestoes-box", "style"),
    Input("ps-buscar", "n_clicks"), Input("ps-consulta", "n_submit"), Input("ps-categoria", "value"),
    State("ps-consulta", "value"), State("ps-score", "value"), prevent_initial_call=True,
)
def buscar(_n, _s, categoria, consulta, score_min):
    esconder, mostrar = {"display": "none"}, {"display": "block"}
    consulta = (consulta or "").strip()
    if not consulta:
        return [], [], [], None, "Digite o item a buscar.", [], esconder
    if not categoria:
        sug = INDICE.sugerir(consulta)
        return [], [], [], None, "Escolha a categoria ou clique numa sugestão abaixo.", sug.to_dict("records"), \
            (mostrar if not sug.empty else esconder)
    res = INDICE.buscar(consulta, categoria, top_n=40, score_minimo=score_min or 0.35)
    painel_repo.registrar_busca(categoria, consulta, res["id_insumo"].tolist() if not res.empty else [])
    if res.empty:
        return [], [], [], None, "Nenhum insumo parecido nesta categoria. Reduza a similaridade mínima.", [], esconder
    ref = res.iloc[0]
    pref = perfil("ref", ref.id_insumo, ref.descricao_completa, categoria, ref.unidade_padrao)
    niveis, motivos = [], []
    for r in res.itertuples(index=False):
        if r.id_insumo == ref.id_insumo:
            niveis.append("referencia"); motivos.append("")
            continue
        p = pontuar(pref, perfil("x", r.id_insumo, r.descricao_completa, categoria, r.unidade_padrao))
        niveis.append(p.nivel); motivos.append("; ".join(p.motivos))
    res = res.assign(nivel_motor=[ROTULO_NIVEL[n] for n in niveis], motivos_motor=motivos, _nivel=niveis)
    unidade_ref = ref.unidade_padrao
    unidades = res.groupby("unidade_padrao")["n_itens"].sum().sort_values(ascending=False)
    linhas = res.drop(columns="_nivel").to_dict("records")
    marcadas = [l for l, n in zip(linhas, niveis) if l["unidade_padrao"] == unidade_ref
                and n in ("referencia", "alta", "media")]
    info = (f"{len(res)} parecidos em “{categoria}”. Referência: “{ref.descricao_completa}”. Pré-marcados {len(marcadas)} "
            f"na unidade “{unidade_ref}” sem conflito técnico — confira os de nível médio.")
    return (linhas, marcadas, [{"label": f"{u} ({int(n)})", "value": u} for u, n in unidades.items()], unidade_ref,
            info, [], esconder)


@callback(Output("ps-resultado", "children"), Output("ps-aviso", "children"), Input("ps-similares", "selectedRows"),
          Input("ps-unidade", "value"), Input("ps-periodo", "start_date"), Input("ps-periodo", "end_date"),
          Input("ps-obras", "value"))
def analisar(sel, unidade, ini, fim, obras):
    if not sel:
        return vazio("Busque um item e marque os similares que representam o mesmo material."), None
    fora = [s for s in sel if unidade and s["unidade_padrao"] != unidade]
    conflito = [s for s in sel if s.get("nivel_motor") == "conflito técnico"]
    ids = [s["id_insumo"] for s in sel if (not unidade or s["unidade_padrao"] == unidade)]
    avisos = []
    if fora:
        avisos.append(html.Div(f"{len(fora)} item(ns) em outra unidade ignorados — a comparação usa só “{unidade}”.",
                               className="cv-alerta yellow"))
    if conflito:
        avisos.append(html.Div(f"Atenção: {len(conflito)} item(ns) marcados têm conflito técnico com a referência. "
                               "Os preços podem não ser comparáveis.", className="cv-alerta red"))
    df = suprimentos_repo.itens_dos_insumos(ids, date.fromisoformat(ini[:10]) if ini else None,
                                            date.fromisoformat(fim[:10]) if fim else None, obras or None)
    if df.empty:
        return vazio("Sem compras para os filtros."), avisos
    df = saving.enriquecer(df)
    r = saving.resumo(df)
    u = unidade or ""
    t_forn, t_obra = saving.por_fornecedor(df), saving.por_obra(df)
    ren = {"preco_medio_pond": "preco_medio", "menor_preco": "minimo", "pedidos": "n", "total_gasto": "valor"}
    mensal = df.groupby("ano_mes").apply(lambda x: pd.Series({
        "mediana": x["preco"].median(), "minimo": x["preco"].min(),
        "media_pond": x["valor_total"].sum() / x["quantidade"].sum()}), include_groups=False).reset_index()
    return html.Div([
        html.Div([
            kpi("Total gasto", brl_curto(r.total_gasto), f"{num(r.quantidade, 1)} {u} em {r.n_itens} compras", "neutro"),
            kpi("Preço médio ponderado", f"{brl(r.preco_medio_pond)}/{u}", "", "neutro"),
            kpi("Menor preço", f"{brl(r.menor_preco)}/{u}", r.fornecedor_menor_preco[:30], "neutro"),
            kpi("Maior preço", f"{brl(r.maior_preco)}/{u}",
                f"+{pct((r.maior_preco / r.menor_preco - 1) * 100, 0)} sobre o menor" if r.menor_preco else "", "neutro"),
            kpi("Fornecedores · obras · pedidos", f"{r.n_fornecedores} · {r.n_obras} · {r.n_pedidos}", "", "neutro"),
            kpi("Diferença para o menor preço do mês", brl_curto(r.saving_menor_mes),
                f"{pct(r.saving_menor_mes / r.total_gasto * 100)} do gasto · estimativa", "destaque", tag="estimativa"),
        ], className="port-kpi-grid", style={"margin": "14px 0"}),
        cartao("Evolução mensal", dcc.Graph(figure=graficos.estatisticas_mes(mensal, u), config={"displaylogo": False}),
               fonte=f"R$/{u}", classe="grafico-card"),
        html.Div([
            cartao("Preço por fornecedor", dcc.Graph(figure=graficos.barras_preco(
                t_forn.rename(columns=ren), "fornecedor", "cod_fornecedor", u), config={"displaylogo": False}),
                classe="grafico-card"),
            cartao("Preço por obra", dcc.Graph(figure=graficos.barras_preco(
                t_obra.rename(columns=ren), "obra", "cod_obra", u), config={"displaylogo": False}), classe="grafico-card"),
        ], className="cv-grid"),
        cartao("Compras", dag.AgGrid(columnDefs=COLS_DETALHE, rowData=df.assign(
            data_pedido=df["data_pedido"].dt.strftime("%Y-%m-%d")).to_dict("records"), className="ag-theme-quartz",
            defaultColDef={"sortable": True, "resizable": True, "filter": True}, style={"height": 420},
            csvExportParams={"fileName": "busca_similaridade.csv", "columnSeparator": ";"})),
        nota("Esta tela compara o que VOCÊ marcou. Para o ranking com equivalências validadas, referência rastreável e "
             "sem dupla contagem, use Oportunidades."),
    ]), avisos


# ── Relatório em PowerPoint (botão "Gerar relatório") ────────────────────────
@callback(Output("ps-rel-down", "data"), Input("ps-rel", "n_clicks"),
          State("ps-similares", "selectedRows"),
          State("ps-unidade", "value"),
          State("ps-periodo", "start_date"),
          State("ps-periodo", "end_date"),
          State("ps-obras", "value"),
          State("ps-consulta", "value"), prevent_initial_call=True)
def gerar_relatorio(n, sel, unidade, ini, fim, obras, consulta):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    return dcc.send_bytes(rel.busca(sel, unidade, ini, fim, obras, consulta), nome_arquivo("busca_similaridade"))
