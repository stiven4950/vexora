"""Análisis profundo: un modelo ve el video completo con su audio, como un animador, y escribe la
coreografía (opcional y de pago; por defecto el coreógrafo económico de siempre).

Nace de la prueba con video_35 (docs/metaforas.md): Gemini 4 Argon, con el video entero, leyó la
intención de cada gesto, escuchó la letra ("It's a UFO", "I don't need no supersuit") y propuso
metáforas con historia. Con fotos sueltas por beat (scene_reader) eso no sale.

Flujo:
1. `build_prompt`: el prompt de animador con el catálogo real (acciones, opciones y figuras).
2. `ask_gemini`: sube el video (API de archivos de Gemini), pide un JSON y borra el archivo.
3. `to_pins`: revisa la respuesta y la vuelve un guion de prueba (director/pins.py) con color e
   intención por momento. Lo que no existe en el catálogo se cambia por el sustituto que el
   mismo modelo propone; los efectos nuevos quedan anotados para programarlos después.

La respuesta se guarda por video, modelo y prompt: reprocesar no vuelve a pagar.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from vfxglow.config import DeepConfig
from vfxglow.director.pins import Pin, PinFile, hex_color

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com"
# Un momento dura entre esto (s): ni un parpadeo ni un efecto eterno.
MIN_DUR, MAX_DUR = 0.2, 4.0

# Qué gesto dispara cada acción del catálogo (para que el modelo sepa cuál elegir).
ACTIONS = {
    "entrance": "la persona aparece o arranca",
    "spotlight": "cualquier momento (la parte del cuerpo protagonista)",
    "point": "señala con el brazo extendido",
    "hands_on_head": "manos sobre o alrededor de la cabeza",
    "rock_hands": "cuernos de rock con la mano",
    "arms_x": "brazos cruzados en X",
    "lunge": "se lanza hacia la cámara",
    "arms_open": "abre los brazos",
    "arms_up": "sube los brazos",
    "heart_hands": "corazón con las manos",
    "hand_ear": "mano en la oreja",
    "cover_eyes": "se tapa los ojos",
    "face_touch": "se toca la cara",
    "spin_body": "gira sobre sí mismo",
    "fast_swing": "golpe, barrido o patada rápida",
    "stomp": "pisotón",
    "throw": "lanza algo",
    "frenzy": "movimiento frenético",
    "beat": "golpe fuerte de la música",
    "still": "quieto",
    "neck_slash": "se pasa la mano por el cuello",
    "prop_transfer": "pasa un objeto a otra mano o persona",
    "prop_spin": "hace girar un objeto",
    "prop_worn": "se pone un objeto (gorra)",
}

# Las figuras con historia: qué hacen, para que el modelo no las elija a ciegas.
STORIES = {
    "stick_man": "un muñequito camina por el brazo extendido, cae, la otra mano lo atrapa y lo aplasta",
    "ufo": "un ovni nace entre las manos, orbita la cabeza, se descontrola, deja caer algo en el pecho y persigue las manos",
    "snake": "una serpiente recorre los brazos de mano a mano, se enrosca y sale como un rayo",
    "water_balloon": "un globo de agua en la extremidad más rápida: se estira, se aplasta y revienta",
    "spark_trap": "una chispa viva salta a la mano levantada, el puño la atrapa dos veces y se parte en dos aros",
    "time_rope": "un ancla detrás de la persona y una soga que jala con las manos; al final se enrolla en una bola de energía",
    "supersuit": "dos cierres suben dibujando una armadura en el torso; el emblema brilla y las placas caen",
    "glider": "alas de planeador entre muñecas y cintura, ondas a los costados y un rayo final de punta a punta",
    "battery": "una batería se carga en el pecho hasta 100%",
    "hero_text": "la palabra HERO en el pecho",
    "punk_crest": "cresta punk que gira con la cabeza; las gafas suben y se vuelve arcos",
    "venom": "cara de Venom",
    "iron_man": "casco de Iron Man",
    "devil_eyes": "cuernos y ojos de demonio",
    "hand_flames": "llamas en las manos",
    "claws": "garras que cortan el aire",
    "exclaim": "signos de exclamación sobre los antebrazos",
    "rock_hands": "manos dibujadas haciendo cuernos de rock",
}

PROMPT = """Eres un animador profesional de efectos 2D en neón. Trabajas para VEXORA: sobre un video
real de baile se dibujan trazos de luz de neón que siguen el cuerpo. El video original no se
modifica; solo se agregan dibujos encima. Tu trabajo no es decorar: es encontrar la intención de
cada movimiento y contarla con un dibujo, como un animador que edita a mano.

Mira el video completo con atención a los tiempos exactos (duración: {duration:.1f} s) y escucha
la canción: la letra y los sonidos (una sirena, un golpe) son fuente de ideas.

Trabaja en este orden:
1. Lee el video: quién es el protagonista (las personas que solo miran NUNCA reciben efectos) y
   qué hace en cada momento, cada 0,3 a 2 s, sin huecos.
2. La historia: arco (inicio, subida, clímax, cierre), un motivo que vuelva, los contrastes y un
   color por acto.
3. Para cada momento, PRIMERO y sin mirar el catálogo, decide la intención (presume, huye,
   atrapa, desafía, carga energía…) y la metáfora ideal, usando el cuerpo como escenario:
   el escenario es el cuerpo (un brazo extendido es una plataforma; la cabeza, un planeta), el
   gesto pone el conflicto (la otra mano persigue, un giro centrifuga) y el final conecta con lo
   que sigue. DESPUÉS busca en el catálogo el efecto que la cuenta. Si ninguno la cuenta bien, es
   un efecto nuevo: descríbelo y usa en ese momento el efecto del catálogo más parecido.

Reglas: ningún segundo sin efecto; un efecto principal por momento; dibujos simples y legibles.

Catálogo (accion: opciones; entre corchetes, las figuras que dibuja cada opción):
{catalog}

Qué hacen las figuras con historia:
{stories}

Responde SOLO este JSON (sin texto fuera de él):
{{
  "protagonista": "ropa y rasgos para identificarlo",
  "publico": "quiénes solo miran",
  "lectura": [{{"inicio": 0.0, "fin": 0.5, "cuerpo": "qué hace exacto", "intencion": "qué transmite", "camara": "qué hace la cámara"}}],
  "historia": {{"arco": "", "motivo": "", "contrastes": "", "colores": ""}},
  "momentos": [{{"seg": 4.1, "dur": 1.1, "accion": "point", "opcion": "munequito", "figura": null,
                 "color": "#39ff14", "intencion": "por qué este efecto aquí", "nuevo": null}}],
  "efectos_nuevos": [{{"nombre": "trampa_chispa", "segundos": "8.9-10.1", "escenario": "", "nace": "",
                       "recorrido": "", "conflicto": "", "final": "", "fisica": "", "porque": ""}}]
}}
- seg y dur en segundos con un decimal. accion y opcion: SOLO combinaciones del catálogo.
- figura: opcional, una de las figuras de esa opción.
- color: hexadecimal, el del acto o el momento.
- nuevo: el nombre del efecto nuevo que ese momento debería tener (descrito en efectos_nuevos),
  o null. En ese caso accion/opcion son el sustituto más parecido del catálogo.
"""


def catalog_text(catalog) -> str:
    lines = []
    for reaction in catalog.reactions:
        options = []
        for option in reaction.options:
            shapes = sorted({s for raw in option.effects for s in raw.get("style", {}).get("shapes", [])})
            if not option.effects:
                continue
            options.append(f"{option.name} [{', '.join(shapes)}]" if shapes else option.name)
        if options:
            gesture = ACTIONS.get(reaction.action, "")
            lines.append(f"- {reaction.action} ({gesture}): {', '.join(options)}" if gesture else f"- {reaction.action}: {', '.join(options)}")
    return "\n".join(lines)


def build_prompt(catalog, duration: float) -> str:
    stories = "\n".join(f"- {name}: {text}" for name, text in STORIES.items())
    return PROMPT.format(duration=duration, catalog=catalog_text(catalog), stories=stories)


# ----- Gemini -----


def _request(url: str, key: str, data: bytes | None = None, headers: dict | None = None, method: str | None = None, timeout: float = 120.0):
    from vfxglow.analysis.models_store import ssl_context

    request = urllib.request.Request(url, data=data, method=method, headers={"x-goog-api-key": key, **(headers or {})})
    return urllib.request.urlopen(request, timeout=timeout, context=ssl_context())


def _upload(video: Path, key: str, timeout: float) -> dict:
    """Sube el video con la API de archivos (sirve para videos de más de 20 MB) y espera a que
    Gemini termine de procesarlo."""
    size = video.stat().st_size
    start = _request(
        f"{API}/upload/v1beta/files",
        key,
        json.dumps({"file": {"display_name": video.name}}).encode(),
        {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": "video/mp4",
            "Content-Type": "application/json",
        },
    )
    upload_url = start.headers["X-Goog-Upload-URL"]
    with _request(
        upload_url,
        key,
        video.read_bytes(),
        {"Content-Length": str(size), "X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"},
        timeout=timeout,
    ) as response:
        info = json.loads(response.read())["file"]
    deadline = time.monotonic() + timeout
    while info.get("state") == "PROCESSING":
        if time.monotonic() > deadline:
            raise TimeoutError("Gemini no terminó de procesar el video")
        time.sleep(3)
        with _request(f"{API}/v1beta/{info['name']}", key) as response:
            info = json.loads(response.read())
    if info.get("state") != "ACTIVE":
        raise RuntimeError(f"Gemini no pudo leer el video ({info.get('state')})")
    return info


def ask_gemini(video: Path, prompt: str, cfg: DeepConfig) -> tuple[dict, dict]:
    """(respuesta JSON, uso de tokens). Sin clave en el entorno es un error: el usuario pidió el
    análisis profundo y no debe salir el económico sin avisar."""
    key = os.environ.get(cfg.api_key_env, "").strip()
    if not key:
        raise RuntimeError(f"El análisis profundo necesita {cfg.api_key_env} en el entorno (.env)")
    info = _upload(video, key, cfg.timeout_s)
    try:
        body = {
            "contents": [{
                "parts": [
                    {"file_data": {"mime_type": info.get("mimeType", "video/mp4"), "file_uri": info["uri"]}, "video_metadata": {"fps": cfg.fps}},
                    {"text": prompt},
                ]
            }],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        try:
            with _request(
                f"{API}/v1beta/models/{cfg.model}:generateContent",
                key,
                json.dumps(body).encode(),
                {"Content-Type": "application/json"},
                timeout=cfg.timeout_s,
            ) as response:
                raw = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Gemini respondió {exc.code}: {exc.read()[:400].decode(errors='replace')}") from exc
    finally:
        try:
            _request(f"{API}/v1beta/{info['name']}", key, method="DELETE").close()
        except (urllib.error.URLError, OSError):
            log.warning("No se pudo borrar el video subido a Gemini (%s); vence solo en 48 h", info.get("name"))
    parts = raw["candidates"][0]["content"]["parts"]
    text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
    return json.loads(text), raw.get("usageMetadata", {})


# ----- de la respuesta al guion -----


def _match(catalog, accion: str | None, opcion: str | None):
    """(acción, opción) del catálogo; la acción se corrige si la opción solo está en otra."""
    found = [(r, o) for r in catalog.reactions for o in r.options if o.name == opcion and o.effects]
    exact = [(r, o) for r, o in found if r.action == accion]
    if exact:
        return exact[0]
    return found[0] if len(found) == 1 else None


def to_pins(answer: dict, catalog, duration: float) -> tuple[PinFile, list[str]]:
    """El guion de prueba de la respuesta y los avisos de lo que se corrigió o descartó."""
    warnings: list[str] = []
    pins: list[Pin] = []
    for raw in answer.get("momentos", []):
        if not isinstance(raw, dict):
            continue
        try:
            seg = round(float(raw.get("seg")), 2)
            dur = float(raw.get("dur") or 0.6)
        except (TypeError, ValueError):
            warnings.append(f"momento sin segundo válido: {raw}")
            continue
        if not 0 <= seg < duration:
            warnings.append(f"{seg} s: fuera del video")
            continue
        match = _match(catalog, raw.get("accion"), raw.get("opcion"))
        if match is None:
            warnings.append(f"{seg} s: {raw.get('accion')}:{raw.get('opcion')} no existe en el catálogo; se omite")
            continue
        reaction, option = match
        if reaction.action != raw.get("accion"):
            warnings.append(f"{seg} s: {option.name} es de {reaction.action}, no de {raw.get('accion')}")
        shapes = {s for e in option.effects for s in e.get("style", {}).get("shapes", [])}
        figura = raw.get("figura") if raw.get("figura") in shapes and len(shapes) > 1 else None
        color = raw.get("color") if hex_color(raw.get("color")) is not None else None
        nota = str(raw.get("intencion") or "").strip()[:200] or None
        if raw.get("nuevo"):
            nota = f"[nuevo: {raw['nuevo']}] {nota or ''}".strip()
        pins.append(Pin(
            seg=seg,
            dur=round(min(max(dur, MIN_DUR), MAX_DUR, duration - seg), 2),
            accion=reaction.action,
            opcion=option.name,
            figura=figura,
            exacto=True,
            color=color,
            nota=nota,
        ))
    pins.sort(key=lambda pin: pin.seg)
    return PinFile(catalogo=catalog.name, solo_estos=True, momentos=pins), warnings


def answer_key(video_sha: str, prompt: str, cfg: DeepConfig) -> str:
    return hashlib.sha256(f"{video_sha}|{cfg.model}|{cfg.fps}|{prompt}".encode()).hexdigest()[:20]


def deep_pins(video: Path, video_sha: str, catalog, duration: float, cfg: DeepConfig, out_dir: Path) -> Path:
    """Guion del análisis profundo en `out_dir` (deep_guion.yaml), con la lectura completa al
    lado (deep_lectura.json). La respuesta del modelo se guarda en caché por video y prompt."""
    from vfxglow.director.pins import save_pins

    prompt = build_prompt(catalog, duration)
    key = answer_key(video_sha, prompt, cfg)
    cache = out_dir / "deep_cache" / f"{key}.json"
    if cache.exists():
        answer = json.loads(cache.read_text(encoding="utf-8"))
        log.info("Análisis profundo en caché (%s)", cfg.model)
    else:
        log.info("Análisis profundo con %s: subiendo el video completo (puede tardar unos minutos)", cfg.model)
        answer, usage = ask_gemini(video, prompt, cfg)
        log.info(
            "Análisis profundo listo: %s tokens de entrada, %s de salida",
            usage.get("promptTokenCount", "?"),
            usage.get("candidatesTokenCount", "?"),
        )
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(answer, ensure_ascii=False, indent=1), encoding="utf-8")
    pins, warnings = to_pins(answer, catalog, duration)
    for warning in warnings:
        log.warning("Análisis profundo: %s", warning)
    if not pins.momentos:
        raise RuntimeError("El análisis profundo no dejó ningún momento utilizable")
    guion = out_dir / "deep_guion.yaml"
    save_pins(pins, guion)
    (out_dir / "deep_lectura.json").write_text(json.dumps(answer, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Análisis profundo: %d momentos, %d efectos nuevos propuestos", len(pins.momentos), len(answer.get("efectos_nuevos") or []))
    return guion


def record_proposals(answer_path: Path, ledger: Path, video_name: str) -> int:
    """Suma los efectos nuevos de una lectura a la lista común de efectos pedidos (una línea JSON
    por efecto). Cada lectura se anota una sola vez. Devuelve cuántos se anotaron."""
    answer = json.loads(answer_path.read_text(encoding="utf-8"))
    tag = hashlib.sha256(answer_path.read_bytes()).hexdigest()[:12]
    seen = ledger.read_text(encoding="utf-8") if ledger.exists() else ""
    if f'"lectura": "{tag}"' in seen:
        return 0
    added = 0
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as out:
        for item in answer.get("efectos_nuevos") or []:
            if isinstance(item, dict) and item.get("nombre"):
                out.write(json.dumps({"video": video_name, "lectura": tag, **item}, ensure_ascii=False) + "\n")
                added += 1
    return added
