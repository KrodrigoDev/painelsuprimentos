"""
Extração de atributos técnicos e verificação de compatibilidade.

A extração trabalha sobre o texto canônico (normalizacao.canonico). Cada
atributo pertence a um GRUPO que define o efeito de uma divergência:

  CRITICO     -> identidade do material (diâmetro, bitola, classe, MPa,
                 código de tela, curva/polos/corrente...). Valores diferentes
                 = CONFLITO TÉCNICO: o par nunca é usado em comparação de
                 preço, qualquer que seja a pontuação textual.
  EMBALAGEM   -> apresentação comercial (kg/saco, litros/lata, metros/barra,
                 unidades/caixa). Diferença só importa quando a unidade de
                 compra é de CONTAGEM (un, sc, cx, br...): o preço por saco
                 de 25 kg não se compara ao de 50 kg. Se a unidade de compra
                 for a própria medida (kg, l, m) a embalagem não interfere.
  INFORMATIVO -> cor, marca, números soltos: reduzem a pontuação, não bloqueiam.

Conjuntos de medidas (ex.: "DN50/DE60" x "DN 50") são compatíveis quando um
contém o outro — vira divergência PARCIAL, que impede confiança alta.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction

from app.matching.normalizacao import canonico

CRITICO, EMBALAGEM, INFORMATIVO = "critico", "embalagem", "informativo"
NUMEROS = "numeros"   # números livres: disjuntos = conflito; um contido no outro = parcial
UNIDADES_CONTAGEM = {"un", "sc", "saco", "cx", "caixa", "pct", "pacote", "br", "barra", "pc", "peca", "rl", "rolo",
                     "gl", "galao", "lata", "bd", "balde", "fd", "fardo", "cj", "conjunto", "jg", "jogo", "par",
                     "tb", "tubo", "kit", "res", "resma", "ct", "cento", "mil", "fl", "folha", "tam"}

CORES = {"branco", "branca", "preto", "preta", "azul", "vermelho", "vermelha", "verde", "amarelo", "amarela",
         "cinza", "marrom", "laranja", "rosa", "roxo", "bege", "marfim", "grafite", "prata", "dourado",
         "transparente", "incolor", "palha", "creme", "vm", "vd", "az", "pt", "am"}
MARCAS = {"tigre", "amanco", "krona", "fortlev", "votorantim", "votoran", "nacional", "itambe", "cauê", "caue",
          "quartzolit", "votomassa", "suvinil", "coral", "sherwin", "eucatex", "eliane", "portobello", "portinari",
          "biancogres", "ceusa", "incefra", "gerdau", "belgo", "arcelor", "arcelormittal", "steck", "schneider",
          "siemens", "weg", "tramontina", "vonder", "gedore", "cortag", "makita", "bosch", "dewalt", "deca", "docol",
          "lorenzetti", "fame", "pial", "legrand", "prysmian", "sil", "cobrecom", "induscabos", "corfio", "viapol",
          "vedacit", "sika", "otto", "baumgart", "dryko", "denver", "brasilit", "eternit", "tupy", "tecnogres",
          "elizabeth", "delta", "cecrisa", "atlas", "pincel", "atlantica", "munari", "hydra", "astra", "censi",
          "blukit", "perlex", "marluvas", "fujiwara", "vicsa", "3m", "danny", "kalipso", "plastcor", "ibratin"}

# linhas de material que não se substituem entre si
LINHAS_MATERIAL = {"pvch", "pvcs", "cpvc", "ppr", "pead", "pex", "pba", "pp", "galvanizado", "inox", "latao",
                   "bronze", "cobre", "aluminio", "ferro", "fundido"}
# grupos de variantes mutuamente exclusivas
VARIANTES = {
    "posicao": {"superior", "inferior"},
    "formato": {"quadrada", "quadrado", "redonda", "redondo", "retangular", "circular", "oval", "sextavado",
                "sextavada"},
    "genero": {"macho", "femea"},
    "lado": {"direita", "direito", "esquerda", "esquerdo"},
    "ambiente": {"interno", "interna", "externo", "externa"},
    "multiplicidade": {"simples", "dupla", "duplo", "tripla", "triplo"},
    "comprimento_rel": {"curta", "curto", "longa", "longo"},
    "abertura": {"aberta", "aberto", "fechada", "fechado"},
    "conexao": {"soldavel", "roscavel", "rosca", "flangeado", "flange"},
    "publico": {"masculino", "masculina", "feminino", "feminina", "infantil", "unissex"},
    "acabamento": {"fosco", "fosca", "brilhante", "acetinado", "acetinada", "polido", "polida", "acetinado"},
}
VARIANTE_CANON = {"quadrado": "quadrada", "redondo": "redonda", "sextavada": "sextavado", "direito": "direita",
                  "esquerdo": "esquerda", "interna": "interno", "externa": "externo", "duplo": "dupla",
                  "triplo": "tripla", "curto": "curta", "longo": "longa", "aberto": "aberta", "fechado": "fechada",
                  "rosca": "roscavel", "flange": "flangeado", "fosca": "fosco", "polida": "polido",
                  "acetinada": "acetinado", "masculina": "masculino", "feminina": "feminino"}
# palavras que não são o "nome" do material (para achar o substantivo principal)
_NAO_CABECA = {"kit", "conjunto", "jogo", "par", "peca", "material", "fornecimento", "servico", "aquisicao",
               "compra", "locacao", "aluguel", "item", "produto", "unidade", "un", "com", "sem", "para", "de", "da",
               "do", "em", "tipo"}
SINONIMOS_CABECA = {"tijolo": "bloco", "cabos": "cabo", "tubos": "tubo", "luvas": "luva", "joelhos": "joelho",
                    "pregos": "prego", "parafusos": "parafuso", "fios": "fio", "telhas": "telha", "perfis": "perfil"}

_NUM = r"\d+(?:\.\d+)?"
_FRAC = r"(?:\d+\s+)?\d+/\d+"
_ROMANOS = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}


def _f(x: str) -> float:
    return round(float(x), 4)


def _frac(x: str) -> float | None:
    try:
        return round(float(sum(Fraction(p) for p in x.split())), 4)
    except (ZeroDivisionError, ValueError):
        return None


@dataclass
class Atributos:
    valores: dict = field(default_factory=dict)        # nome -> valor (float, str, tuple ou frozenset)
    grupos: dict = field(default_factory=dict)         # nome -> CRITICO | EMBALAGEM | INFORMATIVO
    canonico: str = ""

    def add(self, nome: str, valor, grupo: str) -> None:
        if valor in (None, "", frozenset(), ()):
            return
        self.valores[nome] = valor
        self.grupos[nome] = grupo

    def as_dict(self) -> dict:
        """Serializável (para jsonb / exibição)."""
        out = {}
        for k, v in self.valores.items():
            out[k] = sorted(v) if isinstance(v, frozenset) else (list(v) if isinstance(v, tuple) else v)
        return out


def extrair(descricao: str, vocabulario: dict | None = None, texto_canonico: str | None = None) -> Atributos:
    t = texto_canonico if texto_canonico is not None else canonico(descricao, vocabulario)
    a = Atributos(canonico=t)
    consumidos: list[tuple[int, int]] = []

    def achar(padrao: str):
        for m in re.finditer(padrao, t):
            consumidos.append(m.span())
            yield m

    # ── dimensões AxB(xC) (+ unidade opcional) ──────────────────────────────
    dims = []
    # números crus (sem conversão de unidade): "2,45 x 6,00 m" == "2,45 x 6,00"; não começa
    # no meio de fração ("1 1/2 x 13" é bitola de prego, não dimensão 2x13)
    _U = r"(?:\s*(?:mm|cm|m)\b)?"
    for m in achar(rf"(?<![\d/.])({_NUM})(?!/){_U}\s+x\s+({_NUM}){_U}(?:\s+x\s+({_NUM}){_U})?"):
        nums = [_f(g) for g in m.groups()[:3] if g]
        dims.append(tuple(sorted(nums)))
    if dims:
        a.add("dimensoes", frozenset(dims), CRITICO)

    # ── diâmetros / medidas em mm (dn, de, diam, mm, cm) ────────────────────
    mm = set()
    for m in achar(rf"\b(?:dn|diam|diametro)\s*({_NUM})(?:\s*mm)?\b|\bde\s*({_NUM})\s*mm\b"):
        mm.add(_f(m.group(1) or m.group(2)))
    for m in []:
        mm.add(_f(m.group(1)))
    for m in achar(rf"({_NUM})\s*mm\b(?!2)"):
        mm.add(_f(m.group(1)))
    for m in achar(rf"({_NUM})\s*cm\b"):
        mm.add(round(_f(m.group(1)) * 10, 2))

    # ── polegadas (frações e "N pol") ───────────────────────────────────────
    pol = set()
    for m in achar(rf"({_FRAC}|{_NUM})\s*pol\b"):
        pol.add(_frac(m.group(1)) if "/" in m.group(1) else _f(m.group(1)))
    for m in achar(rf"(?<![\d./])({_FRAC})(?![\d/])"):
        if not re.search(r"kv", t[m.end():m.end() + 4]):
            pol.add(_frac(m.group(1)))
    a.add("polegadas", frozenset(p for p in pol if p), CRITICO)

    # ── grandezas elétricas / mecânicas (críticas) ──────────────────────────
    sec = {_f(m.group(1)) for m in achar(rf"({_NUM})\s*mm2\b")}
    # em cabos/fios, "2,5mm" é seção (mm²) escrita sem o expoente
    primeira = next((w for w in t.split() if w.isalpha() and len(w) > 2), "")
    if primeira in ("cabo", "fio", "cordoalha") and not sec and mm and not re.search(r"\bcabo\s+de\s+aco\b", t):
        sec, mm = set(mm), set()
    a.add("secao_mm2", frozenset(sec), CRITICO)
    a.add("medidas_mm", frozenset(mm), CRITICO)
    mpa = set()
    for m in achar(rf"fck\s*=?\s*({_NUM})|({_NUM})\s*mpa\b"):
        mpa.add(_f(m.group(1) or m.group(2)))
    a.add("resistencia_mpa", frozenset(mpa), CRITICO)
    kv = {m.group(0).replace(" ", "") for m in achar(rf"{_NUM}/{_NUM}\s*kv\b")}
    tensao = set(kv)
    for m in achar(rf"(?<![/\d.])({_NUM})\s*(kv|v)\b"):
        tensao.add(f"{_f(m.group(1)) * (1000 if m.group(2) == 'kv' else 1):g}v")
    a.add("tensao", frozenset(tensao), CRITICO)
    a.add("corrente_a", frozenset(_f(m.group(1)) for m in achar(rf"({_NUM})\s*a\b(?!\s*\d+(?:\.\d+)?\s*(?:mm|cm|m|kg|g|l|ml|pol)\b)")), CRITICO)
    a.add("capacidade_ka", frozenset(_f(m.group(1)) for m in achar(rf"({_NUM})\s*ka\b")), CRITICO)
    pot = {f"{_f(m.group(1)):g}{m.group(2)}" for m in achar(rf"({_NUM})\s*(w|kw|cv|hp|btu|kva|va)\b")}
    a.add("potencia", frozenset(pot), CRITICO)
    polos = None
    for nome, n in (("monopolar", 1), ("bipolar", 2), ("tripolar", 3), ("tetrapolar", 4)):
        if re.search(rf"\b{nome}\b", t):
            polos = n
    m = re.search(r"\b([1-4])\s*p\b", t)
    if m:
        polos = int(m.group(1))
    a.add("polos", polos, CRITICO)
    m = re.search(r"\bcurva\s+([bcdk])\b", t)
    a.add("curva", m.group(1).upper() if m else None, CRITICO)

    # ── classes de materiais (críticas) ─────────────────────────────────────
    m = re.search(r"\bca\s*-?\s*(25|50|60)\b", t)
    a.add("classe_aco", f"CA-{m.group(1)}" if m else None, CRITICO)
    m = re.search(r"\bcp\s*-?\s*(iii|ii|iv|v|i|[1-5])\s*(?:-?\s*(e|f|z|ari|rs)\b)?\s*(?:-?\s*(25|32|40)\b)?", t)
    if m:
        a.add("cimento_tipo", f"CP-{_ROMANOS[m.group(1)]}", CRITICO)
        a.add("cimento_adicao", (m.group(2) or "").upper() or None, CRITICO)
        a.add("cimento_classe", m.group(3), CRITICO)
    m = re.search(r"\bac\s*-?\s*(iii|ii|i|[123])\b", t)
    if m and "argamassa" in t:
        a.add("argamassa_ac", f"AC-{_ROMANOS[m.group(1)]}", CRITICO)
    m = re.search(r"\bq\s*-?\s*(\d{2,3})\b", t)
    if m and "tela" in t:
        a.add("tela_q", f"Q{m.group(1)}", CRITICO)
    m = re.search(r"\bbrita\s+(\d/\d|\d)\b", t)
    a.add("brita_n", m.group(1) if m else None, CRITICO)
    m = re.search(r"\b(\d+)\s+furos\b", t)
    a.add("furos", int(m.group(1)) if m else None, CRITICO)
    m = re.search(r"\bpn\s*(\d+(?:\.\d+)?)\b", t)
    a.add("pn", m.group(1) if m else None, CRITICO)
    m = re.search(r"\bsch\s*(\d+)\b", t)
    a.add("sch", m.group(1) if m else None, CRITICO)
    m = re.search(r"\bcat\s*(5e|5|6a|6|7)\b", t)
    a.add("categoria_cabo", m.group(1) if m else None, CRITICO)
    m = re.search(r"\b(areia|brita|po|pedrisco|cascalho|lixa)\b.*\b(fina|media|grossa|extra fina)\b", t)
    a.add("granulometria", m.group(2) if m else None, CRITICO)
    m = re.search(r"\b(?:papel|folha|formato|envelope)\b.*\ba\s*([0-6])\b|\ba([0-6])\b", t)
    if m and re.search(r"\b(papel|folha|envelope|formato|pasta|caderno)\b", t):
        a.add("formato_papel", "A" + (m.group(1) or m.group(2)), CRITICO)
    a.add("bitola_n0", frozenset(m.group(0).replace(" ", "") for m in achar(r"\b\d+\s*/\s*0\b")), CRITICO)
    # letra isolada como código de modelo/forma (junção L x X x T); ignora unidades e conectivos
    sem_dim = re.sub(r"\d\s+x\s+\d", " ", t)
    letras = {w for w in re.findall(r"(?<!\d\s)(?<![\d.])\b([b-df-hj-np-tv-z])\b(?!\s*\d)", sem_dim)
              if w not in {"m", "g", "v", "w", "p"}}
    a.add("letra_modelo", frozenset(letras), CRITICO)
    a.add("capacidade_dados", frozenset(f"{_f(m.group(1)):g}{m.group(2)}" for m in
                                        achar(rf"({_NUM})\s*(gb|tb|mb)\b")), CRITICO)
    angulos = {_f(m.group(1)) for m in achar(rf"({_NUM})\s*graus\b")}
    # "JOELHO 90 PVC" / "CURVA 45": ângulo escrito sem o símbolo de grau
    for m in achar(r"\b(?:joelho|curva|cotovelo|te|juncao)\s+(11|22|22\.5|30|45|60|90|180)\b(?!\s*(?:mm|cm|x))"):
        angulos.add(_f(m.group(1)))
    a.add("angulo", frozenset(angulos), CRITICO)
    m = re.search(r"\b(?:numero|n|no|nr)\s*(\d+)\b", t)
    if m:
        consumidos.append(m.span())
        a.add("numero", m.group(1), CRITICO)
    m = re.search(r"\btipo\s+([a-z])\b", t)
    a.add("tipo_letra", m.group(1).upper() if m else None, CRITICO)
    serie = re.findall(r"\b(sn|sr)\b|\bserie\s+([a-z]+)\b", t)
    a.add("serie", frozenset(x or y for x, y in serie), CRITICO)
    a.add("linha_material", frozenset(set(t.split()) & LINHAS_MATERIAL), CRITICO)
    palavras_set = set(t.split())
    for grupo, termos in VARIANTES.items():
        achados = frozenset(VARIANTE_CANON.get(w, w) for w in palavras_set & termos)
        a.add(f"variante_{grupo}", achados, CRITICO)
    # com X / sem X (ex.: rolo com cabo x rolo sem cabo)
    pol_cs = frozenset(f"{m.group(1)}:{m.group(2)}" for m in re.finditer(r"\b(com|sem)\s+([a-z]{3,})\b", t))
    a.add("com_sem", pol_cs, INFORMATIVO)
    if re.search(r"\b(calca|camisa|camiseta|bota|botina|luva|jaleco|colete|fardamento|blusa|bermuda|macacao|"
                 r"japona|jaqueta|uniforme|sapato|tenis|capa)\b", t):
        tam = re.search(r"\b(?:tam|tamanho)\s+(\w+)", t)
        tamanhos = set(t.split()) & {"pp", "p", "m", "g", "gg", "xg", "eg", "exg", "xgg", "egg", "xxg"}
        if tam:
            a.add("tamanho", tam.group(1).upper(), CRITICO)
        elif tamanhos:
            a.add("tamanho", frozenset(x.upper() for x in tamanhos), CRITICO)
    cabeca = next((w for w in t.split() if len(w) >= 3 and w.isalpha() and w not in _NAO_CABECA), None)
    a.add("tipo_material", SINONIMOS_CABECA.get(cabeca, cabeca), CRITICO)
    for termo in ("autoadensavel", "bombeavel", "estrutural", "vedacao"):
        if re.search(rf"\b{termo}\b", t):
            a.add(f"tipo_{termo}", True, CRITICO)

    # ── embalagem / apresentação comercial ──────────────────────────────────
    a.add("peso_kg", frozenset(
        [_f(m.group(1)) for m in achar(rf"({_NUM})\s*kg\b")] +
        [round(_f(m.group(1)) / 1000, 4) for m in achar(rf"({_NUM})\s*g\b")]), EMBALAGEM)
    a.add("volume_l", frozenset(
        [_f(m.group(1)) for m in achar(rf"({_NUM})\s*l\b")] +
        [round(_f(m.group(1)) / 1000, 4) for m in achar(rf"({_NUM})\s*ml\b")]), EMBALAGEM)
    a.add("comprimento_m", frozenset(_f(m.group(1)) for m in achar(rf"({_NUM})\s*m\b")), EMBALAGEM)
    a.add("area_m2", frozenset(_f(m.group(1)) for m in achar(rf"({_NUM})\s*m2\b")), EMBALAGEM)
    a.add("volume_m3", frozenset(_f(m.group(1)) for m in achar(rf"({_NUM})\s*m3\b")), EMBALAGEM)
    qtd = {int(float(m.group(1))) for m in achar(r"\b(?:com|caixa|pacote|cx|pct)\s+(\d+)\s*(?:un|peca|pecas|unid)?\b")}
    qtd |= {int(float(m.group(1))) for m in achar(r"\b(\d+)\s*(?:un|pecas)\b")}
    a.add("qtd_embalagem", frozenset(qtd), EMBALAGEM)

    # ── informativos ────────────────────────────────────────────────────────
    palavras = set(t.split())
    a.add("cor", frozenset(palavras & CORES), INFORMATIVO)
    a.add("marca", frozenset(palavras & MARCAS), INFORMATIVO)
    livres = t
    for ini, fim in sorted(consumidos, reverse=True):
        livres = livres[:ini] + " " + livres[fim:]
    nums = frozenset(re.findall(r"(?<![a-z\d.])\d+(?:\.\d+)?(?![a-z\d])", livres))
    a.add("numeros", nums, NUMEROS)
    return a


# ─────────────────────────────────────────────────────────────────────────────
# Compatibilidade
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Comparacao:
    iguais: list[str] = field(default_factory=list)
    parciais: list[str] = field(default_factory=list)       # um conjunto contém o outro / só um lado tem
    conflitos: list[dict] = field(default_factory=list)     # críticos divergentes
    embalagem: list[dict] = field(default_factory=list)     # embalagem divergente (unidade de contagem)
    informativos: list[str] = field(default_factory=list)   # cor/marca/números diferentes
    score: float = 1.0                                       # 0..1

    @property
    def tem_conflito(self) -> bool:
        return bool(self.conflitos)

    def resumo(self) -> dict:
        return {"iguais": self.iguais, "parciais": self.parciais, "conflitos": self.conflitos,
                "embalagem": self.embalagem, "informativos": self.informativos, "score": round(self.score, 4)}


def _valores_iguais(v1, v2) -> tuple[bool, bool]:
    """(iguais, compatíveis_por_inclusão)"""
    if isinstance(v1, frozenset) and isinstance(v2, frozenset):
        if v1 == v2:
            return True, True
        return False, v1 <= v2 or v2 <= v1
    return v1 == v2, False


def comparar(a: Atributos, b: Atributos, unidade_a: str | None = None, unidade_b: str | None = None) -> Comparacao:
    c = Comparacao()
    pontos, total = 0.0, 0.0
    unid_contagem = (unidade_a or "un") in UNIDADES_CONTAGEM or (unidade_b or "un") in UNIDADES_CONTAGEM
    for nome in sorted(set(a.valores) | set(b.valores)):
        grupo = a.grupos.get(nome) or b.grupos.get(nome)
        va, vb = a.valores.get(nome), b.valores.get(nome)
        if nome == "com_sem":
            if va and vb:
                ca = {x.split(":")[1]: x.split(":")[0] for x in va}
                cb = {x.split(":")[1]: x.split(":")[0] for x in vb}
                opostos = [w for w in ca if w in cb and ca[w] != cb[w]]
                if opostos:
                    c.conflitos.append({"atributo": "com_sem", "a": _fmt(va), "b": _fmt(vb)})
            continue
        if grupo == INFORMATIVO:
            if va is not None and vb is not None and va != vb and not (va <= vb or vb <= va):
                c.informativos.append(nome)
                pontos -= 0.15
            continue
        if grupo == NUMEROS:
            if (va is None) != (vb is None):
                c.parciais.append(nome)
            elif va is not None and vb is not None and va != vb:
                if va <= vb or vb <= va:
                    c.parciais.append(nome)
                else:
                    c.conflitos.append({"atributo": "numeros", "a": _fmt(va), "b": _fmt(vb)})
            continue
        if grupo == EMBALAGEM and _unidade_da_grandeza(nome, unidade_a) and _unidade_da_grandeza(nome, unidade_b):
            continue
        peso = 1.0 if grupo == CRITICO else 0.6
        total += peso
        if va is None or vb is None:
            c.parciais.append(nome)
            pontos += 0.4 * peso
            continue
        iguais, inclusao = _valores_iguais(va, vb)
        if iguais:
            c.iguais.append(nome)
            pontos += peso
        elif inclusao:
            c.parciais.append(nome)
            pontos += 0.6 * peso
        elif grupo == CRITICO:
            c.conflitos.append({"atributo": nome, "a": _fmt(va), "b": _fmt(vb)})
        else:
            c.embalagem.append({"atributo": nome, "a": _fmt(va), "b": _fmt(vb)})
    c.score = 1.0 if total == 0 else max(0.0, min(1.0, pontos / total))
    if c.conflitos:
        c.score = 0.0
    return c


_GRANDEZA = {"peso_kg": {"kg", "g", "t"}, "volume_l": {"l", "ml"}, "comprimento_m": {"m", "cm", "mm", "km"},
             "area_m2": {"m2"}, "volume_m3": {"m3"}, "qtd_embalagem": set()}


def _unidade_da_grandeza(atributo: str, unidade: str | None) -> bool:
    """True se a unidade de compra já É a grandeza (comprar em kg torna o peso da embalagem irrelevante)."""
    return (unidade or "") in _GRANDEZA.get(atributo, set())


def _fmt(v):
    if isinstance(v, frozenset):
        return ", ".join(str(x) for x in sorted(v, key=str))
    return v
