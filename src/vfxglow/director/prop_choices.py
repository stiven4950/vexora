"""El objeto protagonista que elige el cliente en los estilos que lo siguen (`needs: [props]`).

Grounding DINO lo busca por una descripción en inglés y SAM 2 sigue su contorno, sea cual sea; los
efectos del objeto (contorno, estela, anillos) se dibujan sobre ese contorno. Lo único que depende
del tipo es si se puede poner en la cabeza (`wearable`): solo entonces existe el momento
"se lo pone" (prop_worn). Sin elección, el `prop` del catálogo (la gorra de Baile).
"""

from __future__ import annotations

from pydantic import BaseModel


class PropChoice(BaseModel):
    id: str
    title: str
    # Descripción en inglés para Grounding DINO, frases terminadas en punto. Vacía = sin objeto.
    query: str
    wearable: bool = False


PROP_CHOICES: dict[str, PropChoice] = {
    choice.id: choice
    for choice in (
        PropChoice(id="gorra", title="Gorra", query="a baseball cap. a hat.", wearable=True),
        PropChoice(id="sombrero", title="Sombrero", query="a hat.", wearable=True),
        PropChoice(id="gafas", title="Gafas", query="sunglasses. glasses.", wearable=True),
        PropChoice(id="balon", title="Balón", query="a ball."),
        PropChoice(id="abanico", title="Abanico", query="a hand fan."),
        PropChoice(id="microfono", title="Micrófono", query="a microphone."),
        PropChoice(id="baston", title="Bastón", query="a stick. a cane."),
        PropChoice(id="panuelo", title="Pañuelo", query="a scarf. a handkerchief."),
        PropChoice(id="botella", title="Botella", query="a bottle."),
        PropChoice(id="telefono", title="Teléfono", query="a cell phone."),
        PropChoice(id="ninguno", title="Ninguno", query=""),
    )
}


def check(prop: str | None) -> None:
    if prop is not None and prop not in PROP_CHOICES:
        raise ValueError(f"Objeto no válido: {prop}")
