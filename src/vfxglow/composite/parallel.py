"""Composición en paralelo con escritura en orden.

El motor es con estado y corre en el hilo principal; componer cada fotograma (composite_frame) es
puro y escala con los hilos. Los resultados salen siempre en el orden de envío y se escriben en el
hilo que llama, que es el único que toca el codificador."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np


class OrderedFrames:
    """`submit(fn, *args)` calcula `fn(*args)` y lo entrega a `write` en orden de envío."""

    def __init__(self, threads: int, write: Callable[[np.ndarray], None]) -> None:
        self.threads = threads
        self._write = write
        self._pool = ThreadPoolExecutor(threads) if threads > 1 else None
        self._pending: deque[Future] = deque()

    def submit(self, fn: Callable[..., np.ndarray], *args) -> None:
        if self._pool is None:
            self._write(fn(*args))
            return
        self._pending.append(self._pool.submit(fn, *args))
        # Cada fotograma en vuelo retiene cientos de MB de capas: la cola tiene tope.
        while len(self._pending) > self.threads + 2:
            self._write(self._pending.popleft().result())

    def drain(self) -> None:
        while self._pending:
            self._write(self._pending.popleft().result())

    def __enter__(self) -> OrderedFrames:
        return self

    def __exit__(self, *exc_info) -> None:
        # También con error o cancelación: no se escribe nada más, solo se suelta el trabajo pendiente.
        self._pending.clear()
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
