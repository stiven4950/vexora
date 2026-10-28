"""Límites de peticiones de las páginas públicas (enlaces compartidos): frenan abusos y gastos sin
que quien ve un video lo note.

En memoria, por proceso: la API corre con una sola instancia (docs/despliegue_cloud_run.md), así
que los conteos son exactos. Con más tráfico, una regla por IP en Cloud Armor delante de Cloud Run
frena el abuso antes de llegar aquí. Las IP solo viven en memoria unos minutos: no se registran.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable

# Página del enlace: abrir y recargar unas veces. Video: el navegador lo pide por trozos al
# reproducir y adelantar, así que una persona hace varias peticiones.
PAGE_LIMIT = (30, 60.0)
VIDEO_LIMIT = (120, 60.0)
# Muchos enlaces que no existen seguidos = alguien rastreando: se bloquea esa IP un rato.
MISS_LIMIT = (10, 600.0)
BLOCK_S = 900.0
# Cuántos proxies de confianza hay delante (Cloud Run: 1). Con 0 se usa la IP de la conexión.
PROXY_HOPS_ENV = "VEXORA_PROXY_HOPS"


class Limiter:
    """Ventana deslizante por clave, más bloqueos temporales."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._blocked: dict[str, float] = {}

    def allow(self, scope: str, key: str, limit: tuple[int, float]) -> bool:
        """Cuenta una petición; False si ya se pasó del límite de la ventana."""
        count, window = limit
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault((scope, key), deque())
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= count:
                return False
            hits.append(now)
            self._sweep(now)
            return True

    def blocked_for(self, key: str) -> float:
        """Segundos que le quedan de bloqueo a `key` (0 si no está bloqueada)."""
        with self._lock:
            until = self._blocked.get(key, 0.0)
        return max(until - self.clock(), 0.0)

    def miss(self, key: str) -> None:
        """Un enlace que no existe: al pasar de MISS_LIMIT en la ventana, bloqueo de BLOCK_S."""
        if not self.allow("miss", key, MISS_LIMIT):
            with self._lock:
                self._blocked[key] = self.clock() + BLOCK_S

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._blocked.clear()

    def _sweep(self, now: float) -> None:
        """Olvida lo viejo de vez en cuando para que la memoria no crezca con IP que no vuelven."""
        if len(self._hits) < 5000:
            return
        longest = max(PAGE_LIMIT[1], VIDEO_LIMIT[1], MISS_LIMIT[1])
        for key in [k for k, hits in self._hits.items() if not hits or now - hits[-1] >= longest]:
            del self._hits[key]
        for key in [k for k, until in self._blocked.items() if until <= now]:
            del self._blocked[key]


def client_ip(forwarded: str | None, peer: str | None) -> str:
    """La IP de quien pide. Detrás de N proxies de confianza (VEXORA_PROXY_HOPS) es la N-ésima desde
    la derecha de X-Forwarded-For: las de la izquierda las puede inventar el cliente."""
    hops = int(os.environ.get(PROXY_HOPS_ENV, "0") or 0)
    chain = [part.strip() for part in (forwarded or "").split(",") if part.strip()]
    if hops > 0 and len(chain) >= hops:
        return chain[-hops]
    return peer or "desconocida"


public = Limiter()
