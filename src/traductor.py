"""Módulo traductor: grafo / plano local  <->  coordenadas (lat, lon) de ``tkintermapview``.

El resto del proyecto trabaja en un plano local en unidades de 100 m (x = este, y = norte)
porque así las distancias salen directo y los algoritmos no dependen de la geografía.
Este módulo es el único punto donde se convierte entre ese plano y el par (lat, lon) que
espera el mapa:

* ``xy_a_latlon`` / ``latlon_a_xy``: proyección equirectangular local con origen fijo en el
  centro de Cusco. A escala de ciudad el error es menor a 1 m, y la conversión es
  exactamente invertible.
* ``ids_a_coordenadas``: toma IDs de nodos (de ``RedCusco``, de un ``networkx.Graph`` o de
  un diccionario) y devuelve ``[(lat, lon), ...]`` listo para ``map.set_path``.
* ``a_networkx``: exporta la red a ``networkx`` con los atributos lat/lon en cada nodo.

No importa ``modelos`` ni ``red`` (los usan a ellos), así que no hay imports circulares.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

# --------------------------------------------------------------------------- proyección
UNIDAD_M = 100.0                              # 1 unidad del plano = 100 m
ORIGEN_LAT, ORIGEN_LON = -13.5170, -71.9785   # Plaza de Armas del Cusco (origen del plano)
RADIO_TIERRA_M = 6_371_008.8
_M_POR_GRADO_LAT = RADIO_TIERRA_M * math.pi / 180.0
_M_POR_GRADO_LON = _M_POR_GRADO_LAT * math.cos(math.radians(ORIGEN_LAT))

Coordenada = tuple[float, float]  # (lat, lon), el orden que usa tkintermapview


def xy_a_latlon(x: float, y: float) -> Coordenada:
    """Plano local (unidades de 100 m) -> (lat, lon). O(1)."""
    lat = ORIGEN_LAT + (y * UNIDAD_M) / _M_POR_GRADO_LAT
    lon = ORIGEN_LON + (x * UNIDAD_M) / _M_POR_GRADO_LON
    return lat, lon


def latlon_a_xy(lat: float, lon: float) -> tuple[float, float]:
    """(lat, lon) -> plano local (unidades de 100 m). Inversa exacta de ``xy_a_latlon``."""
    x = (lon - ORIGEN_LON) * _M_POR_GRADO_LON / UNIDAD_M
    y = (lat - ORIGEN_LAT) * _M_POR_GRADO_LAT / UNIDAD_M
    return x, y


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia sobre la esfera entre dos puntos (lat, lon), en metros. O(1)."""
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df, dl = f2 - f1, math.radians(lon2 - lon1)
    a = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(min(1.0, math.sqrt(a)))


def es_latlon_valido(lat: Any, lon: Any) -> bool:
    """True si (lat, lon) son números finitos dentro del rango geográfico."""
    try:
        return (math.isfinite(lat) and math.isfinite(lon)
                and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0)
    except TypeError:
        return False


# --------------------------------------------------------------------------- formato MapView
def formatear_para_mapview(pares: Iterable[Sequence[float]], decimales: int = 7,
                           quitar_repetidos: bool = True) -> list[Coordenada]:
    """Normaliza una secuencia de pares a ``[(lat, lon), ...]`` de floats redondeados.

    Con ``quitar_repetidos`` elimina puntos consecutivos idénticos (tkintermapview dibuja
    mal los tramos de largo cero). Lanza ValueError si algún par es inválido.
    """
    salida: list[Coordenada] = []
    for i, par in enumerate(pares):
        try:
            lat, lon = float(par[0]), float(par[1])
        except (TypeError, ValueError, IndexError):
            raise ValueError(f"Punto {i} inválido: {par!r}; se esperaba (lat, lon)") from None
        if not es_latlon_valido(lat, lon):
            raise ValueError(f"Punto {i} fuera de rango: ({lat}, {lon})")
        punto = (round(lat, decimales), round(lon, decimales))
        if quitar_repetidos and salida and salida[-1] == punto:
            continue
        salida.append(punto)
    return salida


def puntos_xy_a_coordenadas(puntos_xy: Iterable[Sequence[float]]) -> list[Coordenada]:
    """Lista de (x, y) del plano -> ``[(lat, lon), ...]`` para el mapa."""
    return formatear_para_mapview(xy_a_latlon(p[0], p[1]) for p in puntos_xy)


def poligono_de_limites(limites: Sequence[float]) -> list[Coordenada]:
    """Caja (x0, y0, x1, y1) del plano -> 4 esquinas (lat, lon) para ``map.set_polygon``."""
    x0, y0, x1, y1 = limites
    return formatear_para_mapview(xy_a_latlon(x, y)
                                  for x, y in ((x0, y1), (x1, y1), (x1, y0), (x0, y0)))


def caja_a_mapview(limites: Sequence[float]) -> tuple[Coordenada, Coordenada]:
    """Caja (x0, y0, x1, y1) -> (arriba-izquierda, abajo-derecha) para ``fit_bounding_box``."""
    x0, y0, x1, y1 = limites
    return xy_a_latlon(x0, y1), xy_a_latlon(x1, y0)


# --------------------------------------------------------------------------- IDs -> (lat, lon)
def _coordenada_de_nodo(grafo: Any, nodo_id: Any) -> Coordenada:
    """(lat, lon) de un nodo de cualquier fuente soportada; KeyError si no existe."""
    # 1) RedCusco (u objeto parecido): .nodos[id] con .lat/.lon
    nodos = getattr(grafo, "nodos", None)
    if isinstance(nodos, Mapping) and not callable(nodos):
        if nodo_id not in nodos:
            raise KeyError(f"El nodo {nodo_id!r} no existe en la red")
        nodo = nodos[nodo_id]
        return float(nodo.lat), float(nodo.lon)
    # 2) networkx.Graph: grafo.nodes[id] es un dict de atributos
    if hasattr(grafo, "nodes") and hasattr(grafo, "has_node"):
        if not grafo.has_node(nodo_id):
            raise KeyError(f"El nodo {nodo_id!r} no existe en el grafo")
        atributos = grafo.nodes[nodo_id]
        if "lat" in atributos and "lon" in atributos:
            return float(atributos["lat"]), float(atributos["lon"])
        if "x" in atributos and "y" in atributos:
            return xy_a_latlon(atributos["x"], atributos["y"])
        raise KeyError(f"El nodo {nodo_id!r} no tiene atributos lat/lon ni x/y")
    # 3) diccionario {id: (lat, lon)}
    if isinstance(grafo, Mapping):
        if nodo_id not in grafo:
            raise KeyError(f"El nodo {nodo_id!r} no está en el diccionario de coordenadas")
        lat, lon = grafo[nodo_id][:2]
        return float(lat), float(lon)
    raise TypeError(f"Tipo de grafo no soportado: {type(grafo).__name__}")


def ids_a_coordenadas(grafo: Any, ids: Iterable[Any]) -> list[Coordenada]:
    """Traductor principal: IDs de nodos -> ``[(lat, lon), ...]`` para ``tkintermapview``.

    ``grafo`` puede ser una ``RedCusco``, un ``networkx.Graph`` (con atributos de nodo
    ``lat``/``lon`` o ``x``/``y``) o un diccionario ``{id: (lat, lon)}``. ``ids`` es el
    camino devuelto por los algoritmos (por ejemplo ``['San Blas', 'Plaza de Armas']`` o los
    nodos de ``nx.shortest_path``). Lanza KeyError si algún ID no existe.

        >>> ids_a_coordenadas(red, ruta)           # [(-13.5148, -71.9747), ...]
        >>> mapa.set_path(ids_a_coordenadas(red, ruta), color="#1f77b4")
    """
    return formatear_para_mapview(_coordenada_de_nodo(grafo, i) for i in ids)


def a_networkx(red: Any, solo_abiertas: bool = False) -> Any:
    """Exporta una ``RedCusco`` a ``networkx.Graph``.

    Cada nodo lleva ``lat``, ``lon``, ``x``, ``y``; cada arista ``distancia_m``, ``peso``,
    ``tiempo_s``, ``estado`` y ``bloqueada``. Con ``solo_abiertas`` omite las calles
    bloqueadas. Requiere ``networkx`` (``pip install networkx``).
    """
    try:
        import networkx as nx
    except ImportError as error:  # pragma: no cover - depende del entorno
        raise ImportError("a_networkx necesita networkx: pip install networkx") from error
    g = nx.Graph()
    for nombre, nodo in red.nodos.items():
        g.add_node(nombre, lat=nodo.lat, lon=nodo.lon, x=nodo.x, y=nodo.y)
    for calle in red.calles():
        if solo_abiertas and calle.bloqueada:
            continue
        g.add_edge(calle.origen, calle.destino, distancia_m=calle.distancia_m,
                   peso=calle.peso, tiempo_s=calle.tiempo_efectivo_s,
                   estado=calle.estado, bloqueada=calle.bloqueada)
    return g
