"""
Motor de correspondência — casos do escopo (seções 4.5, 4.6 e plano de testes 10).
Descrições no estilo do catálogo Sienge real.
"""
import pytest

from app.matching.atributos import comparar, extrair
from app.matching.pipeline import construir_perfis, formar_grupos
from app.matching.pontuacao import ALTA, INCOMPATIVEL, MEDIA, NAO_COMPARAVEL, perfil, pontuar
from app.matching.unidades import fator

import pandas as pd


def par(a, b, ua="un", ub="un", cat="C"):
    return pontuar(perfil("a", 1, a, cat, ua), perfil("b", 2, b, cat, ub))


# ── 4.5 exemplos do escopo ───────────────────────────────────────────────────
@pytest.mark.parametrize("b", ["Tubo soldável PVC, DN 25, barra de 6 metros", "TUBO PVC 25 MM - 6 METROS"])
def test_tubos_equivalentes_sao_candidatos(b):
    r = par("TUBO PVC SOLDAVEL 25MM 6M", b)
    assert r.nivel in (ALTA, MEDIA)           # candidato (auto ou revisão)
    assert not r.comparacao["conflitos"]


def test_tubo_25_x_50_incompativel_mesmo_com_texto_parecido():
    r = par("TUBO PVC 25MM", "TUBO PVC 50MM")
    assert r.componentes["texto"] > 0.9
    assert r.nivel == INCOMPATIVEL and not r.auto_aprovavel


# ── 10.7 textualmente semelhantes, tecnicamente incompatíveis ───────────────
@pytest.mark.parametrize("a,b,ua,atributo", [
    ("CIMENTO PORTLAND CP II-F-32", "CIMENTO PORTLAND CP II-Z-32", "sc", "cimento_adicao"),
    ("CIMENTO CP II F 32", "CIMENTO CP II F 40", "sc", "cimento_classe"),
    ("Vergalhão de Aço CA-50 6,3MM", "Vergalhão de Aço CA-50 16,0 mm", "kg", "medidas_mm"),
    ("Vergalhão de Aço CA-50 10 mm", "Vergalhão de Aço CA-60 10 mm", "kg", "classe_aco"),
    ("TUBO PBA DN50 PN 6", "TUBO PBA DN50 PN 12", "un", "pn"),
    ("PORCELANATO ACETINADO 60X60", "PORCELANATO ACETINADO 90X90", "m2", "dimensoes"),
    ("TELA SOLDADA NERVURADA Q92 2,45X6M", "TELA SOLDADA NERVURADA Q138 2,45X6M", "un", "tela_q"),
    ("CABO FLEXIVEL 2,5MM² 750V", "CABO FLEXIVEL 10MM² 750V", "m", "secao_mm2"),
    ("DISJUNTOR MONOPOLAR 16A CURVA C", "DISJUNTOR MONOPOLAR 16A CURVA B", "un", "curva"),
    ("BRITA 0", "BRITA 3/4", "m3", "brita_n"),
    ("AREIA MEDIA", "AREIA GROSSA", "m3", "granulometria"),
    ("JOELHO 90 PVC 50MM", "JOELHO 45 PVC 50MM", "un", "angulo"),
    ("LUVA PVC SOLDAVEL 25MM", "JOELHO PVC SOLDAVEL 25MM", "un", "tipo_material"),
    ("PLUG 2P+T 10A FEMEA", "PLUG 2P+T 10A MACHO", "un", "variante_genero"),
    ("ROLO DE ESPUMA 9CM S/CABO", "ROLO DE ESPUMA 9CM C/CABO", "un", "com_sem"),
    ("PAPEL A3 BRANCO", "PAPEL A4 BRANCO", "res", "formato_papel"),
])
def test_conflitos_tecnicos_bloqueiam(a, b, ua, atributo):
    r = par(a, b, ua, ua)
    assert r.nivel == INCOMPATIVEL, (r.nivel, r.motivos)
    assert atributo in {c["atributo"] for c in r.comparacao["conflitos"]}
    assert not r.auto_aprovavel


# ── 10.5 / 10.6 erros, abreviações e ordem das palavras ─────────────────────
def test_abreviacao_e_erro_de_digitacao():
    r = par("CIMENTO PORTILAND CP II F 32", "CIMENTO PORTLAND CP-II-F-32", "sc", "sc")
    assert r.nivel in (ALTA, MEDIA) and not r.comparacao["conflitos"]


def test_ordem_das_palavras():
    r = par("CAIXA D'AGUA - DE POLIETILENO - 500L", "IM - CAIXA D'AGUA 500L - POLIETILENO")
    assert r.componentes["tokens"] >= 0.95 and r.nivel == ALTA


def test_cor_diferente_e_equivalente_para_preco():
    r = par("CABO FLEXIVEL 2,5MM² 750V AZUL", "CABO FLEXIVEL 2,5MM² 750V VERMELHO", "m", "m")
    assert r.auto_aprovavel


def test_descricao_generica_nunca_aprova_sozinha():
    r = par("IM - CAMISA", "CAMISA")
    assert not r.auto_aprovavel


# ── 10.8 / 4.6 unidades e embalagens ────────────────────────────────────────
def test_saco_50kg_x_25kg_nao_comparavel_por_saco():
    r = par("CIMENTO CP II F 32 50KG", "CIMENTO CP II F 32 25KG", "sc", "sc")
    assert r.nivel == NAO_COMPARAVEL


def test_mesma_embalagem_irrelevante_quando_compra_por_kg():
    r = par("CIMENTO CP II F 32 50KG", "CIMENTO CP II F 32 25KG", "kg", "kg")
    assert r.nivel != NAO_COMPARAVEL


def test_unidades_distintas_sem_conversao():
    r = par("LUVA DE VAQUETA", "LUVA DE VAQUETA", "par", "un")
    assert r.nivel == NAO_COMPARAVEL


def test_conversoes_so_rastreaveis():
    assert fator("sc", "kg", extrair("CIMENTO CP II 50KG"))[0] == 50
    assert fator("br", "m", extrair("TUBO PVC 25MM BARRA 6M"))[0] == 6
    assert fator("cx", "un", extrair("PARAFUSO 4,8X50 CAIXA COM 100 UN"))[0] == 100
    assert fator("t", "kg", None)[0] == 0.001 or fator("t", "kg", None)[0] == pytest.approx(0.001)
    assert fator("cx", "un", extrair("PARAFUSO 4,8X50")) is None          # caixa sem composição
    assert fator("sc", "m3", extrair("AREIA MEDIA SACO 20KG")) is None    # sem relação conhecida


# ── grupos: transitividade não junta incompatíveis ──────────────────────────
def test_grupos_recusam_uniao_com_conflito_transitivo():
    df = pd.DataFrame([(1, 10, 0, "TUBO PVC 25MM", "C", "un"), (2, 11, 0, "TUBO PVC 25 MM BRANCO", "C", "un"),
                       (3, 12, 0, "TUBO PVC 50MM", "C", "un")],
                      columns=["id_insumo", "cod_insumo", "cod_detalhe", "descricao_completa", "categoria", "unidade_padrao"])
    perfis = construir_perfis(df)
    # par inválido 11~12 forçado (ex.: aprovação errada) não pode unir 25 mm com 50 mm via 11
    mapa, recusados = formar_grupos(perfis, [("10|0", "11|0", 95.0), ("11|0", "12|0", 90.0)])
    assert mapa["10|0"] == mapa["11|0"] != mapa["12|0"]
    assert recusados and "medidas_mm" in recusados[0][2]


def test_normalizacao_preserva_numeros_e_original():
    a = extrair("IM - Prego - 1 1/2\" X 13 (15 X 18)")
    assert 1.5 in a.valores["polegadas"]
    b = extrair("CABO FLEXIVEL (NBR 7288) - 10mm² 0,6/1KV")
    assert b.valores["secao_mm2"] == frozenset({10.0}) and "0.6/1kv" in b.valores["tensao"]
