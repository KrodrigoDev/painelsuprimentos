"""usuários, perfis de acesso (telas, ações, escopo de dados) e auditoria

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13

Nenhum usuário é criado aqui (nada de senha em código): depois do upgrade rode
    python -m scripts.criar_admin
Os perfis-modelo abaixo são só sugestões editáveis na tela /admin.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

S = "painel"

TODAS_TELAS = ["oportunidades", "comparativo", "historico", "correspondencias", "busca", "curva_abc", "adiantamento",
               "avaliacao", "estoque", "contratos"]
PERFIS = [
    ("Administrador", "Acesso total, inclusive usuários e perfis.", TODAS_TELAS + ["admin"],
     ["exportar", "gerar_relatorio", "decidir_equivalencia", "criar_equivalencia", "editar_vocabulario",
      "administrar_usuarios"], {"dados_sem_dimensao": True}, True),
    ("Gestor de suprimentos", "Todas as telas e decisões do catálogo; sem administração de usuários.", TODAS_TELAS,
     ["exportar", "gerar_relatorio", "decidir_equivalencia", "criar_equivalencia", "editar_vocabulario"],
     {"dados_sem_dimensao": True}, False),
    ("Consulta", "Somente leitura das telas de painéis, sem exportar.",
     ["oportunidades", "comparativo", "historico", "curva_abc", "estoque", "contratos"], [],
     {"dados_sem_dimensao": False}, False),
]


def upgrade() -> None:
    op.create_table(
        "perfil",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("nome", sa.Text, nullable=False, unique=True),
        sa.Column("descricao", sa.Text),
        sa.Column("telas", JSONB, nullable=False, server_default="[]"),
        sa.Column("acoes", JSONB, nullable=False, server_default="[]"),
        sa.Column("escopo", JSONB, nullable=False, server_default="{}"),
        sa.Column("administrador", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("criado_por", sa.Text),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=S,
    )
    op.create_table(
        "usuario",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("login", sa.Text, nullable=False, unique=True),
        sa.Column("nome", sa.Text, nullable=False),
        sa.Column("email", sa.Text),
        sa.Column("senha_hash", sa.Text, nullable=False),
        sa.Column("perfil_id", sa.Integer, sa.ForeignKey(f"{S}.perfil.id"), nullable=False, index=True),
        sa.Column("escopo", JSONB, nullable=False, server_default="{}"),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("deve_trocar_senha", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("tentativas_falhas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bloqueado_ate", sa.DateTime(timezone=True)),
        sa.Column("versao_sessao", sa.Integer, nullable=False, server_default="1"),
        sa.Column("ultimo_login", sa.DateTime(timezone=True)),
        sa.Column("criado_por", sa.Text),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=S,
    )
    op.create_table(
        "auditoria_acesso",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("quando", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("login", sa.Text),
        sa.Column("evento", sa.Text, nullable=False),
        sa.Column("detalhe", JSONB),
        sa.Column("ip", sa.Text),
        schema=S,
    )
    op.create_index("ix_auditoria_acesso_quando", "auditoria_acesso", ["quando"], schema=S)
    tabela = sa.table("perfil", sa.column("nome"), sa.column("descricao"), sa.column("telas", JSONB),
                      sa.column("acoes", JSONB), sa.column("escopo", JSONB), sa.column("administrador"),
                      sa.column("criado_por"), schema=S)
    op.bulk_insert(tabela, [dict(nome=n, descricao=d, telas=t, acoes=a, escopo=e, administrador=adm,
                                 criado_por="migracao_0003") for n, d, t, a, e, adm in PERFIS])


def downgrade() -> None:
    op.drop_index("ix_auditoria_acesso_quando", table_name="auditoria_acesso", schema=S)
    op.drop_table("auditoria_acesso", schema=S)
    op.drop_table("usuario", schema=S)
    op.drop_table("perfil", schema=S)
