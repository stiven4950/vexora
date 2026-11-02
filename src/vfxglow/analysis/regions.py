"""Qué es cada píxel: fondo, pelo, piel, cara o prenda (segmentador multiclase de MediaPipe).

Sirve a los efectos que llenan el espacio alrededor del rostro (engine/ambient_fx.py). Solo se calcula
si el guion usa uno de ellos (Pipeline._engine): cuesta ~130 ms por fotograma en CPU, y baile y peleas
no deben pagarlo. Queda en `analysis/regions/` como un PNG de etiquetas por fotograma.

clean_labels corrige lo que falla en videos reales (facial_2, facial_3): el modelo parte una prenda
entre "ropa" y "otros", deja manchas sueltas sobre la cabeza y toma por ropa un logo sobre el pelo.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("vfxglow")

MODEL = "selfie_multiclass.tflite"
BACKGROUND, HAIR, SKIN, FACE, GARMENT = 0, 1, 2, 3, 4
# Clases del modelo que no se conservan tal cual.
MODEL_CLOTHES, MODEL_OTHER = 4, 5
# El lado mayor de lo que se guarda: el modelo trabaja a 256 px, más no agrega detalle.
MAX_SIDE = 512
# Fracción mínima del cuadro para que algo cuente como prenda: en un primer plano (facial_2) solo
# asoma un trozo de camiseta y el logo de TikTok.
MIN_GARMENT = 0.04
CLOSE = np.ones((5, 5), np.uint8)
DONE = "done"
# Suavizado del borde de la persona, en píxeles del cuadro.
PERSON_SOFT = 2.5


def _largest(mask: np.ndarray) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if count <= 1:
        return np.zeros(mask.shape, bool)
    return labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))


def clean_labels(raw: np.ndarray) -> np.ndarray:
    """Las clases del modelo → BACKGROUND/HAIR/SKIN/FACE/GARMENT, con una persona y una prenda."""
    out = raw.astype(np.uint8).copy()
    out[~_largest(raw > 0)] = BACKGROUND
    cloth = (out == MODEL_CLOTHES) | (out == MODEL_OTHER)
    # "Otros" fuera de la prenda es casi siempre una mancha pegada al pelo: cortaba el portal (facial_3,
    # 9,4 s). La ropa que no resulte ser la prenda sigue siendo la persona.
    out[out == MODEL_OTHER] = BACKGROUND
    out[out == MODEL_CLOTHES] = SKIN
    joined = cv2.morphologyEx(cloth.astype(np.uint8), cv2.MORPH_CLOSE, CLOSE) > 0
    garment = _largest(joined) & cloth
    if garment.mean() >= MIN_GARMENT:
        out[garment] = GARMENT
    return out


def ensure_regions(video_path: Path, run_dir: Path, models_dir: Path) -> Path:
    """Las etiquetas de todo el video; si ya están, no hace nada."""
    target = Path(run_dir) / "analysis" / "regions"
    if (target / DONE).exists():
        return target
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import ImageSegmenter, ImageSegmenterOptions, RunningMode

    from vfxglow.analysis.models_store import ensure_model
    from vfxglow.io.video import VideoReader

    log.info("Separando ropa, pelo y fondo")
    part = target.with_name("regions.part")
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    options = ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=str(ensure_model(models_dir, MODEL))),
        running_mode=RunningMode.VIDEO,
        output_category_mask=True,
    )
    reader = VideoReader(video_path)
    fps = reader.meta.fps
    with ImageSegmenter.create_from_options(options) as segmenter:
        for index, frame in reader:
            ratio = MAX_SIDE / max(frame.shape[:2])
            small = cv2.resize(frame, None, fx=ratio, fy=ratio, interpolation=cv2.INTER_AREA) if ratio < 1.0 else frame
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
            result = segmenter.segment_for_video(image, int(index * 1000 / fps))
            labels = clean_labels(result.category_mask.numpy_view().squeeze())
            cv2.imwrite(str(part / f"{index:06d}.png"), labels)
    (part / DONE).touch()
    shutil.rmtree(target, ignore_errors=True)
    part.rename(target)
    return target


def load_regions(run_dir: Path | None, index: int, width: int, height: int) -> np.ndarray | None:
    """Las etiquetas de un fotograma al tamaño del cuadro, o None si no están calculadas."""
    if run_dir is None:
        return None
    labels = cv2.imread(str(Path(run_dir) / "analysis" / "regions" / f"{index:06d}.png"), cv2.IMREAD_GRAYSCALE)
    if labels is None:
        return None
    if labels.shape[:2] != (height, width):
        labels = cv2.resize(labels, (width, height), interpolation=cv2.INTER_NEAREST)
    return labels


def person_mask(labels: np.ndarray) -> np.ndarray:
    """La persona, 0-1, con el borde suave: el modelo trabaja a 256 px y al ampliar queda escalonado."""
    return cv2.GaussianBlur((labels > BACKGROUND).astype(np.float32), (0, 0), PERSON_SOFT)
