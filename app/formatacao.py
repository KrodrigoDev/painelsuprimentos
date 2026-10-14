"""Formatação pt-BR (moeda, números, %) usada em serviços e telas."""
from __future__ import annotations

import math


def _br(v: float, casas: int) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def brl(v, casas: int | None = None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if casas is None:
        casas = 4 if abs(v) < 10 and v != 0 else 2
    return f"R$ {_br(float(v), casas)}"


def brl_curto(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    a = abs(v)
    if a >= 1e6:
        return f"R$ {_br(v / 1e6, 2)} mi"
    if a >= 1e3:
        return f"R$ {_br(v / 1e3, 1)} mil"
    return brl(v, 2)


def num(v, casas: int = 0) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return _br(float(v), casas)


def pct(v, casas: int = 1) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{_br(float(v), casas)}%"


