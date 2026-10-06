"""Qué lleva cada persona en la cabeza: gafas, gafas de sol, máscara, gorra...

Es un atributo de la persona, no del fotograma: se clasifica pocas veces y la posición se
sigue con los puntos de los ojos en cada fotograma. Por persona se arma una hoja con
`crops` recortes de su cabeza repartidos en el video y se pide al VLM de `analysis.scene`
una lista por recorte. Los recortes contiguos con el mismo accesorio forman un tramo.

Un umbral de píxeles (ojos más oscuros que la mejilla) no sirve: a 720 px de ancho los ojos
miden ~17 px y el tono de piel confunde la medida. Sin clave de API solo cuenta `manual`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.error
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.schema import Accessory, FrameRecord
from vfxglow.analysis.scene_reader import _ask
from vfxglow.config import AccessoriesConfig, SceneConfig

log = logging.getLogger("vfxglow.accessories")

KINDS = ("sunglasses", "glasses", "mask", "hat", "cap", "headband", "hood", "earrings", "none")
CROP = 160

_PROMPT = """Cada imagen es una tira de recortes de la cabeza de UNA misma persona, numerados de izquierda a derecha desde 0.
Para cada recorte di qué lleva puesto en la cabeza o la cara. Usa solo estas etiquetas: {kinds}.
Responde SOLO un JSON: {{"crops": [["etiqueta", ...], ...]}} con una lista por recorte, en orden.
Si un recorte no deja ver la cara, usa []."""


def detect_accessories(
    video_path: Path,
    frames: list[FrameRecord],
    cache_dir: Path,
    cfg: AccessoriesConfig,
    scene: SceneConfig,
) -> list[Accessory]:
    if not cfg.enabled:
        return []
    last = max((record.frame for record in frames), default=0)
    found = [
        Accessory(person=person, kind=kind, start_frame=0, end_frame=last, source="manual")
        for person, kinds in cfg.manual.items()
        for kind in kinds
    ]
    key = os.environ.get(scene.api_key_env, "").strip()
    if not key:
        return found
    declared = set(cfg.manual)
    cap = cv2.VideoCapture(str(video_path))
    try:
        for person in sorted({p.person_id for record in frames for p in record.people} - declared):
            picks = _pick_frames(frames, person, cfg.crops)
            crops = [crop for crop in (_head_crop(cap, record, person) for record in picks) if crop is not None]
            if not crops:
                continue
            labels = _classify(crops, cache_dir, scene, key)
            if labels is None:
                continue
            found += _spans(person, [record.frame for record in picks], labels, last)
    finally:
        cap.release()
    log.info("Accesorios: %s", [(a.person, a.kind, a.start_frame, a.end_frame) for a in found] or "ninguno")
    return found


def _pick_frames(frames: list[FrameRecord], person: str, count: int) -> list[FrameRecord]:
    usable = [
        record
        for record in frames
        for p in record.people
        if p.person_id == person and _head_box(p) is not None
    ]
    if not usable:
        return []
    indexes = np.linspace(0, len(usable) - 1, min(count, len(usable))).round().astype(int)
    return [usable[i] for i in sorted(set(indexes))]


def _head_box(person) -> tuple[float, float, float] | None:
    """Centro (x, y) y lado del recorte de la cabeza, normalizados."""
    pts = {lm.name: (lm.x, lm.y) for lm in person.pose if lm.c > 0.5}
    if "nose" not in pts or "left_shoulder" not in pts or "right_shoulder" not in pts:
        return None
    shoulders = abs(pts["left_shoulder"][0] - pts["right_shoulder"][0])
    side = max(shoulders * 0.9, 0.06)
    return pts["nose"][0], pts["nose"][1] - side * 0.15, side


def _head_crop(cap: cv2.VideoCapture, record: FrameRecord, person: str) -> np.ndarray | None:
    target = next((p for p in record.people if p.person_id == person), None)
    box = _head_box(target) if target is not None else None
    if box is None:
        return None
    cap.set(cv2.CAP_PROP_POS_FRAMES, record.frame)
    ok, frame = cap.read()
    if not ok:
        return None
    height, width = frame.shape[:2]
    cx, cy, side = box[0] * width, box[1] * height, box[2] * width
    x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    crop = frame[y0 : int(cy + side / 2), x0 : int(cx + side / 2)]
    if crop.size == 0:
        return None
    return cv2.resize(crop, (CROP, CROP), interpolation=cv2.INTER_CUBIC)


def _classify(crops: list[np.ndarray], cache_dir: Path, scene: SceneConfig, key: str) -> list[list[str]] | None:
    strip = np.hstack(crops)
    for index in range(len(crops)):
        cv2.putText(strip, str(index), (index * CROP + 4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    ok, encoded = cv2.imencode(".jpg", strip, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        return None
    blob = encoded.tobytes()
    digest = hashlib.sha256(blob + scene.model.encode()).hexdigest()[:20]
    cached = cache_dir / f"accessories_{digest}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    try:
        text, _usage = _ask(scene, key, [blob], _PROMPT.format(kinds=", ".join(KINDS)))
        raw = json.loads(text).get("crops", [])
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
        log.warning("El VLM no clasificó los accesorios (%s); se omiten", exc)
        return None
    labels = [[str(item) for item in entry if str(item) in KINDS and item != "none"] for entry in raw if isinstance(entry, list)]
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(labels), encoding="utf-8")
    return labels


def _spans(person: str, picks: list[int], labels: list[list[str]], last: int) -> list[Accessory]:
    """Cada recorte cubre hasta la mitad del camino hacia sus vecinos."""
    if not labels:
        return []
    picks = picks[: len(labels)]
    edges = [0] + [(a + b) // 2 for a, b in zip(picks, picks[1:])] + [last]
    spans: list[Accessory] = []
    for kind in sorted({k for entry in labels for k in entry}):
        start = None
        for index, entry in enumerate(labels):
            if kind in entry and start is None:
                start = edges[index]
            if kind not in entry and start is not None:
                spans.append(Accessory(person=person, kind=kind, start_frame=start, end_frame=edges[index] - 1))
                start = None
        if start is not None:
            spans.append(Accessory(person=person, kind=kind, start_frame=start, end_frame=last))
    return spans
