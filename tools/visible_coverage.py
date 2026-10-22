"""Qué parte de un video renderizado muestra de verdad el efecto: compara cuadro a cuadro
el render con el original y reporta los tramos vacíos (sin efecto visible).

    .venv/bin/python tools/visible_coverage.py runs/avatar_opening_elements-785c151e \\
        --salida avatar__halloween__fuego-azul__rayo-violeta.mp4
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ANCHO_ANALISIS = 270  # ancho al que se reducen los cuadros antes de comparar
UMBRAL_PIXEL = 40  # cuánto tiene que cambiar (0-255) un píxel, fuera del tinte parejo, para contar como efecto
MAX_ACCIONES = 5  # acciones máximas a listar por tramo vacío


def _reducir(cuadro: np.ndarray) -> np.ndarray:
    alto, ancho = cuadro.shape[:2]
    return cv2.resize(cuadro, (ANCHO_ANALISIS, max(1, round(alto * ANCHO_ANALISIS / ancho))), interpolation=cv2.INTER_AREA)


def _fraccion_cambiada(render: np.ndarray, original: np.ndarray) -> float:
    """Fracción del cuadro con un efecto: píxeles que cambian mucho (aclarando, como el fuego o el
    neón, u oscureciendo, como la roca sobre el cielo), descontado el tinte parejo de todo el
    cuadro (la luz del fuego tiñe todo y no es un efecto que se vea)."""
    if original.shape[:2] != render.shape[:2]:
        original = cv2.resize(original, (render.shape[1], render.shape[0]), interpolation=cv2.INTER_AREA)
    a, b = _reducir(render).astype(np.int16), _reducir(original).astype(np.int16)
    diff = a - b
    tint = np.median(diff.reshape(-1, 3), axis=0)  # el cambio parejo de todo el cuadro
    local = np.abs(diff - tint).max(axis=2)
    return np.count_nonzero(local > UMBRAL_PIXEL) / local.size


def _comparar(ruta_render: Path, ruta_original: Path, umbral: float) -> tuple[list[bool], float]:
    """Devuelve si cada cuadro tiene efecto y los fps del render."""
    cap_render = cv2.VideoCapture(str(ruta_render))
    cap_original = cv2.VideoCapture(str(ruta_original))
    fps = cap_render.get(cv2.CAP_PROP_FPS) or 30.0
    con_efecto: list[bool] = []
    # Se leen en paralelo; se para en el más corto
    while True:
        ok_render, cuadro_render = cap_render.read()
        if not ok_render:
            break
        ok_original, cuadro_original = cap_original.read()
        if not ok_original:
            break
        con_efecto.append(_fraccion_cambiada(cuadro_render, cuadro_original) > umbral)
    cap_render.release()
    cap_original.release()
    return con_efecto, fps


def _tramos_vacios(con_efecto: list[bool], fps: float, minimo_s: float) -> list[tuple[int, int]]:
    """Rangos [inicio, fin] (en cuadros) sin efecto que duran al menos minimo_s segundos."""
    tramos = []
    inicio = None
    for i, activo in enumerate([*con_efecto, True]):  # el True final cierra un tramo abierto
        if not activo and inicio is None:
            inicio = i
        elif activo and inicio is not None:
            if (i - inicio) / fps >= minimo_s:
                tramos.append((inicio, i - 1))
            inicio = None
    return tramos


def _nota_coreografia(run_dir: Path, inicio: int, fin: int) -> str | None:
    """Acciones de la coreografía que se solapan con el tramo vacío."""
    ruta = run_dir / "scripts" / "avatar.choreography.json"
    if not ruta.exists():
        return None
    decisiones = json.loads(ruta.read_text())["decisions"]
    solapan: list[str] = []
    for d in decisiones:
        if d["choice"].startswith("nada"):
            continue
        if d["frame"] <= fin and d.get("until", d["frame"]) >= inicio:
            etiqueta = f"{d['action']}:{d['choice'].split(' (')[0]}"
            if etiqueta not in solapan:
                solapan.append(etiqueta)
    if not solapan:
        return "coreografía: nada encendido"
    return "coreografía: " + ", ".join(solapan[:MAX_ACCIONES])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--salida", default="avatar.mp4", help="Nombre del archivo dentro de output/")
    parser.add_argument("--umbral", type=float, default=0.003, help="Fracción de píxeles cambiados para contar un cuadro con efecto")
    parser.add_argument("--vacio", type=float, default=0.4, help="Duración mínima en segundos de un tramo vacío a reportar")
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "manifest.json").read_text())
    original = Path(manifest["video_path"])
    if not original.is_absolute():
        original = Path.cwd() / original  # relativo a la raíz del repo
    render = args.run_dir / "output" / args.salida

    con_efecto, fps = _comparar(render, original, args.umbral)
    n = len(con_efecto)
    if n == 0:
        print(f"{args.run_dir.name}/{args.salida}: sin cuadros comparables (revisa las rutas de video)")
        return
    pct = 100 * sum(con_efecto) / n
    print(f"{args.run_dir.name}/{args.salida}: {n} cuadros, visible {pct:.0f}% del tiempo")

    for inicio, fin in _tramos_vacios(con_efecto, fps, args.vacio):
        inicio_s, fin_s = inicio / fps, (fin + 1) / fps
        linea = f"  vacío {inicio_s:.2f}-{fin_s:.2f} s ({fin_s - inicio_s:.2f} s)"
        nota = _nota_coreografia(args.run_dir, inicio, fin)
        if nota:
            linea += f" | {nota}"
        print(linea)


if __name__ == "__main__":
    main()
