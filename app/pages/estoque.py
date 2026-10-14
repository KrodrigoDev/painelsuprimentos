"""Estoque de obras: quanto há em estoque, onde está e quais itens concentram o valor."""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from app.components import detalhe, graficos
from app.components.ui import brl, brl_curto, cabecalho, cartao, dropdown, filtro, kpi, nota, num, pct, vazio
from app.pages.oportunidades import F_BRL, F_NUM, F_PCT
from app.repositories import rpa_repo
from app.services import estoque as es

P = "es-dm"


def _c(campo, rotulo, formato="texto", total=False, peso=None):
    d = {"campo": campo, "rotulo": rotulo, "formato": formato, "total": total}
    if peso:
        d["peso"] = peso
    return d


COLS_ITENS_EXPORT = [_c("centro_rotulo", "Centro de custo", peso=2.4), _c("descricao_completa", "Insumo", peso=3.4),
                     _c("grupo_rotulo", "Grupo", peso=1.8), _c("unidade", "Un.", peso=0.5),
                     _c("quantidade", "Quantidade", "num2"), _c("custo_medio", "Custo médio", "brl4"),
                     _c("valor_estoque", "Valor em estoque", "brl", True, 1.2), _c("situacao", "Situação", peso=0.7)]
COLS_AGR = {
    "segmento": "Segmento", "centro_rotulo": "Centro de custo", "grupo_rotulo": "Grupo de insumo", "analista": "Analista",
}

COL_GRUPOS = [
    {"field": "grupo_rotulo", "headerName": "Grupo de insumo", "minWidth": 300, "flex": 2, "tooltipField": "grupo_rotulo",
     "pinned": "left"},
    {"field": "posicoes", "headerName": "Itens com saldo", "width": 130, "cellClass": "num", "type": "rightAligned"},
    {"field": "insumos", "headerName": "Insumos", "width": 100, "cellClass": "num", "type": "rightAligned"},
    {"field": "centros", "headerName": "Centros de custo", "width": 135, "cellClass": "num", "type": "rightAligned"},
    {"field": "valor", "headerName": "Valor em estoque", "width": 160, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned", "sort": "desc"},
    {"field": "pct", "headerName": "% do valor", "width": 110, "valueFormatter": F_PCT, "cellClass": "num",
     "type": "rightAligned"},
]
COL_ITENS = [
    {"field": "centro_rotulo", "headerName": "Centro de custo", "minWidth": 220, "flex": 1, "tooltipField": "centro_rotulo"},
    {"field": "descricao_completa", "headerName": "Insumo", "minWidth": 300, "flex": 2, "tooltipField": "descricao_completa"},
    {"field": "grupo_rotulo", "headerName": "Grupo", "minWidth": 180, "tooltipField": "grupo_rotulo"},
    {"field": "segmento", "headerName": "Segmento", "width": 120},
    {"field": "analista", "headerName": "Analista", "width": 140},
    {"field": "unidade", "headerName": "Un.", "width": 64},
    {"field": "quantidade", "headerName": "Quantidade", "width": 115, "valueFormatter": F_NUM, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "custo_medio", "headerName": "Custo médio", "width": 120, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "valor_estoque", "headerName": "Valor em estoque", "width": 145, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned", "sort": "desc"},
    {"field": "estoque_minimo", "headerName": "Mínimo", "width": 95, "valueFormatter": F_NUM, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "situacao", "headerName": "Situação", "width": 100},
]

_PREP: dict = {}


def base() -> pd.DataFrame:
    """Preparado uma vez por carga do cache (sem escopo) e filtrado pelo escopo do usuário a cada chamada."""
    bruta = rpa_repo.estoque_bruto()
    if _PREP.get("bruta") is not bruta:
        _PREP.update(bruta=bruta, pronta=es.preparar(bruta))
    return rpa_repo.escopar_estoque(_PREP["pronta"])


def situacao_carga():
    """(texto da fonte, aviso de carga incompleta ou None)."""
    try:
        ctl = rpa_repo.controle_estoque()
    except Exception:  # noqa: BLE001
        return None, None
    if ctl.empty:
        return None, None
    pos = ctl["modificado_em"].max()
    ok = ctl[ctl["situacao"] == "ok"]
    fonte = html.Div([html.Div(f"relatório Sienge de {pos:%d/%m/%Y %H:%M}" if pd.notna(pos) else ""),
                      html.Div(f"{len(ok)} páginas · {int(ok['conciliado'].sum())} conferidas com o total da página")])
    aviso = None
    if not bool(ctl["carga_completa"].iat[0]):
        vazias = ctl.loc[ctl["situacao"] == "vazia", "pagina"].astype(int).tolist()
        aus = ctl["paginas_ausentes"].iat[0] or ""
        aviso = html.Div([html.B("Estoque incompleto: "),
                          f"o RPA trouxe página(s) vazia(s) {vazias}" + (f" e não trouxe {aus}" if aus else "") +
                          f" — cada página tem até 5.000 linhas, então os valores abaixo estão subestimados. "
                          "Rode de novo o extract do estoque no projeto legado."], className="alerta-carga")
    return fonte, aviso


def layout(**_):
    try:
        b = base()
    except Exception as exc:  # noqa: BLE001
        return html.Div([cabecalho("Estoque de obras", ""),
                         vazio("Tabela suprimentos.fato_estoque_posicao indisponível. Rode a DAG etl_suprimentos_rpa "
                               f"(ou python main.py --etapa estoque no airflow_api_sienge). Detalhe: {str(exc).splitlines()[0]}")])
    fonte, aviso = situacao_carga()
    s = b[b["com_saldo"]]
    centros = s.groupby(["cod_centro_custo", "centro_rotulo"])["valor_estoque"].sum().reset_index() \
        .sort_values("valor_estoque", ascending=False)
    grupos = s.groupby("grupo_rotulo")["valor_estoque"].sum().sort_values(ascending=False).index
    filtros = html.Div([
        filtro("Obra / centro de custo", dropdown("es-centros", [{"label": r.centro_rotulo, "value": int(r.cod_centro_custo)}
                                                                 for r in centros.itertuples()], multi=True), "largo"),
        filtro("Segmento", dropdown("es-segmentos", [{"label": x, "value": x} for x in sorted(b["segmento"].unique())],
                                    multi=True)),
        filtro("Grupo de insumo", dropdown("es-grupos", [{"label": g, "value": g} for g in grupos], multi=True), "largo"),
        filtro("Analista", dropdown("es-analistas", [{"label": x, "value": x} for x in sorted(b["analista"].unique())],
                                    multi=True)),
        filtro("Descrição do insumo", dcc.Input(id="es-texto", debounce=True, className="cv-input",
                                                placeholder="código ou palavras"), "largo"),
        filtro("Situação", dropdown("es-situacao", [{"label": x.title(), "value": x} for x in
                                                    sorted(b["situacao"].dropna().unique())], multi=True), "estreito"),
    ], className="filtros")
    return html.Div([
        cabecalho("Estoque de obras", "Quanto há em estoque nas obras e nos centros de custo, onde está e quais itens "
                  "concentram o valor (só itens com saldo).", fonte, relatorio="es"),
        aviso, filtros,
        dcc.Loading(html.Div(id="es-conteudo"), type="dot", color="#1B365D"),
        nota(html.B("Como ler: "), "fonte = consulta de estoque de obras do Sienge (exportada pelo RPA em páginas de 5.000 "
             "linhas, cada uma conferida com o total da página). O relatório vem por apropriação (unidade construtiva + "
             "item): o valor em estoque soma o custo de cada apropriação, mas a quantidade é o saldo físico do insumo e "
             "não é somada entre apropriações — o painel antigo somava e inflava as quantidades. Quantidades de insumos "
             "diferentes não são somadas entre si (kg, m, un). Segmento vem do cadastro de centros de custo; analista, da "
             "planilha de analistas por grupo e tipo de obra."),
        *detalhe.modal(P),
    ])


dash.register_page(__name__, path="/estoque", name="Estoque", title="Estoque · Suprimentos", layout=layout)
detalhe.registrar(P)


def dados(centros, segmentos, grupos, analistas, texto, situacao):
    b = base()
    d = es.filtrar(b, centros, segmentos, grupos, analistas, situacao, texto, so_saldo=False)
    return b, d


def _k(chave, *a, **kw):
    return detalhe.kpi_clicavel({"type": "es-kpi", "k": chave}, kpi(*a, **kw))


def _registros(df):
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].dt.strftime("%Y-%m-%d")
    return d.astype(object).where(d.notna(), None).to_dict("records")


@callback(Output("es-conteudo", "children"), Input("es-centros", "value"), Input("es-segmentos", "value"),
          Input("es-grupos", "value"), Input("es-analistas", "value"), Input("es-texto", "value"),
          Input("es-situacao", "value"))
def atualizar(centros, segmentos, grupos, analistas, texto, situacao):
    b, d = dados(centros, segmentos, grupos, analistas, texto, situacao)
    if not d["com_saldo"].any():
        return vazio("Nenhum item com saldo nos filtros atuais.")
    r = es.resumo(d, d)
    kpis = html.Div([
        _k("valor", "Valor total em estoque", brl(r["valor"], 2), f"{num(r['posicoes'])} itens com saldo", "neutro"),
        _k("insumos", "Insumos com saldo", num(r["insumos"]), f"em {num(r['centros'])} centros de custo", "neutro"),
        _k("concentracao", "Concentração", pct(r["pct_top20"], 0), "do valor está em 20% dos itens", "neutro"),
        _k("minimo", "Abaixo do estoque mínimo", num(r["abaixo_minimo"]),
           f"{num(r['acima_maximo'])} acima do máximo", "kpi-alta neutro" if r["abaixo_minimo"] else "neutro"),
        _k("inativos", "Inativos", num(r["inativos"]), f"itens desativados no Sienge · {num(r['inativos_com_saldo'])} com saldo",
           "neutro"),
        _k("top10", "10 maiores itens", brl_curto(r["top10_valor"]),
           f"{pct(r['top10_valor'] / r['valor'] * 100, 1)} do valor em estoque", "neutro"),
    ], className="port-kpi-grid", style={"marginBottom": 14, "gridTemplateColumns": "repeat(6, minmax(0, 1fr))"})
    seg = es.por(d, "segmento")
    cen = es.por(d, "centro_rotulo").head(15)
    gru = es.por(d, "grupo_rotulo")
    hover = "%{y}<br>R$ %{x:,.2f} · %{customdata[0]:.1f}% do valor<br>%{customdata[1]} itens com saldo<extra></extra>"
    graf = html.Div([
        cartao("Valor em estoque por segmento", dcc.Graph(figure=graficos.barras_h(
            seg["segmento"], seg["valor"], "Valor", cor="#1B365D", custom=seg[["pct", "posicoes"]].to_numpy(),
            hover=hover), config={"displaylogo": False}), fonte="itens com saldo", classe="grafico-card"),
        cartao("Valor por grupo de insumo", dcc.Graph(figure=graficos.barras_h(
            gru["grupo_rotulo"].head(12), gru["valor"].head(12), "Valor", cor=graficos.SERIES[2],
            custom=gru[["pct", "posicoes"]].head(12).to_numpy(), hover=hover), config={"displaylogo": False}),
            fonte="12 maiores", classe="grafico-card"),
    ], className="cv-grid", style={"gridTemplateColumns": "minmax(0,1fr) minmax(0,1.4fr)"})
    graf_cc = cartao("Valor por centro de custo", dcc.Graph(figure=graficos.barras_h(
        cen["centro_rotulo"], cen["valor"], "Valor", custom=cen[["pct", "posicoes"]].to_numpy(), hover=hover),
        config={"displaylogo": False}), fonte="15 maiores", classe="grafico-card")
    grade_g = cartao("Por grupo de insumo", dag.AgGrid(
        id="es-grade-grupos", columnDefs=COL_GRUPOS, rowData=_registros(gru), className="ag-theme-quartz",
        defaultColDef={"sortable": True, "resizable": True, "filter": True},
        dashGridOptions={"rowSelection": {"mode": "singleRow", "checkboxes": False, "enableClickSelection": True},
                         "tooltipShowDelay": 300},
        csvExportParams={"fileName": "estoque_por_grupo.csv", "columnSeparator": ";"}, style={"height": 380}),
        html.Span("Clique num grupo para ver os itens dele (com exportação).", className="cv-nota"))
    it = es.itens(d)
    grade_i = cartao("Itens com saldo", dag.AgGrid(
        id="es-grade-itens", columnDefs=COL_ITENS, rowData=_registros(it.head(5000)), className="ag-theme-quartz",
        defaultColDef={"sortable": True, "resizable": True, "filter": True},
        dashGridOptions={"tooltipShowDelay": 300, "enableCellTextSelection": True, "pagination": True,
                         "paginationPageSize": 50, "localeText": {"page": "Página", "of": "de", "to": "a",
                                                                  "pageSizeSelectorLabel": "Linhas por página:"}},
        csvExportParams={"fileName": "estoque_itens.csv", "columnSeparator": ";"}, style={"height": 470}),
        html.Span(f"{num(len(it))} itens (centro de custo × insumo/detalhe/marca), maior valor primeiro"
                  + (" — mostrando 5.000; use os filtros ou exporte." if len(it) > 5000 else "."), className="cv-nota"))
    return html.Div([kpis, graf, graf_cc, grade_g, grade_i])


@callback(*detalhe.saidas(P), Input({"type": "es-kpi", "k": ALL}, "n_clicks"), Input("es-grade-grupos", "selectedRows"),
          State("es-centros", "value"), State("es-segmentos", "value"), State("es-grupos", "value"),
          State("es-analistas", "value"), State("es-texto", "value"), State("es-situacao", "value"),
          prevent_initial_call=True)
def decompor(_c_, linhas, centros, segmentos, grupos, analistas, texto, situacao):
    if not ctx.triggered or not ctx.triggered[0].get("value"):
        return (no_update,) * 5
    b, d = dados(centros, segmentos, grupos, analistas, texto, situacao)
    it = es.itens(d)
    if ctx.triggered_id == "es-grade-grupos":
        g = linhas[0]["grupo_rotulo"]
        sel = it[it["grupo_rotulo"] == g]
        return detalhe.abrir(g, f"{num(len(sel))} itens com saldo · {brl(sel['valor_estoque'].sum(), 2)}", sel,
                             COLS_ITENS_EXPORT)
    k = ctx.triggered_id["k"]
    if k == "valor":
        seg = es.por(d, "segmento")
        cols = [_c("segmento", "Segmento", peso=2), _c("posicoes", "Itens com saldo", "int", True),
                _c("insumos", "Insumos", "int"), _c("centros", "Centros", "int"),
                _c("valor", "Valor em estoque", "brl", True, 1.3), _c("pct", "% do valor", "pct", True)]
        return detalhe.abrir("Valor total em estoque", f"{len(seg)} segmento(s) · {num(len(it))} itens com saldo", seg, cols,
                             "Valor = Σ custo médio × quantidade apropriada (igual ao total do relatório do Sienge).")
    if k == "insumos":
        g = it.groupby(["cod_insumo", "insumo", "unidade"], dropna=False).agg(
            quantidade=("quantidade", "sum"), valor=("valor_estoque", "sum"), centros=("cod_centro_custo", "nunique"),
            detalhes=("cod_detalhe", "nunique")).reset_index().sort_values("valor", ascending=False)
        cols = [_c("cod_insumo", "Código", "int", peso=0.6), _c("insumo", "Insumo", peso=3.4), _c("unidade", "Un.", peso=0.5),
                _c("detalhes", "Detalhes", "int", peso=0.6), _c("centros", "Centros", "int", peso=0.6),
                _c("quantidade", "Quantidade", "num2"), _c("valor", "Valor em estoque", "brl", True, 1.2)]
        return detalhe.abrir("Insumos com saldo", f"{num(len(g))} insumo(s) · quantidade somada só dentro do mesmo insumo",
                             g, cols)
    if k == "concentracao":
        top = it[it["pct_acumulado"] - it["pct_valor"] < 80]
        cols = COLS_ITENS_EXPORT + [_c("pct_acumulado", "% acumulado", "pct", peso=0.8)]
        return detalhe.abrir("Itens que somam 80% do valor", f"{num(len(top))} de {num(len(it))} itens com saldo", top, cols)
    if k == "minimo":
        sel = d[d["abaixo_minimo"]].assign(falta=lambda x: x["estoque_minimo"] - x["quantidade"])
        cols = [_c("centro_rotulo", "Centro de custo", peso=2.4), _c("descricao_completa", "Insumo", peso=3.4),
                _c("unidade", "Un.", peso=0.5), _c("quantidade", "Saldo", "num2"), _c("estoque_minimo", "Mínimo", "num2"),
                _c("falta", "Falta para o mínimo", "num2")]
        return detalhe.abrir("Abaixo do estoque mínimo", f"{len(sel)} item(ns) com mínimo cadastrado e saldo abaixo dele",
                             sel, cols)
    if k == "inativos":
        sel = d[d["situacao"] != "ATIVO"].sort_values(["com_saldo", "valor_estoque"], ascending=False)
        return detalhe.abrir("Itens inativos no Sienge", f"{num(len(sel))} item(ns) · {num(int(sel['com_saldo'].sum()))} "
                             "ainda com saldo", sel, COLS_ITENS_EXPORT)
    if k == "top10":
        sel = it.head(10)
        return detalhe.abrir("10 maiores itens em estoque", f"{brl(sel['valor_estoque'].sum(), 2)} · "
                             f"{pct(sel['valor_estoque'].sum() / it['valor_estoque'].sum() * 100, 1)} do valor", sel,
                             COLS_ITENS_EXPORT)
    return (no_update,) * 5


def _relatorio_estoque(centros, segmentos, grupos, analistas, texto, situacao):
    from app.relatorios import paginas as rel
    _, d = dados(centros, segmentos, grupos, analistas, texto, situacao)
    nomes = {}
    if centros:
        nomes["centros"] = d.drop_duplicates("cod_centro_custo")["centro_rotulo"].tolist()
    filtros = rel._filtros(segmentos=segmentos, grupos=grupos, analistas=analistas, busca=texto, situação=situacao,
                           **nomes)
    _, aviso = situacao_carga()
    incompleto = None
    if aviso is not None:
        incompleto = "ATENÇÃO: carga incompleta — o RPA trouxe página(s) vazia(s); os valores estão subestimados."
    pos = rpa_repo.controle_estoque()["modificado_em"].max()
    return rel.estoque(d, f"Posição de {pos:%d/%m/%Y} · {filtros}" if pd.notna(pos) else filtros, incompleto)


# ── Relatório em PowerPoint (botão "Gerar relatório") ────────────────────────
@callback(Output("es-rel-down", "data"), Input("es-rel", "n_clicks"),
          State("es-centros", "value"),
          State("es-segmentos", "value"),
          State("es-grupos", "value"),
          State("es-analistas", "value"),
          State("es-texto", "value"),
          State("es-situacao", "value"), prevent_initial_call=True)
def gerar_relatorio(n, centros, segmentos, grupos, analistas, texto, situacao):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    return dcc.send_bytes(_relatorio_estoque(centros, segmentos, grupos, analistas, texto, situacao), nome_arquivo("estoque"))
