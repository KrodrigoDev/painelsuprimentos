"""Administração de acesso: usuários, perfis (telas, ações, escopo de dados) e auditoria."""
from __future__ import annotations

import json

import dash
import dash_ag_grid as dag
import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update
from sqlalchemy import select, union

from app.components.ui import cabecalho, cartao, dropdown, filtro, nota, vazio
from app.db import ler_sql
from app.seguranca import repo, sessao
from app.seguranca.catalogo import ACOES, TELAS

HERDAR = "herdar"


def _opcoes_escopo() -> dict:
    """Segmentos, obras e empresas existentes no DW (para escolher, não digitar)."""
    from app.models.dw import dim_centro_custo as cc, dim_empresa, fato_contrato
    out = {"segmentos": [], "obras": [], "empresas": []}
    try:
        seg = ler_sql(select(cc.c.vertical.label("v")).distinct())
        out["segmentos"] = sorted({str(v) for v in seg["v"].dropna()} | {"SEM SEGMENTO"})
        ob = ler_sql(select(cc.c.cod_obra, cc.c.centro_de_custo_1.label("nome")))
        ob["cod"] = pd.to_numeric(ob["cod_obra"], errors="coerce")
        ob = ob.dropna(subset=["cod"]).sort_values("cod")
        out["obras"] = [{"label": f"{int(r.cod)} - {r.nome or ''}".strip(" -"), "value": str(int(r.cod))}
                        for r in ob.itertuples()]
    except Exception:  # noqa: BLE001
        pass
    try:
        em = ler_sql(union(select(dim_empresa.c.cod_empresa, dim_empresa.c.empresa),
                           select(fato_contrato.c.cod_empresa, fato_contrato.c.empresa)))
        em = em.dropna(subset=["cod_empresa"]).drop_duplicates("cod_empresa").sort_values("cod_empresa")
        out["empresas"] = [{"label": f"{int(r.cod_empresa)} - {r.empresa}", "value": str(int(r.cod_empresa))}
                           for r in em.itertuples()]
    except Exception:  # noqa: BLE001
        pass
    return out


def _campos_escopo(p: str, op: dict, com_herdar: bool):
    opc_glob = ([{"label": "Herdar do perfil", "value": HERDAR}] if com_herdar else []) + [
        {"label": "Sim — mostra telas sem obra/empresa/segmento (ex.: Curva ABC)", "value": "sim"},
        {"label": "Não — só dados que dá para filtrar pelo escopo", "value": "nao"}]
    return html.Div([
        filtro("Segmentos (verticais)", dropdown(f"{p}-segmentos", [{"label": s, "value": s} for s in op["segmentos"]],
                                                 multi=True, placeholder="Todos"), "largo"),
        filtro("Obras / centros de custo", dropdown(f"{p}-obras", op["obras"], multi=True, placeholder="Todas"), "largo"),
        filtro("Empresas", dropdown(f"{p}-empresas", op["empresas"], multi=True, placeholder="Todas"), "largo"),
        filtro("Dados sem a dimensão restrita", dropdown(f"{p}-globais", opc_glob, valor=HERDAR if com_herdar else "sim",
                                                          clearable=False), "largo"),
    ], className="filtros")


def layout(**_):
    if not sessao.pode("administrar_usuarios"):
        return html.Div([cabecalho("Usuários e perfis", ""), vazio("Seu perfil não administra usuários.")])
    op = _opcoes_escopo()
    perfis = repo.listar_perfis()
    opc_perfis = [{"label": r.nome + ("" if r.ativo else " (inativo)"), "value": int(r.id)} for r in perfis.itertuples()]
    usuarios = html.Div([
        cartao("Usuários", dag.AgGrid(
            id="adm-u-grade", rowData=[], className="ag-theme-quartz", style={"height": 330},
            defaultColDef={"sortable": True, "resizable": True, "filter": True},
            dashGridOptions={"rowSelection": {"mode": "singleRow", "checkboxes": False, "enableClickSelection": True}},
            columnDefs=[{"field": "login", "headerName": "Login", "width": 150}, {"field": "nome", "headerName": "Nome",
                                                                                  "flex": 1, "minWidth": 180},
                        {"field": "perfil", "headerName": "Perfil", "width": 180},
                        {"field": "escopo_txt", "headerName": "Escopo próprio", "flex": 1, "minWidth": 200,
                         "tooltipField": "escopo_txt"},
                        {"field": "situacao", "headerName": "Situação", "width": 150},
                        {"field": "ultimo_login", "headerName": "Último acesso", "width": 150}]),
               html.Span("Clique num usuário para editar; ‘Novo usuário’ limpa o formulário.", className="cv-nota")),
        cartao("Cadastro do usuário", html.Div([
            dcc.Store(id="adm-u-id"),
            html.Div([
                filtro("Login", dcc.Input(id="adm-u-login", className="cv-input", placeholder="ex.: maria.silva"), "largo"),
                filtro("Nome", dcc.Input(id="adm-u-nome", className="cv-input"), "largo"),
                filtro("E-mail", dcc.Input(id="adm-u-email", className="cv-input", type="email"), "largo"),
                filtro("Perfil", dropdown("adm-u-perfil", opc_perfis, clearable=False, placeholder="Escolha")),
                filtro("Situação", dcc.Checklist(id="adm-u-ativo", options=[{"label": " ativo", "value": "ativo"}],
                                                 value=["ativo"]), "estreito"),
                filtro("Senha provisória", dcc.Input(id="adm-u-senha", className="cv-input", type="password",
                                                     placeholder="obrigatória no novo; opcional p/ redefinir",
                                                     autoComplete="new-password")),
            ], className="filtros"),
            html.Div("Escopo próprio do usuário (vazio = usa o do perfil; preenchido = substitui o do perfil naquela "
                     "dimensão)", className="cv-nota", style={"margin": "8px 0 2px"}),
            _campos_escopo("adm-u", op, True),
            html.Div([html.Button("Novo usuário", id="adm-u-novo", className="btn btn-sec btn-p", n_clicks=0),
                      html.Button("Salvar usuário", id="adm-u-salvar", className="btn btn-pri btn-p", n_clicks=0)],
                     className="acoes", style={"justifyContent": "flex-start", "marginTop": 10}),
            html.Div(id="adm-u-msg", style={"marginTop": 8}),
        ])),
    ], id="adm-sec-usuarios")
    perfis_ui = html.Div([
        cartao("Perfis", dag.AgGrid(
            id="adm-p-grade", rowData=[], className="ag-theme-quartz", style={"height": 260},
            defaultColDef={"sortable": True, "resizable": True, "filter": True},
            dashGridOptions={"rowSelection": {"mode": "singleRow", "checkboxes": False, "enableClickSelection": True}},
            columnDefs=[{"field": "nome", "headerName": "Perfil", "width": 200},
                        {"field": "telas_txt", "headerName": "Telas", "flex": 2, "tooltipField": "telas_txt"},
                        {"field": "acoes_txt", "headerName": "Ações", "flex": 1, "tooltipField": "acoes_txt"},
                        {"field": "escopo_txt", "headerName": "Escopo de dados", "flex": 1, "tooltipField": "escopo_txt"},
                        {"field": "situacao", "headerName": "Situação", "width": 120}])),
        cartao("Cadastro do perfil", html.Div([
            dcc.Store(id="adm-p-id"),
            html.Div([filtro("Nome do perfil", dcc.Input(id="adm-p-nome", className="cv-input")),
                      filtro("Descrição", dcc.Input(id="adm-p-desc", className="cv-input"), "largo"),
                      filtro("Opções", dcc.Checklist(id="adm-p-flags", options=[
                          {"label": " ativo", "value": "ativo"},
                          {"label": " administrador (todas as telas e ações)", "value": "admin"}], value=["ativo"]),
                             "largo")], className="filtros"),
            html.Div([
                html.Div([html.B("Telas que pode abrir"), dcc.Checklist(
                    id="adm-p-telas", options=[{"label": f" {nome}", "value": k} for k, (nome, _, _) in TELAS.items()],
                    value=[], className="adm-check")], style={"flex": 1}),
                html.Div([html.B("Ações que pode executar"), dcc.Checklist(
                    id="adm-p-acoes", options=[{"label": f" {v}", "value": k} for k, v in ACOES.items()], value=[],
                    className="adm-check")], style={"flex": 1}),
            ], style={"display": "flex", "gap": 24, "margin": "10px 0", "flexWrap": "wrap"}),
            html.Div("Escopo de dados padrão do perfil (vazio = sem restrição)", className="cv-nota"),
            _campos_escopo("adm-p", op, False),
            html.Div([html.Button("Novo perfil", id="adm-p-novo", className="btn btn-sec btn-p", n_clicks=0),
                      html.Button("Salvar perfil", id="adm-p-salvar", className="btn btn-pri btn-p", n_clicks=0)],
                     className="acoes", style={"justifyContent": "flex-start", "marginTop": 10}),
            html.Div(id="adm-p-msg", style={"marginTop": 8}),
        ])),
    ], id="adm-sec-perfis", style={"display": "none"})
    return html.Div([
        cabecalho("Usuários e perfis", "Quem acessa o painel, quais telas abre, o que pode fazer e quais dados vê "
                  "(segmento, obra, empresa)."),
        dcc.Tabs(id="adm-aba", value="usuarios", className="adm-abas", children=[
            dcc.Tab(label="Usuários", value="usuarios", className="adm-aba", selected_className="adm-aba-sel"),
            dcc.Tab(label="Perfis", value="perfis", className="adm-aba", selected_className="adm-aba-sel"),
            dcc.Tab(label="Auditoria de acesso", value="auditoria", className="adm-aba", selected_className="adm-aba-sel"),
        ]),
        usuarios, perfis_ui, html.Div(id="adm-sec-auditoria", style={"display": "none"}),
        dcc.Store(id="adm-refresh", data=0),
        nota(html.B("Como funciona: "), "o perfil define telas, ações e um escopo de dados padrão; o usuário pode ter um "
             "escopo próprio que substitui o do perfil em cada dimensão preenchida. Telas cujos dados não têm a "
             "dimensão restrita (ex.: Curva ABC não tem obra) só aparecem se ‘dados sem a dimensão’ for Sim. "
             "Alterar perfil, escopo, situação ou senha encerra as sessões abertas da pessoa. Senhas ficam só como "
             "hash; a senha provisória precisa ser trocada no primeiro acesso. 5 tentativas erradas bloqueiam por "
             "15 minutos. Novas ações (ex.: enviar dados ao Sienge) entram em app/seguranca/catalogo.py."),
    ])


dash.register_page(__name__, path="/admin", name="Usuários e perfis", title="Usuários e perfis · Suprimentos",
                   layout=layout)


def _txt_escopo(e) -> str:
    e = e or {}
    p = [f"{k}: {', '.join(map(str, v))}" for k, v in e.items() if isinstance(v, list) and v]
    if "dados_sem_dimensao" in e:
        p.append("dados sem dimensão: " + ("sim" if e["dados_sem_dimensao"] else "não"))
    return " · ".join(p) or "—"


def _msg(texto, ok=True):
    return html.Div(texto, className="adm-msg " + ("ok" if ok else "erro"))


def _escopo_form(seg, obras, emp, glob) -> dict:
    e = {"segmentos": seg or [], "obras": obras or [], "empresas": emp or []}
    if glob in ("sim", "nao"):
        e["dados_sem_dimensao"] = glob == "sim"
    return e


@callback(Output("adm-sec-usuarios", "style"), Output("adm-sec-perfis", "style"),
          Output("adm-sec-auditoria", "style"), Input("adm-aba", "value"))
def trocar_aba(aba):
    m, e = {"display": "block", "marginTop": 14}, {"display": "none"}
    return [m if aba == x else e for x in ("usuarios", "perfis", "auditoria")]


@callback(Output("adm-u-grade", "rowData"), Output("adm-p-grade", "rowData"), Output("adm-u-perfil", "options"),
          Input("adm-refresh", "data"))
def listar(_):
    sessao.exigir("administrar_usuarios")
    u = repo.listar_usuarios()
    if len(u):
        agora = pd.Timestamp.now(tz="UTC")
        u["escopo_txt"] = u["escopo"].map(_txt_escopo)
        u["situacao"] = ["bloqueado" if pd.notna(b) and b > agora else ("ativo" if a else "inativo") +
                         (" · trocar senha" if t else "") for a, b, t in zip(u["ativo"], u["bloqueado_ate"],
                                                                              u["deve_trocar_senha"])]
        u["ultimo_login"] = pd.to_datetime(u["ultimo_login"], utc=True).dt.tz_convert("America/Maceio").dt.strftime("%d/%m/%Y %H:%M")
    p = repo.listar_perfis()
    if len(p):
        p["telas_txt"] = p["telas"].map(lambda t: ", ".join(TELAS[x][0] for x in t or [] if x in TELAS))
        p["acoes_txt"] = p["acoes"].map(lambda a: ", ".join(a or []))
        p["escopo_txt"] = p["escopo"].map(_txt_escopo)
        p["situacao"] = p["ativo"].map({True: "ativo", False: "inativo"}) + p["administrador"].map(
            {True: " · admin", False: ""})
    opc = [{"label": r.nome + ("" if r.ativo else " (inativo)"), "value": int(r.id)} for r in p.itertuples()]
    cols_u = ["id", "login", "nome", "perfil", "escopo_txt", "situacao", "ultimo_login"]
    cols_p = ["id", "nome", "telas_txt", "acoes_txt", "escopo_txt", "situacao"]
    return (u[cols_u].to_dict("records") if len(u) else []), (p[cols_p].to_dict("records") if len(p) else []), opc


# ── usuário: carregar / limpar / salvar ──────────────────────────────────────
@callback(Output("adm-u-id", "data"), Output("adm-u-login", "value"), Output("adm-u-nome", "value"),
          Output("adm-u-email", "value"), Output("adm-u-perfil", "value"), Output("adm-u-ativo", "value"),
          Output("adm-u-senha", "value"), Output("adm-u-segmentos", "value"), Output("adm-u-obras", "value"),
          Output("adm-u-empresas", "value"), Output("adm-u-globais", "value"), Output("adm-u-login", "disabled"),
          Input("adm-u-grade", "selectedRows"), Input("adm-u-novo", "n_clicks"), prevent_initial_call=True)
def carregar_usuario(linhas, _novo):
    sessao.exigir("administrar_usuarios")
    if ctx.triggered_id == "adm-u-novo" or not linhas:
        return None, "", "", "", None, ["ativo"], "", [], [], [], HERDAR, False
    u = repo.listar_usuarios()
    r = u[u["id"] == linhas[0]["id"]]
    if r.empty:
        return (no_update,) * 12
    r = r.iloc[0]
    e = r["escopo"] or {}
    glob = HERDAR if "dados_sem_dimensao" not in e else ("sim" if e["dados_sem_dimensao"] else "nao")
    return (int(r["id"]), r["login"], r["nome"], r["email"] or "", int(r["perfil_id"]),
            ["ativo"] if r["ativo"] else [], "", e.get("segmentos") or [], e.get("obras") or [],
            e.get("empresas") or [], glob, True)


@callback(Output("adm-u-msg", "children"), Output("adm-refresh", "data", allow_duplicate=True),
          Input("adm-u-salvar", "n_clicks"),
          State("adm-u-id", "data"), State("adm-u-login", "value"), State("adm-u-nome", "value"),
          State("adm-u-email", "value"), State("adm-u-perfil", "value"), State("adm-u-ativo", "value"),
          State("adm-u-senha", "value"), State("adm-u-segmentos", "value"), State("adm-u-obras", "value"),
          State("adm-u-empresas", "value"), State("adm-u-globais", "value"), State("adm-refresh", "data"),
          prevent_initial_call=True)
def salvar_usuario(n, uid, login, nome, email, perfil_id, ativo, senha, seg, obras, emp, glob, ref):
    if not n:
        return no_update, no_update
    adm = sessao.exigir("administrar_usuarios")
    dados = dict(id=uid, login=login, nome=nome, email=email, perfil_id=perfil_id, ativo=bool(ativo),
                 escopo=_escopo_form(seg, obras, emp, glob))
    try:
        novo = repo.salvar_usuario(dados, adm.login, senha_provisoria=(senha or None))
    except repo.ErroAcesso as e:
        return _msg(str(e), False), no_update
    sessao.limpar_cache()
    acao = "criado" if not uid else "atualizado"
    extra = " Senha provisória definida: a pessoa troca no primeiro acesso." if senha else ""
    return _msg(f"Usuário {acao} (id {novo}).{extra}"), (ref or 0) + 1


# ── perfil: carregar / limpar / salvar ───────────────────────────────────────
@callback(Output("adm-p-id", "data"), Output("adm-p-nome", "value"), Output("adm-p-desc", "value"),
          Output("adm-p-flags", "value"), Output("adm-p-telas", "value"), Output("adm-p-acoes", "value"),
          Output("adm-p-segmentos", "value"), Output("adm-p-obras", "value"), Output("adm-p-empresas", "value"),
          Output("adm-p-globais", "value"),
          Input("adm-p-grade", "selectedRows"), Input("adm-p-novo", "n_clicks"), prevent_initial_call=True)
def carregar_perfil(linhas, _novo):
    sessao.exigir("administrar_usuarios")
    if ctx.triggered_id == "adm-p-novo" or not linhas:
        return None, "", "", ["ativo"], [], [], [], [], [], "sim"
    p = repo.listar_perfis()
    r = p[p["id"] == linhas[0]["id"]]
    if r.empty:
        return (no_update,) * 10
    r = r.iloc[0]
    e = r["escopo"] or {}
    flags = (["ativo"] if r["ativo"] else []) + (["admin"] if r["administrador"] else [])
    return (int(r["id"]), r["nome"], r["descricao"] or "", flags, list(r["telas"] or []), list(r["acoes"] or []),
            e.get("segmentos") or [], e.get("obras") or [], e.get("empresas") or [],
            "sim" if e.get("dados_sem_dimensao", True) else "nao")


@callback(Output("adm-p-msg", "children"), Output("adm-refresh", "data", allow_duplicate=True),
          Input("adm-p-salvar", "n_clicks"),
          State("adm-p-id", "data"), State("adm-p-nome", "value"), State("adm-p-desc", "value"),
          State("adm-p-flags", "value"), State("adm-p-telas", "value"), State("adm-p-acoes", "value"),
          State("adm-p-segmentos", "value"), State("adm-p-obras", "value"), State("adm-p-empresas", "value"),
          State("adm-p-globais", "value"), State("adm-refresh", "data"), prevent_initial_call=True)
def salvar_perfil(n, pid, nome, desc, flags, telas, acoes, seg, obras, emp, glob, ref):
    if not n:
        return no_update, no_update
    adm = sessao.exigir("administrar_usuarios")
    flags = flags or []
    dados = dict(id=pid, nome=nome, descricao=desc, telas=telas, acoes=acoes, ativo="ativo" in flags,
                 administrador="admin" in flags, escopo=_escopo_form(seg, obras, emp, glob))
    try:
        novo = repo.salvar_perfil(dados, adm.login)
    except repo.ErroAcesso as e:
        return _msg(str(e), False), no_update
    sessao.limpar_cache()
    return _msg(f"Perfil {'criado' if not pid else 'atualizado'} (id {novo}). Quem usa este perfil entra de novo "
                "com as permissões novas."), (ref or 0) + 1


@callback(Output("adm-sec-auditoria", "children"), Input("adm-aba", "value"), Input("adm-refresh", "data"))
def auditoria(aba, _):
    if aba != "auditoria":
        return no_update
    sessao.exigir("administrar_usuarios")
    a = repo.auditoria(500)
    if a.empty:
        return vazio("Nenhum evento registrado.")
    a["quando"] = pd.to_datetime(a["quando"], utc=True).dt.tz_convert("America/Maceio").dt.strftime("%d/%m/%Y %H:%M:%S")
    a["detalhe"] = a["detalhe"].map(lambda d: json.dumps(d, ensure_ascii=False, default=str) if d else "")
    return cartao("Últimos 500 eventos", dag.AgGrid(
        rowData=a[["quando", "login", "evento", "detalhe", "ip"]].to_dict("records"), className="ag-theme-quartz",
        style={"height": 520}, defaultColDef={"sortable": True, "resizable": True, "filter": True},
        columnDefs=[{"field": "quando", "headerName": "Quando", "width": 160}, {"field": "login", "width": 150},
                    {"field": "evento", "headerName": "Evento", "width": 140},
                    {"field": "detalhe", "headerName": "Detalhe", "flex": 1, "tooltipField": "detalhe"},
                    {"field": "ip", "headerName": "IP", "width": 130}]))
