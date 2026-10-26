"""Proveedores del director. El HTTP vive aquí para no atar el núcleo a un SDK."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Protocol

from vfxglow import telemetry
from vfxglow.analysis.models_store import ssl_context
from vfxglow.config import DirectorConfig

log = logging.getLogger("vfxglow.director")


class Completer(Protocol):
    def __call__(self, prompt: str) -> str: ...


def extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("La respuesta del director no contiene un objeto JSON.")
    return stripped[start : end + 1]


def build_completer(cfg: DirectorConfig, images: list[bytes] | None = None, system: str | None = None) -> Completer:
    encoded = [base64.b64encode(blob).decode("ascii") for blob in images or []]
    if cfg.provider == "openai":
        return lambda prompt: _openai(prompt, cfg, encoded, system)
    if cfg.provider == "anthropic":
        return lambda prompt: _anthropic(prompt, cfg, encoded, system)
    raise RuntimeError(f"Proveedor sin cliente de texto: {cfg.provider}")


def _api_key(cfg: DirectorConfig) -> str:
    key = os.environ.get(cfg.api_key_env, "").strip()
    if not key:
        raise RuntimeError(
            f"Falta la clave de API en la variable de entorno {cfg.api_key_env}."
        )
    return key


def _post(url: str, payload: dict, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120, context=ssl_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"El director remoto respondió {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo contactar al director remoto: {exc.reason}") from exc


def _openai(prompt: str, cfg: DirectorConfig, images: list[str], system: str | None) -> str:
    base = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
    content: str | list[dict] = prompt
    if images:
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}", "detail": "low"}}
            for image in images
        ]
    payload: dict = {
        "model": cfg.model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system or _system_prompt()},
            {"role": "user", "content": content},
        ],
    }
    if _is_reasoning(cfg.model):
        # Sin temperatura: los modelos de razonamiento solo aceptan la de por defecto.
        payload["max_completion_tokens"] = cfg.max_tokens
        payload["reasoning_effort"] = cfg.reasoning_effort
    else:
        payload["temperature"] = cfg.temperature
        payload["max_tokens"] = cfg.max_tokens
    started = time.perf_counter()
    data = _post(
        f"{base}/chat/completions",
        payload,
        {
            "Authorization": f"Bearer {_api_key(cfg)}",
            "Content-Type": "application/json",
        },
    )
    usage = data.get("usage") or {}
    log.info(
        "Director %s: %s tokens de entrada, %s de salida",
        cfg.model,
        usage.get("prompt_tokens", "?"),
        usage.get("completion_tokens", "?"),
    )
    telemetry.llm_call("openai", cfg.model, "director", usage.get("prompt_tokens"), usage.get("completion_tokens"), round((time.perf_counter() - started) * 1000), images=len(images))
    return str(data["choices"][0]["message"]["content"] or "")


def _is_reasoning(model: str) -> bool:
    return model.lower().startswith(("gpt-5", "o1", "o3", "o4"))


def _anthropic(prompt: str, cfg: DirectorConfig, images: list[str], system: str | None) -> str:
    base = (cfg.base_url or "https://api.anthropic.com").rstrip("/")
    content: str | list[dict] = prompt
    if images:
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}}
            for image in images
        ] + [{"type": "text", "text": prompt}]
    payload = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
        "system": system or _system_prompt(),
        "messages": [{"role": "user", "content": content}],
    }
    started = time.perf_counter()
    data = _post(
        f"{base}/v1/messages",
        payload,
        {
            "x-api-key": _api_key(cfg),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    usage = data.get("usage") or {}
    log.info(
        "Director %s: %s tokens de entrada, %s de salida",
        cfg.model,
        usage.get("input_tokens", "?"),
        usage.get("output_tokens", "?"),
    )
    telemetry.llm_call("anthropic", cfg.model, "director", usage.get("input_tokens"), usage.get("output_tokens"), round((time.perf_counter() - started) * 1000), images=len(images))
    blocks = data.get("content", [])
    texts = [block.get("text", "") for block in blocks if block.get("type") == "text"]
    if not texts:
        raise RuntimeError("Anthropic no devolvió texto.")
    return "\n".join(texts)


def _system_prompt() -> str:
    return (
        "Eres el director creativo de un sistema de VFX por capas. "
        "No dibujas píxeles ni reconstruyes el fotograma. "
        "Respondes únicamente con un Effect Script JSON válido, sin markdown."
    )
