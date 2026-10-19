# Física del fuego: escenarios de fuerzas

Las fuerzas que actúan sobre el fuego dibujado del estilo Avatar (`engine/firebend.py`,
`engine/fire_creatures.py`) y cómo está cada una. El fuego no se simula como un fluido real: cada
llama es una forma con un estado que responde a estas fuerzas de forma creíble y estable.

## Escenarios

| # | Escenario | Qué le pasa al fuego | Estado |
| --- | --- | --- | --- |
| 1 | **Flotación** (el aire caliente sube) | Una llama quieta apunta hacia arriba; las brasas suben | ✅ `BUOYANCY`; brasas con empuje hacia arriba |
| 2 | **Viento relativo** (la mano corta el aire) | La llama se inclina en dirección contraria al movimiento del ancla, más cuanto más rápido | ✅ `flame_physics`: `WIND_DRAG` |
| 3 | **Inercia** (arranque) | Al empezar a moverse, la llama se queda atrás un instante | ✅ resorte del ángulo (`SPRING`, `DAMPING`) |
| 4 | **Frenada / sobrepaso** | Al frenar, la llama se pasa de largo hacia adelante, oscila y vuelve a la vertical | ✅ resorte amortiguado; test `test_stop_overshoots_then_settles` |
| 5 | **Estiramiento por velocidad** | Más rápido, más larga y más fina (conserva el área) | ✅ `STRETCH`, ancho / √estiramiento |
| 6 | **Recogida al frenar en seco** | Un instante más corta y ancha antes de volver a su largo | ✅ término de frenada en `flame_physics` |
| 7 | **Estela del golpe** | El látigo sigue la trayectoria de la mano, exagerada y en medialuna | ✅ `fire_whip` (recorrido + Bézier) |
| 8 | **Movimiento de la cabeza** | La melena de la calavera se mece contra el giro y el movimiento de la cabeza | ✅ `flame_physics` en `fire_skull` |
| 9 | **Rotación de la cara** | La calavera se redibuja en 3D según el giro de la cabeza (de frente a perfil) | ✅ `_skull3d` |
| 10 | **Turbulencia** | El borde ondula sin patrón; las brasas se curvan | ✅ ruido coherente (`_smooth_noise`, `_noise`) |
| 11 | **Herencia de velocidad** | Las brasas salen con parte del movimiento del fuego que las suelta | ✅ `embers["inherit"]` |
| 12 | **Arrastre del aire sobre brasas** | Las brasas frenan poco a poco | ✅ `vel * 0.9` por cuadro |
| 13 | **Choque contra el piso** | El fuego se expande a los lados en olas que tiemblan y se aplanan | ✅ `fire_splash` |
| 14 | **Desintegración** | Al apagarse se vacía desde el centro y suelta trozos y brasas | ✅ `erode`, brasas ×3 al morir |
| 15 | **Saltos del detector** | Un salto de la pose (no un movimiento) no debe sacudir la llama | ✅ se ignora (test `test_tracker_jump_is_ignored`) |
| 16 | **Fuerza centrífuga en giros** | En un giro sobre sí mismo, las llamas se abren hacia afuera del eje | ⏳ pendiente (hoy el giro usa el aro) |
| 17 | **Viento del ambiente** | Todas las llamas inclinadas hacia un lado (exteriores, ventilador) | ⏳ parámetro `wind` listo en `flame_physics`, sin uso en el catálogo |
| 18 | **Estela del aire detrás del cuerpo** | Al desplazarse todo el cuerpo, el fuego de la espalda se arrastra | ⏳ pendiente |
| 19 | **Gravedad sobre trozos pesados** | Trozos grandes que se desprenden caen en vez de subir | ✅ las brasas más grandes caen; las livianas flotan |
| 20 | **Interacción entre llamas** | Dos llamas que se acercan se atraen y se funden | Parcial: se funden en la máscara, sin atracción |

## Parámetros para calibrar (`engine/firebend.py`)

| Constante | Qué controla |
| --- | --- |
| `BUOYANCY` | Fuerza hacia arriba |
| `WIND_DRAG` | Cuánto empuja el aire relativo |
| `SPRING`, `DAMPING` | Rigidez del resorte y cuánto tarda en asentarse (menos `DAMPING`, se asienta antes) |
| `MAX_LEAN` | Inclinación máxima respecto de la vertical |
| `STRETCH`, `MAX_STRETCH` | Estiramiento con la velocidad |
