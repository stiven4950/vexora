# VEXORA — Informe de producto y experiencia de usuario

Fecha del informe: 23 de octubre de 2026. Fuente: lectura del código y de los documentos del repositorio (`vfxglow/`), no de una versión desplegada.
Estado del producto: web `v1.0.0` en desarrollo local (React + FastAPI). No hay despliegue público ni modelo de negocio definido.

Convención: **[Hecho]** = existe en el código hoy. **[Propuesto]** = está en un documento de plan, pero no existe. **[No existe]** = se podría suponer que existe y no es así. Para analizar UX conviene no mezclarlos.

---

## 1. Qué es VEXORA (resumen de 30 segundos)

VEXORA (nombre de la marca; el motor y el repositorio se llaman *vfxglow*) toma un video de una persona o dos moviéndose (baile, pelea, espadas, artes marciales) y le dibuja encima efectos visuales de luz que reaccionan al movimiento: estelas de neón, fuego, rayos, agua, viento, rocas, corazones, rosas, máscaras, criaturas con historia.

Principios del producto:

- **El video original nunca se redibuja.** No es IA generativa de video. Los efectos son capas de luz dibujadas por un motor procedural y mezcladas encima. Cuando no hay efecto, el píxel es el original.
- **La IA entiende, el motor dibuja.** Un análisis de movimiento detecta gestos y eventos; un "coreógrafo" decide qué efecto dispara cada gesto; el motor lo dibuja anclado al cuerpo. Un LLM opcional (Gemini) puede "leer" el video como un animador.
- **Sin dados para el usuario.** El usuario no elige semillas ni parámetros técnicos. El sistema prueba 8 coreografías posibles, puntúa cada una y entrega la mejor; "Probar otra versión" entrega la siguiente mejor.
- **Corre sin GPU** (CPU / Apple Silicon). Como contrapartida, es lento: ~6 min para renderizar 28 s de video en CPU (dato de `docs/pendientes.md`).

---

## 2. Inventario de funcionalidades

### 2.1 Cuenta y acceso — [Hecho]

| Función | Detalle |
| --- | --- |
| Inicio de sesión | Correo + contraseña, Google, GitHub (Firebase Auth). |
| Registro | Correo + contraseña (mínimo 6 caracteres). Sin verificación de correo, sin nombre de usuario ni perfil. |
| Recuperar contraseña | Envía correo de Firebase. |
| "Recordarme" | Casilla marcada por defecto. Si se desmarca, la sesión dura lo que la pestaña. |
| Sesión | Se recupera sola al volver. Botón "Salir" en la barra superior, junto al avatar y nombre. |
| Aislamiento por usuario | Cada usuario ve solo sus trabajos; el de otro responde 404. Las URLs de video/miniatura llevan una llave firmada que caduca a las 6 h. |
| Migración | Los trabajos anteriores a las cuentas los adopta el correo configurado como `VEXORA_LEGACY_OWNER`. |
| Modo desarrollo | Sin configuración de Firebase la web **no pide login** y entra como usuario local. |
| Mensajes de error de login | En español, específicos (dominio no autorizado, contraseña incorrecta, demasiados intentos, etc.). |

Detalles de la pantalla de login: fondo fotográfico, a la izquierda la marca, el titular "Convierte tus videos en algo extraordinario" y tres beneficios ("Efectos automáticos", "Edición sin complicaciones", "Resultados profesionales"); a la derecha la tarjeta de acceso. Los enlaces del pie (Términos, Privacidad, Soporte) apuntan a anclas vacías (`#terminos`, etc.): **no hay páginas detrás**.

**[No existe]**: planes, cobros, cuotas por usuario, roles, edición de perfil, borrado de cuenta, verificación de correo, autenticación de dos factores.

### 2.2 Zona de estudio (`/`) — [Hecho]

Es una sola página larga con pasos numerados. Los pasos 03+ aparecen según lo elegido.

| Paso | Qué hace |
| --- | --- |
| Hero | Titular "Tu movimiento, más allá de lo real" y una frase explicando que el video original no se toca. |
| 01 · El plano | Zona de arrastrar y soltar (o clic) para un video: `.mp4 .mov .m4v .webm .mkv`, máximo 500 MB. Al cargarlo muestra vista previa en bucle, nombre, resolución, duración y peso, y un botón "Cambiar". Sin recorte ni selección de tramo. |
| 02 · El estilo | Tarjetas de **coreografías** (catálogos) con una vista previa animada en canvas con la paleta del estilo, título, descripción y etiquetas de las acciones que reconoce. Debajo, un botón plegable "Ver presets fijos (7)". La primera coreografía queda elegida por defecto. El fondo de la página (aurora) cambia al color del estilo elegido. |
| 03 · Toque de temporada (si hay temporadas) | Chips: Sin temporada, Halloween, Día de Muertos, Navidad, Año Nuevo, San Valentín. La temporada vigente aparece primero con la insignia "de temporada" y un texto que la sugiere. Cada chip muestra 4 muestras de color. |
| 04 · Fuego y rayo (solo si el estilo los dibuja: hoy, Avatar) | Dos filas de chips: look del fuego (Clásico/del estilo, Plano amarillo, Mixto, Azul espectral, Verde fantasmal, Pixel art) y look del rayo (del estilo, Blanco eléctrico, Violeta, Rojo carmesí, De fuego). "La coreografía es la misma: cambia el look." |
| 05 · Vestuario (solo catálogos) | Sin prendas / Chaquetas metaleras / Vestidos / Ambos. Texto: se puede refinar por persona después, en la página del video. |
| 06 · Análisis (solo catálogos) | **Económico** (reacciona a cada gesto detectado) vs **Profundo con IA** (una IA ve el video completo con su música, entiende la intención y arma metáforas con historia; "tarda unos minutos más y tiene costo"). |
| Barra de lanzamiento | Resumen "archivo / estilo" con puntos verde/gris, botón **"Revelar en neón"** (deshabilitado hasta tener video y estilo), barra de progreso de subida con porcentaje real. Errores de API o de subida en rojo bajo el botón. |

Notas de UX relevantes:

- El número de pasos cambia según el estilo (los pasos se renumeran dinámicamente).
- El botón siempre dice "Revelar en neón", incluso para Avatar (fuego) o Espadas fuego.
- El costo del análisis profundo se menciona pero **no se muestra cifra ni saldo**.
- No hay vista previa del resultado antes de gastar el render completo.
- Si la API no está levantada, se muestra un error técnico que menciona el comando `vfxglow-api`.

#### Catálogos ("coreografías") disponibles

| Estilo | Para qué video | Idea |
| --- | --- | --- |
| **Baile neón** (`baile`) | Una persona o dos bailando | Lo que más se mueve se enciende; ~48 efectos de "protagonista" más reacciones a gestos (§3.2). En pareja, cada una con su color y lo que hace una se copia en la otra cuando bailan igual. |
| **Pelea neón** (`pelea`) | Combate cuerpo a cuerpo de dos personas | Estelas de neón, llamaradas por golpe, estrellas, rayos desde la mirada, energía al chocar puños (§3.3). |
| **Avatar** (`avatar`) | Artes marciales, acrobacia, una persona | "Maestro fuego" con capítulos de los cuatro elementos y el rayo (§3.4). |
| **Espadas neón** (`espadas_neon`) | Una persona con espadas/bastones | Hojas pintadas de neón, ecos fantasma, arcos, siluetas en volteretas (§3.5). |
| **Espadas fuego** (`espadas_fuego`) | Una persona con katanas | Hojas encendidas en fuego, tajos con lenguas de fuego, humo de cómic (§3.5). |

Presets fijos (aplican siempre lo mismo, sin sorteo): Body Aura, Doodle Dance, Face Neon, Face Runes, Fight Comic, Neon Joints, Paint Reveal. Sus descripciones en la UI son genéricas ("Preset fijo: siempre los mismos efectos"), sin vista previa animada.

### 2.3 Procesamiento (`/jobs/:id` mientras corre) — [Hecho]

Pantalla "cuarto oscuro" (*Darkroom*):

- El video original desenfocado de fondo, en bucle.
- Anillo de progreso con porcentaje y mensaje de la etapa.
- Tres etapas con estado hecho / en curso / pendiente: **01 Lectura del movimiento** (pose, manos, cara, hojas y eventos), **02 Coreografía** (cada acción sortea su reacción visual), **03 Revelado** (capas de luz compuestas sobre el plano).
- Consola en vivo con las últimas 80 líneas del registro del pipeline (texto técnico, autodesplazable).
- Actualización por Server-Sent Events, con respaldo de sondeo cada 1,5 s.
- La cola procesa **un trabajo a la vez**. Estado "En cola" con "Esperando turno en la cola…".
- El progreso se *deduce* de mensajes de log (el análisis pesa ~55 % de la barra), por lo que puede avanzar a saltos.

**[No existe]**: cancelar un trabajo en cola o en curso; estimación de tiempo restante; notificación (correo, push) al terminar; poder cerrar la pestaña y que algo avise.

Si el servidor se reinicia a mitad de un trabajo, queda marcado como interrumpido.

### 2.4 Resultado (`/jobs/:id` al terminar) — [Hecho]

Dos columnas: visor a la izquierda, panel lateral a la derecha.

**Visor comparador (CompareViewer)**
- Antes/después con una **cortina arrastrable** (original a la izquierda, VEXORA a la derecha), con etiquetas "Original" y "VEXORA".
- Los dos videos van sincronizados (corrige desvíos > 1/15 s).
- Controles: reproducir/pausar, tiempo `mm:ss.d / total`, barra de progreso clicable.
- **Línea de tiempo con marcadores**: un punto de color por cada efecto que eligió la coreografía (el color depende del tipo de acción). Pasar el cursor muestra un tooltip (efecto, acción, tiempo); clic salta a ese momento.
- Atajos: **espacio** reproduce/pausa, **flechas** avanzan/retroceden un fotograma (1/30 s).
- La proporción del visor se adapta al video (vertical u horizontal), con tope de altura.

**Panel lateral**
1. **Exportar**: botón "Descargar MP4" y "Revelado en mm:ss". Es el **único formato** de salida. El audio original se conserva.
2. **¿Otra opción?** ("Probamos otra coreografía buena para el mismo video…"): selectores de Estilo, Temporada, Vestuario **por persona** (con un recorte de la cara/cuerpo de cada persona para reconocerla), Fuego, Rayo, Análisis (económico/profundo) y el botón **"Probar otra versión"**. No se vuelve a analizar el video (caché por hash), así que "tarda poco". Al lanzarse, **navega a un trabajo nuevo**.
3. **La coreografía** (plegada por defecto): "N efectos · M distintos", chips de filtro por efecto (8 visibles, "+N más"), y lista cronológica. Cada fila: tiempo, nombre del efecto, acción y persona, y —si se usó análisis profundo— una **nota con la intención** del gesto. Clic en una fila pausa el visor en ese cuadro y lo trae a la vista. La fila del momento en reproducción se resalta.

Cabecera: enlace "Biblioteca", etiqueta con estilo · versión ("mejor versión", "versión 2"…) · temporada · "análisis profundo" · looks de fuego/rayo; el nombre del archivo como título; insignia de estado (En cola / Procesando / Listo / Falló).

Estado **Falló**: icono de alerta, "El revelado falló", mensaje de error en tipografía mono y un desplegable "Ver registro" con el log técnico. **No hay botón de reintentar.**

**[No existe]** en el resultado: editar o quitar un efecto concreto de la coreografía; fijar un efecto en un segundo; ajustar intensidad; cambiar la duración; elegir calidad/resolución de exportación; compartir a redes; copiar enlace; marca de agua; versiones lado a lado; deshacer.

(La edición manual de momentos existe, pero solo por **línea de comandos** con un archivo YAML de "guion de prueba" — ver §4.4.)

### 2.5 Zona de librería (`/library`) — [Hecho]

- Título "Tus revelados" y botón "Nuevo revelado".
- **Cuadrícula plana** de todos los trabajos del usuario, del más reciente al más antiguo, con animación escalonada de entrada.
- Cada tarjeta: miniatura (primer fotograma del resultado), insignia de estado, barra de progreso si está procesando, nombre de archivo, estilo, número de versión (`v2`), "hace 5 min" / fecha, y botón de papelera.
- Borrar pide una confirmación nativa del navegador (`window.confirm`): "¿Borrar «archivo» (estilo)?". Es definitivo.
- Se refresca sola cada 4 s.
- Estado vacío: icono de película y "Aún no hay revelados. Sube tu primer plano en el estudio."

**[No existe]** — y esto es importante porque se mencionó "colecciones": la biblioteca **no tiene colecciones, carpetas, álbumes, etiquetas, favoritos, búsqueda, filtros ni ordenamiento**. Cada "otra versión" es una tarjeta independiente: aunque el trabajo guarda a su "padre" (`parent`), la UI **no agrupa las versiones de un mismo video**. Tampoco hay renombrar, descarga directa desde la tarjeta, selección múltiple, paginación ni indicador de espacio usado.
La palabra "colecciones" solo aplica, en el producto, a las **coreografías** del Estudio (§2.2) y a las temporadas.

### 2.6 Navegación global — [Hecho]

Barra superior fija: logo (a `/`), "Estudio", "Biblioteca", avatar + nombre + "Salir". Pie con el eslogan "Efectos visuales con IA · el plano original nunca se redibuja". Cualquier ruta desconocida redirige a `/`. Hay `@media` para pantallas ≤ 640 px y ≤ 980 px (se adapta, pero no hay una app móvil ni se ha probado móvil según el repositorio).

### 2.7 Nube, planes, compartir — [Propuesto]

`docs/plan_cuentas_y_nube.md` propone (nada de esto existe): Firestore por usuario; "biblioteca de análisis" para reprocesar sin repetir el análisis pagado; subir de nivel de análisis cobrando solo la diferencia; almacenamiento en Firebase Storage; compartir con `navigator.share`, enlace público `/v/{id}` y publicación directa a TikTok/Instagram/YouTube; planes `free`/`pro` con **marca de agua** (logo + `#VexoraFX` + placa final), límite de duración (60 s vs 300 s), análisis profundo y nube solo en pago. El estado actual es **un solo usuario local con los archivos en disco** (`api_data/`, `runs/`).

---

## 3. Qué hace el motor: análisis y efectos

### 3.1 Qué "ve" el sistema (análisis)

| Capacidad | Cómo | Estado |
| --- | --- | --- |
| **Detección de pose del cuerpo** | MediaPipe Pose, 33 puntos, hasta **2 personas** (`person_0`, `person_1`), con suavizado One Euro + Catmull-Rom. Hay un nivel `hq` opcional (YOLO11 + RTMW, 133 puntos). | Hecho |
| **Manos y cara** | MediaPipe Hands y Face (malla de 478 puntos). Si el seguimiento pierde una mano, la busca en un recorte alrededor de la muñeca. Si la cara está cubierta (pintura, máscara), cae a la silueta (Selfie Segmenter) y a un "brillo de ojo". | Hecho |
| **Cinemática** | Velocidad, dirección, trayectoria; descarta muestras con velocidad imposible (`glitch`). Flujo óptico (Farneback). | Hecho |
| **Eventos y gestos** | ~45 acciones (lista abajo). | Hecho |
| **Quién es el protagonista** | "Línea de atención": puntúa por fotograma qué parte del cuerpo/objeto es el foco (hay hasta un segundo foco), con histéresis para no parpadear. Los efectos de una región que no es protagonista se apagan con un fundido. | Hecho |
| **Solista, pareja o público** | `cast.py` deja solo a los protagonistas y descarta al público del fondo; decide si es solista o pareja. | Hecho |
| **Pareja: unísono vs. turnos** | Compara las dos poses (con tolerancia de retraso y espejo): si bailan igual, lo que se enciende en uno se copia al otro; si no, solo se enciende quien lleva el turno. | Hecho |
| **Detección de objetos** | YOLO11n opcional (gorra, botella, etc.); Grounding DINO + SAM 2 para el "objeto protagonista" (p. ej. una gorra que pasa de mano en mano) con contorno exacto — lento (~1,2 s/fotograma en MPS). YOLO-World y Grounding DINO para hojas se probaron y **no mejoraron** lo suficiente: no están integrados. | Parcial (opcional) |
| **Hojas (espadas, bastones, katanas)** | Detección clásica de líneas desde la mano (precisión medida: 99 % en bastones con fondo claro, 63 % en katanas plateadas con volteretas). Solo se activa en catálogos que lo piden. | Hecho, con límites |
| **Accesorios** | Un modelo de visión clasifica gafas, gafas de sol, máscara, gorra, diadema, capucha, aretes (una llamada por persona). Sin clave de API no clasifica. | Hecho (necesita clave) |
| **Análisis de escena** | Cortes de toma (PySceneDetect o histograma), golpes de la música (librosa o flujo espectral), y un lector de escena (`gpt-5-mini`) que describe cada tramo; si no hay clave, queda vacío. | Hecho (parcial sin clave) |
| **Tono de piel** | Se mide por persona para elegir colores de efecto que contrasten. | Hecho |
| **Pintura sobre la cara** | Detecta dónde aparece pintura nueva (maquillaje) y la obra terminada, para los presets de pintura. | Hecho |
| **Dirección de la mirada / frente-espalda** | Coherencia anatómica: ciertos dibujos (solapas, cierre de la chaqueta) no se dibujan si la persona está de espaldas. | Hecho |
| **Silueta por persona / segmentación SAM 2 / más de 2 personas / tipo de video automático / profundidad del piso** | — | **No existe / pendiente** (`docs/pendientes.md`) |

**Acciones que detecta** (agrupadas): movimiento (`fast_swing`, `impact`, `foot_strike`, `jump`, `flip`, `landing`, `tumble`, `turn`, `spin_body`, `step`, `stomp`, `still`, `frenzy`); manos y brazos (`raise_hand`, `arms_up`, `arms_open`, `arms_crossed`, `hand_open/closed`, `point`, `finger_gun`, `fist_up`, `hand_chin`, `hand_ear`, `cover_eyes`, `heart_hands`, `rock_hands`, `hands_on_head`, `arms_x`, `throw`, `neck_slash`, `lunge`); cara y objeto (`face_touch`, `tool_touch`, `held_object`, `object_contact`, `prop_transfer`, `prop_spin`, `prop_worn`); entre personas (`person_contact`, `strike_windup`, `strike_recoil`, `fist_clash`, `body_bump`); estructura (`entrance`, `lull`, `intent`, `intended_strike`, `beat`, `spotlight`); hojas (`blade_swing`, `blade_ground`).

### 3.2 Baile (solista o pareja)

La lógica: el análisis encuentra la parte que más se mueve en cada tramo (`spotlight`), y el coreógrafo sortea un efecto de ese tramo. Ningún tramo de más de 1 s queda sin efecto. Hay tres tipos de efecto:

- **De protagonista** (≈48 opciones sorteadas): tinte y línea de luz pegados a la silueta, abdominales o bíceps de neón; puntos en las rodillas, bandas en los tobillos, líneas que suben por la pierna; notas musicales y corazones; rosas (una rosa que nace como corazón y se abre), cintas de gimnasia rítmica con torsión y lazos, el "alma" de la cabeza que se queda atrás con el impulso y vuelve como liga; rayos en brazos/cuerpo/pies; discos y arcos 3D; cresta punk con gafas, casco tipo Iron Man, cuernos de diablo, antifaces; serpiente, abeja que esquiva la mano, yoyó, burbuja que revienta, luna, león; saco/chaqueta metalera con púas, vestido, corbata, zapatos de neón (tenis, botas, patines); huellas, rayos X, collar de estrellas, sombrero y cinturón.
- **Por gesto**: beso (mano en la cara → cara de caricatura con labios), corazón (manos en el pecho), señalar (señal o muñequito de palitos), brazos arriba (fiesta/cohete), mano al oído (ondas/corona), tapar ojos (antifaz), brazos abiertos (alas/ave/planeador/héroe/diosa/batería que llega a "100 %"), giro (torbellino/arcos), pisotón (globo que revienta / destello / arco en el piso), lanzamiento (energía / kamehameha), corte de cuello ("ya valió"), pistola con la mano (revólver de neón que dispara, con retroceso), puño arriba (monedas, arena, escarcha, reloj de arena), mano en el mentón (cuerno de guerra / pastel con cuchara), manos en la cabeza (diablo / ovni / cabeza que explota), brazos en X ("!"), cuernos de rock.
- **De escena**: discoteca (haces de luz), bola de espejos, ecualizador que salta con la música, pulso de la silueta con cada golpe musical, relevo y cierre.
- **Objeto protagonista**: si una gorra pasa de mano en mano, se le dibuja contorno y estela; al ponérsela hay un efecto propio.
- **Cierre**: en el último tramo todo lo dibujado se disipa en estrellas diminutas hasta que queda la persona sola.
- **Pareja**: cada persona lleva su color durante todo el video; al unísono los efectos se copian en espejo; en solos solo se enciende quien lo lleva.
- **Reglas anti-saturación**: ningún cuadro con más de 3 efectos a la vez; los efectos "exclusivos" (discoteca, bola de espejos…) no se pisan; nada compite con el protagonista; el color cambia por capítulo y contrasta con la piel.

### 3.3 Pelea

Dos personas (naranja fuego y azul eléctrico): estela y trayectoria de neón por cada golpe (con "pintura" y varias hebras), **llamarada** de pétalos y chispas al conectar, **estrellas** de cuatro puntas, descarga/colisión de dos colores al chocar hombros o puños, **rayos desde los ojos** hacia el rival cuando lanza un golpe mirándolo, **brazo musculoso** exagerado en golpes rectos, gafas que se encienden en las pausas entre rondas, runa en el pecho / rayos en el brazo / destellos cuando alguien "anuncia" un movimiento tras una pausa, y swoosh en cruz cuando el golpe sigue a esa intención. Detecta fases del golpe (carga → contacto → retroceso). Pendientes conocidos (no hechos): puños en llamas antes de golpear, rayos que recorren el brazo al agarrar, remolino de aturdimiento, onda elíptica al pisar, aura de guardia, llamas sobre las cabezas en tensión.

### 3.4 "Modo Avatar" (catálogo `avatar`)

No es un modo aparte de la app: es el catálogo **Avatar** (también el primero y el elegido por defecto en el Estudio). Idea: el cuerpo "controla" elementos como en la serie.

- Capítulos de ~3,5 s, cada uno de **un elemento** — fuego casi siempre (y al principio y al final), **rayo** donde lanza o señala, **aire** donde gira/salta/voltea, **agua** y **tierra**. Como mucho 2 "bestias" por video; ningún tramo de más de 1,2 s sin algo de fuego.
- **Estado Avatar** al entrar: marca en la frente y ojos encendidos; pared de fuego y pantalla teñida de naranja al final.
- **Fuego** (anime en capas: borde naranja, cuerpo amarillo, núcleo blanco): látigos con la forma exacta de la trayectoria del golpe, llamas en las manos, fuego a ras del piso, calavera de fuego, cuerpo en llamas, vela, puño en llamas; **bestias**: ave, dragón-serpiente, fénix, dragón lanzado, kitsune de nueve colas, león con melena y zarpazo, serpiente enroscada.
- **Aire**: cintas translúcidas finas, motas y distorsión del fondo ("refract") donde pasó el viento; remolinos, orbitas, estelas de aliento.
- **Agua**: cinta con física (Verlet), brillo en espiral, gotas, chorros, látigo de agua, esferas y anillos de agua, salpicaduras.
- **Tierra**: rocas facetadas con luz, grietas con ámbar, cristales de jade, puño de tierra, escudo, golpe al piso que parte el suelo (solo con la persona parada).
- **Rayo**: cinta quebrada con ramas y chispazos, hasta el borde del cuadro; al señalar, con pistola de dedos o en lanzamientos.
- Personalizable desde la UI: **look del fuego** (6) y **look del rayo** (5).
- Los efectos se apagan en los cortes de toma, y tras un efecto pesado hay relevo para que la escena no quede vacía.

### 3.5 Danza con espada / espadas

Dos catálogos, ambos requieren detección de hojas y están pensados para **una persona sola** con acrobacias:

- **Espadas neón**: hoja pintada en neón cian y verde lima (una por mano), copias fantasma ("eco") al moverla, arcos y arcos dobles en cada tajo, siluetas de neón en saltos y volteretas, rayas, salpicadura en abanico al aterrizar o al golpear el suelo.
- **Espadas fuego**: mirada magenta al empezar, hoja encendida, tajos con lenguas de fuego, bolas de fuego en las patadas, silueta en cada voltereta, raya en el piso, nube de humo de cómic enorme cuando la hoja golpea el suelo, brasas que sueltan las extremidades rápidas. Al final: calma, sin efectos.
- Límites medidos: con katanas plateadas sobre piso gris, hojas en escorzo o desenfoque de giro, la detección acierta solo ~63 %; ahí es donde más se nota que el tajo no aparece.

### 3.6 Otros ejes de personalización

- **Temporadas** (5): Halloween (murciélagos, telarañas, araña que baja, calabaza en la cabeza, fantasma al pisar), Día de Muertos (cempasúchil, calaveras con flores), Navidad (copos, esferas, gorro, estrella), Año Nuevo (estrellas, fuegos artificiales), San Valentín (corazones).
- **Vestuario por persona**: chaqueta metalera con púas, vestidos (de gala, coctel, volantes) o ambos; de espaldas se omiten solapas/cierre.
- **Análisis profundo con IA (Gemini)**: ve el video completo con audio; entiende intención ("quién", "por qué"), historia y letra de la canción; propone metáforas con historia; su respuesta fija los momentos principales (con color e intención) y el coreógrafo económico rellena alrededor. Si pide un efecto que no existe, se anota en `runs/efectos_propuestos.jsonl` y se usa un sustituto. Con 2 personas dice a quién va cada momento (izquierda/derecha/ambos). Reintenta ante saturación del servicio y cae a un modelo de respaldo. Costo del orden de dólares por video (estimación del plan, no medida). Cuesta tiempo y requiere una clave.
- **Director LLM (`--director openai|anthropic`)**: vía CLI. Dibuja trazos propios con validación.

### 3.7 Herramientas internas (no son UI)

`vfxglow` CLI (`run`, `analyze`, `direct`, `render`, `compose`, `pin-export`), guion de prueba YAML para **fijar** qué efecto sale en qué segundo, comparación cuadro a cuadro contra una referencia editada a mano (`tools/compare_reference.py`), pruebas de regresión por hash (`tools/snapshot.py`), 40 archivos de pruebas, sistema de entrenamiento de un detector de hojas propio, y un `graphify` de conocimiento del código. Hay 42 corridas en `runs/` y 87 trabajos registrados en `api_data/jobs.json` de uso interno.

---

## 4. Experiencia de usuario: descripción de todas las interacciones

### 4.1 Mapa de pantallas

```
Sin sesión ─▶ Login ──(entra)──▶ Estudio ──(Revelar)──▶ Trabajo (cola/procesando) ──▶ Trabajo (listo)
                                   ▲  ▲                                                   │  │
                                   │  └────────────────── "Probar otra versión" ◀─────────┘  │
                                   │                                                          │
                              Biblioteca ◀──────────────── "Biblioteca" (cabecera) ◀───────────┘
                           (tarjeta → Trabajo · papelera → borra)
```

Rutas: `/` Estudio · `/jobs/:id` Trabajo · `/library` Biblioteca · `*` → `/`. No hay rutas de ajustes, ayuda, cuenta ni precios.

### 4.2 Viaje principal, paso a paso

1. **Entrada.** El usuario abre la web. Si Firebase está configurado y no hay sesión, ve el login. Elige Google/GitHub (ventana emergente; en móviles que la bloquean, redirección) o correo. Tras entrar cae directo en el Estudio; no hay onboarding ni tutorial ni video de ejemplo.
2. **Subir el plano (01).** Arrastra o elige un video; ve su vista previa reproduciéndose en bucle con los datos técnicos. Solo valida el formato al soltar (si no es video, ignora el archivo en silencio); el tamaño máximo se valida **en el servidor al lanzar**, no al elegir.
3. **Elegir estilo (02).** Ve tarjetas con vista animada y etiquetas de acciones. Al elegir una, la página entera se tiñe con su paleta. Los presets están ocultos tras un enlace. No hay forma de saber qué estilo conviene a su video salvo leer las descripciones; el sistema **no recomienda** ni detecta el tipo de video (pendiente #2).
4. **Opciones opcionales (03–06).** Temporada, look de fuego/rayo (solo Avatar), vestuario y tipo de análisis. Aparecen/desaparecen según el estilo, con lo que el formulario "salta" de longitud. Nada se resume en un solo lugar salvo "archivo / estilo".
5. **Lanzar.** "Revelar en neón". Ve una barra de subida con porcentaje. Al terminar de subir navega a `/jobs/:id`.
6. **Espera.** El Darkroom muestra anillo, etapas y consola. El usuario puede quedarse, ir a la Biblioteca (donde ve la tarjeta con barra) o cerrar la pestaña (el trabajo sigue en el servidor). No hay aviso al terminar. El tiempo depende del largo del video, de si hay cola y del análisis elegido (~6 min por 28 s en CPU, más con análisis profundo o detección de objeto con SAM 2).
7. **Resultado.** Se muestra el comparador. Mueve la cortina, reproduce, salta a un efecto desde la línea de tiempo o desde la lista, lee la nota de intención (si fue análisis profundo).
8. **Decidir.** (a) Descargar el MP4 y listo. (b) "Probar otra versión": cambia estilo/temporada/vestuario/looks/análisis, espera otro render (más rápido porque el análisis está en caché) y llega a **otra página de trabajo**; la versión previa queda en la Biblioteca como una tarjeta más. (c) Volver a la Biblioteca.
9. **Biblioteca.** Ve miniaturas, abre un trabajo, borra con confirmación nativa, o "Nuevo revelado".

### 4.3 Estados y errores (qué ve el usuario)

| Situación | Qué pasa hoy |
| --- | --- |
| API caída | En el Estudio, un recuadro rojo con el texto del error y el comando para arrancarla (dirigido a quien desarrolla, no a un usuario final). |
| Formato no soportado / > 500 MB | Error en rojo bajo el botón, tras intentar subir. |
| Subida interrumpida | Mensaje "No se pudo conectar con la API. ¿Está corriendo vfxglow-api?". |
| Trabajo en cola | "En cola" y "Esperando turno en la cola…"; sin posición ni tiempo. |
| Fallo del pipeline | "El revelado falló", mensaje técnico y log desplegable. Sin reintentar, sin "avísanos", sin mensaje en lenguaje llano. |
| Servidor reiniciado en pleno trabajo | Queda "interrumpido". |
| Análisis profundo saturado (503/429) | Reintenta solo 3 veces (5/10/20 s) y luego usa un modelo de respaldo; si todo falla, el error lo dice. |
| Sin clave de OpenAI/Gemini | El análisis sigue sin esas partes (lector de escena, accesorios, profundo); el usuario **no recibe aviso** de que se degradó. |
| Trabajo ajeno | 404 ("Trabajo no encontrado"). |
| Biblioteca vacía | Mensaje y botón al Estudio. |

### 4.4 Interacciones que existen solo fuera de la web (para equipos técnicos)

Fijar efectos exactos por segundo con un guion YAML (`--pin`), elegir semilla, `--take N`, nivel de análisis (`fast/hq/masks`), exportación en ProRes 4444, guardar capas intermedias, exportar una coreografía que gustó a un guion editable (`pin-export`). Ninguna de estas está en la interfaz: el usuario web no puede editar la coreografía, solo regenerarla.

### 4.5 Accesibilidad, idioma, dispositivos

- **Idioma**: toda la UI está en español, sin internacionalización ni selector de idioma. Los nombres de acción vienen de un diccionario en español (`format.ts`).
- **Teclado**: el comparador tiene espacio/flechas; los chips y botones son nativos. No hay auditoría de accesibilidad hecha; los marcadores de la línea de tiempo tienen `aria-label`; los chips de filtro usan `aria-pressed`; el anillo de progreso tiene `role="img"` con `aria-label`; la consola usa `aria-live="polite"`. Faltan comprobaciones de contraste (la estética es oscura, de neón) y de movimiento reducido (hay auroras y grano de película animados).
- **Móvil**: hay media queries, pero el Estudio y el panel de "otra opción" son largos; no hay prueba documentada.
- **Rendimiento percibido**: las vistas previas de estilos son un canvas animado por tarjeta.

---

## 5. Puntos de fricción detectados en el código (para alimentar el análisis)

Estos no son una lista de decisiones; son observaciones comprobables para que otro modelo las priorice.

**Antes del render**
1. El usuario compromete un render largo sin ver una vista previa de su propio video con el efecto.
2. No sabe qué estilo le conviene: el sistema detectó el tipo de escena técnicamente pero no lo usa (el usuario elige el catálogo).
3. El formulario crece/encoge según el estilo y mezcla decisiones muy distintas (temporada, look, vestuario, tipo de análisis) en una sola página sin resumen.
4. "Profundo con IA" tiene costo y tarda más, pero no se muestra precio, saldo ni estimación de tiempo.
5. Los presets están escondidos y no tienen vista previa animada.
6. No hay recorte de tramo ni muestra de los primeros segundos para probar barato.

**Durante la espera**
7. Sin estimación de tiempo restante, sin posición en la cola, sin cancelar, sin notificación al terminar.
8. La consola muestra texto técnico del pipeline como contenido principal para el usuario.
9. Los trabajos se procesan uno a uno: con varios usuarios (o varias versiones) la cola crece y no se comunica.

**Resultado y edición**
10. Un resultado "casi bueno" solo se puede regenerar completo ("otra versión"), no corregir: no se puede quitar un efecto, ni moverlo, ni cambiar su intensidad, ni fijar uno. La lista de la coreografía es de solo lectura.
11. "Probar otra versión" crea otro trabajo y otra página; el usuario pierde la comparación entre versiones (no hay lado a lado) y la Biblioteca se llena de tarjetas sin relación visible.
12. Los controles de "otra versión" duplican los del Estudio pero en un `select` pequeño dentro de una tarjeta lateral.
13. El único formato de exportación es un MP4; sin elegir resolución/calidad, sin compartir, sin copiar enlace.

**Biblioteca**
14. Sin colecciones, carpetas, búsqueda, filtros, orden, favoritos, renombrado ni agrupación de versiones del mismo video; los nombres son el nombre del archivo original.
15. Borrado definitivo con `window.confirm`; sin papelera ni deshacer.
16. Sin uso de almacenamiento ni límites visibles.

**Cuenta y negocio**
17. No hay planes, cuotas, facturación, ni páginas de términos/privacidad/soporte (los enlaces del login son anclas vacías).
18. El producto está acoplado a un servidor local con archivos en disco; no hay nube ni dispositivos múltiples.

**Confianza y expectativas**
19. El resultado depende de la calidad del seguimiento: acrobacias (volteretas), más de 2 personas, hojas plateadas, caras cubiertas y fondo con mucho público pueden dar efectos ausentes o mal ubicados. La UI **no avisa** de cuándo el análisis tuvo baja confianza ni sugiere un mejor plano.
20. La web promete "Mejor si se ve el cuerpo entero", pero no valida ni advierte sobre el video subido (número de personas, encuadre, duración).
21. El copy comercial ("Resultados profesionales… calidad cinematográfica") no se apoya en ejemplos reales dentro de la propia web (no hay galería de demostración).

---

## 6. Datos y límites técnicos útiles para proponer mejoras viables

- Render: ~6 min por 28 s de video en CPU; el análisis domina la barra de progreso (~55 %). El análisis se cachea por hash del video, así que cambiar de estilo/versión es mucho más barato.
- Tamaño máximo de subida: 500 MB. Formatos: mp4, mov, m4v, webm, mkv.
- Máximo 2 personas con seguimiento fiable; el público del fondo se descarta.
- Cola: 1 trabajo a la vez, en un hilo.
- Determinismo: misma semilla/versión ⇒ misma coreografía (permite "volver a la versión 2").
- La salida es solo MP4 H.264 (ProRes solo por configuración, no por la UI).
- Las versiones reutilizan el análisis, lo que habilita ediciones baratas (cambiar un efecto, color o temporada) si se construye la interfaz para ello. El motor ya genera la "coreografía" como una lista de momentos con segundo, acción, persona, efecto y nota, que hoy se muestra pero no se edita.
- Dependencias externas de pago: Gemini (análisis profundo), OpenAI (lector de escena, accesorios, director opcional). El costo por video no está medido formalmente (es una tarea pendiente en el plan A3).
- Pantallas existentes: 4 (login, estudio, trabajo, biblioteca). Componentes reutilizables: Shell, Dropzone, StyleCard, NeonPreview, Darkroom, CompareViewer, ChoreographyPanel.

---

## 7. Sugerencia de prompt para llevar este informe a otro modelo

> Actúa como diseñador de producto/UX senior. Adjunto el informe de una app llamada VEXORA (efectos visuales de luz procedurales sobre video de baile/pelea/espadas/avatar). Distingue en todo momento entre lo que **existe** y lo **propuesto**. 1) Resume el recorrido del usuario y dónde se rompe. 2) Prioriza con impacto/esfuerzo las 10 mejoras de UX más valiosas, usando las observaciones de la sección 5 y respetando los límites técnicos de la sección 6 (render lento en CPU, 1 trabajo a la vez, edición posible porque el análisis está en caché). 3) Propón el flujo ideal del Estudio, de la espera, del resultado (edición de la coreografía) y de la Biblioteca (colecciones, agrupación de versiones). 4) Propón métricas para medir si mejoran. 5) Señala supuestos que habría que validar con usuarios reales.
