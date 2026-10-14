"""Solicitações de serviço: o que foi pedido, atendido, o que está parado e há quanto tempo."""
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
from app.services import servicos as sv

P = "sv-dm"
F_DATA = {"function": "params.value ? new Date(params.value).toLocaleDateString('pt-BR', {timeZone: 'UTC'}) : ''"}
F_DIAS = {"function": "params.value == null ? '' : Math.round(params.value) + ' d'"}
DIMS = {"obra_rotulo": "Obra", "solicitante": "Solicitante", "autorizador": "Autorizador", "segmento": "Segmento",
        "departamento": "Departamento"}


def _c(campo, rotulo, formato="texto", total=False, peso=None):
    d = {"campo": campo, "rotulo": rotulo, "formato": formato, "total": total}
    if peso:
        d["peso"] = peso
    return d


_PREP: dict = {}


def base() -> pd.DataFrame:
    d = rpa_repo.servicos()
    chave = (cf.parametro("servico.dias_alerta_autorizacao"), cf.parametro("servico.dias_alerta_aberto"))
    if _PREP.get("bruta") is not d or _PREP.get("chave") != chave:
        _PREP.update(bruta=d, chave=chave, pronta=sv.preparar(d, *chave))
    return _PREP["pronta"]


def _fonte():
    try:
        ctl = rpa_repo.controle_servico()
    except Exception:  # noqa: BLE001
        return None
    if ctl.empty:
        return None
    pos = ctl["modificado_em"].max()
    return html.Div([html.Div(f"relatório Sienge de {pos:%d/%m/%Y %H:%M}"),
                     html.Div(f"{num(int(ctl['linhas'].sum()))} solicitações")])


def _opcoes(v, rot=None):
    d = pd.DataFrame({"v": v, "l": rot if rot is not None else v}).dropna(subset=["v"]).drop_duplicates("v").sort_values("l")
    n = pd.api.types.is_numeric_dtype(d["v"])
    return [{"label": str(r.l), "value": int(r.v) if n else str(r.v)} for r in d.itertuples()]


def layout(**_):
    try:
        b = base()
    except Exception as exc:  # noqa: BLE001
        return html.Div([cabecalho("Serviços", ""),
                         vazio("Tabela suprimentos.fato_servico indisponível. Rode a DAG etl_suprimentos_rpa (task "
                               f"servico) ou python main.py --etapa servico. Detalhe: {str(exc).splitlines()[0]}")])
    if b.empty:
        return html.Div([cabecalho("Serviços", ""), vazio("Nenhuma solicitação no seu escopo de acesso.")])
    fim = b["data_cadastro"].max()
    filtros = html.Div([
        filtro("Data do cadastro", periodo("sv-periodo", pd.Timestamp(fim.year, 1, 1).date(), fim.date()), "largo"),
        filtro("Obra", dropdown("sv-obras", _opcoes(b["cod_obra"], b["obra_rotulo"]), multi=True), "largo"),
        filtro("Solicitante", dropdown("sv-solicitantes", _opcoes(b["solicitante"]), multi=True)),
        filtro("Autorizador", dropdown("sv-autorizadores", _opcoes(b["autorizador"]), multi=True)),
        filtro("Situação da autorização", dropdown("sv-aut", [{"label": x, "value": x} for x in sv.AUTORIZACOES],
                                                   multi=True)),
        filtro("Situação", dropdown("sv-situacoes", [{"label": x, "value": x} for x in sv.SITUACOES], multi=True)),
        filtro("Segmento", dropdown("sv-segmentos", _opcoes(b["segmento"]), multi=True)),
        filtro("Nº da solicitação ou texto da observação", dcc.Input(id="sv-texto", debounce=True,
                                                                      className="cv-input"), "largo"),
    ], className="filtros")
    return html.Div([
        cabecalho("Serviços", "Solicitações de serviço: quanto foi pedido e atendido, o que aguarda autorização, o que "
                  "está em aberto há muito tempo e quem concentra as pendências.", _fonte(), relatorio="sv"),
        filtros,
        dcc.Loading(html.Div(id="sv-conteudo"), type="dot", color="#1B365D"),
        nota(html.B("Como ler: "), "fonte = relatório de solicitações de serviço do Sienge (RPA do legado). "
             "Duração do serviço = término − início PREVISTOS na solicitação (não é a execução real). Tempo até a "
             "alteração = data de alteração − cadastro (proxy do tempo de resposta; vazio se nunca alterada). "
             f"Alertas: aguardando autorização há mais de {cf.parametro('servico.dias_alerta_autorizacao')} dias, "
             f"em aberto há mais de {cf.parametro('servico.dias_alerta_aberto')} dias ou com término previsto vencido "
             "(ajuste em Configurações)."),
        *detalhe.modal(P),
    ])


dash.register_page(__name__, path="/servicos", name="Serviços", title="Serviços · Suprimentos", layout=layout)
detalhe.registrar(P)

ENTRADAS = [Input("sv-periodo", "start_date"), Input("sv-periodo", "end_date"), Input("sv-obras", "value"),
            Input("sv-solicitantes", "value"), Input("sv-autorizadores", "value"), Input("sv-aut", "value"),
            Input("sv-situacoes", "value"), Input("sv-segmentos", "value"), Input("sv-texto", "value")]


def dados(*f):
    return sv.filtrar(base(), *f)


@callback(Output("sv-conteudo", "children"), *ENTRADAS)
def atualizar(*filtros):
    d = dados(*filtros)
    if d.empty:
        return vazio("Nenhuma solicitação com os filtros atuais.")
    r = sv.resumo(d)

    def k(chave, *a, **kw):
        return detalhe.kpi_clicavel({"type": "sv-kpi", "k": chave}, kpi(*a, **kw))

    linha1 = html.Div([
        k("solicitado", "Solicitado", num(r["solicitado"]), f"{pct(r['pct_atendido'], 1)} atendido (sem canceladas)",
          "neutro"),
        k("totalmente", "Totalmente atendido", num(r["totalmente"]), "", "destaque"),
        k("parcial", "Parcialmente atendido", num(r["parcial"]), "", "neutro"),
        k("cancelado", "Cancelado", num(r["cancelado"]), "", "neutro"),
        k("pendente", "Pendente", num(r["pendente"]), f"em aberto: {num(r['em_aberto'])} · idade mediana "
          f"{num(r['idade_mediana_aberto'])} d", "neutro"),
    ], className="port-kpi-grid", style={"gridTemplateColumns": "repeat(5, minmax(0, 1fr))", "marginBottom": 12})
    linha2 = html.Div([
        k("aprovado", "Aprovado", num(r["aprovado"]), "", "neutro"),
        k("aguardando", "Aguardando autorização", num(r["aguardando"]),
          f"{num(r['alerta_aut'])} há mais de {cf.parametro('servico.dias_alerta_autorizacao')} dias",
          "alerta" if r["alerta_aut"] else "neutro"),
        k("reprovado", "Reprovado", num(r["reprovado"]), "", "neutro"),
        k("vencido", "Em aberto com término vencido", num(r["termino_vencido"]),
          f"{num(r['alerta_aberto'])} em aberto há mais de {cf.parametro('servico.dias_alerta_aberto')} dias",
          "alerta" if r["termino_vencido"] else "neutro"),
        k("tempos", "Duração prevista | resposta", f"{num(r['duracao_media'])} d | {num(r['resposta_media'], 1)} d",
          f"medianas {num(r['duracao_mediana'])} d | {num(r['resposta_mediana'])} d", "neutro"),
    ], className="port-kpi-grid", style={"gridTemplateColumns": "repeat(5, minmax(0, 1fr))", "marginBottom": 14})

    m = sv.mensal(d)
    cfg = {"displaylogo": False}
    sit = d["situacao"].value_counts().reindex(sv.SITUACOES).fillna(0)
    graf = html.Div([
        cartao("Solicitações por mês do cadastro", dcc.Graph(figure=graficos.barras_mes(
            m.rename(columns={"solicitado": "v"}), "v", "Solicitações", prefixo=""), config=cfg), classe="grafico-card"),
        cartao("Situação das solicitações", dcc.Graph(figure=graficos.situacao_barras(
            sit.index.tolist(), sit.values.tolist(), [graficos.VERDE, graficos.SERIES[3], graficos.SERIES[0],
                                                      graficos.OUTROS]), config=cfg), classe="grafico-card"),
    ], className="cv-grid", style={"gridTemplateColumns": "minmax(0,1.4fr) minmax(0,1fr)"})

    tabela = cartao("Pendências por", dcc.RadioItems(
        id="sv-dim", value="obra_rotulo", inline=True, className="rc-chips",
        options=[{"label": html.Span(v, className="rc-chip"), "value": k_} for k_, v in DIMS.items()]),
        html.Div(id="sv-tabela"))

    lst = d.sort_values(["em_aberto", "data_cadastro"], ascending=[False, True])
    cols = ["cod_solicitacao", "data_cadastro", "solicitante", "obra_rotulo", "data_alteracao",
            "dias_cadastro_alteracao", "situacao_autorizacao", "autorizador", "situacao", "data_termino", "idade_dias",
            "alerta", "observacao"]
    linhas = lst[cols].copy()
    for c in ("data_cadastro", "data_alteracao", "data_termino"):
        linhas[c] = linhas[c].dt.strftime("%Y-%m-%d")
    grade = cartao(f"Solicitações ({num(len(d))})", dag.AgGrid(
        id="sv-grade", rowData=linhas.astype(object).where(linhas.notna(), None).to_dict("records"),
        className="ag-theme-quartz", style={"height": 460},
        defaultColDef={"sortable": True, "resizable": True, "filter": True},
        dashGridOptions={"tooltipShowDelay": 300, "animateRows": False},
        columnDefs=[{"field": "cod_solicitacao", "headerName": "Nº", "width": 80, "pinned": "left"},
                    {"field": "data_cadastro", "headerName": "Cadastro", "width": 110, "valueFormatter": F_DATA},
                    {"field": "solicitante", "headerName": "Solicitante", "width": 170, "tooltipField": "solicitante"},
                    {"field": "obra_rotulo", "headerName": "Obra", "minWidth": 200, "flex": 1, "tooltipField": "obra_rotulo"},
                    {"field": "data_alteracao", "headerName": "Alteração", "width": 110, "valueFormatter": F_DATA},
                    {"field": "dias_cadastro_alteracao", "headerName": "Cadastro→alteração", "width": 150,
                     "valueFormatter": F_DIAS, "cellClass": "num", "type": "rightAligned"},
                    {"field": "situacao_autorizacao", "headerName": "Autorização", "width": 170},
                    {"field": "autorizador", "headerName": "Autorizador", "width": 160, "tooltipField": "autorizador"},
                    {"field": "situacao", "headerName": "Situação", "width": 160},
                    {"field": "data_termino", "headerName": "Término prev.", "width": 120, "valueFormatter": F_DATA},
                    {"field": "idade_dias", "headerName": "Em aberto há", "width": 115, "valueFormatter": F_DIAS,
                     "cellClass": "num", "type": "rightAligned"},
                    {"field": "alerta", "headerName": "Alerta", "width": 210,
                     "cellStyle": {"function": "params.value ? {color: '#B42318', fontWeight: 600} : {}"}},
                    {"field": "observacao", "headerName": "Observação", "minWidth": 260, "flex": 2,
                     "tooltipField": "observacao"}]),
        html.Span("Em aberto primeiro (mais antigas no topo).", className="cv-nota"))
    return [linha1, linha2, graf, tabela, grade]


@callback(Output("sv-tabela", "children"), Input("sv-dim", "value"),
          *[State(i.component_id, i.component_property) for i in ENTRADAS])
def tabela_dim(dim, *filtros):
    t = sv.por(dados(*filtros), dim or "obra_rotulo")
    if t.empty:
        return vazio("Sem dados.")
    cols = [{"field": dim, "headerName": DIMS[dim], "minWidth": 240, "flex": 2, "pinned": "left", "tooltipField": dim}]
    for f, h, fmt in (("solicitado", "Solicitado", None), ("atendido", "Atendido", None),
                      ("pct_atendido", "% atendido", F_PCT), ("em_aberto", "Em aberto", None),
                      ("aguardando", "Aguard. autorização", None), ("termino_vencido", "Término vencido", None),
                      ("idade_mediana", "Idade mediana (aberto)", F_DIAS), ("resposta_mediana", "Resposta mediana", F_DIAS),
                      ("cancelado", "Cancelado", None)):
        c = {"field": f, "headerName": h, "width": 140, "cellClass": "num", "type": "rightAligned"}
        if fmt:
            c["valueFormatter"] = fmt
        cols.append(c)
    return dag.AgGrid(rowData=t.round(1).astype(object).where(t.notna(), None).to_dict("records"), columnDefs=cols,
                      className="ag-theme-quartz", style={"height": 360},
                      defaultColDef={"sortable": True, "resizable": True, "filter": True})


COLS = [_c("cod_solicitacao", "Nº", peso=0.6), _c("data_cadastro", "Cadastro", "data", peso=0.9),
        _c("solicitante", "Solicitante", peso=1.6), _c("obra_rotulo", "Obra", peso=2.4),
        _c("situacao_autorizacao", "Autorização", peso=1.4), _c("autorizador", "Autorizador", peso=1.4),
        _c("situacao", "Situação", peso=1.4), _c("data_termino", "Término prev.", "data", peso=0.9),
        _c("idade_dias", "Em aberto (d)", "int", peso=0.8)]


def _decompor(chave, d):
    sel = {
        "solicitado": (d, "Solicitado"), "totalmente": (d[d["situacao"] == "Totalmente atendida"], "Totalmente atendido"),
        "parcial": (d[d["situacao"] == "Parcialmente atendida"], "Parcialmente atendido"),
        "cancelado": (d[d["situacao"] == "Cancelada"], "Cancelado"), "pendente": (d[d["situacao"] == "Pendente"], "Pendente"),
        "aprovado": (d[d["situacao_autorizacao"] == "Aprovada"], "Aprovado"),
        "aguardando": (d[d["situacao_autorizacao"] == "Aguardando autorização"].sort_values("aguardando_dias",
                                                                                           ascending=False),
                       "Aguardando autorização"),
        "reprovado": (d[d["situacao_autorizacao"] == "Reprovada"], "Reprovado"),
        "vencido": (d[d["termino_vencido"] | d["alerta_aberto"]].sort_values("idade_dias", ascending=False),
                    "Em aberto com término vencido ou antigas"),
        "tempos": (d.sort_values("dias_previstos", ascending=False), "Duração prevista e resposta"),
    }.get(chave)
    if sel is None:
        return None
    sub, titulo = sel
    cols = COLS + ([_c("dias_previstos", "Duração prev. (d)", "int"), _c("dias_cadastro_alteracao", "Resposta (d)", "int")]
                   if chave == "tempos" else [])
    return titulo, f"{num(len(sub))} solicitação(ões)", sub, cols


@callback(*detalhe.saidas(P), Input({"type": "sv-kpi", "k": ALL}, "n_clicks"),
          *[State(i.component_id, i.component_property) for i in ENTRADAS], prevent_initial_call=True)
def abrir_decomposicao(_c_, *filtros):
    if not ctx.triggered or not ctx.triggered[0].get("value") or not isinstance(ctx.triggered_id, dict):
        return (no_update,) * 5
    r = _decompor(ctx.triggered_id["k"], dados(*filtros))
    return (no_update,) * 5 if r is None else detalhe.abrir(*r)


@callback(Output("sv-rel-down", "data"), Input("sv-rel", "n_clicks"),
          *[State(i.component_id, i.component_property) for i in ENTRADAS], prevent_initial_call=True)
def gerar_relatorio(n, *filtros):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    nomes = ["obra", "solicitante", "autorizador", "autorização", "situação", "segmento", "busca"]
    ativos = [x for x, v in zip(nomes, filtros[2:]) if v]
    per = f"{pd.Timestamp(filtros[0]):%d/%m/%Y} a {pd.Timestamp(filtros[1]):%d/%m/%Y}" if filtros[0] and filtros[1] else ""
    txt = " · ".join(x for x in [per, ", ".join(ativos)] if x) or "sem filtros"
    return dcc.send_bytes(rel.servicos(dados(*filtros), txt), nome_arquivo("servicos"))
