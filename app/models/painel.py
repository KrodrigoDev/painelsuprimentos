"""Tabelas do PRÓPRIO painel (schema `painel`), versionadas pelo Alembic.

O schema do DW (suprimentos) pertence ao ETL e NÃO é gerenciado aqui.
Mudou algo aqui? Gere a migração: alembic revision --autogenerate -m "..."
"""
from sqlalchemy import ARRAY, BigInteger, Column, DateTime, Index, Integer, MetaData, Table, Text, func

from app.config import SCHEMA_PAINEL

metadata_painel = MetaData(schema=SCHEMA_PAINEL)

log_busca_saving = Table(
    "log_busca_saving", metadata_painel,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("criado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("schema_dw", Text, nullable=False),
    Column("categoria", Text, nullable=False),
    Column("consulta", Text, nullable=False),
    Column("ids_insumo", ARRAY(Integer)),
    Column("n_resultados", Integer, nullable=False, server_default="0"),
    Index("ix_log_busca_saving_criado_em", "criado_em"),
)

# ─────────────────────────────────────────────────────────────────────────────
# Catálogo de equivalências (migração 0002)
# ─────────────────────────────────────────────────────────────────────────────
from sqlalchemy import Boolean, Numeric, UniqueConstraint, ForeignKey  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402

vocabulario = Table(
    "vocabulario", metadata_painel,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("termo", Text, nullable=False, unique=True),          # como aparece (normalizado, minúsculo, sem acento)
    Column("substituto", Text, nullable=False),                  # forma canônica
    Column("tipo", Text, nullable=False, server_default="sinonimo"),   # sinonimo | abreviacao | correcao
    Column("ativo", Boolean, nullable=False, server_default="true"),
    Column("criado_por", Text),
    Column("criado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

insumo_perfil = Table(
    "insumo_perfil", metadata_painel,
    Column("chave", Text, primary_key=True),                     # "cod_insumo|cod_detalhe"
    Column("id_insumo", Integer, nullable=False),
    Column("cod_insumo", Integer, nullable=False),
    Column("cod_detalhe", Integer, nullable=False),
    Column("descricao_original", Text, nullable=False),
    Column("descricao_canonica", Text, nullable=False),
    Column("atributos", JSONB, nullable=False),
    Column("categoria", Text),
    Column("unidade", Text),
    Column("tipo_insumo", Text),
    Column("versao_regras", Text, nullable=False),
    Column("atualizado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

STATUS_PAR = ("auto_aprovado", "pendente", "aprovado", "rejeitado", "incompativel", "nao_comparavel", "baixa",
              "revisar_mudanca")

equivalencia_par = Table(
    "equivalencia_par", metadata_painel,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("chave_a", Text, nullable=False),
    Column("chave_b", Text, nullable=False),
    Column("descricao_a", Text, nullable=False),
    Column("descricao_b", Text, nullable=False),
    Column("categoria", Text),
    Column("unidade_a", Text),
    Column("unidade_b", Text),
    Column("score", Numeric(5, 1), nullable=False),
    Column("nivel", Text, nullable=False),          # alta | media | baixa | incompativel | nao_comparavel
    Column("auto_aprovavel", Boolean, nullable=False, server_default="false"),
    Column("componentes", JSONB),                   # métricas: texto, tokens, tfidf, atributos, unidade
    Column("comparacao", JSONB),                    # atributos iguais / parciais / conflitos / embalagem
    Column("motivos", JSONB),
    Column("metodo", Text, nullable=False, server_default="pipeline"),   # pipeline | manual
    Column("status", Text, nullable=False),
    Column("hash", Text, nullable=False),           # muda se descrição/unidade/categoria mudarem
    Column("versao_regras", Text, nullable=False),
    Column("decidido_por", Text),
    Column("decidido_em", DateTime(timezone=True)),
    Column("observacao", Text),
    Column("criado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("atualizado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("chave_a", "chave_b", name="uq_equivalencia_par"),
    Index("ix_equivalencia_par_status", "status"),
    Index("ix_equivalencia_par_chave_b", "chave_b"),
)

equivalencia_decisao = Table(
    "equivalencia_decisao", metadata_painel,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("par_id", BigInteger, ForeignKey("painel.equivalencia_par.id", ondelete="CASCADE"), nullable=False,
           index=True),
    Column("status_anterior", Text),
    Column("status_novo", Text, nullable=False),
    Column("usuario", Text),
    Column("observacao", Text),
    Column("versao_regras", Text),
    Column("score", Numeric(5, 1)),
    Column("quando", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

material_grupo = Table(
    "material_grupo", metadata_painel,
    Column("chave", Text, primary_key=True),
    Column("id_insumo", Integer, nullable=False, index=True),
    Column("id_grupo", Text, nullable=False, index=True),       # chave do insumo representante
    Column("nome_grupo", Text, nullable=False),
    Column("n_membros", Integer, nullable=False),
    Column("versao_regras", Text, nullable=False),
    Column("atualizado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

processamento_log = Table(
    "processamento_log", metadata_painel,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("inicio", DateTime(timezone=True), nullable=False),
    Column("fim", DateTime(timezone=True)),
    Column("versao_regras", Text, nullable=False),
    Column("usuario", Text),
    Column("resumo", JSONB),
    Column("status", Text, nullable=False, server_default="ok"),
)

# ─────────────────────────────────────────────────────────────────────────────
# Acesso: usuários, perfis e auditoria (migração 0003)
# ─────────────────────────────────────────────────────────────────────────────
perfil = Table(
    "perfil", metadata_painel,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", Text, nullable=False, unique=True),
    Column("descricao", Text),
    Column("telas", JSONB, nullable=False, server_default="[]"),     # chaves de app/seguranca/catalogo.TELAS
    Column("acoes", JSONB, nullable=False, server_default="[]"),     # chaves de app/seguranca/catalogo.ACOES
    # escopo de dados padrão do perfil: {"segmentos": [...], "obras": [...], "empresas": [...],
    #                                     "dados_sem_dimensao": bool}  (lista ausente/nula = sem restrição)
    Column("escopo", JSONB, nullable=False, server_default="{}"),
    Column("administrador", Boolean, nullable=False, server_default="false"),
    Column("ativo", Boolean, nullable=False, server_default="true"),
    Column("criado_por", Text),
    Column("criado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("atualizado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

usuario = Table(
    "usuario", metadata_painel,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("login", Text, nullable=False, unique=True),             # minúsculo
    Column("nome", Text, nullable=False),
    Column("email", Text),
    Column("senha_hash", Text, nullable=False),                      # werkzeug (scrypt/pbkdf2) — nunca a senha
    Column("perfil_id", Integer, ForeignKey("painel.perfil.id"), nullable=False, index=True),
    # restrição própria do usuário (cada dimensão preenchida substitui a do perfil)
    Column("escopo", JSONB, nullable=False, server_default="{}"),
    Column("ativo", Boolean, nullable=False, server_default="true"),
    Column("deve_trocar_senha", Boolean, nullable=False, server_default="true"),
    Column("tentativas_falhas", Integer, nullable=False, server_default="0"),
    Column("bloqueado_ate", DateTime(timezone=True)),
    Column("versao_sessao", Integer, nullable=False, server_default="1"),   # +1 derruba sessões abertas
    Column("ultimo_login", DateTime(timezone=True)),
    Column("criado_por", Text),
    Column("criado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("atualizado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

auditoria_acesso = Table(
    "auditoria_acesso", metadata_painel,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("quando", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("login", Text),
    Column("evento", Text, nullable=False),     # login_ok | login_falha | bloqueio | logout | negado | admin_* | acao_*
    Column("detalhe", JSONB),
    Column("ip", Text),
    Index("ix_auditoria_acesso_quando", "quando"),
)

# ─────────────────────────────────────────────────────────────────────────────
# Configurações gerais das abas (migração 0004)
# ─────────────────────────────────────────────────────────────────────────────
config_sla_grupo = Table(
    "config_sla_grupo", metadata_painel,
    Column("id_grupo", Integer, primary_key=True),                 # 02.042 -> 2042 (mesma chave do ETL)
    Column("grupo_insumo", Text),
    Column("lt_fase1", Integer),                                    # dias: autorização da solicitação -> pedido
    Column("lt_fase2", Integer),                                    # dias: pedido -> entrega completa
    Column("lt_total", Integer),
    Column("observacao", Text),
    Column("alterado_por", Text, nullable=False),
    Column("alterado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

configuracao = Table(
    "configuracao", metadata_painel,
    Column("chave", Text, primary_key=True),                        # ex.: sla.em_risco_pct
    Column("valor", JSONB, nullable=False),
    Column("alterado_por", Text, nullable=False),
    Column("alterado_em", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

configuracao_historico = Table(
    "configuracao_historico", metadata_painel,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("quando", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("area", Text, nullable=False),                           # sla_grupo | parametro
    Column("chave", Text, nullable=False),
    Column("valor_anterior", JSONB),
    Column("valor_novo", JSONB),
    Column("por", Text, nullable=False),
    Column("observacao", Text),
    Index("ix_configuracao_historico_quando", "quando"),
)
