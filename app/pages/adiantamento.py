"""Adiantamentos a fornecedores: quanto foi adiantado, quanto já foi abatido (entregue/faturado) e o que falta."""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from app.components import detalhe, graficos
from app.components.ui import brl, brl_curto, cabecalho, cartao, dropdown, filtro, kpi, nota, num, pct, periodo, vazio
from app.pages.oportunidades import F_BRL, F_NUM, F_PCT
from app.repositories import rpa_repo
from app.services import adiantamento as ad

F_DATA = {"function": "dataBR(params.value)"}
P = "ad-dm"


def _c(campo, rotulo, formato="texto", total=False, peso=None):
    d = {"campo": campo, "rotulo": rotulo, "formato": formato, "total": total}
    if peso:
        d["peso"] = peso
    return d


COL_DOCS = [
    {"field": "empresa", "headerName": "Empresa", "minWidth": 190, "flex": 1, "tooltipField": "empresa"},
    {"field": "credor", "headerName": "Credor", "minWidth": 220, "flex": 2, "tooltipField": "credor", "pinned": "left"},
    {"field": "documento_vinculado", "headerName": "Doc. vinculado", "width": 140},
    {"field": "tipo_vinculo", "headerName": "Vínculo", "width": 130},
    {"field": "primeiro_adiantamento", "headerName": "1º adiantamento", "width": 130, "valueFormatter": F_DATA},
    {"field": "ultimo_movimento", "headerName": "Último mov.", "width": 120, "valueFormatter": F_DATA},
    {"field": "adiantado", "headerName": "Adiantado", "width": 135, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "abatido", "headerName": "Abatido", "width": 135, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "saldo", "headerName": "Saldo a abater", "width": 140, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned", "sort": "desc"},
    {"field": "pct_abatido", "headerName": "% abatido", "width": 105, "valueFormatter": F_PCT, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "dias_em_aberto", "headerName": "Dias em aberto", "width": 120, "valueFormatter": F_NUM,
     "cellClass": "num", "type": "rightAligned"},
    {"field": "situacao", "headerName": "Situação", "width": 150},
]

COL_MOVS = [
    {"field": "data_movimento", "headerName": "Data", "width": 110, "valueFormatter": F_DATA, "sort": "desc"},
    {"field": "credor", "headerName": "Credor", "minWidth": 220, "flex": 2, "tooltipField": "credor"},
    {"field": "empresa", "headerName": "Empresa", "minWidth": 180, "flex": 1, "tooltipField": "empresa"},
    {"field": "documento_vinculado", "headerName": "Doc. vinculado", "width": 135},
    {"field": "documento", "headerName": "Documento", "width": 140},
    {"field": "tipo_movimento", "headerName": "Tipo mov.", "width": 140},
    {"field": "valor", "headerName": "Valor", "width": 130, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "saldo_documento", "headerName": "Saldo do doc.", "width": 135, "valueFormatter": F_BRL,
     "cellClass": "num", "type": "rightAligned"},
    {"field": "data_vencimento", "headerName": "Vencimento", "width": 115, "valueFormatter": F_DATA},
    {"field": "observacao", "headerName": "Observação", "minWidth": 260, "flex": 2, "tooltipField": "observacao"},
]

COLS_DOC_EXPORT = [_c("empresa", "Empresa", peso=2.2), _c("credor", "Credor", peso=2.8),
                   _c("documento_vinculado", "Doc. vinculado", peso=1.2), _c("tipo_vinculo", "Vínculo", peso=1.1),
                   _c("primeiro_adiantamento", "1º adiant.", "data", peso=0.9),
                   _c("adiantado", "Adiantado", "brl", True), _c("abatido", "Abatido", "brl", True),
                   _c("saldo", "Saldo a abater", "brl", True, 1.1), _c("dias_em_aberto", "Dias", "int", peso=0.6)]
COLS_MOV_EXPORT = [_c("data_movimento", "Data", "data", peso=0.9), _c("credor", "Credor", peso=2.6),
                   _c("empresa", "Empresa", peso=2), _c("documento_vinculado", "Doc. vinculado", peso=1.1),
                   _c("documento", "Documento", peso=1.2), _c("tipo_movimento", "Tipo mov.", peso=1.1),
                   _c("valor", "Valor", "brl", True), _c("saldo_documento", "Saldo do doc.", "brl"),
                   _c("observacao", "Observação", peso=3)]


def _cabecalho_fonte():
    try:
        ctl = rpa_repo.controle_adiantamento()
    except Exception:  # noqa: BLE001
        return None
    if ctl.empty:
        return None
    carregados = ctl[ctl["situacao"] == "carregado"]
    pos = carregados["posicao_em"].max()
    ok = int(carregados["conciliado"].sum())
    ign = int((ctl["situacao"] != "carregado").sum())
    return html.Div([
        html.Div(f"posição Sienge: {pos:%d/%m/%Y %H:%M}" if pd.notna(pos) else "posição: —"),
        html.Div(f"{ok}/{len(carregados)} relatórios conferidos com o total do Sienge"
                 + (f" · {ign} ignorado(s)" if ign else ""), title="; ".join(ctl.loc[ctl["situacao"] != "carregado",
                                                                                     "situacao"])),
    ])


def layout(**_):
    try:
        b = rpa_repo.adiantamentos()
    except Exception as exc:  # noqa: BLE001
        return html.Div([cabecalho("Adiantamentos a fornecedores", ""),
                         vazio("Tabela suprimentos.fato_adiantamento indisponível. Rode a DAG etl_suprimentos_rpa "
                               f"(ou python main.py --etapa adiantamento no airflow_api_sienge). Detalhe: "
                               f"{str(exc).splitlines()[0]}")])
    if b.empty:
        return html.Div([cabecalho("Adiantamentos a fornecedores", ""), vazio("Sem movimentações carregadas.")])
    emp = b.drop_duplicates("cod_empresa").sort_values("empresa")
    cred = b.groupby(["cod_credor", "credor"])["valor"].sum().reset_index().sort_values("valor", ascending=False)
    filtros = html.Div([
        filtro("Data do movimento", periodo("ad-periodo", b["data_movimento"].min().date(),
                                            b["data_movimento"].max().date()), "largo"),
        filtro("Empresa", dropdown("ad-empresas", [{"label": r.empresa, "value": int(r.cod_empresa)}
                                                    for r in emp.itertuples()], multi=True)),
        filtro("Fornecedor (credor)", dropdown("ad-credores", [{"label": r.credor, "value": int(r.cod_credor)}
                                                                for r in cred.itertuples()], multi=True)),
        filtro("Tipo de movimento", dropdown("ad-tipos", [{"label": t, "value": t} for t in
                                                          sorted(b["tipo_movimento"].unique())], multi=True), "estreito"),
        filtro("Vínculo", dropdown("ad-vinculos", [{"label": t, "value": t} for t in
                                                   sorted(b["tipo_vinculo"].unique())], multi=True), "estreito"),
        filtro("Documento vinculado", dcc.Input(id="ad-doc", placeholder="nº do pedido ou contrato", debounce=True,
                                                className="cv-input")),
    ], className="filtros")
    return html.Div([
        cabecalho("Adiantamentos a fornecedores",
                  "O que foi pago antes da entrega, quanto já foi abatido por nota fiscal/medição e o que ainda "
                  "está com o fornecedor.", _cabecalho_fonte(), relatorio="ad"),
        filtros,
        dcc.Loading(html.Div(id="ad-conteudo"), type="dot", color="#1B365D"),
        *detalhe.modal(P),
    ])


dash.register_page(__name__, path="/adiantamento", name="Adiantamento", title="Adiantamentos · Suprimentos",
                   layout=layout)
detalhe.registrar(P)


def _dados(ini, fim, empresas, credores, tipos, vinculos, doc):
    b = rpa_repo.adiantamentos()
    mov, posicao, ref = ad.filtrar(b, ini, fim, empresas, credores, tipos, vinculos, doc)
    docs = ad.por_documento(posicao, ref)
    return mov, posicao, ref, docs


def _barra(pct_feito: float, legenda=True):
    p = 0 if pct_feito != pct_feito else max(0.0, min(100.0, pct_feito))
    return html.Div([
        html.Div(html.Span(pct(p, 2) if p >= 8 else ""), className="barra-feito", style={"width": f"{p}%"}),
        html.Div(html.Span(pct(100 - p, 2) if legenda and 100 - p >= 8 else ""), className="barra-resta"),
    ], className="barra-progresso")


def _kpi(chave, *a, **kw):
    return detalhe.kpi_clicavel({"type": "ad-kpi", "k": chave}, kpi(*a, **kw))


@callback(Output("ad-conteudo", "children"),
          Input("ad-periodo", "start_date"), Input("ad-periodo", "end_date"), Input("ad-empresas", "value"),
          Input("ad-credores", "value"), Input("ad-tipos", "value"), Input("ad-vinculos", "value"),
          Input("ad-doc", "value"))
def atualizar(ini, fim, empresas, credores, tipos, vinculos, doc):
    mov, posicao, ref, docs = _dados(ini, fim, empresas, credores, tipos, vinculos, doc)
    if mov.empty and posicao.empty:
        return vazio("Nenhuma movimentação com os filtros atuais.")
    r = ad.resumo(mov, posicao, ref)
    pct_saldo = r["saldo"] / r["adiantado"] * 100 if r["adiantado"] else float("nan")
    kpis = html.Div([
        _kpi("adiantado", "Total adiantado", brl(r["adiantado"], 2),
             f"{num(r['n_adiantamentos'])} adiantamentos · {num(r['credores'])} credores", "neutro"),
        _kpi("abatido", "Total abatido", brl(r["abatido"], 2), f"{pct(r['pct_abatido'], 2)} do total adiantado",
             "destaque"),
        _kpi("saldo", "Saldo a abater", brl(r["saldo"], 2),
             f"posição em {ref:%d/%m/%Y} · {pct(pct_saldo, 2)} ainda não baixado", "kpi-saldo"),
        _kpi("credores", "Credores com saldo", num(r["credores_com_saldo"]),
             f"{num(r['documentos_abertos'])} documentos em aberto", "neutro"),
        _kpi("antigos", "Saldo há mais de 1 ano", brl_curto(r["saldo_mais_1_ano"]),
             "adiantado e ainda não abatido", "neutro"),
    ], className="port-kpi-grid", style={"marginBottom": 14, "gridTemplateColumns": "repeat(5, minmax(0, 1fr))"})

    realoc = (f" Realocações (saída) no período: {brl(r['realocado'], 2)} — reduzem o saldo sem nota fiscal."
              if r["realocado"] else "")
    progresso = cartao("Progresso de abatimento", _barra(r["pct_abatido"]), html.P(
        "O abatimento acontece quando o fornecedor entrega o material/serviço e a nota (ou medição) é lançada, "
        "baixando o saldo do adiantamento. Saldo alto indica fornecedores que receberam e ainda não "
        "entregaram/faturaram." + realoc, className="cv-nota"))

    vinc = ad.por_vinculo(mov, docs).set_index("tipo_vinculo")
    cards_vinc = []
    for tipo, chave in (("Contrato", "v-contrato"), ("Pedido de compra", "v-pedido")):
        if tipo not in vinc.index:
            continue
        v = vinc.loc[tipo]
        cards_vinc.append(detalhe.kpi_clicavel({"type": "ad-kpi", "k": chave}, html.Div([
            html.Div(f"Vinculado a {tipo.lower()}", className="pk-l"),
            html.Div(brl(v["adiantado"], 2), className="pk-v neutro vinc-v"),
            html.Div(f"{num(v['lancamentos'])} lançamentos · abatido {pct(v['pct_abatido'], 2)} · saldo "
                     f"{brl_curto(v['saldo'])}", className="pk-s"),
            _barra(v["pct_abatido"], legenda=False),
        ], className="port-kpi vinc-card")))

    emp = ad.por_empresa(mov, docs).head(20)
    m = ad.mensal(mov)
    idade = ad.idade_saldo(docs)
    cred = ad.por_credor(docs)
    top = cred[cred["saldo"] > ad.TOL].head(15)
    graficos_ = html.Div([
        cartao("Total adiantado por empresa", dcc.Graph(figure=graficos.barras_h(
            emp["empresa"], emp["adiantado"], "Adiantado", cor="#1B365D",
            custom=emp[["saldo"]].to_numpy(),
            hover="%{y}<br>Adiantado: R$ %{x:,.2f}<br>Saldo a abater: R$ %{customdata[0]:,.2f}<extra></extra>"),
            config={"displaylogo": False}), fonte="no período", classe="grafico-card"),
        cartao("Evolução mensal — adiantado × abatido", dcc.Graph(figure=graficos.mensal_duas(
            m, "adiantado", "Adiantado", "abatido", "Abatido"), config={"displaylogo": False}),
            fonte="R$ por mês", classe="grafico-card"),
    ], className="cv-grid")
    graficos_2 = html.Div([
        cartao("Exposição por credor (maiores saldos)", dcc.Graph(figure=graficos.empilhado_h(
            top["credor"], top["abatido"] + top["realocado"], top["saldo"]), config={"displaylogo": False}),
            fonte=f"posição em {ref:%d/%m/%Y}", classe="grafico-card"),
        cartao("Há quanto tempo o saldo está em aberto", dcc.Graph(figure=graficos.barras_h(
            idade["faixa"], idade["saldo"], "Saldo a abater", cor=graficos.SERIES[1],
            custom=idade[["documentos", "credores"]].to_numpy(),
            hover="%{y}<br>Saldo: R$ %{x:,.2f}<br>%{customdata[0]} documento(s) · %{customdata[1]} credor(es)"
                  "<extra></extra>", altura=260), config={"displaylogo": False}),
            html.Span("Idade = dias desde o primeiro adiantamento do documento até a data final do filtro.",
                      className="cv-nota"), classe="grafico-card"),
    ], className="cv-grid")

    abertos = docs[docs["saldo"].abs() > ad.TOL] if len(docs) else docs
    grade_docs = cartao("Documentos vinculados com saldo", dag.AgGrid(
        id="ad-grade-docs", columnDefs=COL_DOCS, rowData=_registros(abertos), className="ag-theme-quartz",
        defaultColDef={"sortable": True, "resizable": True, "filter": True},
        dashGridOptions={"rowSelection": {"mode": "singleRow", "checkboxes": False, "enableClickSelection": True},
                         "tooltipShowDelay": 300, "enableCellTextSelection": True,
                         "localeText": {"noRowsToShow": "Nenhum documento com saldo"}},
        csvExportParams={"fileName": "adiantamentos_documentos.csv", "columnSeparator": ";"},
        style={"height": 420}),
        html.Span("Clique num documento para ver todas as movimentações dele (com exportação).", className="cv-nota"))
    grade_movs = cartao("Movimentações no período", dag.AgGrid(
        id="ad-grade-movs", columnDefs=COL_MOVS, rowData=_registros(mov), className="ag-theme-quartz",
        defaultColDef={"sortable": True, "resizable": True, "filter": True},
        dashGridOptions={"tooltipShowDelay": 300, "enableCellTextSelection": True, "localeText": {"page": "Página", "of": "de", "to": "a", "pageSizeSelectorLabel": "Linhas por página:", "noRowsToShow": "Sem linhas"}, "pagination": True,
                         "paginationPageSize": 50},
        csvExportParams={"fileName": "adiantamentos_movimentacoes.csv", "columnSeparator": ";"},
        style={"height": 460}))

    return html.Div([
        kpis, progresso,
        html.Div(cards_vinc, className="cv-grid", style={"margin": "14px 0"}),
        graficos_, graficos_2, grade_docs, grade_movs,
        nota(html.B("Como ler: "), "adiantado e abatido somam as movimentações do período filtrado; o saldo a abater é "
             "a posição na data final (todo o histórico até ela), por isso não muda quando o período começa depois "
             "do adiantamento. Saldo = adiantamentos − abatimentos − realocações de saída, e confere com o 'Total de "
             "adiantamentos' de cada relatório do Sienge. Documento iniciado por CT/CTS é contrato; número puro é "
             "pedido de compra."),
    ])


def _registros(df: pd.DataFrame):
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].dt.strftime("%Y-%m-%d")
    return d.astype(object).where(d.notna(), None).to_dict("records")


@callback(*detalhe.saidas(P), Input({"type": "ad-kpi", "k": ALL}, "n_clicks"),
          Input("ad-grade-docs", "selectedRows"),
          State("ad-periodo", "start_date"), State("ad-periodo", "end_date"), State("ad-empresas", "value"),
          State("ad-credores", "value"), State("ad-tipos", "value"), State("ad-vinculos", "value"),
          State("ad-doc", "value"), prevent_initial_call=True)
def decompor(_cliques, linhas, ini, fim, empresas, credores, tipos, vinculos, doc):
    gatilho = ctx.triggered_id
    if not ctx.triggered or not ctx.triggered[0].get("value"):
        return (no_update,) * 5
    mov, posicao, ref, docs = _dados(ini, fim, empresas, credores, tipos, vinculos, doc)
    per = f"{pd.Timestamp(ini):%d/%m/%Y} a {pd.Timestamp(fim):%d/%m/%Y}" if ini and fim else "todo o período"

    if gatilho == "ad-grade-docs":
        o = linhas[0]
        sel = posicao[(posicao["cod_empresa"] == o["cod_empresa"]) & (posicao["cod_credor"] == o["cod_credor"])
                      & (posicao["documento_vinculado"].fillna("") == (o["documento_vinculado"] or ""))]
        sel = sel.sort_values(["data_movimento", "id_movimento"])
        cols = [c for c in COLS_MOV_EXPORT if c["campo"] not in ("credor", "empresa", "documento_vinculado")]
        return detalhe.abrir(f"{o['credor']} · {o['documento_vinculado']}",
                             f"{len(sel)} movimentação(ões) · {o['empresa']} · saldo {brl(o['saldo'], 2)}",
                             sel, cols)

    k = gatilho["k"]
    if k in ("adiantado", "abatido"):
        tipo = "Adiantamento" if k == "adiantado" else "Abatimento"
        d = mov[mov["tipo_movimento"] == tipo].sort_values("valor", ascending=False)
        return detalhe.abrir("Total adiantado" if k == "adiantado" else "Total abatido",
                             f"{len(d)} lançamento(s) · {d['cod_credor'].nunique()} credor(es) · {per}", d, COLS_MOV_EXPORT)
    if k in ("saldo", "antigos", "v-contrato", "v-pedido"):
        d = docs[docs["saldo"] > ad.TOL]
        titulo = "Saldo a abater"
        if k == "antigos":
            d, titulo = d[d["dias_em_aberto"] > 365], "Saldo a abater há mais de 1 ano"
        elif k.startswith("v-"):
            tipo = "Contrato" if k == "v-contrato" else "Pedido de compra"
            d, titulo = docs[docs["tipo_vinculo"] == tipo], f"Adiantamentos vinculados a {tipo.lower()}"
        return detalhe.abrir(titulo, f"{len(d)} documento(s) · {d['cod_credor'].nunique()} credor(es) · posição em "
                             f"{ref:%d/%m/%Y}", d, COLS_DOC_EXPORT,
                             "Saldo = adiantado − abatido − realocações de saída, por documento vinculado.")
    if k == "credores":
        d = ad.por_credor(docs)
        d = d[d["saldo"] > ad.TOL]
        cols = [_c("credor", "Credor", peso=3), _c("documentos", "Documentos", "int", peso=0.8),
                _c("adiantado", "Adiantado", "brl", True), _c("abatido", "Abatido", "brl", True),
                _c("saldo", "Saldo a abater", "brl", True), _c("pct_abatido", "% abatido", "pct", peso=0.8),
                _c("maior_idade", "Maior idade (dias)", "int", peso=0.9)]
        return detalhe.abrir("Credores com saldo", f"{len(d)} credor(es) · posição em {ref:%d/%m/%Y}", d, cols)
    return (no_update,) * 5


# ── Relatório em PowerPoint (botão "Gerar relatório") ────────────────────────
@callback(Output("ad-rel-down", "data"), Input("ad-rel", "n_clicks"),
          State("ad-periodo", "start_date"),
          State("ad-periodo", "end_date"),
          State("ad-empresas", "value"),
          State("ad-credores", "value"),
          State("ad-tipos", "value"),
          State("ad-vinculos", "value"),
          State("ad-doc", "value"), prevent_initial_call=True)
def gerar_relatorio(n, ini, fim, empresas, credores, tipos, vinculos, doc):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    return dcc.send_bytes(rel.adiantamento(ini, fim, empresas, credores, tipos, vinculos, doc), nome_arquivo("adiantamento"))
