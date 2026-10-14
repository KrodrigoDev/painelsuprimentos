"""Tabelas de acesso (schema painel): usuários, perfis e auditoria."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import func, insert, select, update
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import get_engine, ler_sql
from app.models.painel import auditoria_acesso, perfil, usuario

MAX_TENTATIVAS = 5
BLOQUEIO_MIN = 15
_RE_LOGIN = re.compile(r"^[a-z0-9._-]{3,40}$")
# hash "impossível" para comparar quando o login não existe (tempo de resposta igual)
_HASH_FALSO = generate_password_hash("x" * 24)


class ErroAcesso(ValueError):
    pass


def agora():
    return datetime.now(timezone.utc)


def validar_senha(senha: str) -> None:
    if len(senha or "") < 8 or not re.search(r"[A-Za-z]", senha) or not re.search(r"\d", senha):
        raise ErroAcesso("A senha precisa ter pelo menos 8 caracteres, com letras e números.")


def normalizar_login(login: str) -> str:
    login = (login or "").strip().lower()
    if not _RE_LOGIN.match(login):
        raise ErroAcesso("Login inválido: use 3 a 40 caracteres (letras minúsculas, números, ponto, hífen, _).")
    return login


# ── auditoria ────────────────────────────────────────────────────────────────
def auditar(evento: str, login: str | None = None, detalhe: dict | None = None, ip: str | None = None) -> None:
    try:
        with get_engine().begin() as c:
            c.execute(insert(auditoria_acesso).values(evento=evento, login=login, detalhe=detalhe, ip=ip))
    except Exception:  # noqa: BLE001 — auditoria nunca derruba a tela
        pass


def auditoria(limite: int = 300) -> pd.DataFrame:
    return ler_sql(select(auditoria_acesso).order_by(auditoria_acesso.c.id.desc()).limit(limite))


# ── leitura ──────────────────────────────────────────────────────────────────
def tabelas_existem() -> bool:
    try:
        ler_sql(select(func.count()).select_from(usuario))
        return True
    except Exception:  # noqa: BLE001
        return False


def existe_usuario() -> bool:
    return int(ler_sql(select(func.count().label("n")).select_from(usuario))["n"].iat[0]) > 0


def carregar_usuario(uid: int) -> dict | None:
    stmt = (select(usuario, perfil.c.nome.label("perfil_nome"), perfil.c.telas, perfil.c.acoes,
                   perfil.c.escopo.label("perfil_escopo"), perfil.c.administrador, perfil.c.ativo.label("perfil_ativo"))
            .join(perfil, perfil.c.id == usuario.c.perfil_id).where(usuario.c.id == uid))
    with get_engine().connect() as c:
        r = c.execute(stmt).mappings().first()
    return dict(r) if r else None


def listar_usuarios() -> pd.DataFrame:
    return ler_sql(select(usuario.c.id, usuario.c.login, usuario.c.nome, usuario.c.email, usuario.c.perfil_id,
                          perfil.c.nome.label("perfil"), usuario.c.escopo, usuario.c.ativo,
                          usuario.c.deve_trocar_senha, usuario.c.bloqueado_ate, usuario.c.ultimo_login)
                   .join(perfil, perfil.c.id == usuario.c.perfil_id).order_by(usuario.c.login))


def listar_perfis() -> pd.DataFrame:
    return ler_sql(select(perfil).order_by(perfil.c.nome))


# ── login ────────────────────────────────────────────────────────────────────
def autenticar(login: str, senha: str, ip: str | None = None) -> dict:
    """Devolve o usuário (dict) ou lança ErroAcesso com mensagem genérica.
    A contagem de falhas é gravada ANTES de lançar o erro (fora da transação que seria desfeita)."""
    login = (login or "").strip().lower()
    erro, evento, detalhe = None, None, None
    with get_engine().begin() as c:
        u = c.execute(select(usuario).where(usuario.c.login == login).with_for_update()).mappings().first()
        if u is None:
            check_password_hash(_HASH_FALSO, senha or "")
            erro, evento, detalhe = "Login ou senha incorretos.", "login_falha", {"motivo": "login inexistente"}
        elif u["bloqueado_ate"] and u["bloqueado_ate"] > agora():
            erro = (f"Acesso bloqueado por excesso de tentativas. Tente após "
                    f"{u['bloqueado_ate'].astimezone().strftime('%H:%M')}.")
            evento, detalhe = "login_falha", {"motivo": "bloqueado"}
        elif not check_password_hash(u["senha_hash"], senha or ""):
            falhas = u["tentativas_falhas"] + 1
            valores = {"tentativas_falhas": falhas}
            if falhas >= MAX_TENTATIVAS:
                valores = {"tentativas_falhas": 0, "bloqueado_ate": agora() + timedelta(minutes=BLOQUEIO_MIN)}
            c.execute(update(usuario).where(usuario.c.id == u["id"]).values(**valores))
            erro = "Login ou senha incorretos."
            evento, detalhe = ("bloqueio" if falhas >= MAX_TENTATIVAS else "login_falha"), {"tentativa": falhas}
        elif not u["ativo"]:
            erro, evento, detalhe = ("Usuário desativado. Fale com o administrador do painel.", "login_falha",
                                     {"motivo": "inativo"})
        else:
            c.execute(update(usuario).where(usuario.c.id == u["id"]).values(
                tentativas_falhas=0, bloqueado_ate=None, ultimo_login=agora()))
    if erro:
        auditar(evento, login, detalhe, ip)
        raise ErroAcesso(erro)
    auditar("login_ok", login, None, ip)
    return dict(u)


def trocar_senha(uid: int, atual: str | None, nova: str, por: str) -> None:
    validar_senha(nova)
    with get_engine().begin() as c:
        u = c.execute(select(usuario.c.senha_hash, usuario.c.login).where(usuario.c.id == uid)).mappings().first()
        if u is None:
            raise ErroAcesso("Usuário não encontrado.")
        if atual is not None and not check_password_hash(u["senha_hash"], atual):
            raise ErroAcesso("Senha atual incorreta.")
        if check_password_hash(u["senha_hash"], nova):
            raise ErroAcesso("A nova senha precisa ser diferente da atual.")
        c.execute(update(usuario).where(usuario.c.id == uid).values(
            senha_hash=generate_password_hash(nova), deve_trocar_senha=False, atualizado_em=agora(),
            versao_sessao=usuario.c.versao_sessao + 1))
    auditar("senha_alterada", u["login"], {"por": por})


# ── administração ────────────────────────────────────────────────────────────
def _escopo_limpo(esc: dict | None) -> dict:
    esc = esc or {}
    out = {k: sorted({str(v).strip() for v in esc.get(k) or [] if str(v).strip()}) or None
           for k in ("segmentos", "obras", "empresas")}
    out = {k: v for k, v in out.items() if v}
    if esc.get("dados_sem_dimensao") is not None:
        out["dados_sem_dimensao"] = bool(esc["dados_sem_dimensao"])
    return out


def salvar_perfil(dados: dict, por: str) -> int:
    from app.seguranca.catalogo import ACOES, TELAS
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ErroAcesso("Informe o nome do perfil.")
    valores = dict(nome=nome, descricao=(dados.get("descricao") or "").strip() or None,
                   telas=[t for t in dados.get("telas") or [] if t in TELAS],
                   acoes=[a for a in dados.get("acoes") or [] if a in ACOES],
                   escopo=_escopo_limpo(dados.get("escopo")), administrador=bool(dados.get("administrador")),
                   ativo=bool(dados.get("ativo", True)), atualizado_em=agora())
    if valores["administrador"]:
        valores["telas"] = sorted(set(valores["telas"]) | {"admin"})
        valores["acoes"] = sorted(set(valores["acoes"]) | {"administrar_usuarios"})
    with get_engine().begin() as c:
        if dados.get("id"):
            pid = int(dados["id"])
            if not valores["administrador"] or not valores["ativo"]:
                _garantir_outro_admin(c, perfil_id=pid)
            c.execute(update(perfil).where(perfil.c.id == pid).values(**valores))
            # derruba as sessões de quem usa o perfil (permissões mudaram)
            c.execute(update(usuario).where(usuario.c.perfil_id == pid).values(versao_sessao=usuario.c.versao_sessao + 1))
        else:
            pid = c.execute(insert(perfil).values(criado_por=por, **valores).returning(perfil.c.id)).scalar()
    auditar("admin_perfil", por, {"perfil": nome, "id": pid, "telas": valores["telas"], "acoes": valores["acoes"],
                                  "escopo": valores["escopo"]})
    return pid


def salvar_usuario(dados: dict, por: str, senha_provisoria: str | None = None) -> int:
    login = normalizar_login(dados.get("login"))
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ErroAcesso("Informe o nome.")
    if not dados.get("perfil_id"):
        raise ErroAcesso("Escolha o perfil.")
    valores = dict(login=login, nome=nome, email=(dados.get("email") or "").strip() or None,
                   perfil_id=int(dados["perfil_id"]), escopo=_escopo_limpo(dados.get("escopo")),
                   ativo=bool(dados.get("ativo", True)), atualizado_em=agora())
    with get_engine().begin() as c:
        if dados.get("id"):
            uid = int(dados["id"])
            if not valores["ativo"]:
                _garantir_outro_admin(c, usuario_id=uid)
            atual = c.execute(select(usuario.c.perfil_id, usuario.c.ativo, usuario.c.escopo)
                              .where(usuario.c.id == uid)).mappings().first()
            if atual and atual["perfil_id"] != valores["perfil_id"]:
                _garantir_outro_admin(c, usuario_id=uid, novo_perfil=valores["perfil_id"])
            if senha_provisoria:
                validar_senha(senha_provisoria)
                valores.update(senha_hash=generate_password_hash(senha_provisoria), deve_trocar_senha=True,
                               tentativas_falhas=0, bloqueado_ate=None)
            c.execute(update(usuario).where(usuario.c.id == uid).values(versao_sessao=usuario.c.versao_sessao + 1,
                                                                         **valores))
        else:
            if not senha_provisoria:
                raise ErroAcesso("Defina uma senha provisória para o novo usuário.")
            validar_senha(senha_provisoria)
            if c.execute(select(usuario.c.id).where(usuario.c.login == login)).first():
                raise ErroAcesso(f"Já existe o login '{login}'.")
            uid = c.execute(insert(usuario).values(senha_hash=generate_password_hash(senha_provisoria),
                                                   deve_trocar_senha=True, criado_por=por, **valores)
                            .returning(usuario.c.id)).scalar()
    auditar("admin_usuario", por, {"login": login, "id": uid, "perfil_id": valores["perfil_id"],
                                   "ativo": valores["ativo"], "escopo": valores["escopo"],
                                   "senha_redefinida": bool(senha_provisoria)})
    return uid


def _garantir_outro_admin(c, usuario_id: int | None = None, perfil_id: int | None = None,
                          novo_perfil: int | None = None) -> None:
    """Impede ficar sem nenhum administrador ativo."""
    q = (select(usuario.c.id).join(perfil, perfil.c.id == usuario.c.perfil_id)
         .where(usuario.c.ativo.is_(True), perfil.c.administrador.is_(True), perfil.c.ativo.is_(True)))
    if usuario_id is not None:
        q = q.where(usuario.c.id != usuario_id)
        if novo_perfil is not None:
            eh_admin = c.execute(select(perfil.c.administrador).where(perfil.c.id == novo_perfil)).scalar()
            if eh_admin:
                return
    if perfil_id is not None:
        q = q.where(usuario.c.perfil_id != perfil_id)
    if not c.execute(q.limit(1)).first():
        raise ErroAcesso("Operação deixaria o painel sem nenhum administrador ativo.")


def criar_admin(login: str, nome: str, senha: str) -> int:
    """Usado por scripts/criar_admin.py (senha digitada no terminal, nunca em código)."""
    validar_senha(senha)
    login = normalizar_login(login)
    with get_engine().begin() as c:
        pid = c.execute(select(perfil.c.id).where(perfil.c.administrador.is_(True), perfil.c.ativo.is_(True))
                        .order_by(perfil.c.id).limit(1)).scalar()
        if pid is None:
            raise ErroAcesso("Nenhum perfil administrador — rode `alembic upgrade head`.")
        existente = c.execute(select(usuario.c.id).where(usuario.c.login == login)).scalar()
        if existente:
            c.execute(update(usuario).where(usuario.c.id == existente).values(
                senha_hash=generate_password_hash(senha), perfil_id=pid, ativo=True, deve_trocar_senha=False,
                tentativas_falhas=0, bloqueado_ate=None, versao_sessao=usuario.c.versao_sessao + 1))
            uid = existente
        else:
            uid = c.execute(insert(usuario).values(login=login, nome=nome, senha_hash=generate_password_hash(senha),
                                                   perfil_id=pid, deve_trocar_senha=False, criado_por="criar_admin")
                            .returning(usuario.c.id)).scalar()
    auditar("admin_usuario", "criar_admin", {"login": login, "id": uid, "administrador": True})
    return uid
