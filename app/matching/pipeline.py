"""
Pipeline de correspondência (em lote, incremental).

  1. perfis: normaliza descrições e extrai atributos (descrição original preservada)
  2. candidatos: SÓ dentro da mesma categoria; vizinhos por TF-IDF de caracteres
     (top-K por insumo, cosseno mínimo) + pares com texto canônico idêntico
     -> evita o produto cartesiano (12 mil insumos ≈ 70 milhões de pares)
  3. pontuação + nível de confiança (pontuacao.pontuar)
  4. decisões já registradas no catálogo (aprovado/rejeitado) prevalecem
  5. grupos de material: só pares aprovados (humano) ou auto-aprováveis, sem
     permitir que a transitividade junte itens tecnicamente conflitantes

Funções puras (sem banco): o acesso ao Postgres fica em repositories/catalogo_repo.py.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from app.matching import atributos as atr
from app.matching.config import CONFIG, ConfigMatching
from app.matching.pontuacao import PerfilInsumo, perfil, pontuar


def chave_insumo(cod_insumo, cod_detalhe) -> str:
    return f"{int(cod_insumo)}|{int(cod_detalhe or 0)}"


def hash_par(a: PerfilInsumo, b: PerfilInsumo) -> str:
    base = f"{a.descricao}\x1f{a.unidade}\x1f{a.categoria}\x1e{b.descricao}\x1f{b.unidade}\x1f{b.categoria}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def construir_perfis(insumos: pd.DataFrame, vocabulario: dict | None = None) -> dict[str, PerfilInsumo]:
    """insumos: id_insumo, cod_insumo, cod_detalhe, descricao_completa, categoria, unidade_padrao."""
    perfis = {}
    for r in insumos.itertuples(index=False):
        ch = chave_insumo(r.cod_insumo, r.cod_detalhe)
        perfis[ch] = perfil(ch, r.id_insumo, r.descricao_completa or "", r.categoria or "SEM CATEGORIA",
                            r.unidade_padrao, vocabulario)
    return perfis


def gerar_candidatos(perfis: dict[str, PerfilInsumo], cfg: ConfigMatching = CONFIG) -> list[tuple[str, str, float]]:
    """(chave_a, chave_b, cosseno_tfidf) com chave_a < chave_b, só dentro da categoria."""
    df = pd.DataFrame([(p.chave, p.categoria, p.canonico) for p in perfis.values()],
                      columns=["chave", "categoria", "canonico"])
    pares: dict[tuple[str, str], float] = {}
    for _, sub in df.groupby("categoria"):
        if len(sub) < 2:
            continue
        chaves, textos = sub["chave"].to_numpy(), sub["canonico"].fillna("").to_numpy()
        vet = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        try:
            m = vet.fit_transform(textos)
        except ValueError:
            continue
        sim = (m @ m.T).toarray() if len(sub) <= 4000 else None
        k = min(cfg.candidatos_por_insumo, len(sub) - 1)
        for i in range(len(sub)):
            linha = sim[i] if sim is not None else (m[i] @ m.T).toarray().ravel()
            linha[i] = -1
            idx = np.argpartition(-linha, k - 1)[:k] if k > 0 else []
            for j in idx:
                s = float(linha[j])
                if s < cfg.tfidf_minimo_candidato and textos[i] != textos[j]:
                    continue
                a, b = sorted((chaves[i], chaves[j]))
                pares[(a, b)] = max(pares.get((a, b), 0.0), s)
        # textos canônicos idênticos sempre viram candidatos
        for _, g in sub.groupby("canonico"):
            ch = sorted(g["chave"])
            for x in range(len(ch)):
                for y in range(x + 1, len(ch)):
                    pares[(ch[x], ch[y])] = 1.0
    return [(a, b, s) for (a, b), s in pares.items()]


@dataclass
class ParCalculado:
    chave_a: str
    chave_b: str
    hash: str
    resultado: dict


def pontuar_candidatos(perfis, candidatos, cfg: ConfigMatching = CONFIG) -> list[ParCalculado]:
    out = []
    for a, b, cos in candidatos:
        pa, pb = perfis[a], perfis[b]
        out.append(ParCalculado(a, b, hash_par(pa, pb), pontuar(pa, pb, tfidf=cos, cfg=cfg).as_dict()))
    return out


class _UF:
    def __init__(self, itens):
        self.pai = {i: i for i in itens}
        self.membros = {i: {i} for i in itens}

    def achar(self, x):
        while self.pai[x] != x:
            self.pai[x] = self.pai[self.pai[x]]
            x = self.pai[x]
        return x

    def unir(self, a, b):
        ra, rb = self.achar(a), self.achar(b)
        if ra == rb:
            return
        if len(self.membros[ra]) < len(self.membros[rb]):
            ra, rb = rb, ra
        self.pai[rb] = ra
        self.membros[ra] |= self.membros.pop(rb)


def formar_grupos(perfis: dict[str, PerfilInsumo], pares_validos: list[tuple[str, str, float]]) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """
    pares_validos: (a, b, score) aprovados por humano ou auto-aprováveis.
    Une do par de MAIOR score para o menor; antes de unir dois grupos, checa
    conflito técnico entre TODOS os membros (evita A~B, B~C com A x C incompatíveis).
    Retorna ({chave: chave_grupo}, [(a, b, motivo)] de uniões recusadas).
    """
    uf = _UF(perfis.keys())
    recusados = []
    for a, b, _ in sorted(pares_validos, key=lambda x: -x[2]):
        ra, rb = uf.achar(a), uf.achar(b)
        if ra == rb:
            continue
        conflito = None
        for x in uf.membros[ra]:
            for y in uf.membros[rb]:
                c = atr.comparar(perfis[x].atributos, perfis[y].atributos, perfis[x].unidade, perfis[y].unidade)
                if c.conflitos:
                    conflito = f"{x} x {y}: " + "; ".join(f"{k['atributo']} {k['a']}≠{k['b']}" for k in c.conflitos)
                    break
            if conflito:
                break
        if conflito:
            recusados.append((a, b, conflito))
        else:
            uf.unir(a, b)
    return {k: uf.achar(k) for k in perfis}, recusados
