"""Divide y Venceras: segmentacion de la ciudad en zonas."""

from .ordenacion import merge_sort


def dividir_en_zonas(pedidos, k, limites, eje=0):
    """Divide el mapa en k zonas con cortes alternando eje x / eje y.

    Dividir: ordena por el eje actual y corta en dos mitades (proporcionales a k).
    Vencer: resuelve recursivamente cada mitad con la mitad de zonas.
    Combinar: concatena las zonas obtenidas.

    Devuelve lista de (limites, pedidos) con limites = (x0, y0, x1, y1).
    Tiempo O(n log n * log k): cada nivel ordena n pedidos y hay log k niveles.
    """
    if k <= 1:
        return [(limites, list(pedidos))]

    x0, y0, x1, y1 = limites
    ordenados = merge_sort(pedidos, lambda p: p.x if eje == 0 else p.y)
    k_izq = k // 2
    k_der = k - k_izq
    corte_idx = round(len(ordenados) * k_izq / k)

    ini, fin = (x0, x1) if eje == 0 else (y0, y1)
    if 0 < corte_idx < len(ordenados):
        a = ordenados[corte_idx - 1]
        b = ordenados[corte_idx]
        corte = ((a.x + b.x) / 2) if eje == 0 else ((a.y + b.y) / 2)
    else:
        corte = (ini + fin) / 2

    if eje == 0:
        lim_izq, lim_der = (x0, y0, corte, y1), (corte, y0, x1, y1)
    else:
        lim_izq, lim_der = (x0, y0, x1, corte), (x0, corte, x1, y1)

    zonas_izq = dividir_en_zonas(ordenados[:corte_idx], k_izq, lim_izq, 1 - eje)
    zonas_der = dividir_en_zonas(ordenados[corte_idx:], k_der, lim_der, 1 - eje)
    return zonas_izq + zonas_der


# ======================================================================================
# Cuadrantes (quadtree) + resolución por zona + COMBINACIÓN (empalme) de subrutas
# ======================================================================================
import math
from dataclasses import dataclass, field

from .programacion_dinamica import MAX_PEDIDOS_HELD_KARP, ruta_optima_held_karp

EPS = 1e-9
UMBRAL_EXACTO = 8  # hasta este tamaño la ruta interna de una zona es óptima (Held-Karp)


@dataclass
class Zona:
    """Un cuadrante hoja del quadtree: su caja, sus pedidos y las zonas que comparten borde."""
    id: str
    limites: tuple          # (x0, y0, x1, y1) en el plano
    pedidos: list
    nivel: int
    vecinas: list = field(default_factory=list)  # ids de zonas con borde común

    @property
    def centro(self):
        x0, y0, x1, y1 = self.limites
        return (x0 + x1) / 2, (y0 + y1) / 2


@dataclass
class Empalme:
    """Cruce de frontera entre dos zonas en la ruta combinada."""
    de_zona: str
    a_zona: str
    desde: str              # id del pedido (o del punto de salida) antes de cruzar
    hasta: str              # id del pedido al que se llega
    cruce: tuple            # (x, y) aproximado donde la ruta cruza la frontera
    costo: float            # distancia por calles del tramo que cruza
    adyacente: bool         # True si las zonas comparten borde; False = salto sobre zonas vacías


@dataclass
class ResultadoDyV:
    orden: list             # pedidos en el orden de visita final
    zonas: list             # list[Zona]
    subrutas: dict          # zona_id -> pedidos en el orden local (óptimo/heurístico de la zona)
    orden_zonas: list       # ids de zonas en el orden en que se recorren al combinar
    empalmes: list          # list[Empalme] de la ruta final
    distancia: float        # costo total final (misma unidad que 'dist')
    distancia_sin_refinar: float  # costo justo después de empalmar, antes del 2-opt global
    zonas_exactas: int      # zonas resueltas con Held-Karp (óptimo local)


def dividir_cuadrantes(pedidos, limites, max_por_zona=6, max_nivel=3):
    """Divide el mapa en cuadrantes (quadtree) según las coordenadas (x, y) de los pedidos.

    Dividir: si la caja tiene más de 'max_por_zona' pedidos y no se llegó a 'max_nivel', se
    parte por su centro en 4 cuadrantes (NO, NE, SO, SE) y se repite en cada uno.
    Devuelve solo las hojas con pedidos, como lista de ``Zona`` con sus vecinas (zonas que
    comparten un borde de largo positivo) ya calculadas.
    Tiempo O(n * profundidad): cada nivel reparte los n pedidos una vez.
    """
    hojas = []

    def recorrer(lista, caja, nivel, ruta):
        if not lista:
            return
        if len(lista) <= max_por_zona or nivel >= max_nivel:
            hojas.append(Zona("", caja, list(lista), nivel))
            return
        x0, y0, x1, y1 = caja
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        cuadrantes = {
            "NO": ([], (x0, cy, cx, y1)), "NE": ([], (cx, cy, x1, y1)),
            "SO": ([], (x0, y0, cx, cy)), "SE": ([], (cx, y0, x1, cy)),
        }
        for p in lista:
            clave = ("N" if p.y >= cy else "S") + ("E" if p.x >= cx else "O")
            cuadrantes[clave][0].append(p)
        for nombre, (sub, subcaja) in cuadrantes.items():
            recorrer(sub, subcaja, nivel + 1, ruta + [nombre])

    recorrer(list(pedidos), tuple(limites), 0, [])
    for i, z in enumerate(hojas, 1):
        z.id = f"Z{i}"
    for i, a in enumerate(hojas):
        for b in hojas[i + 1:]:
            if _comparten_borde(a.limites, b.limites):
                a.vecinas.append(b.id)
                b.vecinas.append(a.id)
    return hojas


def _comparten_borde(a, b):
    """True si dos cajas se tocan por un borde de largo > 0 (no solo en una esquina)."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    solape_y = min(ay1, by1) - max(ay0, by0)
    solape_x = min(ax1, bx1) - max(ax0, bx0)
    vertical = (abs(ax1 - bx0) < EPS or abs(bx1 - ax0) < EPS) and solape_y > EPS
    horizontal = (abs(ay1 - by0) < EPS or abs(by1 - ay0) < EPS) and solape_x > EPS
    return vertical or horizontal


def _costo_ruta(inicio, orden, dist):
    total, previo = 0.0, inicio
    for p in orden:
        if previo is not None:
            total += dist(previo, p)
        previo = p
    return total


def mejorar_2opt(inicio, orden, dist, max_pasadas=30):
    """Refinamiento 2-opt de una ruta abierta: invierte tramos mientras eso la acorte.

    'inicio' fijo (o None para inicio libre). Cada pasada es O(n^2); termina cuando una
    pasada completa no mejora o al llegar a 'max_pasadas'. Devuelve una lista nueva.
    """
    orden = list(orden)
    n = len(orden)

    def borde(a, b):
        return 0.0 if a is None or b is None else dist(a, b)

    for _ in range(max_pasadas):
        mejoro = False
        for i in range(n - 1):
            previo = orden[i - 1] if i > 0 else inicio
            for j in range(i + 1, n):
                siguiente = orden[j + 1] if j + 1 < n else None
                antes = borde(previo, orden[i]) + borde(orden[j], siguiente)
                despues = borde(previo, orden[j]) + borde(orden[i], siguiente)
                if despues < antes - 1e-9:
                    orden[i:j + 1] = reversed(orden[i:j + 1])
                    mejoro = True
        if not mejoro:
            break
    return orden


def _vecino_mas_cercano_desde(arranque, pedidos, dist):
    restantes = [p for p in pedidos if p is not arranque]
    orden = [arranque]
    while restantes:
        siguiente = min(restantes, key=lambda p: dist(orden[-1], p))
        restantes.remove(siguiente)
        orden.append(siguiente)
    return orden


def resolver_zona(pedidos, dist, umbral_exacto=UMBRAL_EXACTO):
    """Mejor recorrido INTERNO de una zona, sin saber por dónde se entrará.

    Hasta 'umbral_exacto' pedidos usa Held-Karp con inicio libre (óptimo). Con más, prueba
    el vecino más cercano desde los pedidos extremos (mín/máx en x e y) y refina con 2-opt.
    Devuelve (orden, ¿exacto?).
    """
    if len(pedidos) <= 1:
        return list(pedidos), True
    if len(pedidos) <= min(umbral_exacto, MAX_PEDIDOS_HELD_KARP):
        orden, _ = ruta_optima_held_karp(None, pedidos, dist)
        return orden, True
    extremos = {}
    for p in (min(pedidos, key=lambda p: p.x), max(pedidos, key=lambda p: p.x),
              min(pedidos, key=lambda p: p.y), max(pedidos, key=lambda p: p.y)):
        extremos[p.id] = p          # los Pedido no son hashables: se deduplica por id
    mejor, mejor_costo = None, math.inf
    for arranque in extremos.values():
        candidato = mejorar_2opt(None, _vecino_mas_cercano_desde(arranque, pedidos, dist), dist)
        costo = _costo_ruta(None, candidato, dist)
        if costo < mejor_costo:
            mejor, mejor_costo = candidato, costo
    return mejor, False


def combinar_subrutas(inicio, zonas, subrutas, dist):
    """COMBINAR: une las subrutas de las zonas en una sola ruta (empalme de fronteras).

    1. Orden de zonas: desde 'inicio' elige la zona cuyo extremo de subruta esté más cerca y
       luego pasa siempre a una zona ADYACENTE no visitada (la que se entra con menor costo);
       si no quedan adyacentes, salta a la no visitada más cercana.
    2. Empalme: cada subruta se pega por el extremo que quede más cerca del punto actual,
       invirtiéndola si hace falta (una subruta recorrida al revés sigue siendo óptima).
    Devuelve (orden de pedidos, ids de zonas en el orden de recorrido).
    Tiempo O(z^2) con z zonas (más el costo de ``dist``).
    """
    por_id = {z.id: z for z in zonas}
    pendientes = [z.id for z in zonas if subrutas.get(z.id)]
    orden_zonas, ruta = [], []
    actual_pos = inicio          # extremo desde el que se mide
    zona_actual = None

    while pendientes:
        if zona_actual is not None:
            vecinas = [i for i in pendientes if i in por_id[zona_actual].vecinas]
            candidatas = vecinas or pendientes
        else:
            candidatas = pendientes

        def costo_entrada(zid):
            s = subrutas[zid]
            return min(dist(actual_pos, s[0]), dist(actual_pos, s[-1]))

        elegida = min(candidatas, key=costo_entrada)
        sub = list(subrutas[elegida])
        if dist(actual_pos, sub[-1]) < dist(actual_pos, sub[0]):
            sub.reverse()
        ruta.extend(sub)
        orden_zonas.append(elegida)
        pendientes.remove(elegida)
        actual_pos, zona_actual = sub[-1], elegida
    return ruta, orden_zonas


def _punto_de_cruce(a, b, zona_a, zona_b):
    """Punto (x, y) donde el segmento a->b corta el borde compartido de dos zonas."""
    ax0, ay0, ax1, ay1 = zona_a.limites
    bx0, by0, bx1, by1 = zona_b.limites
    adyacentes = zona_b.id in zona_a.vecinas
    if adyacentes:
        if abs(ax1 - bx0) < EPS or abs(bx1 - ax0) < EPS:       # borde vertical x = c
            c = ax1 if abs(ax1 - bx0) < EPS else ax0
            if abs(b.x - a.x) > EPS:
                t = min(1.0, max(0.0, (c - a.x) / (b.x - a.x)))
                return (c, a.y + t * (b.y - a.y)), True
        else:                                                    # borde horizontal y = c
            c = ay1 if abs(ay1 - by0) < EPS else ay0
            if abs(b.y - a.y) > EPS:
                t = min(1.0, max(0.0, (c - a.y) / (b.y - a.y)))
                return (a.x + t * (b.x - a.x), c), True
    return ((a.x + b.x) / 2, (a.y + b.y) / 2), adyacentes


def detectar_empalmes(inicio, orden, zonas, dist):
    """Lista de ``Empalme``: cada paso consecutivo de la ruta que cambia de zona."""
    zona_de = {p.id: z for z in zonas for p in z.pedidos}
    empalmes = []
    previo = inicio
    zona_previa = None
    if inicio is not None and hasattr(inicio, "x"):
        # la zona de salida es la que contiene al punto de inicio (si cae dentro de alguna)
        for z in zonas:
            x0, y0, x1, y1 = z.limites
            if x0 - EPS <= inicio.x <= x1 + EPS and y0 - EPS <= inicio.y <= y1 + EPS:
                zona_previa = z
                break
    for p in orden:
        z = zona_de[p.id]
        if previo is not None and zona_previa is not None and z.id != zona_previa.id:
            cruce, ady = _punto_de_cruce(previo, p, zona_previa, z)
            empalmes.append(Empalme(zona_previa.id, z.id, getattr(previo, "id", "inicio"),
                                    p.id, cruce, dist(previo, p), ady))
        previo, zona_previa = p, z
    return empalmes


def dividir_y_vencer(inicio, pedidos, limites, dist, max_por_zona=6, max_nivel=3,
                     refinar=True):
    """Divide y Vencerás completo para una ruta de visita desde 'inicio'.

    * DIVIDIR: ``dividir_cuadrantes`` parte el mapa por coordenadas (x, y) en cuadrantes.
    * VENCER: ``resolver_zona`` resuelve cada cuadrante por separado (óptimo si es pequeño).
    * COMBINAR: ``combinar_subrutas`` empalma las subrutas de zonas adyacentes y, con
      'refinar', ``mejorar_2opt`` repara las costuras de las fronteras (un viaje que cruza
      de sector puede mejorar intercambiando paradas a ambos lados del borde).

    Heurística: no garantiza el óptimo global. Tiempo: dividir O(n log n) en promedio,
    vencer O((n/k) * 2^k * k^2) con k = max_por_zona, combinar O(z^2 + n^2) por el 2-opt.
    """
    pedidos = list(pedidos)
    if not pedidos:
        return ResultadoDyV([], [], {}, [], [], 0.0, 0.0, 0)
    zonas = dividir_cuadrantes(pedidos, limites, max_por_zona, max_nivel)
    subrutas, exactas = {}, 0
    for z in zonas:
        orden_local, exacto = resolver_zona(z.pedidos, dist)
        subrutas[z.id] = orden_local
        exactas += exacto
    ruta, orden_zonas = combinar_subrutas(inicio, zonas, subrutas, dist)
    antes = _costo_ruta(inicio, ruta, dist)
    if refinar:
        ruta = mejorar_2opt(inicio, ruta, dist)
    despues = _costo_ruta(inicio, ruta, dist)
    empalmes = detectar_empalmes(inicio, ruta, zonas, dist)
    return ResultadoDyV(ruta, zonas, subrutas, orden_zonas, empalmes, despues, antes, exactas)
