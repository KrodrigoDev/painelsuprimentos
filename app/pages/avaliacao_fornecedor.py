"""Avaliação de fornecedores: notas mês a mês (escala 0 a 4), classificação A/B/C e quem é crítico."""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from app.components import detalhe, graficos
from app.components.ui import brl, brl_curto, cabecalho, cartao, dropdown, filtro, kpi, nota, num, pct, periodo, vazio
from app.pages.oportunidades import F_BRL
from app.repositories import rpa_repo
from app.services import avaliacao as av

P = "av-dm"
F_NOTA = {"function": "params.value == null ? '' : Number(params.value).toLocaleString('pt-BR', "
                      "{minimumFractionDigits: 2, maximumFractionDigits: 2})"}
F_DELTA = {"function": "deltaNota(params.value)"}
REGRA_DELTA = {"delta-pos": "params.value > 0.0001", "delta-neg": "params.value < -0.0001"}
REGRA_NOTA = {"nota-a": "params.value != null && Math.round(params.value * 10) / 10 <= 2",
              "nota-c": "params.value != null && Math.round(params.value * 10) / 10 >= 3.5"}


def _c(campo, rotulo, formato="texto", total=False, peso=None):
    d = {"campo": campo, "rotulo": rotulo, "formato": formato, "total": total}
    if peso:
        d["peso"] = peso
    return d


COLS_FORN_EXPORT = [_c("rotulo", "Fornecedor", peso=3.4), _c("classe", "Classe", peso=0.6),
                    _c("nota", "Nota (base)", "num2", peso=0.8), _c("nota_media", "Média pond.", "num2", peso=0.8),
                    _c("nota_ultima", "Última", "num2", peso=0.7), _c("nota_pior", "Pior mês", "num2", peso=0.7),
                    _c("nota_atual", "Nota Sienge", "num2", peso=0.8), _c("avaliacoes", "Avaliações", "int", True, 0.8),
                    _c("meses_criticos", "Meses ≤ 2", "int", peso=0.7), _c("valor_comprado", "Comprado", "brl", True)]


def _fonte():
    try:
        ctl = rpa_repo.controle_avaliacao()
    except Exception:  # noqa: BLE001
        return None
    if ctl.empty:
        return None
    pos = ctl["posicao_em"].max()
    return html.Div([html.Div(f"posição Sienge: {pos:%d/%m/%Y %H:%M}" if pd.notna(pos) else ""),
                     html.Div(f"{int(ctl['conciliado'].sum())}/{len(ctl)} relatórios mensais conferidos (total e média)")])


def layout(**_):
    try:
        b = rpa_repo.avaliacoes()
    except Exception as exc:  # noqa: BLE001
        return html.Div([cabecalho("Avaliação de fornecedores", ""),
                         vazio("Tabela suprimentos.fato_avaliacao_fornecedor indisponível. Rode a DAG etl_suprimentos_rpa "
                               "(ou python main.py --etapa avaliacao_fornecedor no airflow_api_sienge). Detalhe: "
                               f"{str(exc).splitlines()[0]}")])
    if b.empty:
        return html.Div([cabecalho("Avaliação de fornecedores", ""), vazio("Sem avaliações carregadas.")])
    fim = b["mes_referencia"].max()
    ini = (fim - pd.DateOffset(months=2)).to_period("M").to_timestamp()
    forn = (b.groupby(["cod_fornecedor"]).agg(f=("fornecedor", "last"), n=("numero_avaliacoes", "sum"))
            .reset_index().sort_values("n", ascending=False))
    filtros = html.Div([
        filtro("Período (meses)", periodo("av-periodo", ini.date(), (fim + pd.offsets.MonthEnd(0)).date()), "largo"),
        filtro("Fornecedor", dropdown("av-fornecedores", [{"label": f"{r.cod_fornecedor} - {r.f}",
                                                            "value": int(r.cod_fornecedor)} for r in forn.itertuples()],
                                      multi=True), "largo"),
        filtro("Classificação", dropdown("av-classes", [{"label": v, "value": k} for k, v in av.ROTULO_CLASSE.items()],
                                         multi=True)),
        filtro("Classificar pela", dropdown("av-base", [{"label": v, "value": k} for k, v in av.BASES.items()],
                                            valor=av.BASE_PADRAO, clearable=False), "largo"),
        filtro("Mín. de avaliações", dcc.Input(id="av-min", debounce=0.6, type="number", value=1, min=1, step=1, className="cv-input"),
               "estreito"),
    ], className="filtros")
    return html.Div([
        cabecalho("Avaliação de fornecedores",
                  "Notas recebidas em medições de contratos, notas fiscais de compra e pedidos (escala 0 a 4). "
                  "A até 2,0 é crítico · B de 2,1 a 3,4 · C de 3,5 a 4,0.", _fonte(), relatorio="av"),
        filtros,
        dcc.Loading(html.Div(id="av-conteudo"), type="dot", color="#1B365D"),
        nota(html.B("Como ler: "), "a classificação usa a nota escolhida em 'Classificar pela', arredondada a 1 casa como no "
             "Sienge. O padrão é o critério atual: o fornecedor que teve algum mês na faixa A (≤ 2,0) no período é "
             "crítico. 'Média ponderada' é menos sensível a um mês ruim isolado. Médias agregadas são ponderadas pelo nº de avaliações — "
             "o Power BI usava média simples das médias. Delta = nota do mês − nota do mês avaliado anterior (mesmo que "
             "ele esteja fora do filtro). Valor comprado vem dos pedidos de compra da API (ano corrente)."),
        *detalhe.modal(P),
    ])


dash.register_page(__name__, path="/avaliacao-fornecedor", name="Avaliação fornecedor",
                   title="Avaliação de fornecedores · Suprimentos", layout=layout)
detalhe.registrar(P)


def _dados(ini, fim, fornecedores, classes, base, minimo):
    b = rpa_repo.avaliacoes()
    d = av.filtrar(b, ini, fim, fornecedores)
    forn = av.por_fornecedor(d, base or av.BASE_PADRAO, rpa_repo.compras_por_fornecedor())
    forn = forn[forn["avaliacoes"] >= int(minimo or 1)]
    if classes:
        forn = forn[forn["classe"].isin(classes)]
    d = d[d["cod_fornecedor"].isin(forn["cod_fornecedor"])]
    return b, d, forn


def _k(chave, *a, **kw):
    return detalhe.kpi_clicavel({"type": "av-kpi", "k": chave}, kpi(*a, **kw))


def _colunas_matriz(meses):
    cols = [{"field": "rotulo", "headerName": "Fornecedor", "pinned": "left", "minWidth": 280, "tooltipField": "rotulo"},
            {"field": "classe", "headerName": "Classe", "width": 84, "pinned": "left",
             "cellClassRules": {"classe-a": "params.value == 'A'", "classe-b": "params.value == 'B'",
                                "classe-c": "params.value == 'C'"}},
            {"field": "nota", "headerName": "Nota", "width": 80, "pinned": "left", "valueFormatter": F_NOTA,
             "cellClass": "num", "type": "rightAligned", "cellClassRules": REGRA_NOTA}]
    for m in meses:
        k = m.replace("-", "_")
        cols.append({"headerName": graficos.rotulo_mes(m), "marryChildren": True, "children": [
            {"field": f"n_{k}", "headerName": "Aval.", "width": 82, "cellClass": "num", "type": "rightAligned"},
            {"field": f"m_{k}", "headerName": "Média", "width": 88, "valueFormatter": F_NOTA, "cellClass": "num",
             "type": "rightAligned", "cellClassRules": REGRA_NOTA},
            {"field": f"d_{k}", "headerName": "Delta", "width": 92, "valueFormatter": F_DELTA, "cellClass": "num",
             "type": "rightAligned", "cellClassRules": REGRA_DELTA},
        ]})
    cols += [{"field": "nota_atual", "headerName": "Nota Sienge", "width": 108, "valueFormatter": F_NOTA,
              "cellClass": "num", "type": "rightAligned", "headerTooltip": "Nota acumulada do Sienge (último relatório)"},
             {"field": "meses_criticos", "headerName": "Meses ≤ 2", "width": 98, "cellClass": "num",
              "type": "rightAligned"},
             {"field": "valor_comprado", "headerName": "Comprado (pedidos)", "width": 150, "valueFormatter": F_BRL,
              "cellClass": "num", "type": "rightAligned"}]
    return cols


@callback(Output("av-conteudo", "children"), Input("av-periodo", "start_date"), Input("av-periodo", "end_date"),
          Input("av-fornecedores", "value"), Input("av-classes", "value"), Input("av-base", "value"),
          Input("av-min", "value"))
def atualizar(ini, fim, fornecedores, classes, base, minimo):
    b, d, forn = _dados(ini, fim, fornecedores, classes, base, minimo)
    if forn.empty:
        return vazio("Nenhum fornecedor avaliado com os filtros atuais.")
    r = av.resumo(d, forn)
    m = av.mensal(d)
    kpis = html.Div([
        _k("fornecedores", "Fornecedores avaliados", num(r["fornecedores"]), f"{av.BASES[base or av.BASE_PADRAO].lower()}",
           "neutro"),
        _k("avaliacoes", "Avaliações realizadas", num(r["avaliacoes"]), f"{len(m)} mês(es)", "neutro"),
        _k("media", "Nota média (ponderada)", num(r["media"], 2), f"mediana dos fornecedores {num(r['mediana'], 2)}",
           "neutro"),
        _k("criticos", "Fornecedores críticos (A)", num(r["a"]), f"{pct(r['pct_a'], 1)} dos avaliados · nota ≤ 2,0",
           "kpi-alta neutro" if r["a"] else "neutro"),
        _k("atencao", "Em atenção (B)", num(r["b"]), f"nota de 2,1 a 3,4 · {num(r['c'])} na classe C", "neutro"),
        _k("compras_criticos", "Comprado de críticos", brl_curto(r["valor_criticos"]),
           f"{num(r['criticos_com_compra'])} fornecedor(es) A com pedidos", "neutro"),
    ], className="port-kpi-grid", style={"marginBottom": 14, "gridTemplateColumns": "repeat(6, minmax(0, 1fr))"})
    graf = html.Div([
        cartao("Avaliações por mês", dcc.Graph(figure=graficos.avaliacoes_mes(m), config={"displaylogo": False}),
               classe="grafico-card"),
        cartao("Nota média por mês", dcc.Graph(figure=graficos.nota_mes(m), config={"displaylogo": False}),
               html.Span("ponderada pelo nº de avaliações · faixa vermelha = crítico (≤ 2,0), verde = C (≥ 3,5)",
                         className="cv-nota"), classe="grafico-card"),
        cartao("Fornecedores por classe", dcc.Graph(figure=graficos.classes_barra(forn), config={"displaylogo": False}),
               classe="grafico-card"),
    ], className="cv-grid tres")
    risco = cartao("Nota × valor comprado", dcc.Graph(figure=graficos.matriz_risco(forn), config={"displaylogo": False}),
                   html.Span("Cada ponto é um fornecedor (tamanho = nº de avaliações). À esquerda e no alto: nota baixa e "
                             "muito volume comprado — prioridade para plano de ação.", className="cv-nota"),
                   fonte="pedidos de compra da API", classe="grafico-card")

    lim = 600
    fsel = forn.head(lim)
    mat, meses = av.matriz(b, d, fsel["cod_fornecedor"].tolist())
    linhas = fsel.merge(mat, on="cod_fornecedor", how="left") if len(mat) else fsel
    total = av.total_matriz(d, fsel["cod_fornecedor"].tolist(), meses)
    grade = cartao("Avaliações por fornecedor e mês", dag.AgGrid(
        id="av-grade", columnDefs=_colunas_matriz(meses), rowData=_registros(linhas), className="ag-theme-quartz",
        defaultColDef={"sortable": True, "resizable": True, "filter": True},
        dashGridOptions={"rowSelection": {"mode": "singleRow", "checkboxes": False, "enableClickSelection": True},
                         "pinnedBottomRowData": [total], "tooltipShowDelay": 300, "enableCellTextSelection": True,
                         "localeText": {"noRowsToShow": "Sem fornecedores"}},
        csvExportParams={"fileName": "avaliacao_fornecedores.csv", "columnSeparator": ";"}, style={"height": 520}),
        html.Span((f"Mostrando {lim} de {len(forn)} fornecedores (pior nota primeiro). " if len(forn) > lim else
                   "Ordenado da pior nota para a melhor. ") + "Clique num fornecedor para ver todo o histórico dele.",
                  className="cv-nota"))
    return html.Div([kpis, graf, risco, grade])


def _registros(df: pd.DataFrame):
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].dt.strftime("%Y-%m-%d")
    return d.astype(object).where(d.notna(), None).to_dict("records")


@callback(*detalhe.saidas(P), Input({"type": "av-kpi", "k": ALL}, "n_clicks"), Input("av-grade", "selectedRows"),
          State("av-periodo", "start_date"), State("av-periodo", "end_date"), State("av-fornecedores", "value"),
          State("av-classes", "value"), State("av-base", "value"), State("av-min", "value"), prevent_initial_call=True)
def decompor(_c_, linhas, ini, fim, fornecedores, classes, base, minimo):
    if not ctx.triggered or not ctx.triggered[0].get("value"):
        return (no_update,) * 5
    b, d, forn = _dados(ini, fim, fornecedores, classes, base, minimo)
    per = f"{pd.Timestamp(ini):%m/%Y} a {pd.Timestamp(fim):%m/%Y}" if ini and fim else "todo o período"
    gatilho = ctx.triggered_id

    if gatilho == "av-grade":
        o = linhas[0]
        if not o.get("cod_fornecedor"):
            return (no_update,) * 5
        h = b[b["cod_fornecedor"] == o["cod_fornecedor"]].sort_values("mes_referencia", ascending=False).copy()
        h["mes"] = h["mes_referencia"].dt.strftime("%m/%Y")
        h["classe"] = av.classificar(h["avaliacao_periodo"]).values
        cols = [_c("mes", "Mês", peso=0.7), _c("numero_avaliacoes", "Avaliações", "int", True, 0.8),
                _c("avaliacao_periodo", "Nota do mês", "num2", peso=0.8), _c("classe", "Classe do mês", peso=0.8),
                _c("avaliacao_atual", "Nota Sienge (acumulada)", "num2", peso=1.1)]
        comp = (f" · comprado {brl(o['valor_comprado'], 2)} em {int(o['pedidos'] or 0)} pedido(s)"
                if o.get("valor_comprado") else "")
        return detalhe.abrir(o["rotulo"], f"histórico completo · {len(h)} mês(es) avaliados{comp}", h, cols,
                             "Escala 0 a 4: A até 2,0 (crítico) · B 2,1 a 3,4 · C 3,5 a 4,0.")

    k = gatilho["k"]
    if k in ("fornecedores", "media"):
        return detalhe.abrir("Fornecedores avaliados", f"{len(forn)} fornecedor(es) · {per} · nota-base: "
                             f"{av.BASES[base or av.BASE_PADRAO].lower()}", forn, COLS_FORN_EXPORT)
    if k == "avaliacoes":
        mm = av.mensal(d)
        mm["mes"] = [graficos.rotulo_mes(x) for x in mm["ano_mes"]]
        cols = [_c("mes", "Mês", peso=0.8), _c("avaliacoes", "Avaliações", "int", True), _c("fornecedores", "Fornecedores", "int"),
                _c("media", "Nota média (pond.)", "num2"), _c("criticos", "Fornecedores com nota ≤ 2", "int", True)]
        return detalhe.abrir("Avaliações realizadas", f"{int(mm['avaliacoes'].sum())} avaliações · {per}", mm, cols)
    if k in ("criticos", "atencao", "compras_criticos"):
        cl = "B" if k == "atencao" else "A"
        sel = forn[forn["classe"] == cl]
        if k == "compras_criticos":
            sel = sel[sel["valor_comprado"].fillna(0) > 0].sort_values("valor_comprado", ascending=False)
        titulo = {"criticos": "Fornecedores críticos (A)", "atencao": "Fornecedores em atenção (B)",
                  "compras_criticos": "Compras com fornecedores críticos"}[k]
        return detalhe.abrir(titulo, f"{len(sel)} fornecedor(es) · {per} · nota-base: {av.BASES[base or av.BASE_PADRAO].lower()}",
                             sel, COLS_FORN_EXPORT,
                             "Valor comprado = pedidos de compra da API (ano corrente), todos os status exceto cancelado.")
    return (no_update,) * 5


# ── Relatório em PowerPoint (botão "Gerar relatório") ────────────────────────
@callback(Output("av-rel-down", "data"), Input("av-rel", "n_clicks"),
          State("av-periodo", "start_date"),
          State("av-periodo", "end_date"),
          State("av-fornecedores", "value"),
          State("av-classes", "value"),
          State("av-base", "value"),
          State("av-min", "value"), prevent_initial_call=True)
def gerar_relatorio(n, ini, fim, fornecedores, classes, base, minimo):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    return dcc.send_bytes(rel.avaliacao(ini, fim, fornecedores, classes, base, minimo), nome_arquivo("avaliacao_fornecedores"))
