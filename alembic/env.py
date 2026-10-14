"""Ambiente do Alembic: só enxerga o schema `painel`."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

from app.config import SCHEMA_PAINEL, SETTINGS
from app.models.painel import metadata_painel

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata_painel


def include_object(obj, name, type_, reflected, compare_to):
    # ignora tudo que não for do schema do painel (DW é do ETL)
    schema = getattr(obj, "schema", None) if type_ != "schema" else name
    return schema == SCHEMA_PAINEL if type_ in ("table", "schema") else True


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == SCHEMA_PAINEL
    return True


def run_migrations_offline() -> None:
    context.configure(url=SETTINGS.database_url, target_metadata=target_metadata, literal_binds=True,
                      include_schemas=True, include_object=include_object, include_name=include_name,
                      version_table_schema=SCHEMA_PAINEL)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(SETTINGS.database_url)
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA_PAINEL}"'))
        conn.commit()
        context.configure(connection=conn, target_metadata=target_metadata, include_schemas=True,
                          include_object=include_object, include_name=include_name,
                          version_table_schema=SCHEMA_PAINEL)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
