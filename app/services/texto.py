"""Normalização de texto — MESMA regra do ETL (pedidos_compra_transformer_2.normalizar_texto),
para que a consulta digitada no painel e a descricao_normalizada do DW batam."""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd


def normalizar_texto(texto) -> str:
    """minúsculas, sem acento, só [a-z0-9] separados por 1 espaço (ponto só dentro de número)."""
    if texto is None or texto is pd.NA or (isinstance(texto, float) and np.isnan(texto)):
        return ""
    texto = unicodedata.normalize("NFKD", str(texto).lower()).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"(\d),(\d)", r"\1.\2", texto)
    texto = re.sub(r"[^a-z0-9.]+", " ", texto)
    texto = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()
