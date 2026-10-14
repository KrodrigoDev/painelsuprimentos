"""Curva ABC de insumos (apropriações): onde está o valor e como o preço de cada insumo evoluiu ano a ano."""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from app.components import detalhe, graficos
from app.components.ui import brl, brl_curto, cabecalho, cartao, dropdown, filtro, kpi, nota, num, pct, selo, vazio
from app.pages.oportunidades import F_BRL, F_NUM, F_PCT
from app.repositories import rpa_repo
from app.services import curva_abc as ca

P = "ca-dm"
F_BRL4 = {"function": "params.value == null ? '' : Number(params.value).toLocaleString('pt-BR', {style:'currency', "
                      "currency:'BRL', minimumFractionDigits: 2, maximumFractionDigits: 4})"}
F_VAR = {"function": "params.value == null ? '' : (params.value > 0 ? '+' : '') + Number(params.value)"
                     ".toLocaleString('pt-BR', {maximumFractionDigits: 1}) + '%'"}

COLUNAS = [
    {"field": "posicao", "headerName": "#", "width": 70, "cellClass": "num", "type": "rightAligned", "pinned": "left"},
    {"field": "classe", "headerName": "Classe", "width": 82, "cellClass": "classe-abc"},
    {"field": "insumo", "headerName": "Insumo", "minWidth": 260, "flex": 2, "tooltipField": "insumo", "pinned": "left"},
    {"field": "grupo", "headerName": "Grupo de insumo", "minWidth": 190, "flex": 1, "tooltipField": "grupo"},
    {"field": "tabela", "headerName": "Tabela", "width": 120},
    {"field": "detalhes", "headerName": "Detalhes", "width": 92, "cellClass": "num", "type": "rightAligned"},
    {"field": "unidade", "headerName": "Un.", "width": 64},
    {"field": "quantidade", "headerName": "Quantidade", "width": 120, "valueFormatter": F_NUM, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "preco_medio", "headerName": "Preço médio", "width": 125, "valueFormatter": F_BRL4, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "preco_anterior", "headerName": "Preço ano ant.", "width": 125, "valueFormatter": F_BRL4,
     "cellClass": "num", "type": "rightAligned"},
    {"field": "var_preco_pct", "headerName": "Var. preço", "width": 105, "valueFormatter": F_VAR,
     "cellClassRules": {"var-alta": "params.value > 0", "var-baixa": "params.value < 0"}, "type": "rightAligned"},
    {"field": "valor", "headerName": "Valor apropriado", "width": 145, "valueFormatter": F_BRL, "cellClass": "num",
     "type": "rightAligned", "sort": "desc"},
    {"field": "pct_part", "headerName": "% part.", "width": 92, "valueFormatter": F_PCT, "cellClass": "num",
     "type": "rightAligned"},
    {"field": "pct_acum", "headerName": "% acum.", "width": 92, "valueFormatter": F_PCT, "cellClass": "num",
     "type": "rightAligned"},
]


def _c(campo, rotulo, formato="texto", total=False, peso=None):
    d = {"campo": campo, "rotulo": rotulo, "formato": formato, "total": total}
    if peso:
        d["peso"] = peso
    return d


COLS_RANK_EXPORT = [_c("posicao", "#", "int", peso=0.4), _c("classe", "Classe", peso=0.5), _c("insumo", "Insumo", peso=3.2),
                    _c("grupo", "Grupo", peso=2), _c("unidade", "Un.", peso=0.5), _c("quantidade", "Qtd.", "num2"),
                    _c("preco_medio", "Preço médio", "brl4"), _c("var_preco_pct", "Var. preço", "pct", peso=0.8),
                    _c("valor", "Valor apropriado", "brl", True, 1.2), _c("pct_part", "% part.", "pct", True, 0.7),
                    _c("pct_acum", "% acum.", "pct", peso=0.7)]


_PREPARADA: dict = {}


def _base():
    """Preparada uma vez por carga do cache (sem escopo); o escopo do usuário é aplicado a cada chamada."""
    bruta = rpa_repo.curva_abc_bruta()
    if _PREPARADA.get("bruta") is not bruta:   # recalcula só quando o cache do repositório renova
        _PREPARADA.update(bruta=bruta, pronta=ca.preparar(bruta))
    return rpa_repo.escopar_curva_abc(_PREPARADA["pronta"])


def _fonte():
    try:
        ctl = rpa_repo.controle_curva_abc()
    except Exception:  # noqa: BLE001
        return None
    if ctl.empty:
        return None
    pos = ctl["posicao_em"].max()
    return html.Div([html.Div(f"posição Sienge: {pos:%d/%m/%Y %H:%M}" if pd.notna(pos) else ""),
                     html.Div(f"{int(ctl['conciliado'].sum())}/{len(ctl)} relatórios conferidos com o Total geral")])


def layout(insumo=None, **_):
    try:
        b = _base()
    except Exception as exc:  # noqa: BLE001
        return html.Div([cabecalho("Curva ABC — insumos", ""),
                         vazio("Tabela suprimentos.fato_curva_abc_insumo indisponível. Rode a DAG etl_suprimentos_rpa "
                               f"(ou python main.py --etapa curva_abc no airflow_api_sienge). Detalhe: "
                               f"{str(exc).splitlines()[0]}")])
    if b.empty:
        return html.Div([cabecalho("Curva ABC — insumos", ""), vazio("Sem dados carregados.")])
    anos = sorted(b["ano"].unique(), reverse=True)
    grupos = (b.groupby("grupo_rotulo")["preco_total"].sum().sort_values(ascending=False).index.tolist())
    tabelas = b.drop_duplicates("cod_tabela").sort_values("cod_tabela")
    filtros = html.Div([
        filtro("Ano", dropdown("ca-ano", [{"label": str(a), "value": int(a)} for a in anos], valor=int(anos[0]),
                               clearable=False), "estreito"),
        filtro("Comparar preço com", dropdown("ca-ano-ant", [{"label": str(a), "value": int(a)} for a in anos],
                                              valor=int(anos[1]) if len(anos) > 1 else None,
                                              placeholder="sem comparação"), "estreito"),
        filtro("Grupo de insumo", dropdown("ca-grupos", [{"label": g, "value": g} for g in grupos], multi=True), "largo"),
        filtro("Tabela de insumos", dropdown("ca-tabelas", [{"label": f"{r.cod_tabela} - {r.tabela}",
                                                             "value": int(r.cod_tabela)} for r in tabelas.itertuples()],
                                             multi=True)),
        filtro("Tipo", dropdown("ca-tipos", [{"label": t, "value": t} for t in
                                             sorted(b["tipo_insumo"].fillna("—").unique())], multi=True), "estreito"),
    ], className="filtros")

    return html.Div([
        cabecalho("Curva ABC — insumos",
                  "Onde está o valor apropriado em obra e como o preço médio de cada insumo evoluiu de um ano para o "
                  "outro.", _fonte(), relatorio="ca"),
        filtros,
        dcc.Loading(html.Div(id="ca-visao"), type="dot", color="#1B365D"),
        html.H2("Análise do insumo", className="secao-titulo", style={"marginTop": 26}),
        html.Div([
            filtro("Buscar insumo (código ou descrição)", dcc.Input(id="ca-busca", debounce=True, className="cv-input",
                                                                     placeholder="ex.: 1001, camisa, cimento CP II")),
            filtro("Insumo", dropdown("ca-insumo", [], placeholder="Escolha o insumo", valor=insumo, clearable=False),
                   "largo"),
            filtro("Detalhe", dropdown("ca-detalhes", [], multi=True, placeholder="Todos"), "largo"),
        ], className="filtros"),
        dcc.Loading(html.Div(id="ca-insumo-conteudo"), type="dot", color="#1B365D"),
        nota(html.B("Como ler: "), "fonte = relatório 'Curva ABC de Apropriações' do Sienge (um por ano), conferido com o "
             "Total geral. Preço médio = valor ÷ quantidade, só com detalhes na mesma unidade e sem o '*' do Sienge "
             "(quantidade não convertida para a unidade do cadastro). O código do insumo depende da tabela de insumos "
             "(Tabela geral × Tabela Telesil), por isso o insumo é identificado por tabela + código. A classe ABC do "
             "ranking é recalculada no recorte filtrado (A até 80% do valor, B até 95%, C o resto)."),
        dcc.Store(id="ca-rank-store"),
        *detalhe.modal(P),
    ])


dash.register_page(__name__, path="/curva-abc", name="Curva ABC - Insumo", title="Curva ABC · Suprimentos",
                   layout=layout)
detalhe.registrar(P)


def _filtrada(grupos, tabelas, tipos):
    return ca.filtrar(_base(), None, tabelas, grupos, tipos)


def _td_var(v):
    if v != v or v is None:
        return html.Td("")
    return html.Td(f"{v:+.2f}%".replace(".", ","), className="mono " + ("var-alta" if v > 0 else "var-baixa" if v < 0 else ""))


def _k(chave, *a, **kw):
    return detalhe.kpi_clicavel({"type": "ca-kpi", "k": chave}, kpi(*a, **kw))


@callback(Output("ca-visao", "children"), Output("ca-insumo", "options"), Output("ca-insumo", "value"),
          Input("ca-ano", "value"), Input("ca-ano-ant", "value"), Input("ca-grupos", "value"),
          Input("ca-tabelas", "value"), Input("ca-tipos", "value"), State("ca-insumo", "value"))
def visao(ano, ano_ant, grupos, tabelas, tipos, insumo_atual):
    d = _filtrada(grupos, tabelas, tipos)
    ano_ant = ano_ant if ano_ant != ano else None
    rank = ca.ranking(d, ano, ano_ant)
    if rank.empty:
        return vazio("Sem insumos no recorte."), [], None
    r = ca.resumo_ano(rank)
    gr = ca.por_grupo(d, ano).head(12)
    comp = f"vs {ano_ant}" if ano_ant else "sem ano de comparação"
    kpis = html.Div([
        _k("valor", f"Valor apropriado em {ano}", brl_curto(r["valor"]), f"{num(r['insumos'])} insumos no recorte",
           "neutro"),
        _k("classe_a", "Classe A", f"{num(r['a_n'])} insumos",
           f"{pct(r['a_pct_itens'], 1)} dos itens = {pct(r['a_valor'] / r['valor'] * 100, 1)} do valor", "neutro"),
        _k("altas", "Alta de preço em A/B", num(r["altas_ab"]), f"insumos A/B mais caros {comp}", "neutro"),
        _k("efeito", "Efeito preço (A/B)", brl_curto(r["efeito_preco_ab"]),
           f"pago a mais pela alta, na quantidade de {ano}", "neutro", tag="estimativa"),
        _k("nao_conv", "Quantidade não convertida", num(int(rank["nao_convertida"].sum())),
           "insumos com '*' do Sienge (preço médio não confiável)", "neutro"),
    ], className="port-kpi-grid", style={"marginBottom": 14, "gridTemplateColumns": "repeat(5, minmax(0, 1fr))"})
    graf = html.Div([
        cartao("Curva ABC do recorte", dcc.Graph(figure=graficos.pareto(ca.pareto(rank)), config={"displaylogo": False}),
               html.Span(f"{num(r['a_n'])} insumos (A) concentram {pct(r['a_valor'] / r['valor'] * 100, 1)} do valor "
                         f"de {ano}.", className="cv-nota"), fonte=str(ano), classe="grafico-card"),
        cartao("Valor por grupo de insumo", dcc.Graph(figure=graficos.barras_h(
            gr["grupo_rotulo"], gr["valor"], "Valor", custom=gr[["pct", "insumos"]].to_numpy(),
            hover="%{y}<br>R$ %{x:,.2f} · %{customdata[0]:.1f}% do ano<br>%{customdata[1]} insumos<extra></extra>"),
            config={"displaylogo": False}), fonte=f"top 12 · {ano}", classe="grafico-card"),
    ], className="cv-grid")
    grade = cartao(f"Ranking de insumos — {ano}", dag.AgGrid(
        id="ca-grade", columnDefs=COLUNAS, rowData=rank.head(3000).to_dict("records"), className="ag-theme-quartz",
        defaultColDef={"sortable": True, "resizable": True, "filter": True},
        dashGridOptions={"rowSelection": {"mode": "singleRow", "checkboxes": False, "enableClickSelection": True},
                         "tooltipShowDelay": 300, "enableCellTextSelection": True, "localeText": {"page": "Página", "of": "de", "to": "a", "pageSizeSelectorLabel": "Linhas por página:", "noRowsToShow": "Sem linhas"}, "pagination": True,
                         "paginationPageSize": 50},
        csvExportParams={"fileName": f"curva_abc_{ano}.csv", "columnSeparator": ";"}, style={"height": 520}),
        html.Span("Clique num insumo para abrir a análise dele abaixo. Var. preço: vermelho = mais caro que no ano "
                  "de comparação.", className="cv-nota"))

    opcoes = [{"label": f"{x.insumo} · {x.tabela}", "value": x.chave_insumo} for x in rank.head(60).itertuples()]
    valor = insumo_atual or rank["chave_insumo"].iat[0]
    if valor not in {o["value"] for o in opcoes}:
        sel = d[d["chave_insumo"] == valor]
        if len(sel):
            opcoes = [{"label": f"{sel['insumo_rotulo'].iat[0]} · {sel['tabela'].iat[0]}", "value": valor}] + opcoes
    return html.Div([kpis, graf, grade]), opcoes, valor


@callback(Output("ca-insumo", "options", allow_duplicate=True), Input("ca-busca", "value"),
          State("ca-insumo", "value"), prevent_initial_call=True)
def buscar(texto, atual):
    if not texto:
        return no_update
    b = _base()
    t = str(texto).strip().lower()
    alvo = b.drop_duplicates("chave_insumo")
    if t.isdigit():
        hit = alvo[alvo["cod_insumo"].astype(str).str.startswith(t)]
    else:
        termos = t.split()
        m = pd.Series(True, index=alvo.index)
        rot = (alvo["insumo_rotulo"] + " " + alvo["detalhe_rotulo"]).str.lower()
        for termo in termos:
            m &= rot.str.contains(termo, regex=False)
        hit = alvo[m]
    valor = b.groupby("chave_insumo")["preco_total"].sum()
    hit = hit.assign(v=hit["chave_insumo"].map(valor)).sort_values("v", ascending=False).head(80)
    return [{"label": f"{x.insumo_rotulo} · {x.tabela}", "value": x.chave_insumo} for x in hit.itertuples()] or no_update


@callback(Output("ca-insumo", "value", allow_duplicate=True), Input("ca-grade", "selectedRows"),
          prevent_initial_call=True)
def escolher_da_grade(linhas):
    return linhas[0]["chave_insumo"] if linhas else no_update


@callback(Output("ca-detalhes", "options"), Output("ca-detalhes", "value"), Input("ca-insumo", "value"))
def opcoes_detalhe(chave):
    if not chave:
        return [], None
    b = _base()
    d = b[b["chave_insumo"] == chave].groupby(["detalhe_rotulo", "unidade_padrao"])["preco_total"].sum() \
        .reset_index().sort_values("preco_total", ascending=False)
    return [{"label": f"{r.detalhe_rotulo} ({r.unidade_padrao})", "value": r.detalhe_rotulo}
            for r in d.drop_duplicates("detalhe_rotulo").itertuples()], None


@callback(Output("ca-insumo-conteudo", "children"), Input("ca-insumo", "value"), Input("ca-detalhes", "value"))
def analise_insumo(chave, detalhes):
    if not chave:
        return vazio("Escolha um insumo (ou clique numa linha do ranking).")
    b = _base()
    s, info = ca.serie_insumo(b, chave, detalhes)
    if s.empty:
        return vazio("Sem dados para este insumo/detalhe.")
    u = info["unidade"] or ""
    avisos = []
    if info["mistura_unidades"]:
        avisos.append(f"Os detalhes estão em unidades diferentes ({', '.join(info['unidades'])}). O preço médio usa só "
                      f"'{u}' (unidade de maior valor); escolha o detalhe para analisar outra unidade.")
    if info["nao_convertida"]:
        avisos.append("Há linhas com '*' do Sienge (quantidade não convertida para a unidade do cadastro): elas entram "
                      "no valor, mas não no preço médio.")
    if info["detalhes"] > 1 and not detalhes:
        avisos.append(f"{info['detalhes']} detalhes somados. Para uma análise mais precisa, escolha o detalhe.")
    cab = html.Div([
        html.Div([html.Div(info["insumo"], className="ins-titulo"),
                  html.Div([html.Span(info["tabela"], className="selo info"), " ",
                            *[html.Div(a, className="ins-aviso") for a in avisos]])]),
        html.Div([html.Div(info["grupo"], className="ins-grupo"),
                  html.Div(["UN: ", html.B(u)], className="ins-un"),
                  html.Div(f"grupo casado por {info['origem_grupo']}", className="ins-origem")], className="ins-dir"),
    ], className="cv-card ins-cab")
    var = info["var_yoy"]
    kpis = html.Div([
        _k("i-preco", f"Preço unit. médio {info['ano_atual'] or ''}", f"{brl(info['preco_atual'])}/{u}",
           "ponderado pela quantidade", "neutro"),
        _k("i-var", "Variação de preço no ano", "—" if var != var else f"{var:+.2f}%".replace(".", ","),
           ("mesmos detalhes nos dois anos" if info["var_mesmos"] else "preço médio vs ano anterior")
           + ("" if info["var_yoy_mix"] != info["var_yoy_mix"] or not info["var_mesmos"]
              else f" · preço médio: {info['var_yoy_mix']:+.1f}%".replace(".", ",")),
           "neutro " + ("kpi-alta" if var == var and var > 0 else
                                                      "kpi-baixa" if var == var and var < 0 else "")),
        _k("i-amp", "Amplitude de preço", brl(info["amplitude"]), f"pico em {info['ano_pico']}", "neutro"),
        _k("i-total", "Valor total acumulado", brl(info["valor_total"], 2), f"{len(s)} ano(s)", "neutro"),
    ], className="port-kpi-grid", style={"margin": "12px 0", "gridTemplateColumns": "repeat(4, minmax(0, 1fr))"})
    graf = html.Div([
        cartao("Evolução do preço unitário médio", dcc.Graph(figure=graficos.serie_anual(
            s["ano"], s["preco_medio"], "Preço médio", sufixo=f"/{u}", casas=4), config={"displaylogo": False}),
            fonte=f"R$/{u}", classe="grafico-card"),
        cartao("Quantidade apropriada", dcc.Graph(figure=graficos.serie_anual(
            s["ano"], s["quantidade"], "Quantidade", prefixo="", sufixo=f" {u}", tipo="barra", casas=0),
            config={"displaylogo": False}), fonte=u, classe="grafico-card"),
        cartao("Variação anual do preço", dcc.Graph(figure=graficos.variacao_anual(s["ano"], s["var_tela_pct"]),
                                                    config={"displaylogo": False}),
               html.Span("vermelho = ficou mais caro · compara o mesmo detalhe nos dois anos (sem efeito de mix)",
                         className="cv-nota"), classe="grafico-card"),
    ], className="cv-grid tres")
    linhas = [html.Tr([html.Td(int(x.ano)), html.Td(brl(x.preco_medio), className="mono"),
                       html.Td(num(x.quantidade, 2), className="mono"), html.Td(x.unidade),
                       html.Td(brl(x.valor, 2), className="mono"), html.Td(pct(x.pct_ano, 3), className="mono"),
                       _td_var(x.var_yoy_pct), _td_var(x.var_mesmos_pct),
                       html.Td("" if x.cobertura_pct != x.cobertura_pct else pct(x.cobertura_pct, 0), className="mono")])
              for x in s.itertuples()]
    tabela = cartao("Por ano", html.Table([
        html.Thead(html.Tr([html.Th(h) for h in ("Ano", "Preço unit. médio", "Quantidade", "Un.", "Valor total",
                                                  "% do ano", "Var. preço médio", "Var. mesmos detalhes",
                                                  "Valor comparável")])),
        html.Tbody(linhas)], className="tabela"))
    det = ca.detalhes_insumo(b, chave, int(s["ano"].max()))
    n_det = len(det)
    tab_det = cartao(f"Detalhes em {int(s['ano'].max())}" + (f" — 15 maiores de {n_det}" if n_det > 15 else ""), html.Table([
        html.Thead(html.Tr([html.Th(h) for h in ("Detalhe", "Un.", "Quantidade", "Preço médio", "Valor", "Classe")])),
        html.Tbody([html.Tr([html.Td(x.detalhe_rotulo + (" *" if x.nao_convertida else "")), html.Td(x.unidade_padrao),
                             html.Td(num(x.quantidade, 2), className="mono"), html.Td(brl(x.preco_medio), className="mono"),
                             html.Td(brl(x.valor, 2), className="mono"), html.Td(selo(x.classe, f"abc-{x.classe}"))])
                    for x in det.head(15).itertuples()])], className="tabela tabela-compacta"),
        html.Span("Todos os detalhes e anos: clique no card 'Valor total acumulado' (exporta PDF/CSV).",
                  className="cv-nota") if n_det > 15 else None)
    return html.Div([cab, kpis, graf, tabela, tab_det])


@callback(*detalhe.saidas(P), Input({"type": "ca-kpi", "k": ALL}, "n_clicks"),
          State("ca-ano", "value"), State("ca-ano-ant", "value"), State("ca-grupos", "value"),
          State("ca-tabelas", "value"), State("ca-tipos", "value"), State("ca-insumo", "value"),
          State("ca-detalhes", "value"), prevent_initial_call=True)
def decompor(_c_, ano, ano_ant, grupos, tabelas, tipos, chave, detalhes):
    if not ctx.triggered or not ctx.triggered[0].get("value") or not isinstance(ctx.triggered_id, dict):
        return (no_update,) * 5
    k = ctx.triggered_id["k"]
    if k.startswith("i-"):
        b = _base()
        linhas = b[b["chave_insumo"] == chave]
        if detalhes:
            linhas = linhas[linhas["detalhe_rotulo"].isin(detalhes)]
        nome = linhas["insumo_rotulo"].iat[0] if len(linhas) else ""
        d = linhas.assign(preco_medio=linhas["preco_total"] / linhas["quantidade"].where(linhas["quantidade"] > 0))
        d = d.sort_values(["ano", "preco_total"], ascending=[False, False])
        d["nc"] = d["qtd_nao_convertida"].map({True: "sim", False: ""})
        cols = [_c("ano", "Ano", peso=0.5), _c("detalhe_rotulo", "Detalhe", peso=3.4), _c("unidade_padrao", "Un.", peso=0.5),
                _c("quantidade", "Quantidade", "num2"), _c("preco_medio", "Preço médio", "brl4"),
                _c("preco_total", "Valor", "brl", True), _c("classe_abc", "Classe (ano)", peso=0.6),
                _c("nc", "Qtd. não conv. (*)", peso=0.8)]
        return detalhe.abrir(nome, f"{len(d)} linha(s) do relatório · ano × detalhe", d, cols,
                             "Preço médio da linha = valor ÷ quantidade do próprio detalhe.")
    d = _filtrada(grupos, tabelas, tipos)
    ano_ant = ano_ant if ano_ant != ano else None
    rank = ca.ranking(d, ano, ano_ant)
    if k == "valor":
        g = ca.por_grupo(d, ano)
        cols = [_c("grupo_rotulo", "Grupo de insumo", peso=3), _c("insumos", "Insumos", "int", True, 0.7),
                _c("valor", "Valor apropriado", "brl", True, 1.2), _c("pct", "% do ano", "pct", True, 0.8)]
        return detalhe.abrir(f"Valor apropriado em {ano}", f"{len(g)} grupo(s) · {num(len(rank))} insumos", g, cols)
    if k == "classe_a":
        a = rank[rank["classe"] == "A"]
        return detalhe.abrir(f"Classe A — {ano}", f"{len(a)} insumo(s) · {pct(a['valor'].sum() / rank['valor'].sum() * 100, 1)} "
                             "do valor do recorte", a, COLS_RANK_EXPORT)
    if k in ("altas", "efeito"):
        a = rank[rank["classe"].isin(["A", "B"]) & (rank["var_preco_pct"] > 0)].copy()
        a = a.rename(columns={"efeito_preco": "efeito"}).sort_values("efeito", ascending=False)
        cols = [_c("classe", "Classe", peso=0.5), _c("insumo", "Insumo", peso=3.2), _c("unidade", "Un.", peso=0.5),
                _c("preco_anterior", f"Preço médio {ano_ant}*", "brl4"), _c("preco_medio", f"Preço médio {ano}*", "brl4"),
                _c("var_preco_pct", "Var. (mesmos detalhes)", "pct", peso=0.9), _c("cobertura_pct", "Valor comparável", "pct", peso=0.8),
                _c("efeito", "Efeito preço", "brl", True, 1.1), _c("valor", "Valor", "brl", True)]
        return detalhe.abrir(f"Insumos A/B mais caros que em {ano_ant}", f"{len(a)} insumo(s) · efeito preço = "
                             "Σ (preço do ano − preço anterior) × quantidade do ano, por detalhe", a, cols,
                             "Compara só o mesmo detalhe na mesma unidade nos dois anos (sem efeito de mix); "
                             "variações acima de 10x são descartadas como prováveis erros de unidade. "
                             "'Valor comparável' = parte do valor do ano que tem par no ano anterior. "
                             "* Preço médio do insumo somando todos os detalhes (pode mudar só pelo mix).")
    if k == "nao_conv":
        a = rank[rank["nao_convertida"]]
        return detalhe.abrir("Insumos com quantidade não convertida (*)", f"{len(a)} insumo(s) · {ano}", a,
                             COLS_RANK_EXPORT, "Revisar a unidade do insumo nas obras (nota do relatório do Sienge).")
    return (no_update,) * 5


# ── Relatório em PowerPoint (botão "Gerar relatório") ────────────────────────
@callback(Output("ca-rel-down", "data"), Input("ca-rel", "n_clicks"),
          State("ca-ano", "value"),
          State("ca-ano-ant", "value"),
          State("ca-grupos", "value"),
          State("ca-tabelas", "value"),
          State("ca-tipos", "value"),
          State("ca-insumo", "value"),
          State("ca-detalhes", "value"), prevent_initial_call=True)
def gerar_relatorio(n, ano, ano_ant, grupos, tabelas, tipos, chave, detalhes):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    return dcc.send_bytes(rel.curva_abc(_base(), ano, ano_ant, grupos, tabelas, tipos, chave, detalhes), nome_arquivo("curva_abc"))
