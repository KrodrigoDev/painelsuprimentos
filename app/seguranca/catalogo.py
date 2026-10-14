"""Catálogo de telas e ações liberáveis por perfil.

Tela nova: inclua em TELAS (chave, nome, rota, prefixo dos ids da página). O prefixo
é usado pelo guarda para recusar callbacks de telas sem acesso (ids "<prefixo>-...").
Ação nova (ex.: um POST futuro para o Sienge): inclua em ACOES e chame
`sessao.exigir("<acao>")` no callback que executa a ação.
"""
from __future__ import annotations

# chave -> (nome, rota, prefixo dos ids)
TELAS: dict[str, tuple[str, str, str]] = {
    "visao_geral": ("Visão geral", "/visao-geral", "vg"),
    "oportunidades": ("Oportunidades", "/", "op"),
    "comparativo": ("Comparativo de fornecedores", "/comparativo", "cp"),
    "historico": ("Histórico de preços", "/historico", "hp"),
    "correspondencias": ("Correspondências", "/correspondencias", "co"),
    "busca": ("Busca por similaridade", "/busca", "ps"),
    "curva_abc": ("Curva ABC - Insumo", "/curva-abc", "ca"),
    "adiantamento": ("Adiantamento", "/adiantamento", "ad"),
    "avaliacao": ("Avaliação fornecedor", "/avaliacao-fornecedor", "av"),
    "estoque": ("Estoque", "/estoque", "es"),
    "contratos": ("Contratos", "/contratos", "ct"),
    "sla_insumos": ("SLA - Insumos", "/sla-insumos", "sla"),
    "servicos": ("Serviços", "/servicos", "sv"),
    "configuracoes": ("Configurações", "/configuracoes", "cfg"),
    "admin": ("Usuários e perfis", "/admin", "adm"),
}
TELA_POR_ROTA = {rota: chave for chave, (_, rota, _) in TELAS.items()}
TELA_POR_PREFIXO = {pref: chave for chave, (_, _, pref) in TELAS.items()}

ACOES: dict[str, str] = {
    "exportar": "Exportar tabelas e decomposições (CSV / PDF)",
    "gerar_relatorio": "Gerar relatório em PowerPoint",
    "decidir_equivalencia": "Aprovar / rejeitar equivalências de insumos",
    "criar_equivalencia": "Criar par de equivalência manual",
    "editar_vocabulario": "Editar o vocabulário do catálogo",
    "editar_configuracoes": "Editar configurações das abas (ex.: prazos de SLA)",
    "administrar_usuarios": "Criar e editar usuários e perfis",
}

DIMENSOES = {
    "segmentos": "Segmento / vertical",
    "obras": "Obra / centro de custo",
    "empresas": "Empresa",
}

# Dimensões de escopo que os dados de cada tela têm (o resto exige "dados sem a dimensão")
DIMENSOES_DA_TELA: dict[str, dict[str, bool]] = {
    "visao_geral": {"segmento": True, "obra": True, "empresa": True},
    "oportunidades": {"segmento": True, "obra": True, "empresa": True},
    "comparativo": {"segmento": True, "obra": True, "empresa": True},
    "historico": {"segmento": True, "obra": True, "empresa": True},
    "busca": {"segmento": True, "obra": True, "empresa": True},
    "estoque": {"segmento": True, "obra": True, "empresa": True},
    "contratos": {"segmento": True, "obra": True, "empresa": True},
    "sla_insumos": {"segmento": True, "obra": True},
    "servicos": {"segmento": True, "obra": True, "empresa": True},
    "adiantamento": {"empresa": True},
    "curva_abc": {},
    "avaliacao": {},
    "correspondencias": {},
}

# telas de administração (não mostram dados do DW): o escopo de dados não se aplica
TELAS_SEM_DADOS = {"admin", "configuracoes"}
