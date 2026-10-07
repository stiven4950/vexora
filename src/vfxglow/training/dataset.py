"""Arma el dataset YOLO-OBB a partir de las etiquetas revisadas.

training/datasets/<tarea>/images/{train,val}/*.jpg
training/datasets/<tarea>/labels/{train,val}/*.txt   (clase + 4 esquinas normalizadas)
training/datasets/<tarea>/data.yaml, manifest.json

Validación: las fuentes en `holdout` y la parte "validation/test" de Open Images. Nunca se
reparten fotogramas de un mismo video entre entrenamiento y validación: serían casi iguales y
la medida saldría inflada.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections import Counter

import cv2
import numpy as np
import yaml

from vfxglow.training import store
from vfxglow.training.geometry import yolo_obb_line
from vfxglow.training.task import Task

log = logging.getLogger("vfxglow.training")


def build(task: Task, seed: int = 0) -> Counter:
    root = task.dataset_dir
    if root.exists():
        shutil.rmtree(root)
    rng = np.random.default_rng(seed)
    counts: Counter = Counter()
    for folder in sorted((task.data_dir / "labels" / task.name).glob("*")):
        source = folder.name
        bad = store.rejected(task.review_dir / source)
        split = "val" if source in task.holdout or source in {"openimages_validation", "openimages_test"} else "train"
        for row in store.load(folder):
            if row["key"] in bad:
                counts[(source, "rechazada")] += 1
                continue
            image = cv2.imread(str(folder / f"{row['key']}.jpg"))
            if image is None:
                continue
            boxes = [np.array(b) for b in row["boxes"]]
            _write(root, split, row["key"], image, boxes)
            counts[(source, split)] += 1
            if split == "train":
                for k in range(task.augment.motion_blur_copies):
                    _write(root, split, f"{row['key']}_blur{k}", motion_blur(image, rng, task.augment.motion_blur_px), boxes)
                    counts[(source, "train_blur")] += 1
    names = dict(enumerate(task.classes))
    (root / "data.yaml").write_text(
        yaml.safe_dump({"path": str(root.resolve()), "train": "images/train", "val": "images/val", "names": names}, sort_keys=False),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(json.dumps({f"{s}/{k}": v for (s, k), v in sorted(counts.items())}, indent=1), encoding="utf-8")
    log.info("Dataset %s: %s", task.name, dict(counts))
    return counts


def _write(root, split: str, key: str, image: np.ndarray, boxes: list[np.ndarray]) -> None:
    images, labels = root / "images" / split, root / "labels" / split
    images.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    height, width = image.shape[:2]
    cv2.imwrite(str(images / f"{key}.jpg"), image, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
    (labels / f"{key}.txt").write_text("\n".join(yolo_obb_line(0, b, width, height) for b in boxes) + "\n", encoding="utf-8")


def motion_blur(image: np.ndarray, rng: np.random.Generator, size: tuple[int, int]) -> np.ndarray:
    """Desenfoque lineal en una dirección al azar: como una hoja (o la cámara) moviéndose rápido."""
    length = int(rng.integers(size[0], size[1] + 1)) | 1
    kernel = np.zeros((length, length), dtype=np.float32)
    kernel[length // 2, :] = 1.0
    rot = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), float(rng.uniform(0, 180)), 1.0)
    kernel = cv2.warpAffine(kernel, rot, (length, length))
    kernel /= max(float(kernel.sum()), 1e-6)
    return cv2.filter2D(image, -1, kernel)
