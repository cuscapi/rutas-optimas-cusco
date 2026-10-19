# Resultados de los experimentos E1 a E4

- Fecha: 2026-10-19T10:59:04
- Equipo: x86_64 (2 núcleos), Linux-6.18.44-fc-v139-x86_64-with-glibc2.39, Python 3.13.16
- Semillas por configuración: 1 a 30; repeticiones medidas: 5 (+1 de calentamiento); tope de métodos exponenciales: 10 s
- Red: 16 nodos, 29 calles; trazado recto (distancia geodésica × sinuosidad)
- Duración total: 30.5 s

## E1-Ruta: vecino más cercano frente a Held-Karp (H1)

- n = 6: brecha media 4.08 %, máxima 24.63 %, tiempo mediano VMC 0.006 ms y HK 0.162 ms.
- n = 8: brecha media 6.33 %, máxima 32.52 %, tiempo mediano VMC 0.010 ms y HK 1.086 ms.
- n = 10: brecha media 6.98 %, máxima 21.88 %, tiempo mediano VMC 0.014 ms y HK 6.901 ms.
- n = 12: brecha media 8.55 %, máxima 23.94 %, tiempo mediano VMC 0.018 ms y HK 43.271 ms.
- Backtracking coincide con Held-Karp en todas las instancias completas: sí.

| Prueba | N | Empates | Media d | IC 95 % | z | p | p Holm | r | Decisión |
|---|---|---|---|---|---|---|---|---|---|
| E1-Ruta n=6: d = VMC - HK (km) | 30 | 17 | 0.4805 | [0.2309; 0.7773] | 3.563 | 0.0001837 | 0.0001837 | 0.65 (grande) | se rechaza H0 |
| E1-Ruta n=8: d = VMC - HK (km) | 30 | 9 | 0.7453 | [0.491; 1.018] | 4.386 | 5.774e-06 | 1.155e-05 | 0.80 (grande) | se rechaza H0 |
| E1-Ruta n=10: d = VMC - HK (km) | 30 | 7 | 0.9892 | [0.6649; 1.342] | 4.528 | 2.98e-06 | 8.939e-06 | 0.83 (grande) | se rechaza H0 |
| E1-Ruta n=12: d = VMC - HK (km) | 30 | 6 | 1.344 | [0.9566; 1.749] | 4.588 | 2.234e-06 | 8.937e-06 | 0.84 (grande) | se rechaza H0 |

## E1-Carga: mochila voraz frente a mochila 0/1 (H2)

- n = 15, W = 25 kg: la voraz logra en promedio 98.09 % del óptimo.
- n = 15, W = 30 kg: la voraz logra en promedio 98.67 % del óptimo.
- n = 25, W = 25 kg: la voraz logra en promedio 98.68 % del óptimo.
- n = 25, W = 30 kg: la voraz logra en promedio 99.08 % del óptimo.
- n = 40, W = 25 kg: la voraz logra en promedio 99.20 % del óptimo.
- n = 40, W = 30 kg: la voraz logra en promedio 99.02 % del óptimo.

| Prueba | N | Empates | Media d | IC 95 % | z | p | p Holm | r | Decisión |
|---|---|---|---|---|---|---|---|---|---|
| E1-Carga n=15 W=25: d = PD - voraz (S/) | 30 | 13 | 6.767 | [4.2; 9.667] | 4.025 | 2.846e-05 | 0.0001138 | 0.73 (grande) | se rechaza H0 |
| E1-Carga n=15 W=30: d = PD - voraz (S/) | 30 | 17 | 6.033 | [2.633; 10] | 3.563 | 0.0001835 | 0.000367 | 0.65 (grande) | se rechaza H0 |
| E1-Carga n=25 W=25: d = PD - voraz (S/) | 30 | 13 | 6.433 | [3.6; 9.7] | 4.025 | 2.845e-05 | 0.0001138 | 0.73 (grande) | se rechaza H0 |
| E1-Carga n=25 W=30: d = PD - voraz (S/) | 30 | 12 | 5.1 | [2.833; 7.633] | 4.126 | 1.846e-05 | 0.0001108 | 0.75 (grande) | se rechaza H0 |
| E1-Carga n=40 W=25: d = PD - voraz (S/) | 30 | 18 | 5.233 | [2.6; 8.167] | 3.430 | 0.0003013 | 0.000367 | 0.63 (grande) | se rechaza H0 |
| E1-Carga n=40 W=30: d = PD - voraz (S/) | 30 | 12 | 6.567 | [4.167; 9] | 4.125 | 1.854e-05 | 0.0001108 | 0.75 (grande) | se rechaza H0 |

## E2: backtracking con calles bloqueadas (H3)

- 0 bloqueos: nodos sin poda (mediana) 2819, con cota 33, con RyP 86; reducción media 97.5 %.
- 2 bloqueos: nodos sin poda (mediana) 1221, con cota 44, con RyP 48; reducción media 94.1 %.
- 4 bloqueos: nodos sin poda (mediana) 584, con cota 34, con RyP 42; reducción media 91.9 %.
- RyP coincide con Dijkstra en el 100 % de las instancias. Instancias reemplazadas por destino aislado: 0.

| Prueba | N | Empates | Media d | IC 95 % | z | p | p Holm | r | Decisión |
|---|---|---|---|---|---|---|---|---|---|
| E2 bloqueos=0: d = nodos sin poda - nodos RyP | 30 | 0 | 3306 | [2677; 4048] | 4.783 | 8.634e-07 | 2.59e-06 | 0.87 (grande) | se rechaza H0 |
| E2 bloqueos=2: d = nodos sin poda - nodos RyP | 30 | 0 | 1518 | [1162; 1935] | 4.782 | 8.672e-07 | 2.59e-06 | 0.87 (grande) | se rechaza H0 |
| E2 bloqueos=4: d = nodos sin poda - nodos RyP | 30 | 0 | 601.8 | [491.6; 713.5] | 4.782 | 8.672e-07 | 2.59e-06 | 0.87 (grande) | se rechaza H0 |

## E3a: Held-Karp único frente a divide y vencerás (H4, tiempo)

- m = 4: aceleración mediana 212.7×, exceso de distancia medio 1.93 %.
- m = 6: aceleración mediana 188.7×, exceso de distancia medio 1.90 %.

| Prueba | N | Empates | Media d | IC 95 % | z | p | p Holm | r | Decisión |
|---|---|---|---|---|---|---|---|---|---|
| E3a m=4: d = t HK - t DyV (ms) | 30 | 0 | 46.67 | [43.37; 50.54] | 4.782 | 8.672e-07 | 1.734e-06 | 0.87 (grande) | se rechaza H0 |
| E3a m=6: d = t HK - t DyV (ms) | 30 | 0 | 46.62 | [43.32; 50.49] | 4.782 | 8.672e-07 | 1.734e-06 | 0.87 (grande) | se rechaza H0 |

Distancia (bilateral, descriptiva):

| Prueba | N | Empates | Media d | IC 95 % | z | p | p Holm | r | Decisión |
|---|---|---|---|---|---|---|---|---|---|
| E3a m=4: d = dist DyV - dist HK (km) | 30 | 13 | 0.3027 | [0.1752; 0.4478] | 4.025 | 5.709e-05 | 0.0001142 | 0.73 (grande) | se rechaza H0 |
| E3a m=6: d = dist DyV - dist HK (km) | 30 | 13 | 0.2905 | [0.1709; 0.4218] | 4.025 | 5.709e-05 | 0.0001142 | 0.73 (grande) | se rechaza H0 |

## E3b: vecino más cercano frente a divide y vencerás con muchos pedidos (H4, distancia)

- n = 24, m = 4: DyV es en promedio 4.30 % más corto que VMC.
- n = 24, m = 6: DyV es en promedio 6.04 % más corto que VMC.
- n = 36, m = 4: DyV es en promedio 2.92 % más corto que VMC.
- n = 36, m = 6: DyV es en promedio 2.94 % más corto que VMC.

| Prueba | N | Empates | Media d | IC 95 % | z | p | p Holm | r | Decisión |
|---|---|---|---|---|---|---|---|---|---|
| E3b n=24 m=4: d = VMC - DyV (km) | 30 | 2 | 1.121 | [0.563; 1.693] | 3.189 | 0.001428 | 0.004284 | 0.58 (grande) | se rechaza H0 |
| E3b n=24 m=6: d = VMC - DyV (km) | 30 | 1 | 1.559 | [1.057; 2.088] | 4.320 | 1.563e-05 | 6.253e-05 | 0.79 (grande) | se rechaza H0 |
| E3b n=36 m=4: d = VMC - DyV (km) | 30 | 0 | 0.8924 | [0.3355; 1.424] | 2.828 | 0.004682 | 0.009364 | 0.52 (grande) | se rechaza H0 |
| E3b n=36 m=6: d = VMC - DyV (km) | 30 | 0 | 0.9092 | [0.3143; 1.471] | 2.766 | 0.005667 | 0.009364 | 0.51 (grande) | se rechaza H0 |

## E4: flujo voraz frente a flujo integrado (hipótesis general)

- Valor entregado medio: voraz S/ 1039.4, integrado S/ 1144.9.
- Pedidos atendidos medios: voraz 16.5, integrado 19.7.
- km por pedido: voraz 1.707, integrado 1.252.
- Tiempo del flujo integrado: mediana 2.2 ms, máximo 7.4 ms → cumple el criterio de Nielsen (≤ 1 s y ≤ 10 s).

| Prueba | N | Empates | Media d | IC 95 % | z | p | p Holm | r | Decisión |
|---|---|---|---|---|---|---|---|---|---|
| E4: d = valor integrado - valor voraz (S/) | 30 | 0 | 105.5 | [84.1; 128.2] | 4.762 | 9.599e-07 | 9.599e-07 | 0.87 (grande) | se rechaza H0 |

Archivos CSV con todas las instancias en esta misma carpeta. Semillas registradas en cada fila.
