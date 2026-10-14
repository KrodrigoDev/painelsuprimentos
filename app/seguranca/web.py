"""Rotas de login/logout/troca de senha e o guarda de TODAS as requisições do servidor.

Guarda (before_request):
  - sem sessão válida: páginas -> redireciona para /login; chamadas internas do
    Dash (/_dash-*) -> 401 (o navegador recarrega e cai no login);
  - senha provisória: só /trocar-senha até trocar;
  - callback de uma tela sem acesso (ids "<prefixo>-..." da tela) -> 403.
Sessão: cookie assinado (PAINEL_SECRET_KEY do .env), HttpOnly, SameSite=Lax,
expira em PAINEL_SESSAO_HORAS (padrão 10 h).
"""
from __future__ import annotations

import html
import json
import logging
import os
import secrets
from datetime import timedelta
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, redirect, request, session

from app.config import SETTINGS
from app.seguranca import repo, sessao
from app.seguranca.catalogo import TELA_POR_PREFIXO

logger = logging.getLogger(__name__)

LIVRES = ("/login", "/assets/", "/_favicon.ico", "/favicon.ico")
GLOBAIS = {"url", "sidebar-meta", "rodape", "_pages_location", "_pages_content", "_pages_store", "_pages_dummy",
           "conta-sair"}


def _ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()


def _destino_seguro(nxt: str | None) -> str:
    if not nxt:
        return "/"
    u = urlparse(nxt)
    return nxt if not u.netloc and not u.scheme and nxt.startswith("/") and not nxt.startswith("//") else "/"


def _csrf() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def _csrf_ok() -> bool:
    enviado = request.form.get("csrf", "")
    return bool(enviado) and secrets.compare_digest(enviado, session.get("csrf", ""))


# ─────────────────────────────────────────────────────────────────────────────
# Página (HTML simples no estilo do painel: navy + Fraunces/Hanken Grotesk)
# ─────────────────────────────────────────────────────────────────────────────
_ESTILO = """
:root{--navy:#1B365D;--fundo:#F4F2EE;--borda:#DAD6CE;--texto:#1d2433;--sub:#5d6677;--erro:#A4262C;--ok:#1E6B45}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--fundo);
font-family:'Hanken Grotesk',system-ui,sans-serif;color:var(--texto);padding:16px}
.caixa{width:100%;max-width:400px;background:#fff;border:1px solid var(--borda);border-radius:14px;padding:32px 30px;
box-shadow:0 10px 30px rgba(27,54,93,.08)}
.marca{display:flex;gap:12px;align-items:center;margin-bottom:22px}.marca img{width:40px;height:40px}
.marca b{font-family:Fraunces,Georgia,serif;font-size:22px;color:var(--navy);display:block;font-weight:600}
.marca small{color:var(--sub);font-size:12.5px}
h1{font-family:Fraunces,Georgia,serif;font-weight:500;font-size:19px;margin:0 0 4px;color:var(--navy)}
p.sub{margin:0 0 18px;color:var(--sub);font-size:13.5px}
label{display:block;font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--sub);
margin:14px 0 6px}input{width:100%;padding:11px 12px;border:1px solid var(--borda);border-radius:8px;font:inherit;
font-size:15px}input:focus{outline:2px solid rgba(27,54,93,.25);border-color:var(--navy)}
button{margin-top:22px;width:100%;padding:12px;border:0;border-radius:8px;background:var(--navy);color:#fff;
font:inherit;font-weight:600;font-size:15px;cursor:pointer}button:hover{background:#244a7d}
.msg{margin-top:14px;padding:10px 12px;border-radius:8px;font-size:13.5px}
.msg.erro{background:#fbeceb;color:var(--erro)}.msg.ok{background:#e9f4ee;color:var(--ok)}
.rodape{margin-top:18px;font-size:12px;color:var(--sub);text-align:center}
"""
_FONTES = ("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&"
           "family=Hanken+Grotesk:wght@400;500;600;700&display=swap")


def _pagina(titulo: str, sub: str, campos: str, botao: str, msg: str = "", tipo: str = "erro", acao: str = "") -> str:
    aviso = f'<div class="msg {tipo}" role="alert">{html.escape(msg)}</div>' if msg else ""
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(titulo)} · Suprimentos</title>
<link rel="stylesheet" href="{_FONTES}"><style>{_ESTILO}</style></head><body>
<form class="caixa" method="post" action="{html.escape(acao)}" autocomplete="on">
<div class="marca"><img src="/assets/logo.svg" alt=""><div><b>Suprimentos</b><small>Inteligência de compras · Telesil</small></div></div>
<h1>{html.escape(titulo)}</h1><p class="sub">{html.escape(sub)}</p>
<input type="hidden" name="csrf" value="{_csrf()}">{campos}{aviso}
<button type="submit">{html.escape(botao)}</button>
<div class="rodape">Acesso restrito · fonte {html.escape(SETTINGS.dw_schema)}</div></form></body></html>"""


def _form_login(msg: str = "", tipo: str = "erro", login: str = "") -> str:
    nxt = html.escape(_destino_seguro(request.args.get("next")))
    campos = (f'<label for="login">Login</label><input id="login" name="login" value="{html.escape(login)}" '
              f'autocomplete="username" required autofocus>'
              f'<label for="senha">Senha</label><input id="senha" name="senha" type="password" '
              f'autocomplete="current-password" required>')
    return _pagina("Entrar", "Use o login e a senha fornecidos pelo administrador do painel.", campos, "Entrar",
                   msg, tipo, acao=f"/login?next={nxt}")


def _form_troca(msg: str = "", tipo: str = "erro", obrigatoria: bool = False) -> str:
    campos = ("" if obrigatoria else '<label for="atual">Senha atual</label><input id="atual" name="atual" '
              'type="password" autocomplete="current-password" required>')
    campos += ('<label for="nova">Nova senha</label><input id="nova" name="nova" type="password" '
               'autocomplete="new-password" required minlength="8">'
               '<label for="conf">Repita a nova senha</label><input id="conf" name="conf" type="password" '
               'autocomplete="new-password" required minlength="8">')
    sub = ("Sua senha é provisória: defina uma senha pessoal para continuar (mínimo 8 caracteres, com letras e "
           "números)." if obrigatoria else "Mínimo 8 caracteres, com letras e números.")
    return _pagina("Trocar senha", sub, campos, "Salvar nova senha", msg, tipo, acao="/trocar-senha")


# ─────────────────────────────────────────────────────────────────────────────
# Guarda
# ─────────────────────────────────────────────────────────────────────────────
def _id_texto(i) -> str:
    if isinstance(i, dict):
        return str(i.get("type", ""))
    if isinstance(i, str) and i.startswith("{"):
        try:
            return str(json.loads(i).get("type", ""))
        except ValueError:
            return i
    return str(i or "")


def _ids_do_callback() -> set[str]:
    """Ids de saída do callback pedido. `output` (texto) é o que o Dash usa para achar a função — é a fonte
    principal; `outputs` (estruturado, com listas aninhadas nos padrões ALL) entra junto."""
    corpo = request.get_json(silent=True) or {}
    ids = set()
    texto = str(corpo.get("output") or "")
    if texto:
        partes = texto[2:-2].split("...") if texto.startswith("..") else [texto]
        ids |= {_id_texto(p.rsplit(".", 1)[0]) for p in partes if p}

    def visitar(x):
        if isinstance(x, list):
            for y in x:
                visitar(y)
        elif isinstance(x, dict):
            ids.add(_id_texto(x.get("id")))

    visitar(corpo.get("outputs"))
    ids.discard("")
    return ids


def tela_do_id(id_: str) -> str | None:
    if id_ in GLOBAIS or id_.startswith(("nav-", "badge-")):
        return None
    return TELA_POR_PREFIXO.get(id_.split("-")[0])


def _guarda():
    caminho = request.path
    if caminho.startswith(LIVRES):
        return None
    u = sessao.atual()
    interno = caminho.startswith("/_dash") or caminho.startswith("/_reload")
    if u is None:
        if interno:
            return jsonify(erro="sessão expirada"), 401
        session.clear()
        return redirect(f"/login?next={request.full_path.rstrip('?')}")
    if u.deve_trocar_senha and caminho not in ("/trocar-senha", "/logout"):
        return (jsonify(erro="troca de senha obrigatória"), 401) if interno else redirect("/trocar-senha")
    if caminho == "/_dash-update-component":
        for id_ in _ids_do_callback():
            tela = tela_do_id(id_)
            if tela and tela not in u.telas:
                repo.auditar("negado", u.login, {"tela": tela, "id": id_}, _ip())
                return jsonify(erro="acesso negado a esta tela"), 403
    return None


def instalar(server: Flask) -> None:
    chave = os.getenv("PAINEL_SECRET_KEY")
    if not chave:
        if not SETTINGS.debug:
            raise RuntimeError("PAINEL_SECRET_KEY não definido no .env (gere com: python -c \"import secrets; "
                               "print(secrets.token_urlsafe(48))\").")
        logger.warning("PAINEL_SECRET_KEY ausente — usando chave temporária (sessões caem ao reiniciar). "
                       "Só aceitável com DASH_DEBUG=true.")
        chave = secrets.token_urlsafe(48)
    server.config.update(
        SECRET_KEY=chave, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("PAINEL_COOKIE_SEGURO", "false").lower() in ("1", "true", "sim"),
        SESSION_COOKIE_NAME="painel_suprimentos",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=int(os.getenv("PAINEL_SESSAO_HORAS", "10"))))
    server.before_request(_guarda)

    @server.after_request
    def _cabecalhos(resp):
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    @server.route("/login", methods=["GET", "POST"])
    def login():
        if not repo.tabelas_existem() or not repo.existe_usuario():
            return _pagina("Configuração pendente", "Nenhum usuário cadastrado. No servidor do painel rode "
                           "`alembic upgrade head` e depois `python -m scripts.criar_admin`.", "", "Recarregar",
                           acao="/login"), 503
        if request.method == "GET":
            return _form_login()
        if not _csrf_ok():
            return _form_login("Sessão do formulário expirou. Tente de novo."), 400
        login_ = request.form.get("login", "")
        try:
            u = repo.autenticar(login_, request.form.get("senha", ""), _ip())
        except repo.ErroAcesso as e:
            return _form_login(str(e), login=login_), 401
        session.clear()
        session.permanent = True
        session.update(uid=u["id"], v=u["versao_sessao"])
        _csrf()
        sessao.carregar(u["id"], forcar=True)
        return redirect("/trocar-senha" if u["deve_trocar_senha"] else _destino_seguro(request.args.get("next")))

    @server.route("/logout")
    def logout():
        u = sessao.atual()
        if u:
            repo.auditar("logout", u.login, None, _ip())
        session.clear()
        return redirect("/login")

    @server.route("/trocar-senha", methods=["GET", "POST"])
    def trocar_senha():
        u = sessao.atual()
        if u is None:
            return redirect("/login")
        obrig = u.deve_trocar_senha
        if request.method == "GET":
            return _form_troca(obrigatoria=obrig)
        if not _csrf_ok():
            abort(400)
        nova, conf = request.form.get("nova", ""), request.form.get("conf", "")
        if nova != conf:
            return _form_troca("As duas senhas não conferem.", obrigatoria=obrig), 400
        try:
            repo.trocar_senha(u.id, None if obrig else request.form.get("atual", ""), nova, u.login)
        except repo.ErroAcesso as e:
            return _form_troca(str(e), obrigatoria=obrig), 400
        novo = sessao.carregar(u.id, forcar=True)
        session["v"] = novo.versao if novo else 0
        return redirect("/")

