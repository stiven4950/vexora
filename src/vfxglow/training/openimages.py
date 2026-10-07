"""Fotos de Open Images V7 con cajas de la clase pedida (p. ej. /m/06y5r Sword).

Las cajas de Open Images son rectas; la hoja va en diagonal dentro de ellas. Dentro de cada caja
se busca la recta dominante (mapa de crestas + Hough) y esa da la caja rotada. Si no hay recta
pero la caja es muy alargada (espada horizontal o vertical), la caja misma vale. Si no, la foto
se descarta: mejor menos etiquetas que etiquetas malas.

Licencia: anotaciones CC BY 4.0, imágenes CC BY 2.0 (según Open Images; cada imagen trae su
autor en el CSV de metadatos). Guardar atribución si el modelo se distribuye.
"""

from __future__ import annotations

import csv
import logging
import random
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.models_store import ssl_context
from vfxglow.training.geometry import segment_to_obb
from vfxglow.training.pairs import Labeled
from vfxglow.training.task import OpenImagesSource

log = logging.getLogger("vfxglow.training")

BOX_URLS = {
    "train": "https://storage.googleapis.com/openimages/v6/oidv6-train-annotations-bbox.csv",
    "validation": "https://storage.googleapis.com/openimages/v5/validation-annotations-bbox.csv",
    "test": "https://storage.googleapis.com/openimages/v5/test-annotations-bbox.csv",
}
IMAGE_URL = "https://open-images-dataset.s3.amazonaws.com/{split}/{image}.jpg"
MAX_SIDE = 1280
# Caja ya alargada: se acepta tal cual si largo/ancho (en px) supera esto.
STRAIGHT_ASPECT = 3.5


def fetch_boxes(folder: Path, classes: list[str]) -> None:
    """Filtra los CSV de Open Images en streaming (el de train pesa 2,3 GB) y guarda solo las filas útiles."""
    folder.mkdir(parents=True, exist_ok=True)
    wanted = {f",{mid}," for mid in classes}
    for split, url in BOX_URLS.items():
        dest = folder / f"{split}-boxes.csv"
        if dest.exists():
            continue
        log.info("Filtrando cajas de %s (%s)", split, url)
        partial = dest.with_suffix(".csv.part")
        with urllib.request.urlopen(url, context=ssl_context()) as response, partial.open("w", encoding="utf-8") as out:
            for raw in response:
                line = raw.decode("utf-8")
                if any(tag in line for tag in wanted):
                    out.write(line)
        partial.replace(dest)


def fetch_images(folder: Path, cfg: OpenImagesSource, seed: int = 0) -> dict[str, list[tuple[str, Path, list[tuple[float, float, float, float]]]]]:
    """Descarga hasta `max_images` imágenes; devuelve por split (id, ruta, cajas normalizadas)."""
    out: dict[str, list] = {}
    rng = random.Random(seed)
    for split in BOX_URLS:
        rows = _read_boxes(folder / f"{split}-boxes.csv", cfg)
        images = sorted(rows)
        rng.shuffle(images)
        budget = cfg.max_images if split == "train" else max(cfg.max_images // 10, 50)
        images = images[:budget]
        target = folder / "images" / split
        target.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(16) as pool:
            paths = list(pool.map(lambda image: _download(split, image, target), images))
        out[split] = [(image, path, rows[image]) for image, path in zip(images, paths) if path is not None]
        log.info("Open Images %s: %d imágenes", split, len(out[split]))
    return out


def label_images(found, ridge_kernel) -> dict[str, list[Labeled]]:
    out: dict[str, list[Labeled]] = {}
    for split, items in found.items():
        labeled = []
        for image_id, path, boxes in items:
            image = cv2.imread(str(path))
            if image is None:
                continue
            obbs = [obb for obb in (box_to_obb(image, box, ridge_kernel) for box in boxes) if obb is not None]
            if obbs and len(obbs) == len(boxes):
                labeled.append(Labeled(source=f"openimages_{split}", frame=0, image=image, boxes=obbs, name=f"oi_{image_id}"))
        out[split] = labeled
        log.info("Open Images %s: %d imágenes con todas sus hojas ubicadas", split, len(labeled))
    return out


def box_to_obb(image: np.ndarray, box: tuple[float, float, float, float], kernel) -> np.ndarray | None:
    height, width = image.shape[:2]
    x0, x1, y0, y1 = box[0] * width, box[1] * width, box[2] * height, box[3] * height
    bw, bh = x1 - x0, y1 - y0
    if min(bw, bh) < 1:
        return None
    if max(bw, bh) / min(bw, bh) >= STRAIGHT_ASPECT:
        if bw >= bh:
            return segment_to_obb(np.array([x0, (y0 + y1) / 2]), np.array([x1, (y0 + y1) / 2]), bh)
        return segment_to_obb(np.array([(x0 + x1) / 2, y0]), np.array([(x0 + x1) / 2, y1]), bw)
    crop = cv2.cvtColor(image[int(y0) : int(y1), int(x0) : int(x1)], cv2.COLOR_BGR2GRAY).astype(np.float32)
    if crop.size == 0:
        return None
    ridge = np.maximum(cv2.morphologyEx(crop, cv2.MORPH_TOPHAT, kernel), cv2.morphologyEx(crop, cv2.MORPH_BLACKHAT, kernel))
    mask = (ridge > max(float(np.percentile(ridge, 92)), 15.0)).astype(np.uint8) * 255
    diagonal = float(np.hypot(bw, bh))
    lines = cv2.HoughLinesP(mask, 1, np.pi / 180, 40, minLineLength=int(diagonal * 0.55), maxLineGap=int(diagonal * 0.05))
    if lines is None:
        return None
    best = max(lines.reshape(-1, 4), key=lambda l: np.hypot(l[2] - l[0], l[3] - l[1]))
    a = np.array([best[0] + x0, best[1] + y0], dtype=np.float64)
    b = np.array([best[2] + x0, best[3] + y0], dtype=np.float64)
    return segment_to_obb(a, b)


def _read_boxes(path: Path, cfg: OpenImagesSource) -> dict[str, list[tuple[float, float, float, float]]]:
    """ImageID,Source,LabelName,Confidence,XMin,XMax,YMin,YMax,IsOccluded,IsTruncated,IsGroupOf,IsDepiction,IsInside"""
    rows: dict[str, list] = {}
    skip: set[str] = set()
    if not path.exists():
        return rows
    for row in csv.reader(path.open(encoding="utf-8")):
        if len(row) < 13 or row[2] not in cfg.classes:
            continue
        image = row[0]
        if (cfg.skip_groups and row[10] == "1") or (cfg.skip_depictions and row[11] == "1"):
            skip.add(image)
            continue
        rows.setdefault(image, []).append(tuple(float(v) for v in row[4:8]))
    return {image: boxes for image, boxes in rows.items() if image not in skip}


def _download(split: str, image: str, target: Path) -> Path | None:
    path = target / f"{image}.jpg"
    if path.exists():
        return path
    try:
        with urllib.request.urlopen(IMAGE_URL.format(split=split, image=image), context=ssl_context(), timeout=30) as response:
            data = np.frombuffer(response.read(), dtype=np.uint8)
    except OSError as exc:
        log.warning("No se pudo bajar %s (%s)", image, exc)
        return None
    picture = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if picture is None:
        return None
    scale = MAX_SIDE / max(picture.shape[:2])
    if scale < 1:
        picture = cv2.resize(picture, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), picture, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    return path
