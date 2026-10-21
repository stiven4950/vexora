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
from pathlib import Path

import cv2
import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vfxglow.api.auth import User, auth_enabled, check_bind, current_user, media_key, media_owner
from vfxglow.api.jobs import Job, JobStore, owns
from vfxglow.config import PRESET_ALIASES, catalog_name

ROOT = Path(os.environ.get("VFXGLOW_ROOT", Path.cwd()))
CONFIG = ROOT / "configs" / "default.yaml"
VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
MAX_UPLOAD_MB = 500

app = FastAPI(title="VFX Glow", version="1.0", description="Edición de video con efectos de neón guiados por el movimiento.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
store: JobStore | None = None


def jobs() -> JobStore:
    global store
    if store is None:
        store = JobStore(ROOT / "api_data", CONFIG)
    return store


# ----- estilos -----


class Style(BaseModel):
    kind: str
    name: str
    title: str
    description: str
    palette: list[tuple[float, float, float]]
    actions: list[str]
    needs: list[str]
    tags: list[str] = []


@app.get("/api/styles", response_model=list[Style])
def styles() -> list[Style]:
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


@app.get("/api/looks", response_model=LooksView)
def looks() -> LooksView:
    """Estilos de fuego y de rayo que el cliente puede elegir antes de renderizar."""
    from vfxglow.director.looks import bolt_looks, fire_looks

    return LooksView(fuego=[LookView(**x.model_dump()) for x in fire_looks()], rayo=[LookView(**x.model_dump()) for x in bolt_looks()])


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
    duration: float | None = None
    # URLs de los archivos, con la llave corta (?k=) que las abre sin cabeceras (auth.py).
    output_url: str | None = None
    original_url: str | None = None
    thumbnail_url: str | None = None
    events_url: str | None = None
    # El estilo con su nombre de hoy (un trabajo viejo puede decir baile_duo: hoy es baile; o el
    # preset avatar_fire: hoy es el catálogo avatar) y su tipo de hoy.
    style_current: str = ""
    style_kind_current: str = ""


def view(job: Job) -> JobView:
    data = job.model_dump()
    data["owner"] = None  # el uid no sale de la API
    data["log"] = job.log[-20:]
    done = job.status == "done" and job.output
    key = f"?k={media_key(job.id, job.owner or 'local')}"
    return JobView(
        **data,
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
    if auth_enabled() and legacy and (user.email or "").lower() == legacy:
        adopted = jobs().adopt(user.uid)
        if adopted:
            logging.getLogger("vfxglow.api").info("%s adoptó %d trabajos sin dueño", user.email, adopted)


def _job(job_id: str, user: User) -> Job:
    """El trabajo, solo si es de `user`. El de otro da 404 (no se revela que existe)."""
    job = jobs().get(job_id)
    if job is None or not owns(job, user.uid):
        raise HTTPException(404, "Trabajo no encontrado")
    return job


def _media_job(job_id: str, key: str | None) -> Job:
    """El trabajo de un archivo pedido con la llave corta (?k=)."""
    job = jobs().get(job_id)
    if job is None:
        raise HTTPException(404, "Trabajo no encontrado")
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


@app.get("/api/me", response_model=User)
def me(user: User = Depends(current_user)) -> User:
    return user


@app.post("/api/jobs", response_model=JobView, status_code=201)
def create_job(
    video: UploadFile = File(...),
    style_kind: str = Form("catalog"),
    style: str = Form(...),
    seed: int | None = Form(None),
    season: str | None = Form(None),
    wardrobe: str | None = Form(None),
    deep: bool = Form(False),
    fire_style: str | None = Form(None),
    bolt_style: str | None = Form(None),
    user: User = Depends(current_user),
) -> JobView:
    if Path(video.filename or "").suffix.lower() not in VIDEO_TYPES:
        raise HTTPException(415, f"Formato no soportado. Usa {', '.join(sorted(VIDEO_TYPES))}")
    if video.size is not None and video.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"El video supera {MAX_UPLOAD_MB} MB")
    style = _check_style(style_kind, style)
    _check_season(season or None)
    _check_looks(fire_style or None, bolt_style or None)
    wear = _check_wardrobe(json.loads(wardrobe) if wardrobe and wardrobe.strip().startswith("{") else ({"*": wardrobe} if wardrobe else {}))
    return view(jobs().create(video.filename or "video.mp4", video.file, style_kind, style, seed, season or None, owner=user.uid, wardrobe=wear, deep=deep, fire_style=fire_style or None, bolt_style=bolt_style or None))


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
    return view(jobs().variation(_job(job_id, user), body.style_kind, style, body.seed, body.season, wear, body.deep, body.fire_style, body.bolt_style))


@app.get("/api/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str, user: User = Depends(current_user)) -> JobView:
    return view(_job(job_id, user))


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, user: User = Depends(current_user)) -> Response:
    _job(job_id, user)
    if not jobs().delete(job_id):
        raise HTTPException(404, "Trabajo no encontrado")
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    host = os.environ.get("VFXGLOW_HOST", "127.0.0.1")
    check_bind(host)
    uvicorn.run(app, host=host, port=int(os.environ.get("VFXGLOW_PORT", "8000")), log_level="info")


if __name__ == "__main__":
    main()
