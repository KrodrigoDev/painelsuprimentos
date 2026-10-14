"""configurações gerais das abas: prazos de SLA por grupo de insumo, parâmetros e histórico

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14

Também libera as telas novas (SLA de insumos, Serviços, Configurações) nos perfis-modelo.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

S = "painel"


def upgrade() -> None:
    op.create_table(
        "config_sla_grupo",
        sa.Column("id_grupo", sa.Integer, primary_key=True),
        sa.Column("grupo_insumo", sa.Text),
        sa.Column("lt_fase1", sa.Integer),
        sa.Column("lt_fase2", sa.Integer),
        sa.Column("lt_total", sa.Integer),
        sa.Column("observacao", sa.Text),
        sa.Column("alterado_por", sa.Text, nullable=False),
        sa.Column("alterado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=S,
    )
    op.create_table(
        "configuracao",
        sa.Column("chave", sa.Text, primary_key=True),
        sa.Column("valor", JSONB, nullable=False),
        sa.Column("alterado_por", sa.Text, nullable=False),
        sa.Column("alterado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=S,
    )
    op.create_table(
        "configuracao_historico",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("quando", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("area", sa.Text, nullable=False),
        sa.Column("chave", sa.Text, nullable=False),
        sa.Column("valor_anterior", JSONB),
        sa.Column("valor_novo", JSONB),
        sa.Column("por", sa.Text, nullable=False),
        sa.Column("observacao", sa.Text),
        schema=S,
    )
    op.create_index("ix_configuracao_historico_quando", "configuracao_historico", ["quando"], schema=S)
    # telas novas nos perfis-modelo (o Administrador já vê tudo)
    op.execute(f"""UPDATE {S}.perfil SET telas = telas || '["sla_insumos", "servicos", "configuracoes"]'::jsonb,
                   acoes = acoes || '["editar_configuracoes"]'::jsonb WHERE nome = 'Gestor de suprimentos'""")
    op.execute(f"""UPDATE {S}.perfil SET telas = telas || '["sla_insumos", "servicos"]'::jsonb
                   WHERE nome = 'Consulta'""")


def downgrade() -> None:
    op.drop_index("ix_configuracao_historico_quando", table_name="configuracao_historico", schema=S)
    op.drop_table("configuracao_historico", schema=S)
    op.drop_table("configuracao", schema=S)
    op.drop_table("config_sla_grupo", schema=S)
