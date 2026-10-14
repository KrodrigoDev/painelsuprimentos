"""
Teste do painel contra o DW REAL (schema suprimentos) + remoção do mock.

Uso (na raiz do projeto, com o .venv ativo):
    python -m scripts.testar_dw                  # só testa
    python -m scripts.testar_dw --remover-mock   # testa e apaga o schema suprimentos_mock

Gera relatorio_teste_dw.txt na raiz do projeto (o mesmo conteúdo sai no console).
Não altera nada no schema suprimentos (só leitura).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# força a leitura do schema REAL antes de carregar as configurações do app
os.environ["DW_SCHEMA"] = "suprimentos"

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from app.config import RAIZ, SETTINGS  # noqa: E402
from app.models.dw import metadata_dw  # noqa: E402

RELATORIO = RAIZ / "relatorio_teste_dw.txt"
_linhas: list[str] = []
_falhas: list[str] = []


def log(msg: str = "") -> None:
    print(msg)
    _linhas.append(msg)


def ok(msg: str) -> None:
    log(f"  [OK]    {msg}")


def aviso(msg: str) -> None:
    log(f"  [AVISO] {msg}")


def falha(msg: str) -> None:
    log(f"  [FALHA] {msg}")
    _falhas.append(msg)


def secao(titulo: str) -> None:
    log("")
    log(f"── {titulo} " + "─" * max(0, 70 - len(titulo)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remover-mock", action="store_true", help="DROP SCHEMA suprimentos_mock CASCADE")
    args = ap.parse_args()

    log(f"Teste do painel contra o DW — {datetime.now():%d/%m/%Y %H:%M:%S}")
    log(f"Banco: {SETTINGS.database_url.split('@')[-1]}  |  schema lido: {SETTINGS.dw_schema}")
    engine = create_engine(SETTINGS.database_url)

    # ── 1. Conexão ──────────────────────────────────────────────────────────
    secao("1. Conexão")
    try:
        with engine.connect() as c:
            versao = c.execute(text("select version()")).scalar()
            usuario = c.execute(text("select current_user")).scalar()
        ok(f"conectado como {usuario} — {versao.split(',')[0]}")
    except Exception as exc:  # noqa: BLE001
        falha(f"não conectou: {str(exc).splitlines()[0]}")
        return _fim()

    insp = inspect(engine)
    schemas = insp.get_schema_names()

    # ── 2. Estrutura ────────────────────────────────────────────────────────
    secao("2. Estrutura do schema suprimentos (x modelos do painel)")
    if "suprimentos" not in schemas:
        falha("schema suprimentos não existe — a DAG etl_pedidos_compra já carregou?")
        return _fim()
    tabelas_db = set(insp.get_table_names(schema="suprimentos"))
    for tabela in metadata_dw.sorted_tables:
        if tabela.name not in tabelas_db:
            falha(f"tabela {tabela.name} não existe no banco")
            continue
        cols_db = {c["name"] for c in insp.get_columns(tabela.name, schema="suprimentos")}
        cols_app = {c.name for c in tabela.columns}
        faltando = cols_app - cols_db
        if faltando:
            falha(f"{tabela.name}: colunas usadas pelo painel e ausentes no banco: {sorted(faltando)}")
        else:
            extras = cols_db - cols_app
            ok(f"{tabela.name}: {len(cols_db)} colunas" + (f" (extras no banco: {sorted(extras)})" if extras else ""))
    views = insp.get_view_names(schema="suprimentos")
    (ok if "vw_itens_pedido" in views else aviso)(f"views: {views}")

    # ── 3. Volumes e qualidade ──────────────────────────────────────────────
    secao("3. Volumes e qualidade dos dados")
    q = lambda sql: pd_read(engine, sql)  # noqa: E731
    vol = q("""
        select (select count(*) from suprimentos.dim_pedido) pedidos,
               (select count(*) from suprimentos.fato_pedido_compra_item) itens,
               (select count(*) from suprimentos.dim_insumo) insumos,
               (select count(*) from suprimentos.dim_fornecedor) fornecedores,
               (select count(distinct cod_obra) from suprimentos.fato_pedido_compra_item) obras,
               (select min(data_pedido) from suprimentos.fato_pedido_compra_item) data_ini,
               (select max(data_pedido) from suprimentos.fato_pedido_compra_item) data_fim,
               (select max(data_carga) from suprimentos.fato_pedido_compra_item) ultima_carga
    """).iloc[0]
    for k, v in vol.items():
        log(f"  {k:<14} {v}")
    if not vol["itens"]:
        falha("fato_pedido_compra_item vazia")
        return _fim()

    qual = q("""
        select count(*) total,
               count(*) filter (where flag_preco_valido)              preco_valido,
               count(*) filter (where coalesce(preco_liquido,0) <= 0)  preco_zero,
               count(*) filter (where flag_cancelado)                 cancelados,
               count(*) filter (where id_fornecedor is null)          sem_fornecedor,
               sum(valor_liquido_item) filter (where flag_preco_valido) gasto_valido
        from suprimentos.fato_pedido_compra_item
    """).iloc[0].fillna(0)
    qual = {k: (float(v) if k == "gasto_valido" else int(v)) for k, v in qual.items()}
    pct = qual["preco_valido"] / qual["total"] * 100
    (ok if pct >= 90 else aviso)(f"itens com preço válido p/ saving: {qual['preco_valido']:,} de {qual['total']:,} ({pct:.1f}%)")
    log(f"  preço zerado: {qual['preco_zero']:,} | cancelados: {qual['cancelados']:,} | sem fornecedor: {qual['sem_fornecedor']:,}")
    log(f"  gasto total (itens válidos): R$ {float(qual['gasto_valido'] or 0):,.2f}")

    nm = q("""select count(distinct f.cod_obra) n from suprimentos.fato_pedido_compra_item f
              join suprimentos.dim_centro_custo c using (cod_obra) where c.origem_info = 'sienge_nao_mapeado'""").iloc[0, 0]
    (ok if nm == 0 else aviso)(f"centros de custo sem cadastro (aparecem só com o código): {nm}")
    forn_sem_nome = q("""select count(*) from suprimentos.dim_fornecedor where nome_fornecedor like 'FORNECEDOR %%'""").iloc[0, 0]
    (ok if forn_sem_nome == 0 else aviso)(f"fornecedores sem nome (credores.csv desatualizado?): {forn_sem_nome}")

    cat = q("""
        select i.categoria, count(distinct i.id_insumo) insumos, count(*) itens, sum(f.valor_liquido_item) gasto
        from suprimentos.fato_pedido_compra_item f join suprimentos.dim_insumo i using (id_insumo)
        where f.flag_preco_valido group by 1 order by gasto desc
    """)
    sem_cat = cat.loc[cat["categoria"] == "SEM CATEGORIA", "itens"].sum()
    (ok if sem_cat == 0 else aviso)(f"categorias: {len(cat)} | itens SEM CATEGORIA: {int(sem_cat):,}")
    log("  top 10 categorias por gasto:")
    for r in cat.head(10).itertuples():
        log(f"    {r.categoria[:45]:<45} {r.insumos:>5} insumos  R$ {float(r.gasto):>16,.2f}")
    prefixo = q("""select count(*) from suprimentos.dim_insumo where grupo_insumo is null""").iloc[0, 0]
    if prefixo:
        aviso(f"{prefixo} insumos sem grupo no de-para (categoria = prefixo do código Sienge)")

    un = q("""select unidade_padrao, count(*) n from suprimentos.dim_insumo group by 1 order by 2 desc limit 12""")
    log("  unidades: " + ", ".join(f"{r.unidade_padrao}={r.n}" for r in un.itertuples()))

    # ── 4. Funcional: similaridade + saving com dados reais ─────────────────
    secao("4. Teste funcional (busca por similaridade + saving)")
    try:
        from app.repositories import suprimentos_repo
        from app.services import saving
        from app.services.similaridade import INDICE

        t = time.perf_counter()
        cats = INDICE.categorias()
        ok(f"índice carregado: {len(INDICE.insumos()):,} insumos com compra, {len(cats)} categorias "
           f"({time.perf_counter() - t:.1f}s)")

        # 3 maiores categorias: busca pelo insumo mais comprado de cada uma
        alvo = q("""
            select distinct on (i.categoria) i.categoria, i.descricao_completa, sum(f.valor_liquido_item) gasto
            from suprimentos.fato_pedido_compra_item f join suprimentos.dim_insumo i using (id_insumo)
            where f.flag_preco_valido group by 1, 2 order by i.categoria, gasto desc
        """).sort_values("gasto", ascending=False).head(3)
        for r in alvo.itertuples():
            consulta = " ".join(str(r.descricao_completa).split()[:4])
            t = time.perf_counter()
            res = INDICE.buscar(consulta, r.categoria, top_n=40)
            t_busca = time.perf_counter() - t
            if res.empty:
                aviso(f"“{consulta}” em {r.categoria}: nenhum similar")
                continue
            unid = res.iloc[0]["unidade_padrao"]
            ids = res.loc[res["unidade_padrao"] == unid, "id_insumo"].tolist()
            t = time.perf_counter()
            df = saving.enriquecer(suprimentos_repo.itens_dos_insumos(ids))
            rs = saving.resumo(df)
            t_saving = time.perf_counter() - t
            ok(f"“{consulta}” em {r.categoria[:30]} → {len(res)} similares ({t_busca * 1000:.0f} ms), "
               f"{len(ids)} na unidade {unid}")
            log(f"        gasto R$ {rs.total_gasto:,.2f} | médio pond. R$ {rs.preco_medio_pond:,.4f} | "
                f"menor R$ {rs.menor_preco:,.4f} | maior R$ {rs.maior_preco:,.4f}")
            log(f"        {rs.n_fornecedores} fornec. · {rs.n_obras} obras · {rs.n_pedidos} pedidos | "
                f"saving (menor do mês) R$ {rs.saving_menor_mes:,.2f} "
                f"({rs.saving_menor_mes / rs.total_gasto * 100 if rs.total_gasto else 0:.1f}%) | {t_saving * 1000:.0f} ms")
            log("        top 5 similares: " + " | ".join(
                f"{d[:40]} ({s:.0%})" for d, s in res[["descricao_completa", "score"]].head(5).itertuples(index=False)))
    except Exception:  # noqa: BLE001
        falha("erro no teste funcional:\n" + traceback.format_exc())

    # ── 5. Schema do painel (Alembic) ───────────────────────────────────────
    secao("5. Schema painel (Alembic)")
    if "painel" in schemas:
        v = q("select version_num from painel.alembic_version")
        ok(f"schema painel existe — migração {v.iloc[0, 0] if len(v) else '?'}")
    else:
        aviso("schema painel não existe — rode: alembic upgrade head")

    # ── 6. Mock ─────────────────────────────────────────────────────────────
    secao("6. Dados mockup")
    if "suprimentos_mock" in schemas:
        if args.remover_mock:
            with engine.begin() as c:
                c.execute(text("DROP SCHEMA suprimentos_mock CASCADE"))
                if "painel" in schemas:
                    c.execute(text("DELETE FROM painel.log_busca_saving WHERE schema_dw = 'suprimentos_mock'"))
            ok("schema suprimentos_mock removido (e log de buscas do mock apagado)")
        else:
            aviso("schema suprimentos_mock ainda existe — rode com --remover-mock para apagar")
    else:
        ok("nenhum schema de mock no banco")
    env = (RAIZ / ".env").read_text(encoding="utf-8") if (RAIZ / ".env").exists() else ""
    (ok if "DW_SCHEMA=suprimentos\n" in env.replace("\r", "") + "\n" else aviso)(
        "o .env aponta para DW_SCHEMA=suprimentos" if "DW_SCHEMA=suprimentos\n" in env.replace("\r", "") + "\n"
        else "ajuste o .env: DW_SCHEMA=suprimentos")
    return _fim()


def pd_read(engine, sql: str):
    import pandas as pd
    with engine.connect() as c:
        return pd.read_sql(text(sql), c)


def _fim() -> int:
    secao("Resultado")
    log("TUDO OK" if not _falhas else f"{len(_falhas)} FALHA(S): " + "; ".join(f.splitlines()[0] for f in _falhas))
    RELATORIO.write_text("\n".join(_linhas), encoding="utf-8")
    print(f"\nRelatório salvo em {RELATORIO}")
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
