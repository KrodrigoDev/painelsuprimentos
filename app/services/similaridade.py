"""
Busca de insumos similares, SEMPRE dentro de uma categoria.

Por que por categoria:
  - leveza: cada categoria tem de dezenas a ~2 mil insumos, então os índices
    são pequenos, ficam em memória e a busca responde em milissegundos;
  - precisão: "saco" e "aço" nunca disputam o mesmo resultado, porque
    ficam em categorias diferentes.

Score (0 a 1) = combinação de três sinais complementares:
  - 0.50 · TF-IDF de PALAVRAS (1-2 gramas): pesa termos raros e informativos
          ("cp ii", "50kg"); termos comuns ("de", "para") pesam pouco;
  - 0.30 · TF-IDF de CARACTERES (3-5 gramas, dentro da palavra): tolera
          erro de digitação, abreviação e plural ("parafuso" ~ "parafusos");
  - 0.20 · rapidfuzz token_set_ratio: robusto a ordem das palavras
          ("tubo pvc 50mm" ~ "pvc tubo 50 mm").
Medidas (números) que aparecem na consulta e NÃO aparecem no insumo
reduzem o score (ex.: buscar "cabo 2,5mm" não deve trazer "cabo 10mm" no
topo), via PENALIDADE_NUMERO por número ausente.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process
from sklearn.feature_extraction.text import TfidfVectorizer

from app.config import SETTINGS
from app.repositories import suprimentos_repo
from app.services.texto import normalizar_texto

PESO_PALAVRA, PESO_CARACTER, PESO_FUZZY = 0.50, 0.30, 0.20
PENALIDADE_NUMERO = 0.12
_RE_NUMERO = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class _IndiceCategoria:
    insumos: pd.DataFrame          # linhas da categoria (reset_index)
    vet_palavra: TfidfVectorizer
    vet_caracter: TfidfVectorizer
    mat_palavra: object            # sparse (n_insumos x vocab), L2-normalizada
    mat_caracter: object
    textos: list[str]


def _numeros(texto: str) -> set[str]:
    return set(_RE_NUMERO.findall(texto))


class IndiceSimilaridade:
    """Índices TF-IDF por categoria, construídos sob demanda e mantidos em cache."""

    def __init__(self, ttl_minutos: int = SETTINGS.cache_minutos):
        self._ttl = ttl_minutos * 60
        self._lock = threading.Lock()
        self._carregado_em = 0.0
        self._insumos: pd.DataFrame | None = None
        self._indices: dict[str, _IndiceCategoria] = {}

    # ── dados base ──────────────────────────────────────────────────────────
    def insumos(self) -> pd.DataFrame:
        with self._lock:
            if self._insumos is None or time.monotonic() - self._carregado_em > self._ttl:
                df = suprimentos_repo.insumos_com_compra()
                df["descricao_normalizada"] = df["descricao_normalizada"].fillna(
                    df["descricao_completa"].map(normalizar_texto))
                self._insumos = df
                self._indices = {}
                self._carregado_em = time.monotonic()
            return self._insumos

    def categorias(self) -> pd.DataFrame:
        """Categorias com nº de insumos e gasto total (para o dropdown)."""
        return (self.insumos().groupby("categoria", as_index=False)
                .agg(n_insumos=("id_insumo", "size"), total_gasto=("total_gasto", "sum"))
                .sort_values("categoria"))

    def limpar_cache(self) -> None:
        with self._lock:
            self._insumos = None
            self._indices = {}

    # ── índice por categoria ────────────────────────────────────────────────
    def _indice(self, categoria: str) -> _IndiceCategoria | None:
        insumos = self.insumos()
        if categoria in self._indices:
            return self._indices[categoria]
        sub = insumos[insumos["categoria"] == categoria].reset_index(drop=True)
        if sub.empty:
            return None
        textos = sub["descricao_normalizada"].tolist()
        vp = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), token_pattern=r"(?u)\b[\w.]+\b",
                             sublinear_tf=True, min_df=1)
        vc = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1)
        idx = _IndiceCategoria(sub, vp, vc, vp.fit_transform(textos), vc.fit_transform(textos), textos)
        with self._lock:
            self._indices[categoria] = idx
        return idx

    # ── busca ───────────────────────────────────────────────────────────────
    def buscar(
            self,
            consulta: str,
            categoria: str,
            top_n: int = 30,
            score_minimo: float = 0.35,
            unidade: str | None = None,
    ) -> pd.DataFrame:
        """
        Retorna os insumos da `categoria` mais parecidos com `consulta`,
        ordenados por score (desc). Colunas extras: score, numeros_ausentes.
        """
        q = normalizar_texto(consulta)
        idx = self._indice(categoria)
        if not q or idx is None:
            return pd.DataFrame()

        s_pal = (idx.mat_palavra @ idx.vet_palavra.transform([q]).T).toarray().ravel()
        s_car = (idx.mat_caracter @ idx.vet_caracter.transform([q]).T).toarray().ravel()
        s_fuz = np.array([r for r in process.cdist([q], idx.textos, scorer=fuzz.token_set_ratio)[0]]) / 100.0
        score = PESO_PALAVRA * s_pal + PESO_CARACTER * s_car + PESO_FUZZY * s_fuz

        nums_q = _numeros(q)
        if nums_q:
            ausentes = np.array([len(nums_q - _numeros(t)) for t in idx.textos])
            score = score - PENALIDADE_NUMERO * ausentes
        else:
            ausentes = np.zeros(len(idx.textos), dtype=int)

        res = idx.insumos.assign(score=np.clip(score, 0, 1).round(4), numeros_ausentes=ausentes)
        if unidade:
            res = res[res["unidade_padrao"] == unidade]
        res = res[res["score"] >= score_minimo]
        return res.sort_values(["score", "total_gasto"], ascending=[False, False]).head(top_n).reset_index(drop=True)

    def sugerir(self, texto: str, limite: int = 15) -> pd.DataFrame:
        """Autocomplete em TODAS as categorias (para descobrir a categoria do item)."""
        q = normalizar_texto(texto)
        ins = self.insumos()
        if len(q) < 2 or ins.empty:
            return pd.DataFrame()
        achados = process.extract(q, ins["descricao_normalizada"].tolist(), scorer=fuzz.WRatio, limit=limite * 3)
        linhas = ins.iloc[[i for _, _, i in achados]].assign(score=[s / 100 for _, s, _ in achados])
        return linhas.sort_values(["score", "total_gasto"], ascending=False).head(limite)


INDICE = IndiceSimilaridade()
