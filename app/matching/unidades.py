"""
Unidades de medida: padronização e conversões SEGURAS.

Só converte quando a relação é conhecida e rastreável:
  - fixa e universal: t <-> kg (1000), l <-> ml, m <-> cm/mm;
  - pela apresentação EXTRAÍDA da descrição: saco de 50 kg -> R$/kg,
    barra de 6 m -> R$/m, caixa com 100 un -> R$/un, lata de 18 l -> R$/l,
    caixa com 2,03 m² -> R$/m².
Nada de presumir que caixa = unidade ou saco = kg sem a composição.
Se não der para converter, a comparação é marcada como "não diretamente comparável".
"""
from __future__ import annotations

from app.matching.atributos import Atributos

PADRAO = {
    "und": "un", "unid": "un", "unid.": "un", "un.": "un", "pc": "un", "pç": "un", "peca": "un", "peça": "un",
    "m²": "m2", "m^2": "m2", "m³": "m3", "m^3": "m3", "lt": "l", "litro": "l", "mês": "mes", "ton": "t",
    "pr": "par", "rol": "rl", "unxmes": "mes", "un x mes": "mes", "mes x un": "mes", "m3xmes": "m3 x mes", "saco": "sc", "barra": "br", "caixa": "cx", "pacote": "pct", "galao": "gl",
}
FIXAS = {("t", "kg"): 1000.0, ("kg", "t"): 0.001, ("l", "ml"): 1000.0, ("ml", "l"): 0.001,
         ("m", "cm"): 100.0, ("cm", "m"): 0.01, ("m", "mm"): 1000.0, ("mm", "m"): 0.001}
# unidade de compra (contagem) -> (unidade-base, atributo da apresentação que dá o fator)
POR_APRESENTACAO = {
    ("sc", "kg"): "peso_kg", ("un", "kg"): "peso_kg", ("bd", "kg"): "peso_kg", ("lata", "kg"): "peso_kg",
    ("gl", "l"): "volume_l", ("lata", "l"): "volume_l", ("bd", "l"): "volume_l", ("un", "l"): "volume_l",
    ("br", "m"): "comprimento_m", ("un", "m"): "comprimento_m", ("rl", "m"): "comprimento_m",
    ("cx", "un"): "qtd_embalagem", ("pct", "un"): "qtd_embalagem",
    ("cx", "m2"): "area_m2", ("un", "m2"): "area_m2",
}


def padronizar(unidade: str | None) -> str | None:
    if unidade is None:
        return None
    u = str(unidade).strip().lower()
    return PADRAO.get(u, u)


def fator(unidade_compra: str | None, destino: str | None, atributos: Atributos | None) -> tuple[float, str] | None:
    """
    Fator F tal que  preço_na_unidade_destino = preço_na_unidade_de_compra / F
    (ex.: saco de 50 kg -> F=50). Retorna (F, regra_textual) ou None se não houver
    relação segura.
    """
    o, d = padronizar(unidade_compra), padronizar(destino)
    if not o or not d:
        return None
    if o == d:
        return 1.0, "mesma unidade"
    if (o, d) in FIXAS:
        return 1 / FIXAS[(o, d)], f"conversão fixa {o}->{d}"
    attr = POR_APRESENTACAO.get((o, d))
    if attr and atributos is not None:
        valor = atributos.valores.get(attr)
        if isinstance(valor, frozenset) and len(valor) == 1:
            f = float(next(iter(valor)))
            if f > 0:
                return f, f"{o} com {f:g} {d} (extraído da descrição)"
    return None
