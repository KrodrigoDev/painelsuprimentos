"""
Parâmetros do motor de correspondência — VERSIONADOS.

Toda decisão automática grava `VERSAO_REGRAS`. Ao mudar pesos, faixas ou
regras de extração, suba a versão: pares automáticos são recalculados na
próxima execução; decisões humanas são preservadas (e sinalizadas se a
descrição dos insumos mudou).

Os valores podem ser sobrescritos sem mexer no código criando
`config_matching.json` na raiz do projeto, ex.:
    {"pesos": {"atributos": 0.35, "tokens": 0.20}, "faixa_alta": 88}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

VERSAO_REGRAS = "2026.10.1"
_ARQ_OVERRIDE = Path(__file__).resolve().parents[2] / "config_matching.json"


@dataclass(frozen=True)
class ConfigMatching:
    # Pesos da pontuação (somam 1.0)
    pesos: dict = field(default_factory=lambda: {
        "texto": 0.15,      # rapidfuzz ratio (edição) sobre o texto canônico
        "tokens": 0.25,     # max(token_set, token_sort) + Jaccard
        "tfidf": 0.20,      # cosseno TF-IDF de caracteres (3-5) — tolera abreviação/erro
        "atributos": 0.30,  # compatibilidade dos atributos técnicos extraídos
        "unidade": 0.10,    # mesma unidade (1), conversível (0.8), outra (0)
    })
    faixa_alta: float = 85.0     # >= alta (se sem conflito/parcial e unidade comparável)
    faixa_media: float = 65.0    # >= média ; abaixo = baixa
    # geração de candidatos (por categoria)
    candidatos_por_insumo: int = 12
    tfidf_minimo_candidato: float = 0.30
    versao: str = VERSAO_REGRAS


def carregar_config() -> ConfigMatching:
    cfg = ConfigMatching()
    if _ARQ_OVERRIDE.exists():
        dados = json.loads(_ARQ_OVERRIDE.read_text(encoding="utf-8"))
        pesos = {**cfg.pesos, **dados.pop("pesos", {})}
        cfg = replace(cfg, pesos=pesos, **{k: v for k, v in dados.items() if hasattr(cfg, k)})
    total = sum(cfg.pesos.values())
    if abs(total - 1) > 1e-6:
        cfg = replace(cfg, pesos={k: v / total for k, v in cfg.pesos.items()})
    return cfg


CONFIG = carregar_config()
