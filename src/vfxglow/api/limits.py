"""Límites de la API: qué video se acepta y cuánto puede pedir cada usuario.

Sin esto, cualquiera con una cuenta (el registro es abierto) podría llenar la cola de un solo hilo
o pedir análisis profundos pagados sin tope (docs/analisis_mejoras_y_seguridad.md, §5).

- Video: se lee la cabecera con el ffmpeg del proyecto (imageio-ffmpeg) antes de encolarlo. Un
  archivo que no es video, o que pasa de VEXORA_MAX_VIDEO_SECONDS o de VEXORA_MAX_VIDEO_SIDE
  píxeles en el lado largo, se rechaza.
- Cuotas por usuario: trabajos activos a la vez (en cola o procesando) y trabajos por día.
- Análisis profundo (de pago): solo para quien esté en VEXORA_DEEP_ALLOW (uids o correos separados
  por comas; "*" = todos), con un tope diario por usuario y otro global.

Con la autenticación apagada (VEXORA_AUTH=off, solo en la máquina local) las cuotas no aplican;
la validación del video sí.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from vfxglow import telemetry
from vfxglow.api.auth import User, auth_enabled
from vfxglow.api.jobs import Job

MAX_SECONDS_ENV = "VEXORA_MAX_VIDEO_SECONDS"
MAX_SIDE_ENV = "VEXORA_MAX_VIDEO_SIDE"
MAX_ACTIVE_ENV = "VEXORA_MAX_ACTIVE_JOBS"
DAILY_JOBS_ENV = "VEXORA_DAILY_JOBS"
DAILY_PREVIEWS_ENV = "VEXORA_DAILY_PREVIEWS"
DEEP_ALLOW_ENV = "VEXORA_DEEP_ALLOW"
DAILY_DEEP_ENV = "VEXORA_DAILY_DEEP"
DAILY_DEEP_GLOBAL_ENV = "VEXORA_DAILY_DEEP_GLOBAL"

DAY_S = 24 * 3600


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def max_video_seconds() -> float:
    return _number(MAX_SECONDS_ENV, 180)


def max_video_side() -> int:
    return int(_number(MAX_SIDE_ENV, 2160))


class VideoInfo(BaseModel):
    duration_s: float
    width: int
    height: int
    fps: float
    codec: str


def probe_video(path: Path) -> VideoInfo:
    """Cabecera del video, o 422 si no es un video que el pipeline pueda leer o se pasa de los
    límites. No decodifica fotogramas: ~0,1 s."""
    import imageio_ffmpeg

    try:
        reader = imageio_ffmpeg.read_frames(str(path))
        meta = next(reader)
        reader.close()
    except (OSError, RuntimeError, StopIteration) as error:
        raise HTTPException(422, "No pudimos leer el video. Expórtalo de nuevo en MP4 (H.264) y vuelve a subirlo.") from error
    width, height = (int(v) for v in meta.get("size") or (0, 0))
    duration = float(meta.get("duration") or 0.0)
    if width <= 0 or height <= 0 or duration <= 0:
        raise HTTPException(422, "No pudimos leer el video. Expórtalo de nuevo en MP4 (H.264) y vuelve a subirlo.")
    max_seconds = max_video_seconds()
    if duration > max_seconds:
        raise HTTPException(422, f"El video dura {duration:.0f} s y el máximo es {max_seconds:.0f} s. Recórtalo y vuelve a subirlo.")
    max_side = max_video_side()
    if max(width, height) > max_side:
        raise HTTPException(422, f"El video mide {width}×{height} y el máximo es {max_side} px en el lado largo. Expórtalo a 1080p.")
    return VideoInfo(duration_s=round(duration, 2), width=width, height=height, fps=float(meta.get("fps") or 0.0), codec=str(meta.get("codec") or ""))


def _refuse(user: User, rule: str, message: str) -> HTTPException:
    telemetry.event("security.quota_exceeded", level=logging.WARNING, usr={"id": telemetry.user_ref(user.uid)}, rule=rule)
    return HTTPException(429, message)


def deep_allowed(user: User) -> bool:
    allow = {item.strip().lower() for item in os.environ.get(DEEP_ALLOW_ENV, "").split(",") if item.strip()}
    return "*" in allow or user.uid.lower() in allow or (user.email or "").lower() in allow


def check_quota(user: User, mine: list[Job], everyone: list[Job], deep: bool, now: float | None = None) -> None:
    """429 si `user` ya no puede encolar otro trabajo (o uno con análisis profundo)."""
    if not auth_enabled():
        return
    now = now or time.time()
    active = sum(job.status in ("queued", "running") for job in mine)
    if active >= _number(MAX_ACTIVE_ENV, 2):
        raise _refuse(user, "active_jobs", "Ya tienes videos en proceso. Espera a que terminen para pedir otro.")
    today = [job for job in mine if now - job.created < DAY_S]
    if len(today) >= _number(DAILY_JOBS_ENV, 20):
        raise _refuse(user, "daily_jobs", "Llegaste al límite de videos por hoy. Vuelve a intentarlo mañana.")
    if not deep:
        return
    if not deep_allowed(user):
        raise _refuse(user, "deep_not_allowed", "El análisis profundo con IA aún no está disponible para tu cuenta. Usa el análisis económico.")
    if sum(job.deep for job in today) >= _number(DAILY_DEEP_ENV, 2):
        raise _refuse(user, "daily_deep", "Llegaste al límite de análisis profundos por hoy. Usa el análisis económico o vuelve mañana.")
    global_today = sum(job.deep and now - job.created < DAY_S for job in everyone)
    if global_today >= _number(DAILY_DEEP_GLOBAL_ENV, 20):
        raise _refuse(user, "daily_deep_global", "El análisis profundo está saturado por hoy. Usa el análisis económico o vuelve mañana.")


def check_preview_quota(user: User, today: int) -> None:
    """429 si `user` ya pidió todas sus vistas previas del editor de las últimas 24 h (cada una cuesta CPU)."""
    if not auth_enabled():
        return
    limit = _number(DAILY_PREVIEWS_ENV, 60)
    if today >= limit:
        raise _refuse(user, "daily_previews", f"Llegaste al límite de {limit:.0f} vistas previas por hoy. Aplica los cambios para ver el resultado o vuelve mañana.")
