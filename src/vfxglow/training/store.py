"""Etiquetas candidatas en disco, hojas de revisión y lista de rechazos.

training/data/labels/<tarea>/<fuente>/<clave>.jpg + labels.jsonl   (lo que salió automático)
training/review/<tarea>/<fuente>/sheet_NN.jpg                        (para mirar)
training/review/<tarea>/<fuente>/rejected.txt                        (claves malas, una por línea)
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from vfxglow.training.pairs import Labeled

SHEET_COLS = 6
SHEET_ROWS = 4
TILE_WIDTH = 300


def save(items: list[Labeled], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "labels.jsonl").open("w", encoding="utf-8") as out:
        for item in items:
            cv2.imwrite(str(folder / f"{item.key}.jpg"), item.image, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
            out.write(json.dumps({"key": item.key, "source": item.source, "frame": item.frame, "boxes": [b.tolist() for b in item.boxes]}) + "\n")


def load(folder: Path) -> list[dict]:
    path = folder / "labels.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def rejected(review: Path) -> set[str]:
    path = review / "rejected.txt"
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}


def write_sheets(labels: Path, review: Path) -> int:
    """Hojas de contacto numeradas: cada mosaico muestra su clave para copiarla a rejected.txt."""
    review.mkdir(parents=True, exist_ok=True)
    rows = load(labels)
    per = SHEET_COLS * SHEET_ROWS
    for old in review.glob("sheet_*.jpg"):
        old.unlink()
    for page in range(0, len(rows), per):
        tiles = []
        for row in rows[page : page + per]:
            image = cv2.imread(str(labels / f"{row['key']}.jpg"))
            for box in row["boxes"]:
                cv2.polylines(image, [np.array(box, dtype=np.int32)], True, (0, 255, 0), max(2, image.shape[1] // 200))
            scale = TILE_WIDTH / image.shape[1]
            tile = cv2.resize(image, (TILE_WIDTH, int(image.shape[0] * scale)))
            tile = cv2.copyMakeBorder(tile, 26, 0, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
            cv2.putText(tile, row["key"][-22:], (4, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            tiles.append(tile)
        height = max(t.shape[0] for t in tiles)
        tiles = [cv2.copyMakeBorder(t, 0, height - t.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0)) for t in tiles]
        tiles += [np.zeros_like(tiles[0])] * (per - len(tiles))
        sheet = np.vstack([np.hstack(tiles[r * SHEET_COLS : (r + 1) * SHEET_COLS]) for r in range(SHEET_ROWS)])
        cv2.imwrite(str(review / f"sheet_{page // per:02d}.jpg"), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    reject = review / "rejected.txt"
    if not reject.exists():
        reject.write_text("# Una clave por línea (la que aparece arriba de cada mosaico) para excluirla del entrenamiento.\n", encoding="utf-8")
    return (len(rows) + per - 1) // per
