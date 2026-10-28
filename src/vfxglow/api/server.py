"""API HTTP del servicio de edición (FastAPI).

    vfxglow-api                      # http://127.0.0.1:8000  (docs en /docs)

Endpoints bajo /api: estilos disponibles, crear trabajos subiendo un video, seguir su progreso
(JSON o eventos SSE), variaciones con otro estilo o semilla, y los videos original y editado.
Si existe web/dist (el front compilado), se sirve en la raíz.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path

import cv2
import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vfxglow import telemetry
from vfxglow.analysis.quality import QualityWarning
from vfxglow.api import limits
from vfxglow.api.auth import User, auth_enabled, check_bind, current_user, media_key, media_owner
from vfxglow.api.jobs import Job, JobBusy, JobStore, NotRetryable, UploadTooLarge, owns
from vfxglow.api.layers import LayerStore, estimate_seconds
from vfxglow.api.previews import PreviewStore, window_for
from vfxglow.api.uploads import TooManyAnalyzing, Upload, UploadNotFound, UploadStore, UploadUsed
from vfxglow.config import PRESET_ALIASES, catalog_name
from vfxglow.telemetry import redact

ROOT = Path(os.environ.get("VFXGLOW_ROOT", Path.cwd()))
CONFIG = ROOT / "configs" / "default.yaml"
VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
MAX_UPLOAD_MB = 500
JOB_NOT_FOUND = "Trabajo no encontrado"
UPLOAD_GONE = "La subida ya no existe: vuelve a cargar el video."

app = FastAPI(title="VFX Glow", version="1.0", description="Edición de video con efectos de neón guiados por el movimiento.")
app.add_middleware(
    CORSMiddleware,
    # En producción: VEXORA_CORS_ORIGINS=https://app.ejemplo.com (separados por comas). Nunca "*".
    allow_origins=[o.strip() for o in os.environ.get("VEXORA_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
store: JobStore | None = None
upload_store: UploadStore | None = None

# Cabeceras de seguridad en toda respuesta. Sin CSP todavía: hay que medir antes qué necesita el
# acceso con Google (ventana emergente de Firebase) para no romperlo.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    # Las URLs de archivos llevan la llave ?k=: que no viaje en el Referer a otros sitios.
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")


def _production() -> bool:
    return os.environ.get("VEXORA_ENV", "dev").strip().lower() == "prod"


def _client_ip(request: Request) -> str | None:
    """La IP sin su último tramo (privacidad): 190.24.8.0, 2800:e2:4a::."""
    host = request.client.host if request.client else None
    if not host:
        return None
    if ":" in host:
        return ":".join(host.split(":")[:3]) + "::"
    parts = host.split(".")
    return ".".join(parts[:3] + ["0"]) if len(parts) == 4 else host


@app.middleware("http")
async def observe(request: Request, call_next) -> Response:
    """Una línea http.request por petición (ruta plantilla, estado, duración) y las cabeceras de
    seguridad. En producción, la documentación interactiva de la API no se sirve."""
    started = time.perf_counter()
    request_id = telemetry.new_trace_id()
    if _production() and request.url.path in DOCS_PATHS:
        response: Response = Response(status_code=404)
    else:
        response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    response.headers["X-Request-Id"] = request_id
    route = getattr(request.scope.get("route"), "path", None)
    telemetry.event(
        "http.request",
        request_id=request_id,
        http={"method": request.method, "route": route or "sin_ruta", "status_code": response.status_code},
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
        bytes_out=response.headers.get("content-length"),
        network={"client_ip": _client_ip(request)},
        user_agent=request.headers.get("user-agent", "")[:200],
    )
    return response


def jobs() -> JobStore:
    global store
    if store is None:
        store = JobStore(ROOT / "api_data", CONFIG)
    return store


def _catalog_names() -> list[str]:
    return [style.name for style in _styles_for(_styles_stamp()) if style.kind == "catalog"]


def uploads() -> UploadStore:
    """Las subidas; se rehacen si cambia el almacén de trabajos (las pruebas lo reemplazan)."""
    global upload_store
    if upload_store is None or upload_store.jobs is not jobs():
        upload_store = UploadStore(jobs(), _catalog_names)
    return upload_store


# ----- estilos -----


class Style(BaseModel):
    kind: str
    name: str
    title: str
    description: str
    subtitle: str = ""
    palette: list[tuple[float, float, float]]
    actions: list[str]
    needs: list[str]
    tags: list[str] = []


def _styles_stamp() -> tuple[tuple[str, int], ...]:
    """Qué archivos de catálogos y presets hay y de cuándo son: si algo cambia, se vuelve a leer."""
    folders = (ROOT / "configs" / "catalogs", ROOT / "configs" / "presets")
    return tuple((f"{folder.name}/{path.name}", path.stat().st_mtime_ns) for folder in folders for path in sorted(folder.glob("*.yaml")))


@lru_cache(maxsize=1)
def _styles_for(_stamp: tuple[tuple[str, int], ...]) -> list[Style]:
    """Los estilos disponibles. Leer los catálogos (algunos extienden a otros) cuesta ~0,5 s, y los
    piden el Estudio y la página de cada trabajo: se leen una vez por cambio de archivos."""
    from vfxglow.director.choreography import load_catalog

    out = []
    for path in sorted((ROOT / "configs" / "catalogs").glob("*.yaml")):
        if path.name.startswith("_"):
            continue  # fragmentos que otros catálogos incluyen, no estilos
        catalog = load_catalog(path)
        palette = catalog.defaults.get("style", {}).get("palette") or catalog.colors
        out.append(
            Style(
                kind="catalog",
                name=catalog.name,
                title=catalog.title or catalog.name,
                description=catalog.description,
                subtitle=catalog.subtitle,
                palette=[tuple(c) for c in palette],
                actions=[r.action for r in catalog.reactions],
                needs=catalog.needs,
                tags=catalog.tags,
            )
        )
    for path in sorted((ROOT / "configs" / "presets").glob("*.yaml")):
        if path.stem in PRESET_ALIASES:
            continue  # ya es un estilo de catálogo (avatar_fire y avatar_storm → avatar)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        colors = [tuple(c) for e in raw.get("effects", []) for c in e.get("style", {}).get("colors", [])][:4]
        out.append(Style(kind="preset", name=path.stem, title=raw.get("title", path.stem), description="Preset fijo: siempre los mismos efectos.", palette=colors, actions=[], needs=[]))
    return out


@app.get("/api/styles", response_model=list[Style])
def styles() -> list[Style]:
    return _styles_for(_styles_stamp())


# ----- temporadas -----


class SeasonView(BaseModel):
    id: str
    title: str
    emoji: str
    description: str
    tags: list[str]
    palette: list[tuple[float, float, float]]
    particles: list[str]
    suggested: bool


@app.get("/api/seasons", response_model=list[SeasonView])
def seasons() -> list[SeasonView]:
    """Temporadas disponibles; `suggested` marca la que toca hoy (la web la propone)."""
    from vfxglow.director.seasons import load_seasons, suggest

    all_seasons = load_seasons(ROOT / "configs" / "seasons.yaml")
    today = suggest(all_seasons)
    return [
        SeasonView(id=s.id, title=s.title, emoji=s.emoji, description=s.description, tags=s.tags, palette=s.palette, particles=s.particles, suggested=today is not None and s.id == today.id)
        for s in all_seasons
    ]


class LookView(BaseModel):
    id: str
    title: str
    description: str


class LooksView(BaseModel):
    fuego: list[LookView]
    rayo: list[LookView]


class PlansView(BaseModel):
    draft: bool
    currency: str
    # El plan de quien pregunta (hoy no hay suscripciones: el plan por omisión).
    current: str
    plans: list[dict]
    packs: list[dict]


@app.get("/api/plans", response_model=PlansView)
def plans(user: User = Depends(current_user)) -> PlansView:
    """Planes y paquetes de créditos de "Mi plan", con los precios del servidor (configs/plans.yaml)."""
    from vfxglow.api.plans import catalog

    data = catalog(ROOT / "configs" / "plans.yaml")
    return PlansView(
        draft=data.draft,
        currency=data.currency,
        current=data.default_plan,
        plans=[plan.model_dump() for plan in data.plans],
        packs=[pack.model_dump() for pack in data.packs],
    )


@app.get("/api/looks", response_model=LooksView)
def looks() -> LooksView:
    """Estilos de fuego y de rayo que el cliente puede elegir antes de renderizar."""
    from vfxglow.director.looks import bolt_looks, fire_looks

    return LooksView(fuego=[LookView(**x.model_dump()) for x in fire_looks()], rayo=[LookView(**x.model_dump()) for x in bolt_looks()])


class PropView(BaseModel):
    id: str
    title: str
    wearable: bool


@app.get("/api/props", response_model=list[PropView])
def props() -> list[PropView]:
    """Objetos protagonistas que el cliente puede elegir en los estilos que siguen uno (`needs: [props]`)."""
    from vfxglow.director.prop_choices import PROP_CHOICES

    return [PropView(id=c.id, title=c.title, wearable=c.wearable) for c in PROP_CHOICES.values()]


def _check_prop(prop: str | None) -> None:
    from vfxglow.director.prop_choices import check

    try:
        check(prop)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _check_looks(fire: str | None, bolt: str | None) -> None:
    from vfxglow.director.looks import check

    try:
        check(fire, bolt)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _check_season(season: str | None) -> None:
    from vfxglow.director.seasons import find, load_seasons

    if season and find(load_seasons(ROOT / "configs" / "seasons.yaml"), season) is None:
        raise HTTPException(422, f"Temporada desconocida: {season}")


# ----- trabajos -----


class JobView(Job):
    # Etiquetas del estilo (y de la temporada) para las tarjetas de Mis proyectos.
    tags: list[str] = []
    # Se puede abrir en el editor de efectos (coreografía terminada con su guion guardado).
    editable: bool = False
    # Terminada, de catálogo y sin guion guardado (hecha antes del editor): `prepare-edit` la deja editable.
    preparable: bool = False
    # Ya tiene las capas por pista de la vista en vivo del editor (/layers).
    layers_ready: bool = False
    duration: float | None = None
    # Segundos que se espera que tarde, y cuántos trabajos van antes en la cola (un solo trabajador).
    estimate_s: float | None = None
    queue_ahead: int = 0
    # URLs de los archivos, con la llave corta (?k=) que las abre sin cabeceras (auth.py).
    output_url: str | None = None
    original_url: str | None = None
    thumbnail_url: str | None = None
    events_url: str | None = None
    # El estilo con su nombre de hoy (un trabajo viejo puede decir baile_duo: hoy es baile; o el
    # preset avatar_fire: hoy es el catálogo avatar) y su tipo de hoy.
    style_current: str = ""
    style_kind_current: str = ""


@lru_cache(maxsize=64)
def _catalog_tags(name: str) -> list[str]:
    """Las etiquetas de un catálogo, leídas una vez (view() corre por cada trabajo en cada consulta)."""
    from vfxglow.director.choreography import load_catalog

    path = ROOT / "configs" / "catalogs" / f"{name}.yaml"
    return list(load_catalog(path).tags) if path.exists() else []


def _tags(job: Job) -> list[str]:
    tags = _catalog_tags(catalog_name(job.style)) if job.style_kind == "catalog" else []
    return [*tags, job.season.replace("_", " ")] if job.season else tags


def view(job: Job) -> JobView:
    data = job.model_dump()
    data["owner"] = None  # el uid no sale de la API
    # La consola en vivo, solo mientras procesa y sin rutas del servidor; el detalle de un fallo
    # queda en el registro del servidor (el cliente recibe error_code y un mensaje claro).
    data["log"] = [redact(line) for line in job.log[-20:]] if job.status in ("queued", "running") else []
    done = job.status == "done" and job.output
    key = f"?k={media_key(job.id, job.owner or 'local')}"
    waiting = job.status in ("queued", "running")
    return JobView(
        **data,
        tags=_tags(job),
        editable=jobs().editable(job),
        preparable=jobs().preparable(job),
        layers_ready=layers().ready(job.id),
        estimate_s=jobs().estimate(job) if waiting else None,
        queue_ahead=jobs().queue_ahead(job) if job.status == "queued" else 0,
        duration=(job.finished or 0) - job.started if job.started and job.finished else None,
        output_url=f"/api/jobs/{job.id}/output{key}" if done else None,
        original_url=f"/api/jobs/{job.id}/original{key}",
        thumbnail_url=f"/api/jobs/{job.id}/thumbnail{key}",
        events_url=f"/api/jobs/{job.id}/events{key}",
        style_current=catalog_name(job.style) if job.style_kind == "catalog" else PRESET_ALIASES.get(job.style, job.style),
        style_kind_current="catalog" if job.style_kind == "catalog" or job.style in PRESET_ALIASES else job.style_kind,
    )


# Correo de quien adopta los trabajos de antes de las cuentas (VEXORA_LEGACY_OWNER).
LEGACY_ENV = "VEXORA_LEGACY_OWNER"


def _adopt(user: User) -> None:
    legacy = os.environ.get(LEGACY_ENV, "").strip().lower()
    # Solo con el correo verificado: cualquiera puede registrar un correo ajeno con contraseña.
    if auth_enabled() and legacy and user.email_verified and (user.email or "").lower() == legacy:
        adopted = jobs().adopt(user.uid)
        if adopted:
            logging.getLogger("vfxglow.api").info("%s adoptó %d trabajos sin dueño", user.email, adopted)


def _job(job_id: str, user: User) -> Job:
    """El trabajo, solo si es de `user`. El de otro da 404 (no se revela que existe)."""
    job = jobs().get(job_id)
    if job is None or not owns(job, user.uid):
        raise HTTPException(404, JOB_NOT_FOUND)
    return job


def _media_job(job_id: str, key: str | None) -> Job:
    """El trabajo de un archivo pedido con la llave corta (?k=)."""
    job = jobs().get(job_id)
    if job is None:
        raise HTTPException(404, JOB_NOT_FOUND)
    media_owner(job_id, key, job.owner or "local")
    return job


def _check_style(kind: str, name: str) -> str:
    """El nombre del estilo, con los nombres viejos de catálogo ya traducidos; 422 si no existe."""
    if kind == "catalog":
        name = catalog_name(name)
    folder = "catalogs" if kind == "catalog" else "presets"
    if kind not in ("catalog", "preset") or not (ROOT / "configs" / folder / f"{name}.yaml").exists():
        raise HTTPException(422, f"Estilo desconocido: {kind}/{name}")
    return name


@app.get("/api/jobs", response_model=list[JobView])
def list_jobs(user: User = Depends(current_user)) -> list[JobView]:
    _adopt(user)
    return [view(job) for job in jobs().list(user.uid)]


class LimitsView(BaseModel):
    max_upload_mb: int
    max_video_seconds: float
    max_video_side: int
    # El análisis profundo es de pago: solo las cuentas permitidas (limits.deep_allowed) lo usan.
    deep_allowed: bool


@app.get("/api/limits", response_model=LimitsView)
def get_limits(user: User = Depends(current_user)) -> LimitsView:
    """Lo que la web avisa antes de subir: duración, tamaño y si esta cuenta tiene análisis profundo."""
    return LimitsView(
        max_upload_mb=MAX_UPLOAD_MB,
        max_video_seconds=limits.max_video_seconds(),
        max_video_side=limits.max_video_side(),
        deep_allowed=limits.deep_allowed(user) or not auth_enabled(),
    )


@app.get("/api/me", response_model=User)
def me(user: User = Depends(current_user)) -> User:
    return user


@app.post("/api/jobs", response_model=JobView, status_code=201)
def create_job(
    video: UploadFile | None = File(None),
    upload_id: str | None = Form(None),
    style_kind: str = Form("catalog"),
    style: str = Form(...),
    seed: int | None = Form(None),
    season: str | None = Form(None),
    wardrobe: str | None = Form(None),
    deep: bool = Form(False),
    fire_style: str | None = Form(None),
    bolt_style: str | None = Form(None),
    prop: str | None = Form(None),
    user: User = Depends(current_user),
) -> JobView:
    # Exactamente uno: el video, o una subida que ya se analizó (o se está analizando).
    if video is not None and not video.filename:
        video = None
    if (video is None) == (not upload_id):
        raise HTTPException(422, "Envía el video o una subida.")
    if video is not None:
        if Path(video.filename or "").suffix.lower() not in VIDEO_TYPES:
            raise HTTPException(415, f"Formato no soportado. Usa {', '.join(sorted(VIDEO_TYPES))}")
        if video.size is not None and video.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"El video supera {MAX_UPLOAD_MB} MB")
    style = _check_style(style_kind, style)
    _check_season(season or None)
    _check_looks(fire_style or None, bolt_style or None)
    _check_prop(prop or None)
    wear = _check_wardrobe(json.loads(wardrobe) if wardrobe and wardrobe.strip().startswith("{") else ({"*": wardrobe} if wardrobe else {}))
    deep = deep and style_kind == "catalog"
    limits.check_quota(user, jobs().list(user.uid), jobs().list(), deep)
    options = dict(
        owner=user.uid, wardrobe=wear, deep=deep, fire_style=fire_style or None, bolt_style=bolt_style or None, prop=prop or None
    )
    if video is None:
        return view(_job_from_upload(upload_id or "", user, style_kind, style, seed, season or None, options))
    try:
        job = jobs().create(
            video.filename or "video.mp4",
            video.file,
            style_kind,
            style,
            seed,
            season or None,
            max_bytes=MAX_UPLOAD_MB * 1024 * 1024,
            check=limits.probe_video,
            **options,
        )
    except UploadTooLarge as error:
        raise HTTPException(413, f"El video supera {MAX_UPLOAD_MB} MB") from error
    return view(job)


def _job_from_upload(upload_id: str, user: User, style_kind: str, style: str, seed: int | None, season: str | None, options: dict) -> Job:
    """El trabajo que usa el video de una subida: el archivo pasa al trabajo y la subida queda `used`."""
    try:
        item, previous = uploads().claim(upload_id, user.uid)
    except UploadNotFound as error:
        raise HTTPException(404, UPLOAD_GONE) from error
    except UploadUsed as error:
        raise HTTPException(409, "Esta subida ya se usó en otro video.") from error
    try:
        info = limits.VideoInfo(duration_s=item.video_seconds or 0.0, width=item.video_width or 0, height=item.video_height or 0, fps=0.0, codec="")
        job = jobs().create(item.filename, None, style_kind, style, seed, season, source=Path(item.video_path), info=info, **options)
    except BaseException:
        uploads().release(upload_id, previous)
        raise
    uploads().finish_used(item)
    return job


class RecommendationView(BaseModel):
    style: str
    reason: str
    alternatives: list[dict[str, str]]


class UploadView(BaseModel):
    id: str
    status: str
    filename: str
    created: float
    video_seconds: float | None = None
    video_width: int | None = None
    video_height: int | None = None
    video_bytes: int | None = None
    error: str | None = None
    recommendation: RecommendationView | None = None
    warnings: list[QualityWarning] = []


def upload_view(item: Upload) -> UploadView:
    picks = item.recommendation if item.status == "ready" else []
    return UploadView(
        **item.model_dump(include={"id", "status", "filename", "created", "video_seconds", "video_width", "video_height", "video_bytes", "error"}),
        recommendation=RecommendationView(style=picks[0].style, reason=picks[0].reason, alternatives=[p.model_dump() for p in picks[1:]]) if picks else None,
        warnings=item.warnings if item.status == "ready" else [],
    )


@app.post("/api/uploads", response_model=UploadView, status_code=201)
def create_upload(video: UploadFile = File(...), user: User = Depends(current_user)) -> UploadView:
    """Guarda el video y empieza a analizarlo ya, mientras la persona elige estilo."""
    if Path(video.filename or "").suffix.lower() not in VIDEO_TYPES:
        raise HTTPException(415, f"Formato no soportado. Usa {', '.join(sorted(VIDEO_TYPES))}")
    if video.size is not None and video.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"El video supera {MAX_UPLOAD_MB} MB")
    try:
        item = uploads().create(video.filename or "video.mp4", video.file, user.uid, MAX_UPLOAD_MB * 1024 * 1024, limits.probe_video)
    except UploadTooLarge as error:
        raise HTTPException(413, f"El video supera {MAX_UPLOAD_MB} MB") from error
    except TooManyAnalyzing as error:
        raise HTTPException(429, "Ya tienes videos analizándose; espera a que terminen.") from error
    return upload_view(item)


@app.get("/api/uploads/{upload_id}", response_model=UploadView)
def get_upload(upload_id: str, user: User = Depends(current_user)) -> UploadView:
    try:
        return upload_view(uploads().get(upload_id, user.uid))
    except UploadNotFound as error:
        raise HTTPException(404, UPLOAD_GONE) from error


@app.delete("/api/uploads/{upload_id}", status_code=204)
def delete_upload(upload_id: str, user: User = Depends(current_user)) -> Response:
    try:
        uploads().delete(upload_id, user.uid)
    except UploadNotFound as error:
        raise HTTPException(404, UPLOAD_GONE) from error
    previews().forget_job(upload_id)
    return Response(status_code=204)


class VariationRequest(BaseModel):
    style_kind: str = "catalog"
    style: str
    seed: int | None = None
    season: str | None = None
    # Vestuario por persona; sin él, el del trabajo de origen.
    wardrobe: dict[str, str] | None = None
    # Análisis profundo; sin valor, el del trabajo de origen.
    deep: bool | None = None
    # Estilos de fuego y de rayo; sin valor, los del trabajo de origen ("" = los del catálogo).
    fire_style: str | None = None
    bolt_style: str | None = None
    # Objeto protagonista; sin valor, el del trabajo de origen ("" = el del catálogo).
    prop: str | None = None


def _check_wardrobe(wardrobe: dict[str, str]) -> dict[str, str]:
    from vfxglow.director.choreography import WARDROBE_CHOICES

    for person, choice in wardrobe.items():
        if choice not in WARDROBE_CHOICES or not (person == "*" or person.startswith("person_")):
            raise HTTPException(422, f"Vestuario no válido: {person}={choice}")
    return wardrobe


@app.post("/api/jobs/{job_id}/variations", response_model=JobView, status_code=201)
def create_variation(job_id: str, body: VariationRequest, user: User = Depends(current_user)) -> JobView:
    style = _check_style(body.style_kind, body.style)
    _check_season(body.season)
    wear = _check_wardrobe(body.wardrobe) if body.wardrobe is not None else None
    _check_looks(body.fire_style or None, body.bolt_style or None)
    _check_prop(body.prop or None)
    parent = _job(job_id, user)
    deep = (parent.deep if body.deep is None else body.deep) and body.style_kind == "catalog"
    limits.check_quota(user, jobs().list(user.uid), jobs().list(), deep)
    return view(jobs().variation(parent, body.style_kind, style, body.seed, body.season, wear, body.deep, body.fire_style, body.bolt_style, body.prop))


@app.post("/api/jobs/{job_id}/retry", response_model=JobView)
def retry_job(job_id: str, user: User = Depends(current_user)) -> JobView:
    """Vuelve a procesar un trabajo que falló, con lo mismo que pidió."""
    job = _job(job_id, user)
    # Reintentar no suma un trabajo del día ni otro análisis profundo: solo cuenta lo activo.
    limits.check_quota(user, jobs().list(user.uid), jobs().list(), deep=False)
    try:
        return view(jobs().retry(job.id))
    except NotRetryable as error:
        raise HTTPException(409, "Solo se puede reintentar un video que falló.") from error


@app.get("/api/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str, user: User = Depends(current_user)) -> JobView:
    return view(_job(job_id, user))


@app.post("/api/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str, user: User = Depends(current_user)) -> dict:
    """Cancela un trabajo en cola (se borra ya) o en curso (se corta en unos segundos y se borra)."""
    _job(job_id, user)
    outcome = jobs().cancel(job_id)
    if outcome == "none":
        raise HTTPException(409, "Este video ya no está en proceso: no hay nada que cancelar.")
    return {"status": outcome}


# ----- editor de efectos (director/edits.py) -----


class EditorMoment(BaseModel):
    id: str
    start: float
    end: float
    choice: str
    action: str
    person: str | None = None
    note: str = ""


class EditorTrack(BaseModel):
    key: str
    label: str
    icon: str
    color: str
    element: str | None = None
    start: float
    end: float
    moments: list[EditorMoment]


class EditorOption(BaseModel):
    option: str
    action: str
    # La pista de la opción: su nombre (una pista por tipo de efecto).
    track: str
    element: str | None = None


class EditorView(BaseModel):
    job_id: str
    fps: float
    frames: int
    duration: float
    tracks: list[EditorTrack]
    options: list[EditorOption]


def _editor_catalog(job: Job):
    """El catálogo con que se hizo la versión (vestuario, temporada y looks incluidos)."""
    from vfxglow.config import load_config
    from vfxglow.director.director import CreativeDirector

    director = load_config(CONFIG).director.model_copy(
        update={"provider": "catalog", "catalog": job.style, "season": job.season, "fire_style": job.fire_style, "bolt_style": job.bolt_style, "wardrobe": dict(job.wardrobe)}
    )
    return CreativeDirector(director, ROOT / "configs" / "presets").catalog()


def _video_timing(job: Job) -> tuple[float, int]:
    cap = cv2.VideoCapture(job.video_path)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    return fps, frames


@app.get("/api/jobs/{job_id}/editor", response_model=EditorView)
def job_editor(job_id: str, user: User = Depends(current_user)) -> EditorView:
    """Las pistas y los momentos de una versión para el editor, y lo que se le puede agregar."""
    from vfxglow.director.edits import Moment, assign_tracks, element_lookup

    job = _job(job_id, user)
    if not jobs().editable(job):
        raise HTTPException(409, "Esta versión no se puede editar: solo las coreografías terminadas desde que existe el editor. Crea otra versión para editarla.")
    catalog = _editor_catalog(job)
    element_of = element_lookup(catalog)
    moments = [Moment.model_validate(m) for m in json.loads(jobs().artifact(job.id, "moments").read_text(encoding="utf-8"))]
    tracks = assign_tracks(moments, element_of)
    fps, frames = _video_timing(job)
    by_id = {m.id: m for m in moments}
    views = []
    for track in tracks:
        items = [by_id[mid] for mid in track.moments]
        views.append(
            EditorTrack(
                **track.model_dump(exclude={"moments"}),
                start=round(min(m.frame for m in items) / fps, 2),
                end=round(max(m.until for m in items) / fps, 2),
                moments=[
                    EditorMoment(id=m.id, start=round(m.frame / fps, 2), end=round(max(m.until, m.frame) / fps, 2), choice=m.choice, action=m.action, person=m.target.split(":")[0] if m.target.startswith("person_") else None, note=m.note)
                    for m in sorted(items, key=lambda m: m.frame)
                ],
            )
        )
    options = []
    for reaction in catalog.reactions:
        for option in reaction.options:
            if not option.effects:
                continue
            options.append(EditorOption(option=option.name, action=reaction.action, track=option.name, element=element_of(option.name, reaction.action) or None))
    return EditorView(job_id=job.id, fps=fps, frames=frames, duration=round(frames / fps, 2), tracks=views, options=options)


@app.post("/api/jobs/{job_id}/prepare-edit", response_model=JobView)
def prepare_edit(job_id: str, user: User = Depends(current_user)) -> JobView:
    """Deja editable una versión hecha antes del editor (vuelve a dirigir con su análisis; no dibuja)."""
    job = _job(job_id, user)
    if job.status != "done":
        raise HTTPException(409, "La versión todavía no termina: espera a que esté lista.")
    if job.style_kind != "catalog":
        raise HTTPException(409, "Solo las versiones de catálogo se pueden editar.")
    if jobs().editable(job):
        raise HTTPException(409, "Esta versión ya se puede editar.")
    started = time.time()
    try:
        prepared = jobs().prepare(job)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    telemetry.event("job.prepared", job_id=job.id, duration_ms=round((time.time() - started) * 1000))
    return view(prepared)


class EditRequest(BaseModel):
    edits: list[dict]


def _validated_edits(job: Job, raw: list[dict]) -> list:
    """Los cambios del editor ya validados contra el guion de la versión; 422 con el motivo si no."""
    from vfxglow.analysis.schema import MotionEvent
    from vfxglow.director.edits import Edit, Moment, apply_edits, assign_tracks, element_lookup
    from vfxglow.director.schema import EffectScript

    try:
        edits = [Edit.model_validate(e) for e in raw]
    except ValueError as error:
        raise HTTPException(422, f"Cambio no válido: {error}") from error
    # Un efecto nuevo se compila en el trabajo (necesita el análisis); sin él, se prueba todo aquí.
    if not any(e.op == "add" for e in edits):
        script = EffectScript.model_validate_json(jobs().artifact(job.id, "script").read_text(encoding="utf-8"))
        moments = [Moment.model_validate(m) for m in json.loads(jobs().artifact(job.id, "moments").read_text(encoding="utf-8"))]
        events = [MotionEvent.model_validate(e) for e in json.loads(jobs().artifact(job.id, "events").read_text(encoding="utf-8"))]
        fps, frames = _video_timing(job)
        try:
            apply_edits(script, moments, assign_tracks(moments, element_lookup(_editor_catalog(job))), edits, events, fps, frames)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    return edits


@app.post("/api/jobs/{job_id}/edit", response_model=JobView, status_code=201)
def edit_job(job_id: str, body: EditRequest, user: User = Depends(current_user)) -> JobView:
    """Crea una versión nueva con los cambios del editor. Se validan antes de encolar: un cambio
    imposible responde 422 con el motivo."""
    job = _job(job_id, user)
    if not jobs().editable(job):
        raise HTTPException(409, "Esta versión no se puede editar.")
    if not body.edits:
        raise HTTPException(422, "No hay cambios que aplicar.")
    edits = _validated_edits(job, body.edits)
    limits.check_quota(user, jobs().list(user.uid), jobs().list(), deep=False)
    return view(jobs().edit(job, [e.model_dump(exclude_none=True) for e in edits]))


class PreviewRequest(BaseModel):
    edits: list[dict]
    # Segundo del cabezal: la vista previa cubre 1,5 s a cada lado.
    at: float


class PreviewView(BaseModel):
    preview_id: str
    status: str  # rendering | ready | failed
    url: str | None = None
    start: float
    end: float
    error: str | None = None


_previews: PreviewStore | None = None


def previews() -> PreviewStore:
    global _previews
    if _previews is None or _previews.jobs is not jobs():
        _previews = PreviewStore(jobs())
    return _previews


def _preview_view(job: Job, item) -> PreviewView:
    ready = previews().url_path(item) is not None
    status = item.status if item.status != "ready" or ready else "failed"
    key = f"?k={media_key(job.id, job.owner or 'local')}"
    return PreviewView(
        preview_id=item.id,
        status=status,
        url=f"/api/jobs/{job.id}/preview/{item.id}.mp4{key}" if ready else None,
        start=round(item.window[0] / item.fps, 3),
        end=round((item.window[1] + 1) / item.fps, 3),
        error=item.error if status == "failed" else None,
    )


@app.post("/api/jobs/{job_id}/preview", response_model=PreviewView, status_code=202)
def create_preview(job_id: str, body: PreviewRequest, user: User = Depends(current_user)) -> PreviewView:
    """Vista previa de ~3 s alrededor de `at` con los cambios pendientes, sin crear versión. Los
    cambios imposibles responden 422 como en /edit."""
    job = _job(job_id, user)
    if not jobs().editable(job):
        raise HTTPException(409, "Esta versión no se puede editar.")
    if not body.edits:
        raise HTTPException(422, "No hay cambios que ver.")
    edits = _validated_edits(job, body.edits)
    fps, frames = _video_timing(job)
    window = window_for(max(body.at, 0.0), fps, frames)
    item, cached = previews().submit(
        job.id,
        user.uid,
        [e.model_dump(exclude_none=True) for e in edits],
        window,
        fps,
        check_quota=lambda today: limits.check_preview_quota(user, today),
    )
    if cached and item.status == "ready":
        telemetry.event("preview.finished", job_id=job.id, duration_ms=0, frames=item.frames, cache_hit=True)
    return _preview_view(job, item)


@app.get("/api/jobs/{job_id}/preview/{preview_id}.mp4")
def preview_file(job_id: str, preview_id: str, k: str | None = Query(None)) -> FileResponse:
    job = _media_job(job_id, k)
    item = previews().get(job.id, preview_id)
    path = previews().url_path(item) if item is not None else None
    if path is None:
        raise HTTPException(404, "La vista previa ya no existe")
    return FileResponse(path, media_type="video/mp4")


_layers: LayerStore | None = None


def layers() -> LayerStore:
    global _layers
    if _layers is None or _layers.jobs is not jobs():
        _layers = LayerStore(jobs())
    return _layers


class LayersView(BaseModel):
    status: str  # "none" | "rendering" | "ready" | "failed"
    url: str | None = None
    layout: dict | None = None
    error: str | None = None
    estimate_s: int = 0


def _layers_view(job: Job) -> LayersView:
    status, error = layers().status(job.id)
    layout = layers().layout(job.id) if status == "ready" else None
    if status == "ready" and layout is None:
        status = "none"
    key = f"?k={media_key(job.id, job.owner or 'local')}"
    frames = int(layout["frames"]) if layout else _video_timing(job)[1]
    return LayersView(
        status=status,
        url=f"/api/jobs/{job.id}/layers.mp4{key}" if status == "ready" else None,
        layout=layout,
        error=error if status == "failed" else None,
        estimate_s=estimate_seconds(frames),
    )


@app.post("/api/jobs/{job_id}/layers", response_model=LayersView, status_code=202)
def create_layers(job_id: str, user: User = Depends(current_user)) -> LayersView:
    """Genera (una vez por versión) las capas por pista de la vista en vivo del editor. Cuenta
    como una vista previa en la cuota."""
    job = _job(job_id, user)
    if not jobs().editable(job):
        raise HTTPException(409, "Esta versión no se puede editar, así que no tiene vista en vivo.")
    layers().submit(
        job,
        check_quota=lambda: limits.check_preview_quota(user, previews().renders_today(user.uid)),
        on_queued=lambda: previews().note_render(user.uid),
    )
    return _layers_view(job)


@app.get("/api/jobs/{job_id}/layers", response_model=LayersView)
def get_layers(job_id: str, user: User = Depends(current_user)) -> LayersView:
    return _layers_view(_job(job_id, user))


@app.get("/api/jobs/{job_id}/layers.mp4")
def layers_file(job_id: str, k: str | None = Query(None)) -> FileResponse:
    job = _media_job(job_id, k)
    if not layers().ready(job.id):
        raise HTTPException(404, "Las capas ya no existen")
    return FileResponse(layers().video_path(job.id), media_type="video/mp4")


@app.get("/api/jobs/{job_id}/preview/{preview_id}", response_model=PreviewView)
def get_preview(job_id: str, preview_id: str, user: User = Depends(current_user)) -> PreviewView:
    job = _job(job_id, user)
    item = previews().get(job.id, preview_id)
    if item is None:
        raise HTTPException(404, "La vista previa ya no existe")
    return _preview_view(job, item)


# ----- vista previa del Estudio (una subida lista + el estilo elegido) -----


class StudioPreviewRequest(BaseModel):
    style_kind: str = "catalog"
    style: str
    season: str | None = None
    fire_style: str | None = None
    bolt_style: str | None = None
    # Vestuario por persona, o un solo nombre para todas ("*").
    wardrobe: dict[str, str] | str | None = None
    # Objeto protagonista (director/prop_choices.py); sin él, el del catálogo.
    prop: str | None = None


def _studio_view(upload: Upload, item) -> PreviewView:
    ready = previews().url_path(item) is not None
    status = item.status if item.status != "ready" or ready else "failed"
    key = f"?k={media_key(upload.id, upload.owner)}"
    return PreviewView(
        preview_id=item.id,
        status=status,
        url=f"/api/uploads/{upload.id}/preview/{item.id}.mp4{key}" if ready else None,
        start=round(item.window[0] / item.fps, 3),
        end=round((item.window[1] + 1) / item.fps, 3),
        error=item.error if status == "failed" else None,
    )


def _owned_upload(upload_id: str, user: User) -> Upload:
    try:
        return uploads().get(upload_id, user.uid)
    except UploadNotFound as error:
        raise HTTPException(404, UPLOAD_GONE) from error


@app.post("/api/uploads/{upload_id}/preview", response_model=PreviewView, status_code=202)
def create_upload_preview(upload_id: str, body: StudioPreviewRequest, user: User = Depends(current_user)) -> PreviewView:
    """Unos 3 s con efectos reales del estilo elegido, en el tramo más activo del video, antes de
    crear el trabajo. Solo estilos de catálogo; los que piden hojas u objeto (`needs`) los buscan
    solo en ese tramo."""
    from vfxglow.analysis.schema import MotionBrief
    from vfxglow.api.previews import STUDIO_SIDE, busiest_window
    from vfxglow.io.store import read_model

    upload = _owned_upload(upload_id, user)
    if body.style_kind != "catalog":
        raise HTTPException(422, "La vista previa solo está disponible para estilos del catálogo.")
    style = _check_style("catalog", body.style)
    _check_season(body.season or None)
    _check_looks(body.fire_style or None, body.bolt_style or None)
    _check_prop(body.prop or None)
    wardrobe = body.wardrobe if isinstance(body.wardrobe, dict) else ({"*": body.wardrobe} if body.wardrobe else {})
    wear = _check_wardrobe(wardrobe)
    if upload.status == "used":
        raise HTTPException(409, "Esta subida ya se usó en otro video.")
    brief_path = Path(upload.run_dir or "") / "analysis" / "motion_brief.json"
    if upload.status != "ready" or not upload.run_dir or not brief_path.exists():
        raise HTTPException(409, "Espera a que termine el análisis.")
    brief = read_model(brief_path, MotionBrief)
    window = busiest_window(brief)
    studio = dict(
        video_path=upload.video_path,
        run_dir=upload.run_dir,
        style=style,
        season=body.season or None,
        fire_style=body.fire_style or None,
        bolt_style=body.bolt_style or None,
        wardrobe=wear,
        prop=body.prop or None,
    )
    item, cached = previews().submit_studio(
        upload.id,
        user.uid,
        studio,
        window,
        brief.video.fps or 30.0,
        STUDIO_SIDE,
        check_quota=lambda today: limits.check_preview_quota(user, today),
    )
    if cached and item.status == "ready":
        telemetry.event("preview.finished", job_id=upload.id, duration_ms=0, frames=item.frames, cache_hit=True, kind="studio")
    return _studio_view(upload, item)


@app.get("/api/uploads/{upload_id}/preview/{preview_id}.mp4")
def upload_preview_file(upload_id: str, preview_id: str, k: str | None = Query(None)) -> FileResponse:
    upload = uploads().peek(upload_id)
    if upload is None:
        raise HTTPException(404, UPLOAD_GONE)
    media_owner(upload.id, k, upload.owner)
    item = previews().get(upload.id, preview_id)
    path = previews().url_path(item) if item is not None else None
    if path is None:
        raise HTTPException(404, "La vista previa ya no existe")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/uploads/{upload_id}/preview/{preview_id}", response_model=PreviewView)
def get_upload_preview(upload_id: str, preview_id: str, user: User = Depends(current_user)) -> PreviewView:
    upload = _owned_upload(upload_id, user)
    item = previews().get(upload.id, preview_id)
    if item is None:
        raise HTTPException(404, "La vista previa ya no existe")
    return _studio_view(upload, item)


@app.get("/api/jobs/{job_id}/filmstrip")
def job_filmstrip(job_id: str, n: int = Query(12, ge=4, le=24), k: str | None = Query(None)) -> Response:
    """Tira de N fotogramas del video editado (o del original), para la línea de tiempo del editor."""
    import numpy as np

    job = _media_job(job_id, k)
    source = job.output if job.output and Path(job.output).exists() else job.video_path
    cache = jobs().outputs / f"{job.id}.filmstrip-{n}.jpg"
    if not cache.exists():
        cap = cv2.VideoCapture(source)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        tiles = []
        for i in range(n):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int((i + 0.5) * total / n))
            ok, frame = cap.read()
            if ok:
                height = 96
                tiles.append(cv2.resize(frame, (max(int(frame.shape[1] * height / frame.shape[0]), 1), height), interpolation=cv2.INTER_AREA))
        cap.release()
        if not tiles:
            raise HTTPException(404, "Sin fotogramas")
        cv2.imwrite(str(cache), np.hstack(tiles), [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return FileResponse(cache, media_type="image/jpeg")


class RenameRequest(BaseModel):
    title: str


@app.patch("/api/jobs/{job_id}", response_model=JobView)
def rename_job(job_id: str, body: RenameRequest, user: User = Depends(current_user)) -> JobView:
    """Renombra el proyecto (el video y todas sus versiones)."""
    _job(job_id, user)
    renamed = jobs().rename(job_id, body.title.strip()[:80])
    if renamed is None:
        raise HTTPException(404, JOB_NOT_FOUND)
    return view(renamed)


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, user: User = Depends(current_user)) -> Response:
    _job(job_id, user)
    try:
        deleted = jobs().delete(job_id)
    except JobBusy as error:
        raise HTTPException(409, "Este video se está procesando. Espera a que termine para borrarlo.") from error
    if not deleted:
        raise HTTPException(404, JOB_NOT_FOUND)
    return Response(status_code=204)


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, k: str | None = Query(None)) -> StreamingResponse:
    """Server-Sent Events: el estado del trabajo cada vez que cambia, hasta que termina."""
    _media_job(job_id, k)

    async def stream():
        last = None
        while True:
            job = jobs().get(job_id)
            if job is None:
                return
            payload = view(job).model_dump_json()
            if payload != last:
                last = payload
                yield f"data: {payload}\n\n"
            if job.status in ("done", "failed"):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/jobs/{job_id}/output")
def job_output(job_id: str, download: bool = False, k: str | None = Query(None)) -> FileResponse:
    job = _media_job(job_id, k)
    if not job.output or not Path(job.output).exists():
        raise HTTPException(404, "El video editado aún no existe")
    name = f"{Path(job.filename).stem}-{job.style}{'-' + str(job.seed) if job.seed is not None else ''}.mp4"
    return FileResponse(job.output, media_type="video/mp4", filename=name if download else None)


@app.get("/api/jobs/{job_id}/original")
def job_original(job_id: str, k: str | None = Query(None)) -> FileResponse:
    return FileResponse(_media_job(job_id, k).video_path, media_type="video/mp4")


@app.get("/api/jobs/{job_id}/thumbnail")
def job_thumbnail(job_id: str, original: bool = False, first: bool = False, k: str | None = Query(None)) -> Response:
    """Fotograma del editado (o del original con ?original=true): a un tercio del video, o el
    primero con ?first=true (póster del comparador: coincide con el inicio de la reproducción)."""
    job = _media_job(job_id, k)
    source = job.output if not original and job.output and Path(job.output).exists() else job.video_path
    kind = f"{'out' if source == job.output else 'in'}{'-first' if first else ''}"
    cache = Path(job.video_path).parent / f"thumb-{job.id}-{kind}.jpg"
    if not cache.exists():
        cap = cv2.VideoCapture(source)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0 if first else max(total // 3, 0))
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise HTTPException(404, "Sin miniatura")
        scale = (960 if first else 480) / max(frame.shape[:2])
        cv2.imwrite(str(cache), cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return FileResponse(cache, media_type="image/jpeg")


class Moment(BaseModel):
    second: float
    action: str
    target: str
    choice: str
    # La intención del gesto, cuando el momento viene del análisis profundo.
    note: str = ""


class PersonView(BaseModel):
    id: str
    label: str
    image_url: str


def _people_frames(job: Job) -> dict[str, tuple[int, tuple[float, float, float, float]]]:
    """Por persona, el fotograma donde se ve entera y más grande (y su caja). Se guarda junto al
    video."""
    cache = Path(job.video_path).parent / f"people-{Path(job.run_dir or '').name}.json"
    if cache.exists():
        return {k: (v[0], tuple(v[1])) for k, v in json.loads(cache.read_text()).items()}
    tracks = Path(job.run_dir or "") / "analysis" / "tracks.jsonl"
    best: dict[str, tuple[float, int, tuple]] = {}
    cap = cv2.VideoCapture(job.video_path)
    aspect = (cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1.0) / (cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1.0)
    cap.release()
    records = [json.loads(line) for line in tracks.open(encoding="utf-8")] if tracks.exists() else []
    # Cuántas personas tiene el video: con dos, "sola" exige ver a las dos (si una tapa a la otra,
    # el detector ve una sola y el recorte las mostraría juntas).
    crowd = max((len(r.get("people") or []) for r in records), default=1)
    if records:
        for record in records:
                boxes = [(person["person_id"], person.get("box")) for person in record.get("people") or [] if person.get("box")]
                for pid, box in boxes:
                    # De pie, entera y sola: la más alta con un ancho de persona (no los brazos
                    # abiertos) y sin la otra persona encima (el recorte la mostraría).
                    tall = box[3] - box[1]
                    wide = (box[2] - box[0]) * aspect
                    alone = len(boxes) >= crowd and all(min(box[2], other[2]) - max(box[0], other[0]) <= -0.03 for oid, other in boxes if oid != pid)
                    score = tall if wide <= 0.7 * tall and box[0] >= 0 and box[2] <= 1 else tall * 0.3
                    score *= 1.0 if alone else 0.2
                    person = {"person_id": pid}
                    if score > best.get(person["person_id"], (0.0,))[0]:
                        best[person["person_id"]] = (score, record["frame"], tuple(box))
    found = {pid: (frame, box) for pid, (_, frame, box) in sorted(best.items())}
    cache.write_text(json.dumps(found))
    return found


@app.get("/api/jobs/{job_id}/people", response_model=list[PersonView])
def job_people(job_id: str, user: User = Depends(current_user)) -> list[PersonView]:
    """Las personas del video, con un recorte de cada una (para elegir su vestuario)."""
    job = _job(job_id, user)
    key = f"?k={media_key(job.id, job.owner or 'local')}"
    return [
        PersonView(id=pid, label=f"Persona {int(pid.rsplit('_', 1)[-1]) + 1}", image_url=f"/api/jobs/{job.id}/people/{pid}.jpg{key}")
        for pid in _people_frames(job)
    ]


@app.get("/api/jobs/{job_id}/people/{person_id}.jpg")
def job_person_image(job_id: str, person_id: str, k: str | None = Query(None)) -> Response:
    job = _media_job(job_id, k)
    found = _people_frames(job)
    if person_id not in found:
        raise HTTPException(404, "Persona no encontrada")
    cache = Path(job.video_path).parent / f"person-{Path(job.run_dir or '').name}-{person_id}.jpg"
    if not cache.exists():
        frame_index, (x0, y0, x1, y1) = found[person_id]
        cap = cv2.VideoCapture(job.video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise HTTPException(404, "No se pudo leer el video")
        h, w = frame.shape[:2]
        pad_x, pad_y = (x1 - x0) * 0.15, (y1 - y0) * 0.08
        crop = frame[int(max(y0 - pad_y, 0) * h) : int(min(y1 + pad_y, 1) * h), int(max(x0 - pad_x, 0) * w) : int(min(x1 + pad_x, 1) * w)]
        scale = 360 / max(crop.shape[0], 1)
        crop = cv2.resize(crop, (max(int(crop.shape[1] * scale), 1), 360))
        cv2.imwrite(str(cache), crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return FileResponse(cache, media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/choreography", response_model=list[Moment])
def job_choreography(job_id: str, user: User = Depends(current_user)) -> list[Moment]:
    """Qué reacción salió en cada acción (solo estilos de catálogo); 'nada' se omite."""
    job = _job(job_id, user)
    if not job.run_dir:
        return []
    path = Path(job.run_dir) / "scripts" / f"{job.style}.choreography.json"
    if not path.exists():
        return []
    decisions = json.loads(path.read_text(encoding="utf-8")).get("decisions", [])
    return [Moment(note=d.get("note", ""), **{k: d[k] for k in ("second", "action", "target", "choice")}) for d in decisions if not d["choice"].startswith("nada")]


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


_web = ROOT / "web" / "dist"
if _web.exists():
    app.mount("/assets", StaticFiles(directory=_web / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """El front es una SPA: cualquier ruta que no sea /api ni un archivo devuelve index.html."""
        if path.startswith("api/"):
            raise HTTPException(404, "No encontrado")
        target = (_web / path).resolve()
        if path and target.is_file() and target.is_relative_to(_web.resolve()):
            return FileResponse(target)
        return FileResponse(_web / "index.html")


def main() -> None:
    import uvicorn

    from vfxglow.cli import load_env_file

    load_env_file(ROOT / ".env")
    # Consola en JSON (VEXORA_LOG_FORMAT=text para leerla a ojo) y logs/events.jsonl siempre en JSON.
    telemetry.setup("vexora-api", ROOT / "logs")
    host = os.environ.get("VFXGLOW_HOST", "127.0.0.1")
    check_bind(host)
    uvicorn.run(app, host=host, port=int(os.environ.get("VFXGLOW_PORT", "8000")), log_level="info", access_log=False)  # http.request lo reemplaza


if __name__ == "__main__":
    main()
