"""Análisis profundo: la respuesta del modelo se vuelve un guion revisado (sin llamar a la red)."""

from __future__ import annotations

import json
from pathlib import Path

from vfxglow.analysis.schema import MotionBrief, VideoMeta
from vfxglow.config import DirectorConfig
from vfxglow.director.choreography import choreograph, load_catalog, pin_chapters
from vfxglow.director.deep import build_prompt, record_proposals, to_pins
from vfxglow.director.pins import Capitulo, Pin, PinFile, chapter_plan, hex_color, load_pins, save_pins

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
    # Mixto por defecto: el coreógrafo económico rellena alrededor de lo fijado.
    assert not pins.solo_estos and all(pin.exacto for pin in pins.momentos)
    assert to_pins(answer, CATALOG, 32.4, fill=False)[0].solo_estos
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
    assert deep._generate(DeepConfig(provider="gemini"), "k", {}, sleep=waits.append) == {"ok": True}
    assert waits == [5, 10]

    calls.clear()
    monkeypatch.setattr(deep, "_request", lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"bad"))))
    import pytest

    with pytest.raises(RuntimeError, match="400"):
        deep._generate(DeepConfig(provider="gemini"), "k", {}, sleep=waits.append)


def test_busy_model_falls_back_after_retries(monkeypatch) -> None:
    import io
    import urllib.error

    import pytest

    from vfxglow.config import DeepConfig
    from vfxglow.director import deep

    models = []

    def fake(url, key, data=None, headers=None, method=None, timeout=120.0):
        models.append(url.split("/models/")[1].split(":")[0] if "/models/" in url else url)
        if "argon" in url:
            raise urllib.error.HTTPError(url, 503, "busy", {}, io.BytesIO(b"high demand"))
        raise AssertionError("no debe llegar aquí")

    monkeypatch.setattr(deep, "_request", fake)
    cfg = DeepConfig(provider="gemini", model="gemini-4-argon", retries=3)
    with pytest.raises(deep.Saturated):
        deep._generate(cfg, "k", {}, sleep=lambda s: None)
    assert models == ["gemini-4-argon"] * 4  # 1 intento + 3 reintentos, y luego el respaldo lo decide ask_gemini
    assert cfg.fallback_model == "gemini-3.8-flash"


def test_prompt_lists_figures_not_style_flags() -> None:
    prompt = build_prompt(CATALOG, 30.0)
    assert "burbuja [bubble]" in prompt and "cohete [rocket]" in prompt
    assert "no_outline" not in prompt and "lines_only" not in prompt
    assert "nunca\n  la misma dos veces" in prompt


def test_who_maps_left_right_and_both() -> None:
    from vfxglow.analysis.schema import FrameRecord, PersonPose
    from vfxglow.director.deep import sides_from_tracks

    frames = [
        FrameRecord(frame=i, time_s=i / 25.0, people=[
            PersonPose(person_id="person_0", box=(0.6, 0.1, 0.9, 0.9)),
            PersonPose(person_id="person_1", box=(0.1, 0.1, 0.4, 0.9)),
        ])
        for i in range(50)
    ]
    who = sides_from_tracks(frames, 25.0)
    assert who(1.0, "izquierda") == ("person_1", False)
    assert who(1.0, "derecha") == ("person_0", False)
    assert who(1.0, "ambos") == ("person_1", True)
    assert who(1.0, "protagonista") == (None, False)
    answer = {"momentos": [{"seg": 1.0, "accion": "point", "opcion": "munequito", "quien": "derecha"},
                           {"seg": 1.5, "accion": "spin_body", "opcion": "arcos", "quien": "ambos"}]}
    pins, _ = to_pins(answer, CATALOG, 2.0, who=who)
    assert (pins.momentos[0].persona, pins.momentos[0].espejo) == ("person_0", None)
    assert (pins.momentos[1].persona, pins.momentos[1].espejo) == ("person_1", True)


def _brief_with(events, seconds: float = 20.0, people=("person_0",), onsets=()):
    from vfxglow.analysis.schema import MotionEvent

    meta = VideoMeta(path="x", fps=25.0, width=400, height=600, frame_count=int(seconds * 25), duration_s=seconds)
    evs = [MotionEvent(name=n, target="person_0", start_frame=f, end_frame=f + 5, confidence=1.0) for n, f in events]
    return MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=evs, summary="", people=list(people), audio_onsets=list(onsets))


def test_fps_follows_how_fast_the_dance_is() -> None:
    from vfxglow.config import DeepConfig
    from vfxglow.director.deep import choose_fps

    calm = _brief_with([("step", f) for f in range(0, 500, 25)])  # 1 gesto rápido por segundo
    busy = _brief_with([("fast_swing", f) for f in range(0, 500, 6)])  # ~4 por segundo
    wild = _brief_with([("impact", f) for f in range(0, 500, 3)])  # ~8 por segundo
    assert choose_fps(calm, DeepConfig()) == 5.0
    assert choose_fps(busy, DeepConfig()) == 8.0
    assert choose_fps(wild, DeepConfig()) == 10.0
    # Un video largo no pasa del presupuesto de fotogramas (el costo).
    long_wild = _brief_with([("impact", f) for f in range(0, 2500, 3)], seconds=100.0)
    assert choose_fps(long_wild, DeepConfig()) == 4.5
    assert choose_fps(calm, DeepConfig(fps=12.0)) == 12.0


def test_moments_snap_to_the_detected_gesture_or_beat() -> None:
    from vfxglow.director.deep import snapper

    snap = snapper(_brief_with([("point", 105)], onsets=[202]))  # gesto en 4,2 s; golpe en 8,08 s
    assert snap(4.0, "point") == 4.2
    assert snap(4.0, "lunge") == 4.0  # otra acción y sin golpe cerca: se queda
    assert snap(8.0, "spotlight") == 8.08
    assert snap(5.0, "point") == 5.0  # el gesto está a 0,8 s: demasiado lejos


def test_point_becomes_the_detected_finger_gun() -> None:
    from vfxglow.director.deep import upgrader

    brief = _brief_with([("finger_gun", 105)])  # 4,2 s; termina en 4,4 s
    answer = {"momentos": [{"seg": 4.0, "dur": 1.0, "accion": "point", "opcion": "munequito"},
                           {"seg": 9.0, "dur": 1.0, "accion": "point", "opcion": "munequito"}]}
    pins, warnings = to_pins(answer, CATALOG, 20.0, upgrade=upgrader(brief))
    gun, plain = pins.momentos
    assert (gun.accion, gun.opcion, gun.exacto) == ("finger_gun", "revolver", False)
    assert (plain.accion, plain.opcion, plain.exacto) == ("point", "munequito", True)
    assert any("revolver" in w for w in warnings)


def test_voice_chapters_become_pins_and_skip_malformed() -> None:
    answer = {
        "capitulos": [
            {"inicio": 2.5, "fin": 5.0, "elemento": " Tierra ", "voz": "tierra"},
            {"inicio": 0.0, "fin": 2.5, "elemento": "AGUA", "voz": "agua"},
            {"inicio": 6.0, "fin": 5.0, "elemento": "fuego"},
            {"inicio": "x", "fin": 7.0, "elemento": "aire"},
        ]
    }
    pins, warnings = to_pins(answer, CATALOG, 32.4)
    assert [(c.inicio, c.elemento) for c in pins.capitulos] == [(0.0, "agua"), (2.5, "tierra")]
    assert len(warnings) == 2


def test_chapter_plan_frames() -> None:
    pins = PinFile(capitulos=[Capitulo(inicio=2.5, fin=5.0, elemento="tierra"), Capitulo(inicio=0.0, fin=2.5, elemento="agua")])
    assert chapter_plan(pins, 30) == [(0, 75, "agua"), (75, 150, "tierra")]
    assert chapter_plan(PinFile(), 30) == []


def test_chapters_round_trip_yaml(tmp_path: Path) -> None:
    pins = PinFile(capitulos=[Capitulo(inicio=0.0, fin=2.5, elemento="agua", voz="agua")])
    save_pins(pins, tmp_path / "g.yaml")
    assert load_pins(tmp_path / "g.yaml").capitulos == pins.capitulos


def test_prompt_asks_for_voice_chapters() -> None:
    avatar = load_catalog(ROOT / "configs" / "catalogs" / "avatar.yaml")
    prompt = build_prompt(avatar, 10.0)
    assert "capitulos" in prompt and "nombra un elemento" in prompt


def test_alternatives_keep_only_same_action_options() -> None:
    answer = {
        "momentos": [
            {
                "seg": 6.0, "accion": "hands_on_head", "opcion": "ovni",
                "alternativas": [
                    {"opcion": "diablo", "encaje": 7},  # válida, encaje al tope
                    {"opcion": "senal", "encaje": 0.8},  # de otra acción
                    {"opcion": "no_existe", "encaje": 0.8},
                    {"opcion": "ovni", "encaje": 0.9},  # la principal
                    {"opcion": "diablo", "encaje": 0.4},  # repetida
                    "basura",
                ],
            },
            {"seg": 9.0, "accion": "hands_on_head", "opcion": "ovni", "alternativas": [{"opcion": "aro_manos", "encaje": -2}]},
        ]
    }
    pins, warnings = to_pins(answer, CATALOG, 32.4)
    first, second = pins.momentos
    assert [(a.opcion, a.encaje) for a in first.alternativas] == [("diablo", 1.0)]
    assert [(a.opcion, a.encaje) for a in second.alternativas] == [("aro_manos", 0.05)]
    assert any("senal" in w for w in warnings) and any("no_existe" in w for w in warnings) and any("mal formada" in w for w in warnings)


def test_pins_without_alternatives_save_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "g.yaml"
    save_pins(PinFile(momentos=[Pin(seg=1.0, opcion="ovni")]), path)
    assert "alternativas" not in path.read_text(encoding="utf-8")


def test_alternatives_keep_the_main_element() -> None:
    from vfxglow.director.choreography import load_catalog
    from vfxglow.director.deep import _alternatives

    catalog = load_catalog(ROOT / "configs" / "catalogs" / "avatar.yaml")
    warnings: list[str] = []
    alts = _alternatives([{"opcion": "viento", "encaje": 0.4}, {"opcion": "puno_tierra", "encaje": 0.6}, {"opcion": "estela", "encaje": 0.9}], catalog, "fast_swing", "latigo_agua", 0.8, warnings)
    assert alts == []  # viento (aire), puño (tierra) y estela (fuego): ninguno es agua
    assert len(warnings) == 3


def test_meta_is_default_and_gemini_stays_as_option() -> None:
    from vfxglow.config import DeepConfig

    meta = DeepConfig()
    assert (meta.provider, meta.model, meta.fallback_model, meta.api_key_env) == ("meta", "muse-spark-1.3", "muse-spark-1.2", "META_API_KEY")
    gemini = DeepConfig(provider="gemini")
    assert (gemini.model, gemini.fallback_model, gemini.api_key_env) == ("gemini-4-argon", "gemini-3.8-flash", "GEMINI_API_KEY")
    assert DeepConfig(fallback_model=None).fallback_model is None


def test_lyrics_go_into_the_prompt_with_their_times() -> None:
    from vfxglow.director.deep import lyrics_text

    text = lyrics_text([{"start": 0.78, "end": 13.66, "texto": "it's a UFO"}])
    assert "[0.8-13.7 s] it's a UFO" in text
    assert "sin audio" in text
    assert "no trae voz" in lyrics_text([])


def test_failed_transcription_keeps_going_without_lyrics(monkeypatch, tmp_path) -> None:
    import urllib.error

    from vfxglow.config import DeepConfig
    from vfxglow.director import deep

    monkeypatch.setattr(deep, "transcribe", lambda video, key: (_ for _ in ()).throw(urllib.error.URLError("sin red")))
    assert deep._lyrics(tmp_path / "v.mp4", "a" * 64, DeepConfig(), tmp_path) == []
    assert not list(tmp_path.glob("letra_*.json"))  # el fallo no se guarda: la próxima vez se reintenta


def test_busy_muse_spark_falls_back(monkeypatch, tmp_path) -> None:
    import io
    import urllib.error

    from vfxglow.config import DeepConfig
    from vfxglow.director import deep

    asked = []

    class Done(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake(url, key, data, content_type, timeout):
        model = json.loads(data)["model"]
        asked.append(model)
        if model == "muse-spark-1.3":
            raise urllib.error.HTTPError(url, 503, "busy", {}, io.BytesIO(b"busy"))
        return Done(json.dumps({"choices": [{"message": {"content": '{"momentos": []}'}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}).encode())

    monkeypatch.setenv("META_API_KEY", "k")
    monkeypatch.setattr(deep, "_meta_request", fake)
    monkeypatch.setattr(deep, "_small_video", lambda video, fps, out: out.write_bytes(b"mp4") and out)
    monkeypatch.setattr(deep, "RETRY_WAITS_S", ())
    answer, usage, model = deep.ask_meta(tmp_path / "v.mp4", "prompt", DeepConfig(fps=5.0))
    assert answer == {"momentos": []}
    assert model == "muse-spark-1.2"
    assert asked == ["muse-spark-1.3", "muse-spark-1.2"]
    assert usage == {"promptTokenCount": 7, "candidatesTokenCount": 3}
