"""Avisos de calidad del video, con lo que el análisis ya guardó (brief + tracks). Puro: sin E/S.

Avisan a la persona, antes de gastar el render, de por qué el resultado puede salir mal. Nunca
bloquean. Umbrales calibrados con los `runs/*/analysis` existentes (ver tests/test_quality.py).

Señales omitidas por no existir un dato barato: `dark` (el análisis no guarda brillo del fotograma).
`crowd` usa los contornos de silueta (`body_contours`), que son ruidosos: solo avisa con 4 o más
siluetas y claramente más que las personas seguidas.
"""

from __future__ import annotations

from statistics import median
from typing import Literal

from pydantic import BaseModel

from vfxglow.analysis.schema import FrameRecord, MotionBrief

NO_PERSON_MAX = 0.05  # con pose en menos de esta fracción de fotogramas: nadie
LOW_TRACKING = 0.70
CUT_OFF_SHARE = 0.30
CUT_OFF_EDGE = 0.985  # un tobillo más abajo de esto (o poco visible) cuenta como fuera de cuadro
MIN_CONF = 0.3
SMALL_HEIGHT = 0.25
CROWD_SILHOUETTES = 4
CROWD_SHARE = 0.40
MANY_PEOPLE = 4
SHORT_S = 3.0


class QualityWarning(BaseModel):
    code: str
    level: Literal["info", "warn"]
    title: str
    detail: str


def _cut_off(frame: FrameRecord) -> bool:
    by = {p.name: p for p in frame.pose}
    nose = by.get("nose")
    head = nose is not None and (nose.c < MIN_CONF or not 0.01 <= nose.y <= 0.99 or not 0.0 <= nose.x <= 1.0)
    ankles = [by[n] for n in ("left_ankle", "right_ankle") if n in by]
    feet = bool(ankles) and all(a.y > CUT_OFF_EDGE or a.c < MIN_CONF for a in ankles)
    return head or feet


def _height(frame: FrameRecord) -> float | None:
    """Alto de la persona como fracción del cuadro: su caja, o la extensión de la pose."""
    if frame.box:
        return max(0.0, frame.box[3] - frame.box[1])
    ys = [p.y for p in frame.pose if p.c >= MIN_CONF]
    return (max(ys) - min(ys)) / 0.85 if ys else None


def _crowded(frame: FrameRecord) -> bool:
    count = len(frame.body_contours)
    return count >= CROWD_SILHOUETTES and count >= max(len(frame.people), 1) + 2


def quality_warnings(brief: MotionBrief, tracks: list[FrameRecord]) -> list[QualityWarning]:
    out: list[QualityWarning] = []
    posed = [f for f in tracks if f.pose]
    share = len(posed) / len(tracks) if tracks else 0.0
    if brief.video.duration_s < SHORT_S:
        out.append(QualityWarning(code="short", level="info", title="El video es muy corto", detail="Con menos de 3 segundos hay poco movimiento que realzar."))
    if share < NO_PERSON_MAX:
        out.append(QualityWarning(code="no_person", level="warn", title="No encontramos a nadie", detail="Los efectos siguen al cuerpo: graba a la persona de cuerpo entero."))
        return out
    if share < LOW_TRACKING:
        out.append(QualityWarning(code="low_tracking", level="warn", title="Perdemos a la persona a ratos", detail=f"Solo la seguimos en el {round(share * 100)} % del video; en el resto los efectos desaparecerán. Prueba con mejor luz y sin objetos delante."))
    if sum(_cut_off(f) for f in posed) / len(posed) > CUT_OFF_SHARE:
        out.append(QualityWarning(code="cut_off", level="warn", title="Parte del cuerpo queda fuera de cuadro", detail="La cabeza o los pies se salen del encuadre buena parte del tiempo; aleja un poco la cámara."))
    heights = [h for h in map(_height, posed) if h is not None]
    if heights and median(heights) < SMALL_HEIGHT:
        out.append(QualityWarning(code="small_person", level="warn", title="La persona se ve pequeña", detail="Ocupa muy poco alto del cuadro: acércate o recorta el video."))
    if len(brief.people) >= MANY_PEOPLE or sum(map(_crowded, posed)) / len(posed) > CROWD_SHARE:
        out.append(QualityWarning(code="many_people", level="info", title="Hay mucha gente en el cuadro", detail="Solo seguimos a las personas más visibles; el resto no tendrá efectos."))
    return out
