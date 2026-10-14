"""
Configurações gerais das abas (tela /configuracoes).

  - Prazos de SLA por grupo de insumo: a REFERÊNCIA vem do ETL (planilha de Suprimentos ->
    suprimentos.ref_sla_grupo_insumo); o que for editado aqui fica em painel.config_sla_grupo e
    vale NA HORA (a tela de SLA compara dias × prazo ao ler). Toda alteração vai para o histórico.
  - Parâmetros: chave/valor com padrão no código (PARAMETROS). Novo parâmetro = nova entrada aqui.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import get_engine, ler_sql
from app.models.dw import fato_sla_item, ref_sla_grupo_insumo
from app.models.painel import config_sla_grupo, configuracao, configuracao_historico

# chave -> (rótulo, descrição, tipo, padrão, mínimo, máximo)
PARAMETROS: dict[str, tuple] = {
    "sla.em_risco_pct": ("SLA: alerta de risco (% do prazo)", "Item em aberto com idade a partir deste % do prazo "
                         "aparece como 'em risco' (antes de estourar).", "int", 80, 10, 100),
    "sla.contar_abertos": ("SLA: contar em aberto que já estourou como não atendido",
                           "Sim = o backlog vencido entra no % de SLA (visão de gestão). Não = só o que já foi "
                           "concluído (como o Power BI).", "bool", True, None, None),
    "servico.dias_alerta_autorizacao": ("Serviços: alerta de autorização (dias)", "Solicitação aguardando "
                                        "autorização há mais que isso aparece como alerta.", "int", 7, 1, 365),
    "servico.dias_alerta_aberto": ("Serviços: alerta de solicitação em aberto (dias)", "Pendente/parcial há mais "
                                   "que isso desde o cadastro aparece como alerta.", "int", 60, 1, 3650),
}


class ErroConfiguracao(ValueError):
    pass


_cache: dict = {}
_lock = threading.Lock()
TTL_S = 300   # salvar limpa na hora; o TTL só cobre outro processo do servidor


def _cacheado(chave, carregar):
    with _lock:
        em, v = _cache.get(chave, (0.0, None))
        if v is None or time.monotonic() - em > TTL_S:
            v = carregar()
            _cache[chave] = (time.monotonic(), v)
        return v


def limpar_cache():
    with _lock:
        _cache.clear()


# ── parâmetros ───────────────────────────────────────────────────────────────
def _parametros_salvos() -> dict:
    try:
        df = ler_sql(select(configuracao.c.chave, configuracao.c.valor))
    except Exception:  # noqa: BLE001 — migração 0004 ainda não aplicada
        return {}
    return dict(zip(df["chave"], df["valor"]))


def parametro(chave: str):
    salvos = _cacheado("parametros", _parametros_salvos)
    return salvos.get(chave, PARAMETROS[chave][3])


def parametros() -> pd.DataFrame:
    salvos = _cacheado("parametros", _parametros_salvos)
    return pd.DataFrame([{"chave": k, "rotulo": r, "descricao": d, "tipo": t, "padrao": p,
                          "valor": salvos.get(k, p), "minimo": mn, "maximo": mx}
                         for k, (r, d, t, p, mn, mx) in PARAMETROS.items()])


def salvar_parametro(chave: str, valor, por: str) -> None:
    if chave not in PARAMETROS:
        raise ErroConfiguracao(f"Parâmetro desconhecido: {chave}")
    _, _, tipo, _, mn, mx = PARAMETROS[chave]
    if tipo == "int":
        try:
            valor = int(valor)
        except (TypeError, ValueError):
            raise ErroConfiguracao(f"{chave}: informe um número inteiro.") from None
        if (mn is not None and valor < mn) or (mx is not None and valor > mx):
            raise ErroConfiguracao(f"{chave}: valor entre {mn} e {mx}.")
    elif tipo == "bool":
        valor = bool(valor)
    anterior = parametro(chave)
    if anterior == valor:
        return
    with get_engine().begin() as c:
        c.execute(pg_insert(configuracao).values(chave=chave, valor=valor, alterado_por=por)
                  .on_conflict_do_update(index_elements=["chave"],
                                         set_={"valor": valor, "alterado_por": por, "alterado_em": func.now()}))
        c.execute(insert(configuracao_historico).values(area="parametro", chave=chave, valor_anterior=anterior,
                                                        valor_novo=valor, por=por))
    limpar_cache()


# ── prazos de SLA ────────────────────────────────────────────────────────────
def _carregar_prazos() -> pd.DataFrame:
    try:
        ref = ler_sql(select(ref_sla_grupo_insumo))
    except Exception:  # noqa: BLE001 — ETL ainda não rodou a etapa sla_insumo
        ref = pd.DataFrame(columns=[c.name for c in ref_sla_grupo_insumo.c])
    try:   # grupos que aparecem nas compras e não estão na planilha também precisam de prazo
        usados = ler_sql(select(fato_sla_item.c.id_grupo, fato_sla_item.c.grupo_insumo, fato_sla_item.c.tipo_grupo,
                                func.count().label("itens")).where(fato_sla_item.c.id_grupo.isnot(None))
                         .group_by(fato_sla_item.c.id_grupo, fato_sla_item.c.grupo_insumo, fato_sla_item.c.tipo_grupo))
        usados = usados.sort_values("itens", ascending=False).drop_duplicates("id_grupo")
    except Exception:  # noqa: BLE001
        usados = pd.DataFrame(columns=["id_grupo", "grupo_insumo", "tipo_grupo", "itens"])
    try:
        ed = ler_sql(select(config_sla_grupo))
    except Exception:  # noqa: BLE001
        ed = pd.DataFrame(columns=[c.name for c in config_sla_grupo.c])
    base = ref.rename(columns={"lt_fase1": "ref_fase1", "lt_fase2": "ref_fase2", "lt_total": "ref_total"})
    base = base.merge(usados[["id_grupo", "grupo_insumo", "tipo_grupo", "itens"]], on="id_grupo", how="outer",
                      suffixes=("", "_dados"))
    base["grupo_insumo"] = base["grupo_insumo"].fillna(base.pop("grupo_insumo_dados"))
    base["tipo_grupo"] = base["tipo_grupo"].fillna(base.pop("tipo_grupo_dados"))
    base["itens"] = base["itens"].fillna(0).astype(int)
    ed = ed.rename(columns={"lt_fase1": "ed_fase1", "lt_fase2": "ed_fase2", "lt_total": "ed_total",
                            "grupo_insumo": "grupo_editado"})
    base = base.merge(ed, on="id_grupo", how="outer")
    base["grupo_insumo"] = base["grupo_insumo"].fillna(base["grupo_editado"])
    for f in ("fase1", "fase2", "total"):
        base[f"lt_{f}"] = pd.to_numeric(base[f"ed_{f}"], errors="coerce").fillna(
            pd.to_numeric(base[f"ref_{f}"], errors="coerce"))
    editado = base[["ed_fase1", "ed_fase2", "ed_total"]].notna().any(axis=1)
    sem = base["lt_fase1"].isna() & base["lt_fase2"].isna()
    base["origem"] = ["editado no painel" if e else ("sem prazo" if s_ else "planilha") for e, s_ in zip(editado, sem)]
    base["id_grupo"] = base["id_grupo"].astype(int)
    return base.sort_values("id_grupo").reset_index(drop=True)


def prazos_sla() -> pd.DataFrame:
    """Prazo VIGENTE por grupo (editado no painel > planilha), com a referência ao lado."""
    return _cacheado("prazos", _carregar_prazos)


def salvar_prazos(linhas: list[dict], por: str, observacao: str | None = None) -> int:
    """linhas: [{id_grupo, grupo_insumo, lt_fase1, lt_fase2, lt_total}] — só as que mudaram são gravadas.
    Valor igual ao da planilha remove a edição (volta a valer a planilha)."""
    atual = prazos_sla().set_index("id_grupo")
    agora = datetime.now(timezone.utc)
    n = 0
    with get_engine().begin() as c:
        for ln in linhas:
            gid = int(ln["id_grupo"])
            novo = {}
            for f in ("fase1", "fase2", "total"):
                v = ln.get(f"lt_{f}")
                v = None if v in (None, "") or (isinstance(v, float) and pd.isna(v)) else v
                if v is not None:
                    try:
                        v = int(round(float(v)))
                    except (TypeError, ValueError):
                        raise ErroConfiguracao(f"Grupo {gid}: prazo inválido ({v}).") from None
                    if v < 0 or v > 730:
                        raise ErroConfiguracao(f"Grupo {gid}: prazo deve estar entre 0 e 730 dias.")
                novo[f"lt_{f}"] = v
            ant = atual.loc[gid] if gid in atual.index else None
            vig = {k: (None if ant is None or pd.isna(ant[k]) else int(ant[k])) for k in novo}
            if vig == novo:
                continue
            ref = {k: (None if ant is None or pd.isna(ant[f"ref_{k[3:]}"]) else int(ant[f"ref_{k[3:]}"]))
                   for k in novo}
            if ref == novo:
                c.execute(delete(config_sla_grupo).where(config_sla_grupo.c.id_grupo == gid))
            else:
                valores = dict(grupo_insumo=ln.get("grupo_insumo") or (None if ant is None else ant["grupo_insumo"]),
                               observacao=observacao, alterado_por=por, alterado_em=agora, **novo)
                c.execute(pg_insert(config_sla_grupo).values(id_grupo=gid, **valores)
                          .on_conflict_do_update(index_elements=["id_grupo"], set_=valores))
            c.execute(insert(configuracao_historico).values(area="sla_grupo", chave=str(gid), valor_anterior=vig,
                                                            valor_novo=novo, por=por, observacao=observacao))
            n += 1
    limpar_cache()
    return n


def historico(limite: int = 300) -> pd.DataFrame:
    return ler_sql(select(configuracao_historico).order_by(configuracao_historico.c.id.desc()).limit(limite))

