# Cambios de la versión 3

## 1. Rutas por las calles reales (problema principal)

| Antes (v2) | Ahora (v3) |
|---|---|
| Cada calle se dibujaba como una recta entre sus nodos: las rutas cruzaban manzanas. | Cada calle tiene su **trazado real** de OpenStreetMap y todo se dibuja siguiendo las vías. |
| La longitud de cada calle era estimada (recta × sinuosidad). | Se puede usar el **largo real** medido sobre las calles (interruptor en la pestaña Pedidos). |
| Los pedidos se ubicaban sobre la recta. | Los pedidos quedan **sobre la vía real** (misma calle y misma fracción `t`). |
| Los nodos estaban en coordenadas aproximadas. | Cada nodo se pega a la **intersección real** más cercana. |
| Clic para bloquear calle o agregar pedido medido contra la recta. | Se mide contra el trazado real de la calle. |

Archivos: `src/calles_reales.py` (nuevo), `src/modelos.py` (Calle con `geometria`),
`src/red.py` (polilíneas, `RedVial` que sigue el trazado), `src/datos.py`, `src/gui.py`.

Funciona sin internet después de la primera descarga (caché en
`datos_ejemplo/calles_osm_cusco.json`). Si no hay internet ni caché, el programa avisa y
sigue funcionando con calles en recta.

## 2. Errores corregidos

1. **Rutas imposibles dibujadas como rectas.** Cuando un pedido quedaba aislado por calles
   bloqueadas, `RedVial.camino` devolvía una recta origen-destino, que en el mapa parecía un
   camino real. Ahora devuelve una lista vacía y ese tramo no se dibuja.
2. **Asignación voraz de pedidos inalcanzables.** `asignar_mas_cercano` podía darle a un
   repartidor un pedido a distancia infinita (aislado por bloqueos) y luego la ruta mostraba
   «inf km». Ahora esos pedidos quedan sin asignar y se informan.
3. **Ruta voraz con pedidos inalcanzables** (cuando la asignación venía de antes): se filtran.
4. **Mochila voraz ignoraba el objetivo «Prioridad».** Siempre maximizaba el valor en soles
   aunque se eligiera prioridad; ahora acepta `valor_fn` igual que la de programación dinámica.
5. **Benchmark con «Usar los pedidos del mapa»** incluía pedidos aislados (distancias
   infinitas en Held-Karp/backtracking). Ahora solo usa los alcanzables.
6. **Cargar pedidos guardados con otro trazado** daba error («no está donde dicen su calle»).
   Ahora la calle y `t` mandan y el punto se recoloca sobre el trazado actual.
7. **Guardar la red en CSV** fallaría con el nuevo campo de geometría: el CSV ahora guarda
   solo las columnas de siempre (el JSON sí guarda el trazado).
8. **Caja del mapa (`limites`)** solo consideraba los nodos: con trazados reales, partes de
   una calle podían quedar fuera de las zonas de Divide y Vencerás. Ahora incluye el trazado.
9. **Tiempo de recorrido desactualizado** al cambiar la longitud de una calle: ahora
   `Calle.cambiar_distancia` recalcula `tiempo_s`.
10. **Prueba de la GUI frágil**: el clic de prueba se hacía en el punto medio de la recta; ahora
    usa un punto sobre el trazado de la calle.

## 3. Funciones nuevas

* **Experimentos E1–E4** (`src/experimentos.py`): implementan exactamente el diseño del
  capítulo 7 (600 instancias pareadas, semillas 1–30, protocolo de 1 calentamiento + 5
  mediciones con `gc` desactivado, tope de 10 s), guardan un CSV por experimento y un
  `resumen.md` con las pruebas de hipótesis. También desde la pestaña Análisis.
* **Estadística** (`src/estadistica.py`): Wilcoxon con método de Pratt (verificado contra
  SciPy), Holm, bootstrap de percentiles, tamaño del efecto r.
* **Horas de llegada y ventanas** (`src/exportar.py`): cada ruta informa la llegada a cada
  pedido y cuántos se entregan dentro de su ventana de tiempo.
* **Exportar rutas** a GPX y CSV, y **abrir en Google Maps** con las paradas en orden.
* **Botón «Calles reales (OSM)»** y etiqueta de estado en la cabecera.
* **32 pruebas nuevas** (`tests/test_v3.py`; total 158), con datos de OSM simulados para no
  depender de internet.

## 4. Lo que NO cambia

* El modelo sigue siendo de **16 nodos y 29 calles**; los algoritmos son los mismos.
* Sin trazado real (o con el interruptor de largo real apagado) las distancias son
  **idénticas** a las de la v2, así que los resultados del plan de tesis siguen valiendo
  (con trazado real, Divide y Vencerás puede variar un poco porque usa la posición de los pedidos).
* No se agregaron dependencias: la descarga usa solo la biblioteca estándar (`urllib`).
