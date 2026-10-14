"""
Janela de decomposição: ao clicar num card (KPI), mostra de que ele é formado —
grade (AG Grid) com total fixo no rodapé, e exportação em PDF e CSV (todas as
linhas; os dados ficam no servidor, o navegador só guarda um token).

Uso numa página:
    from app.components import detalhe
    layout: [..., *detalhe.modal("op-dm")]
    detalhe.registrar("op-dm")                         # fechar + exportar
    callback que abre: return detalhe.abrir(titulo, subtitulo, df, colunas)
        -> (estilo, titulo, subtitulo, corpo, dados_store)
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict

import dash_ag_grid as dag
import pandas as pd
from dash import Input, Output, State, callback, dcc, html, no_update

from app.exportacao import NUMERICOS, csv_bytes, nome_arquivo, pdf_bytes, totais

# AG Grid só desenha as linhas visíveis: dá para mostrar bem mais que a tabela HTML antiga (800)
LIMITE_TELA = 3000

ABERTO = {"display": "flex"}
FECHADO = {"display": "none"}

# ── Dados da janela ficam no SERVIDOR ─────────────────────────────────────────
# Antes, todas as linhas iam para o navegador (dcc.Store) e voltavam no exportar: 3–14 MB por clique.
# Agora o navegador guarda só um token; a exportação lê daqui (mesmo usuário, validade de 2 h).
_GUARDA: OrderedDict[str, tuple] = OrderedDict()
_LOCK = threading.Lock()
_MAX_ITENS, _VALIDADE_S = 60, 2 * 3600


def _usuario_id() -> int | None:
    from app.seguranca import sessao
    u = sessao.atual()
    return u.id if u else None


def _guardar(titulo, subtitulo, df, colunas) -> str:
    token = secrets.token_urlsafe(16)
    with _LOCK:
        _GUARDA[token] = (_usuario_id(), time.monotonic(), titulo, subtitulo, colunas, df)
        while len(_GUARDA) > _MAX_ITENS:
            _GUARDA.popitem(last=False)
    return token


def _recuperar(token: str | None):
    if not token:
        return None
    with _LOCK:
        item = _GUARDA.get(token)
    if not item:
        return None
    uid, quando, *resto = item
    if uid != _usuario_id() or time.monotonic() - quando > _VALIDADE_S:
        return None
    return resto                                    # titulo, subtitulo, colunas, df


def modal(p: str) -> list:
    """Janela no padrão drill-down do tema (classes drill-* do 01_construview_base.css)."""
    from app.seguranca import sessao
    exp = None if sessao.pode("exportar") else {"display": "none"}
    return [
        html.Div(html.Div([
            html.Div([
                html.Div([html.H2(id=f"{p}-titulo"), html.Div(id=f"{p}-sub", className="drill-meta"),
                          html.Div(id=f"{p}-aviso", className="drill-aviso")]),
                html.Div([html.Button("Exportar PDF", id=f"{p}-pdf", n_clicks=0, className="btn-claro", style=exp),
                          html.Button("Exportar CSV", id=f"{p}-csv", n_clicks=0, className="btn-claro", style=exp),
                          html.Button("Fechar", id=f"{p}-fechar", n_clicks=0, className="btn-claro")],
                         className="drill-acoes no-print"),
            ], className="drill-head"),
            html.Div(id=f"{p}-corpo", className="drill-corpo"),
        ], className="drill-box"), id=f"{p}-modal", className="drill-overlay", style=FECHADO),
        dcc.Store(id=f"{p}-dados"),
        dcc.Download(id=f"{p}-down"),
    ]


def _coluna(c: dict, primeira: bool) -> dict:
    fmt = c.get("formato", "texto")
    num = fmt in NUMERICOS
    peso = c.get("peso") or (1.4 if fmt in ("brl", "brl4") else 1 if num else 2)
    # largura mínima pelo conteúdo e pelo cabeçalho: a maior palavra do título não pode quebrar no meio
    maior_palavra = max((len(w) for w in str(c["rotulo"]).split()), default=4)
    minimo = max(int(55 * peso + 40), 8 * maior_palavra + 58)
    d = {"field": c["campo"], "headerName": c["rotulo"], "flex": peso, "minWidth": minimo,
         "headerTooltip": c["rotulo"]}
    if num:
        d.update(type="rightAligned", cellClass="num",
                 valueFormatter={"function": f"fmtDm(params.value, '{fmt}')"})
    elif fmt == "data":
        d["valueFormatter"] = {"function": "dataBR(params.value)"}
    else:
        d["tooltipField"] = c["campo"]
    if primeira:
        d["pinned"] = "left"
    return d


def _grade(df: pd.DataFrame, colunas: list[dict]):
    cols = [c for c in colunas if c["campo"] in df]
    d = df.head(LIMITE_TELA)[[c["campo"] for c in cols]].copy()
    for c in cols:
        if c.get("formato") == "data":
            d[c["campo"]] = pd.to_datetime(d[c["campo"]], errors="coerce").dt.strftime("%Y-%m-%d")
        elif c.get("formato") in NUMERICOS:
            d[c["campo"]] = pd.to_numeric(d[c["campo"]], errors="coerce").round(4)
    linhas = d.astype(object).where(d.notna(), None).to_dict("records")
    tot = totais(df, cols)                              # total sobre TODAS as linhas, não só as exibidas
    rodape = []
    if tot:
        r = {c["campo"]: tot.get(c["campo"]) for c in cols}
        primeira = cols[0]
        if primeira["campo"] not in tot:
            r[primeira["campo"]] = "Total"
        rodape = [r]
    opcoes = {"tooltipShowDelay": 300, "animateRows": False, "suppressColumnVirtualisation": False,
              "pinnedBottomRowData": rodape, "enableCellTextSelection": True, "ensureDomOrder": True}
    estilo = {"height": "min(62vh, 620px)", "width": "100%"}
    if len(linhas) <= 12:
        opcoes["domLayout"] = "autoHeight"
        estilo = {"width": "100%"}
    return dag.AgGrid(rowData=linhas, columnDefs=[_coluna(c, i == 0) for i, c in enumerate(cols)],
                      defaultColDef={"sortable": True, "resizable": True, "filter": True, "wrapHeaderText": True,
                                     "autoHeaderHeight": True},
                      dashGridOptions=opcoes, className="ag-theme-quartz dm-grade", style=estilo)


def abrir(titulo: str, subtitulo: str, df: pd.DataFrame, colunas: list[dict], nota=None):
    """Valores para as saídas (estilo, titulo, sub, corpo, store) do callback que abre a janela."""
    if df is None or df.empty:
        corpo = html.Div("Nada a decompor com os filtros atuais.", className="drill-vazio")
        return ABERTO, titulo, subtitulo, corpo, None
    filhos = [_grade(df, colunas)]
    if len(df) > LIMITE_TELA:
        filhos.insert(0, html.Div(f"Mostrando {LIMITE_TELA:,} de {len(df):,} linhas — a exportação traz todas "
                                  "(ordenar/filtrar na grade vale para as linhas exibidas).".replace(",", "."),
                                  className="drill-nota"))
    if nota:
        filhos.append(html.Div(nota, className="drill-nota"))
    token = _guardar(titulo, subtitulo, df[[c["campo"] for c in colunas if c["campo"] in df]].copy(), colunas)
    return ABERTO, titulo, subtitulo, html.Div(filhos), {"token": token}


def saidas(p: str) -> list:
    """Outputs padrão do callback que abre a janela."""
    return [Output(f"{p}-modal", "style", allow_duplicate=True), Output(f"{p}-titulo", "children"),
            Output(f"{p}-sub", "children"), Output(f"{p}-corpo", "children"), Output(f"{p}-dados", "data")]


def registrar(p: str) -> None:
    @callback(Output(f"{p}-modal", "style", allow_duplicate=True), Output(f"{p}-aviso", "children"),
              Input(f"{p}-fechar", "n_clicks"), prevent_initial_call=True)
    def _fechar(n):
        return (FECHADO, None) if n else (no_update, no_update)

    @callback(Output(f"{p}-down", "data"), Output(f"{p}-aviso", "children", allow_duplicate=True),
              Input(f"{p}-pdf", "n_clicks"), Input(f"{p}-csv", "n_clicks"),
              State(f"{p}-dados", "data"), prevent_initial_call=True)
    def _exportar(n_pdf, n_csv, dados):
        from dash import ctx
        from app.seguranca import sessao
        if not dados:
            return no_update, no_update
        sessao.exigir("exportar")
        guardado = _recuperar(dados.get("token"))
        if guardado is None:
            return no_update, "Esta janela expirou — feche e clique no card de novo para exportar."
        titulo, subtitulo, colunas, df = guardado
        if ctx.triggered_id == f"{p}-pdf" and n_pdf:
            return dcc.send_bytes(pdf_bytes(titulo, subtitulo, df, colunas), nome_arquivo(titulo, "pdf")), None
        if ctx.triggered_id == f"{p}-csv" and n_csv:
            return dcc.send_bytes(csv_bytes(df, colunas), nome_arquivo(titulo, "csv")), None
        return no_update, no_update


def kpi_clicavel(id_, componente):
    """Envolve um card para ser clicável (abre a decomposição)."""
    componente.className = (componente.className or "") + " drill"
    return html.Div(componente, id=id_, n_clicks=0, className="kpi-clicavel", role="button", tabIndex="0",
                    title="Clique para ver de que este número é formado")
