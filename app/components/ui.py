"""Componentes visuais compartilhados (classes do tema base 01_construview_base.css)."""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html


from app.formatacao import brl, brl_curto, num, pct  # noqa: F401,E402


# ── blocos ───────────────────────────────────────────────────────────────────
def cabecalho(titulo: str, subtitulo: str, direita=None, relatorio: str | None = None):
    """relatorio = prefixo dos ids do botão 'Gerar relatório' (f"{prefixo}-rel" / f"{prefixo}-rel-down")."""
    lado = []
    if relatorio:
        lado.append(botao_relatorio(relatorio))
    if direita is not None:
        lado.append(html.Div(direita, className="fonte-dados"))
    return html.Div([
        html.Div([html.H1(titulo, className="titulo"), html.P(subtitulo, className="subtitulo")]),
        html.Div(lado, className="cabecalho-lado") if lado else None,
    ], className="cabecalho-pagina")


def botao_relatorio(p: str):
    from app.seguranca import sessao
    pode = sessao.pode("gerar_relatorio")
    return html.Div([
        html.Button([html.Span("▤", className="rel-ico"), "Gerar relatório"], id=f"{p}-rel", n_clicks=0,
                    className="btn btn-pri btn-p btn-rel", disabled=not pode,
                    title=("Baixa um PowerPoint com os principais números desta tela, com os filtros atuais" if pode
                           else "Seu perfil não permite gerar relatórios")),
        dcc.Loading(dcc.Download(id=f"{p}-rel-down"), type="circle", color="#1B365D"),
    ], className="rel-wrap no-print")


def kpi(rotulo: str, valor: str, sub: str = "", classe: str = "", tag: str | None = None, titulo: str | None = None,
        id_=None):
    filhos = [html.Div(rotulo, className="pk-l"), html.Div(valor, className="pk-v" + (" neutro" if "neutro" in classe else ""), title=valor),
              html.Div(sub, className="pk-s", title=titulo or sub)]
    if tag:
        filhos.insert(0, html.Span(tag, className="kpi-tag"))
    props = {"id": id_} if id_ else {}
    return html.Div(filhos, className=f"port-kpi {classe}".strip(), **props)


def cartao(titulo: str | None, *filhos, fonte: str | None = None, classe: str = "", **kw):
    cab = None
    if titulo:
        cab = html.Div([html.Span(titulo, className="cv-card-t"),
                        html.Span(f"  · {fonte}", className="cv-fonte") if fonte else None], className="cv-card-h")
    return html.Div([cab, *filhos], className=f"cv-card {classe}".strip(), **kw)


def selo(texto: str, classe: str) -> html.Span:
    return html.Span(texto, className=f"selo {classe}")


def filtro(rotulo: str, componente, classe: str = ""):
    return html.Div([html.Label(rotulo), componente], className=f"filtro {classe}".strip())


def vazio(texto: str):
    return html.Div(texto, className="vazio-box")


def nota(*filhos):
    return html.Div(filhos, className="nota-metodo")


def dropdown(id_, opcoes=None, multi=False, placeholder="Todos", valor=None, **kw):
    return dcc.Dropdown(id=id_, options=opcoes or [], multi=multi, placeholder=placeholder, value=valor,
                        optionHeight=34, **kw)


def periodo(id_, ini=None, fim=None):
    return dcc.DatePickerRange(id=id_, start_date=ini, end_date=fim, display_format="DD/MM/YYYY",
                               first_day_of_week=0, minimum_nights=0, start_date_placeholder_text="início",
                               end_date_placeholder_text="fim", clearable=True)


def botao(texto, id_, tipo="pri", **kw):
    return html.Button(texto, id=id_, className=f"btn btn-{tipo}", n_clicks=0, **kw)


def gaveta(id_, titulo_id, corpo_id):
    return dbc.Offcanvas(html.Div(id=corpo_id), id=id_, title=html.Span(id=titulo_id), placement="end",
                         is_open=False, scrollable=True, className="gaveta")
