"""Caché en disco, JSONL y huellas de etapa."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def stage_key(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


_PACKAGE = Path(__file__).resolve().parent.parent


def code_fingerprint(*parts: str, exclude: tuple[str, ...] = ()) -> str:
    """Huella del código fuente de los subpaquetes o módulos de vfxglow indicados.

    Cambiar la lógica de una etapa invalida su caché sin tener que subir a mano la etiqueta de la clave.
    `exclude`: módulos que no cuentan (rutas como "analysis/gestures.py").
    """
    digest = hashlib.sha256()
    skip = {(_PACKAGE / part).resolve() for part in exclude}
    for part in parts:
        target = _PACKAGE / part
        files = sorted(target.rglob("*.py")) if target.is_dir() else [target]
        for path in files:
            if path.resolve() in skip:
                continue
            digest.update(str(path.relative_to(_PACKAGE)).encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def write_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")


def read_model(path: Path, cls: type[T]) -> T:
    return cls.model_validate_json(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, rows: list[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def read_jsonl(path: Path, cls: type[T]) -> list[T]:
    rows: list[T] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(cls.model_validate_json(line))
    return rows


class Manifest(BaseModel):
    version: str = "1.0"
    video_path: str
    video_sha256: str
    device: str
    stages: dict[str, str] = {}
    # Entradas legibles de cada etapa (hash del guion, preset, huella del código, fotogramas escritos).
    inputs: dict[str, dict[str, str]] = {}


def load_manifest(path: Path) -> Manifest | None:
    if not path.exists():
        return None
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, manifest: Manifest) -> None:
    write_model(path, manifest)
