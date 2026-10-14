"""
Avaliação do motor de correspondência contra pares rotulados.

Fontes de rótulo (usa as que existirem):
  1. tests/dados/pares_rotulados.csv  — descrições REAIS do catálogo Sienge,
     rotuladas na construção do motor (equivalente para comparar preço: 1/0);
  2. --catalogo: decisões humanas registradas na tela de Correspondências
     (painel.equivalencia_par com status aprovado/rejeitado) — conforme o setor
     de Suprimentos revisa, este passa a ser o conjunto de validação oficial.

Métricas (priorizando a PRECISÃO da aprovação automática):
  precisão_auto   = equivalentes de verdade entre os aprovados automaticamente
  revocação_auto  = equivalentes aprovados automaticamente / todos os equivalentes
  revocação_util  = equivalentes que chegam a auto OU revisão humana
  falso_conflito  = equivalentes bloqueados como "incompatível"
  % revisão       = pares encaminhados para revisão humana

Uso:
    python -m scripts.avaliar_motor                # só o CSV
    python -m scripts.avaliar_motor --catalogo     # CSV + decisões do banco
Gera relatorio_avaliacao_motor.txt na raiz do projeto.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from app.matching.config import CONFIG
from app.matching.pontuacao import ALTA, INCOMPATIVEL, MEDIA, perfil, pontuar
from app.matching.unidades import padronizar

RAIZ = Path(__file__).resolve().parents[1]
CSV = RAIZ / "tests" / "dados" / "pares_rotulados.csv"


def avaliar(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    t0 = time.perf_counter()
    linhas = []
    for r in df.itertuples(index=False):
        pa = perfil("a", 1, r.descricao_a, r.categoria, padronizar(r.unidade_a))
        pb = perfil("b", 2, r.descricao_b, r.categoria, padronizar(r.unidade_b))
        res = pontuar(pa, pb)
        destino = ("auto" if res.auto_aprovavel else
                   "revisao" if res.nivel in (ALTA, MEDIA) else res.nivel)
        linhas.append({**r._asdict(), "score": res.score, "nivel": res.nivel, "destino": destino,
                       "motivos": "; ".join(res.motivos)})
    out = pd.DataFrame(linhas)
    ms = (time.perf_counter() - t0) / max(len(df), 1) * 1000
    pos = out["equivalente"] == 1
    auto = out["destino"] == "auto"
    m = {
        "pares": len(out), "equivalentes": int(pos.sum()), "nao_equivalentes": int((~pos).sum()),
        "auto": int(auto.sum()),
        "precisao_auto": (out.loc[auto, "equivalente"].mean() if auto.any() else float("nan")),
        "falsos_positivos_auto": int((auto & ~pos).sum()),
        "revocacao_auto": (auto & pos).sum() / pos.sum() if pos.any() else float("nan"),
        "revocacao_util": (out["destino"].isin(["auto", "revisao"]) & pos).sum() / pos.sum() if pos.any() else float("nan"),
        "falsos_negativos": int((~out["destino"].isin(["auto", "revisao"]) & pos).sum()),
        "falso_conflito": int(((out["nivel"] == INCOMPATIVEL) & pos).sum()),
        "pct_revisao": (out["destino"] == "revisao").mean(),
        "nao_equivalentes_barrados": ((~out["destino"].isin(["auto"])) & ~pos).sum() / max((~pos).sum(), 1),
        "ms_por_par": ms,
    }
    return out, m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogo", action="store_true", help="inclui decisões humanas do banco")
    args = ap.parse_args()
    df = pd.read_csv(CSV, sep=";")
    df["fonte"] = "csv_rotulado"
    if args.catalogo:
        from app.repositories import catalogo_repo
        dec = catalogo_repo.decisoes_humanas()
        if len(dec):
            df = pd.concat([df, dec.assign(fonte="decisao_humana")], ignore_index=True)

    out, m = avaliar(df)
    lin = [f"Avaliação do motor de correspondência — regras {CONFIG.versao}",
           f"Pares avaliados: {m['pares']} ({m['equivalentes']} equivalentes, {m['nao_equivalentes']} não equivalentes)",
           "Amostra ESTRATIFICADA por nível de confiança (não é proporcional à população de pares).", "",
           f"Aprovação automática : {m['auto']} pares | precisão {m['precisao_auto']:.1%} | "
           f"falsos positivos {m['falsos_positivos_auto']}",
           f"Revocação automática : {m['revocacao_auto']:.1%}   (equivalentes aprovados sem revisão)",
           f"Revocação útil       : {m['revocacao_util']:.1%}   (equivalentes que chegam a auto ou revisão)",
           f"Falsos negativos     : {m['falsos_negativos']}   (equivalentes descartados: baixa/incompatível/não comparável)",
           f"Falso conflito       : {m['falso_conflito']}   (equivalentes bloqueados por 'conflito técnico')",
           f"Encaminhados p/ revisão humana: {m['pct_revisao']:.1%}",
           f"Não equivalentes barrados da aprovação automática: {m['nao_equivalentes_barrados']:.1%}",
           f"Tempo: {m['ms_por_par']:.2f} ms por par", "",
           "Por categoria (pares | equivalentes | auto | FP auto):"]
    for cat, g in out.groupby("categoria"):
        a = g["destino"] == "auto"
        lin.append(f"  {str(cat)[:40]:<40} {len(g):>4} {int(g['equivalente'].sum()):>4} {int(a.sum()):>4} "
                   f"{int((a & (g['equivalente'] == 0)).sum()):>4}")
    erros = out[((out["destino"] == "auto") & (out["equivalente"] == 0)) |
                ((out["nivel"] == INCOMPATIVEL) & (out["equivalente"] == 1))]
    lin += ["", "Erros relevantes (falso positivo automático / falso conflito):"]
    for r in erros.itertuples():
        lin.append(f"  [{r.destino}/{r.nivel} {r.score}] {r.descricao_a[:60]}  ||  {r.descricao_b[:60]}  -> rótulo {r.equivalente}")
    texto = "\n".join(lin)
    print(texto)
    (RAIZ / "relatorio_avaliacao_motor.txt").write_text(texto, encoding="utf-8")
    out.to_csv(RAIZ / "relatorio_avaliacao_motor_pares.csv", sep=";", index=False)


if __name__ == "__main__":
    main()
