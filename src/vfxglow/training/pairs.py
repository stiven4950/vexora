"""Etiquetas a partir de pares original/glow: lo que pintó el editor marca dónde está el objeto.

Extractor `blade_from_glow`: en la diferencia entre los dos fotogramas, las manchas rectas y
alargadas que nacen junto a una muñeca son hojas pintadas encima de la hoja real. Se descartan
los arcos (poco rellenos), las siluetas (no alargadas) y las copias fantasma (lejos de la mano).
La versión con glow puede venir reencuadrada (video_38 está acercada ~25% con un zoom que cambia
en el tiempo): cada fotograma se alinea con el original (ECC afín) antes de compararlos.

Un fotograma sin ninguna hoja pintada se omite: no se puede saber si la hoja no está o si el
editor no la pintó (video_39 deja las katanas sin pintar al final).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.schema import FrameRecord
from vfxglow.training.task import PairSource

log = logging.getLogger("vfxglow.training")

# Diferencia (0-255) que cuenta como pintado en el núcleo del trazo.
CORE_DIFF = 70
# Una hoja: largo/ancho mínimo, relleno mínimo de su caja rotada, largo mínimo (torsos) y
# distancia máxima de un extremo a una muñeca (torsos).
MIN_ASPECT = 5.0
MIN_FILL = 0.35
MIN_LENGTH = 0.3
# La prolongación de la hoja pasa a menos de MAX_PERP torsos de una muñeca y su extremo cercano
# queda a menos de MAX_GAP (el mango de una katana separa la hoja de la mano).
MAX_PERP = 0.35
MAX_GAP = 1.1
# El trazo pintado incluye un halo ancho: la forma se mide con los píxeles más brillantes de la
# mancha (por encima de este percentil de su propia diferencia).
CORE_PERCENTILE = 60
# Calidad: fracción mínima del segmento con una cresta real en el original (la hoja física
# debajo de la pintura) y fracción máxima del cuadro pintada (una silueta de cuerpo entero
# hace que el brazo parezca hoja pintada).
MIN_REAL = 0.35
MAX_PAINTED = 0.12
# El neón incluye el halo: el ancho de la caja se reduce a esta fracción.
CORE_WIDTH = 0.6


@dataclass
class Labeled:
    source: str
    frame: int
    image: np.ndarray
    boxes: list[np.ndarray]
    name: str = ""

    @property
    def key(self) -> str:
        return self.name or f"{self.source}_f{self.frame:06d}"


def find_run(original: Path) -> Path | None:
    """El run de vfxglow cuyo video es este original."""
    for manifest in sorted(Path("runs").glob(f"{original.stem}-*/manifest.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if Path(data.get("video_path", "")).resolve() == original.resolve():
            return manifest.parent
    return None


def label_pair(source: PairSource, stride: int) -> list[Labeled]:
    extractor = EXTRACTORS.get(source.extractor)
    if extractor is None:
        raise ValueError(f"Extractor desconocido: {source.extractor}. Disponibles: {', '.join(EXTRACTORS)}")
    run = Path(source.run) if source.run else find_run(Path(source.original))
    if run is None:
        raise FileNotFoundError(f"No hay análisis de {source.original}. Corre antes: vfxglow analyze --video {source.original}")
    tracks = [FrameRecord.model_validate_json(line) for line in (run / "analysis" / "tracks.jsonl").open(encoding="utf-8")]
    original, reference = cv2.VideoCapture(source.original), cv2.VideoCapture(source.reference)
    out: list[Labeled] = []
    aligner = Aligner()
    for index, record in enumerate(tracks):
        ok_a, frame = original.read()
        ok_b, painted = reference.read()
        if not (ok_a and ok_b):
            break
        painted = aligner(frame, painted)
        if index % max(stride, 1) or painted is None:
            continue
        boxes = extractor(frame, painted, record)
        if boxes:
            out.append(Labeled(source=source.name, frame=index, image=frame, boxes=boxes))
    log.info("%s: %d fotogramas etiquetados, %d hojas", source.name, len(out), sum(len(item.boxes) for item in out))
    return out


# Correlación mínima del registro: por debajo, el fotograma no se usa (corte, efecto que tapa todo).
MIN_ECC = 0.6
_ALIGN_SIZE = (360, 640)


class Aligner:
    """Lleva cada fotograma de la referencia a las coordenadas del original (ECC afín).

    Arranca del ajuste del fotograma anterior: el reencuadre cambia despacio.
    """

    def __init__(self) -> None:
        self.warp = np.eye(2, 3, dtype=np.float32)

    def __call__(self, frame: np.ndarray, painted: np.ndarray) -> np.ndarray | None:
        height, width = frame.shape[:2]
        sx, sy = _ALIGN_SIZE[0] / width, _ALIGN_SIZE[1] / height
        small_a = cv2.cvtColor(cv2.resize(frame, _ALIGN_SIZE), cv2.COLOR_BGR2GRAY).astype(np.float32)
        small_b = cv2.cvtColor(cv2.resize(painted, _ALIGN_SIZE), cv2.COLOR_BGR2GRAY).astype(np.float32)
        warp = self.warp.copy()
        try:
            score, warp = cv2.findTransformECC(
                small_a, small_b, warp, cv2.MOTION_AFFINE,
                (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5), None, 5,
            )
        except cv2.error:
            return None
        if score < MIN_ECC:
            return None
        self.warp = warp
        full = warp.copy()
        full[0, 2] /= sx
        full[1, 2] /= sy
        full[0, 1] *= sx / sy
        full[1, 0] *= sy / sx
        return cv2.warpAffine(painted, full, (width, height), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)


def blade_from_glow(frame: np.ndarray, painted: np.ndarray, record: FrameRecord) -> list[np.ndarray]:
    """Barrido de rayos desde cada mano sobre el mapa de lo pintado (el mismo de la detección).

    Analizar manchas no basta: la hoja pintada se une a llamas y arcos, y su halo la ensancha.
    Los rayos solo siguen la franja recta que sale de la mano.
    """
    from vfxglow.analysis import blades as B
    from vfxglow.training.geometry import segment_to_obb

    height, width = frame.shape[:2]
    valid = painted.max(axis=2) > 0  # fuera del encuadre alineado no hay datos
    diff = np.abs(painted.astype(np.int16) - frame.astype(np.int16)).max(axis=2).astype(np.float32)
    diff[cv2.erode(valid.astype(np.uint8), np.ones((15, 15), np.uint8)) == 0] = 0
    if float((diff > CORE_DIFF).mean()) > MAX_PAINTED:
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    ridge = np.maximum(cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, B._KERNEL), cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, B._KERNEL))
    ridge_thr = max(float(np.percentile(ridge, 90)), 15.0)
    people = record.people or ([None] if record.pose else [])
    found: list[tuple[np.ndarray, np.ndarray]] = []
    for person in people:
        pose = person.pose if person is not None else record.pose
        pts = {lm.name: np.array([lm.x * width, lm.y * height]) for lm in pose if lm.c > 0.3}
        torso = B._torso(pts)
        if torso is None:
            continue
        for side in ("left", "right"):
            wrist, elbow = pts.get(f"{side}_wrist"), pts.get(f"{side}_elbow")
            if wrist is None:
                continue
            hand = B._hand(person, side, width, height) if person is not None else None
            grip = hand["center"] if hand else wrist
            best = B._best_line(diff, grip, B._grip_direction(hand, wrist, elbow), elbow, torso)
            if best is None:
                continue
            hilt, tip = best[0], best[1]
            if np.linalg.norm(tip - hilt) < MIN_LENGTH * torso:
                continue
            if _support(ridge, hilt, tip, ridge_thr) < MIN_REAL:
                continue
            if any(_same(hilt, tip, h, t, torso) for h, t in found):
                continue  # la misma hoja tomada con las dos manos
            found.append((hilt, tip))
    return [segment_to_obb(h, t) for h, t in found]


def _support(ridge: np.ndarray, a: np.ndarray, b: np.ndarray, threshold: float) -> float:
    """Fracción del segmento con cresta en el original (máximo en una banda de ±3 px)."""
    height, width = ridge.shape
    u = (b - a) / max(float(np.linalg.norm(b - a)), 1e-6)
    n = np.array([-u[1], u[0]])
    t = np.linspace(0.1, 0.95, 30)[:, None]
    hits = np.zeros(30, dtype=bool)
    for off in (-3, 0, 3):
        pts = a + (b - a) * t + n * off
        inside = (pts[:, 0] >= 0) & (pts[:, 0] < width) & (pts[:, 1] >= 0) & (pts[:, 1] < height)
        vals = np.zeros(30)
        vals[inside] = ridge[pts[inside, 1].astype(int), pts[inside, 0].astype(int)]
        hits |= vals > threshold
    return float(hits.mean())


def _same(a0: np.ndarray, a1: np.ndarray, b0: np.ndarray, b1: np.ndarray, torso: float) -> bool:
    mid = float(np.linalg.norm((a0 + a1) / 2 - (b0 + b1) / 2))
    da, db = a1 - a0, b1 - b0
    cos = abs(float(da @ db)) / max(float(np.linalg.norm(da) * np.linalg.norm(db)), 1e-6)
    return mid < 0.3 * torso and cos > np.cos(np.radians(15))


def _held(a: np.ndarray, b: np.ndarray, wrist: np.ndarray, torso: float) -> bool:
    u = (b - a) / max(float(np.linalg.norm(b - a)), 1e-6)
    perp = abs(float((wrist - a) @ np.array([-u[1], u[0]])))
    gap = min(float(np.linalg.norm(a - wrist)), float(np.linalg.norm(b - wrist)))
    # La muñeca no puede quedar en medio de la hoja: debe estar más allá de un extremo.
    along = float((wrist - a) @ u)
    beyond = along <= 0.15 * np.linalg.norm(b - a) or along >= 0.85 * np.linalg.norm(b - a)
    return perp <= MAX_PERP * torso and gap <= MAX_GAP * torso and beyond


def _long_axis(corners: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from vfxglow.training.geometry import obb_to_segment

    return obb_to_segment(corners)


def _wrists(record: FrameRecord, width: int, height: int) -> tuple[list[np.ndarray], float | None]:
    people = record.people or []
    poses = [p.pose for p in people] or ([record.pose] if record.pose else [])
    wrists, torsos = [], []
    for pose in poses:
        pts = {lm.name: np.array([lm.x * width, lm.y * height]) for lm in pose if lm.c > 0.3}
        wrists += [pts[name] for name in ("left_wrist", "right_wrist") if name in pts]
        for side in ("left", "right"):
            if f"{side}_shoulder" in pts and f"{side}_hip" in pts:
                torsos.append(float(np.linalg.norm(pts[f"{side}_shoulder"] - pts[f"{side}_hip"])))
                break
    return wrists, (max(np.median(torsos), 20.0) if torsos else None)


EXTRACTORS = {"blade_from_glow": blade_from_glow}
