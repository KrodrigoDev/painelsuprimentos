"""
Normalização de descrições de insumos.

Regras:
  - a descrição ORIGINAL nunca é alterada (auditoria); aqui só se produz o
    texto CANÔNICO usado na comparação;
  - números, medidas, frações, códigos e marcas são PRESERVADOS — só a
    grafia é padronizada ("1,5mm²" -> "1.5 mm2", "3/4''" -> "3/4 pol");
  - abreviações/sinônimos vêm de um vocabulário padrão + entradas do
    usuário (tabela painel.vocabulario), aplicado por palavra inteira.
"""
from __future__ import annotations

import re
import unicodedata

# ── Vocabulário padrão (termo -> forma canônica). Expansível pela tela de
#    Correspondências (painel.vocabulario), que tem prioridade sobre este.
VOCABULARIO_PADRAO: dict[str, str] = {
    # conectores
    # materiais / processos
    "sold": "soldavel", "sold.": "soldavel", "galv": "galvanizado", "galvaniz": "galvanizado",
    "flex": "flexivel", "esg": "esgoto", "inox": "inox", "aco": "aco",
    "cpvc": "cpvc", "ppr": "ppr", "pead": "pead", "fofo": "ferro fundido",
    "portiland": "portland", "portlan": "portland",
    "ceramico": "ceramico", "ceram": "ceramico", "porc": "porcelanato",
    "ret": "retificado", "retif": "retificado",
    "ref": "referencia", "mod": "modelo",
    # formas / apresentação
    "brs": "barra", "pc": "peca", "pç": "peca", "pca": "peca", "pcs": "peca",
    "und": "un", "unid": "un", "unidade": "un", "unidades": "un",
    "cx": "caixa", "sc": "saco", "pct": "pacote", "rl": "rolo", "gl": "galao", "lt": "l",
    "tb": "tubo", "cj": "conjunto", "jg": "jogo",
    # elétrica
    "monofasico": "monopolar", "unipolar": "monopolar", "bifasico": "bipolar", "trifasico": "tripolar",
    "cabo flexivel": "cabo flexivel",
    # unidades escritas por extenso
    "metros": "m", "metro": "m", "mts": "m", "mt": "m", "mtrs": "m",
    "milimetros": "mm", "milimetro": "mm", "centimetros": "cm", "centimetro": "cm",
    "litros": "l", "litro": "l", "lts": "l", "kgs": "kg", "quilos": "kg", "gramas": "g",
    "polegada": "pol", "polegadas": "pol",
}

# palavras que não ajudam a diferenciar materiais (não entram nos tokens)
STOPWORDS = {
    "de", "da", "do", "das", "dos", "e", "em", "para", "com", "sem", "a", "o", "as", "os", "tipo",
    "nbr", "im", "ap", "mo", "ref", "referencia", "modelo", "cor", "linha", "marca", "ou", "x", "graus",
}

_RE_TIPO = re.compile(r"^\s*(im|mo|ap|m0|mt)\s*-\s*", re.I)
_RE_NBR = re.compile(r"\(?\bnbr\s*(?:nm\s*|iso\s*)?\d{3,5}(?:-\d+)?(?:\s*(?:e|/|,)\s*(?:nbr\s*)?\d{3,5}(?:-\d+)?)*\s*\)?", re.I)


def remover_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def tipo_insumo(descricao: str) -> str | None:
    """'IM - Papel' -> 'IM' (material), MO (mão de obra), AP (apropriação)."""
    m = _RE_TIPO.match(descricao or "")
    return m.group(1).upper().replace("M0", "MO") if m else None


def preparar(descricao: str) -> str:
    """Passo 1: minúsculas, sem acento, símbolos de medida padronizados (sem vocabulário)."""
    t = descricao or ""
    t = _RE_TIPO.sub("", t)
    t = t.replace("²", "2").replace("³", "3").replace("º", "o").replace("°", "o").replace("Ø", " diam ").replace("ø", " diam ")
    t = remover_acentos(t).lower()
    t = re.sub(r"\b([cps])/\s*", lambda m: {"c": " com ", "p": " para ", "s": " sem "}[m.group(1)], t)
    t = re.sub(r"(\d)\s*(lts|lt|litros|litro)\b", r"\1 l", t)
    t = re.sub(r"(\d)\s*(''|\"|”|“|pol\b)", r"\1 pol ", t)          # 3/4'' -> 3/4 pol
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)                             # 1,5 -> 1.5
    t = re.sub(r"\b(\d+)\.(\d{1,2})/(2|4|8|16|32|64)(?!\d)", r"\1 \2/\3", t)  # 1.1/2 -> 1 1/2 (bitola em pol)
    t = re.sub(r"\bm\s*2\b|\bm2\b", " m2 ", t)
    t = re.sub(r"\bm\s*3\b|\bm3\b", " m3 ", t)
    t = re.sub(r"(\d)\s*mm\s*2\b", r"\1 mm2 ", t)
    t = re.sub(r"\bd\s*=\s*(\d)", r"dn \1", t)                       # d=75mm -> dn 75mm
    t = re.sub(r"\bde\s*(\d)", r"de \1", t)
    # separa número de unidade colado: 25mm -> 25 mm ; 6m -> 6 m ; 20kg -> 20 kg
    t = re.sub(r"(\d)\s*o\b", r"\1 graus", t)                          # 90o (de 90°) -> 90 graus
    t = re.sub(r"(\d)(mm2|mm|cm|m2|m3|m|kg|g|ml|l|v|kv|kva|va|a|ka|w|kw|cv|hp|mpa|pol)(?=\b|x\d)", r"\1 \2", t)
    # x entre números (dimensões): 09x19x19 / 2.45 x 6.00
    t = re.sub(r"(\d)\s*[x×*]\s*(?=\d)", r"\1 x ", t)
    t = re.sub(r"[^a-z0-9./+ x-]+", " ", t)
    t = re.sub(r"(?<![\d])[.\-/]|[.\-/](?![\d])", " ", t)          # pontuação fora de número
    return re.sub(r"\s+", " ", t).strip()


def aplicar_vocabulario(texto: str, vocabulario: dict[str, str] | None = None) -> str:
    voc = {**VOCABULARIO_PADRAO, **(vocabulario or {})}
    # termos com mais de uma palavra primeiro
    for termo in sorted((k for k in voc if " " in k), key=len, reverse=True):
        texto = re.sub(rf"\b{re.escape(termo)}\b", voc[termo], texto)
    return " ".join(voc.get(p, p) for p in texto.split())


def canonico(descricao: str, vocabulario: dict[str, str] | None = None) -> str:
    """Texto canônico completo (o que é comparado)."""
    t = preparar(descricao)
    t = _RE_NBR.sub(" ", t) if "nbr" in t else t
    return re.sub(r"\s+", " ", aplicar_vocabulario(t, vocabulario)).strip()


def tokens(texto_canonico: str) -> list[str]:
    """Tokens informativos (sem stopwords; números e medidas preservados)."""
    return [p for p in texto_canonico.split() if p not in STOPWORDS and len(p) > 0]
