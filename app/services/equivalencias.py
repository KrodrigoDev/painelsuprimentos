"""
(Removido) O processamento do catálogo de equivalências saiu do painel.

Agora roda no ETL — airflow_api_sienge, etapa `inteligencia_compras`
(stage/transform/inteligencia/catalogo.py), depois da carga de pedidos e de hora
em hora (DAG etl_inteligencia_compras). O painel só lê o catálogo e grava as
decisões humanas (tela Correspondências).
"""
from __future__ import annotations


def usuario_atual() -> str:
    """Login do usuário da sessão (mantido para compatibilidade)."""
    from app.seguranca import sessao
    return sessao.login_atual()
