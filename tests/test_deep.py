"""Análisis profundo: la respuesta del modelo se vuelve un guion revisado (sin llamar a la red)."""

from __future__ import annotations

import json
from pathlib import Path

from vfxglow.analysis.schema import MotionBrief, VideoMeta
from vfxglow.config import DirectorConfig
from vfxglow.director.choreography import choreograph, load_catalog, pin_chapters
from vfxglow.director.deep import build_prompt, record_proposals, to_pins
from vfxglow.director.pins import Pin, PinFile, hex_color

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "configs" / "catalogs" / "baile.yaml")


def test_off_by_default() -> None:
    assert DirectorConfig().deep.enabled is False


def test_prompt_lists_the_real_catalog() -> None:
    prompt = build_prompt(CATALOG, 32.4)
    assert "32.4 s" in prompt
    assert "munequito [stick_man]" in prompt
    assert "planeador [glider]" in prompt
    assert "- point (señala con el brazo extendido):" in prompt


def test_answer_becomes_checked_pins() -> None:
    answer = {
        "momentos": [
            {"seg": 6.0, "dur": 1.6, "accion": "hands_on_head", "opcion": "ovni", "color": "#39ff14", "intencion": "la letra dice UFO"},
            # La opción existe, pero en otra acción: se corrige la acción.
            {"seg": 4.1, "dur": 1.1, "accion": "spotlight", "opcion": "munequito"},
            # Un efecto nuevo llega con su sustituto del catálogo.
            {"seg": 8.9, "dur": 1.2, "accion": "spotlight", "opcion": "chispa", "nuevo": "trampa_chispa", "intencion": "atrapa algo"},
            {"seg": 12.0, "accion": "spotlight", "opcion": "NUEVO_algo"},
            {"seg": 99.0, "accion": "point", "opcion": "munequito"},
            {"seg": 20.0, "dur": 9.0, "accion": "spotlight", "opcion": "cabeza_accesorio", "figura": "crown", "color": "verde"},
        ]
    }
    pins, warnings = to_pins(answer, CATALOG, 32.4)
    by_seg = {pin.seg: pin for pin in pins.momentos}
    assert sorted(by_seg) == [4.1, 6.0, 8.9, 20.0]
    assert pins.solo_estos and all(pin.exacto for pin in pins.momentos)
    assert by_seg[6.0].color == "#39ff14" and by_seg[6.0].nota == "la letra dice UFO"
    assert by_seg[4.1].accion == "point"
    assert by_seg[8.9].nota.startswith("[nuevo: trampa_chispa]")
    assert by_seg[20.0].figura == "crown" and by_seg[20.0].color is None and by_seg[20.0].dur == 4.0
    assert any("NUEVO_algo" in w for w in warnings) and any("fuera del video" in w for w in warnings)


def test_colors_by_moment_become_chapters() -> None:
    pins = PinFile(momentos=[Pin(seg=0.0, opcion="x", color="#ff0000"), Pin(seg=1.0, opcion="y"), Pin(seg=2.0, opcion="z", color="#0000ff")])
    chapters = pin_chapters(pins, 30.0, 120)
    assert [(c.start_frame, c.end_frame) for c in chapters] == [(0, 59), (60, 119)]
    assert chapters[0].colors[0] == hex_color("#ff0000") and chapters[1].colors[0] == (0.0, 0.0, 1.0)


def test_pinned_colors_reach_the_script() -> None:
    meta = VideoMeta(path="x", fps=30.0, width=400, height=600, frame_count=120, duration_s=4.0)
    brief = MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=[], summary="", people=["person_0"])
    pins = PinFile(solo_estos=True, momentos=[
        Pin(seg=0.5, accion="point", opcion="munequito", exacto=True, dur=1.0, color="#39ff14", nota="camina por el brazo"),
    ])
    script, choreography = choreograph(CATALOG, brief, 1, pins)
    assert script.chapters and script.chapters[0].colors[0] == hex_color("#39ff14")
    assert any(d.note == "camina por el brazo" for d in choreography.decisions)


def test_new_effects_are_recorded_once(tmp_path: Path) -> None:
    lectura = tmp_path / "deep_lectura.json"
    lectura.write_text(json.dumps({"efectos_nuevos": [{"nombre": "soga", "porque": "jala"}, {"sin": "nombre"}]}), encoding="utf-8")
    ledger = tmp_path / "efectos_propuestos.jsonl"
    assert record_proposals(lectura, ledger, "video_35.mp4") == 1
    assert record_proposals(lectura, ledger, "video_35.mp4") == 0
    line = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert line["nombre"] == "soga" and line["video"] == "video_35.mp4"


def test_busy_model_is_retried(monkeypatch) -> None:
    import io
    import urllib.error

    from vfxglow.config import DeepConfig
    from vfxglow.director import deep

    calls = []

    class Done(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake(url, key, data=None, headers=None, method=None, timeout=120.0):
        calls.append(url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(url, 503, "busy", {}, io.BytesIO(b'{"error": "high demand"}'))
        return Done(b'{"ok": true}')

    monkeypatch.setattr(deep, "_request", fake)
    waits = []
    assert deep._generate(DeepConfig(), "k", {}, sleep=waits.append) == {"ok": True}
    assert waits == [15, 45]

    calls.clear()
    monkeypatch.setattr(deep, "_request", lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"bad"))))
    import pytest

    with pytest.raises(RuntimeError, match="400"):
        deep._generate(DeepConfig(), "k", {}, sleep=waits.append)


def test_prompt_lists_figures_not_style_flags() -> None:
    prompt = build_prompt(CATALOG, 30.0)
    assert "burbuja [bubble]" in prompt and "cohete [rocket]" in prompt
    assert "no_outline" not in prompt and "lines_only" not in prompt
    assert "nunca\n  la misma dos veces" in prompt
