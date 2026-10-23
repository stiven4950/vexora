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
from collections.abc import Callable
from pathlib import Path

from vfxglow.config import DeepConfig
from vfxglow.director.pins import Alternativa, Capitulo, Pin, PinFile, hex_color

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com"
# Un momento dura entre esto (s): ni un parpadeo ni un efecto eterno.
MIN_DUR, MAX_DUR = 0.2, 4.0

# Qué gesto dispara cada acción del catálogo (para que el modelo sepa cuál elegir).
ACTIONS = {
    "entrance": "la persona aparece o arranca",
    "spotlight": "cualquier momento (la parte del cuerpo protagonista)",
    "point": "señala con el brazo extendido",
    "hand_chin": "una mano en el mentón y la otra extendida",
    "fist_up": "puño en alto a la altura del hombro (la atención en el puño)",
    "finger_gun": "la mano en forma de revólver (índice al frente, pulgar arriba); el pulgar que baja es el disparo",
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
    "yoyo": "una esfera con hilo elástico rebota entre la mano y el piso; al final la mano la recoge y estalla en chispas",
    "bee": "una abeja zumba en ochos alrededor de la cabeza y esquiva la mano; un aplauso la atrapa",
    "energy_ball": "una bola de energía se carga en la mano (o entre las dos) y sale disparada como un rayo",
    "rocket": "un cohete despega de los pies con humo, sube por el cuerpo y estalla en fuegos sobre la cabeza",
    "bird": "un pájaro llega, se posa en el brazo extendido, picotea y sale volando si el brazo se sacude",
    "bubble": "una burbuja envuelve a la persona, tiembla con lo pequeño y revienta con un movimiento fuerte",
    "finger_gun": "un revólver de neón sobre la mano que dispara cuando baja el pulgar: fogonazo, retroceso, bala, casquillo y humo",
    "bullet": "solo la bala que sale del dedo con su estela y el fogonazo",
    "goddess_arms": "los brazos se copian en neón y se abren en abanico (seis brazos, como una diosa); al final se pliegan de golpe",
    "snap_cables": "cables de energía entre las manos de una persona y los hombros de la otra; se tensan con el tirón y revientan con un latigazo",
    "mind_blown": "emoji de sorpresa en la cara; al abrir las manos de golpe la tapa de la cabeza sale en un resorte y vuelan pedazos de cerebro",
    "lion_roar": "melena de león alrededor de la cara y el rugido: ondas desde la boca y un ROAR! que tiembla (asustar)",
    "fist_orb": "una bola brillante pequeña en el puño con rayos que chisporrotean",
    "fist_rays": "rayitos de colores distintos que salen del puño",
    "coins": "monedas que caen del puño girando y rebotan en el piso",
    "sand": "un chorro de arena que cae del puño y hace un montoncito",
    "glitter": "escarcha que cae del puño destellando",
    "hourglass": "reloj de arena: la mitad de abajo en el piso y la de arriba cortada hasta el puño, que vierte la arena (controla el tiempo)",
    "shofar": "un cuerno de guerra de la boca a la otra mano, que se curva; de la campana sale el llamado",
    "snack": "pastel o carne en una mano y cuchara o cuchillo en la otra; se le caen cuando baja las manos al piso",
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

Reglas:
- Tú pones la historia: los momentos principales, sin huecos, con dibujos simples y legibles.
  El sistema agrega por su cuenta los acentos pequeños (golpes de la música, chispas, toques en
  la otra persona), así que no hace falta que los pidas.
- Si bailan dos o más personas, di a quién va cada momento ("quien") mirando el video tal como se
  ve: izquierda o derecha en ese segundo, o ambos si hacen lo mismo. Reparte la historia entre
  las dos personas según quién tiene la atención; no la cargues toda en una.
- Las figuras con historia (lista de abajo) llaman mucho la atención: úsalas en los 2 a 4
  momentos más fuertes del video, solo donde la metáfora encaje de verdad con el gesto, y nunca
  la misma dos veces. No las fuerces: el resto del video lo cuentan los demás efectos.
- Si la metáfora ideal de un momento no está en el catálogo, propón el efecto nuevo (hasta 3 por
  video): es bienvenido y se programa después.

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
                 "alternativas": [{{"opcion": "aro", "figura": null, "encaje": 0.7}}],
                 "color": "#39ff14", "quien": "protagonista", "intencion": "por qué este efecto aquí", "nuevo": null}}],
  "capitulos": [{{"inicio": 0.0, "fin": 2.5, "elemento": "agua", "voz": "lo que dice la voz"}}],
  "efectos_nuevos": [{{"nombre": "trampa_chispa", "segundos": "8.9-10.1", "escenario": "", "nace": "",
                       "recorrido": "", "conflicto": "", "final": "", "fisica": "", "porque": ""}}]
}}
- seg y dur en segundos con un decimal. accion y opcion: SOLO combinaciones del catálogo.
- figura: opcional y SOLO una de las que aparecen entre corchetes en esa opción; si la que
  imaginas no está en la lista, usa null (no inventes nombres de figuras).
- alternativas: 1 a 2 opciones de la MISMA acción que también cuentan esa intención (no otra
  acción), con su encaje de 0 a 1 (qué tan bien la cuentan); la opción principal es la mejor.
- color: hexadecimal, el del acto o el momento.
- quien: "protagonista" si baila una sola persona; con dos o más, "izquierda", "derecha" o
  "ambos" (como se ve en pantalla en ese segundo).
- capitulos: solo si una voz del video nombra elementos (tramo de cada uno, en segundos); si no,
  lista vacía.
- nuevo: el nombre del efecto nuevo que ese momento debería tener (descrito en efectos_nuevos),
  o null. En ese caso accion/opcion son el sustituto más parecido del catálogo.
"""


# Marcas de estilo que viajan en `shapes` pero no son figuras (cómo se dibuja, no qué).
STYLE_FLAGS = {"no_outline", "no_fill", "lines_only", "partial", "abs", "wave", "wave_down", "hem", "flap", "stitches", "dots", "glow"}


def figures(option) -> list[str]:
    return sorted({s for raw in option.effects for s in raw.get("style", {}).get("shapes", [])} - STYLE_FLAGS)


def catalog_text(catalog) -> str:
    lines = []
    for reaction in catalog.reactions:
        options = []
        for option in reaction.options:
            shapes = figures(option)
            if not option.effects:
                continue
            options.append(f"{option.name} [{', '.join(shapes)}]" if shapes else option.name)
        if options:
            gesture = ACTIONS.get(reaction.action, "")
            lines.append(f"- {reaction.action} ({gesture}): {', '.join(options)}" if gesture else f"- {reaction.action}: {', '.join(options)}")
    return "\n".join(lines)


# Las figuras de fuego del estilo Avatar (engine/firebend.py, engine/fire_creatures.py): no son
# metáforas raras sino el lenguaje del estilo, y el modelo debe saber qué dibuja cada una.
FIRE_FIGURES = {
    "fire_trail": "la estela de fuego (el swoosh de fuego, el efecto más recurrente): la mano o el pie lleva la llama prendida y, al moverse, el fuego la persigue por su recorrido; sale de las manos cuando ellas tienen la atención y de los pies en volteretas, rodadas o patadas",
    "fire_whip": "medialunas de fuego grandes y espejadas con las dos manos: solo al abrir los brazos o en un salto (no en cada golpe)",
    "fire_blast": "chorro de fuego desde el puño en la dirección del antebrazo, que se abre en lenguas al final (lanzar, empujar)",
    "fire_halo": "aro grande de fuego que sube de un pie y rodea todo el cuerpo (giros y volteretas)",
    "fire_orbit": "la mano pone el fuego a girar alrededor del cuerpo, lo atrapa al completar la vuelta y, si estira el brazo o abre la mano, lo lanza como explosión",
    "fire_landing": "al caer al piso con el fuego en los pies (después de una voltereta), el fuego se desbarata en el suelo",
    "fire_phoenix": "un fénix de fuego que sale del puño al lanzar, hace un arco sobre la persona, vuelve en picada a la mano y se usa en el puñetazo siguiente (explosión en estrella)",
    "fire_dragon_launch": "un dragón oriental de fuego con el mismo ciclo que el fénix: sale del puño, vuelve a la mano y se usa en el golpe",
    "fire_coil": "una serpiente de fuego que se enrosca en el brazo, rodea el cuerpo siguiendo un giro, sube en espiral y vuelve a la mano para el golpe",
    "fire_kitsune": "nueve colas de fuego en abanico desde la cadera, que siguen el giro y se abren con los brazos; luego el fuego va a la mano para el golpe",
    "fire_lion": "melena de fuego alrededor de la cabeza, rugido en anillo y, en el golpe, un zarpazo de tres cortes",
    "hand_fire": "llamas de base redonda que suben de las manos",
    "candle": "una sola llama entre las manos juntas que se achica",
    "floor_fire": "fuego a ras del piso bajo la mano o el pie",
    "fire_splash": "el fuego choca contra el piso y se expande en olas",
    "fire_ring": "un aro de fuego que gira alrededor de la mano",
    "fire_skull": "calavera con melena de fuego en la cabeza; luego el fuego viaja a la mano",
    "fire_bird": "ave de fuego que sale de la mano levantada, vuela y vuelve",
    "fire_serpent": "dragón serpiente de fuego que sale de la mano",
    "fire_breath": "el fuego sube a la cabeza, sale por la boca y queda una cara de demonio",
    "fire_dragon": "las llamas suben por los brazos y forman un dragón de alas enormes",
    "body_blaze": "el cuerpo arde: llamas en brazos y piernas y alas de fuego",
    "avatar_mark": "estado Avatar: la flecha que sube de la frente por la cabeza (de espaldas, por la columna) y los ojos encendidos",
    "wind": "viento (elemento aire): pinceladas anchas de aire, blancas lisas o de neón azul, que siguen a las extremidades rápidas en giros, saltos y volteretas",
}

# Los momentos de temporada (Halloween): cada uno es la consecuencia de un gesto, no decoración.
SEASON_FIGURES = {
    "bat_release": "la mano que suelta algo (golpe, brazos abiertos, lanzamiento) libera murciélagos que escapan hacia arriba",
    "claw_slash": "un tajo con la mano deja cuatro arañazos en la dirección del golpe",
    "ghost_rise": "al pisar fuerte sale un fantasma del piso, donde pisó el pie",
    "pumpkin_head": "en una pausa de frente a la cámara la cabeza se vuelve una calabaza tallada encendida (solo de frente y quieto)",
    "spider_drop": "si se queda quieto, una araña baja de su hilo hasta la cabeza",
    "web_corner": "si se queda quieto mucho rato, crece una telaraña en la esquina de arriba",
    "bat_swarm": "un enjambre de murciélagos sale del cuerpo en un movimiento frenético",
}

# Reglas del estilo Avatar (configs/catalogs/avatar.yaml): el coreógrafo las cumple solo, pero lo
# que fija el modelo pasa por encima, así que el modelo tiene que conocerlas.
AVATAR_RULES = """Reglas del estilo Avatar (respétalas: lo que tú fijas pasa por encima del sistema):
- Un elemento por capítulo: el video se cuenta en tramos de 3 a 4 s y cada tramo es de UN solo
  elemento (fuego, rayo o aire). El fuego abre, cierra y vuelve después de cada tramo de rayo o
  de aire. Nunca pongas un rayo o un viento dentro de un tramo de fuego, ni al revés.
- El swoosh de fuego (estela) es el efecto principal: úsalo en la mayoría de golpes, estocadas y
  giros. Las medialunas solo al abrir los brazos o en un salto; el chorro, poco.
- El fuego va donde está la atención: de las manos cuando son ellas las que mandan; en
  volteretas, rodadas o patadas, de los pies.
- Continuidad: el fuego nunca aparece ni desaparece de golpe. Al pasar de una extremidad a otra
  (de una mano a la otra, de la cabeza a la mano, de las manos a los pies) el sistema lo hace
  viajar solo; tú elige momentos seguidos que cuenten ese viaje (por ejemplo, la calavera y
  luego el puño que lanza; la voltereta y luego la caída que desbarata el fuego).
- El rayo sale solo de las manos y se lanza desde ellas: en un tramo de rayo, al lanzar, señalar
  o extender el brazo; nunca de los pies ni del cuerpo.
- El viento (aire) va en un tramo de giros, saltos o volteretas.
- Las bestias tienen un objetivo: salen de una extremidad, hacen su recorrido, vuelven a la mano
  y la persona las usa en un golpe. Elige una bestia SOLO si poco después (1 a 2 s) hay un golpe
  de esa mano que la use, y cada una como mucho una vez por video. Por gesto: lanzamiento → fénix
  o dragón; giro → serpiente o kitsune; estocada → león.
- Cadenas: una voltereta con el fuego en los pies y, si cae al piso enseguida, el desbarate.
- Si una voz del video nombra un elemento (agua, tierra, fuego, aire, rayo), desde ese segundo el
  tramo es de ese elemento hasta que nombre otro; los gestos de ese tramo usan los efectos de ese
  elemento y la voz manda sobre el reparto automático de capítulos. Si el catálogo no tiene
  efectos de ese elemento, repórtalo igual en "capitulos".
- No fijes cierres en el piso: la pared o la alfombra de fuego del final las pone el sistema solo
  si la persona termina quieta y de frente."""


def build_prompt(catalog, duration: float) -> str:
    stories = "\n".join(f"- {name}: {text}" for name, text in STORIES.items())
    shapes = {s for r in catalog.reactions for o in r.options for e in o.effects for s in e.get("style", {}).get("shapes", [])}
    fire = [f"- {name}: {text}" for name, text in FIRE_FIGURES.items() if name in shapes]
    if fire:  # el estilo Avatar: el fuego es el lenguaje principal, no un acento
        stories += "\n\nFiguras del estilo Avatar (el fuego en casi todos los momentos; las opciones \"rayo\" son el rayo cian que sale de la mano):\n" + "\n".join(fire)
        stories += "\n\n" + AVATAR_RULES
    season = [f"- {name}: {text}" for name, text in SEASON_FIGURES.items() if name in shapes]
    if season:  # una temporada encima: sus momentos son consecuencias de un gesto, no adornos
        stories += "\n\nMomentos de la temporada (solo con el gesto que los provoca, pocas veces cada uno):\n" + "\n".join(season)
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


def ask_gemini(video: Path, prompt: str, cfg: DeepConfig) -> tuple[dict, dict, str]:
    """(respuesta JSON, uso de tokens, modelo que respondió). Si el modelo principal sigue saturado
    tras sus reintentos, responde el de respaldo. Sin clave en el entorno es un error: el usuario
    pidió el análisis profundo y no debe salir el económico sin avisar."""
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
            raw = _generate(cfg, key, body)
            model = cfg.model
        except Saturated:
            if not cfg.fallback_model:
                raise
            log.warning("%s sigue saturado tras %d reintentos; se pide la respuesta a %s", cfg.model, cfg.retries, cfg.fallback_model)
            model = cfg.fallback_model
            raw = _generate(cfg.model_copy(update={"model": model}), key, body)
    finally:
        try:
            _request(f"{API}/v1beta/{info['name']}", key, method="DELETE").close()
        except (urllib.error.URLError, OSError):
            log.warning("No se pudo borrar el video subido a Gemini (%s); vence solo en 48 h", info.get("name"))
    parts = raw["candidates"][0]["content"]["parts"]
    text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
    return json.loads(text), raw.get("usageMetadata", {}), model


# Saturación pasajera (503 "high demand", 429 por cuota por minuto, 500/504): se reintenta con
# espera corta, sin volver a subir el video. Agotados los reintentos, se pasa al modelo de respaldo.
RETRY_CODES = (429, 500, 503, 504)
RETRY_WAITS_S = (5, 10, 20)


class Saturated(RuntimeError):
    """El modelo sigue respondiendo con saturación después de todos los reintentos."""


def _generate(cfg: DeepConfig, key: str, body: dict, sleep=time.sleep) -> dict:
    waits = list(RETRY_WAITS_S[: max(cfg.retries, 0)])
    while True:
        try:
            with _request(
                f"{API}/v1beta/models/{cfg.model}:generateContent",
                key,
                json.dumps(body).encode(),
                {"Content-Type": "application/json"},
                timeout=cfg.timeout_s,
            ) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode(errors="replace")
            if exc.code not in RETRY_CODES:
                raise RuntimeError(f"Gemini respondió {exc.code}: {detail}") from exc
            if not waits:
                raise Saturated(f"Gemini respondió {exc.code} en {cfg.model}: {detail}") from exc
            wait = waits.pop(0)
            log.warning("Gemini respondió %d (saturado); reintento en %d s (quedan %d)", exc.code, wait, len(waits))
            sleep(wait)


# ----- de la respuesta al guion -----


# Opciones renombradas: las respuestas guardadas con el nombre viejo siguen sirviendo.
RENAMED = {"latigo": "estela"}


def _match(catalog, accion: str | None, opcion: str | None):
    """(acción, opción) del catálogo; la acción se corrige si la opción solo está en otra."""
    if opcion in RENAMED and not any(o.name == opcion for r in catalog.reactions for o in r.options):
        opcion = RENAMED[opcion]
    found = [(r, o) for r in catalog.reactions for o in r.options if o.name == opcion and o.effects]
    exact = [(r, o) for r, o in found if r.action == accion]
    if exact:
        return exact[0]
    return found[0] if len(found) == 1 else None


def _alternatives(raw, catalog, action: str, main: str, seg: float, warnings: list[str]) -> list[Alternativa]:
    """Las alternativas del modelo que existen en la MISMA acción, sin repetidas ni la principal."""
    out: list[Alternativa] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            name = item["opcion"]
            fit = min(max(float(item.get("encaje", 0.5)), 0.05), 1.0)
            figura = item.get("figura")
            if not isinstance(name, str) or (figura is not None and not isinstance(figura, str)):
                raise TypeError
        except (KeyError, TypeError, ValueError, AttributeError):
            warnings.append(f"{seg} s: alternativa mal formada: {item}")
            continue
        found = next((o for r in catalog.reactions if r.action == action for o in r.options if o.name == name and o.effects), None)
        if found is None:
            warnings.append(f"{seg} s: la alternativa {name} no es de {action}; se omite")
            continue
        if name == main or any(a.opcion == name and a.figura == figura for a in out):
            continue
        shapes = figures(found)
        out.append(Alternativa(opcion=name, figura=figura if figura in shapes and len(shapes) > 1 else None, encaje=round(fit, 3)))
    return out


def to_pins(
    answer: dict,
    catalog,
    duration: float,
    fill: bool = True,
    who: Callable[[float, str], tuple[str | None, bool]] | None = None,
    snap: Callable[[float, str], float] | None = None,
    upgrade: Callable[[float, str], tuple[str, str] | None] | None = None,
) -> tuple[PinFile, list[str]]:
    """El guion de prueba de la respuesta y los avisos de lo que se corrigió o descartó.

    fill: el coreógrafo económico rellena alrededor de lo fijado (acentos, golpes de la música,
    la otra persona); sin él, solo lo que dijo el modelo (un efecto cada uno o dos segundos, que
    en un dúo deja casi sin nada a una persona: dance_two_mens).
    who(seg, quien) → (persona, ambos): la persona de "izquierda"/"derecha" en ese segundo.
    snap(seg, acción) → el segundo exacto del gesto que vio nuestro análisis cerca (snapper).
    upgrade(seg, acción) → (acción, opción) más específica que vio el análisis ahí (upgrader)."""
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
        exacto = True
        better = upgrade(seg, reaction.action) if upgrade is not None else None
        found = _match(catalog, *better) if better is not None else None
        if found is not None:
            # El análisis vio la seña concreta (el revólver con la mano): manda, y el momento se
            # engancha a ese gesto (exacto=False) para que sus disparos caigan donde fueron.
            warnings.append(f"{seg} s: {option.name} → {found[1].name} (el análisis vio {found[0].action})")
            reaction, option = found
            exacto = False
        elif snap is not None:
            seg = round(snap(seg, reaction.action), 2)
        if reaction.action != raw.get("accion"):
            warnings.append(f"{seg} s: {option.name} es de {reaction.action}, no de {raw.get('accion')}")
        shapes = figures(option)
        figura = raw.get("figura") if raw.get("figura") in shapes and len(shapes) > 1 else None
        if raw.get("figura") and raw.get("figura") not in shapes:
            warnings.append(f"{seg} s: la figura {raw.get('figura')} no es de {option.name}; se sortea")
        color = raw.get("color") if hex_color(raw.get("color")) is not None else None
        nota = str(raw.get("intencion") or "").strip()[:200] or None
        if raw.get("nuevo"):
            nota = f"[nuevo: {raw['nuevo']}] {nota or ''}".strip()
        persona, both = who(seg, str(raw.get("quien") or "").strip().lower()) if who is not None else (None, False)
        pins.append(Pin(
            alternativas=_alternatives(raw.get("alternativas"), catalog, reaction.action, option.name, seg, warnings),
            seg=seg,
            dur=round(min(max(dur, MIN_DUR), MAX_DUR, duration - seg), 2),
            accion=reaction.action,
            opcion=option.name,
            figura=figura,
            exacto=exacto,
            color=color,
            nota=nota,
            persona=persona,
            espejo=True if both else None,
        ))
    pins.sort(key=lambda pin: pin.seg)
    chapters: list[Capitulo] = []
    for raw in answer.get("capitulos") or []:
        if not isinstance(raw, dict):
            continue
        try:
            start, end = round(float(raw.get("inicio")), 2), round(float(raw.get("fin")), 2)
        except (TypeError, ValueError):
            warnings.append(f"capítulo sin tiempos válidos: {raw}")
            continue
        element = str(raw.get("elemento") or "").strip().lower()
        if end <= start or not element:
            warnings.append(f"capítulo inválido: {raw}")
            continue
        chapters.append(Capitulo(inicio=start, fin=end, elemento=element, voz=str(raw.get("voz") or "").strip()))
    chapters.sort(key=lambda c: c.inicio)
    return PinFile(catalogo=catalog.name, solo_estos=not fill, momentos=pins, capitulos=chapters), warnings


def sides_from_tracks(frames, fps: float) -> Callable[[float, str], tuple[str | None, bool]]:
    """who(seg, quien) para to_pins: con dos personas en pantalla, "izquierda" es la de la caja
    más a la izquierda en ese instante (o en el cuadro más cercano que las vea a las dos)."""
    seen: dict[int, list[tuple[float, str]]] = {}
    for record in frames:
        people = [((p.box[0] + p.box[2]) / 2, p.person_id) for p in record.people if p.box is not None]
        if len(people) >= 2:
            seen[record.frame] = sorted(people)
    known = sorted(seen)

    def who(seg: float, quien: str) -> tuple[str | None, bool]:
        if not known or quien not in ("izquierda", "derecha", "ambos"):
            return None, False
        frame = int(round(seg * fps))
        nearest = min(known, key=lambda f: abs(f - frame))
        if abs(nearest - frame) > 2 * fps:
            return None, quien == "ambos"
        row = seen[nearest]
        if quien == "derecha":
            return row[-1][1], False
        return row[0][1], quien == "ambos"

    return who


# Un momento del modelo se corre al gesto que detectó nuestro análisis (que mira todos los
# fotogramas) si está a menos de esto; si no hay gesto, al golpe de la música más cercano.
SNAP_S = 0.3
SNAP_BEAT_S = 0.15
# Gestos rápidos por segundo y por persona (del análisis económico) que piden más fotogramas:
# video_34 y michael_jackson_dance ~2,4 → 5 fps; dance_two_mens 4,3 y video_35 4,6 → 8; las
# peleas y el ninja acróbata (5 a 7,8) → 10.
FAST_EVENTS = {"fast_swing", "impact", "stomp", "step", "foot_strike", "spin_body", "turn", "jump", "frenzy", "lunge", "throw", "landing"}
FPS_STEPS = ((2.5, 5.0), (5.0, 8.0))


def choose_fps(brief, cfg: DeepConfig) -> float:
    """Fotogramas por segundo para el modelo: los de la configuración o, sin ellos, según lo
    rápido que es el baile; nunca más de frame_budget en todo el video."""
    duration = brief.video.frame_count / (brief.video.fps or 30.0)
    if cfg.fps:
        fps = cfg.fps
    else:
        people = max(len(brief.people or [brief.person_id]), 1)
        rate = sum(1 for e in brief.events if e.name in FAST_EVENTS) / max(duration, 1e-6) / people
        fps = next((value for limit, value in FPS_STEPS if rate < limit), cfg.fps_max)
        fps = min(max(fps, cfg.fps_min), cfg.fps_max)
    if duration > 0 and fps * duration > cfg.frame_budget:
        fps = max(cfg.frame_budget / duration, 1.0)
    return round(fps, 1)


def snapper(brief) -> Callable[[float, str], float]:
    """snap(seg, acción): el instante exacto del gesto de esa acción que detectó el análisis cerca
    (mira todos los fotogramas, el modelo solo unos pocos por segundo); si no hay, el golpe de la
    música más cercano; si tampoco, el mismo segundo."""
    fps = brief.video.fps or 30.0
    starts: dict[str, list[float]] = {}
    for event in brief.events:
        starts.setdefault(event.name, []).append(event.start_frame / fps)
    beats = [frame / fps for frame in brief.audio_onsets]

    def snap(seg: float, action: str) -> float:
        near = [s for s in starts.get(action, []) if abs(s - seg) <= SNAP_S]
        if near:
            return min(near, key=lambda s: abs(s - seg))
        near = [s for s in beats if abs(s - seg) <= SNAP_BEAT_S]
        return min(near, key=lambda s: abs(s - seg)) if near else seg

    return snap


# Gestos que nuestro análisis distingue mejor que el modelo (mira los dedos en todos los
# fotogramas): si el modelo pide la acción general y el análisis vio la concreta en ese instante,
# va la concreta (dance_two_mens, seg. 7: Argon puso "señalar" donde la mano hace un revólver).
UPGRADES = {"point": ("finger_gun", "revolver")}


def upgrader(brief) -> Callable[[float, str], tuple[str, str] | None]:
    fps = brief.video.fps or 30.0
    spans: dict[str, list[tuple[float, float]]] = {}
    for event in brief.events:
        spans.setdefault(event.name, []).append((event.start_frame / fps, event.end_frame / fps))

    def upgrade(seg: float, action: str) -> tuple[str, str] | None:
        if action not in UPGRADES:
            return None
        name, option = UPGRADES[action]
        hit = any(start - SNAP_S <= seg <= end for start, end in spans.get(name, []))
        return (name, option) if hit else None

    return upgrade


def answer_key(video_sha: str, prompt: str, cfg: DeepConfig) -> str:
    return hashlib.sha256(f"{video_sha}|{cfg.model}|{cfg.fps}|{prompt}".encode()).hexdigest()[:20]


def deep_pins(video: Path, video_sha: str, catalog, duration: float, cfg: DeepConfig, out_dir: Path, who=None, brief=None) -> Path:
    """Guion del análisis profundo en `out_dir` (deep_guion.yaml), con la lectura completa al
    lado (deep_lectura.json). La respuesta del modelo se guarda en caché por video y prompt."""
    from vfxglow.director.pins import save_pins

    prompt = build_prompt(catalog, duration)
    if brief is not None:
        cfg = cfg.model_copy(update={"fps": choose_fps(brief, cfg)})
    elif not cfg.fps:
        cfg = cfg.model_copy(update={"fps": cfg.fps_min})
    key = answer_key(video_sha, prompt, cfg)
    cache = out_dir / "deep_cache" / f"{key}.json"
    if cache.exists():
        answer = json.loads(cache.read_text(encoding="utf-8"))
        log.info("Análisis profundo en caché (%s)", cfg.model)
    else:
        log.info("Análisis profundo con %s a %s fotogramas por segundo: subiendo el video completo (puede tardar unos minutos)", cfg.model, cfg.fps)
        answer, usage, model = ask_gemini(video, prompt, cfg)
        log.info(
            "Análisis profundo listo con %s: %s tokens de entrada, %s de salida",
            model,
            usage.get("promptTokenCount", "?"),
            usage.get("candidatesTokenCount", "?"),
        )
        # La respuesta se guarda bajo el modelo que de verdad contestó: así el respaldo no queda
        # como si fuera Argon, y la próxima vez Argon vuelve a intentarse primero.
        cache = out_dir / "deep_cache" / f"{answer_key(video_sha, prompt, cfg.model_copy(update={'model': model}))}.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(answer, ensure_ascii=False, indent=1), encoding="utf-8")
    pins, warnings = to_pins(
        answer,
        catalog,
        duration,
        fill=cfg.fill,
        who=who,
        snap=snapper(brief) if brief is not None else None,
        upgrade=upgrader(brief) if brief is not None else None,
    )
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
