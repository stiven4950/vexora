"""Trazos de la prenda para el estilo desfile (docs/referencias/video_46.md): lo que un creador delinea
de la ropa, cuadro a cuadro.

Por cada fotograma, con el segmentador multiclase de MediaPipe (las seis clases, sin la limpieza de
analysis/regions.py, que descarta "otros", justo donde caen zapatos, bolsos y gorras):

- border: la frontera entre la prenda y la piel (ruedo del abrigo contra la pierna, cintura del crop
  top) o entre la prenda y el calzado (la caña de la bota).
- accessory: el contorno de lo que el modelo llama "otros": calzado, bolsos, gorras.
- inner: bordes largos dentro de la prenda (costuras, solapas, franjas, cierres, el acolchado), de la
  imagen a tamaño real.

El modelo trabaja a 256 px: cada punto de una frontera se corre al borde más fuerte de la imagen a
pocos píxeles (`snap`), así la línea cae sobre la tela y no sobre el escalón de la máscara. Cada
trazo lleva un `id` que se conserva de un cuadro al siguiente (se empareja por clase, posición y
largo) y vuelve a empezar en cada corte: el efecto puede quedarse con los mismos trazos toda la toma.

Solo se calcula si el guion lo pide (Pipeline._engine). Queda en `analysis/garment.jsonl`: una línea
por fotograma con sus trazos en coordenadas 0-1.

Mejora anotada (decisión del usuario, 2026-11-02): recortar cada prenda con SAM 2 para un contorno casi
perfecto, a ~0,9 s por cuadro.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("vfxglow")

MODEL = "selfie_multiclass.tflite"
BACKGROUND, HAIR, BODY_SKIN, FACE_SKIN, CLOTHES, OTHER = range(6)
FILE = "garment.jsonl"
# El lado mayor con el que se segmenta (el modelo trabaja a 256 px; más no agrega detalle).
SEG_SIDE = 512
# Largo mínimo de un trazo (fracción del alto del cuadro) y cuántos de cada clase se guardan.
MIN_LENGTH = {"border": 0.05, "accessory": 0.04, "inner": 0.09}
KEEP = {"border": 6, "accessory": 6, "inner": 10}
# Un accesorio más chico que esto (fracción del cuadro) es ruido; uno en la parte alta de la persona
# (esta fracción de su alto) es pelo o gorra.
MIN_ACCESSORY = 0.0015
HEAD_ZONE = 0.22
# Ajuste al borde real: hasta cuántos píxeles se mueve cada punto, y el desenfoque previo.
SNAP_PX = 6
# Bordes de la imagen dentro de la prenda (Canny) y cuánto se achica la prenda para no tomar su silueta.
CANNY = (40, 110)
INNER_ERODE = 9
# Emparejar trazos entre cuadros: distancia media máxima de sus puntos (fracción del alto) y cuántos
# cuadros puede faltar un trazo sin perder su id.
TRACK_DIST = 0.025
TRACK_MISS = 4
# Puntos máximos de cada trazo guardado.
POINTS = 48


def _resample(curve: np.ndarray, n: int) -> np.ndarray:
    seg = np.linalg.norm(np.diff(curve, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    if acc[-1] < 1e-6:
        return curve[:1].repeat(n, axis=0)
    q = np.linspace(0.0, acc[-1], n)
    return np.stack([np.interp(q, acc, curve[:, 0]), np.interp(q, acc, curve[:, 1])], axis=1)


def _length(curve: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(curve, axis=0), axis=1).sum()) if len(curve) > 1 else 0.0


def snap(curve: np.ndarray, gradient: np.ndarray, reach: int = SNAP_PX) -> np.ndarray:
    """Cada punto, corrido a lo largo de su normal hasta el borde más fuerte a `reach` píxeles."""
    if len(curve) < 3:
        return curve
    h, w = gradient.shape
    tangent = np.gradient(curve, axis=0)
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-6)
    steps = np.arange(-reach, reach + 1, dtype=np.float64)
    probes = curve[:, None, :] + normal[:, None, :] * steps[None, :, None]
    xs = np.clip(np.round(probes[..., 0]).astype(int), 0, w - 1)
    ys = np.clip(np.round(probes[..., 1]).astype(int), 0, h - 1)
    best = np.argmax(gradient[ys, xs] - np.abs(steps)[None, :] * 0.02 * gradient.max(), axis=1)
    moved = probes[np.arange(len(curve)), best]
    # Suavizado a lo largo: el borde de la tela no salta de un píxel al otro.
    kernel = np.ones(5) / 5.0
    padded = np.pad(moved, ((2, 2), (0, 0)), mode="edge")
    return np.stack([np.convolve(padded[:, k], kernel, mode="valid") for k in range(2)], axis=1)


def _chains(mask: np.ndarray, min_px: float, closed: bool = False) -> list[np.ndarray]:
    """Las líneas de una máscara de bordes (o el contorno de una región, con `closed`)."""
    mode = cv2.RETR_EXTERNAL if closed else cv2.RETR_LIST
    contours, _ = cv2.findContours(mask.astype(np.uint8), mode, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in contours:
        curve = c[:, 0, :].astype(np.float64)
        if not closed and len(curve) > 4:
            # Un borde fino vuelve sobre sí mismo (findContours da las dos caras): se queda una.
            half = len(curve) // 2
            curve = curve[: half + 1]
        if _length(curve) >= min_px:
            out.append(curve)
    return out


def frame_strokes(frame: np.ndarray, categories: np.ndarray) -> list[dict]:
    """Los trazos de un fotograma: (clase, curva en píxeles, puntaje)."""
    h, w = frame.shape[:2]
    cat = cv2.resize(categories, (w, h), interpolation=cv2.INTER_NEAREST)
    cat = cv2.medianBlur(cat.astype(np.uint8), 5)
    clothes, other = cat == CLOTHES, cat == OTHER
    skin = (cat == BODY_SKIN) | (cat == FACE_SKIN)
    gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    gradient = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    ring = np.ones((5, 5), np.uint8)
    strokes: list[dict] = []
    # Fronteras: prenda contra piel y prenda contra calzado/accesorio.
    grown = cv2.dilate(clothes.astype(np.uint8), ring)
    for neighbour in (skin, other):
        edge = grown & cv2.dilate(neighbour.astype(np.uint8), ring)
        edge = cv2.ximgproc.thinning(edge * 255) if hasattr(cv2, "ximgproc") else cv2.Canny(edge * 255, 50, 150)
        for curve in _chains(edge > 0, MIN_LENGTH["border"] * h):
            strokes.append({"kind": "border", "curve": snap(curve, gradient)})
    # Accesorios: el contorno de cada "otros" (calzado, bolso), cerrado. Lo de la parte alta de la
    # persona es pelo o gorra: ahí va la pieza de cabeza, no un contorno.
    blobs = cv2.morphologyEx(other.astype(np.uint8), cv2.MORPH_OPEN, ring)
    rows = np.nonzero((cat > 0).any(axis=1))[0]
    head_line = rows.min() + HEAD_ZONE * (rows.max() - rows.min()) if len(rows) else 0.0
    for curve in _chains(blobs, MIN_LENGTH["accessory"] * h, closed=True):
        if curve[:, 1].mean() < head_line:
            continue
        if cv2.contourArea(curve.astype(np.float32)) >= MIN_ACCESSORY * h * w:
            strokes.append({"kind": "accessory", "curve": snap(np.vstack([curve, curve[:1]]), gradient)})
    # Bordes de la imagen dentro de la prenda.
    inside = cv2.erode(clothes.astype(np.uint8), np.ones((INNER_ERODE, INNER_ERODE), np.uint8))
    edges = cv2.Canny(gray, *CANNY) * inside
    for curve in _chains(edges > 0, MIN_LENGTH["inner"] * h):
        strokes.append({"kind": "inner", "curve": curve})
    # Puntaje: largo por contraste medio del borde (las costuras marcadas ganan a las arrugas).
    for stroke in strokes:
        curve = stroke["curve"]
        xs = np.clip(np.round(curve[:, 0]).astype(int), 0, w - 1)
        ys = np.clip(np.round(curve[:, 1]).astype(int), 0, h - 1)
        stroke["score"] = _length(curve) / h * float(gradient[ys, xs].mean()) / 255.0
    kept = []
    for kind, keep in KEEP.items():
        kept += sorted((s for s in strokes if s["kind"] == kind), key=lambda s: -s["score"])[:keep]
    for stroke in kept:
        stroke["curve"] = _resample(stroke["curve"], POINTS)
    return kept


# Zonas de la prenda: a qué escala se calculan (fracción del cuadro), el área mínima de una zona
# (fracción del cuadro) y cuánto cerca del tobillo un "otros" es calzado y no bolso (fracción del alto).
ZONE_SCALE = 0.4
MIN_ZONE = 0.004
SHOE_REACH = 0.1
ZONES = ("torso", "sleeve_left", "sleeve_right", "leg_left", "leg_right", "bag", "shoe_left", "shoe_right")


def _seg_dist(px: np.ndarray, a, b) -> np.ndarray:
    """Distancia de cada punto `px` (N, 2) al segmento a-b."""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    ab = b - a
    t = np.clip(((px - a) @ ab) / max(float(ab @ ab), 1e-9), 0.0, 1.0)
    return np.linalg.norm(px - (a + t[:, None] * ab), axis=1)


def _chain_dist(px: np.ndarray, chain: list) -> np.ndarray:
    """Distancia a una cadena de puntos (hombro, codo, muñeca); infinito sin dos puntos seguidos."""
    pts = [p for p in chain if p is not None]
    if len(pts) < 2:
        return np.full(len(px), np.inf)
    return np.min([_seg_dist(px, a, b) for a, b in zip(pts[:-1], pts[1:])], axis=0)


def frame_zones(categories: np.ndarray, pose: dict[str, np.ndarray], width: int, height: int) -> dict[str, np.ndarray]:
    """La prenda partida en zonas con la pose (torso, mangas, piernas) y los accesorios (bolso,
    calzado de cada pie): el contorno de cada una en píxeles del cuadro.

    `pose`: articulaciones en píxeles del cuadro (las que se vieron)."""
    w, h = max(int(width * ZONE_SCALE), 8), max(int(height * ZONE_SCALE), 8)
    cat = cv2.medianBlur(cv2.resize(categories.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST), 3)
    scale = np.array([w / width, h / height])
    joints = {name: p * scale for name, p in pose.items()}
    zone = np.zeros((h, w), np.uint8)  # 0 = nada; k + 1 = ZONES[k]
    ys, xs = np.nonzero(cat == CLOTHES)
    if len(xs):
        px = np.stack([xs, ys], axis=1).astype(np.float64)
        hips = [joints.get("left_hip"), joints.get("right_hip")]
        shoulders = [joints.get("left_shoulder"), joints.get("right_shoulder")]
        if all(p is not None for p in hips + shoulders):
            mid_hip, mid_shoulder = (hips[0] + hips[1]) / 2, (shoulders[0] + shoulders[1]) / 2
            upper = px[:, 1] < mid_hip[1]
            torso = _seg_dist(px, mid_shoulder, mid_hip)
            labels = np.full(len(px), ZONES.index("torso"))
            for side in ("left", "right"):
                arm = _chain_dist(px, [joints.get(f"{side}_shoulder"), joints.get(f"{side}_elbow"), joints.get(f"{side}_wrist")])
                other = _chain_dist(px, [joints.get(f"{'right' if side == 'left' else 'left'}_shoulder"), joints.get(f"{'right' if side == 'left' else 'left'}_elbow"),
                                         joints.get(f"{'right' if side == 'left' else 'left'}_wrist")])
                labels[upper & (arm < torso) & (arm <= other)] = ZONES.index(f"sleeve_{side}")
            legs = {side: _chain_dist(px, [joints.get(f"{side}_hip"), joints.get(f"{side}_knee"), joints.get(f"{side}_ankle")]) for side in ("left", "right")}
            lower = ~upper
            labels[lower & (legs["left"] <= legs["right"])] = ZONES.index("leg_left")
            labels[lower & (legs["right"] < legs["left"])] = ZONES.index("leg_right")
        else:
            labels = np.full(len(px), ZONES.index("torso"))
        zone[ys, xs] = labels + 1
    # Accesorios: lo que está cerca de un tobillo es su calzado; el resto (lejos de la cabeza), bolso.
    rows = np.nonzero((cat > 0).any(axis=1))[0]
    head_line = rows.min() + HEAD_ZONE * (rows.max() - rows.min()) if len(rows) else 0
    count, blobs, stats, centers = cv2.connectedComponentsWithStats((cat == OTHER).astype(np.uint8))
    near_person = cv2.dilate(((cat > 0) & (cat != OTHER)).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    for k in range(1, count):
        cx, cy = centers[k]
        if cy < head_line or stats[k, cv2.CC_STAT_AREA] < MIN_ZONE * w * h:
            continue
        if not (near_person & (blobs == k)).any():
            continue  # no toca a la persona: un reflejo en el espejo o algo del fondo
        name = "bag"
        for side in ("left", "right"):
            ankle = joints.get(f"{side}_ankle")
            if ankle is not None and np.hypot(cx - ankle[0], cy - ankle[1]) < SHOE_REACH * h:
                name = f"shoe_{side}"
        zone[blobs == k] = ZONES.index(name) + 1
    out = {}
    for k, name in enumerate(ZONES):
        mask = (zone == k + 1).astype(np.uint8)
        if mask.sum() < MIN_ZONE * w * h:
            continue
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        big = max(contours, key=cv2.contourArea)[:, 0, :].astype(np.float64)
        if len(big) >= 8:
            # Suavizado a lo largo del contorno (la máscara del modelo tiene escalones) y 40 puntos.
            kernel = np.ones(7) / 7.0
            padded = np.vstack([big[-3:], big, big[:3]])
            smooth = np.stack([np.convolve(padded[:, k], kernel, mode="valid") for k in range(2)], axis=1)
            out[name] = _resample(np.vstack([smooth, smooth[:1]]), 40)[:-1] / scale
    return out


class Tracker:
    """Ids estables. Cada trazo se compara con los trazos vivos de la misma clase por la distancia media
    de sus puntos al otro (un tramo de la misma costura cuenta como la misma costura: Canny la parte
    distinto en cada cuadro), y hereda el id del más cercano. Un trazo que falta unos cuadros sigue
    vivo. Un corte vuelve a empezar."""

    def __init__(self) -> None:
        self.tracks: dict[int, tuple[int, str, np.ndarray]] = {}  # id → (último cuadro, clase, puntos)
        self.next_id = 0
        self.frame = 0

    def reset(self) -> None:
        self.tracks = {}

    def assign(self, strokes: list[dict], height: float) -> None:
        self.frame += 1
        taken: set[int] = set()
        for stroke in sorted(strokes, key=lambda s: -s["score"]):
            points = _resample(stroke["curve"], 24)
            best, best_d = None, TRACK_DIST * height
            for sid, (_seen, kind, old) in self.tracks.items():
                if kind != stroke["kind"] or sid in taken:
                    continue
                # Distancia media de los puntos del trazo nuevo al viejo (vale aunque sea un tramo).
                d = float(np.mean(np.min(np.linalg.norm(points[:, None, :] - old[None, :, :], axis=2), axis=1)))
                if d < best_d:
                    best, best_d = sid, d
            if best is None:
                best = self.next_id
                self.next_id += 1
            stroke["id"] = best
            taken.add(best)
            self.tracks[best] = (self.frame, stroke["kind"], points)
        self.tracks = {sid: t for sid, t in self.tracks.items() if self.frame - t[0] <= TRACK_MISS}


def ensure_garment(video_path: Path, run_dir: Path, models_dir: Path, cuts: list[int] | None = None) -> Path:
    """Los trazos de todo el video; si ya están, no hace nada."""
    target = Path(run_dir) / "analysis" / FILE
    if target.exists():
        return target
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import ImageSegmenter, ImageSegmenterOptions, RunningMode

    from vfxglow.analysis.models_store import ensure_model
    from vfxglow.io.video import VideoReader

    log.info("Buscando los trazos de la prenda")
    options = ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=str(ensure_model(models_dir, MODEL))),
        running_mode=RunningMode.VIDEO,
        output_category_mask=True,
    )
    cut_set = set(cuts or [])
    tracker = Tracker()
    poses = _poses(Path(run_dir) / "analysis" / "tracks.jsonl")
    part = target.with_suffix(".part")
    with VideoReader(video_path) as reader, ImageSegmenter.create_from_options(options) as segmenter, part.open("w") as out:
        fps, (h, w) = reader.meta.fps, (reader.meta.height, reader.meta.width)
        for index, frame in reader:
            if index in cut_set:
                tracker.reset()
            ratio = SEG_SIDE / max(frame.shape[:2])
            small = cv2.resize(frame, None, fx=ratio, fy=ratio, interpolation=cv2.INTER_AREA) if ratio < 1.0 else frame
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
            categories = segmenter.segment_for_video(image, int(index * 1000 / fps)).category_mask.numpy_view().squeeze()
            strokes = frame_strokes(frame, categories)
            tracker.assign(strokes, h)
            pose = {name: p * [w, h] for name, p in poses.get(index, {}).items()}
            zones = frame_zones(categories, pose, w, h)
            out.write(json.dumps({"frame": index, "strokes": [
                {"id": s["id"], "kind": s["kind"], "score": round(s["score"], 4), "points": np.round(s["curve"] / [w, h], 4).tolist()} for s in strokes
            ], "zones": {name: np.round(poly / [w, h], 4).tolist() for name, poly in zones.items()}}) + "\n")
    part.rename(target)
    return target


# Cambio de outfit: ventana a cada lado (cuadros, saltando los 2 del medio, que pueden ser una
# transición), distancia de Bhattacharyya mínima entre el color de la prenda de antes y de después,
# separación mínima entre dos cambios (s) y cuánto se corre el cambio a un corte cercano (cuadros).
# Medido el 2026-11-03: video_46 da 0,40-0,81 en sus cuatro cambios; video_55, 0,66 al ponerse la
# sudadera y 0,50 al sumar pantalón y bomber, y no más de 0,28 en sus otros seis cortes.
OUTFIT_WINDOW = 8
OUTFIT_SKIP = 2
OUTFIT_CHANGE = 0.33
OUTFIT_GAP_S = 0.8
OUTFIT_SNAP = 4


def outfit_changes(video_path: Path, models_dir: Path, cuts: list[int] | None = None) -> list[int]:
    """Dónde empieza un outfit nuevo: picos del cambio de color de la prenda (tono, saturación y brillo
    de lo que el segmentador llama ropa), no los cortes. Una capa que se suma con colores parecidos
    no cuenta; una prenda que se cambia en un salto sin corte, sí."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import ImageSegmenter, ImageSegmenterOptions

    from vfxglow.analysis.models_store import ensure_model
    from vfxglow.io.video import VideoReader

    options = ImageSegmenterOptions(base_options=BaseOptions(model_asset_path=str(ensure_model(models_dir, MODEL))), output_category_mask=True)
    hists = []
    with VideoReader(video_path) as reader, ImageSegmenter.create_from_options(options) as segmenter:
        fps = reader.meta.fps
        for _index, frame in reader:
            ratio = SEG_SIDE / max(frame.shape[:2])
            small = cv2.resize(frame, None, fx=ratio, fy=ratio, interpolation=cv2.INTER_AREA)
            cat = segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(small, cv2.COLOR_BGR2RGB))).category_mask.numpy_view().squeeze()
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1, 2], (cat == CLOTHES).astype(np.uint8), [12, 4, 4], [0, 180, 0, 256, 0, 256]).flatten()
            hists.append(hist / max(float(hist.sum()), 1.0))
    return outfit_peaks(np.array(hists), fps, cuts)


def outfit_peaks(hists: np.ndarray, fps: float, cuts: list[int] | None = None) -> list[int]:
    """Los cambios de outfit a partir del color de la prenda por cuadro (un histograma por fila)."""
    n, wnd, skip = len(hists), OUTFIT_WINDOW, OUTFIT_SKIP
    score = np.zeros(n)
    for t in range(wnd, n - wnd):
        before, after = hists[t - wnd : t - skip].mean(axis=0), hists[t + skip : t + wnd].mean(axis=0)
        score[t] = cv2.compareHist(before.astype(np.float32), after.astype(np.float32), cv2.HISTCMP_BHATTACHARYYA)
    # Un cambio seco da una meseta (la ventana salta los cuadros del medio): el suavizado la vuelve un pico
    # en su centro, que es donde cambió.
    score = np.convolve(score, np.array([1.0, 2.0, 3.0, 2.0, 1.0]) / 9.0, mode="same")
    gap = int(round(OUTFIT_GAP_S * fps))
    peaks = []
    for t in np.argsort(-score):
        if score[t] < OUTFIT_CHANGE:
            break
        if all(abs(int(t) - p) >= gap for p in peaks):
            peaks.append(int(t))
    out = []
    for p in sorted(peaks):
        near = [c for c in (cuts or []) if abs(c - p) <= OUTFIT_SNAP]
        out.append(min(near, key=lambda c: abs(c - p)) if near else p)
    return out


def _poses(path: Path) -> dict[int, dict[str, np.ndarray]]:
    """Las articulaciones de la pose por fotograma, en coordenadas 0-1 de quien se vio (las de
    confianza); se pasan a píxeles al usarlas."""
    if not path.exists():
        return {}
    from vfxglow.analysis.schema import FrameRecord
    from vfxglow.io.store import read_jsonl

    out = {}
    for record in read_jsonl(path, FrameRecord):
        if record.pose:
            out[record.frame] = {lm.name: np.array([lm.x, lm.y]) for lm in record.pose if lm.c > 0.3}
    return out


def load_garment(run_dir: Path | None) -> dict[int, dict]:
    """Por fotograma, sus trazos (`strokes`) y sus zonas (`zones`), en coordenadas 0-1; vacío si no se
    calcularon."""
    path = Path(run_dir) / "analysis" / FILE if run_dir is not None else None
    if path is None or not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        row = json.loads(line)
        out[row["frame"]] = {"strokes": row["strokes"], "zones": row.get("zones", {})}
    return out
