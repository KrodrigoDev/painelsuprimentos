"""
Cache em memória das bases do painel (compartilhado por todos os usuários; o escopo de acesso é
aplicado DEPOIS, em cada leitura).

- Trava por chave: carregar uma tabela não bloqueia a leitura das outras.
- Vencido = serve o dado anterior e recarrega em segundo plano (uma recarga por chave por vez):
  o usuário só espera o banco na primeira leitura de cada tabela depois que o servidor sobe
  (e o aquecimento em app/desempenho.py faz essa primeira leitura antes de alguém pedir).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)


class CacheSWR:
    def __init__(self, nome: str, ttl_padrao_min: float = 30):
        self.nome = nome
        self.ttl_padrao_min = ttl_padrao_min
        self._lock = threading.Lock()
        self._travas: dict[str, threading.Lock] = {}
        self.dados: dict[str, tuple[float, object]] = {}
        self._carregadores: dict[str, tuple[Callable, float]] = {}
        self._recarregando: set[str] = set()

    def _trava(self, chave: str) -> threading.Lock:
        with self._lock:
            return self._travas.setdefault(chave, threading.Lock())

    def _carregar(self, chave: str, carregar: Callable):
        t0 = time.perf_counter()
        v = carregar()
        with self._lock:
            self.dados[chave] = (time.monotonic(), v)
        logger.debug("cache %s/%s carregado em %.1fs", self.nome, chave, time.perf_counter() - t0)
        return v

    def _recarregar_fundo(self, chave: str, carregar: Callable) -> None:
        with self._lock:
            if chave in self._recarregando:
                return
            self._recarregando.add(chave)

        def _rodar():
            try:
                with self._trava(chave):
                    self._carregar(chave, carregar)
            except Exception:  # noqa: BLE001 — mantém o dado anterior; tenta de novo na próxima leitura
                logger.exception("Falha ao recarregar cache %s/%s (mantido o anterior)", self.nome, chave)
            finally:
                with self._lock:
                    self._recarregando.discard(chave)
        threading.Thread(target=_rodar, name=f"cache-{chave}", daemon=True).start()

    def obter(self, chave: str, carregar: Callable, ttl_min: float | None = None):
        ttl = (self.ttl_padrao_min if ttl_min is None else ttl_min) * 60
        with self._lock:
            self._carregadores[chave] = (carregar, ttl)
            em, v = self.dados.get(chave, (0.0, None))
        if v is not None:
            if time.monotonic() - em > ttl:
                self._recarregar_fundo(chave, carregar)          # serve o anterior agora
            return v
        with self._trava(chave):                                  # 1ª leitura: espera (só esta chave)
            with self._lock:
                em, v = self.dados.get(chave, (0.0, None))
            if v is not None:                                     # outra thread carregou enquanto esperávamos
                return v
            return self._carregar(chave, carregar)

    def renovar_vencendo(self, folga_s: float = 120) -> None:
        """Recarrega em segundo plano o que vence nos próximos `folga_s` segundos (laço de aquecimento)."""
        with self._lock:
            itens = [(c, f, ttl, self.dados.get(c, (0.0, None))[0]) for c, (f, ttl) in self._carregadores.items()]
        agora = time.monotonic()
        for chave, carregar, ttl, em in itens:
            if agora - em > ttl - folga_s:
                self._recarregar_fundo(chave, carregar)

    def limpar(self) -> None:
        with self._lock:
            self.dados.clear()
