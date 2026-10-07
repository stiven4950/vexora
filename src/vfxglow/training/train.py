"""Entrena con Ultralytics y exporta los pesos a models/ para el pipeline."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from vfxglow.training.task import Task

log = logging.getLogger("vfxglow.training")


def device(name: str) -> str:
    if name != "auto":
        return name
    import torch

    if torch.cuda.is_available():
        return "0"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def train(task: Task) -> Path:
    from ultralytics import YOLO

    data = task.dataset_dir / "data.yaml"
    if not data.exists():
        raise FileNotFoundError(f"Falta {data}: corre antes 'build'.")
    cfg = task.train
    model = YOLO(cfg.model)
    model.train(
        data=str(data),
        epochs=cfg.epochs,
        imgsz=cfg.imgsz,
        batch=cfg.batch,
        device=device(cfg.device),
        patience=cfg.patience,
        project=str(task.runs_dir.resolve()),
        name=task.name,
        exist_ok=True,
        plots=True,
    )
    best = task.runs_dir / task.name / "weights" / "best.pt"
    return export(task, best)


def export(task: Task, best: Path | None = None) -> Path:
    best = best or task.runs_dir / task.name / "weights" / "best.pt"
    if not best.exists():
        raise FileNotFoundError(f"No hay pesos entrenados en {best}")
    task.weights.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, task.weights)
    log.info("Pesos exportados a %s", task.weights)
    return task.weights
