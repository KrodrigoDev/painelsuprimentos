"""Gravações no schema `painel` (tabelas do próprio app, criadas pelo Alembic)."""
from __future__ import annotations

import logging

from sqlalchemy import insert

from app.config import SETTINGS
from app.db import get_engine
from app.models.painel import log_busca_saving

logger = logging.getLogger(__name__)


def registrar_busca(categoria: str, consulta: str, ids_insumo: list[int]) -> None:
    """Log das buscas (base futura para 'itens mais pesquisados'). Nunca derruba a tela."""
    try:
        with get_engine().begin() as conn:
            conn.execute(insert(log_busca_saving).values(
                schema_dw=SETTINGS.dw_schema, categoria=categoria, consulta=consulta,
                ids_insumo=[int(i) for i in ids_insumo][:200], n_resultados=len(ids_insumo)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Log de busca não gravado (rode `alembic upgrade head`?): %s", str(exc).splitlines()[0])
