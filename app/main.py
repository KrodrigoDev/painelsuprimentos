"""Aplicação Dash — Suprimentos · Inteligência de Compras (layout com menu lateral + login)."""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc  # noqa: F401  (componentes usados nas páginas)
from dash import ALL, Dash, Input, Output, ctx, dcc, html

from app import desempenho
from app.cache import CacheSWR
from app.config import SETTINGS
from app.seguranca import sessao, web
from app.seguranca.catalogo import DIMENSOES_DA_TELA, TELA_POR_ROTA, TELAS_SEM_DADOS
from app.seguranca.escopo import cobre_dataset

FONTES = ("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&"
          "family=Hanken+Grotesk:wght@400;500;600;700&family=Spline+Sans+Mono:wght@400;500;600&display=swap")

MENU = [
    ("Visão geral", [
        ("Visão geral", "/visao-geral", "Resumo de todas as abas"),
    ]),
    ("Inteligência de compras", [
        ("Oportunidades", "/", "Ranking de negociação"),
        ("Comparativo de fornecedores", "/comparativo", "Material x fornecedores"),
        ("Histórico de preços", "/historico", "Evolução e atípicos"),
        ("Correspondências", "/correspondencias", "Revisão de equivalências"),
        ("Busca por similaridade", "/busca", "Encontrar itens parecidos"),
    ]),
    ("Painéis", [
        ("Curva ABC - Insumo", "/curva-abc", "Valor e preço por insumo"),
        ("Adiantamento", "/adiantamento", "Saldo com fornecedores"),
        ("Avaliação fornecedor", "/avaliacao-fornecedor", "Notas e fornecedores críticos"),
        ("Estoque", "/estoque", "Valor e itens em estoque"),
        ("Contratos", "/contratos", "Saldo, medição e vencimentos"),
        ("SLA - Insumos", "/sla-insumos", "Prazos de compra e entrega"),
        ("Serviços", "/servicos", "Solicitações de serviço"),
    ]),
    ("Administração", [
        ("Configurações", "/configuracoes", "Prazos de SLA e parâmetros"),
        ("Usuários e perfis", "/admin", "Acessos, telas e dados"),
    ]),
]
EM_BREVE = ["Solicitação de compras", "Pedidos"]

ICONE = {  # ícones de linha simples (inline SVG, sem dependência externa)
    "/": "M3 17l5-5 4 4 8-8M14 8h6v6",
    "/comparativo": "M4 20V10M10 20V4M16 20v-7M22 20H2",
    "/historico": "M3 3v18h18M7 14l4-4 3 3 5-6",
    "/correspondencias": "M8 7h12M8 12h12M8 17h12M3 7h.01M3 12h.01M3 17h.01",
    "/busca": "M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm10 2-4.3-4.3",
    "/curva-abc": "M3 20h18M5 20V8M10 20v-6M15 20v-3M20 20v-1",
    "/adiantamento": "M12 3v18M17 7H9.5a3 3 0 0 0 0 6h5a3 3 0 0 1 0 6H6",
    "/estoque": "M3 7l9-4 9 4-9 4-9-4zM3 7v10l9 4 9-4V7M12 11v10",
    "/avaliacao-fornecedor": "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z",
    "/contratos": "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
    "/admin": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
    "/visao-geral": "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z",
    "/sla-insumos": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 3",
    "/servicos": "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z",
    "/configuracoes": "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
}


def _icone(rota: str):
    return html.Img(src="data:image/svg+xml;utf8," + (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%231B365D' "
        f"stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='{ICONE.get(rota, 'M4 12h16')}'/></svg>"),
        className="nav-ico")


def _sidebar(u):
    secoes = []
    for titulo, itens in MENU:
        visiveis = [(n, r, d) for n, r, d in itens if TELA_POR_ROTA.get(r) in u.telas
                    and (TELA_POR_ROTA.get(r) in TELAS_SEM_DADOS
                         or cobre_dataset(u.escopo, **DIMENSOES_DA_TELA.get(TELA_POR_ROTA.get(r), {})))]
        if not visiveis:
            continue
        secoes.append(html.Div([html.Div(titulo, className="nav-titulo")] + [
            dcc.Link([_icone(rota), html.Span([nome, html.Small(desc)], className="nav-txt"),
                      html.Span(id={"type": "badge", "r": rota})],
                     href=rota, id={"type": "nav", "r": rota}, className="nav-item")
            for nome, rota, desc in visiveis], className="nav-secao"))
    secoes.append(html.Div([html.Div("Painéis (em breve)", className="nav-titulo")] + [
        html.Div([html.Span(nome, className="nav-txt")], className="nav-item off", title="Em construção")
        for nome in EM_BREVE], className="nav-secao"))
    return html.Aside([
        html.Div([html.Img(src="/assets/logo.svg", className="brand-logo"),
                  html.Div([html.Div("Suprimentos", className="brand-nome"),
                            html.Div("Inteligência de compras · Telesil", className="brand-sub")])], className="brand"),
        html.Nav(secoes, className="nav"),
        html.Div([html.Div(u.nome, className="nav-conta-nome"),
                  html.Div(f"{u.perfil} · {u.escopo.descricao()}", className="nav-conta-perfil",
                           title="Perfil e dados que você pode ver"),
                  html.Div([html.A("Trocar senha", href="/trocar-senha"), html.A("Sair", href="/logout")],
                           className="nav-conta-links"),
                  html.Div(id="sidebar-meta", className="nav-conta-meta")], className="nav-conta"),
    ], className="sidebar", id="sidebar")


def _layout():
    u = sessao.atual()
    if u is None:   # o guarda já redireciona; isto só aparece se a sessão cair no meio do carregamento
        return html.Div(dcc.Location(id="url", href="/login", refresh=True))
    return html.Div([
        dcc.Location(id="url"),
        _sidebar(u),
        html.Main([dash.page_container], className="conteudo pagina"),
        html.Footer(id="rodape", className="rodape"),
    ], className="app")


def _sem_acesso(nome: str):
    from app.components.ui import cabecalho, vazio
    return html.Div([cabecalho("Acesso não liberado", nome),
                     vazio(f"Seu perfil não inclui a tela “{nome}”. Peça a liberação ao administrador do painel.")])


def _sem_dados(nome: str):
    from app.components.ui import cabecalho, vazio
    return html.Div([cabecalho(nome, "Sem dados no seu escopo de acesso"),
                     vazio(f"Os dados de “{nome}” não têm obra/segmento/empresa para filtrar, e o seu acesso é "
                           f"restrito ({sessao.escopo().descricao()}). Peça ao administrador para liberar "
                           "“dados sem a dimensão” no seu perfil, se for o caso.")])


def _proteger_paginas() -> None:
    """Cada página checa a tela no servidor antes de montar o layout."""
    for pagina in dash.page_registry.values():
        tela = TELA_POR_ROTA.get(pagina["path"])
        original = pagina["layout"]
        if tela is None or getattr(original, "_protegido", False):
            continue

        def protegido(*args, _orig=original, _tela=tela, _nome=pagina["name"], **kwargs):
            if not sessao.pode_tela(_tela):
                return _sem_acesso(_nome)
            if _tela not in TELAS_SEM_DADOS and not cobre_dataset(sessao.escopo(), **DIMENSOES_DA_TELA.get(_tela, {})):
                return _sem_dados(_nome)
            return _orig(*args, **kwargs) if callable(_orig) else _orig

        protegido._protegido = True
        pagina["layout"] = protegido


# menu lateral: contagem de pendências e último ETL mudam pouco — 1 min de cache em vez de 2 consultas por clique
_META = CacheSWR("menu", 1)


def criar_app() -> Dash:
    app = Dash(__name__, use_pages=True, pages_folder="", assets_folder="assets", external_stylesheets=[FONTES],
               suppress_callback_exceptions=True, title="Suprimentos · Inteligência de Compras")
    web.instalar(app.server)
    desempenho.instalar_compressao(app.server)
    from app.pages import (adiantamento, admin, avaliacao_fornecedor, comparativo, configuracoes,  # noqa: F401
                           contratos, correspondencias, curva_abc, estoque, historico, oportunidades,
                           possivel_saving, servicos, sla_insumos, visao_geral)
    _proteger_paginas()
    app.layout = _layout

    @app.callback(Output({"type": "nav", "r": ALL}, "className"), Input("url", "pathname"))
    def _ativo(path):
        return ["nav-item ativo" if (path or "/") == o["id"]["r"] else "nav-item" for o in ctx.outputs_list]

    @app.callback(Output("sidebar-meta", "children"), Output("rodape", "children"),
                  Output({"type": "badge", "r": ALL}, "children"), Input("url", "pathname"))
    def _meta(_):
        from app.matching.config import CONFIG
        from app.repositories import catalogo_repo
        from app.services import inteligencia
        pend = 0
        if sessao.pode_tela("correspondencias"):
            try:
                st = _META.obter("pendentes", catalogo_repo.contagem_status, 1).set_index("status")["n"]
                pend = int(st.get("pendente", 0) + st.get("revisar_mudanca", 0))
            except Exception:  # noqa: BLE001
                pend = 0
        etl = _META.obter("etl", lambda: inteligencia.ultimo_processamento() or {}, 1) or None
        quando = etl["processado_em"].strftime("%d/%m %H:%M") if etl else "nunca"
        meta = [html.Div(f"fonte: {SETTINGS.dw_schema}"), html.Div(f"análise de compras (ETL): {quando}")]
        if etl and etl["versao_regras"] != CONFIG.versao:
            meta.append(html.Div(f"⚠ regras do ETL {etl['versao_regras']} ≠ painel {CONFIG.versao}",
                                 className="nav-alerta", title="Atualize app/matching e o ETL juntos"))
        badges = [html.Span(f"{pend:,}".replace(",", "."), className="nav-badge")
                  if pend and o["id"]["r"] == "/correspondencias" else None for o in ctx.outputs_list[2]]
        sint = " · DADOS SINTÉTICOS (mock)" if SETTINGS.dw_schema != "suprimentos" else ""
        return meta, f"Suprimentos · Inteligência de Compras — fonte {SETTINGS.dw_schema}{sint}", badges

    return app


app = criar_app()
server = app.server

if __name__ == "__main__":
    desempenho.iniciar_aquecimento()
    app.run(debug=SETTINGS.debug, port=SETTINGS.port)
