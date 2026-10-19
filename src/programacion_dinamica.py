"""Programación Dinámica: mochila 0/1 (tabulación, memoización, peso + volumen) y
ruta óptima de visita (Held-Karp).

Todas las mochilas devuelven la lista EXACTA de pedidos elegidos, reconstruida hacia atrás
sobre la tabla (o sobre la memoria) de la PD: no se vuelve a resolver nada para saber qué
se eligió. ``ids`` de esa lista se obtiene con ``[p.id for p in elegidos]``.
"""

import math
import sys

from .modelos import distancia

MAX_PEDIDOS_HELD_KARP = 12


def _valor_por_defecto(p):
    return p.valor


def mochila_01(pedidos, capacidad, valor_fn=None):
    """Mochila 0/1 por tabulación (bottom-up).

    Estado: dp[i][w] = mejor valor usando los primeros i pedidos con capacidad w.
    Recurrencia: dp[i][w] = max(dp[i-1][w], dp[i-1][w - peso_i] + valor_i).
    Casos base: dp[0][w] = 0 y dp[i][0] = 0.

    'valor_fn' elige qué se maximiza (por defecto ``p.valor``; ``lambda p: p.urgencia``
    maximiza prioridad). Reconstrucción: se recorre la tabla de i = n hasta 1; si
    dp[i][w] != dp[i-1][w] el pedido i se tomó y se descuenta su peso de w.

    Devuelve (seleccionados, valor total, peso total).
    Tiempo O(n*W), espacio O(n*W), con W la capacidad (entera).
    """
    valor_fn = valor_fn or _valor_por_defecto
    n = len(pedidos)
    capacidad = max(0, int(capacidad))
    dp = [[0] * (capacidad + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        p = pedidos[i - 1]
        v = valor_fn(p)
        for w in range(capacidad + 1):
            dp[i][w] = dp[i - 1][w]
            if p.peso <= w:
                dp[i][w] = max(dp[i][w], dp[i - 1][w - p.peso] + v)

    elegidos = []
    w = capacidad
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            elegidos.append(pedidos[i - 1])
            w -= pedidos[i - 1].peso
    elegidos.reverse()
    return elegidos, dp[n][capacidad], sum(p.peso for p in elegidos)


def mochila_01_memo(pedidos, capacidad, valor_fn=None):
    """Mochila 0/1 top-down con MEMOIZACIÓN (recursión + diccionario de subproblemas).

    f(i, w) = mejor valor usando los pedidos i..n-1 con capacidad w
            = max(f(i+1, w), valor_i + f(i+1, w - peso_i))   (si cabe).
    Solo se calculan los estados alcanzables desde (0, W), así que puede ser más rápida
    que la tabla completa cuando muchos pesos no caben. Misma reconstrucción: si
    f(i, w) != f(i+1, w) el pedido i se tomó.

    Devuelve (seleccionados, valor total, peso total). Tiempo y espacio O(n*W) en el
    peor caso (recursión de profundidad n).
    """
    valor_fn = valor_fn or _valor_por_defecto
    n = len(pedidos)
    capacidad = max(0, int(capacidad))
    valores = [valor_fn(p) for p in pedidos]
    memo = {}

    limite_anterior = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limite_anterior, n + 1000))
    try:
        def f(i, w):
            if i == n:
                return 0
            clave = (i, w)
            if clave in memo:
                return memo[clave]
            mejor = f(i + 1, w)
            if pedidos[i].peso <= w:
                mejor = max(mejor, valores[i] + f(i + 1, w - pedidos[i].peso))
            memo[clave] = mejor
            return mejor

        total = f(0, capacidad)
        elegidos = []
        w = capacidad
        for i in range(n):
            if f(i, w) != f(i + 1, w):
                elegidos.append(pedidos[i])
                w -= pedidos[i].peso
    finally:
        sys.setrecursionlimit(limite_anterior)
    return elegidos, total, sum(p.peso for p in elegidos)


def mochila_01_peso_volumen(pedidos, cap_kg, cap_m3, paso_m3=0.01, valor_fn=None):
    """Mochila 0/1 con DOS restricciones: peso (kg) y volumen (m3).

    El volumen se discretiza en unidades de 'paso_m3' (por defecto 0.01 m3 = 10 L): el de cada
    pedido se redondea hacia arriba y la capacidad hacia abajo, así que la solución nunca se
    pasa del volumen real. Estado: dp[i][w][v] = mejor valor con los primeros i pedidos,
    capacidad w kg y v unidades de volumen.

    Devuelve (seleccionados, valor total, peso total, volumen total m3).
    Tiempo y espacio O(n * W * V).
    """
    valor_fn = valor_fn or _valor_por_defecto
    n = len(pedidos)
    W = max(0, int(cap_kg))
    V = max(0, int(math.floor(cap_m3 / paso_m3 + 1e-9)))
    ancho = V + 1
    vol_u = [max(0, math.ceil(p.volumen_m3 / paso_m3 - 1e-9)) for p in pedidos]
    dp = [[0] * ((W + 1) * ancho) for _ in range(n + 1)]
    for i in range(1, n + 1):
        p = pedidos[i - 1]
        wi, vi, val = p.peso, vol_u[i - 1], valor_fn(p)
        prev, cur = dp[i - 1], dp[i]
        for w in range(W + 1):
            base = w * ancho
            for v in range(V + 1):
                mejor = prev[base + v]
                if wi <= w and vi <= v:
                    candidato = prev[(w - wi) * ancho + (v - vi)] + val
                    if candidato > mejor:
                        mejor = candidato
                cur[base + v] = mejor

    elegidos = []
    w, v = W, V
    for i in range(n, 0, -1):
        if dp[i][w * ancho + v] != dp[i - 1][w * ancho + v]:
            elegidos.append(pedidos[i - 1])
            w -= pedidos[i - 1].peso
            v -= vol_u[i - 1]
    elegidos.reverse()
    return (elegidos, dp[n][W * ancho + V], sum(p.peso for p in elegidos),
            round(sum(p.volumen_m3 for p in elegidos), 6))


def ruta_optima_held_karp(inicio, pedidos, dist=distancia):
    """Ruta abierta de costo mínimo desde 'inicio' visitando todos los pedidos.

    Estado: dp[mask][j] = costo mínimo de visitar el conjunto 'mask' terminando en j.
    Recurrencia: dp[mask | {k}][k] = min(dp[mask][j] + d(j, k)).
    'dist' mide la distancia (por defecto en línea recta; la app usa la de calles).
    Con ``inicio=None`` el camino puede empezar en cualquier pedido (inicio libre): sirve
    para resolver el mejor recorrido interno de una zona sin saber por dónde se entra.
    Devuelve (orden, distancia total).
    Tiempo O(n^2 * 2^n), espacio O(n * 2^n). Limitado a 12 pedidos.
    """
    n = len(pedidos)
    if n == 0:
        return [], 0.0
    if n > MAX_PEDIDOS_HELD_KARP:
        raise ValueError(f"Held-Karp admite como máximo {MAX_PEDIDOS_HELD_KARP} pedidos")

    d = [[dist(a, b) for b in pedidos] for a in pedidos]
    d0 = [dist(inicio, p) for p in pedidos] if inicio is not None else [0.0] * n
    inf = math.inf
    dp = [[inf] * n for _ in range(1 << n)]
    padre = [[-1] * n for _ in range(1 << n)]
    for j in range(n):
        dp[1 << j][j] = d0[j]

    for mask in range(1 << n):
        for j in range(n):
            if not (mask >> j) & 1 or dp[mask][j] == inf:
                continue
            for k in range(n):
                if (mask >> k) & 1:
                    continue
                nueva = mask | (1 << k)
                costo = dp[mask][j] + d[j][k]
                if costo < dp[nueva][k]:
                    dp[nueva][k] = costo
                    padre[nueva][k] = j

    completo = (1 << n) - 1
    j = min(range(n), key=lambda x: dp[completo][x])
    total = dp[completo][j]
    orden = []
    mask = completo
    while j != -1:
        orden.append(pedidos[j])
        anterior = padre[mask][j]
        mask ^= 1 << j
        j = anterior
    orden.reverse()
    return orden, total
