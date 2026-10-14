"""catálogo de equivalências de insumos (pares, decisões, grupos, vocabulário, perfis)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

S = "painel"


def _agora():
    return sa.func.now()


def upgrade() -> None:
    op.create_table(
        "vocabulario",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("termo", sa.Text, nullable=False, unique=True),
        sa.Column("substituto", sa.Text, nullable=False),
        sa.Column("tipo", sa.Text, nullable=False, server_default="sinonimo"),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("criado_por", sa.Text),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=_agora()),
        schema=S,
    )
    op.create_table(
        "insumo_perfil",
        sa.Column("chave", sa.Text, primary_key=True),
        sa.Column("id_insumo", sa.Integer, nullable=False),
        sa.Column("cod_insumo", sa.Integer, nullable=False),
        sa.Column("cod_detalhe", sa.Integer, nullable=False),
        sa.Column("descricao_original", sa.Text, nullable=False),
        sa.Column("descricao_canonica", sa.Text, nullable=False),
        sa.Column("atributos", JSONB, nullable=False),
        sa.Column("categoria", sa.Text),
        sa.Column("unidade", sa.Text),
        sa.Column("tipo_insumo", sa.Text),
        sa.Column("versao_regras", sa.Text, nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=_agora()),
        schema=S,
    )
    op.create_table(
        "equivalencia_par",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("chave_a", sa.Text, nullable=False),
        sa.Column("chave_b", sa.Text, nullable=False),
        sa.Column("descricao_a", sa.Text, nullable=False),
        sa.Column("descricao_b", sa.Text, nullable=False),
        sa.Column("categoria", sa.Text),
        sa.Column("unidade_a", sa.Text),
        sa.Column("unidade_b", sa.Text),
        sa.Column("score", sa.Numeric(5, 1), nullable=False),
        sa.Column("nivel", sa.Text, nullable=False),
        sa.Column("auto_aprovavel", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("componentes", JSONB),
        sa.Column("comparacao", JSONB),
        sa.Column("motivos", JSONB),
        sa.Column("metodo", sa.Text, nullable=False, server_default="pipeline"),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("hash", sa.Text, nullable=False),
        sa.Column("versao_regras", sa.Text, nullable=False),
        sa.Column("decidido_por", sa.Text),
        sa.Column("decidido_em", sa.DateTime(timezone=True)),
        sa.Column("observacao", sa.Text),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=_agora()),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=_agora()),
        sa.UniqueConstraint("chave_a", "chave_b", name="uq_equivalencia_par"),
        schema=S,
    )
    op.create_index("ix_equivalencia_par_status", "equivalencia_par", ["status"], schema=S)
    op.create_index("ix_equivalencia_par_chave_b", "equivalencia_par", ["chave_b"], schema=S)
    op.create_table(
        "equivalencia_decisao",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("par_id", sa.BigInteger, sa.ForeignKey(f"{S}.equivalencia_par.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("status_anterior", sa.Text),
        sa.Column("status_novo", sa.Text, nullable=False),
        sa.Column("usuario", sa.Text),
        sa.Column("observacao", sa.Text),
        sa.Column("versao_regras", sa.Text),
        sa.Column("score", sa.Numeric(5, 1)),
        sa.Column("quando", sa.DateTime(timezone=True), nullable=False, server_default=_agora()),
        schema=S,
    )
    op.create_index("ix_painel_equivalencia_decisao_par_id", "equivalencia_decisao", ["par_id"], schema=S)
    op.create_table(
        "material_grupo",
        sa.Column("chave", sa.Text, primary_key=True),
        sa.Column("id_insumo", sa.Integer, nullable=False),
        sa.Column("id_grupo", sa.Text, nullable=False),
        sa.Column("nome_grupo", sa.Text, nullable=False),
        sa.Column("n_membros", sa.Integer, nullable=False),
        sa.Column("versao_regras", sa.Text, nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=_agora()),
        schema=S,
    )
    op.create_index("ix_painel_material_grupo_id_insumo", "material_grupo", ["id_insumo"], schema=S)
    op.create_index("ix_painel_material_grupo_id_grupo", "material_grupo", ["id_grupo"], schema=S)
    op.create_table(
        "processamento_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim", sa.DateTime(timezone=True)),
        sa.Column("versao_regras", sa.Text, nullable=False),
        sa.Column("usuario", sa.Text),
        sa.Column("resumo", JSONB),
        sa.Column("status", sa.Text, nullable=False, server_default="ok"),
        schema=S,
    )


def downgrade() -> None:
    for t in ("processamento_log", "material_grupo", "equivalencia_decisao", "equivalencia_par",
              "insumo_perfil", "vocabulario"):
        op.drop_table(t, schema=S)
