"""
Pontuação 0-100 de um PAR de insumos + nível de confiança.

    score = 100 × Σ peso_i × componente_i        (pesos em config.py)

Componentes (0..1): texto (edição), tokens (ordem/Jaccard), tfidf (caracteres),
atributos (compatibilidade técnica), unidade (mesma / conversível / outra).

Níveis:
    incompativel   conflito técnico crítico — NUNCA comparado (independe do score)
    nao_comparavel sem conflito, mas unidade/embalagem impedem comparar preço
    alta           score >= faixa_alta, sem divergência parcial em atributo crítico
    media          score >= faixa_media (ou alta com divergência parcial) -> revisão humana
    baixa          abaixo -> não usado em comparações
Aprovação automática: só `alta` E (mesmos tokens OU ≥1 atributo crítico idêntico e texto ≥ 0.85).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.matching import atributos as atr
from app.matching.config import CONFIG, ConfigMatching
from app.matching.normalizacao import tokens
from app.matching.unidades import fator

INCOMPATIVEL, NAO_COMPARAVEL, ALTA, MEDIA, BAIXA = "incompativel", "nao_comparavel", "alta", "media", "baixa"
ORDEM_NIVEL = {ALTA: 0, MEDIA: 1, NAO_COMPARAVEL: 2, BAIXA: 3, INCOMPATIVEL: 4}


@dataclass
class PerfilInsumo:
    chave: str                    # "cod_insumo|cod_detalhe" (chave natural, estável entre cargas)
    id_insumo: int
    descricao: str                # ORIGINAL (auditoria)
    categoria: str
    unidade: str | None
    atributos: atr.Atributos
    tokens: frozenset = field(default_factory=frozenset)

    @property
    def canonico(self) -> str:
        return self.atributos.canonico


def perfil(chave, id_insumo, descricao, categoria, unidade, vocabulario=None) -> PerfilInsumo:
    a = atr.extrair(descricao, vocabulario)
    return PerfilInsumo(chave, int(id_insumo), descricao, categoria, unidade, a, frozenset(tokens(a.canonico)))


@dataclass
class ResultadoPar:
    score: float
    nivel: str
    auto_aprovavel: bool
    componentes: dict
    comparacao: dict
    unidade: dict
    motivos: list[str]

    def as_dict(self) -> dict:
        return {"score": self.score, "nivel": self.nivel, "auto_aprovavel": self.auto_aprovavel,
                "componentes": self.componentes, "comparacao": self.comparacao, "unidade": self.unidade,
                "motivos": self.motivos}


def _trigramas(t: str) -> set[str]:
    t = f"  {t} "
    return {t[i:i + 3] for i in range(len(t) - 2)}


def pontuar(a: PerfilInsumo, b: PerfilInsumo, tfidf: float | None = None,
            cfg: ConfigMatching = CONFIG) -> ResultadoPar:
    ca, cb = a.canonico, b.canonico
    jacc = len(a.tokens & b.tokens) / len(a.tokens | b.tokens) if (a.tokens | b.tokens) else 0.0
    ta, tb = " ".join(sorted(a.tokens)), " ".join(sorted(b.tokens))
    comp_tokens = 0.5 * max(fuzz.token_set_ratio(ta, tb), fuzz.token_sort_ratio(ta, tb)) / 100 + 0.5 * jacc
    if tfidf is None:
        g1, g2 = _trigramas(ca), _trigramas(cb)
        tfidf = len(g1 & g2) / len(g1 | g2) if (g1 | g2) else 0.0
    cmp = atr.comparar(a.atributos, b.atributos, a.unidade, b.unidade)

    # unidade: igual / conversível (em qualquer direção) / incompatível
    conv = fator(a.unidade, b.unidade, a.atributos) or fator(b.unidade, a.unidade, b.atributos)
    if a.unidade and a.unidade == b.unidade:
        comp_unid, regra_unid = 1.0, "mesma unidade"
    elif conv:
        comp_unid, regra_unid = 0.8, conv[1]
    else:
        comp_unid, regra_unid = 0.0, f"{a.unidade or '?'} x {b.unidade or '?'} sem conversão conhecida"

    comp = {"texto": fuzz.ratio(ca, cb) / 100, "tokens": comp_tokens, "tfidf": float(tfidf),
            "atributos": cmp.score, "unidade": comp_unid}
    score = round(100 * sum(cfg.pesos[k] * v for k, v in comp.items()), 1)

    criticos_parciais = [p for p in cmp.parciais
                         if (a.atributos.grupos.get(p) or b.atributos.grupos.get(p)) == atr.CRITICO]
    # o nome do material (tipo_material) é igual em quase todo candidato: não conta como evidência técnica
    criticos_iguais = [p for p in cmp.iguais
                       if (a.atributos.grupos.get(p) or b.atributos.grupos.get(p)) == atr.CRITICO
                       and p != "tipo_material"]
    motivos = []
    if cmp.conflitos:
        nivel = INCOMPATIVEL
        motivos += [f"conflito técnico: {c['atributo']} ({c['a']} x {c['b']})" for c in cmp.conflitos]
    elif comp_unid == 0.0 or cmp.embalagem:
        nivel = NAO_COMPARAVEL
        if comp_unid == 0.0:
            motivos.append(f"unidade: {regra_unid}")
        motivos += [f"embalagem diferente: {e['atributo']} ({e['a']} x {e['b']})" for e in cmp.embalagem]
    elif score >= cfg.faixa_alta and not criticos_parciais:
        nivel = ALTA
    elif score >= cfg.faixa_media:
        nivel = MEDIA
        if criticos_parciais:
            motivos.append("atributo crítico só em uma descrição: " + ", ".join(criticos_parciais))
    else:
        nivel = BAIXA
    if cmp.informativos:
        motivos.append("diferem em: " + ", ".join(cmp.informativos))
    # descrição genérica ("CAMISA", "SERVIÇO", "PARAFUSO"): pouca informação para afirmar equivalência
    informativos_a = {w for w in a.tokens if w.isalpha() and len(w) > 2}
    informativos_b = {w for w in b.tokens if w.isalpha() and len(w) > 2}
    generica = min(len(informativos_a), len(informativos_b)) < 2 and not criticos_iguais
    if generica and nivel == ALTA:
        nivel = MEDIA
        motivos.append("descrição genérica: confirmar se é o mesmo material")
    if a.categoria != b.categoria:
        motivos.append("categorias diferentes")
        if nivel == ALTA:
            nivel = MEDIA

    embalagem_parcial = [p for p in cmp.parciais
                         if (a.atributos.grupos.get(p) or b.atributos.grupos.get(p)) == atr.EMBALAGEM]
    if nivel == ALTA and (embalagem_parcial or "numeros" in cmp.parciais):
        nivel = MEDIA
        motivos.append("apresentação/números só em uma descrição: " + ", ".join(embalagem_parcial + (
            ["numeros"] if "numeros" in cmp.parciais else [])))
    # palavras exclusivas dos DOIS lados (ex.: "1 aba" x "fechado tubular") = variantes -> revisão
    _neutras = atr.CORES | atr.MARCAS | {"claro", "escuro", "cor"}
    so_a = {w for w in a.tokens - b.tokens if not w[0].isdigit() and w not in _neutras}
    so_b = {w for w in b.tokens - a.tokens if not w[0].isdigit() and w not in _neutras}
    exclusivas = (a.tokens ^ b.tokens) - atr.CORES - atr.MARCAS
    linha_comercial = (" linha " in f" {a.canonico} ") != (" linha " in f" {b.canonico} ")
    # códigos/siglas exclusivos de um lado (ex.: "m16", "46", "dr", "out") mudam o produto
    com_codigo = any(any(ch.isdigit() for ch in w) or len(w) <= 3 for w in exclusivas
                     if w not in ("com", "sem", "para", "claro", "escuro"))
    variantes_dos_dois_lados = bool(so_a) and bool(so_b)
    # mesmos termos descontando cor/marca (ex.: cabo 2,5 mm² azul x vermelho)
    sem_cor_a = {w for w in a.tokens if w not in atr.CORES and w not in atr.MARCAS and w != "claro" and w != "escuro"}
    sem_cor_b = {w for w in b.tokens if w not in atr.CORES and w not in atr.MARCAS and w != "claro" and w != "escuro"}
    mesmos_termos = sem_cor_a == sem_cor_b and len({w for w in sem_cor_a if w.isalpha() and len(w) > 2}) >= 2
    auto = nivel == ALTA and not variantes_dos_dois_lados and not com_codigo and not linha_comercial and not (so_a | so_b) and (
        jacc == 1.0 or mesmos_termos or (criticos_iguais and comp["texto"] >= 0.85))
    return ResultadoPar(score, nivel, bool(auto), {k: round(v, 4) for k, v in comp.items()},
                        cmp.resumo(), {"a": a.unidade, "b": b.unidade, "regra": regra_unid}, motivos)
