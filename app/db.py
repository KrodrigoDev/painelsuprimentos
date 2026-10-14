"""Engine SQLAlchemy.

O schema do DW é escolhido por DW_SCHEMA via schema_translate_map: os modelos
apontam para o schema lógico "suprimentos" e cada query é reescrita para o
schema configurado. Trocar mock -> real é só mudar o .env.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.config import SCHEMA_LOGICO, SETTINGS


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    engine = create_engine(SETTINGS.database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    return engine.execution_options(schema_translate_map={SCHEMA_LOGICO: SETTINGS.dw_schema})


def ler_sql(stmt) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(stmt, conn)
