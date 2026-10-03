"""Dibuja glifos SVG anclados a la cabeza o a un punto de impacto.

La biblioteca vive en assets/glyphs. Un SVG compuesto por el LLM solo se
acepta si pasa el validador: path, circle y line, menos de 40 elementos.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from vfxglow.director.schema import Effect
from vfxglow.engine.raster import stroke_polyline

_ALLOWED = {"svg", "path", "circle", "line", "g"}
_TOKEN = re.compile(r"[MLCZmlcz]|-?\d*\.?\d+(?:e[-+]?\d+)?")


@dataclass
class Glyph:
    name: str
    tags: list[str]
    anchor: str
    scale: float
    viewbox: tuple[float, float, float, float]
    svg: str


def glyphs_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "assets" / "glyphs"
        if candidate.is_dir():
            return candidate
    return here.parents[3] / "assets" / "glyphs"


def validate_svg(text: str) -> bool:
    """SVG de un solo trazo. Rechaza scripts, imágenes y dibujos demasiado largos."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return False
    if _tag(root) != "svg":
        return False
    count = 0
    for element in root.iter():
        if _tag(element) not in _ALLOWED:
            return False
        count += 1
        if count >= 40:
            return False
    return True


def resolve_glyph(name: str) -> Glyph | None:
    if name.strip().startswith("<"):
        if not validate_svg(name):
            return None
        return Glyph("custom", [], "head", 0.8, (0, 0, 100, 100), name)
    found = _library().get(name)
    if found is not None:
        return found
    return _closest(name)


def draw_glyph(
    layer: np.ndarray,
    glyph: Glyph,
    origin: np.ndarray,
    shoulder: float,
    color: tuple[float, float, float],
    width: float,
    gain: float,
    jitter: np.ndarray | None = None,
) -> None:
    paths = _paths(glyph.svg)
    if not paths:
        return
    vb_w = max(glyph.viewbox[2], 1.0)
    scale = max(shoulder, 12.0) * glyph.scale / vb_w
    cx = glyph.viewbox[0] + glyph.viewbox[2] * 0.5
    cy = glyph.viewbox[1] + glyph.viewbox[3] * 0.5
    shift = np.array([0.0, -shoulder * 0.15]) if glyph.anchor == "overhead" else np.zeros(2)
    for path in paths:
        placed = (path - np.array([cx, cy])) * scale + origin + shift
        if jitter is not None and len(placed):
            placed = placed + jitter[: len(placed)]
        stroke_polyline(layer, placed, color, width, gain, alpha=0.95)


def _closest(name: str) -> Glyph | None:
    library = _library()
    if not library:
        return None
    needle = set(re.split(r"[^a-z0-9]+", name.lower()))
    best = None
    score = 0
    for glyph in library.values():
        overlap = len(needle & set(glyph.tags + [glyph.name]))
        if overlap > score:
            score = overlap
            best = glyph
    return best if score else next(iter(library.values()))


@lru_cache(maxsize=1)
def _library() -> dict[str, Glyph]:
    root = glyphs_dir()
    found: dict[str, Glyph] = {}
    if not root.is_dir():
        return found
    for meta_path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        svg_path = meta_path.with_suffix(".svg")
        if not svg_path.exists():
            continue
        svg = svg_path.read_text(encoding="utf-8")
        if not validate_svg(svg):
            continue
        box = tuple(float(v) for v in raw.get("viewbox", [0, 0, 100, 100]))
        glyph = Glyph(
            name=str(raw.get("id", meta_path.stem)),
            tags=[str(tag) for tag in raw.get("tags", [])],
            anchor=str(raw.get("anchor", "head")),
            scale=float(raw.get("scale", 0.7)),
            viewbox=(box[0], box[1], box[2], box[3]),  # type: ignore[index]
            svg=svg,
        )
        found[glyph.name] = glyph
    return found


def _paths(svg: str) -> list[np.ndarray]:
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return []
    paths: list[np.ndarray] = []
    for element in root.iter():
        tag = _tag(element)
        if tag == "path" and element.get("d"):
            parsed = _path_d(element.get("d", ""))
            if len(parsed) >= 2:
                paths.append(parsed)
        elif tag == "line":
            try:
                paths.append(
                    np.array(
                        [
                            [float(element.get("x1", 0)), float(element.get("y1", 0))],
                            [float(element.get("x2", 0)), float(element.get("y2", 0))],
                        ],
                        dtype=np.float64,
                    )
                )
            except ValueError:
                continue
        elif tag == "circle":
            try:
                cx, cy, r = float(element.get("cx", 0)), float(element.get("cy", 0)), float(element.get("r", 1))
            except ValueError:
                continue
            angles = np.linspace(0, np.pi * 2, 24, endpoint=False)
            paths.append(np.stack([cx + np.cos(angles) * r, cy + np.sin(angles) * r], axis=1))
    return paths


def _path_d(data: str) -> np.ndarray:
    tokens = _TOKEN.findall(data)
    points: list[tuple[float, float]] = []
    command = "M"
    index = 0
    cx = cy = 0.0
    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            if command in "Zz":
                if points:
                    points.append(points[0])
            continue
        if command in "MmLl" and index + 1 < len(tokens):
            x, y = float(tokens[index]), float(tokens[index + 1])
            index += 2
            if command.islower():
                x += cx
                y += cy
            points.append((x, y))
            cx, cy = x, y
            if command in "Mm":
                command = "l" if command == "m" else "L"
        elif command in "Cc" and index + 5 < len(tokens):
            nums = [float(tokens[index + offset]) for offset in range(6)]
            index += 6
            if command.islower():
                nums = [n + (cx if i % 2 == 0 else cy) for i, n in enumerate(nums)]
            start = np.array([cx, cy])
            c1 = np.array(nums[0:2])
            c2 = np.array(nums[2:4])
            end = np.array(nums[4:6])
            for step in range(1, 7):
                t = step / 6
                point = (1 - t) ** 3 * start + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t**2 * c2 + t**3 * end
                points.append((float(point[0]), float(point[1])))
            cx, cy = float(end[0]), float(end[1])
        else:
            index += 1
    if len(points) < 2:
        return np.zeros((0, 2))
    return np.asarray(points, dtype=np.float64)


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def boil_jitter(effect: Effect, frame_index: int, count: int, amount: float) -> np.ndarray:
    """Ruido nuevo cada N fotogramas: el trazo tiembla como un dibujo redibujado."""
    step = max(effect.style.boil_frames, 1)
    boiled = (frame_index // step) * step
    rng = np.random.default_rng((effect.style.seed_offset * 997 + boiled * 13) & 0xFFFFFFFF)
    if effect.style.boil_frames <= 1 or amount <= 0:
        return np.zeros((count, 2))
    return rng.normal(0.0, amount, size=(count, 2))
