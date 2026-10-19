# Sistema de Gestión de Rutas Óptimas en Cusco (versión 3)

App de escritorio en Python que gestiona pedidos de reparto sobre una red de calles de Cusco
y resuelve rutas con cinco enfoques algorítmicos: **ordenación/búsqueda, Voraz, Divide y
Vencerás, Programación Dinámica y Backtracking**, con mapa interactivo, **trazado real de las
calles (OpenStreetMap)**, exportación de rutas, benchmark (Big-O) y los **experimentos E1–E4**
del plan de tesis con su análisis estadístico.

## Instalación y ejecución

    pip install -r requirements.txt
    python main.py

Requiere Python 3.10+ con Tkinter (en Linux: `sudo apt install python3-tk`). El mapa base y
el trazado real de las calles se descargan de internet; sin conexión, el mapa queda gris y las
calles se dibujan en recta, pero todos los algoritmos funcionan igual.

## Calles reales (lo nuevo de la v3)

Antes cada calle del modelo se dibujaba como una **línea recta** entre sus dos nodos, así que
las rutas atravesaban manzanas. Ahora:

1. La **primera vez** que abres el programa con internet, descarga de OpenStreetMap (API
   Overpass) las vías de la zona, pega cada uno de los 16 nodos a la intersección real más
   cercana y calcula, para cada una de las 29 calles, el **recorrido real por las calles**
   entre sus extremos (A*). Tarda de 10 a 60 s y no bloquea la ventana.
2. El resultado se guarda en `datos_ejemplo/calles_osm_cusco.json`; las siguientes veces se
   usa ese archivo y **no hace falta internet**.
3. Todas las rutas (Voraz, Divide y Vencerás, Held-Karp, Backtracking) y las calles bloqueadas
   se dibujan **siguiendo las calles**. Los pedidos quedan sobre la vía real.
4. El interruptor «Usar el largo real de las calles (OSM)» (pestaña Pedidos) elige si las
   distancias son las **reales** medidas sobre las calles o las **sintéticas** del plan de
   tesis (distancia geodésica × sinuosidad). El dibujo sigue la calle real en los dos casos.

También se puede preparar desde la terminal:

    python -m src.calles_reales            # descarga y guarda la caché
    python -m src.calles_reales --forzar   # vuelve a descargarla

Limitaciones (iguales a las del plan de tesis): no se considera el sentido de circulación de
las calles; las escaleras, veredas y ciclovías no se usan. Datos © colaboradores de
OpenStreetMap (ODbL).

## Experimentos E1–E4 del plan de tesis

    python -m src.experimentos                         # 30 semillas, todo (≈ 30 s a 2 min)
    python -m src.experimentos --semillas 5 --rapido   # prueba corta
    python -m src.experimentos --solo E1-Ruta E2       # solo algunos
    python -m src.experimentos --calles-reales         # con el trazado y largo reales

O desde la pestaña **Análisis → Experimentos de la tesis**. Genera una carpeta con un CSV por
experimento (una fila por instancia, con su semilla), `resumen.md` y `analisis.json`:
Wilcoxon de rangos con signo (Pratt para empates, aproximación normal), ajuste de Holm por
familia, tamaño del efecto r = z/√N e IC 95 % por bootstrap (10 000 remuestreos). Protocolo
de tiempo: 1 calentamiento + 5 mediciones con `gc` desactivado, mediana.

La carpeta `resultados_experimentos/` trae una corrida completa (30 semillas). Las
distancias, valores y nodos son reproducibles en cualquier equipo; **los tiempos dependen del
equipo**, así que para la tesis hay que volver a correrlo en la computadora que se reporte.

## Pruebas

    python -m unittest discover -s tests -v          # 158 pruebas
    xvfb-run -a python -m unittest discover -s tests  # Linux sin pantalla: incluye las de la GUI

Las pruebas de la GUI se omiten solas si no hay pantalla o faltan `customtkinter`/`tkintermapview`.
Las de calles reales usan datos de OpenStreetMap **simulados** (`tests/osm_simulado.py`), así
que no necesitan internet.

## Qué se puede hacer en la interfaz

* **Mapa interactivo** (`tkintermapview`). Selector «Clic en el mapa»: *Navegar*,
  *Bloquear / abrir calle* (clic sobre una calle) y *Agregar pedido* (clic en cualquier punto;
  se ubica sobre la calle más cercana). El clic derecho abre un menú con las mismas acciones.
* **Calles reales (OSM)** en la cabecera: descarga o actualiza el trazado real; la etiqueta de
  al lado dice cuántas calles lo tienen.
* **Colores**: verde = Voraz, azul = Backtracking, naranja = Divide y Vencerás, morado =
  Programación Dinámica, **rojo = calle bloqueada**.
* **Horas de llegada**: cada ruta informa en la bitácora a qué minuto llega a cada pedido
  (velocidad del repartidor + 2 min por entrega) y cuántos quedan dentro de su ventana.
* **Exportar rutas**: GPX (Google Earth, OsmAnd, GPS) o CSV (Excel), y **Google Maps** abre
  la ruta con las paradas en orden.
* **Sin congelarse**: todos los algoritmos corren en un hilo (`threading`) y la interfaz
  consulta una `queue` cada 80 ms. Hay barra de progreso y botón **Cancelar**.
* **Ruta no encontrada**: si los bloqueos aíslan el destino se muestra un aviso (sin errores).
* **Pestaña Análisis**: matriz comparativa, gráfica Tiempo vs N y experimentos E1–E4.

## Estructura

    main.py                       punto de entrada
    requirements.txt
    src/gui.py                    interfaz (customtkinter + tkintermapview + matplotlib, hilos)
    src/modelos.py                Nodo, Calle (con trazado real), Pedido, Repartidor, Punto
    src/red.py                    RedCusco (calles, bloqueos, trazado) y RedVial (distancias y recorridos por calles)
    src/datos.py                  red de Cusco, generador de pedidos, archivos JSON/CSV, Escenario
    src/calles_reales.py          NUEVO: descarga OSM (Overpass), grafo real, A*, caché y aplicación del trazado
    src/traductor.py              plano local <-> (lat, lon), exportación a networkx
    src/ordenacion.py             MergeSort, QuickSort, HeapSort, búsqueda binaria, índices hash
    src/voraz.py                  asignación al más cercano, vecino más cercano, mochila voraz, Dijkstra
    src/divide_venceras.py        quadtree, resolución por zona, combinación (empalme + 2-opt)
    src/programacion_dinamica.py  mochila 0/1 (tabulación, memoización, peso+volumen) y Held-Karp
    src/backtracking.py           rutas con poda de calles bloqueadas, enumeración, orden óptimo
    src/benchmark.py              comparación en lote y curvas Tiempo vs N
    src/experimentos.py           NUEVO: experimentos E1–E4 en lote (CSV + resumen)
    src/estadistica.py            NUEVO: Wilcoxon (Pratt), Holm, bootstrap
    src/exportar.py               NUEVO: horas de llegada, GPX, CSV y enlaces de Google Maps
    tests/                        158 pruebas (+ osm_simulado.py)
    datos_ejemplo/                red, pedidos y repartidores (JSON y CSV) y, tras la 1.ª descarga, calles_osm_cusco.json
    resultados_experimentos/      corrida completa de E1–E4 (30 semillas)

## Modelo del mapa y datos

* Los algoritmos trabajan en un **plano local** (x, y; 1 unidad = 100 m). `traductor.py` es el
  único lugar donde se convierte a (lat, lon), solo para dibujar.
* La red del modelo tiene **16 nodos y 29 calles**. Cada calle puede tener su **trazado real**
  (lista de puntos de OSM); los pedidos están sobre las calles (calle + fracción `t` del
  recorrido real) y `RedVial` calcula la distancia por calles con Dijkstra.
* Unidades: distancias en metros, tiempos de calle en segundos, ventanas de pedidos en minutos
  desde el inicio de la jornada, peso en kg (entero) y volumen en m³.

```python
from src import datos, calles_reales, backtracking

esc = datos.Escenario.sintetico(cantidad=18, semilla=7)
cache = calles_reales.cargar_cache()             # o calles_reales.obtener(esc.red) para descargar
if cache:
    calles_reales.aplicar(esc.red, cache)        # trazado (y largo) real de cada calle
    esc.reubicar()                               # pedidos y repartidores sobre el trazado

esc.red.bloquear_calle("San Blas", "Zaguán del Cielo")
r = backtracking.ruta_mas_corta_segura(esc.red, "San Blas", "Wanchaq")
puntos = esc.red.polilinea_camino(r.camino)      # [(lat, lon), ...] siguiendo las calles
```

## Complejidades

| Algoritmo | Tiempo | Espacio | Óptimo |
|---|---|---|---|
| MergeSort / HeapSort / QuickSort | O(n log n) / O(n log n) / O(n log n) promedio | O(n) / O(1) / O(n) | — |
| Búsqueda binaria / tabla hash | O(log n) / O(1) promedio | O(1) / O(n) | — |
| Vecino más cercano (Voraz) | O(n²) | O(n) | No |
| Asignación voraz | O(n log n + n·m) | O(n) | No |
| Dijkstra | O((V+E) log V) | O(V) | Sí |
| A* sobre las calles reales (trazado) | O((V+E) log V) | O(V) | Sí |
| Divide y Vencerás (cuadrantes + empalme) | dividir O(n log n), combinar O(z² + n²) | O(n) | No |
| Mochila 0/1 (PD, tabulación o memoización) | O(n·W) | O(n·W) | Sí |
| Mochila con peso y volumen | O(n·W·V) | O(n·W·V) | Sí |
| Held-Karp (PD) | O(n²·2ⁿ) | O(n·2ⁿ) | Sí (n ≤ 12) |
| Backtracking: ruta entre nodos | O(bᵈ) peor caso, mucho menos con poda | O(d) | Sí |
| Backtracking: orden de visita | O(n!) peor caso, con cota inferior | O(n) | Sí si termina |

## Datos de ejemplo

    python -m src.datos [carpeta] [json|csv]     # regenera los archivos de ejemplo

Ver `CAMBIOS_v3.md` para la lista completa de correcciones y mejoras de esta versión.
