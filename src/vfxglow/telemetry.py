"""Trazabilidad: eventos JSON de una línea (docs/analisis_mejoras_y_seguridad.md, §7).

Cada evento dice qué pasó, cuándo (UTC con milisegundos), en qué servicio y bajo qué trabajo y
traza. Los nombres siguen OpenTelemetry y los atributos reservados de Datadog, así que Grafana
(Loki, Prometheus) y después Datadog leen las mismas líneas sin cambiar el código.

- `event(nombre, **campos)`: un evento suelto (`job.created`, `security.quota_exceeded`...).
- `span(etapa)`: `stage.started` al entrar y `stage.finished` al salir, con `duration_ms`, tiempo de
  CPU y resultado. `annotate(cache_hit=True)` añade campos al tramo en curso.
- `llm_call(...)`: una llamada a un modelo, con tokens y costo estimado (configs/llm_prices.yaml).
- `job_context(...)`: lo que pasa dentro de un trabajo hereda `job_id` y `trace_id`, y sus tramos y
  llamadas se suman en un resumen (`metrics`) que el trabajo guarda. `on_change` avisa cada vez que
  una etapa empieza o termina (la web muestra el avance por etapa en vivo) y `cancel` deja pedir
  que el trabajo pare: `checkpoint()` lo comprueba donde el proceso ya informa su avance.

Nunca se registran correos, tokens, llaves `?k=`, claves de API ni prompts: el usuario va como
hash de su uid (`user_ref`).

Formato de la consola con VEXORA_LOG_FORMAT (`json` o `text`); el archivo
`<VEXORA_LOG_DIR>/events.jsonl` siempre es JSON y rota a los 20 MB.
"""

from __future__ import annotations

import contextvars
import datetime
import hashlib
import json
import logging
import logging.handlers
import os
import re
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from vfxglow import __version__

FORMAT_ENV = "VEXORA_LOG_FORMAT"
DIR_ENV = "VEXORA_LOG_DIR"
ENV_ENV = "VEXORA_ENV"
PRICES_ENV = "VEXORA_LLM_PRICES"

# No empieza por "vfxglow": el lector de progreso de la API (api/jobs.py) no debe verlos.
events_log = logging.getLogger("vexora.events")

_service = "vexora"
_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("vexora_context", default=None)
_metrics: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("vexora_metrics", default=None)
_spans: contextvars.ContextVar[tuple[dict[str, Any], ...]] = contextvars.ContextVar("vexora_spans", default=())
_on_change: contextvars.ContextVar[Callable[[str, str, dict[str, Any]], None] | None] = contextvars.ContextVar("vexora_on_change", default=None)


class StopSignal(Protocol):
    """Lo que dice si hay que parar: un threading.Event o algo que también mire el almacén
    (api/workqueue.py, StopFlag: la cancelación puede llegar desde otro proceso)."""

    def is_set(self) -> bool: ...


_cancel: contextvars.ContextVar[StopSignal | None] = contextvars.ContextVar("vexora_cancel", default=None)


class Cancelled(Exception):
    """La persona pidió parar el trabajo: el proceso lo corta en el siguiente punto de control."""


def checkpoint() -> None:
    """Punto de control: levanta Cancelled si se pidió parar este trabajo. Sin trabajo, no hace nada."""
    event = _cancel.get()
    if event is not None and event.is_set():
        raise Cancelled()

_KEY = re.compile(r"([?&]k=)[^&\s]+")
_PATH = re.compile(r"/(?:[^/\s:]+/)+")


def new_trace_id() -> str:
    return uuid.uuid4().hex


def user_ref(uid: str | None) -> str | None:
    """El usuario sin datos personales: un hash corto y estable de su uid."""
    if not uid:
        return None
    return "sha256:" + hashlib.sha256(uid.encode()).hexdigest()[:16]


def redact(text: str) -> str:
    """Sin llaves de archivos (`?k=`) ni rutas absolutas del servidor (queda el nombre)."""
    return _PATH.sub("", _KEY.sub(r"\1***", text))


# ----- contexto -----


def bind(**fields: Any) -> contextvars.Token:
    return _context.set({**(_context.get() or {}), **{k: v for k, v in fields.items() if v is not None}})


def unbind(token: contextvars.Token) -> None:
    _context.reset(token)


@contextmanager
def job_context(
    job_id: str,
    trace_id: str,
    on_change: Callable[[str, str, dict[str, Any]], None] | None = None,
    cancel: StopSignal | None = None,
    **fields: Any,
) -> Iterator[dict[str, Any]]:
    """Lo que ocurra dentro lleva el trabajo y su traza; devuelve el resumen que se va llenando.

    `on_change(kind, stage, summary)` se llama al empezar ("started") y al terminar ("finished")
    cada etapa; `summary["current"]` es la etapa en curso y `summary["current_started"]`, desde cuándo."""
    summary: dict[str, Any] = {"stages": {}, "llm": {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd_est": None}}
    context = bind(job_id=job_id, trace_id=trace_id, **fields)
    metrics = _metrics.set(summary)
    hook = _on_change.set(on_change)
    stop = _cancel.set(cancel)
    try:
        yield summary
    finally:
        _cancel.reset(stop)
        _on_change.reset(hook)
        _metrics.reset(metrics)
        unbind(context)


# ----- eventos -----


def event(name: str, level: int = logging.INFO, **fields: Any) -> None:
    events_log.log(level, name, extra={"vexora": {"event": name, **{k: v for k, v in fields.items() if v is not None}}})


def annotate(**fields: Any) -> None:
    """Campos extra para el tramo en curso (p. ej. `cache_hit=True`)."""
    stack = _spans.get()
    if stack:
        stack[-1].update(fields)


def current_span() -> dict[str, Any]:
    """Los campos del tramo en curso (vacío fuera de un tramo)."""
    stack = _spans.get()
    return stack[-1] if stack else {}


@contextmanager
def span(stage: str, **fields: Any) -> Iterator[None]:
    span_id = uuid.uuid4().hex[:16]
    parent = _spans.get()[-1]["span_id"] if _spans.get() else None
    attributes: dict[str, Any] = {"stage": stage, "span_id": span_id, "parent_span_id": parent, **fields}
    parent_stage = _spans.get()[-1]["stage"] if _spans.get() else None
    stack = _spans.set(_spans.get() + (attributes,))
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    event("stage.started", **attributes)
    _notify("started", stage, current=stage, current_started=time.time())
    outcome, error = "ok", None
    try:
        yield
    except BaseException as exc:
        outcome, error = "error", type(exc).__name__
        summary = _metrics.get()
        if summary is not None and "failed_stage" not in summary:
            summary["failed_stage"] = stage
        raise
    finally:
        duration = round((time.perf_counter() - started_wall) * 1000)
        cpu = round((time.process_time() - started_cpu) * 1000)
        _spans.reset(stack)
        event(
            "stage.finished",
            level=logging.INFO if outcome == "ok" else logging.WARNING,
            duration_ms=duration,
            cpu_ms=cpu,
            outcome=outcome,
            error={"kind": error} if error else None,
            **attributes,
        )
        summary = _metrics.get()
        if summary is not None:
            stages = summary["stages"]
            stages[stage] = stages.get(stage, 0) + duration
            if attributes.get("cache_hit"):
                summary.setdefault("cache_hits", []).append(stage)
        _notify("finished", stage, current=parent_stage, current_started=time.time() if parent_stage else None)


def _notify(kind: str, stage: str, **summary_fields: Any) -> None:
    """Pone la etapa en curso en el resumen del trabajo y avisa a quien lo sigue (la API)."""
    summary = _metrics.get()
    if summary is None:
        return
    summary.update(summary_fields)
    if kind == "started":
        # Cuándo empezó cada etapa: con eso se sabe cuánto duró una que aún no cerró (la que
        # contiene a otra) en cuanto empieza la siguiente.
        summary.setdefault("started_at", {})[stage] = time.time()
    hook = _on_change.get()
    if hook is not None:
        hook(kind, stage, summary)


# ----- llamadas a modelos -----


@lru_cache(maxsize=1)
def _prices() -> dict[str, dict[str, Any]]:
    """Tarifas por modelo (USD por millón de tokens) y su nivel. Un precio vacío = sin costo
    estimado: se mide, no se inventa."""
    path = Path(os.environ.get(PRICES_ENV) or Path.cwd() / "configs" / "llm_prices.yaml")
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw.get("models") or {}


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float | None:
    price = _prices().get(model) or {}
    per_in, per_out = price.get("input_per_mtok"), price.get("output_per_mtok")
    if per_in is None or per_out is None:
        return None
    return round((tokens_in * float(per_in) + tokens_out * float(per_out)) / 1_000_000, 6)


def llm_call(provider: str, model: str, purpose: str, tokens_in: int | None, tokens_out: int | None, duration_ms: int | None = None, cache_hit: bool = False, **fields: Any) -> None:
    tokens_in, tokens_out = int(tokens_in or 0), int(tokens_out or 0)
    cost = None if cache_hit else estimate_cost(model, tokens_in, tokens_out)
    event(
        "llm.call",
        provider=provider,
        model=model,
        tier=(_prices().get(model) or {}).get("tier"),
        purpose=purpose,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_ms=duration_ms,
        cache_hit=cache_hit,
        cost_usd_est=cost,
        **fields,
    )
    summary = _metrics.get()
    if summary is None or cache_hit:
        return
    llm = summary["llm"]
    llm["calls"] += 1
    llm["tokens_in"] += tokens_in
    llm["tokens_out"] += tokens_out
    if cost is not None:
        llm["cost_usd_est"] = round((llm["cost_usd_est"] or 0.0) + cost, 6)


# ----- salida -----


class JsonFormatter(logging.Formatter):
    """Una línea JSON por registro: los eventos con sus campos y los mensajes del pipeline como
    `message`, todos con el contexto del trabajo en curso."""

    def format(self, record: logging.LogRecord) -> str:
        stamp = datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc)
        data: dict[str, Any] = {
            "timestamp": stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "service": _service,
            "env": os.environ.get(ENV_ENV, "dev"),
            "version": __version__,
            "logger": record.name,
        }
        data.update(_context.get() or {})
        fields = getattr(record, "vexora", None)
        if fields:
            data.update(fields)
        else:
            data["event"] = "log"
            data["message"] = redact(record.getMessage())
        if record.exc_info and record.exc_info[0] is not None:
            data["error"] = {"kind": record.exc_info[0].__name__, "message": redact(str(record.exc_info[1]))[:500]}
        return json.dumps(data, ensure_ascii=False, default=str)


def setup(service: str, log_dir: Path | None = None, console: str | None = None, text_format: str = "%(levelname)s %(name)s %(message)s") -> None:
    """Prepara la consola (JSON o texto) y el archivo de eventos JSON. Idempotente."""
    global _service
    _service = service
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        if getattr(handler, "_vexora", False):
            root.removeHandler(handler)
    style = (console or os.environ.get(FORMAT_ENV, "json")).strip().lower()
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(JsonFormatter() if style == "json" else logging.Formatter(text_format))
    if style != "json":
        stream.addFilter(lambda record: record.name != events_log.name)
    folder = Path(os.environ.get(DIR_ENV) or log_dir or Path.cwd() / "logs")
    folder.mkdir(parents=True, exist_ok=True)
    file = logging.handlers.RotatingFileHandler(folder / "events.jsonl", maxBytes=20 * 1024 * 1024, backupCount=10, encoding="utf-8")
    file.setFormatter(JsonFormatter())
    for handler in (stream, file):
        handler._vexora = True  # type: ignore[attr-defined]
        root.addHandler(handler)
