"""Definición de una tarea de entrenamiento (training/tasks/<nombre>.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairSource(_Strict):
    """Video original + versión con glow del mismo plano: las etiquetas salen de la diferencia."""

    name: str
    original: str
    reference: str
    # Run de vfxglow con el análisis del original (para las muñecas). Vacío: se busca en runs/.
    run: str = ""
    # Extractor de etiquetas a partir de lo pintado (registrado en training/pairs.py).
    extractor: str = "blade_from_glow"


class OpenImagesSource(_Strict):
    enabled: bool = True
    # Clases de Open Images (MID): /m/06y5r Sword, /m/02gzp Dagger.
    classes: list[str] = Field(default_factory=lambda: ["/m/06y5r"])
    max_images: int = 1500
    skip_depictions: bool = True
    skip_groups: bool = True


class VideoSource(_Strict):
    """Video sin glow: se pre-etiqueta con el detector actual y se revisa a mano."""

    name: str
    video: str
    run: str = ""


class AugmentConfig(_Strict):
    # Copias con desenfoque de movimiento: enseñan cómo se ve una hoja girando rápido.
    motion_blur_copies: int = 1
    motion_blur_px: tuple[int, int] = (9, 31)


class TrainConfig(_Strict):
    model: str = "yolo11n-obb.pt"
    epochs: int = 80
    imgsz: int = 960
    batch: int = 8
    device: str = "auto"
    patience: int = 20


class Task(_Strict):
    name: str
    type: Literal["obb"] = "obb"
    classes: list[str]
    # Fotogramas que se saltan en videos: los consecutivos son casi iguales.
    frame_stride: int = 2
    # Nombres de fuentes (pares o videos) que van a validación y nunca al entrenamiento.
    holdout: list[str] = Field(default_factory=list)
    pairs: list[PairSource] = Field(default_factory=list)
    openimages: OpenImagesSource = Field(default_factory=OpenImagesSource)
    videos: list[VideoSource] = Field(default_factory=list)
    augment: AugmentConfig = Field(default_factory=AugmentConfig)
    train: TrainConfig = Field(default_factory=TrainConfig)

    @property
    def root(self) -> Path:
        return Path("training")

    @property
    def data_dir(self) -> Path:
        """Descargas y etiquetas intermedias (no se versiona)."""
        return self.root / "data"

    @property
    def dataset_dir(self) -> Path:
        return self.root / "datasets" / self.name

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def review_dir(self) -> Path:
        return self.root / "review" / self.name

    @property
    def weights(self) -> Path:
        """Pesos exportados que usa el pipeline."""
        return Path("models") / f"{self.name}-{self.type}.pt"


def load_task(path: Path) -> Task:
    return Task.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
