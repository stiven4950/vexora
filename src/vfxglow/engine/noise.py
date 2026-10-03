"""Ruido de valor 3D. La tercera coordenada es el tiempo, así el fuego evoluciona."""

from __future__ import annotations

import numpy as np


class ValueNoise:
    def __init__(self, seed: int) -> None:
        rng = np.random.default_rng(seed & 0xFFFFFFFF)
        self.perm = rng.permutation(256).astype(np.int32)
        self.grad = rng.random(256).astype(np.float32)

    def _lattice(self, ix: np.ndarray, iy: np.ndarray, iz: np.ndarray) -> np.ndarray:
        h = self.perm[ix & 255]
        h = self.perm[(h + (iy & 255)) & 255]
        h = self.perm[(h + (iz & 255)) & 255]
        return self.grad[h]

    def noise(self, x: np.ndarray, y: np.ndarray, z: float) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32)
        x0 = np.floor(x).astype(np.int32)
        y0 = np.floor(y).astype(np.int32)
        z0 = int(np.floor(z))
        xf = x - x0
        yf = y - y0
        zf = np.float32(z - z0)
        u = xf * xf * (3.0 - 2.0 * xf)
        v = yf * yf * (3.0 - 2.0 * yf)
        w = zf * zf * (3.0 - 2.0 * zf)
        n000 = self._lattice(x0, y0, np.int32(z0))
        n100 = self._lattice(x0 + 1, y0, np.int32(z0))
        n010 = self._lattice(x0, y0 + 1, np.int32(z0))
        n110 = self._lattice(x0 + 1, y0 + 1, np.int32(z0))
        n001 = self._lattice(x0, y0, np.int32(z0 + 1))
        n101 = self._lattice(x0 + 1, y0, np.int32(z0 + 1))
        n011 = self._lattice(x0, y0 + 1, np.int32(z0 + 1))
        n111 = self._lattice(x0 + 1, y0 + 1, np.int32(z0 + 1))
        nx00 = n000 * (1 - u) + n100 * u
        nx10 = n010 * (1 - u) + n110 * u
        nx01 = n001 * (1 - u) + n101 * u
        nx11 = n011 * (1 - u) + n111 * u
        nxy0 = nx00 * (1 - v) + nx10 * v
        nxy1 = nx01 * (1 - v) + nx11 * v
        return (nxy0 * (1 - w) + nxy1 * w) * 2.0 - 1.0

    def fbm(self, x: np.ndarray, y: np.ndarray, z: float, octaves: int) -> np.ndarray:
        total = np.zeros_like(np.asarray(x, dtype=np.float32), dtype=np.float32)
        amp = 1.0
        freq = 1.0
        norm = 0.0
        zz = z
        for _ in range(max(octaves, 1)):
            total = total + amp * self.noise(np.asarray(x) * freq, np.asarray(y) * freq, zz)
            norm += amp
            amp *= 0.5
            freq *= 2.0
            zz *= 1.7
        return total / max(norm, 1e-6)

    def scalar(self, x: float, y: float, z: float, octaves: int = 1) -> float:
        return float(self.fbm(np.float32(x), np.float32(y), z, octaves))
