"""
Cria e popula o schema de MOCK (padrão: suprimentos_mock) com o MESMO layout
do schema `suprimentos` do DW, para desenvolver o painel sem depender da DAG.

Fonte: os CSVs antigos do painel de compras (data/input/painel_compras/*.csv)
fornecem insumos, obras, fornecedores, datas e quantidades REAIS; os PREÇOS
são SINTÉTICOS (o CSV não tem preço unitário), gerados assim:
    preço = base do insumo × fator do fornecedor × fator da obra
            × tendência mensal × ruído
de modo que existam diferenças de preço entre obras/fornecedores para o
cálculo de saving fazer sentido. NÃO use os valores do mock para decisão.

Uso (na raiz do projeto, com o .venv ativo):
    python -m scripts.seed_mock                 # schema do .env (DW_SCHEMA)
    python -m scripts.seed_mock --schema suprimentos_mock

Por segurança, recusa gravar no schema `suprimentos` (dados reais).
"""
from __future__ import annotations

import argparse
import glob
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from app.config import RAIZ, SCHEMA_LOGICO, SETTINGS
from app.models.dw import metadata_dw
from app.services.texto import normalizar_texto

logger = logging.getLogger("seed_mock")

DIR_CSV = RAIZ / "data" / "input" / "painel_compras"
DIM_CC = RAIZ / "data" / "reference" / "dim_centro_custo.csv"

STATUS = {"Pendente": "PENDING", "Parcialmente entregue": "PARTIALLY_DELIVERED",
          "Totalmente entregue": "FULLY_DELIVERED", "Cancelado": "CANCELED"}
DIM_STATUS = pd.DataFrame([
    (0, "DESCONHECIDO", "Não informado"), (1, "PENDING", "Pendente"),
    (2, "PARTIALLY_DELIVERED", "Parcialmente entregue"), (3, "FULLY_DELIVERED", "Totalmente entregue"),
    (4, "CANCELED", "Cancelado")], columns=["id_status", "status_pedido", "descricao"])
UNIDADE_PADRAO = {"und": "un", "unid": "un", "unid.": "un", "pc": "un", "pç": "un", "m²": "m2", "m³": "m3",
                  "lt": "l", "mês": "mes", "ton": "t", "pr": "par", "rol": "rl"}


def _num_br(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")


def _ler_csvs() -> pd.DataFrame:
    arquivos = sorted(glob.glob(str(DIR_CSV / "*.csv")))
    if not arquivos:
        raise FileNotFoundError(f"Nenhum CSV em {DIR_CSV}")
    df = pd.concat([pd.read_csv(a, sep=";", dtype=str) for a in arquivos], ignore_index=True)
    df = df.dropna(subset=["N° do Pedido", "Cód. Fornecedor", "Data do pedido"])
    logger.info("CSVs: %d linhas com pedido", len(df))
    return df


def montar(df: pd.DataFrame, seed: int = 42) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    df = df.copy()
    df["cod_pedido"] = df["N° do Pedido"].astype(int)
    df["cod_insumo"] = df["Cód. Insumo"].astype(int)
    df["detalhe"] = df["Detalhe"].fillna("").str.strip()
    df["data_pedido"] = pd.to_datetime(df["Data do pedido"], dayfirst=True)
    df["quantidade"] = _num_br(df["Quantidade solicitada"])
    df = df[df["quantidade"] > 0]

    # ── dim_insumo ──────────────────────────────────────────────────────────
    df["cod_detalhe"] = 0
    com_det = df["detalhe"] != ""
    df.loc[com_det, "cod_detalhe"] = (
        df[com_det].groupby("cod_insumo")["detalhe"].transform(lambda s: pd.factorize(s.sort_values())[0][
            pd.Index(s.sort_values().unique()).get_indexer(s)] + 1)
    )
    ins = df.drop_duplicates(["cod_insumo", "cod_detalhe"], keep="last").copy()
    partes = ins["Descrição do insumo"].str.extract(r"^\s*\d+\s*-\s*(?:([A-Za-z0-9]{1,3})\s*-\s*)?(.*)$")
    ins["tipo_insumo"] = partes[0].str.upper()
    ins["insumo"] = partes[1].str.strip()
    ins["descricao_completa"] = (ins["insumo"] + np.where(ins["detalhe"] != "", " - " + ins["detalhe"], "")).str.strip()
    ins["descricao_normalizada"] = ins["descricao_completa"].map(normalizar_texto)
    ins["cod_grupo_insumo"] = ins["Cód. Grupo de insumo"]
    ins["grupo_insumo"] = ins["Grupo de insumo"].str.replace(r"^[\d.]+\s*-\s*", "", regex=True).str.strip()
    ins["categoria"] = ins["grupo_insumo"].fillna("SEM CATEGORIA")
    ins["unidade"] = ins["Unidade de movimento"].str.strip().str.lower()
    ins["unidade_padrao"] = ins["unidade"].map(lambda u: UNIDADE_PADRAO.get(u, u))
    ins = ins.sort_values(["cod_insumo", "cod_detalhe"]).reset_index(drop=True)
    ins["id_insumo"] = ins.index + 1
    dim_insumo = ins[["id_insumo", "cod_insumo", "cod_detalhe", "insumo", "detalhe", "descricao_completa",
                      "descricao_normalizada", "tipo_insumo", "cod_grupo_insumo", "grupo_insumo", "categoria",
                      "unidade", "unidade_padrao"]].assign(codigo_auxiliar_insumo=None, prefixo_codigo=None)

    # ── dim_fornecedor / comprador / centro de custo ────────────────────────
    forn = df.drop_duplicates("Cód. Fornecedor")[["Cód. Fornecedor", "Fornecedor"]].copy()
    forn["cod_fornecedor"] = forn["Cód. Fornecedor"].astype(int)
    forn["nome_fornecedor"] = forn["Fornecedor"].str.replace(r"^\d+\s*-\s*", "", regex=True)
    forn = forn.sort_values("cod_fornecedor").reset_index(drop=True)
    forn["id_fornecedor"] = forn.index + 1
    dim_fornecedor = forn[["id_fornecedor", "cod_fornecedor", "nome_fornecedor"]]

    comp = pd.DataFrame({"cod_comprador": sorted(df["Comprador"].dropna().str.strip().unique())})
    comp["id_comprador"] = comp.index + 1
    dim_comprador = comp[["id_comprador", "cod_comprador"]]

    cc = pd.read_csv(DIM_CC, sep=";", dtype={"cod_obra": str})
    cc.columns = [c.lower().replace(" ", "_") for c in cc.columns]
    obras_csv = df.drop_duplicates("Cód. Obra")[["Cód. Obra", "Obra"]]
    falt = obras_csv[~obras_csv["Cód. Obra"].isin(cc["cod_obra"])]
    if len(falt):
        prox = int(cc["id_obra"].max()) + 1
        cc = pd.concat([cc, pd.DataFrame({
            "id_obra": range(prox, prox + len(falt)), "cod_obra": falt["Cód. Obra"].to_numpy(),
            "centro_de_custo_1": falt["Obra"].str.replace(r"^\d+\s*-\s*", "", regex=True).to_numpy(),
            "origem_info": "sienge_nao_mapeado"})], ignore_index=True)
    dim_centro_custo = cc

    # ── itens / preços sintéticos ───────────────────────────────────────────
    itens = df.merge(dim_insumo[["id_insumo", "cod_insumo", "cod_detalhe", "unidade"]], on=["cod_insumo", "cod_detalhe"])
    itens = itens.drop_duplicates(["cod_pedido", "cod_insumo", "cod_detalhe"]).copy()
    itens["numero_item"] = itens.groupby("cod_pedido").cumcount() + 1
    itens["cod_fornecedor"] = itens["Cód. Fornecedor"].astype(int)
    itens["cod_obra"] = itens["Cód. Obra"]

    # itens parecidos (mesma categoria + 2 primeiras palavras + unidade) compartilham o preço-base,
    # com ±10% por insumo — assim variantes do mesmo produto têm preços comparáveis, como na vida real
    familia = (dim_insumo["categoria"] + "|" + dim_insumo["descricao_normalizada"].str.split().str[:2].str.join(" ")
               + "|" + dim_insumo["unidade_padrao"].fillna(""))
    cod_fam, uniq = pd.factorize(familia)
    base_fam = np.exp(rng.normal(3.2, 1.4, len(uniq)))
    base = pd.Series(base_fam[cod_fam] * rng.normal(1, 0.10, len(dim_insumo)).clip(0.7, 1.3),
                     index=dim_insumo["id_insumo"])
    f_forn = pd.Series(rng.choice([0.88, 0.95, 1.0, 1.05, 1.15, 1.30], len(dim_fornecedor),
                                  p=[.1, .2, .3, .2, .15, .05]), index=dim_fornecedor["cod_fornecedor"])
    f_obra = pd.Series(rng.normal(1, 0.05, len(dim_centro_custo)), index=dim_centro_custo["cod_obra"])
    meses = (itens["data_pedido"].dt.year - 2026) * 12 + itens["data_pedido"].dt.month - 1
    preco = (itens["id_insumo"].map(base) * itens["cod_fornecedor"].map(f_forn)
             * itens["cod_obra"].map(f_obra).fillna(1) * (1 + 0.006 * meses)
             * rng.normal(1, 0.06, len(itens)))
    itens["preco_unitario"] = preco.round(4).clip(lower=0.01)
    itens["preco_liquido"] = itens["preco_unitario"]
    itens["frete_unitario"] = 0.0
    itens["status_pedido"] = itens["Situação do pedido"].map(STATUS).fillna("DESCONHECIDO")
    itens["id_status"] = itens["status_pedido"].map(DIM_STATUS.set_index("status_pedido")["id_status"])
    itens["id_fornecedor"] = itens["cod_fornecedor"].map(dim_fornecedor.set_index("cod_fornecedor")["id_fornecedor"])
    itens["cod_comprador"] = itens["Comprador"].str.strip()
    itens["id_comprador"] = itens["cod_comprador"].map(dim_comprador.set_index("cod_comprador")["id_comprador"])
    itens["valor_bruto_item"] = itens["quantidade"] * itens["preco_unitario"]
    itens["valor_liquido_item"] = itens["quantidade"] * itens["preco_liquido"]
    itens["valor_frete_item"] = 0.0
    itens["valor_total_item"] = itens["valor_liquido_item"]
    itens["flag_cancelado"] = itens["status_pedido"].eq("CANCELED")
    itens["flag_autorizado"] = True
    itens["flag_preco_valido"] = ~itens["flag_cancelado"]
    itens["ano_mes"] = itens["data_pedido"].dt.strftime("%Y-%m")
    itens["cod_cotacao"] = 9000 + itens["cod_pedido"] % 700
    itens["data_carga"] = datetime.now()
    fato = itens[["id_insumo", "id_fornecedor", "id_comprador", "id_status", "cod_pedido", "numero_item",
                  "cod_obra", "cod_insumo", "cod_detalhe", "cod_fornecedor", "cod_cotacao", "data_pedido",
                  "ano_mes", "unidade", "quantidade", "preco_unitario", "preco_liquido", "frete_unitario",
                  "valor_bruto_item", "valor_liquido_item", "valor_frete_item", "valor_total_item",
                  "flag_autorizado", "flag_cancelado", "flag_preco_valido", "data_carga"]]

    ped = itens.drop_duplicates("cod_pedido")
    tot = fato.groupby("cod_pedido")["valor_total_item"].sum()
    dim_pedido = pd.DataFrame({
        "cod_pedido": ped["cod_pedido"], "numero_pedido": ped["cod_pedido"].astype(str),
        "status_pedido": ped["status_pedido"], "consistencia": "CONSISTENT", "autorizado": True,
        "cod_fornecedor": ped["cod_fornecedor"], "cod_centro_custo": pd.to_numeric(ped["cod_obra"], errors="coerce"),
        "cod_comprador": ped["cod_comprador"], "data_pedido": ped["data_pedido"],
        "condicao_pagamento": "30 dias", "valor_total_pedido": ped["cod_pedido"].map(tot),
        "observacao_interna": "MOCK - preços sintéticos",
    })
    return {"dim_status_pedido": DIM_STATUS, "dim_insumo": dim_insumo, "dim_fornecedor": dim_fornecedor,
            "dim_comprador": dim_comprador, "dim_centro_custo": dim_centro_custo, "dim_pedido": dim_pedido,
            "fato_pedido_compra_item": fato}


def gravar(tabelas: dict[str, pd.DataFrame], schema: str) -> None:
    if schema == "suprimentos":
        raise SystemExit("Recusado: 'suprimentos' é o schema REAL (carregado pela DAG). Use suprimentos_mock.")
    engine = create_engine(SETTINGS.database_url).execution_options(schema_translate_map={SCHEMA_LOGICO: schema})
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        metadata_dw.create_all(conn)
        for nome in ["dim_status_pedido", "dim_insumo", "dim_fornecedor", "dim_comprador",
                     "dim_centro_custo", "dim_pedido", "fato_pedido_compra_item"]:
            df = tabelas[nome]
            cols = [c.name for c in metadata_dw.tables[f"{SCHEMA_LOGICO}.{nome}"].columns]
            df[[c for c in df.columns if c in cols]].to_sql(nome, conn, schema=schema, if_exists="append",
                                                           index=False, chunksize=1000, method="multi")
            logger.info("  %s.%s: %d linhas", schema, nome, len(df))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema", default=SETTINGS.dw_schema)
    args = ap.parse_args()
    gravar(montar(_ler_csvs()), args.schema)
    logger.info("Mock pronto no schema %s.", args.schema)


if __name__ == "__main__":
    main()
