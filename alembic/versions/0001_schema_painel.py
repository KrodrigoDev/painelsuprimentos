"""schema painel + log de buscas do saving

Revision ID: 0001
Revises:
Create Date: 2026-10-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS painel')
    op.create_table(
        "log_busca_saving",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("schema_dw", sa.Text, nullable=False),
        sa.Column("categoria", sa.Text, nullable=False),
        sa.Column("consulta", sa.Text, nullable=False),
        sa.Column("ids_insumo", postgresql.ARRAY(sa.Integer)),
        sa.Column("n_resultados", sa.Integer, nullable=False, server_default="0"),
        schema="painel",
    )
    op.create_index("ix_log_busca_saving_criado_em", "log_busca_saving", ["criado_em"], schema="painel")


def downgrade() -> None:
    op.drop_index("ix_log_busca_saving_criado_em", table_name="log_busca_saving", schema="painel")
    op.drop_table("log_busca_saving", schema="painel")
