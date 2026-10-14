"""Histórico de preços de um material: evolução, fornecedores, obras e atípicos (estatística robusta)."""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import numpy as np
from dash import no_update, State, Input, Output, callback, dcc, html

from app.components import graficos
from app.components.ui import brl, cabecalho, cartao, dropdown, filtro, kpi, nota, num, pct, periodo, vazio
from app.pages.comparativo import F_DATA, _c, _opcoes_material
from app.pages.oportunidades import F_BRL, F_NUM, F_PCT
from app.services import inteligencia as ig

COLUNAS = [
    _c("data", "Data", F_DATA, 104, sort="desc"), _c("fornecedor", "Fornecedor", minWidth=190, flex=1,
                                                     tooltipField="fornecedor"),
    _c("obra", "Obra", minWidth=170, flex=1, tooltipField="obra"), _c("cod_pedido", "Pedido", w=90),
    _c("descricao_completa", "Insumo", minWidth=220, flex=1, tooltipField="descricao_completa"),
    _c("quantidade", "Qtd", F_NUM, 90), _c("unidade", "Un.", w=62), _c("preco_base", "Preço comparável", F_BRL, 135),
    _c("preco_anterior_forn", "Compra anterior (mesmo forn.)", F_BRL, 175),
    _c("var_vs_anterior_pct", "Var. vs anterior", F_PCT, 120),
    _c("mediana_grupo", "Mediana do material", F_BRL, 150), _c("z_robusto", "z robusto", F_NUM, 96),
    _c("situacao_preco", "Leitura", minWidth=210, tooltipField="situacao_preco"),
]


def layout(grupo=None, **_):
    opcoes, erro = _opcoes_material()
    if erro:
        return html.Div([cabecalho("Histórico de preços", ""), vazio(f"Erro de conexão: {erro}")])
    b = ig.base()
    return html.Div([
        cabecalho("Histórico de preços",
                  "Evolução do preço comparável por fornecedor e por obra, com valores atípicos isolados por "
                  "estatística robusta (mediana e MAD).", relatorio="hp"),
        html.Div([
            filtro("Material (grupo de equivalência)", dropdown("hp-material", opcoes, placeholder="Busque o material…",
                                                                valor=grupo or (opcoes[0]["value"] if opcoes else None),
                                                                clearable=False), "largo"),
            filtro("Período", periodo("hp-periodo", b["data_pedido"].min().date() if len(b) else None,
                                      b["data_pedido"].max().date() if len(b) else None), "largo"),
            filtro("Série do gráfico", dropdown("hp-serie", [{"label": "Fornecedor", "value": "fornecedor"},
                                                             {"label": "Obra", "value": "obra"}], valor="fornecedor",
                                                clearable=False)),
        ], className="filtros"),
        dcc.Loading(html.Div(id="hp-conteudo"), type="dot", color="#1B365D"),
    ])


dash.register_page(__name__, path="/historico", name="Histórico de preços", title="Histórico · Suprimentos",
                   layout=layout)


@callback(Output("hp-conteudo", "children"), Input("hp-material", "value"), Input("hp-periodo", "start_date"),
          Input("hp-periodo", "end_date"), Input("hp-serie", "value"))
def mostrar(grupo, ini, fim, serie):
    if not grupo:
        return vazio("Escolha um material.")
    d = ig.detalhe_material(grupo, ini, fim)
    if d.empty:
        return vazio("Sem compras deste material no período.")
    unid = d["unidade_base"].iat[0]
    comp = d[d["comparavel"]]
    ok = comp[~comp["atipico"]]
    if ok.empty:
        return vazio("Nenhuma compra com preço comparável neste material.")
    med = ok["preco_base"].median()
    mad = (ok["preco_base"] - med).abs().median()
    meses = max(1, ok["ano_mes"].nunique())
    ult = ok.iloc[-1]
    ant = ok[ok["cod_fornecedor"] == ult.cod_fornecedor].iloc[:-1]
    var_ult = (ult.preco_base / ant["preco_base"].median() - 1) * 100 if len(ant) >= 1 else np.nan

    def leitura(r):
        if not r.comparavel:
            return f"não comparável: {r.regra_unidade}"
        if r.atipico:
            return "atípico — conferir registro (fora da análise)"
        if not np.isnan(r.var_vs_anterior_pct) and r.var_vs_anterior_pct >= 10 and r.z_robusto and r.z_robusto > 2:
            return "aumento acima do padrão histórico"
        if r.z_robusto is not None and not np.isnan(r.z_robusto) and r.z_robusto < -1.5:
            return "abaixo do padrão (boa referência)"
        return "dentro do padrão"

    grade = d.assign(data=d["data_pedido"].dt.strftime("%Y-%m-%d"))
    grade["situacao_preco"] = [leitura(r) for r in d.itertuples(index=False)]
    mensal = ig.estatisticas_mensais(d)
    por_obra = ig.resumo_por(d, ["cod_obra", "obra"])
    return html.Div([
        html.Div([
            kpi("Mediana", f"{brl(med)}/{unid}", f"MAD {brl(mad)} · {num(len(ok))} compras", "neutro"),
            kpi("Mínimo comparável", f"{brl(ok['preco_base'].min())}/{unid}",
                ok.loc[ok["preco_base"].idxmin(), "fornecedor"][:30], "neutro"),
            kpi("Média ponderada", f"{brl((ok['preco_base'] * ok['qtd_base']).sum() / ok['qtd_base'].sum())}/{unid}",
                "pelo volume comprado", "neutro"),
            kpi("Última compra", f"{brl(ult.preco_base)}/{unid}",
                f"{ult.data_pedido:%d/%m/%Y} · {ult.fornecedor[:22]}"
                + (f" · {pct(var_ult)} vs histórico do fornecedor" if not np.isnan(var_ult) else ""), "neutro"),
            kpi("Frequência", f"{num(len(ok) / meses, 1)} compras/mês", f"{num(ok['qtd_base'].sum(), 1)} {unid} no período",
                "neutro"),
            kpi("Atípicos isolados", num(int(comp["atipico"].sum())), "|z robusto| > 3,5 ou fora de 5× a mediana",
                "neutro"),
        ], className="port-kpi-grid", style={"marginBottom": 14}),
        cartao(f"Preço comparável por {'fornecedor' if serie == 'fornecedor' else 'obra'}",
               dcc.Graph(figure=graficos.linhas_preco(comp, serie=serie or "fornecedor", unidade=unid),
                         config={"displaylogo": False}),
               html.Span("Cinco séries de maior volume; as demais em cinza ('Outros'). X vermelho = preço atípico, "
                         "fora de médias, mínimos e oportunidades.", className="cv-nota"),
               fonte=f"R$/{unid}", classe="grafico-card"),
        html.Div([
            cartao("Mediana, média ponderada e mínimo por mês", dcc.Graph(figure=graficos.estatisticas_mes(mensal, unid),
                                                                          config={"displaylogo": False}),
                   fonte=f"R$/{unid}", classe="grafico-card"),
            cartao("Comparação entre obras", dcc.Graph(figure=graficos.barras_preco(
                por_obra, "obra", "cod_obra", unid, limite=12), config={"displaylogo": False}),
                fonte=f"R$/{unid}", classe="grafico-card"),
        ], className="cv-grid"),
        cartao("Compras (variação em relação à compra anterior do mesmo fornecedor)", dag.AgGrid(
            columnDefs=COLUNAS, rowData=grade.to_dict("records"), className="ag-theme-quartz",
            defaultColDef={"sortable": True, "resizable": True, "filter": True},
            dashGridOptions={"tooltipShowDelay": 300,
                             "rowClassRules": {"linha-atipica": "params.data.atipico === true"}},
            csvExportParams={"fileName": "historico_precos.csv", "columnSeparator": ";"}, style={"height": 440})),
        nota(html.B("Leitura cuidadosa: "), "um aumento não é automaticamente oportunidade de desconto — pode refletir "
             "reajuste de mercado, especificação, frete ou prazo. 'Aumento acima do padrão' exige variação ≥ 10% sobre "
             "a compra anterior do mesmo fornecedor E preço acima de 2 desvios robustos da mediana do material."),
    ])


# ── Relatório em PowerPoint (botão "Gerar relatório") ────────────────────────
@callback(Output("hp-rel-down", "data"), Input("hp-rel", "n_clicks"),
          State("hp-material", "value"),
          State("hp-periodo", "start_date"),
          State("hp-periodo", "end_date"), prevent_initial_call=True)
def gerar_relatorio(n, grupo, ini, fim):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    return dcc.send_bytes(rel.historico(grupo, ini, fim), nome_arquivo("historico_precos"))
