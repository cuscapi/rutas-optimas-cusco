"""Trazado REAL de las calles a partir de OpenStreetMap (OSM).

Problema que resuelve: en la versión anterior cada calle de la red se dibujaba (y se medía)
como una recta entre sus dos nodos, así que las rutas atravesaban manzanas. Este módulo:

1. Descarga de la API Overpass las vías de Cusco que caen dentro de la caja de la red
   (solo con la biblioteca estándar: ``urllib``; no hace falta instalar nada más).
2. Arma el grafo de calles reales (miles de nodos de OSM) y se queda con su componente
   conexa más grande.
3. "Pega" cada uno de los 16 nodos del modelo a la intersección real más cercana.
4. Para cada una de las 29 calles del modelo busca el camino más corto por calles reales
   (A* con distancia geodésica) entre sus dos nodos: ese recorrido es el TRAZADO de la
   calle y su longitud es la longitud REAL.
5. Guarda el resultado en un archivo de caché (``datos_ejemplo/calles_osm_cusco.json``),
   así la descarga se hace una sola vez; después funciona sin internet.

``aplicar(red, cache)`` copia ese trazado a la ``RedCusco``: las rutas de TODOS los
algoritmos (que viajan por las calles del modelo) se dibujan siguiendo las calles reales y,
si se pide, las distancias pasan a ser las reales. El modelo de 16 nodos y 29 calles no
cambia, así que los algoritmos y las pruebas siguen siendo los mismos.

Datos © colaboradores de OpenStreetMap, licencia ODbL (https://www.openstreetmap.org/copyright).

Uso desde la terminal (desde la carpeta del proyecto):

    python -m src.calles_reales            # descarga y guarda la caché
    python -m src.calles_reales --forzar   # vuelve a descargar aunque ya exista
"""

from __future__ import annotations

import heapq
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .traductor import haversine_m, latlon_a_xy

# --------------------------------------------------------------------------- configuración
SERVIDORES_OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
AGENTE = "RutasCusco/3.0 (proyecto academico UNSAAC; Python urllib)"
VERSION_CACHE = 1
ARCHIVO_CACHE = Path(__file__).resolve().parent.parent / "datos_ejemplo" / "calles_osm_cusco.json"

# Vías por las que no circula un repartidor motorizado (escaleras, veredas, ciclovías...).
VIAS_EXCLUIDAS = ("footway", "steps", "path", "cycleway", "bridleway", "corridor",
                  "construction", "proposed", "platform", "elevator", "raceway",
                  "bus_guideway", "escape", "abandoned", "razed", "via_ferrata", "busway")

# Preferencia de vía al ELEGIR el trazado (no cambia la longitud que se mide): se prefieren
# avenidas y calles normales; las peatonales y de servicio solo si no hay otra opción.
FACTOR_VIA = {
    "motorway": 1.0, "trunk": 1.0, "primary": 1.0, "secondary": 1.0, "tertiary": 1.0,
    "motorway_link": 1.0, "trunk_link": 1.0, "primary_link": 1.0, "secondary_link": 1.0,
    "tertiary_link": 1.0, "unclassified": 1.05, "residential": 1.05, "living_street": 1.15,
    "road": 1.1, "service": 1.3, "pedestrian": 1.5, "track": 1.8,
}
FACTOR_VIA_DEFECTO = 1.2
MARGEN_GRADOS = 0.004          # ~450 m alrededor de la caja de la red
DESVIO_MAXIMO = 4.0            # un trazado más largo que 4 veces la recta se descarta
SNAP_MAXIMO_M = 350.0          # un nodo a más de esto de cualquier calle no se pega


class ErrorDescarga(RuntimeError):
    """No se pudo obtener la información de OpenStreetMap (sin internet, servidor caído...)."""


# --------------------------------------------------------------------------- descarga
def caja_de_red(red: Any, margen: float = MARGEN_GRADOS) -> tuple[float, float, float, float]:
    """(sur, oeste, norte, este) en grados que contiene todos los nodos de la red."""
    lats = [n.lat for n in red.nodos.values()]
    lons = [n.lon for n in red.nodos.values()]
    return (min(lats) - margen, min(lons) - margen, max(lats) + margen, max(lons) + margen)


def consulta_overpass(caja: tuple[float, float, float, float]) -> str:
    s, o, n, e = caja
    excluidas = "|".join(VIAS_EXCLUIDAS)
    return (f'[out:json][timeout:120];'
            f'(way["highway"]["highway"!~"^({excluidas})$"]["area"!="yes"]'
            f'["access"!~"^(private|no)$"]({s:.6f},{o:.6f},{n:.6f},{e:.6f}););'
            f'out body geom;')


def descargar_osm(caja: tuple[float, float, float, float], timeout: float = 150.0,
                  servidores: tuple[str, ...] = SERVIDORES_OVERPASS,
                  progreso: Callable[[float, str], None] | None = None) -> dict:
    """Descarga las vías de la caja desde Overpass. Prueba varios servidores.

    Lanza ``ErrorDescarga`` con un mensaje claro si ninguno responde."""
    datos = urllib.parse.urlencode({"data": consulta_overpass(caja)}).encode("utf-8")
    errores = []
    for i, url in enumerate(servidores):
        if progreso:
            progreso(0.1 + 0.3 * i / max(1, len(servidores)),
                     f"Descargando calles de OpenStreetMap ({urllib.parse.urlparse(url).netloc})...")
        pedido = urllib.request.Request(url, data=datos, headers={
            "User-Agent": AGENTE, "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(pedido, timeout=timeout) as respuesta:
                contenido = json.loads(respuesta.read().decode("utf-8"))
            if not isinstance(contenido, dict) or not contenido.get("elements"):
                raise ErrorDescarga("respuesta vacía")
            return contenido
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, ErrorDescarga) as error:
            errores.append(f"{urllib.parse.urlparse(url).netloc}: {error}")
            time.sleep(0.5)
    detalle = " | ".join(errores)
    pista = ""
    if "CERTIFICATE_VERIFY_FAILED" in detalle:
        pista = (" En macOS ejecuta una vez «Install Certificates.command» de la carpeta de Python;"
                 " en otros sistemas, actualiza los certificados (pip install --upgrade certifi).")
    raise ErrorDescarga("No se pudo descargar el mapa de calles de OpenStreetMap "
                        "(¿hay conexión a internet?)." + pista + " Detalle: " + detalle)


# --------------------------------------------------------------------------- grafo de calles reales
class GrafoCalles:
    """Grafo no dirigido de las calles reales: nodos de OSM con (lat, lon) y aristas con su
    largo en metros y un costo de preferencia (largo × factor de la vía).

    Nota: no se considera el sentido de circulación (como en el resto del modelo)."""

    def __init__(self) -> None:
        self.coords: dict[int, tuple[float, float]] = {}
        self.ady: dict[int, dict[int, tuple[float, float]]] = {}

    def agregar_arista(self, u: int, v: int, factor: float) -> None:
        if u == v:
            return
        (la1, lo1), (la2, lo2) = self.coords[u], self.coords[v]
        largo = haversine_m(la1, lo1, la2, lo2)
        costo = largo * factor
        anterior = self.ady.setdefault(u, {}).get(v)
        if anterior is None or costo < anterior[1]:
            self.ady[u][v] = (largo, costo)
            self.ady.setdefault(v, {})[u] = (largo, costo)

    def componente_mayor(self) -> set[int]:
        """Nodos de la componente conexa más grande (BFS). O(V + E)."""
        vistos: set[int] = set()
        mejor: set[int] = set()
        for inicio in self.ady:
            if inicio in vistos:
                continue
            comp = {inicio}
            cola = deque([inicio])
            while cola:
                u = cola.popleft()
                for v in self.ady[u]:
                    if v not in comp:
                        comp.add(v)
                        cola.append(v)
            vistos |= comp
            if len(comp) > len(mejor):
                mejor = comp
        return mejor

    def nodo_mas_cercano(self, lat: float, lon: float, permitidos: set[int]) -> tuple[int, float]:
        """(id del nodo de OSM más cercano, distancia en metros). O(V)."""
        x0, y0 = latlon_a_xy(lat, lon)
        mejor, d_mejor = None, math.inf
        for nid in permitidos:
            x, y = latlon_a_xy(*self.coords[nid])
            d = (x - x0) ** 2 + (y - y0) ** 2
            if d < d_mejor:
                mejor, d_mejor = nid, d
        if mejor is None:
            raise ValueError("El grafo de calles está vacío")
        return mejor, haversine_m(lat, lon, *self.coords[mejor])

    def camino_mas_corto(self, origen: int, destino: int) -> tuple[list[int], float]:
        """A* por costo de preferencia (heurística: distancia geodésica, admisible porque
        todos los factores son >= 1). Devuelve (ids, largo REAL en metros); ([], inf) si no
        hay camino."""
        if origen == destino:
            return [origen], 0.0
        lat_d, lon_d = self.coords[destino]
        g = {origen: 0.0}
        padre: dict[int, int] = {}
        abiertos = [(haversine_m(*self.coords[origen], lat_d, lon_d), 0.0, origen)]
        cerrados: set[int] = set()
        while abiertos:
            _, costo, u = heapq.heappop(abiertos)
            if u in cerrados:
                continue
            if u == destino:
                camino = [u]
                while camino[-1] != origen:
                    camino.append(padre[camino[-1]])
                camino.reverse()
                largo = sum(self.ady[a][b][0] for a, b in zip(camino, camino[1:]))
                return camino, largo
            cerrados.add(u)
            for v, (_, c) in self.ady[u].items():
                nuevo = costo + c
                if nuevo < g.get(v, math.inf):
                    g[v] = nuevo
                    padre[v] = u
                    h = haversine_m(*self.coords[v], lat_d, lon_d)
                    heapq.heappush(abiertos, (nuevo + h, nuevo, v))
        return [], math.inf


def construir_grafo(osm: dict) -> GrafoCalles:
    """Arma el ``GrafoCalles`` desde la respuesta JSON de Overpass.

    Acepta tanto ``out geom`` (cada vía trae 'geometry') como ``out body; >; out skel``
    (nodos sueltos con lat/lon)."""
    g = GrafoCalles()
    for e in osm.get("elements", []):
        if e.get("type") == "node" and "lat" in e and "lon" in e:
            g.coords[int(e["id"])] = (float(e["lat"]), float(e["lon"]))
    for e in osm.get("elements", []):
        if e.get("type") != "way":
            continue
        tags = e.get("tags", {}) or {}
        via = tags.get("highway", "")
        if not via or via in VIAS_EXCLUIDAS or tags.get("area") == "yes":
            continue
        ids = [int(n) for n in e.get("nodes", [])]
        geometria = e.get("geometry") or []
        if geometria and len(geometria) == len(ids):
            for nid, punto in zip(ids, geometria):
                if punto and "lat" in punto:
                    g.coords.setdefault(nid, (float(punto["lat"]), float(punto["lon"])))
        ids = [n for n in ids if n in g.coords]
        factor = FACTOR_VIA.get(via, FACTOR_VIA_DEFECTO)
        for u, v in zip(ids, ids[1:]):
            g.agregar_arista(u, v, factor)
    return g


def simplificar(puntos: list[tuple[float, float]], tolerancia_m: float = 2.0) -> list[tuple[float, float]]:
    """Douglas-Peucker: quita puntos casi alineados (menos de 'tolerancia_m' de desvío)."""
    if len(puntos) <= 2:
        return list(puntos)
    xy = [latlon_a_xy(lat, lon) for lat, lon in puntos]
    tol = tolerancia_m / 100.0  # el plano local está en unidades de 100 m
    conservar = [False] * len(puntos)
    conservar[0] = conservar[-1] = True
    pila = [(0, len(puntos) - 1)]
    while pila:
        i, j = pila.pop()
        (x1, y1), (x2, y2) = xy[i], xy[j]
        dx, dy = x2 - x1, y2 - y1
        largo = math.hypot(dx, dy)
        peor, k_peor = -1.0, -1
        for k in range(i + 1, j):
            x0, y0 = xy[k]
            d = (abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / largo if largo
                 else math.hypot(x0 - x1, y0 - y1))
            if d > peor:
                peor, k_peor = d, k
        if peor > tol:
            conservar[k_peor] = True
            pila.append((i, k_peor))
            pila.append((k_peor, j))
    return [p for p, ok in zip(puntos, conservar) if ok]


# --------------------------------------------------------------------------- trazado de la red del modelo
def trazar_red(red: Any, osm: dict, progreso: Callable[[float, str], None] | None = None) -> dict:
    """Calcula el trazado real de cada calle de 'red' con los datos 'osm'. Devuelve el
    diccionario de caché (ver ``guardar_cache``); no modifica la red."""
    g = construir_grafo(osm)
    if not g.ady:
        raise ErrorDescarga("Los datos de OpenStreetMap no tienen calles en la zona.")
    comp = g.componente_mayor()
    if progreso:
        progreso(0.5, f"Grafo de calles reales: {len(g.coords)} puntos, {len(comp)} conectados.")

    nodos, pegado = {}, {}
    for nombre, n in red.nodos.items():
        nid, d = g.nodo_mas_cercano(n.lat, n.lon, comp)
        pegado[nombre] = nid if d <= SNAP_MAXIMO_M else None
        lat, lon = g.coords[nid]
        nodos[nombre] = {"original": [n.lat, n.lon], "real": [lat, lon], "distancia_m": round(d, 1),
                         "pegado": d <= SNAP_MAXIMO_M}

    calles = []
    lista = red.calles()
    for i, c in enumerate(lista, 1):
        if progreso:
            progreso(0.5 + 0.45 * i / len(lista), f"Trazando {c.origen} — {c.destino}...")
        a, b = pegado[c.origen], pegado[c.destino]
        registro = {"origen": c.origen, "destino": c.destino, "estado": "recta"}
        if a is not None and b is not None:
            ids, largo = g.camino_mas_corto(a, b)
            recta = haversine_m(*g.coords[a], *g.coords[b])
            if ids and largo <= max(DESVIO_MAXIMO * recta, recta + 250.0):
                puntos = simplificar([g.coords[k] for k in ids])
                registro.update({"estado": "ok", "largo_m": round(largo, 1),
                                 "geometria": [[round(la, 7), round(lo, 7)] for la, lo in puntos]})
            elif ids:
                registro["motivo"] = f"desvío excesivo ({largo:.0f} m frente a {recta:.0f} m en recta)"
            else:
                registro["motivo"] = "sin camino por calles reales"
        else:
            registro["motivo"] = "un extremo está lejos de toda calle real"
        calles.append(registro)

    return {
        "version": VERSION_CACHE,
        "creado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": "© colaboradores de OpenStreetMap (ODbL) vía Overpass API",
        "caja": list(caja_de_red(red)),
        "puntos_osm": len(g.coords),
        "nodos": nodos,
        "calles": calles,
    }


# --------------------------------------------------------------------------- caché
def guardar_cache(cache: dict, ruta: str | os.PathLike | None = None) -> Path:
    ruta = Path(ruta or ARCHIVO_CACHE)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(json.dumps(cache, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temporal, ruta)
    return ruta


def cargar_cache(ruta: str | os.PathLike | None = None) -> dict | None:
    """El diccionario de caché, o None si no existe o está dañado."""
    ruta = Path(ruta or ARCHIVO_CACHE)
    if not ruta.exists():
        return None
    try:
        cache = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cache, dict) or cache.get("version") != VERSION_CACHE:
        return None
    return cache


def aplicar(red: Any, cache: dict, usar_largo_real: bool = True, mover_nodos: bool = True,
            tolerancia_m: float = 400.0) -> dict:
    """Copia el trazado real de la caché a la red.

    * Cada nodo se mueve a la intersección real donde se pegó (si está a menos de
      'tolerancia_m' de su posición original guardada en la caché).
    * Cada calle con trazado "ok" recibe su geometría y, con 'usar_largo_real', su
      longitud real (y el tiempo de recorrido según su tipo de vía).
    Devuelve un resumen {"calles_reales", "calles_rectas", "nodos_movidos", "faltantes"}.
    """
    resumen = {"calles_reales": 0, "calles_rectas": 0, "nodos_movidos": 0, "faltantes": []}
    nodos = cache.get("nodos", {})
    if mover_nodos:
        for nombre, info in nodos.items():
            if nombre not in red.nodos or not info.get("pegado", True):
                continue
            n = red.nodos[nombre]
            olat, olon = info.get("original", [n.lat, n.lon])
            if haversine_m(n.lat, n.lon, olat, olon) > tolerancia_m:
                continue  # la red cargada no es la misma de la caché
            lat, lon = info["real"]
            if abs(lat - n.lat) > 1e-9 or abs(lon - n.lon) > 1e-9:
                red.mover_nodo(nombre, lat, lon)
                resumen["nodos_movidos"] += 1
    por_clave = {frozenset((c["origen"], c["destino"])): c for c in cache.get("calles", [])}
    for calle in red.calles():
        registro = por_clave.get(calle.clave)
        if registro is None:
            resumen["faltantes"].append(f"{calle.origen} — {calle.destino}")
            continue
        if registro.get("estado") != "ok" or not registro.get("geometria"):
            resumen["calles_rectas"] += 1
            continue
        puntos = registro["geometria"]
        origen = registro["origen"] if registro["origen"] in (calle.origen, calle.destino) else calle.origen
        destino = calle.destino if origen == calle.origen else calle.origen
        largo = registro.get("largo_m") if usar_largo_real else None
        if largo is not None and calle.distancia_base_m is None:
            calle.distancia_base_m = calle.distancia_m
        if not usar_largo_real and calle.distancia_base_m is not None:
            largo = calle.distancia_base_m
        red.establecer_geometria(origen, destino, puntos, "osm", largo)
        resumen["calles_reales"] += 1
    return resumen


def obtener(red: Any, forzar: bool = False, ruta: str | os.PathLike | None = None,
            progreso: Callable[[float, str], None] | None = None) -> dict:
    """Caché lista para ``aplicar``: la lee del disco o, si falta (o 'forzar'), la descarga y
    la calcula. Puede lanzar ``ErrorDescarga``."""
    if not forzar:
        cache = cargar_cache(ruta)
        if cache is not None and _cubre_red(cache, red):
            return cache
    if progreso:
        progreso(0.05, "Conectando con OpenStreetMap...")
    osm = descargar_osm(caja_de_red(red), progreso=progreso)
    cache = trazar_red(red, osm, progreso)
    guardar_cache(cache, ruta)
    if progreso:
        progreso(1.0, "Calles reales listas.")
    return cache


def _cubre_red(cache: dict, red: Any) -> bool:
    claves = {frozenset((c["origen"], c["destino"])) for c in cache.get("calles", [])}
    return all(c.clave in claves for c in red.calles())


def resumen_texto(cache: dict) -> str:
    ok = sum(1 for c in cache.get("calles", []) if c.get("estado") == "ok")
    total = len(cache.get("calles", []))
    lineas = [f"Calles con trazado real: {ok}/{total} (datos {cache.get('fuente', 'OSM')}, "
              f"{cache.get('creado', '')})."]
    for c in cache.get("calles", []):
        if c.get("estado") != "ok":
            lineas.append(f"  {c['origen']} — {c['destino']}: en recta ({c.get('motivo', '')})")
    lejanos = [f"{n} ({i['distancia_m']:.0f} m)" for n, i in cache.get("nodos", {}).items()
               if i.get("distancia_m", 0) > 60]
    if lejanos:
        lineas.append("  Nodos que se movieron más de 60 m para quedar sobre una calle: "
                      + ", ".join(lejanos))
    return "\n".join(lineas)


if __name__ == "__main__":  # pragma: no cover - requiere internet
    import argparse

    from . import datos

    parser = argparse.ArgumentParser(description="Descarga el trazado real de las calles (OSM).")
    parser.add_argument("--forzar", action="store_true", help="volver a descargar aunque exista la caché")
    parser.add_argument("--red", help="red .json propia (por defecto, la de Cusco del proyecto)")
    parser.add_argument("--archivo", default=str(ARCHIVO_CACHE), help="dónde guardar la caché")
    args = parser.parse_args()
    red_modelo = datos.cargar_red(args.red) if args.red else datos.crear_red()
    try:
        resultado = obtener(red_modelo, args.forzar, args.archivo,
                            lambda f, t: print(f"[{f * 100:5.1f} %] {t}"))
    except ErrorDescarga as error:
        raise SystemExit(str(error))
    print(resumen_texto(resultado))
    print("Caché:", args.archivo)
