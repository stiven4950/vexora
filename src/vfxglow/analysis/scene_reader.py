"""Lee cada beat con un VLM remoto. Sin clave de API el brief sigue solo con cinemática.

El modelo por defecto es gpt-5-mini: pocos fotogramas y un JSON corto. La
respuesta se cachea por el hash de esos fotogramas.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2

from vfxglow import telemetry
from vfxglow.analysis.models_store import ssl_context
from vfxglow.analysis.schema import Beat, SceneBeat
from vfxglow.config import SceneConfig

log = logging.getLogger("vfxglow.scene")

_PROMPT = """Miras fotogramas de un solo beat de un video. Responde SOLO un JSON con estas claves:
{"scene": "pelea|maquillaje|baile|otro", "gesture": "frase corta del gesto", "intent": "frase corta de la intención", "objects": ["objeto"]}
No describas el fondo. No añadas texto fuera del JSON."""


def read_scenes(
    video_path: Path,
    beats: list[Beat],
    cache_dir: Path,
    cfg: SceneConfig | None = None,
) -> list[SceneBeat]:
    cfg = cfg or SceneConfig()
    if not cfg.enabled or not beats:
        return []
    key = os.environ.get(cfg.api_key_env, "").strip()
    if not key:
        log.info("Sin %s: el director usa solo las señales cinemáticas", cfg.api_key_env)
        return []
    cache_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    scenes: list[SceneBeat] = []
    calls = from_cache = tokens_in = tokens_out = 0
    try:
        for beat in beats:
            frames = _sample(cap, beat)
            if not frames:
                continue
            digest = hashlib.sha256(b"".join(frames)).hexdigest()[:20]
            cached = cache_dir / f"{digest}.json"
            if cached.exists():
                scenes.append(SceneBeat.model_validate_json(cached.read_text(encoding="utf-8")))
                from_cache += 1
                continue
            try:
                text, (used_in, used_out) = _ask(cfg, key, frames)
                calls += 1
                tokens_in += used_in
                tokens_out += used_out
                payload = json.loads(text)
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
                log.warning("El VLM falló en el beat %s (%s); se omite", beat.id, exc)
                continue
            scene = SceneBeat(
                beat_id=beat.id,
                scene=str(payload.get("scene", ""))[:80],
                gesture=str(payload.get("gesture", ""))[:120],
                intent=str(payload.get("intent", ""))[:120],
                objects=[str(item)[:40] for item in payload.get("objects", []) if isinstance(item, str)][:8],
            )
            cached.write_text(scene.model_dump_json(), encoding="utf-8")
            scenes.append(scene)
    finally:
        cap.release()
    log.info(
        "VLM %s: %d llamadas, %d beats desde caché, %d tokens de entrada, %d de salida",
        cfg.model,
        calls,
        from_cache,
        tokens_in,
        tokens_out,
    )
    return scenes


def _sample(cap: cv2.VideoCapture, beat: Beat) -> list[bytes]:
    span = max(beat.end_frame - beat.start_frame, 1)
    indexes = [beat.start_frame + int(span * t) for t in (0.2, 0.5, 0.8)]
    blobs: list[bytes] = []
    for index in indexes:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok:
            continue
        small = cv2.resize(frame, (360, 640))
        ok, encoded = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if ok:
            blobs.append(encoded.tobytes())
    return blobs


def _ask(cfg: SceneConfig, key: str, frames: list[bytes], prompt: str = _PROMPT, purpose: str = "scene") -> tuple[str, tuple[int, int]]:
    """Devuelve el texto de la respuesta y los tokens de entrada y salida."""
    images = [base64.b64encode(blob).decode("ascii") for blob in frames]
    started = time.perf_counter()
    ask = _gemini if cfg.provider == "gemini" else _openai
    text, (tokens_in, tokens_out) = ask(cfg.model, key, images, prompt)
    telemetry.llm_call(cfg.provider, cfg.model, purpose, tokens_in, tokens_out, round((time.perf_counter() - started) * 1000), images=len(images))
    return text, (tokens_in, tokens_out)


def _openai(model: str, key: str, images: list[str], prompt: str = _PROMPT) -> tuple[str, tuple[int, int]]:
    content: list[dict] = [{"type": "text", "text": prompt}]
    content.extend(
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}", "detail": "low"}}
        for image in images
    )
    body: dict = {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": content}],
    }
    if _is_reasoning(model):
        # Los modelos de razonamiento solo aceptan la temperatura por defecto y
        # gastan tokens pensando antes del JSON.
        body["max_completion_tokens"] = 2000
        body["reasoning_effort"] = "minimal"
    else:
        body["temperature"] = 0.2
        body["max_tokens"] = 300
    raw = _post(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        body,
    )
    usage = raw.get("usage") or {}
    text = raw["choices"][0]["message"]["content"] or ""
    return text, (int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)))


def _gemini(model: str, key: str, images: list[str], prompt: str = _PROMPT) -> tuple[str, tuple[int, int]]:
    parts: list[dict] = [{"text": prompt}]
    parts.extend({"inline_data": {"mime_type": "image/jpeg", "data": image}} for image in images)
    body = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    raw = _post(url, {"Content-Type": "application/json"}, body)
    usage = raw.get("usageMetadata") or {}
    text = raw["candidates"][0]["content"]["parts"][0]["text"]
    return text, (int(usage.get("promptTokenCount", 0)), int(usage.get("candidatesTokenCount", 0)))


def _is_reasoning(model: str) -> bool:
    name = model.lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


def _post(url: str, headers: dict[str, str], body: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60, context=ssl_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise ValueError(f"HTTP {exc.code}: {detail}") from exc
