"""Contratos: valor contratado, medido, saldo a medir, vencimentos e autorizações (relatório do Sienge via RPA)."""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from app.components import detalhe, graficos
from app.components.ui import brl, brl_curto, cabecalho, cartao, dropdown, filtro, kpi, nota, num, pct, periodo, vazio
from app.pages.oportunidades import F_BRL, F_PCT
from app.repositories import rpa_repo
from app.services import contratos as ct

P = "ct-dm"
LIMITE_GRADE = 2000


def _c(campo, rotulo, formato="texto", total=False, peso=None):
    d = {"campo": campo, "rotulo": rotulo, "formato": formato, "total": total}
    if peso:
        d["peso"] = peso
    return d


F_DATA = {"function": "params.value ? new Date(params.value).toLocaleDateString('pt-BR', {timeZone: 'UTC'}) : ''"}
COL_GRADE = [
    {"field": "numero_contrato", "headerName": "Contrato", "width": 125, "pinned": "left"},
    {"field": "fornecedor_rotulo", "headerName": "Fornecedor", "minWidth": 240, "flex": 2, "tooltipField": "fornecedor_rotulo"},
    {"field": "obra_rotulo", "headerName": "Obra", "minWidth": 200, "flex": 1, "tooltipField": "obra_rotulo"},
    {"field": "tipo_contrato", "headerName": "Tipo", "minWidth": 160, "tooltipField": "tipo_contrato"},
    {"field": "situacao", "headerName": "Situação", "width": 150},
    {"field": "data_termino", "headerName": "Término", "width": 110, "valueFormatter": F_DATA},
    {"field": "valor_total", "headerName": "Valor", "width": 140, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "pct_medido", "headerName": "% medido", "width": 100, "valueFormatter": F_PCT, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "saldo_aberto", "headerName": "Saldo a medir", "width": 140, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned", "sort": "desc"},
    {"field": "alerta", "headerName": "Alerta", "width": 150},
]
COLS_LISTA = [_c("numero_contrato", "Contrato", peso=1), _c("fornecedor_rotulo", "Fornecedor", peso=2.6),
              _c("obra_rotulo", "Obra", peso=2.2), _c("tipo_contrato", "Tipo", peso=1.6), _c("situacao", "Situação", peso=1.2),
              _c("data_termino", "Término", "data", peso=0.9), _c("valor_total", "Valor", "brl", True, 1.2),
              _c("valor_medido", "Medido", "brl", True, 1.2), _c("saldo_aberto", "Saldo a medir", "brl", True, 1.2)]

_PREP: dict = {}


def base() -> pd.DataFrame:
    """Preparada uma vez por carga do cache; o escopo do usuário já vem aplicado pelo repositório."""
    d = rpa_repo.contratos()
    if _PREP.get("bruta") is not d:
        _PREP.update(bruta=d, pronta=ct.preparar(d))
    return _PREP["pronta"]


def _fonte():
    try:
        ctl = rpa_repo.controle_contrato()
    except Exception:  # noqa: BLE001
        return None
    if ctl.empty:
        return None
    pos = ctl["modificado_em"].max()
    return html.Div([html.Div(f"relatório Sienge de {pos:%d/%m/%Y %H:%M}" if pd.notna(pos) else ""),
                     html.Div(f"{len(ctl)} arquivo(s) · {int(ctl['conciliado'].sum())} conferido(s) com o total impresso")])


def _opcoes(serie_cod, serie_nome):
    d = pd.DataFrame({"v": serie_cod, "l": serie_nome}).dropna(subset=["v"]).drop_duplicates("v").sort_values("l")
    return [{"label": r.l, "value": int(r.v)} for r in d.itertuples()]


def layout(**_):
    try:
        b = base()
    except Exception as exc:  # noqa: BLE001
        return html.Div([cabecalho("Contratos", ""),
                         vazio("Tabela suprimentos.fato_contrato indisponível. Rode a DAG etl_suprimentos_rpa (task "
                               f"contrato) ou python main.py --etapa contrato. Detalhe: {str(exc).splitlines()[0]}")])
    if b.empty:
        return html.Div([cabecalho("Contratos", ""), vazio("Nenhum contrato no seu escopo de acesso.")])
    tipos = b.groupby("tipo_contrato")["valor_total"].sum().sort_values(ascending=False).index
    filtros = html.Div([
        filtro("Data do contrato", periodo("ct-periodo", None, None), "largo"),
        filtro("Situação", dropdown("ct-situacoes", [{"label": s, "value": s} for s in ct.SITUACOES
                                                     if s in set(b["situacao"])], multi=True,
                                    placeholder="Todas")),
        filtro("Segmento", dropdown("ct-segmentos", [{"label": s, "value": s} for s in sorted(b["segmento"].unique())],
                                    multi=True)),
        filtro("Obra", dropdown("ct-obras", _opcoes(b["cod_obra"], b["obra_rotulo"]), multi=True), "largo"),
        filtro("Empresa", dropdown("ct-empresas", _opcoes(b["cod_empresa"], b["empresa_rotulo"]), multi=True), "largo"),
        filtro("Fornecedor", dropdown("ct-fornecedores", _opcoes(b["cod_fornecedor"], b["fornecedor_rotulo"]), multi=True),
               "largo"),
        filtro("Tipo de contrato", dropdown("ct-tipos", [{"label": t, "value": t} for t in tipos], multi=True), "largo"),
        filtro("Autorização", dropdown("ct-autorizacao", [{"label": s, "value": s} for s in
                                                          sorted(b["situacao_autorizacao"].dropna().unique())], multi=True)),
        filtro("Contrato, objeto ou fornecedor", dcc.Input(id="ct-texto", debounce=True, className="cv-input",
                                                           placeholder="ex.: CT/642, locação"), "largo"),
    ], className="filtros")
    return html.Div([
        cabecalho("Contratos", "Quanto está contratado, quanto já foi medido, o saldo a medir e o que está vencido ou "
                  "vence em breve — por obra, fornecedor e tipo de contrato.", _fonte(), relatorio="ct"),
        filtros,
        dcc.Loading(html.Div(id="ct-conteudo"), type="dot", color="#1B365D"),
        nota(html.B("Como ler: "), "fonte = relatório de contratos do Sienge (exportado pelo RPA do legado e conferido "
             "com a linha de total de cada arquivo). Saldo a medir = valor − medido, só para contratos em andamento "
             "(Pendente ou Parcialmente medido; o Sienge não informa saldo de contratos encerrados). Vencido com saldo = "
             "término antes da data do relatório e ainda com saldo — normalmente contrato a encerrar ou aditar. "
             "Não executado = valor − medido de contratos concluídos ou rescindidos. Obra = 1ª obra do contrato. "
             "Ficam fora os contratos em que a empresa é a CONTRATADA (contratos com clientes, sem fornecedor)."),
        *detalhe.modal(P),
    ])


dash.register_page(__name__, path="/contratos", name="Contratos", title="Contratos · Suprimentos", layout=layout)
detalhe.registrar(P)

ENTRADAS = [Input("ct-periodo", "start_date"), Input("ct-periodo", "end_date"), Input("ct-situacoes", "value"),
            Input("ct-tipos", "value"), Input("ct-segmentos", "value"), Input("ct-obras", "value"),
            Input("ct-empresas", "value"), Input("ct-fornecedores", "value"), Input("ct-texto", "value"),
            Input("ct-autorizacao", "value")]


def dados(ini, fim, situacoes, tipos, segmentos, obras, empresas, fornecedores, texto, autorizacao) -> pd.DataFrame:
    return ct.filtrar(base(), ini, fim, situacoes, tipos, segmentos, obras, empresas, fornecedores, texto, autorizacao)


def _alerta(d: pd.DataFrame) -> pd.Series:
    return pd.Series(["vencido com saldo" if v else ("vence em breve" if b else "") for v, b in
                      zip(d["vencido_com_saldo"], d["vence_em_breve"])], index=d.index)


@callback(Output("ct-conteudo", "children"), *ENTRADAS)
def atualizar(*filtros):
    d = dados(*filtros)
    if d.empty:
        return vazio("Nenhum contrato com os filtros atuais.")
    r = ct.resumo(d)

    def k(chave, *a, **kw):
        return detalhe.kpi_clicavel({"type": "ct-kpi", "k": chave}, kpi(*a, **kw))

    kpis = html.Div([
        k("contratos", "Contratos", num(r["contratos"]), f"{num(r['fornecedores'])} fornecedores", "neutro"),
        k("valor", "Valor contratado", brl_curto(r["valor_total"]), f"medido {pct(r['pct_medido'], 1)}", "neutro"),
        k("medido", "Valor medido", brl_curto(r["valor_medido"]), "acumulado do contrato", "neutro"),
        k("saldo", "Saldo a medir", brl_curto(r["saldo"]), f"{num(r['em_andamento'])} contratos em andamento",
          "destaque"),
        k("vencidos", "Vencidos com saldo", num(r["vencidos"]), f"{brl_curto(r['saldo_vencidos'])} a medir",
          "alerta" if r["vencidos"] else "neutro"),
        k("breve", "Vencem em breve", num(r["vence_breve"]), f"{brl_curto(r['saldo_breve'])} a medir", "neutro"),
        k("aguardando", "Aguardando autorização", num(r["aguardando"]), brl_curto(r["valor_aguardando"]), "neutro"),
        k("nao_executado", "Não executado (encerrados)", brl_curto(r["nao_executado"]),
          f"{num(r['encerrados'])} concluídos ou rescindidos", "neutro"),
    ], className="port-kpi-grid", style={"marginBottom": 14, "gridTemplateColumns": "repeat(4, minmax(0, 1fr))"})

    posicao = d["posicao_em"].max() if d["posicao_em"].notna().any() else pd.Timestamp.today()
    g_venc = graficos.vencimentos(ct.vencimentos(d, posicao))
    g_mes = graficos.assinados_mes(ct.assinados_mes(d))
    seg = ct.por(d, "segmento")
    g_seg = graficos.empilhado_h(seg["segmento"], seg["valor_medido"], seg["saldo"], series=("Medido", "Saldo a medir"))
    forn = ct.por(d[d["em_andamento"]], "cod_fornecedor", "fornecedor_rotulo").head(15)
    g_forn = graficos.barras_h(forn["fornecedor_rotulo"], forn["saldo"], "Saldo a medir")
    obra = ct.por(d[d["em_andamento"]], "cod_obra", "obra_rotulo").head(15)
    g_obra = graficos.barras_h(obra["obra_rotulo"], obra["saldo"], "Saldo a medir", cor=graficos.SERIES[2])
    tipo = ct.por(d, "tipo_contrato").head(12)
    g_tipo = graficos.barras_h(tipo["tipo_contrato"], tipo["valor_total"], "Valor contratado", cor=graficos.SERIES[1])
    cfg = {"displaylogo": False}
    graf = html.Div([
        cartao("Saldo a medir por mês de término", dcc.Graph(figure=g_venc, config=cfg),
               html.Span("Contratos em andamento. ‘Vencidos’ = término já passou e ainda há saldo.", className="cv-nota"),
               classe="grafico-card"),
        cartao("Valor contratado por mês (data do contrato)", dcc.Graph(figure=g_mes, config=cfg), classe="grafico-card"),
        cartao("Medido × saldo a medir por segmento", dcc.Graph(figure=g_seg, config=cfg), classe="grafico-card"),
        cartao("Valor contratado por tipo de contrato", dcc.Graph(figure=g_tipo, config=cfg), classe="grafico-card"),
        cartao("Maiores saldos a medir — fornecedores", dcc.Graph(figure=g_forn, config=cfg), classe="grafico-card"),
        cartao("Maiores saldos a medir — obras", dcc.Graph(figure=g_obra, config=cfg), classe="grafico-card"),
    ], className="cv-grid", style={"gridTemplateColumns": "repeat(2, minmax(0, 1fr))"})

    g = d.assign(alerta=_alerta(d)).sort_values(["saldo_aberto", "valor_total"], ascending=False)
    linhas = g.head(LIMITE_GRADE)[["numero_contrato", "fornecedor_rotulo", "obra_rotulo", "tipo_contrato", "situacao",
                                   "data_termino", "valor_total", "pct_medido", "saldo_aberto", "alerta"]].copy()
    linhas["data_termino"] = linhas["data_termino"].dt.strftime("%Y-%m-%d")
    grade = cartao(f"Contratos ({num(len(g))}" + (f", mostrando {LIMITE_GRADE}" if len(g) > LIMITE_GRADE else "") + ")",
                   dag.AgGrid(id="ct-grade", columnDefs=COL_GRADE, rowData=linhas.to_dict("records"),
                              className="ag-theme-quartz", defaultColDef={"sortable": True, "resizable": True,
                                                                          "filter": True},
                              dashGridOptions={"rowSelection": {"mode": "singleRow", "checkboxes": False,
                                                                "enableClickSelection": True},
                                               "tooltipShowDelay": 300, "animateRows": False},
                              style={"height": 480}),
                   html.Span("Clique num contrato para ver todos os campos.", className="cv-nota"))
    return [kpis, graf, grade]


# ── Decomposição dos cards ───────────────────────────────────────────────────
def _decompor(chave: str, d: pd.DataFrame):
    filtros = {
        "contratos": (d, "Contratos", "todos os contratos dos filtros"),
        "valor": (d, "Valor contratado", "todos os contratos dos filtros"),
        "medido": (d[d["valor_medido"].fillna(0) > 0], "Valor medido", "contratos com medição"),
        "saldo": (d[d["em_andamento"]], "Saldo a medir", "contratos em andamento (Pendente / Parcialmente medido)"),
        "vencidos": (d[d["vencido_com_saldo"]], "Vencidos com saldo", "término antes da data do relatório, com saldo"),
        "breve": (d[d["vence_em_breve"]], "Vencem em breve", "em andamento, término nos próximos dias"),
        "aguardando": (d[d["situacao_autorizacao"] == "Aguardando autorização"], "Aguardando autorização",
                       "contratos ainda não autorizados no Sienge"),
        "nao_executado": (d[d["situacao"].isin(ct.ENCERRADOS)], "Não executado (encerrados)",
                          "concluídos ou rescindidos: valor − medido"),
    }
    if chave not in filtros:
        return None
    sub, titulo, desc = filtros[chave]
    cols = list(COLS_LISTA)
    if chave == "nao_executado":
        cols = cols[:-1] + [_c("nao_executado", "Não executado", "brl", True, 1.2)]
        sub = sub.sort_values("nao_executado", ascending=False)
    elif chave in ("vencidos", "breve"):
        cols = cols[:5] + [_c("data_termino", "Término", "data", peso=0.9),
                           _c("dias_para_termino", "Dias p/ término", "int", peso=0.8)] + cols[6:]
        sub = sub.sort_values("saldo_aberto", ascending=False)
    else:
        sub = sub.sort_values(["saldo_aberto", "valor_total"], ascending=False)
    return titulo, f"{num(len(sub))} contrato(s) · {desc}", sub, cols


@callback(*detalhe.saidas(P), Input({"type": "ct-kpi", "k": ALL}, "n_clicks"), Input("ct-grade", "selectedRows"),
          *[State(i.component_id, i.component_property) for i in ENTRADAS], prevent_initial_call=True)
def abrir_decomposicao(_cliques, linhas, *filtros):
    if ctx.triggered_id == "ct-grade":
        return ficha(linhas)
    if not ctx.triggered or not ctx.triggered[0].get("value") or not isinstance(ctx.triggered_id, dict):
        return (no_update,) * 5
    r = _decompor(ctx.triggered_id["k"], dados(*filtros))
    if r is None:
        return (no_update,) * 5
    titulo, sub, d, cols = r
    return detalhe.abrir(titulo, sub, d, cols)


CAMPOS_FICHA = [("numero_contrato", "Contrato", "texto"), ("situacao", "Situação", "texto"),
                ("situacao_autorizacao", "Autorização", "texto"), ("autorizado_por", "Autorizado por", "texto"),
                ("fornecedor_rotulo", "Fornecedor", "texto"), ("cnpj_fornecedor", "CNPJ", "texto"),
                ("empresa_rotulo", "Empresa", "texto"), ("obras", "Obra(s)", "texto"), ("segmento", "Segmento", "texto"),
                ("tipo_contrato", "Tipo", "texto"), ("objeto", "Objeto", "texto"), ("responsavel", "Responsável", "texto"),
                ("data_contrato", "Data do contrato", "data"), ("data_inicio", "Início", "data"),
                ("data_termino", "Término", "data"), ("valor_total", "Valor", "brl"), ("valor_medido", "Medido", "brl"),
                ("pct_medido", "% medido", "pct"), ("saldo", "Saldo a medir", "brl"),
                ("total_mao_obra", "Total mão de obra", "brl"), ("total_material", "Total material", "brl"),
                ("total_em_aberto", "Total em aberto (Sienge)", "brl"), ("total_fat_direto", "Faturamento direto", "brl"),
                ("data_alteracao_situacao", "Alteração de situação", "data"),
                ("descricao_alteracao", "Motivo da alteração", "texto"), ("arquivo_origem", "Arquivo", "texto")]


def ficha(linhas):
    if not linhas:
        return (no_update,) * 5
    numero = linhas[0]["numero_contrato"]
    c = base()
    c = c[c["numero_contrato"] == numero]
    if c.empty:
        return (no_update,) * 5
    r = c.iloc[0]
    fmt = {"brl": lambda v: brl(v, 2), "pct": lambda v: pct(v, 1),
           "data": lambda v: pd.Timestamp(v).strftime("%d/%m/%Y"), "texto": str}
    ficha_df = pd.DataFrame([{"campo": rot, "valor": fmt[f](r[k]) if pd.notna(r[k]) and r[k] != "" else "—"}
                             for k, rot, f in CAMPOS_FICHA if k in r])
    return detalhe.abrir(f"Contrato {numero}", r["fornecedor_rotulo"], ficha_df,
                         [_c("campo", "Campo", peso=1.2), _c("valor", "Valor", peso=3.5)])


# ── Relatório em PowerPoint ──────────────────────────────────────────────────
@callback(Output("ct-rel-down", "data"), Input("ct-rel", "n_clicks"),
          *[State(i.component_id, i.component_property) for i in ENTRADAS], prevent_initial_call=True)
def gerar_relatorio(n, *filtros):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    d = dados(*filtros)
    rotulos = ["período", "situação", "tipo", "segmento", "obra", "empresa", "fornecedor", "busca", "autorização"]
    ativos = [r for r, v in zip(rotulos, [filtros[0] or filtros[1], *filtros[2:]]) if v]
    return dcc.send_bytes(rel.contratos(d, ", ".join(ativos) or "sem filtros"), nome_arquivo("contratos"))
