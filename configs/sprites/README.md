# Sprites (`sprite_fx`)

Efectos diseñados en otra herramienta (After Effects, Blender, EmberGen, Unreal...) que el
motor coloca donde y cuando la coreografía lo pide. Cada sprite es uno de estos:

- **Carpeta con secuencia de PNG** con transparencia (`0001.png`, `0002.png`...). Es lo
  recomendado: alfa exacto.
- **Un PNG suelto** (una figura fija que aparece y se desvanece).
- **Un video** (`.mp4`, `.mov`, `.webm`). Si no trae canal alfa, el negro se vuelve
  transparente y la luz se suma: sirve para partículas sobre fondo negro.

Consejos de exportación:

- Fondo transparente (o negro puro si es video).
- El efecto centrado en el cuadro: el centro del cuadro es el que se pega al punto del evento
  (la mano, el impacto). Si el efecto tiene una dirección, que apunte hacia la derecha (0°), así
  `orient` lo gira hacia donde va el movimiento.
- Cuadrado y de hasta 512 px de lado (el motor los achica a 512 en memoria).
- 24-30 fps; la velocidad se ajusta con `sprite_fps`.

Uso en un catálogo:

```yaml
- action: throw
  options:
  - name: estallido
    weight: 1.0
    effects:
    - type: sprite_fx
      target: {kind: event_point, id: impact}
      style: {sprite: demo_burst, size: 1.2, sprite_fps: 30, hdr_gain: 1.4, shapes: [orient]}
      trigger: {anchor: end, hold: 16, fade_in: 0, fade_out: 4}
```

Formas (`style.shapes`): `loop` (repite la animación mientras dure), `orient` (gira hacia la
dirección del evento) y `tint` (lo tiñe con el color del capítulo). `size` = alto del sprite en
torsos.

`demo_burst/` es un estallido de ejemplo generado por código para probar el motor.
