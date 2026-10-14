"""Catálogo de equivalências (schema painel): leitura do que o ETL processou + decisões humanas."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import and_, func, insert, or_, select, update

from app.db import get_engine, ler_sql
from app.matching.config import CONFIG
from app.models.painel import (equivalencia_decisao, equivalencia_par, insumo_perfil, material_grupo,
                               processamento_log, vocabulario)

STATUS_HUMANOS = ("aprovado", "rejeitado")
STATUS_VALIDOS_GRUPO = ("aprovado", "auto_aprovado")


# ── vocabulário ──────────────────────────────────────────────────────────────
def carregar_vocabulario() -> dict[str, str]:
    try:
        df = ler_sql(select(vocabulario.c.termo, vocabulario.c.substituto).where(vocabulario.c.ativo.is_(True)))
    except Exception:  # noqa: BLE001 — migração ainda não aplicada
        return {}
    return dict(zip(df["termo"], df["substituto"]))


def listar_vocabulario() -> pd.DataFrame:
    return ler_sql(select(vocabulario).order_by(vocabulario.c.termo))


def salvar_termo(termo: str, substituto: str, tipo: str, usuario: str) -> None:
    from app.matching.normalizacao import preparar
    termo_n, subst_n = preparar(termo), preparar(substituto)
    with get_engine().begin() as c:
        existe = c.execute(select(vocabulario.c.id).where(vocabulario.c.termo == termo_n)).scalar()
        if existe:
            c.execute(update(vocabulario).where(vocabulario.c.id == existe).values(
                substituto=subst_n, tipo=tipo, ativo=True, criado_por=usuario))
        else:
            c.execute(insert(vocabulario).values(termo=termo_n, substituto=subst_n, tipo=tipo, criado_por=usuario))


def desativar_termo(id_: int) -> None:
    with get_engine().begin() as c:
        c.execute(update(vocabulario).where(vocabulario.c.id == id_).values(ativo=False))


# ── processamento em lote: feito no ETL (airflow_api_sienge, etapa inteligencia_compras) ──
# perfis, pares calculados, grupos e o log de processamento são GRAVADOS lá; aqui só leitura e
# as decisões humanas (decidir, criar_par_manual, vocabulário).


def ultimo_processamento() -> dict | None:
    try:
        df = ler_sql(select(processamento_log).order_by(processamento_log.c.id.desc()).limit(1))
    except Exception:  # noqa: BLE001
        return None
    return None if df.empty else df.iloc[0].to_dict()


# ── revisão humana ───────────────────────────────────────────────────────────
def decidir(par_id: int, status_novo: str, usuario: str, observacao: str | None = None) -> None:
    if status_novo not in ("aprovado", "rejeitado", "pendente"):
        raise ValueError(status_novo)
    with get_engine().begin() as c:
        atual = c.execute(select(equivalencia_par.c.status, equivalencia_par.c.score)
                          .where(equivalencia_par.c.id == par_id)).one()
        agora = datetime.now(timezone.utc)
        c.execute(update(equivalencia_par).where(equivalencia_par.c.id == par_id).values(
            status=status_novo, decidido_por=usuario, decidido_em=agora, observacao=observacao, atualizado_em=agora))
        c.execute(insert(equivalencia_decisao).values(
            par_id=par_id, status_anterior=atual.status, status_novo=status_novo, usuario=usuario,
            observacao=observacao, versao_regras=CONFIG.versao, score=atual.score))


def criar_par_manual(perfil_a, perfil_b, resultado: dict, usuario: str, observacao: str, status: str) -> int:
    from app.matching.pipeline import hash_par
    a, b = sorted([perfil_a, perfil_b], key=lambda p: p.chave)
    linha = dict(chave_a=a.chave, chave_b=b.chave, descricao_a=a.descricao, descricao_b=b.descricao,
                 categoria=a.categoria, unidade_a=a.unidade, unidade_b=b.unidade, score=resultado["score"],
                 nivel=resultado["nivel"], auto_aprovavel=False, componentes=resultado["componentes"],
                 comparacao=resultado["comparacao"], motivos=resultado["motivos"], metodo="manual", status=status,
                 hash=hash_par(a, b), versao_regras=CONFIG.versao, decidido_por=usuario,
                 decidido_em=datetime.now(timezone.utc), observacao=observacao)
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(equivalencia_par).values(**linha)
    stmt = stmt.on_conflict_do_update(index_elements=["chave_a", "chave_b"],
                                      set_={k: stmt.excluded[k] for k in linha if k not in ("chave_a", "chave_b")})
    with get_engine().begin() as c:
        par_id = c.execute(stmt.returning(equivalencia_par.c.id)).scalar()
        c.execute(insert(equivalencia_decisao).values(par_id=par_id, status_anterior=None, status_novo=status,
                                                      usuario=usuario, observacao=f"[manual] {observacao}",
                                                      versao_regras=CONFIG.versao, score=resultado["score"]))
    return par_id


def listar_pares(status: list[str] | None = None, categoria: str | None = None, texto: str | None = None,
                 nivel: list[str] | None = None, limite: int = 2000) -> pd.DataFrame:
    p = equivalencia_par
    filtros = []
    if status:
        filtros.append(p.c.status.in_(status))
    if nivel:
        filtros.append(p.c.nivel.in_(nivel))
    if categoria:
        filtros.append(p.c.categoria == categoria)
    if texto:
        termo = f"%{texto.strip()}%"
        filtros.append(or_(p.c.descricao_a.ilike(termo), p.c.descricao_b.ilike(termo),
                           p.c.chave_a.like(f"{texto.strip()}|%"), p.c.chave_b.like(f"{texto.strip()}|%")))
    stmt = (select(p.c.id, p.c.chave_a, p.c.chave_b, p.c.descricao_a, p.c.descricao_b, p.c.categoria,
                   p.c.unidade_a, p.c.unidade_b, p.c.score, p.c.nivel, p.c.status, p.c.metodo, p.c.motivos,
                   p.c.decidido_por, p.c.decidido_em, p.c.observacao, p.c.versao_regras)
            .where(and_(*filtros) if filtros else True).order_by(p.c.score.desc()).limit(limite))
    df = ler_sql(stmt)
    df["score"] = df["score"].astype(float)
    return df


def detalhe_par(par_id: int) -> dict | None:
    df = ler_sql(select(equivalencia_par).where(equivalencia_par.c.id == par_id))
    return None if df.empty else df.iloc[0].to_dict()


def historico(par_id: int | None = None, limite: int = 300) -> pd.DataFrame:
    d, p = equivalencia_decisao, equivalencia_par
    stmt = (select(d.c.quando, d.c.usuario, d.c.status_anterior, d.c.status_novo, d.c.observacao, d.c.versao_regras,
                   d.c.score, p.c.id.label("par_id"), p.c.descricao_a, p.c.descricao_b)
            .join(p, p.c.id == d.c.par_id).order_by(d.c.quando.desc()).limit(limite))
    if par_id:
        stmt = stmt.where(d.c.par_id == par_id)
    return ler_sql(stmt)


def contagem_status() -> pd.DataFrame:
    return ler_sql(select(equivalencia_par.c.status, func.count().label("n")).group_by(equivalencia_par.c.status))


def grupos() -> pd.DataFrame:
    try:
        return ler_sql(select(material_grupo))
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=["chave", "id_insumo", "id_grupo", "nome_grupo", "n_membros"])


def perfis_salvos(chaves: list[str] | None = None) -> pd.DataFrame:
    stmt = select(insumo_perfil)
    if chaves:
        stmt = stmt.where(insumo_perfil.c.chave.in_(chaves))
    return ler_sql(stmt)


def decisoes_humanas() -> pd.DataFrame:
    """Pares decididos por pessoas — conjunto de validação que cresce com o uso."""
    p = equivalencia_par
    df = ler_sql(select(p.c.chave_a, p.c.chave_b, p.c.descricao_a, p.c.descricao_b, p.c.unidade_a, p.c.unidade_b,
                        p.c.categoria, p.c.status).where(p.c.status.in_(STATUS_HUMANOS)))
    df["equivalente"] = (df["status"] == "aprovado").astype(int)
    return df.drop(columns="status")
