"""Usuário da requisição atual (lido da sessão Flask) e checagem de permissões.

A sessão guarda só {uid, versão}. O usuário é relido do banco com cache de 30 s:
desativar alguém, trocar perfil/escopo ou redefinir senha incrementa
`versao_sessao` e a sessão aberta cai na próxima requisição.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from flask import has_request_context, session

from app.seguranca import repo
from app.seguranca.catalogo import ACOES, TELAS
from app.seguranca.escopo import TOTAL, Escopo

TTL_S = 30


class AcessoNegado(PermissionError):
    pass


@dataclass(frozen=True)
class UsuarioSessao:
    id: int
    login: str
    nome: str
    perfil: str
    telas: frozenset = field(default_factory=frozenset)
    acoes: frozenset = field(default_factory=frozenset)
    escopo: Escopo = TOTAL
    administrador: bool = False
    deve_trocar_senha: bool = False
    versao: int = 1


# usuário "de sistema" para scripts/testes fora de requisição web (sem tela, sem restrição)
SISTEMA = UsuarioSessao(id=0, login="sistema", nome="Processo interno", perfil="sistema",
                        telas=frozenset(TELAS), acoes=frozenset(ACOES), administrador=True)

_cache: dict[int, tuple[float, UsuarioSessao | None]] = {}
_lock = threading.Lock()


def _montar(r: dict) -> UsuarioSessao:
    adm = bool(r["administrador"])
    return UsuarioSessao(
        id=r["id"], login=r["login"], nome=r["nome"], perfil=r["perfil_nome"],
        telas=frozenset(TELAS) if adm else frozenset(r["telas"] or []),
        acoes=frozenset(ACOES) if adm else frozenset(r["acoes"] or []),
        escopo=Escopo.de_json(r["perfil_escopo"], r["escopo"]), administrador=adm,
        deve_trocar_senha=bool(r["deve_trocar_senha"]), versao=int(r["versao_sessao"]))


def carregar(uid: int, forcar: bool = False) -> UsuarioSessao | None:
    with _lock:
        em, u = _cache.get(uid, (0.0, None))
        if forcar or time.monotonic() - em > TTL_S:
            r = repo.carregar_usuario(uid)
            u = _montar(r) if r and r["ativo"] and r["perfil_ativo"] else None
            _cache[uid] = (time.monotonic(), u)
        return u


def limpar_cache() -> None:
    with _lock:
        _cache.clear()


def atual() -> UsuarioSessao | None:
    """Usuário logado (None se não há sessão válida). Fora de requisição web: SISTEMA."""
    if not has_request_context():
        return SISTEMA
    uid = session.get("uid")
    if not uid:
        return None
    u = carregar(int(uid))
    if u is None or u.versao != session.get("v"):
        return None
    return u


def login_atual() -> str:
    u = atual()
    return u.login if u else "anônimo"


def escopo() -> Escopo:
    u = atual()
    return u.escopo if u else Escopo(segmentos=frozenset(), obras=frozenset(), empresas=frozenset(),
                                     dados_sem_dimensao=False)


def pode(acao: str) -> bool:
    u = atual()
    return bool(u and acao in u.acoes)


def pode_tela(tela: str) -> bool:
    u = atual()
    return bool(u and tela in u.telas)


def exigir(acao: str) -> UsuarioSessao:
    """Use no início de callbacks que EXECUTAM algo (gravar, exportar, futuros POSTs)."""
    u = atual()
    if not u or acao not in u.acoes:
        repo.auditar("negado", u.login if u else None, {"acao": acao})
        raise AcessoNegado(f"Seu perfil não permite: {ACOES.get(acao, acao)}.")
    return u
