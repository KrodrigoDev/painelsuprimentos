"""Comparativo de fornecedores para um material (e seus equivalentes do catálogo)."""
from __future__ import annotations

import json

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import no_update, State, Input, Output, callback, dcc, html

from app.components import graficos
from app.components.ui import brl, brl_curto, cabecalho, cartao, dropdown, filtro, kpi, nota, num, pct, periodo, selo, vazio
from app.repositories import catalogo_repo
from app.services import inteligencia as ig
from app.pages.oportunidades import F_BRL, F_NUM, F_PCT

F_DATA = {"function": "dataBR(params.value)"}


def _c(campo, nome, fmt=None, w=None, **kw):
    col = {"field": campo, "headerName": nome, **kw}
    if fmt is not None:
        col["valueFormatter"] = fmt
        if fmt is not F_DATA:
            col.update(cellClass="num", type="rightAligned")
    if w:
        col["width"] = w
    return col


COLUNAS = [
    _c("data", "Data", F_DATA, 104, sort="desc", pinned="left"),
    _c("fornecedor", "Fornecedor", minWidth=190, flex=1, tooltipField="fornecedor", pinned="left"),
    _c("cnpj", "CNPJ", w=150),
    _c("cod_pedido", "Pedido", w=90), _c("numero_item", "Item", w=66), _c("cod_cotacao", "Cotação", w=90),
    _c("nf", "Nota fiscal", w=120),
    _c("descricao_completa", "Descrição original", minWidth=240, flex=2, tooltipField="descricao_completa"),
    _c("descricao_canonica", "Descrição normalizada", minWidth=200, flex=1, tooltipField="descricao_canonica"),
    _c("cod_insumo", "Cód. insumo", w=100), _c("obra", "Obra", minWidth=170, tooltipField="obra"),
    _c("empreendimento", "Empreendimento", minWidth=150, tooltipField="empreendimento"),
    _c("quantidade", "Qtd", F_NUM, 90), _c("unidade", "Un.", w=62),
    _c("preco", "Preço unit.", F_BRL, 115), _c("frete_unitario", "Frete un.", F_BRL, 100),
    _c("pct_ipi", "IPI %", F_PCT, 80), _c("pct_icms", "ICMS %", F_PCT, 86),
    _c("condicao_pagamento", "Cond. pagamento", w=140, tooltipField="condicao_pagamento"),
    _c("preco_base", "Preço comparável", F_BRL, 135), _c("unidade_base", "Un. base", w=80),
    _c("preco_referencia", "Referência", F_BRL, 120),
    _c("fornecedor_referencia", "Fornecedor da referência", minWidth=170, tooltipField="fornecedor_referencia"),
    _c("pedido_referencia", "Pedido ref.", w=96),
    _c("dif_unit", "Dif. unit.", F_BRL, 110), _c("dif_pct", "Dif. %", F_PCT, 84),
    _c("economia_potencial", "Economia pot.", F_BRL, 125),
    _c("confianca_membro", "Similaridade / conf.", F_NUM, 120), _c("origem_equivalencia", "Equivalência", w=170),
    _c("comparabilidade", "Comparabilidade", minWidth=230, tooltipField="comparabilidade"),
]


def _opcoes_material():
    try:
        m = ig.opcoes_materiais()
    except Exception as exc:  # noqa: BLE001
        return [], str(exc).splitlines()[0]
    m = m[(m["fornecedores"] >= 2) | (m["insumos"] >= 2)].head(3000)
    return [{"label": f"{r.nome[:70]}  ·  {r.fornecedores} fornec. · {r.insumos} insumo(s) · {brl_curto(r.valor)}",
             "value": r.id_grupo} for r in m.itertuples()], None


def layout(grupo=None, **_):
    opcoes, erro = _opcoes_material()
    if erro:
        return html.Div([cabecalho("Comparativo de fornecedores", ""), vazio(f"Erro de conexão: {erro}")])
    if grupo and grupo not in {o["value"] for o in opcoes}:
        b = ig.base()
        nome = b.loc[b["id_grupo"] == grupo, "nome_grupo"]
        if len(nome):
            opcoes = [{"label": nome.iat[0], "value": grupo}] + opcoes
    b = ig.base()
    return html.Div([
        cabecalho("Comparativo de fornecedores",
                  "Compras de um material e de seus equivalentes aprovados, com o preço de referência e o que "
                  "impede a comparação direta.", relatorio="cp"),
        html.Div([
            filtro("Material (grupo de equivalência)", dropdown("cp-material", opcoes, placeholder="Busque o material…",
                                                                valor=grupo or (opcoes[0]["value"] if opcoes else None),
                                                                clearable=False), "largo"),
            filtro("Período", periodo("cp-periodo", b["data_pedido"].min().date() if len(b) else None,
                                      b["data_pedido"].max().date() if len(b) else None), "largo"),
            filtro("Obras", dropdown("cp-obras", [{"label": r.obra, "value": r.cod_obra} for r in
                                                  b.drop_duplicates("cod_obra").sort_values("obra").itertuples()],
                                     multi=True)),
        ], className="filtros"),
        dcc.Loading(html.Div(id="cp-conteudo"), type="dot", color="#1B365D"),
    ])


dash.register_page(__name__, path="/comparativo", name="Comparativo de fornecedores",
                   title="Comparativo · Suprimentos", layout=layout)


def _membros(d: pd.DataFrame):
    chaves = d["chave"].unique().tolist()
    perf = catalogo_repo.perfis_salvos(chaves)
    linhas = []
    for r in d.drop_duplicates("chave").itertuples():
        p = perf[perf["chave"] == r.chave]
        atrs = p["atributos"].iat[0] if len(p) else {}
        atrs = json.loads(atrs) if isinstance(atrs, str) else (atrs or {})
        atr_txt = " · ".join(f"{k.replace('_', ' ')}: {', '.join(map(str, v)) if isinstance(v, list) else v}"
                             for k, v in atrs.items() if k not in ("numeros", "tipo_material")) or "—"
        linhas.append(html.Tr([
            html.Td([html.Div(r.descricao_completa, className="par-desc"),
                     html.Div(p["descricao_canonica"].iat[0] if len(p) else "", className="par-canon")]),
            html.Td(f"{r.cod_insumo}" + (f" / det. {r.cod_detalhe}" if r.cod_detalhe else ""), className="mono"),
            html.Td(r.categoria), html.Td(r.unidade),
            html.Td(atr_txt, className="obs"),
            html.Td([selo(r.origem_equivalencia, "ok" if r.origem_equivalencia != "catálogo (automática)" else "info"),
                     html.Div(f"confiança {r.confianca_membro:.0f}", className="obs")]),
        ]))
    return html.Table([html.Thead(html.Tr([html.Th(h) for h in ("Descrição original / normalizada", "Código",
                                                                  "Categoria", "Un.", "Atributos técnicos extraídos",
                                                                  "Equivalência")])),
                       html.Tbody(linhas)], className="tabela")


@callback(Output("cp-conteudo", "children"), Input("cp-material", "value"), Input("cp-periodo", "start_date"),
          Input("cp-periodo", "end_date"), Input("cp-obras", "value"))
def mostrar(grupo, ini, fim, obras):
    if not grupo:
        return vazio("Escolha um material.")
    d = ig.detalhe_material(grupo, ini, fim, obras)
    if d.empty:
        return vazio("Sem compras deste material no período/obras selecionados.")
    unid = d["unidade_base"].iat[0]
    ok = d[d["comparavel"] & ~d["atipico"]]
    forn = ig.resumo_por(d, ["cod_fornecedor", "fornecedor"])
    melhor = forn.loc[forn["preco_medio"].idxmin()] if len(forn) else None
    nao_comp = d[~d["comparavel"] | d["atipico"]]
    perf = catalogo_repo.perfis_salvos(d["chave"].unique().tolist()).set_index("chave")["descricao_canonica"]
    grade = d.assign(data=d["data_pedido"].dt.strftime("%Y-%m-%d"), nf="não disponível",
                     descricao_canonica=d["chave"].map(perf))
    economia = float(d["economia_potencial"].sum())
    return html.Div([
        html.Div([
            kpi("Compras comparáveis", num(len(ok)), f"de {num(len(d))} · {num(ok['cod_fornecedor'].nunique())} fornecedores",
                "neutro"),
            kpi("Preço mediano", f"{brl(ok['preco_base'].median())}/{unid}", "robusto a valores extremos", "neutro"),
            kpi("Menor preço comparável", f"{brl(ok['preco_base'].min())}/{unid}",
                ok.loc[ok["preco_base"].idxmin(), "fornecedor"] if len(ok) else "", "neutro"),
            kpi("Fornecedor com menor preço médio", melhor["fornecedor"] if melhor is not None else "—",
                f"{brl(melhor['preco_medio'])}/{unid} em {int(melhor['n'])} compra(s)" if melhor is not None else "",
                "neutro texto"),
            kpi("Pago acima da referência", brl_curto(economia),
                "Σ (preço − referência) × qtd nas compras listadas · não é a economia do ranking", "neutro",
                tag="estimativa"),
            kpi("Não diretamente comparáveis", num(len(nao_comp)), "unidade/atípico — fora dos cálculos", "neutro"),
        ], className="port-kpi-grid", style={"marginBottom": 14}),
        cartao("Insumos que compõem este material", _membros(d),
               html.Span("Equivalências vêm do catálogo (aprovadas por pessoa ou automáticas de alta confiança, sem "
                         "conflito técnico). Corrija em Correspondências.", className="cv-nota")),
        html.Div([
            cartao("Preço comparável por fornecedor", dcc.Graph(
                figure=graficos.barras_preco(forn.rename(columns={"n": "n"}), "fornecedor", "cod_fornecedor", unid),
                config={"displaylogo": False}), fonte=f"R$/{unid}", classe="grafico-card"),
            cartao("Resumo por fornecedor", html.Table([
                html.Thead(html.Tr([html.Th(h) for h in ("Fornecedor", "Compras", "Mediana", "Mínimo", "Último",
                                                          "Volume")])),
                html.Tbody([html.Tr([html.Td(r.fornecedor[:34]), html.Td(int(r.n), className="mono"),
                                     html.Td(brl(r.mediana), className="mono"), html.Td(brl(r.minimo), className="mono"),
                                     html.Td(brl(r.ultimo_preco), className="mono"),
                                     html.Td(f"{num(r.qtd, 1)} {unid}", className="mono")])
                            for r in forn.sort_values("mediana").itertuples()])], className="tabela")),
        ], className="cv-grid"),
        cartao("Compras e documentos", dag.AgGrid(
            columnDefs=COLUNAS, rowData=grade.to_dict("records"), className="ag-theme-quartz",
            defaultColDef={"sortable": True, "resizable": True, "filter": True},
            dashGridOptions={"tooltipShowDelay": 300, "enableCellTextSelection": True,
                             "rowClassRules": {"linha-atipica": "params.data.atipico === true",
                                               "linha-ressalva": "params.data.comparabilidade !== 'direta'"}},
            csvExportParams={"fileName": "comparativo_fornecedores.csv", "columnSeparator": ";"},
            style={"height": 480}),
            html.Span("Referência = menor preço comparável de OUTRO fornecedor até 180 dias da compra. Linhas em "
                      "vermelho = preço atípico (fora dos cálculos); marca amarela = comparação com ressalva "
                      "(convertida, equivalente ou pendente). Nota fiscal não existe na fonte atual (pedidos de "
                      "compra).", className="cv-nota")),
        nota(html.B("Não diretamente comparáveis: "), "quando a unidade não tem conversão segura (ex.: caixa sem "
             "quantidade informada), quando o preço é atípico ou quando a equivalência ainda não foi validada, a "
             "linha aparece mas não entra em referência nem em economia. Diferenças de frete, impostos e condição "
             "de pagamento ficam visíveis nas colunas e nas ressalvas — o preço comparável usa o preço líquido do "
             "pedido."),
    ])


# ── Relatório em PowerPoint (botão "Gerar relatório") ────────────────────────
@callback(Output("cp-rel-down", "data"), Input("cp-rel", "n_clicks"),
          State("cp-material", "value"),
          State("cp-periodo", "start_date"),
          State("cp-periodo", "end_date"),
          State("cp-obras", "value"), prevent_initial_call=True)
def gerar_relatorio(n, grupo, ini, fim, obras):
    if not n:
        return no_update
    from app.relatorios import paginas as rel
    from app.relatorios.apresentacao import nome_arquivo
    return dcc.send_bytes(rel.comparativo(grupo, ini, fim, obras), nome_arquivo("comparativo"))
