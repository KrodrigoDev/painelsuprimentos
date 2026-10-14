"""
Desempenho do painel (sem dependências novas):

1. Compressão gzip das respostas (JSON dos callbacks, HTML, JS/CSS dos componentes).
   Os callbacks do Dash devolvem JSON muito repetitivo: comprime ~8–15x, o que pesa
   principalmente quando o painel é acessado pela rede (não localhost).

2. Pré-aquecimento e renovação dos caches em segundo plano: ao subir o servidor, as
   bases de cada aba são lidas do banco numa thread; depois são renovadas antes de
   vencer. O usuário não fica esperando a leitura do banco (só se abrir uma aba antes
   do primeiro aquecimento terminar).
"""
from __future__ import annotations

import gzip
import logging
import os
import threading
import time

from flask import Flask, request

logger = logging.getLogger(__name__)

_COMPRIMIVEIS = ("application/json", "text/html", "text/css", "application/javascript", "text/javascript",
                 "text/plain", "image/svg+xml")
_MINIMO = 1024


def instalar_compressao(server: Flask) -> None:
    if os.getenv("PAINEL_GZIP", "true").lower() in ("0", "false", "nao", "não"):
        return

    @server.after_request
    def _gzip(resp):
        try:
            if (resp.direct_passthrough or resp.status_code < 200 or resp.status_code >= 300
                    or "gzip" not in (request.headers.get("Accept-Encoding") or "").lower()
                    or "Content-Encoding" in resp.headers
                    or not (resp.mimetype or "").startswith(_COMPRIMIVEIS)):
                return resp
            dados = resp.get_data()
            if len(dados) < _MINIMO:
                return resp
            resp.set_data(gzip.compress(dados, compresslevel=5))
            resp.headers["Content-Encoding"] = "gzip"
            resp.headers["Content-Length"] = str(len(resp.get_data()))
            vary = resp.headers.get("Vary")
            resp.headers["Vary"] = f"{vary}, Accept-Encoding" if vary else "Accept-Encoding"
        except Exception:  # noqa: BLE001 — compressão nunca pode derrubar a resposta
            logger.exception("Falha ao comprimir resposta; enviando sem compressão.")
        return resp


# ── Aquecimento dos caches ───────────────────────────────────────────────────
def _tarefas() -> list[tuple[str, callable]]:
    """Leituras SEM escopo de usuário (o escopo é aplicado depois, em cada requisição)."""
    from app.repositories import rpa_repo as r
    from app.services import inteligencia as ig
    c = r._CACHE.obter
    return [
        ("compras analisadas", lambda: ig._CACHE.obter("base", ig._carregar_base)),
        ("oportunidades", lambda: ig._CACHE.obter("oportunidades", ig._carregar_oportunidades)),
        ("estoque", r.estoque_bruto),
        ("curva ABC", r.curva_abc_bruta),
        ("adiantamentos", lambda: c("adiantamento", r._carregar_adiantamento, r.SETTINGS.cache_minutos)),
        ("avaliações", lambda: c("avaliacoes", r._carregar_avaliacoes, r.SETTINGS.cache_minutos)),
        ("compras por fornecedor", lambda: c("compras_fornecedor", r._carregar_compras_fornecedor,
                                             r.SETTINGS.cache_minutos)),
        ("contratos", lambda: c("contratos", r._carregar_contratos, r.SETTINGS.cache_minutos)),
        ("SLA", r.sla_bruto),
        ("serviços", lambda: c("servicos", r._carregar_servicos, r.SETTINGS.cache_minutos)),
        ("solicitações x pedidos", r.solicitacoes_por_pedido),
    ]


def aquecer() -> None:
    for nome, fn in _tarefas():
        t0 = time.perf_counter()
        try:
            fn()
            logger.info("Cache aquecido: %s (%.1fs)", nome, time.perf_counter() - t0)
        except Exception as exc:  # noqa: BLE001 — fonte ainda não carregada: a aba mostra o aviso dela
            logger.warning("Cache não aquecido (%s): %s", nome, str(exc).splitlines()[0][:150])


def iniciar_aquecimento() -> None:
    """Thread de fundo: aquece ao subir e renova a cada CACHE_MINUTOS (menos 2 min, para não vencer antes)."""
    if os.getenv("PAINEL_AQUECER", "true").lower() in ("0", "false", "nao", "não"):
        return
    def _loop():
        time.sleep(1)
        aquecer()                                   # 1ª leitura de cada base, antes de alguém pedir
        from app.repositories import rpa_repo
        from app.services import inteligencia as ig
        while True:                                 # depois: renova o que está para vencer, em segundo plano
            time.sleep(60)
            for cache in (ig._CACHE, rpa_repo._CACHE):
                cache.renovar_vencendo(folga_s=180)
    threading.Thread(target=_loop, name="aquecer-cache", daemon=True).start()
