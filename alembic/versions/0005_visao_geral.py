"""libera a tela Visão geral nos perfis-modelo

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""UPDATE painel.perfil SET telas = telas || '["visao_geral"]'::jsonb
                  WHERE nome IN ('Gestor de suprimentos', 'Consulta') AND NOT telas ? 'visao_geral'""")


def downgrade() -> None:
    op.execute("UPDATE painel.perfil SET telas = telas - 'visao_geral'")
