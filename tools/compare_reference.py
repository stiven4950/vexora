"""Comparación cuadro a cuadro de nuestro render contra la referencia de un animador.

En cada fotograma:

0. Empareja los tiempos: la referencia puede ir corrida unos cuadros respecto al original y el
   corrimiento cambiar a lo largo del video (video_34: 0 al empezar, la referencia se adelanta
   hasta 3 cuadros al final). Se mide cada 15 cuadros y se interpola (`time_offsets`).
1. Alinea la referencia con el original (ECC afín sobre gris reducido): el animador pudo
   reencuadrar o estabilizar unos píxeles, y sin alinear los bordes se leerían como efecto.
2. Luz añadida = lo que la versión tiene de más brillante que el original, contra el máximo del
   original en el cuadro anterior, el actual y el siguiente y en unos píxeles alrededor: los dos
   videos no van exactamente al mismo instante (un borde que se mueve no es un efecto; un neón
   destaca igual).
3. La reparte por persona (la caja de su pose, ampliada) y compara presencia y lugar con nuestro
   render: intersección sobre unión de las dos máscaras engrosadas un tercio del ancho de hombros
   (un dibujo a mano no coincide trazo por trazo; lo que se juzga es que esté en la misma parte
   del cuerpo).

Salida: tabla por fotograma (CSV) y un resumen de tramos que no coinciden: falta (la referencia
dibuja y nosotros no), sobra (al revés) y lugar (los dos dibujan pero en otro sitio).

    python tools/compare_reference.py --original o.mp4 --reference g.mp4 --ours n.mp4 \\
        --tracks runs/<run>/analysis/tracks.jsonl --out runs/<run>/compare
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vfxglow.pipeline import load_tracks  # noqa: E402

# Luz añadida: cuánto más brillante (0-255) y qué tan brillante debe quedar el píxel.
LIFT = 40
BRIGHT = 140
# Píxeles mínimos para decir que una persona "tiene efecto" en ese cuadro.
MIN_AREA = 120
# Engrosamiento de las máscaras antes de comparar el lugar (fracción del ancho de hombros), y la
# coincidencia mínima.
TOLERANCE = 0.33
MIN_IOU = 0.2
# Un tramo que no coincide tiene que durar al menos esto (fotogramas).
MIN_SPAN = 3


def time_offsets(original: Path, reference: Path, step: int = 15, search: int = 12) -> np.ndarray:
    """Por cuadro del original, cuántos cuadros hay que sumar para hallar el mismo instante en la
    referencia (negativo: la referencia va adelantada)."""
    def small(path):
        cap = cv2.VideoCapture(str(path))
        out = []
        while True:
            ok, frame = cap.read()
            if not ok:
                return out
            out.append(cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (90, 112)).astype(np.float32))

    a, b = small(original), small(reference)
    marks, values = [], []
    for i in range(0, len(a), step):
        errs = {d: float(np.abs(a[i] - b[i + d]).mean()) for d in range(-search, search + 1) if 0 <= i + d < len(b)}
        marks.append(i)
        values.append(min(errs, key=errs.get))
    # Mediana móvil: un cuadro sin movimiento empata entre varios desfases.
    smooth = [int(np.median(values[max(k - 2, 0) : k + 3])) for k in range(len(values))]
    return np.round(np.interp(np.arange(len(a)), marks, smooth)).astype(int)


def _align(reference: np.ndarray, original: np.ndarray, warp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """La referencia llevada a las coordenadas del original (y la transformación, para el siguiente)."""
    small = 0.5
    ga = cv2.resize(cv2.cvtColor(original, cv2.COLOR_BGR2GRAY), None, fx=small, fy=small).astype(np.float32)
    gb = cv2.resize(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), None, fx=small, fy=small).astype(np.float32)
    try:
        _, warp = cv2.findTransformECC(ga, gb, warp.copy(), cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4), None, 3)
    except cv2.error:
        pass
    full = warp.copy()
    full[:, 2] /= small
    h, w = original.shape[:2]
    aligned = cv2.warpAffine(reference, full, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
    return aligned, warp


# Tolerancia espacial del máximo del original (px).
SLACK = 7


def added_light(version: np.ndarray, original: np.ndarray, neighbours: list[np.ndarray] | None = None) -> np.ndarray:
    base = original.max(axis=2)
    for other in neighbours or []:
        base = np.maximum(base, other.max(axis=2))
    base = cv2.dilate(base, np.ones((SLACK, SLACK), np.uint8))
    lift = version.astype(np.int16).max(axis=2) - base.astype(np.int16)
    mask = ((lift > LIFT) & (version.max(axis=2) > BRIGHT)).astype(np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def shoulder_widths(track, width: int, height: int) -> dict[str, float]:
    out = {}
    for person in (track.people if track is not None else []):
        lm = {l.name: np.array([l.x * width, l.y * height]) for l in person.pose}
        if "left_shoulder" in lm and "right_shoulder" in lm:
            out[person.person_id] = max(float(np.linalg.norm(lm["left_shoulder"] - lm["right_shoulder"])), 20.0)
    return out


def person_boxes(track, width: int, height: int) -> dict[str, tuple[int, int, int, int]]:
    boxes = {}
    for person in (track.people if track is not None else []):
        pts = np.array([[l.x * width, l.y * height] for l in person.pose if l.c > 0.3])
        if len(pts) < 4:
            continue
        x0, y0 = pts.min(axis=0)
        x1, y1 = pts.max(axis=0)
        pad_x, pad_y = (x1 - x0) * 0.6 + 20, (y1 - y0) * 0.25 + 20
        boxes[person.person_id] = (int(max(x0 - pad_x, 0)), int(max(y0 - pad_y * 1.6, 0)), int(min(x1 + pad_x, width)), int(min(y1 + pad_y, height)))
    return boxes


def _split(mask: np.ndarray, boxes: dict) -> dict[str, np.ndarray]:
    """Cada píxel encendido va a la persona cuya caja lo contiene y cuyo centro está más cerca."""
    out = {pid: np.zeros_like(mask) for pid in boxes}
    ys, xs = np.nonzero(mask)
    if not len(xs) or not boxes:
        return out
    centers = {pid: ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for pid, b in boxes.items()}
    ids = list(boxes)
    dist = np.stack([(xs - centers[p][0]) ** 2 + ((ys - centers[p][1]) * 0.5) ** 2 for p in ids])
    inside = np.stack([(xs >= boxes[p][0]) & (xs < boxes[p][2]) & (ys >= boxes[p][1]) & (ys < boxes[p][3]) for p in ids])
    dist = np.where(inside, dist, np.inf)
    owner = dist.argmin(axis=0)
    valid = np.isfinite(dist.min(axis=0))
    for k, pid in enumerate(ids):
        sel = valid & (owner == k)
        out[pid][ys[sel], xs[sel]] = 1
    return out


def _iou(a: np.ndarray, b: np.ndarray, shoulders: float = 60.0) -> float:
    size = max(int(TOLERANCE * shoulders), 5)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    da, db = cv2.dilate(a, kernel), cv2.dilate(b, kernel)
    union = (da | db).sum()
    return float((da & db).sum() / union) if union else 1.0


def compare(original: Path, reference: Path, ours: Path, tracks_path: Path, out: Path, fps: float = 30.0) -> list[dict]:
    tracks = {t.frame: t for t in load_tracks(tracks_path)}
    offsets = time_offsets(original, reference)
    caps = [cv2.VideoCapture(str(p)) for p in (original, ours)]
    ref_cap = cv2.VideoCapture(str(reference))
    ref_frames: dict[int, np.ndarray] = {}
    ref_next = 0

    def ref_at(k: int):
        nonlocal ref_next
        while ref_next <= k:
            ok, frame = ref_cap.read()
            if not ok:
                break
            ref_frames[ref_next] = frame
            ref_next += 1
        for old in [x for x in ref_frames if x < k - 20]:
            del ref_frames[old]
        return ref_frames.get(k)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    warp = np.eye(2, 3, dtype=np.float32)
    index = 0

    def read():
        frames = [cap.read() for cap in caps]
        return [f for _, f in frames] if all(ok for ok, _ in frames) else None

    previous, current, following = None, read(), read()
    while current is not None:
        o, n = current
        g = ref_at(min(max(index + int(offsets[min(index, len(offsets) - 1)]), 0), 10**9))
        if g is None:
            break
        neighbours = [x[0] for x in (previous, following) if x is not None]
        h, w = o.shape[:2]
        g = cv2.resize(g, (w, h)) if g.shape[:2] != (h, w) else g
        n = cv2.resize(n, (w, h)) if n.shape[:2] != (h, w) else n
        g, warp = _align(g, o, warp)
        boxes = person_boxes(tracks.get(index), w, h)
        widths = shoulder_widths(tracks.get(index), w, h)
        ref = _split(added_light(g, o, neighbours), boxes)
        own = _split(added_light(n, o), boxes)
        for pid in sorted(boxes):
            ra, oa = int(ref[pid].sum()), int(own[pid].sum())
            rows.append({
                "frame": index, "t": round(index / fps, 2), "ref_offset": int(offsets[min(index, len(offsets) - 1)]), "person": pid,
                "ref_area": ra, "our_area": oa,
                "iou": round(_iou(ref[pid], own[pid], widths.get(pid, 60.0)), 3) if ra >= MIN_AREA and oa >= MIN_AREA else "",
            })
        index += 1
        previous, current, following = current, following, read()
    with (out / "frames.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    spans = mismatches(rows, fps)
    (out / "mismatches.json").write_text(json.dumps(spans, indent=1, ensure_ascii=False))
    return spans


def mismatches(rows: list[dict], fps: float) -> list[dict]:
    """Tramos de fotogramas seguidos con el mismo desacuerdo, por persona."""
    def kind(row) -> str:
        ref_on, our_on = row["ref_area"] >= MIN_AREA, row["our_area"] >= MIN_AREA
        if ref_on and not our_on:
            return "falta"
        if our_on and not ref_on:
            return "sobra"
        if ref_on and our_on and row["iou"] != "" and row["iou"] < MIN_IOU:
            return "lugar"
        return ""

    spans = []
    for pid in sorted({r["person"] for r in rows}):
        current = None
        for row in (r for r in rows if r["person"] == pid):
            k = kind(row)
            if current and (k != current["tipo"] or row["frame"] != current["hasta_f"] + 1):
                if current["hasta_f"] - current["desde_f"] + 1 >= MIN_SPAN:
                    spans.append(current)
                current = None
            if k:
                if current is None:
                    current = {"persona": pid, "tipo": k, "desde_f": row["frame"], "hasta_f": row["frame"]}
                else:
                    current["hasta_f"] = row["frame"]
        if current and current["hasta_f"] - current["desde_f"] + 1 >= MIN_SPAN:
            spans.append(current)
    for span in spans:
        span["desde"] = round(span["desde_f"] / fps, 2)
        span["hasta"] = round(span["hasta_f"] / fps, 2)
    return sorted(spans, key=lambda s: (s["desde_f"], s["persona"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--ours", type=Path, required=True)
    parser.add_argument("--tracks", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    spans = compare(args.original, args.reference, args.ours, args.tracks, args.out)
    rows = list(csv.DictReader((args.out / "frames.csv").open()))
    both = [r for r in rows if int(r["ref_area"]) >= MIN_AREA or int(r["our_area"]) >= MIN_AREA]
    agree = [r for r in both if (int(r["ref_area"]) >= MIN_AREA) == (int(r["our_area"]) >= MIN_AREA) and (r["iou"] == "" or float(r["iou"]) >= MIN_IOU)]
    print(f"Fotogramas-persona con efecto en alguna versión: {len(both)}; coinciden: {len(agree)} ({100 * len(agree) / max(len(both), 1):.0f}%)")
    for s in spans:
        print(f"{s['desde']:6.2f}-{s['hasta']:6.2f}  {s['persona']}  {s['tipo']}")


if __name__ == "__main__":
    main()
