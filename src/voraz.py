"""Enfoque voraz (Greedy): decisiones locales que no se reconsideran."""

import heapq
import math

from .modelos import distancia
from .ordenacion import merge_sort


def asignar_mas_cercano(pedidos, repartidores, dist=distancia):
    """Asigna cada pedido al repartidor mas cercano que aun tenga capacidad.

    'dist' mide la distancia (por defecto en linea recta; la app usa la de calles).
    Los pedidos mas urgentes se atienden primero. Un pedido al que ningun repartidor con
    espacio puede llegar (calles bloqueadas) queda sin asignar. Devuelve
    ({nombre: [pedidos]}, [pedidos sin asignar]).
    Tiempo O(n log n + n*m) con n pedidos y m repartidores.
    """
    carga = {r.nombre: 0 for r in repartidores}
    asignacion = {r.nombre: [] for r in repartidores}
    pendientes = []
    for p in merge_sort(pedidos, lambda p: p.urgencia, inverso=True):
        # solo repartidores con capacidad libre que PUEDEN llegar (las calles bloqueadas
        # pueden dejar un pedido a distancia infinita de alguno o de todos)
        candidatos = [(dist(r, p), r) for r in repartidores
                      if carga[r.nombre] + p.peso <= r.capacidad]
        candidatos = [(d, r) for d, r in candidatos if not math.isinf(d)]
        if not candidatos:
            pendientes.append(p)
            continue
        elegido = min(candidatos, key=lambda dr: dr[0])[1]
        asignacion[elegido.nombre].append(p)
        carga[elegido.nombre] += p.peso
    return asignacion, pendientes


def ruta_vecino_mas_cercano(inicio, pedidos, dist=distancia):
    """Desde 'inicio' siempre visita el pedido mas cercano a la posicion actual.

    Ruta abierta (no regresa al inicio). Devuelve (orden, distancia total).
    Tiempo O(n^2), espacio O(n). No garantiza el optimo.
    """
    pendientes = list(pedidos)
    actual = inicio
    orden = []
    total = 0.0
    while pendientes:
        siguiente = min(pendientes, key=lambda p: dist(actual, p))
        total += dist(actual, siguiente)
        orden.append(siguiente)
        pendientes.remove(siguiente)
        actual = siguiente
    return orden, total


def mochila_voraz(pedidos, capacidad, valor_fn=None):
    """Mochila 0/1 voraz: ordena por valor/peso y mete mientras quepa.

    'valor_fn' elige que se maximiza (por defecto ``p.valor``; ``lambda p: p.urgencia``
    maximiza prioridad), igual que en las mochilas de programacion dinamica.
    Devuelve (seleccionados, valor total, peso total).
    Tiempo O(n log n). Es heuristica: puede quedar lejos del optimo.
    """
    valor_fn = valor_fn or (lambda p: p.valor)
    ordenados = merge_sort(pedidos, lambda p: valor_fn(p) / p.peso, inverso=True)
    elegidos, peso, valor = [], 0, 0
    for p in ordenados:
        if peso + p.peso <= capacidad:
            elegidos.append(p)
            peso += p.peso
            valor += valor_fn(p)
    return elegidos, valor, peso


def dijkstra(grafo, origen, destino, cerradas=frozenset()):
    """Camino minimo con pesos no negativos (voraz con cola de prioridad).

    Devuelve (costo, [nodos]); (inf, []) si no hay camino.
    Tiempo O((V + E) log V).
    """
    dist = {origen: 0.0}
    padre = {}
    cola = [(0.0, origen)]
    visitados = set()
    while cola:
        costo, nodo = heapq.heappop(cola)
        if nodo in visitados:
            continue
        visitados.add(nodo)
        if nodo == destino:
            camino = [nodo]
            while camino[-1] != origen:
                camino.append(padre[camino[-1]])
            camino.reverse()
            return costo, camino
        for vecino, c in grafo[nodo]:
            if frozenset((nodo, vecino)) in cerradas:
                continue
            nuevo = costo + c
            if nuevo < dist.get(vecino, math.inf):
                dist[vecino] = nuevo
                padre[vecino] = nodo
                heapq.heappush(cola, (nuevo, vecino))
    return math.inf, []


def dijkstra_todos(grafo, origen):
    """Dijkstra desde un origen hacia todos los nodos alcanzables.

    Devuelve (distancias {nodo: costo}, padres {nodo: nodo previo}).
    Tiempo O((V + E) log V).
    """
    dist = {origen: 0.0}
    padre = {}
    cola = [(0.0, origen)]
    hechos = set()
    while cola:
        costo, nodo = heapq.heappop(cola)
        if nodo in hechos:
            continue
        hechos.add(nodo)
        for vecino, c in grafo.get(nodo, []):
            nuevo = costo + c
            if nuevo < dist.get(vecino, math.inf):
                dist[vecino] = nuevo
                padre[vecino] = nodo
                heapq.heappush(cola, (nuevo, vecino))
    return dist, padre
