"""Visão geral: o resumo de todas as abas, os pontos de atenção e o panorama por vertical e por obra."""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import Input, Output, State, callback, dcc, html, no_update

from app.components import graficos
from app.components.ui import brl_curto, cabecalho, cartao, dropdown, filtro, nota, num, pct, periodo, vazio
from app.pages.oportunidades import F_BRL, F_PCT
from app.services import visao_geral as vg

F_INT = {"function": "params.value == null ? '' : Math.round(params.value).toLocaleString('pt-BR')"}
F_DATAHORA = {"function": "params.value ? new Date(params.value).toLocaleString('pt-BR', {dateStyle: 'short', "
                          "timeStyle: 'short'}) : ''"}
NIVEL = {"alta": ("Alta", "#B42318"), "media": ("Média", "#C98A00"), "baixa": ("Baixa", "#4A5568")}


def _opcoes():
    """Verticais e obras visíveis para o usuário (a partir de contratos, estoque, SLA e compras)."""
    segs, obras = set(), {}
    for carregar, col_o, col_n in (("app.pages.contratos", "cod_obra", "obra_rotulo"),
                                    ("app.pages.estoque", "cod_centro_custo", "centro_rotulo"),
                                    ("app.pages.sla_insumos", "cod_obra", "obra_rotulo")):
        try:
            import importlib
            b = importlib.import_module(carregar).base()
        except Exception:  # noqa: BLE001
            continue
        segs |= set(b["segmento"].dropna().unique())
        for c, n in b[[col_o, col_n]].dropna().drop_duplicates(col_o).itertuples(index=False):
            obras.setdefault(int(c), str(n))
    return sorted(segs), sorted(obras.items(), key=lambda x: x[1])


def layout(**_):
    segs, obras = _opcoes()
    hoje = pd.Timestamp.today().normalize()
    filtros = html.Div([
        filtro("Vertical (segmento)", dropdown("vg-segmentos", [{"label": s, "value": s} for s in segs], multi=True,
                                               placeholder="Todas")),
        filtro("Obra", dropdown("vg-obras", [{"label": n, "value": c} for c, n in obras], multi=True,
                                placeholder="Todas"), "largo"),
        filtro("Período (compras, SLA e serviços)", periodo("vg-periodo", pd.Timestamp(hoje.year, 1, 1).date(),
                                                            hoje.date()), "largo"),
    ], className="filtros")
    return html.Div([
        cabecalho("Visão geral", "O principal de cada aba num lugar só: o que pede ação agora e como cada vertical e "
                  "obra está em compras, estoque, contratos, prazos e serviços.", None, relatorio="vg"),
        filtros,
        dcc.Loading(html.Div(id="vg-conteudo"), type="dot", color="#1B365D"),
        nota(html.B("Como ler: "), "cada card resume uma aba com os mesmos números dela (clique para abrir). Vertical "
             "e obra filtram compras, oportunidades, estoque, contratos, SLA e serviços; adiantamentos, avaliação de "
             "fornecedores e curva ABC não têm obra no Sienge e aparecem sempre no total. O período vale para o que é "
             "fluxo (compras, SLA, serviços); estoque e saldos são a posição da última carga. O botão Gerar relatório "
             "traz o panorama completo, com uma página por vertical."),
    ])


dash.register_page(__name__, path="/visao-geral", name="Visão geral", title="Visão geral · Suprimentos", layout=layout)

ENTRADAS = [Input("vg-segmentos", "value"), Input("vg-obras", "value"), Input("vg-periodo", "start_date"),
            Input("vg-periodo", "end_date")]


def _card(a: vg.Area, valor: str, sub: str, extra: str = "", alerta: bool = False):
    corpo = ([html.Div(a.nome, className="pk-l"), html.Div(valor, className="pk-v"), html.Div(sub, className="pk-s"),
              html.Div(extra, className="pk-s")] if a.ok else
             [html.Div(a.nome, className="pk-l"), html.Div("indisponível", className="pk-v neutro"),
              html.Div(a.erro or "", className="pk-s", title=a.erro)])
    return dcc.Link(html.Div(corpo, className="port-kpi " + ("alerta" if alerta and a.ok else "neutro")),
                    href=a.rota, className="vg-card", title=f"Abrir {a.nome}")


def _cards(areas: dict[str, vg.Area]):
    c, e, ct, s, sv, ad, av, ca = (areas[k] for k in ("compras", "estoque", "contratos", "sla", "servicos",
                                                     "adiantamento", "avaliacao", "curva_abc"))
    k = lambda a, campo, padrao=0: a.kpis.get(campo, padrao) if a.ok else padrao  # noqa: E731
    return html.Div([
        _card(c, brl_curto(k(c, "valor")), f"comprado no período · {num(k(c, 'itens'))} itens",
              f"economia potencial {brl_curto(k(c, 'economia'))}"),
        _card(e, brl_curto(k(e, "valor")), f"em estoque · {num(k(e, 'insumos'))} insumos",
              f"{num(k(e, 'centros'))} centros de custo"),
        _card(ct, brl_curto(k(ct, "saldo")), f"saldo a medir · {num(k(ct, 'em_andamento'))} em andamento",
              f"{num(k(ct, 'vencidos'))} vencidos com saldo ({brl_curto(k(ct, 'saldo_vencidos'))})",
              alerta=bool(k(ct, "vencidos"))),
        _card(s, f"{pct(k(s, 'pct_f1', float('nan')), 0)} | {pct(k(s, 'pct_f2', float('nan')), 0)}",
              "no prazo · compra | entrega",
              f"{num(k(s, 'vencidos_f1') + k(s, 'vencidos_f2'))} itens vencidos em aberto",
              alerta=bool(k(s, "vencidos_f1") + k(s, "vencidos_f2"))),
        _card(sv, num(k(sv, "em_aberto")), f"serviços em aberto · {num(k(sv, 'aguardando'))} aguardando autorização",
              f"{pct(k(sv, 'pct_atendido', float('nan')), 0)} atendido no período"),
        _card(ad, brl_curto(k(ad, "saldo")), f"adiantamento a abater · {num(k(ad, 'credores_com_saldo'))} credores",
              f"{brl_curto(k(ad, 'saldo_mais_1_ano'))} há mais de 1 ano · todas as verticais"),
        _card(av, num(k(av, "a")), f"fornecedores críticos · {k(av, 'periodo', '')}",
              f"{brl_curto(k(av, 'valor_criticos'))} comprados deles · todas as verticais", alerta=bool(k(av, "a"))),
        _card(ca, brl_curto(k(ca, "valor")), f"apropriado em {k(ca, 'ano', '')} · {num(k(ca, 'a_n'))} insumos classe A",
              f"{num(k(ca, 'altas_ab'))} A/B mais caros · todas as verticais"),
    ], className="port-kpi-grid vg-cards", style={"gridTemplateColumns": "repeat(4, minmax(0, 1fr))",
                                                   "marginBottom": 14})


def _pontos(pontos: list[dict]):
    if not pontos:
        return html.Div("Nenhum ponto de atenção com os filtros atuais.", className="cv-nota")
    return html.Ul([html.Li([html.Span(NIVEL[p["nivel"]][0], className="vg-nivel",
                                       style={"background": NIVEL[p["nivel"]][1]}),
                             html.B(f"{p['area']}: "), p["texto"], " ",
                             dcc.Link("abrir →", href=p["rota"], className="vg-link")]) for p in pontos],
                   className="vg-pontos")


COL_PAN = [
    {"field": "compras", "headerName": "Compras no período", "width": 150, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "economia", "headerName": "Economia potencial", "width": 145, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "estoque", "headerName": "Estoque", "width": 130, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "contratos_saldo", "headerName": "Contratos a medir", "width": 145, "valueFormatter": F_BRL,
     "cellClass": "num", "type": "rightAligned"},
    {"field": "contratos_vencido", "headerName": "…vencidos", "width": 125, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned", "cellStyle": {"function": "params.value > 0 ? {color: '#B42318'} : {}"}},
    {"field": "sla_f1", "headerName": "SLA compra", "width": 110, "valueFormatter": F_PCT, "cellClass": "num",
     "type": "rightAligned", "cellStyle": {"function": "params.value != null && params.value < 70 ? {color: '#B42318', fontWeight: 600} : {}"}},
    {"field": "sla_f2", "headerName": "SLA entrega", "width": 110, "valueFormatter": F_PCT, "cellClass": "num",
     "type": "rightAligned", "cellStyle": {"function": "params.value != null && params.value < 70 ? {color: '#B42318', fontWeight: 600} : {}"}},
    {"field": "sla_vencidos", "headerName": "Itens vencidos", "width": 120, "valueFormatter": F_INT, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "servicos_abertos", "headerName": "Serviços em aberto", "width": 140, "valueFormatter": F_INT,
     "cellClass": "num", "type": "rightAligned"},
]


def _grade(df: pd.DataFrame, primeiras: list[dict], altura: int, id_=None):
    linhas = df.round(2).astype(object).where(df.notna(), None).to_dict("records")
    kw = {"id": id_} if id_ else {}
    opcoes = {"tooltipShowDelay": 300, "animateRows": False}
    estilo = {"height": altura}
    if len(linhas) <= 10:                      # poucas linhas: a grade cresce só o necessário
        opcoes["domLayout"] = "autoHeight"
        estilo = {}
    return dag.AgGrid(rowData=linhas, columnDefs=primeiras + COL_PAN, className="ag-theme-quartz",
                      style=estilo, defaultColDef={"sortable": True, "resizable": True, "filter": True},
                      dashGridOptions=opcoes, **kw)


def _linhas_fontes(f: pd.DataFrame) -> list[dict]:
    t = f.assign(posicao=f["posicao"].dt.strftime("%Y-%m-%dT%H:%M:%S"))[["fonte", "posicao", "situacao", "detalhe"]]
    return t.astype(object).where(t.notna(), None).to_dict("records")


@callback(Output("vg-conteudo", "children"), *ENTRADAS)
def atualizar(segmentos, obras, ini, fim):
    areas = vg.carregar(segmentos, obras, ini, fim)
    if not any(a.ok for a in areas.values()):
        return vazio("Nenhuma fonte disponível (ou nada no seu escopo de acesso).")
    fontes = vg.fontes()
    pontos = vg.pontos_de_atencao(areas, fontes)
    seg = vg.panorama(areas, "segmento")
    obra = vg.panorama(areas, "cod_obra")
    cfg = {"displaylogo": False}
    blocos = [_cards(areas)]
    blocos.append(html.Div([
        cartao("Pontos de atenção", _pontos(pontos), classe="grafico-card"),
        cartao("Atualização das fontes", dag.AgGrid(
            rowData=_linhas_fontes(fontes),
            columnDefs=[{"field": "fonte", "headerName": "Fonte", "flex": 1.4, "minWidth": 180},
                        {"field": "posicao", "headerName": "Posição", "width": 140, "valueFormatter": F_DATAHORA},
                        {"field": "situacao", "headerName": "Situação", "width": 120,
                         "cellStyle": {"function": "params.value != 'ok' ? {color: '#B42318', fontWeight: 600} : "
                                                   "{color: '#0F7B6C', fontWeight: 600}"}},
                        {"field": "detalhe", "headerName": "Detalhe", "flex": 1, "tooltipField": "detalhe"}],
            className="ag-theme-quartz", style={"height": 330}, defaultColDef={"resizable": True}),
            classe="grafico-card"),
    ], className="cv-grid", style={"gridTemplateColumns": "minmax(0,1.3fr) minmax(0,1fr)"}))
    if len(seg):
        g1 = graficos.barras_h(seg["segmento"], seg["compras"], "Compras no período")
        g2 = graficos.empilhado_h(seg["segmento"], seg["estoque"], seg["contratos_saldo"],
                                  series=("Estoque", "Contratos a medir"))
        blocos.append(html.Div([
            cartao("Compras no período por vertical", dcc.Graph(figure=g1, config=cfg), classe="grafico-card"),
            cartao("Exposição por vertical: estoque + contratos a medir", dcc.Graph(figure=g2, config=cfg),
                   classe="grafico-card"),
        ], className="cv-grid", style={"gridTemplateColumns": "minmax(0,1fr) minmax(0,1fr)"}))
        blocos.append(cartao("Panorama por vertical", _grade(seg, [
            {"field": "segmento", "headerName": "Vertical", "minWidth": 160, "pinned": "left"}], 330)))
    if len(obra):
        obra = obra.assign(obra=obra["cod_obra"].astype("Int64").astype(str) + " - " + obra["nome"].fillna("").astype(str)
                           .str.replace(r"^\d+\s*-\s*", "", regex=True))
        blocos.append(cartao(f"Panorama por obra ({num(len(obra))})", _grade(obra, [
            {"field": "obra", "headerName": "Obra", "minWidth": 260, "flex": 1, "pinned": "left", "tooltipField": "obra"},
            {"field": "segmento", "headerName": "Vertical", "width": 130}], 520),
            html.Span("Ordenado por compras no período; clique nos cabeçalhos para reordenar (ex.: contratos vencidos ou "
                      "SLA).", className="cv-nota")))
    return blocos


@callback(Output("vg-rel-down", "data"), Input("vg-rel", "n_clicks"),
          *[State(i.component_id, i.component_property) for i in ENTRADAS], prevent_initial_call=True)
def gerar_relatorio(n, segmentos, obras, ini, fim):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    partes = []
    if ini and fim:
        partes.append(f"{pd.Timestamp(ini):%d/%m/%Y} a {pd.Timestamp(fim):%d/%m/%Y}")
    if segmentos:
        partes.append("verticais: " + ", ".join(segmentos))
    if obras:
        partes.append(f"{len(obras)} obra(s)")
    return dcc.send_bytes(rel.visao_geral(segmentos, obras, ini, fim, " · ".join(partes) or "sem filtros"),
                          nome_arquivo("visao_geral"))
