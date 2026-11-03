# Estilos para el rostro: estado y plan (para retomar en una sesión nueva)

Nota escrita el 2026-10-30 para no tener que reconstruir el contexto. Leer esto primero y luego solo
los archivos que la tarea pida.

## Contexto en una línea

vfxglow (Vexora) dibuja efectos glowing sobre videos. Además de baile y peleas, ahora hay una línea
de **efectos para el rostro**: el catálogo `cara` y un **modo Halloween** con rostros de terror en
neón sacados de una cuadrícula de 24 personajes, ya todos hechos. Además hay bichos que caminan por
la cara, heridas de luz, besos lanzados, caras de impresión, ráfagas con la mirada, balacas de
serpientes, cachos, guadaña, esqueletos y hadas.

## Reglas que dio el usuario (no romperlas)

- Solo efectos glowing: luz sobre la persona real; nada de deformar la cara, filtros de belleza ni
  caricaturas de cuerpo entero.
- En `cara`, **un solo efecto principal a la vez sobre el rostro** (`one_at_a_time: true` en el
  catálogo). Con él puede ir **uno periférico** (alrededor de la cabeza, sin tapar ojos ni boca); con
  un efecto que cubre toda la cara, nada (`coverage` en `engine/face_zone.py`, decidido el
  2026-11-02). La capa de ambiente va fuera de la cara y puede coincidir con él (acción `ambient`).
- No buscar figuras sueltas en ropa u objetos para colorearlas: da formas al azar. Se trabaja con zonas
  completas (ropa, pelo, fondo).
- La ropa se ilumina de paso, sin rellenarla de color plano: la onda conserva el tejido.
- Preferir **partículas que salen del rostro o lo rodean** (pesan más en el catálogo que los dibujos
  de líneas).
- Con un **rostro especial** puesto (máscara de terror) no va nada más sobre la cara: la coreografía
  rechaza esas opciones y el motor apaga las que ya estaban (`engine/face_zone.py`).
- Las máscaras se arman rápido (~0,8 s), la luz corre por sus líneas "como agua por una zanja" (no
  giran las figuras) y al irse se sueltan en polvo fino con figuritas diminutas, con mucha expansión
  y fluido (~1,1 s, `engine/dissolve.py`). Por eso duran ~2,4 s y no 1,5.
- Bichos que caminan: efectos largos (~5 s), como los filtros de Instagram. Heridas: solo luz.
- En `baile` los efectos de cara son cortos; en `cara` pueden durar más.
- ~40% de los cambios de efecto se transforman del dibujo anterior al nuevo (continuidad), pero solo
  si el anterior ya terminó.
- Lo delgado o pequeño, con poco halo. Tareas mecánicas a subagentes con modelo barato.

## Qué existe

| Pieza | Dónde |
| --- | --- |
| Expresiones y orientación de la cabeza (MediaPipe blendshapes) → eventos `mouth_open`, `blink`, `wink`, `eyes_wide`, `smile`, `brows_up`, `cheeks_puff`, `pucker`, `head_turn`, `head_tilt` | `analysis/expressions.py`, `analysis/mediapipe_backend.py` |
| Trazo de maquillaje → evento `paint_stroke` (figura + zona) | `analysis/appearance.py` |
| ~23 dibujos de cara (delineado, malla, cristal, runas, ojos, boca, partículas `face_emanate`, `face_swirl`, `face_sparkle_rain`, `eye_sparks`) | `engine/face_glow.py` |
| Catálogo `cara` (alias de los viejos presets `face_neon` y `face_runes`) | `configs/catalogs/cara.yaml`, doc `docs/referencias/cara.md` |
| Cuadrícula de 24 rostros neón (fuente) y su índice (n, id, nombre) | `assets/masks/source/halloween_grid.png` y `.yaml` |
| Herramienta: celda de la cuadrícula → trazos vectoriales con rol, en coordenadas de cara. Los rasgos salen de `marks` en el índice (leídos a mano); el detector de huecos solo sirve para Ghostface | `tools/mask_from_grid.py --cell N` → `assets/masks/<id>.yaml` |
| Bichos: arañas, hormigas, ciempiés, cucarachas | `engine/face_creatures.py` |
| Heridas: zarpazo, cicatriz cosida, grietas | `engine/face_wounds.py` |
| Beso lanzado, impresión (ojos y líneas de impacto), ráfaga de la mirada | `engine/face_moods.py` |
| Balaca y corona de serpientes, cachos rojos, gancho de la muerte, esqueletos, hadas | `engine/head_beasts.py` |
| Desintegración en polvo (máscaras y dibujos de cara) | `engine/dissolve.py` |
| Eventos `surprise`, `speaking` y `gaze_shift` (la mirada usa las expresiones `eyeLook*`) | `analysis/expressions.py` |
| Volumen por fotograma (`FrameRecord.voice`) | `analysis/voice.py` |
| El cuervo: silueta que se transforma entre vuelo y posado, aterrizaje sobre el contorno del hombro | `engine/raven.py` |
| Colores de las máscaras: `MASK_PALETTES` (cerca de la mitad, de un solo color: `MONO`), se sortea una por aparición | `engine/horror_masks.py` |
| Efectos que responden por grados: aliento de dragón, pulso sónico, marioneta, cuervo, sellos en los ojos | `engine/living_fx.py` |
| Señales por grados en el motor: `runtime.voice`, `runtime.head_pose`, `runtime.energy` (además de `runtime.expressions`) | `engine/bodyglow.py` |
| Máscara viva `terror_<id>` (se ajusta por los ojos, grita con `jawOpen`, parpadea, luz que fluye, salida en figuras de Halloween) | `engine/horror_masks.py` |
| Halloween: la máscara como momento de temporada | `configs/seasons.yaml` (halloween → moments), `director/seasons.py` |
| Qué es cada píxel (fondo, pelo, piel, cara, prenda), solo si el guion lo pide; PNG por fotograma en `analysis/regions/` | `analysis/regions.py`, `Pipeline._engine` |
| Ambiente alrededor de la persona: portal detrás de la cabeza, aro, onda en la prenda (sin prenda, un aro) | `engine/ambient_fx.py`, `ambient_every_s` en el catálogo, `ambient_events` en `director/choreography.py` |
| Agujeros negros: `black_holes`, centro negro real (`blend: over`), en el fondo libre, se tragan polvo de luz | `engine/ambient_fx.py` |
| Ojos de Cleopatra: delineado, ojo de Horus y diadema en oro; llamas desde el rabillo, que se contraen al parpadear | `engine/cleopatra.py` |
| Fantasma: `behind_ghost`, asoma detrás del hombro y cambia de lado si la cabeza gira hacia él | `engine/ambient_fx.py` |
| Cabello de energía: `hair_energy`, mechones desde el borde real del pelo que se atrasan al mover la cabeza | `engine/ambient_fx.py` |
| Ojos de hielo: iris azul, grietas finas, escarcha y cristales al parpadear | `engine/ice_eyes.py` |
| Mini yo: copia diminuta de la malla facial que repite los gestos | `engine/hologram.py` |
| Ojos láser con carga: `laser_eyes` y el evento `frown` | `engine/living_fx.py`, `analysis/expressions.py` |
| Símbolos por emoción alrededor de la cabeza (corazones, estrellas, rayos): `emotion_burst` | `engine/face_moods.py` |
| Señales de la cara comunes: niveles suavizados, flancos (parpadeo, abrir los ojos, guiño, boca), mirada, giro de la cabeza, mirada fija y cara relajada | `engine/face_signals.py` |
| Familia de ojos: base común (iris, párpado, cuatro fases, reacciones por señal) y seis variantes con personalidad (`eyes_fire`, `eyes_galaxy`, `eyes_storm`, `eyes_void`, `eyes_feline`, `eyes_scanner`); perillas de variación por aparición con semilla (`style.variants`) | `engine/eye_family.py` |
| Cobertura de la cara (peripheral, low, medium, high) y quién convive con quién | `engine/face_zone.py`, `director/choreography.py` |
| Opciones de motor nuevas: `keep_on_cut` (sigue tras un corte de toma), `one_at_a_time` y `moment_scale` en el catálogo | `director/schema.py`, `director/choreography.py`, `engine/engine.py` |

Video de prueba: `api_data/uploads/3c00dd033c/facil_1.mp4` (la API que corre el usuario mueve las
subidas; si no está, buscar `facil_1.mp4` en `api_data/uploads/`). Resultado:
`runs/facil_1-34ec1af4/output/cara__halloween.mp4`.

    vfxglow run --video api_data/uploads/3c00dd033c/facil_1.mp4 --catalog cara --season halloween

## Siguiente paso (plan)

Las mejoras de cara neón propuestas el 2026-11-02 van por entregas. La 1 (señales comunes, familia de
ojos, variaciones y cobertura) está hecha. Las siguientes, en orden:

- Entrega 2 (hecha): `ice_eyes` y `eye_curse` leen `face_signals`; Cleopatra y el láser conservan su
  lectura propia (es su personalidad). Símbolos (`engine/face_symbols.py`), maquillaje de luz sacado de
  referencias del usuario (`engine/face_makeup.py`, incluida la desintegración facial) y criaturas
  periféricas (`engine/head_companions.py`, con Medusa). Criterio del usuario: dibujos profesionales,
  no infantiles; tomar sus referencias de maquillaje real como guía de forma.
- Entrega 3 (hecha): la continuidad empareja cada línea con la más cercana del dibujo nuevo
  (`morph.match_lines`, se recorre al revés si viaja menos), cada línea pasa de su color al de su
  pareja, dura ~0,35 s a cualquier fps, suelta chispas mientras se convierte y solo une dibujos de la
  misma zona (cabeza o cuerpo). Los efectos de línea fina devuelven (curva, color, ancho) y el motor
  los pinta: así también se transforman. Como el que sale ya se suelta en polvo, el nuevo nace de esos
  fragmentos (el "reensamblar desde el polvo").
- Entrega 4: porcelana fracturada (variante de `face_cracks`).

Además:

1. Que el usuario vea el render y diga qué ajustar.
2. Cuando llegue un video de referencia de cara con efectos glowing: analizarlo como los de baile
   (`docs/criterio_de_analisis.md`) y calibrar tiempos y formas.
3. Falta probar en video real lo que `facil_1` no tiene: boca abierta y cara de impresión.

Para revisar efectos sin renderizar todo, dibujarlos sobre fotogramas reales con `EffectEngine` y un
evento sintético (como `tools/preview.py`); los tramos de frente de `facil_1` empiezan en los
fotogramas 2 y 470.

## Calibración con `expressions_1.mp4` (video de gestos, 14,9 fps)

| Señal | Qué se midió | Decisión |
| --- | --- | --- |
| `eyeWide*` | Ojos muy abiertos: 0,14; máximo 0,27 | `eyes_wide` pasa de 0,35 fijo a 0,12 sobre lo habitual |
| Asombro | Boca muy abierta con cejas casi quietas | `surprise` también con la boca bien abierta y sostenida |
| `eyeSquint*` | 0,18 al asombrarse, 0,45 al gritar con dientes | Cara tensa: ni asombro ni beso |
| `mouthPucker` | 0,9 también al hablar con labios redondos | El beso exige boca casi cerrada |
| `cheekPuff` | Máximo 0,002: MediaPipe casi no lo mide | `cheeks_puff` rara vez sale; la llamarada también arranca con labios fruncidos |
| Ancho de cara como medida de mejillas | Varía más por el ángulo que por el gesto | Descartado |
| 14,9 fps | Los efectos duraban el doble | `at_fps` (duraciones) y `paced`/`steps` (animación): todo a tiempo real |

Un grito sin ceño ni ojos entrecerrados (fotogramas 214-219) no se distingue del asombro.

## Efectos largos: lugar reservado

Con `one_at_a_time`, los momentos cortos ocupaban todo y los efectos de 4-5 s no salían (fantasma, hielo,
Cleopatra y mini yo: 0 de 40 semillas en `facial_3`). `look_every_s` reserva un lugar cada ~8 s, que se
reparte antes que todo y busca el tramo con menos gestos clave. Para medir: contar opciones elegidas con 40 semillas sobre el brief.

## Medición de la capa de ambiente (`facial_2`, `facial_3`)

Antes casi todo iba sobre la piel. La diferencia entre render y original, aproximada:

| Video | Fotogramas con efecto | Pantalla encendida | Hueco mayor |
| --- | --- | --- | --- |
| `facial_2` | de 76% a 80% | de 1,3% a 3,1% | de 1,9 s a 1,5 s |
| `facial_3` | de 81% a 92% | de 1,5% a 5,9% | de 1,3 s a menos de 1 s |

Lecciones de esos videos: el modelo parte una prenda entre "ropa" y "otros", deja manchas pegadas al
pelo y toma por ropa el logo de TikTok (`clean_labels`). En un primer plano no hay prenda: la onda se
vuelve un aro. Una mano rápida abre huecos en la máscara: la luz de la prenda se suaviza en el tiempo.

## Pendientes conocidos

- Cleopatra salió de una descripción del trend, sin video: al llegar uno, calibrar forma y tiempos. Va
  desde el rabillo y sigue la cabeza, no la mirada, porque la mirada salta entre cuadros.
- Agujeros sobre la cara: descartados con centro negro (parecen lunares o heridas). Solo se probaría un
  anillo de luz diminuto si los de alrededor convencen.
- La máscara `espectro` es igual a la de Scream: no usarla como dibujo genérico. El fantasma tiene su
  propia silueta.
- La onda solo se probó con un suéter liso, no con ropa estampada.
- Con la mano cerca de la cabeza el portal no reacciona todavía (idea original: ondas al acercarla).
- El evento `frown` está calibrado con `expressions_1` y `facial_3`; `facial_2` no frunce el ceño.
- Sin video de referencia de cara: tiempos y pesos calibrados a ojo sobre `facil_1`.
- `facil_1` no tiene boca abierta ni ojos muy abiertos: para eso usar `expressions_1.mp4`.
- Los análisis anteriores a octubre de 2026 no tienen malla facial (se borraba en `analysis/cast.py`)
  ni mirada: hay que reanalizar el video. Al cambiar el código de análisis eso ocurre solo.
- El gancho de la muerte entra desde un lado de la cabeza; no lo agarra la mano.
- Si la cara gira mucho, el lado de atrás se oculta por el ancho de los ojos; no hay oclusión 3D.
- Commits en `main` sin subir al cerrar esta sesión: subirlos cuando el usuario lo pida.
