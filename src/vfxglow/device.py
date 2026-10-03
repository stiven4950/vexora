"""Selección de dispositivo: cuda, luego mps, luego cpu."""

from __future__ import annotations


def cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def mps_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    backend = getattr(torch.backends, "mps", None)
    if backend is None:
        return False
    try:
        return bool(backend.is_available())
    except Exception:
        return False


def detect_device() -> str:
    """Elige el mejor dispositivo disponible sin exigir PyTorch."""
    if cuda_available():
        return "cuda"
    if mps_available():
        return "mps"
    return "cpu"


def resolve_device(preference: str) -> str:
    """Resuelve `auto` o valida un dispositivo pedido de forma explícita."""
    if preference == "auto":
        return detect_device()
    if preference == "cuda" and not cuda_available():
        raise RuntimeError("Se pidió CUDA y no hay una GPU NVIDIA disponible.")
    if preference == "mps" and not mps_available():
        raise RuntimeError("Se pidió MPS y este equipo no lo ofrece.")
    if preference not in {"cpu", "mps", "cuda"}:
        raise RuntimeError(f"Dispositivo desconocido: {preference}")
    return preference


def require_cuda(feature: str, device: str) -> None:
    """Falla al inicio si una función exclusiva de CUDA se pidió sin GPU NVIDIA."""
    if device != "cuda":
        raise RuntimeError(
            f"{feature} requiere CUDA y el dispositivo actual es '{device}'. "
            "Desactiva esa opción o ejecuta el pipeline en una máquina con GPU NVIDIA."
        )
