"""Escopo de dados do usuário: quais segmentos (verticais), obras e empresas ele vê.

Regra:
  - dimensão sem lista (None) = sem restrição naquela dimensão;
  - cada dimensão preenchida no USUÁRIO substitui a do PERFIL;
  - dataset que NÃO tem uma dimensão restrita (ex.: Curva ABC não tem obra) só é
    mostrado se `dados_sem_dimensao` estiver liberado — senão a tela fica vazia
    com o aviso de que o acesso não cobre esses dados (privilégio mínimo).
Códigos são comparados como texto de inteiro ("137"), segmentos sem acento/caixa.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import pandas as pd


def _norm_seg(v) -> str:
    return unicodedata.normalize("NFKD", str(v).strip().upper()).encode("ascii", "ignore").decode("ascii")


def _norm_cod(v) -> str:
    try:
        return str(int(float(str(v).strip())))
    except (TypeError, ValueError):
        return str(v).strip()


@dataclass(frozen=True)
class Escopo:
    segmentos: frozenset | None = None
    obras: frozenset | None = None
    empresas: frozenset | None = None
    dados_sem_dimensao: bool = True

    @property
    def irrestrito(self) -> bool:
        return self.segmentos is None and self.obras is None and self.empresas is None

    @classmethod
    def de_json(cls, perfil: dict | None, usuario: dict | None = None) -> "Escopo":
        perfil, usuario = perfil or {}, usuario or {}

        def lista(chave, norm):
            v = usuario.get(chave) if usuario.get(chave) else perfil.get(chave)
            return frozenset(norm(x) for x in v) if v else None

        globais = usuario.get("dados_sem_dimensao")
        if globais is None:
            globais = perfil.get("dados_sem_dimensao", True)
        return cls(lista("segmentos", _norm_seg), lista("obras", _norm_cod), lista("empresas", _norm_cod), bool(globais))

    def descricao(self) -> str:
        if self.irrestrito:
            return "todos os dados"
        p = []
        if self.segmentos is not None:
            p.append("segmentos " + ", ".join(sorted(self.segmentos)))
        if self.obras is not None:
            p.append("obras " + ", ".join(sorted(self.obras, key=lambda x: (len(x), x))))
        if self.empresas is not None:
            p.append("empresas " + ", ".join(sorted(self.empresas, key=lambda x: (len(x), x))))
        return " · ".join(p)


TOTAL = Escopo()


def filtrar(df: pd.DataFrame, esc: Escopo, segmento: str | None = None, obra: str | None = None,
            empresa: str | None = None) -> pd.DataFrame:
    """Aplica o escopo. Passe o NOME da coluna de cada dimensão que o dataset tem (None = não tem)."""
    if esc.irrestrito or df is None or df.empty:
        return df
    m = pd.Series(True, index=df.index)
    for valores, coluna, norm in ((esc.segmentos, segmento, _norm_seg), (esc.obras, obra, _norm_cod),
                                  (esc.empresas, empresa, _norm_cod)):
        if valores is None:
            continue
        if coluna is None or coluna not in df:
            if not esc.dados_sem_dimensao:
                return df.iloc[0:0]
            continue
        col = df[coluna]
        m &= col.notna() & col.map(norm).isin(valores)
    return df[m]


def cobre_dataset(esc: Escopo, segmento: bool = False, obra: bool = False, empresa: bool = False) -> bool:
    """True se o dataset (com as dimensões indicadas) pode ser mostrado para esse escopo."""
    if esc.irrestrito or esc.dados_sem_dimensao:
        return True
    return ((esc.segmentos is None or segmento) and (esc.obras is None or obra)
            and (esc.empresas is None or empresa))
