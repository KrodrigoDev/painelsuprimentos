"""Configurações do painel (lidas do .env na raiz do projeto)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str
    dw_schema: str
    cache_minutos: int
    debug: bool
    port: int

    @classmethod
    def from_env(cls) -> "Settings":
        url = os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL não definido. Copie .env.example para .env e preencha.")
        return cls(
            database_url=url,
            dw_schema=os.getenv("DW_SCHEMA", "suprimentos_mock"),
            cache_minutos=int(os.getenv("CACHE_MINUTOS", "30")),
            debug=os.getenv("DASH_DEBUG", "false").lower() in ("1", "true", "sim"),
            port=int(os.getenv("DASH_PORT", "8050")),
        )


SETTINGS = Settings.from_env()

# Schema "lógico" usado nos modelos; traduzido em tempo de execução para
# SETTINGS.dw_schema (suprimentos_mock em desenvolvimento, suprimentos em produção).
SCHEMA_LOGICO = "suprimentos"
# Schema do próprio painel (gerenciado pelo Alembic).
SCHEMA_PAINEL = "painel"
