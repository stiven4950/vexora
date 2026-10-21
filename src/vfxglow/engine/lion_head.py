"""Cabeza de león estilizada (tribal), la misma para el león de fuego (Avatar) y el de neón (baile).

Copiada de una cabeza de león tribal de referencia: simétrica, con la melena en mechones que
barren hacia afuera y abajo con la punta en gancho, separados por ranuras; el copete en la
coronilla, orejas enroscadas, ceño en cuña sobre ojos rasgados, la nariz ancha con su puente y la
barba en escudo con la muesca de los dientes. Lo "en tinta" (lo negro de la referencia) son las
piezas que se devuelven; la cara es el espacio que queda entre ellas.

Coordenadas normalizadas: el centro de la nariz en (0, 0), `x` hacia la derecha de la imagen, `y`
hacia arriba, en radios de cara (la cara mide ~1,8 de ancho y la cabeza entera ~4,4).
"""

from __future__ import annotations

import numpy as np


def _bezier(p: np.ndarray, n: int) -> np.ndarray:
    """Curva de Bézier cúbica por los 4 puntos de control `p`, en `n` puntos."""
    t = np.linspace(0.0, 1.0, n)[:, None]
    return (1 - t) ** 3 * p[0] + 3 * (1 - t) ** 2 * t * p[1] + 3 * (1 - t) * t ** 2 * p[2] + t ** 3 * p[3]


def _outline(spine: np.ndarray, widths: np.ndarray) -> np.ndarray:
    """Polígono de una espina con su ancho (medio) en cada punto."""
    d = np.gradient(spine, axis=0)
    d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
    n = np.stack([-d[:, 1], d[:, 0]], axis=1)
    return np.vstack([spine + n * widths[:, None], (spine - n * widths[:, None])[::-1]])


def _tuft_parts(root, c1, c2, tip, width: float, n: int = 22) -> tuple[np.ndarray, np.ndarray]:
    spine = _bezier(np.array([root, c1, c2, tip], np.float64), n)
    s = np.linspace(0.0, 1.0, n)
    profile = np.sin(np.clip(s * 2.2, 0.0, 1.0) * np.pi / 2) ** 0.5 * (1.0 - s) ** 0.75  # panza a un tercio, punta fina
    return spine, width * profile + 0.004


def tuft(root, c1, c2, tip, width: float, n: int = 22) -> np.ndarray:
    """Un mechón: ancho en la raíz y en punta afilada, por la curva root-c1-c2-tip."""
    return _outline(*_tuft_parts(root, c1, c2, tip, width, n))


def _slit(root, c1, c2, tip, width: float, n: int = 22) -> np.ndarray:
    """La ranura del mechón: una línea fina sobre su borde de abajo (lo separa del de abajo, como
    el blanco entre mechones de la referencia)."""
    spine, widths = _tuft_parts(root, c1, c2, tip, width, n)
    d = np.gradient(spine, axis=0)
    d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
    normal = np.stack([-d[:, 1], d[:, 0]], axis=1)
    if float(normal[:, 1].mean()) > 0:  # el borde de abajo
        normal = -normal
    edge = spine + normal * widths[:, None]
    q = np.linspace(0.0, 1.0, n)
    return _outline(edge, SLIT * np.sin(np.pi * np.clip(q * 1.1, 0, 1)) ** 0.5 + 0.002)


def _mirror(poly: np.ndarray) -> np.ndarray:
    return poly * np.array([-1.0, 1.0])


SLIT = 0.035  # medio ancho de las ranuras blancas entre mechones
MANE_BODY = 2.1  # grosor de los mechones (en la referencia la melena es casi una masa con ranuras)

# Media cabeza (el lado derecho de la imagen): (raíz, control 1, control 2, punta, ancho). Medido
# sobre la referencia con la nariz en el centro y 100 px por unidad.
_MANE = [
    # Copete: el de arriba al costado del central, barriendo hacia afuera.
    ((0.25, 1.25), (0.55, 1.75), (1.05, 1.95), (1.35, 1.8), 0.16),
    ((0.55, 1.15), (1.05, 1.5), (1.55, 1.55), (1.85, 1.25), 0.15),
    # La melena del costado, de arriba hacia abajo: cada vez más larga y más caída.
    ((1.0, 0.95), (1.6, 1.15), (2.05, 0.85), (2.2, 0.45), 0.17),
    ((1.05, 0.55), (1.65, 0.55), (2.05, 0.05), (2.15, -0.45), 0.18),
    ((1.0, 0.1), (1.55, -0.05), (1.85, -0.6), (1.85, -1.1), 0.17),
    ((0.9, -0.35), (1.35, -0.55), (1.5, -1.1), (1.35, -1.6), 0.15),
    ((0.75, -0.75), (1.05, -1.0), (1.0, -1.5), (0.75, -1.85), 0.12),
    # Mechones finos entre la melena y la cara (las ranuras blancas quedan entre ellos).
    ((0.9, 0.75), (1.25, 0.75), (1.45, 0.45), (1.5, 0.1), 0.07),
    ((0.82, -0.1), (1.1, -0.3), (1.2, -0.65), (1.1, -1.0), 0.06),
]
# El mechón central del copete: alto, en S.
_CROWN = ((0.0, 1.15), (0.2, 1.6), (-0.25, 1.95), (-0.05, 2.3), 0.17)
# La oreja: un gancho que se enrosca hacia adentro, dentro de la melena.
_EAR = ((0.75, 1.0), (0.85, 1.5), (1.3, 1.45), (1.15, 1.15), 0.09)


def _brow() -> np.ndarray:
    """Ceño derecho: una cuña que baja de afuera hacia la nariz, gruesa adentro."""
    return tuft((0.12, 0.55), (0.35, 0.98), (0.72, 0.98), (0.98, 0.7), 0.16, 18)


def _eye() -> np.ndarray:
    """Ojo derecho: almendra fina y rasgada, inclinada hacia afuera."""
    t = np.linspace(0, np.pi, 14)
    top = np.stack([0.3 + 0.42 * (1 - np.cos(t)) / 2, 0.42 + 0.06 * np.sin(t) + 0.12 * (1 - np.cos(t)) / 2], axis=1)
    bottom = np.stack([0.3 + 0.42 * (1 - np.cos(t)) / 2, 0.42 - 0.03 * np.sin(t) + 0.12 * (1 - np.cos(t)) / 2], axis=1)
    return np.vstack([top, bottom[::-1]])


def _nose() -> np.ndarray:
    """La almohadilla de la nariz: triángulo redondeado ancho, con las fosas hacia abajo."""
    t = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    x = 0.32 * np.sin(t)
    y = 0.02 + 0.13 * np.cos(t) - 0.08 * np.cos(2 * t) * (np.cos(t) < 0)
    return np.stack([x, y], axis=1)


def _bridge() -> np.ndarray:
    """Línea derecha del puente de la nariz, de entre los ojos hasta la almohadilla."""
    return tuft((0.1, 0.62), (0.13, 0.45), (0.22, 0.3), (0.3, 0.1), 0.035, 14)


def _philtrum() -> np.ndarray:
    """La línea corta que baja de la nariz a la boca."""
    return tuft((0.0, -0.08), (0.01, -0.2), (0.0, -0.32), (0.0, -0.45), 0.04, 10)


def _beard() -> np.ndarray:
    """La barba: una masa redondeada bajo la boca que termina en punta, con el borde de arriba en
    arco (la boca)."""
    right = _bezier(np.array([(0.0, -0.62), (0.45, -0.5), (0.8, -0.75), (0.72, -1.2)]), 14)
    down = _bezier(np.array([(0.72, -1.2), (0.62, -1.62), (0.14, -1.85), (0.0, -2.18)]), 14)
    half = np.vstack([right, down[1:]])
    return np.vstack([half, _mirror(half[::-1])[1:-1]])


def _chin(open_: float) -> np.ndarray:
    """El mechón blanco del mentón que se mete en la barba: un abanico de tres puntas hacia abajo.
    Al rugir baja (la boca se abre)."""
    drop = 0.25 * open_
    xs = np.array([-0.42, -0.28, -0.16, 0.0, 0.16, 0.28, 0.42])
    ys = np.array([-0.6, -0.92, -0.78, -1.08, -0.78, -0.92, -0.6]) - drop * np.array([0.3, 1, 0.8, 1, 0.8, 1, 0.3])
    tips = np.stack([xs, ys], axis=1)
    arc = np.stack([np.linspace(0.42, -0.42, 9), -0.6 + 0.08 * np.sin(np.linspace(0, np.pi, 9))], axis=1)
    return np.vstack([tips, arc[1:-1]])


def lion_head(open_mouth: float = 0.0, sway: np.ndarray | None = None) -> dict[str, list[np.ndarray]]:
    """Las piezas en tinta de la cabeza, en coordenadas normalizadas.

    - `mane`: los mechones (con el copete y las orejas), del centro hacia afuera.
    - `features`: ceño, puente, nariz y la línea a la boca.
    - `eyes`: los ojos (el león de neón los omite: quedan los de la persona).
    - `beard`: la barba.

    - `slits`: las ranuras entre mechones y alrededor de las orejas: se recortan de la tinta.
    - `chin`: el mechón blanco del mentón: se recorta de la barba.

    `sway`: desplazamiento de la punta de cada mechón del lado derecho (el izquierdo lo espeja),
    para que la melena se mezca. `open_mouth` (0-1) abre la boca al rugir."""
    specs = [_CROWN, *_MANE]
    sway = np.zeros((len(specs), 2)) if sway is None else sway
    mane, slits = [], []
    for k, (root, c1, c2, tip, width) in enumerate(specs):
        s = sway[k]
        spec = (root, c1, np.asarray(c2) + s * 0.5, np.asarray(tip) + s, width * MANE_BODY)
        right, cut = tuft(*spec), _slit(*spec)
        mane.append(right)
        slits.append(cut)
        if k > 0:  # el central no se espeja (va en el medio)
            mane.append(_mirror(right))
            slits.append(_mirror(cut))
    ear = tuft(*_EAR[:4], _EAR[4] * MANE_BODY)
    ring = _outline(_bezier(np.array(_EAR[:4], np.float64), 22), np.full(22, _EAR[4] * MANE_BODY + SLIT * 2))
    mane += [ear, _mirror(ear)]
    slits += [ring, _mirror(ring)]  # la oreja se separa de la melena por un borde blanco
    features = []
    for piece in (_brow(), _bridge()):
        features += [piece, _mirror(piece)]
    eye = _eye()
    features += [_nose(), _philtrum()]
    return {"mane": mane, "slits": slits, "features": features, "eyes": [eye, _mirror(eye)], "beard": [_beard()], "chin": [_chin(open_mouth)]}


def place(piece: np.ndarray, center: np.ndarray, r: float, up: np.ndarray, across: np.ndarray) -> np.ndarray:
    """La pieza normalizada en la imagen: centrada en la nariz, `r` píxeles por unidad."""
    return center + np.outer(piece[:, 0] * r, across) + np.outer(piece[:, 1] * r, up)


def ink_steps(parts: dict[str, list[np.ndarray]]) -> list[tuple[np.ndarray, bool]]:
    """El orden de dibujo: (polígono, True = tinta / False = recorte). La melena, sus ranuras
    recortadas, las orejas encima, los rasgos y la barba, y el mechón del mentón recortado."""
    ears = parts["mane"][-2:]
    return (
        [(p, True) for p in parts["mane"][:-2]]
        + [(p, False) for p in parts["slits"]]
        + [(p, True) for p in ears + parts["features"] + parts["eyes"] + parts["beard"]]
        + [(p, False) for p in parts["chin"]]
    )
