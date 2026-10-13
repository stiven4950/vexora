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
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vfxglow.api.jobs import Job, JobStore

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


def _check_season(season: str | None) -> None:
    from vfxglow.director.seasons import find, load_seasons

    if season and find(load_seasons(ROOT / "configs" / "seasons.yaml"), season) is None:
        raise HTTPException(422, f"Temporada desconocida: {season}")


# ----- trabajos -----


class JobView(Job):
    duration: float | None = None
    output_url: str | None = None
    original_url: str | None = None
    thumbnail_url: str | None = None


def view(job: Job) -> JobView:
    data = job.model_dump()
    data["log"] = job.log[-20:]
    done = job.status == "done" and job.output
    return JobView(
        **data,
        duration=(job.finished or 0) - job.started if job.started and job.finished else None,
        output_url=f"/api/jobs/{job.id}/output" if done else None,
        original_url=f"/api/jobs/{job.id}/original",
        thumbnail_url=f"/api/jobs/{job.id}/thumbnail",
    )


def _job(job_id: str) -> Job:
    job = jobs().get(job_id)
    if job is None:
        raise HTTPException(404, "Trabajo no encontrado")
    return job


def _check_style(kind: str, name: str) -> None:
    folder = "catalogs" if kind == "catalog" else "presets"
    if kind not in ("catalog", "preset") or not (ROOT / "configs" / folder / f"{name}.yaml").exists():
        raise HTTPException(422, f"Estilo desconocido: {kind}/{name}")


@app.get("/api/jobs", response_model=list[JobView])
def list_jobs() -> list[JobView]:
    return [view(job) for job in jobs().list()]


@app.post("/api/jobs", response_model=JobView, status_code=201)
def create_job(
    video: UploadFile = File(...),
    style_kind: str = Form("catalog"),
    style: str = Form(...),
    seed: int | None = Form(None),
    season: str | None = Form(None),
) -> JobView:
    if Path(video.filename or "").suffix.lower() not in VIDEO_TYPES:
        raise HTTPException(415, f"Formato no soportado. Usa {', '.join(sorted(VIDEO_TYPES))}")
    if video.size is not None and video.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"El video supera {MAX_UPLOAD_MB} MB")
    _check_style(style_kind, style)
    _check_season(season or None)
    return view(jobs().create(video.filename or "video.mp4", video.file, style_kind, style, seed, season or None))


class VariationRequest(BaseModel):
    style_kind: str = "catalog"
    style: str
    seed: int | None = None
    season: str | None = None


@app.post("/api/jobs/{job_id}/variations", response_model=JobView, status_code=201)
def create_variation(job_id: str, body: VariationRequest) -> JobView:
    _check_style(body.style_kind, body.style)
    _check_season(body.season)
    return view(jobs().variation(_job(job_id), body.style_kind, body.style, body.seed, body.season))


@app.get("/api/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str) -> JobView:
    return view(_job(job_id))


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> Response:
    if not jobs().delete(job_id):
        raise HTTPException(404, "Trabajo no encontrado")
    return Response(status_code=204)


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    """Server-Sent Events: el estado del trabajo cada vez que cambia, hasta que termina."""
    _job(job_id)

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
def job_output(job_id: str, download: bool = False) -> FileResponse:
    job = _job(job_id)
    if not job.output or not Path(job.output).exists():
        raise HTTPException(404, "El video editado aún no existe")
    name = f"{Path(job.filename).stem}-{job.style}{'-' + str(job.seed) if job.seed is not None else ''}.mp4"
    return FileResponse(job.output, media_type="video/mp4", filename=name if download else None)


@app.get("/api/jobs/{job_id}/original")
def job_original(job_id: str) -> FileResponse:
    return FileResponse(_job(job_id).video_path, media_type="video/mp4")


@app.get("/api/jobs/{job_id}/thumbnail")
def job_thumbnail(job_id: str, original: bool = False, first: bool = False) -> Response:
    """Fotograma del editado (o del original con ?original=true): a un tercio del video, o el
    primero con ?first=true (póster del comparador: coincide con el inicio de la reproducción)."""
    job = _job(job_id)
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


@app.get("/api/jobs/{job_id}/choreography", response_model=list[Moment])
def job_choreography(job_id: str) -> list[Moment]:
    """Qué reacción salió en cada acción (solo estilos de catálogo); 'nada' se omite."""
    job = _job(job_id)
    if not job.run_dir:
        return []
    path = Path(job.run_dir) / "scripts" / f"{job.style}.choreography.json"
    if not path.exists():
        return []
    decisions = json.loads(path.read_text(encoding="utf-8")).get("decisions", [])
    return [Moment(**{k: d[k] for k in ("second", "action", "target", "choice")}) for d in decisions if not d["choice"].startswith("nada")]


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
    uvicorn.run(app, host=os.environ.get("VFXGLOW_HOST", "127.0.0.1"), port=int(os.environ.get("VFXGLOW_PORT", "8000")), log_level="info")


if __name__ == "__main__":
    main()
