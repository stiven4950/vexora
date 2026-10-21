"""Mide, cuadro a cuadro, el fuego dibujado de una referencia estilo glowing.

Separa el fuego por color (cuerpo casi blanco y borde amarillo; el resto del cuadro es naranja
oscuro) y, por cada pieza conectada, da área, largo, ancho medio y máximo, posición y fracción
blanca. También cuenta cuántos cuadros dura cada dibujo (si se anima a uno o a dos).

    .venv/bin/python tools/measure_fire.py ../glowing/data/glowing/video_18.mp4 --hasta 3 --json out.json

Con `--trozos`, sigue cuadro a cuadro los trocitos sueltos (piezas chicas que se desprenden) y da
su vida, cuánto se achican, cuánto suben y derivan, cuántos nacen por cuadro según si la masa
principal crece o se achica, y los picos agudos por cada 100 px de contorno. Con `--motor RUN`
mide lo mismo sobre las capas de fuego de nuestro motor (sin el video de fondo):

    .venv/bin/python tools/measure_fire.py ../glowing/data/glowing/video_51.mp4 --hasta 4.6 --trozos
    .venv/bin/python tools/measure_fire.py ../glowing/data/original/video_51.mp4 --hasta 4.6 --trozos \
        --motor runs/video_51-4e4fb85f --catalogo avatar
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

import cv2
import numpy as np


def fire_mask(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    b, g, r = (frame[..., k].astype(int) for k in range(3))
    core = (b > 185) & (g > 215) & (r > 215)
    rim = (r > 225) & (g > 150) & (b < 185) & ~core
    fire = cv2.morphologyEx((core | rim).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return fire, core


def pieces(fire: np.ndarray, core: np.ndarray, min_area: int = 25) -> list[dict]:
    count, labels, stats, centers = cv2.connectedComponentsWithStats(fire, 8)
    out = []
    for k in range(1, count):
        area = int(stats[k, 4])
        if area < min_area:
            continue
        mask = (labels == k).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        length = cv2.arcLength(max(contours, key=cv2.contourArea), True) / 2
        out.append({
            "area": area,
            "x": round(float(centers[k][0])),
            "y": round(float(centers[k][1])),
            "largo": round(length),
            "ancho_medio": round(area / max(length, 1), 1),
            "ancho_max": round(float(cv2.distanceTransform(mask, cv2.DIST_L2, 5).max() * 2), 1),
            "blanco": round(float(core[labels == k].mean()), 2),
        })
    return sorted(out, key=lambda p: -p["area"])


# Los trozos se miden a esta resolución (540x960), para comparar videos de distinto tamaño.
WORK = (540, 960)


def track_pieces(masks: list[np.ndarray], lo: int = 15, hi: int = 1500, reach: float = 25.0) -> dict:
    """Sigue las piezas chicas (entre `lo` y `hi` px) de cuadro en cuadro por cercanía."""
    done, alive = [], []
    born = np.zeros(len(masks), int)
    main_area = []
    for i, m in enumerate(masks):
        n, _lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
        main_area.append(int(st[1:, 4].max()) if n > 1 else 0)
        pieces = [(cen[k][0], cen[k][1], st[k, 4]) for k in range(1, n) if lo <= st[k, 4] <= hi]
        used, keep = set(), []
        for track in alive:
            cx, cy, _a = track[-1]
            best = min(((np.hypot(x - cx, y - cy), j) for j, (x, y, _b) in enumerate(pieces) if j not in used), default=None)
            if best is not None and best[0] < reach:
                used.add(best[1])
                track.append(pieces[best[1]])
                keep.append(track)
            else:
                done.append(track)
        for j, p in enumerate(pieces):
            if j not in used:
                keep.append([p])
                born[i] += 1
        alive = keep
    done += alive
    life = np.array([len(t) for t in done]) if done else np.zeros(1)
    long = [t for t in done if len(t) >= 3]
    shrink = [t[-1][2] / t[0][2] for t in long]
    rise = [-(t[-1][1] - t[0][1]) / len(t) for t in long]
    drift = [abs(t[-1][0] - t[0][0]) / len(t) for t in long]
    falling = [born[i] for i in range(1, len(masks)) if main_area[i] < main_area[i - 1] * 0.85]
    growing = [born[i] for i in range(1, len(masks)) if main_area[i] >= main_area[i - 1]]
    return {
        "trozos": len(done),
        "vida_mediana": float(np.median(life)),
        "vida_p90": float(np.percentile(life, 90)),
        "area_final_inicial": round(float(np.median(shrink)), 2) if shrink else None,
        "sube_px": round(float(np.median(rise)), 2) if rise else None,
        "deriva_px": round(float(np.median(drift)), 2) if drift else None,
        "nacen_por_cuadro": round(float(born.mean()), 2),
        "nacen_si_se_achica": round(float(np.mean(falling)), 2) if falling else None,
        "nacen_si_crece": round(float(np.mean(growing)), 2) if growing else None,
        "picos_por_100px": sharp_tips(masks),
    }


def sharp_tips(masks: list[np.ndarray], k: int = 8) -> float | None:
    """Puntas agudas (menos de 60°) del contorno de la masa principal, por cada 100 px de contorno."""
    tips = []
    for m in masks[::2]:
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        c = max(contours, key=cv2.contourArea)
        if cv2.contourArea(c) < 3000:
            continue
        pts = c[:, 0, :].astype(float)
        n = len(pts)
        a = pts[(np.arange(n) - k) % n] - pts
        b = pts[(np.arange(n) + k) % n] - pts
        cos = (a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-6)
        runs = int(np.sum(np.diff((cos > 0.5).astype(int)) == 1))
        tips.append(runs / (cv2.arcLength(c, True) / 100))
    return round(float(np.median(tips)), 2) if tips else None


def video_masks(path: str, first: int, last: int) -> list[np.ndarray]:
    """Máscaras del fuego dibujado de una referencia (cuerpo y borde por color)."""
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    out = []
    for _ in range(first, last + 1):
        ok, frame = cap.read()
        if not ok:
            break
        fire, _core = fire_mask(frame)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)  # también el amarillo plano (video_51)
        flat = ((hsv[..., 1] > 150) & (hsv[..., 2] > 220) & (hsv[..., 0] > 20) & (hsv[..., 0] < 40)).astype(np.uint8)
        out.append(cv2.resize(np.maximum(fire, flat), WORK, interpolation=cv2.INTER_NEAREST))
    return out


def engine_masks(run: str, catalog: str, first: int, last: int) -> list[np.ndarray]:
    """Máscaras del fuego de nuestro motor: el alfa de las capas de adornos (el fuego), sin el video."""
    from pathlib import Path

    from vfxglow.analysis.schema import MotionBrief
    from vfxglow.config import EngineConfig
    from vfxglow.director.choreography import choreograph, load_catalog
    from vfxglow.director.schema import resolve_timing
    from vfxglow.engine.engine import EffectEngine
    from vfxglow.pipeline import load_tracks

    run_dir = Path(run)
    tracks = {t.frame: t for t in load_tracks(run_dir / "analysis" / "tracks.jsonl")}
    brief = MotionBrief.model_validate_json((run_dir / "analysis" / "motion_brief.json").read_text())
    cat = load_catalog(Path("configs/catalogs") / f"{catalog}.yaml")
    script, _ = choreograph(cat, brief, cat.seed)
    script = resolve_timing(script, brief.video.frame_count)
    fire = {e.id for e in script.effects if e.type == "adornment"}
    engine = EffectEngine(script, EngineConfig(), events=list(brief.events), fps=brief.video.fps)
    out = []
    for index in range(0, last + 1):
        layers = engine.render_frame(tracks.get(index), index, brief.video.width, brief.video.height, brief.video.frame_count)
        if index < first:
            continue
        alpha = np.zeros((brief.video.height, brief.video.width), np.float32)
        for eid, group, layer in layers:
            if eid in fire and group == "glow":  # sin la luz del fuego (grade), que cubre el cuadro
                np.maximum(alpha, layer[..., 3], out=alpha)
        out.append(cv2.resize((alpha > 0.5).astype(np.uint8), WORK, interpolation=cv2.INTER_NEAREST))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--desde", type=float, default=0.0)
    parser.add_argument("--hasta", type=float, default=3.0)
    parser.add_argument("--json", default=None)
    parser.add_argument("--trozos", action="store_true", help="Medir los trocitos sueltos y los picos")
    parser.add_argument("--motor", default=None, help="Run de nuestro motor: medir sus capas de fuego")
    parser.add_argument("--catalogo", default="avatar")
    args = parser.parse_args()
    if args.trozos:
        fps = cv2.VideoCapture(args.video).get(cv2.CAP_PROP_FPS) or 30.0
        first, last = int(args.desde * fps), int(args.hasta * fps)
        masks = engine_masks(args.motor, args.catalogo, first, last) if args.motor else video_masks(args.video, first, last)
        for key, value in track_pieces(masks).items():
            print(f"{key:20s} {value}")
        return
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    first, last = int(args.desde * fps), int(args.hasta * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    rows, previous, runs, run = [], None, [], 1
    for index in range(first, last + 1):
        ok, frame = cap.read()
        if not ok:
            break
        fire, core = fire_mask(frame)
        found = pieces(fire, core)
        rows.append({"cuadro": index, "seg": round(index / fps, 2), "piezas": len(found), "area": sum(p["area"] for p in found), "formas": found[:8]})
        if previous is not None:
            union = (fire | previous).sum()
            if union and (fire & previous).sum() / union > 0.97:
                run += 1
            else:
                runs.append(run)
                run = 1
        previous = fire
    runs.append(run)
    for row in rows:
        top = " ; ".join(f"A{p['area']} L{p['largo']} w{p['ancho_medio']}/{p['ancho_max']} ({p['x']},{p['y']}) b{p['blanco']}" for p in row["formas"][:3])
        print(f"{row['cuadro']:4d} {row['seg']:6.2f}s piezas={row['piezas']:3d} area={row['area']:7d} | {top}")
    print(f"Dibujos distintos: {len(runs)} en {len(rows)} cuadros; cuadros por dibujo: {dict(Counter(runs))}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as out:
            json.dump(rows, out, ensure_ascii=False)


if __name__ == "__main__":
    main()
