"""Datos del sistema de rutas de Cusco: red vial, repartidores y pedidos.

Dos orígenes de datos, con la misma interfaz:

a) Sintéticos: ``crear_red()`` arma las intersecciones y calles de Cusco (distancias en
   metros y tiempos de recorrido según el tipo de calle) y ``generar_pedidos()`` crea
   pedidos aleatorios pero coherentes (misma semilla, mismos datos).
b) Archivos: ``guardar_red`` / ``cargar_red`` y ``guardar_pedidos`` / ``cargar_pedidos``
   leen y escriben JSON o CSV según la extensión del archivo.

``Escenario`` junta red + pedidos + repartidores + depósito y ofrece las consultas
rápidas que usan la GUI y los algoritmos.

Los nodos tienen coordenadas reales aproximadas (lat, lon) de lugares del Cusco; el plano
local (x, y en unidades de 100 m) se deriva de ellas con ``traductor``. La distancia de cada
calle es la distancia geodésica entre sus extremos por un factor de sinuosidad según el
tipo de vía (aproximada, no medida en terreno). Con un archivo JSON/CSV se pueden poner
coordenadas y distancias reales por calle, por ejemplo tomadas de OpenStreetMap.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .modelos import (ESTADO_PENDIENTE, Calle, Pedido, Punto, Repartidor)
from .ordenacion import merge_sort
from .red import RedCusco, RedVial
from .traductor import UNIDAD_M, haversine_m, latlon_a_xy
from .voraz import dijkstra_todos

# --------------------------------------------------------------------------- constantes
DEPOSITO_NODO = "Av. El Sol"
VERSION_FORMATO = 2

# Coordenadas reales APROXIMADAS (lat, lon) de cada intersección/lugar. Son puntos de
# referencia para la demostración; para precisión de calle, reemplázalas en red_cusco.json
# (o en red_cusco_nodos.csv) con valores tomados de OpenStreetMap o Google Maps.
NODOS_LATLON: dict[str, tuple[float, float]] = {
    "San Blas": (-13.51480, -71.97470),
    "San Cristóbal": (-13.51430, -71.98120),
    "Plaza de Armas": (-13.51700, -71.97850),
    "Santa Ana": (-13.51250, -71.97080),
    "Zaguán del Cielo": (-13.51620, -71.97010),
    "Estadio Universitario": (-13.52370, -71.95730),
    "Av. de la Cultura": (-13.52620, -71.95450),
    "Wanchaq": (-13.53300, -71.95200),
    "Mercado Huanchaq": (-13.53000, -71.96500),
    "Av. El Sol": (-13.51860, -71.97690),
    "Coricancha": (-13.51950, -71.97530),
    "Mercado Central": (-13.52110, -71.98240),
    "San Francisco": (-13.52030, -71.98130),
    "San Pedro": (-13.52310, -71.98180),
    "Av. Pardo": (-13.52650, -71.97200),
    "San Sebastián": (-13.53250, -71.92500),
}

# Posición de cada nodo en el plano local (x, y), derivada de las coordenadas reales.
NODOS: dict[str, tuple[float, float]] = {
    nombre: latlon_a_xy(lat, lon) for nombre, (lat, lon) in NODOS_LATLON.items()}


def _caja_de_nodos(margen: float = 2.0) -> tuple[float, float, float, float]:
    xs = [x for x, _ in NODOS.values()]
    ys = [y for _, y in NODOS.values()]
    return (min(xs) - margen, min(ys) - margen, max(xs) + margen, max(ys) + margen)


LIMITES = _caja_de_nodos()  # caja (x0, y0, x1, y1) del plano que contiene toda la red

# Una calle real es más larga que la recta entre sus extremos: factor por tipo de vía.
SINUOSIDAD = {"avenida": 1.10, "calle": 1.20, "empinada": 1.35}

CALLES = [
    ("San Blas", "San Cristóbal"),
    ("San Blas", "Santa Ana"),
    ("San Blas", "Plaza de Armas"),
    ("San Blas", "Zaguán del Cielo"),
    ("San Cristóbal", "Plaza de Armas"),
    ("San Cristóbal", "San Francisco"),
    ("Plaza de Armas", "San Francisco"),
    ("Plaza de Armas", "Av. El Sol"),
    ("Plaza de Armas", "Estadio Universitario"),
    ("Santa Ana", "Zaguán del Cielo"),
    ("Zaguán del Cielo", "Av. de la Cultura"),
    ("Zaguán del Cielo", "Estadio Universitario"),
    ("Estadio Universitario", "Av. de la Cultura"),
    ("Estadio Universitario", "Coricancha"),
    ("Av. El Sol", "Coricancha"),
    ("Av. El Sol", "San Francisco"),
    ("Av. El Sol", "Mercado Central"),
    ("Mercado Central", "San Francisco"),
    ("Mercado Central", "San Pedro"),
    ("San Pedro", "Av. El Sol"),
    ("Coricancha", "Mercado Huanchaq"),
    ("Coricancha", "Av. Pardo"),
    ("Mercado Huanchaq", "Av. de la Cultura"),
    ("Mercado Huanchaq", "Wanchaq"),
    ("Mercado Huanchaq", "Av. Pardo"),
    ("Av. de la Cultura", "Wanchaq"),
    ("Av. Pardo", "Wanchaq"),
    ("Wanchaq", "San Sebastián"),
    ("Av. Pardo", "San Sebastián"),
]

CALLES_CERRADAS_EJEMPLO = [
    ("San Blas", "Zaguán del Cielo"),
    ("Zaguán del Cielo", "Av. de la Cultura"),
]

# Tipo de calle (define la velocidad con la vía libre). Las no listadas son "calle".
_AVENIDAS = [
    ("Plaza de Armas", "Av. El Sol"), ("Av. El Sol", "Coricancha"),
    ("Av. El Sol", "Mercado Central"), ("Estadio Universitario", "Av. de la Cultura"),
    ("Mercado Huanchaq", "Av. de la Cultura"), ("Av. de la Cultura", "Wanchaq"),
    ("Coricancha", "Av. Pardo"), ("Av. Pardo", "Wanchaq"),
    ("Mercado Huanchaq", "Av. Pardo"), ("Wanchaq", "San Sebastián"),
    ("Av. Pardo", "San Sebastián"),
]
_EMPINADAS = [
    ("San Blas", "San Cristóbal"), ("San Blas", "Santa Ana"), ("San Blas", "Plaza de Armas"),
    ("San Blas", "Zaguán del Cielo"), ("San Cristóbal", "Plaza de Armas"),
    ("San Cristóbal", "San Francisco"), ("Santa Ana", "Zaguán del Cielo"),
]
TIPOS_CALLE: dict[frozenset[str], str] = {
    **{frozenset(par): "avenida" for par in _AVENIDAS},
    **{frozenset(par): "empinada" for par in _EMPINADAS},
}

# Criterios de ordenación listos para la GUI: nombre -> (función clave, ¿mayor primero?).
CRITERIOS_ORDEN: dict[str, tuple[Callable[[Pedido], Any], bool]] = {
    "urgencia": (lambda p: p.urgencia, True),
    "peso": (lambda p: p.peso, False),
    "valor": (lambda p: p.valor, True),
    "valor_por_kg": (lambda p: p.valor_por_kg, True),
    "ventana_fin": (lambda p: p.ventana_fin, False),
    "id": (lambda p: p.id, False),
}

CUADRANTES = ("NO", "NE", "SO", "SE")  # N = y grande (arriba en el mapa), E = x grande


# --------------------------------------------------------------------------- red sintética
def clave_calle(a: str, b: str) -> frozenset[str]:
    """Clave no dirigida de una calle: la misma para (a, b) y (b, a)."""
    return frozenset((a, b))


def costo_calle(a: str, b: str, tipo: str | None = None) -> float:
    """Longitud sintética en metros de la calle entre dos nodos de ``NODOS_LATLON``.

    Distancia geodésica entre extremos por el factor de sinuosidad del tipo de vía
    (por defecto, el tipo que le corresponde en ``TIPOS_CALLE``).
    """
    (lat_a, lon_a), (lat_b, lon_b) = NODOS_LATLON[a], NODOS_LATLON[b]
    tipo = tipo or TIPOS_CALLE.get(clave_calle(a, b), "calle")
    return haversine_m(lat_a, lon_a, lat_b, lon_b) * SINUOSIDAD[tipo]


def crear_red(bloqueadas: Iterable[tuple[str, str]] = (), metrica: str = "peso") -> RedCusco:
    """Red vial sintética de Cusco: 16 intersecciones y 29 calles.

    La distancia de cada calle es la distancia geodésica entre sus extremos (con factor
    de sinuosidad por tipo de vía) en metros; el tiempo sale
    de la velocidad de su tipo (avenida 35 km/h, calle 22, empinada 12).
    'bloqueadas' es una lista de pares (a, b) que arrancan con la calle bloqueada.
    """
    red = RedCusco(metrica)
    for nombre, (lat, lon) in NODOS_LATLON.items():
        x, y = NODOS[nombre]
        red.agregar_nodo(nombre, x, y, lat, lon)
    for a, b in CALLES:
        tipo = TIPOS_CALLE.get(clave_calle(a, b), "calle")
        red.agregar_calle(Calle(a, b, costo_calle(a, b, tipo), tipo=tipo))
    for a, b in bloqueadas:
        red.bloquear_calle(a, b)
    return red


def aplicar_trafico_aleatorio(red: RedCusco, semilla: int = 1, probabilidad: float = 0.3,
                              maximo: float = 2.5) -> None:
    """Asigna un factor de tráfico aleatorio (entre 1.2 y 'maximo') a una parte de las calles."""
    azar = random.Random(semilla)
    for calle in red.calles():
        if azar.random() < probabilidad:
            calle.establecer_trafico(round(azar.uniform(1.2, maximo), 2))


def construir_grafo(red: RedCusco | None = None) -> dict[str, list[tuple[str, float]]]:
    """Lista de adyacencia {nodo: [(vecino, metros), ...]} sin calles bloqueadas. O(V + E)."""
    return (red or crear_red()).a_adyacencia()


def sector_mas_cercano(x: float, y: float, red: RedCusco | None = None) -> str:
    """Nombre del nodo del mapa más cercano a (x, y). O(V)."""
    if red is None:
        return min(NODOS, key=lambda n: math.hypot(NODOS[n][0] - x, NODOS[n][1] - y))
    return red.nodo_mas_cercano(x, y)


def crear_repartidores() -> list[Repartidor]:
    """Tres repartidores con su base en un cruce y su capacidad en kg."""
    bases = [("Repartidor A", "San Francisco", "#d62728"),
             ("Repartidor B", "Zaguán del Cielo", "#1f77b4"),
             ("Repartidor C", "Wanchaq", "#9467bd")]
    return [Repartidor(nombre, NODOS[nodo][0], NODOS[nodo][1], 30, color, nodo)
            for nombre, nodo, color in bases]


def crear_deposito(nodo: str = DEPOSITO_NODO, red: RedCusco | None = None) -> Punto:
    """El depósito está en un cruce del mapa."""
    if red is None:
        x, y = NODOS[nodo]
    else:
        n = red.nodos[nodo]
        x, y = n.x, n.y
    return Punto("Depósito", nodo, x, y)


def proyectar_en_calle(x: float, y: float,
                       red: RedCusco | None = None) -> tuple[tuple[str, str], float, float, float]:
    """Punto de calle más cercano a (x, y). Devuelve (calle, t, px, py). O(E)."""
    red = red or crear_red()
    calle, _distancia, t, px, py = red.calle_mas_cercana(x, y)
    return (calle.origen, calle.destino), t, px, py


# --------------------------------------------------------------------------- pedidos sintéticos
# Plazo (minutos de holgura sobre la llegada estimada) según la urgencia.
_PLAZO_MIN = {5: (15, 40), 4: (30, 75), 3: (60, 150), 2: (120, 240), 1: (180, 360)}


def _minutos_desde(red: RedCusco, nodo: str) -> dict[str, float]:
    """Minutos de viaje (con el tráfico actual) desde 'nodo' a cada nodo alcanzable."""
    segundos, _ = dijkstra_todos(red.a_adyacencia("tiempo"), nodo)
    return {n: s / 60 for n, s in segundos.items()}


def generar_pedidos(cantidad: int, semilla: int = 7, red: RedCusco | None = None,
                    deposito: str = DEPOSITO_NODO) -> list[Pedido]:
    """Genera pedidos aleatorios sobre las calles (misma semilla, mismos datos).

    Cada pedido sale del nodo 'deposito' hacia un punto de una calle (elegida con
    probabilidad proporcional a su largo). Datos coherentes entre sí:
      * volumen_m3 sale del peso con una densidad entre 60 y 200 kg/m3;
      * la ventana de tiempo (minutos desde el inicio de la jornada) deja al menos el
        tiempo de viaje desde el depósito, y es más corta cuanto más urgente.
    Posición, urgencia, peso y valor usan el mismo generador de siempre, así que con una
    semilla dada coinciden con las versiones anteriores del proyecto.
    """
    if cantidad < 0:
        raise ValueError("cantidad no puede ser negativa")
    red = red or crear_red()
    azar = random.Random(semilla)
    azar_extra = random.Random(semilla * 7919 + 13)  # campos nuevos: no alteran los anteriores
    calles = red.calles()
    largos = [c.distancia_m for c in calles]
    minutos = _minutos_desde(red, deposito) if deposito in red.nodos else {}

    pedidos = []
    for i in range(1, cantidad + 1):
        calle = azar.choices(calles, weights=largos)[0]
        t = azar.uniform(0.15, 0.85)
        # sobre el trazado real de la calle si lo tiene (si no, sobre la recta: igual que antes)
        x, y = red.punto_en_calle(calle.origen, calle.destino, t)
        urgencia = azar.randint(1, 5)
        peso = azar.randint(1, 12)
        valor = 10 * urgencia + azar.randint(5, 40)

        densidad = azar_extra.uniform(60, 200)
        inicio = 0 if urgencia >= 4 else 5 * azar_extra.randint(0, 18)
        plazo = azar_extra.randint(*_PLAZO_MIN[urgencia])
        viaje = min(minutos.get(calle.origen, math.inf) + t * calle.tiempo_efectivo_s / 60,
                    minutos.get(calle.destino, math.inf) + (1 - t) * calle.tiempo_efectivo_s / 60)
        llegada = 0 if math.isinf(viaje) else math.ceil(viaje)
        fin = 5 * math.ceil((max(llegada, inicio) + plazo) / 5)

        pedidos.append(Pedido(
            id=f"P{i:02d}", cliente=f"Cliente {i}", x=x, y=y,
            urgencia=urgencia, peso=peso, valor=valor,
            sector=red.nodo_mas_cercano(x, y), calle=(calle.origen, calle.destino), t=t,
            origen=deposito, volumen_m3=round(max(0.005, peso / densidad), 3),
            ventana_inicio=inicio, ventana_fin=fin,
        ))
    return pedidos


# --------------------------------------------------------------------------- archivos
CAMPOS_NODO = ("nombre", "lat", "lon", "x", "y")
CAMPOS_CALLE = ("origen", "destino", "distancia_m", "tiempo_s", "estado", "factor_trafico", "tipo")
CAMPOS_PEDIDO = ("id", "cliente", "x", "y", "lat", "lon", "urgencia", "peso", "valor", "sector", "calle", "t",
                 "origen", "destino", "volumen_m3", "ventana_inicio", "ventana_fin", "estado")
CAMPOS_REPARTIDOR = ("nombre", "x", "y", "lat", "lon", "capacidad", "color", "nodo",
                     "capacidad_volumen_m3", "velocidad_kmh")


def _escribir_atomico(ruta: Path, texto: str, encoding: str = "utf-8") -> None:
    """Escribe en un archivo temporal y lo renombra: nunca deja un archivo a medias."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(texto, encoding=encoding, newline="")
    os.replace(temporal, ruta)


def _guardar_tabla(registros: Sequence[dict[str, Any]], campos: Sequence[str],
                   ruta: Path, clave_json: str) -> None:
    """Guarda una lista de diccionarios como JSON ({version, clave_json: [...]}) o CSV."""
    if ruta.suffix.lower() == ".json":
        cuerpo = {"version": VERSION_FORMATO, clave_json: list(registros)}
        _escribir_atomico(ruta, json.dumps(cuerpo, ensure_ascii=False, indent=2) + "\n")
    elif ruta.suffix.lower() == ".csv":
        salida = io.StringIO(newline="")
        escritor = csv.DictWriter(salida, fieldnames=list(campos), lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(registros)
        _escribir_atomico(ruta, salida.getvalue(), encoding="utf-8-sig")
    else:
        raise ValueError(f"Formato no soportado {ruta.suffix!r}: use .json o .csv")


def _cargar_tabla(ruta: Path, clave_json: str) -> list[dict[str, Any]]:
    """Lee una tabla JSON (lista o {clave_json: [...]}) o CSV como lista de diccionarios."""
    sufijo = ruta.suffix.lower()
    if sufijo == ".json":
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        if isinstance(contenido, dict):
            if clave_json not in contenido:
                raise ValueError(f"{ruta}: falta la clave '{clave_json}'")
            contenido = contenido[clave_json]
        if not isinstance(contenido, list):
            raise ValueError(f"{ruta}: se esperaba una lista de '{clave_json}'")
        return contenido
    if sufijo == ".csv":
        with ruta.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    raise ValueError(f"Formato no soportado {ruta.suffix!r}: use .json o .csv")


def _construir(fabrica: Callable[[dict[str, Any]], Any], filas: list[dict[str, Any]],
               ruta: Path) -> list[Any]:
    """Crea un objeto por fila indicando archivo y fila si algo está mal."""
    resultado = []
    for n, fila in enumerate(filas, 1):
        try:
            resultado.append(fabrica(fila))
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f"{ruta.name}, registro {n}: {error}") from error
    return resultado


def _rutas_csv_red(ruta: Path) -> tuple[Path, Path]:
    """red.csv, red_nodos.csv o red_calles.csv -> (red_nodos.csv, red_calles.csv)."""
    base = ruta.stem
    for sufijo in ("_nodos", "_calles"):
        if base.endswith(sufijo):
            base = base[: -len(sufijo)]
    return (ruta.with_name(f"{base}_nodos.csv"), ruta.with_name(f"{base}_calles.csv"))


def guardar_red(red: RedCusco, ruta: str | os.PathLike) -> list[Path]:
    """Guarda la red (con el estado y tráfico de cada calle).

    .json -> un archivo ({version, unidad_mapa_m, nodos, calles}).
    .csv  -> dos archivos: <base>_nodos.csv y <base>_calles.csv.
    Devuelve las rutas escritas.
    """
    ruta = Path(ruta)
    datos = red.to_dict()
    if ruta.suffix.lower() == ".json":
        cuerpo = {"version": VERSION_FORMATO, "unidad_mapa_m": UNIDAD_M,
                  "sistema": "WGS84 (lat, lon); x, y = plano local en unidades de 100 m", **datos}
        _escribir_atomico(ruta, json.dumps(cuerpo, ensure_ascii=False, indent=2) + "\n")
        return [ruta]
    if ruta.suffix.lower() == ".csv":
        r_nodos, r_calles = _rutas_csv_red(ruta)
        calles = [{k: v for k, v in c.items() if k in CAMPOS_CALLE} for c in datos["calles"]]
        _guardar_tabla(datos["nodos"], CAMPOS_NODO, r_nodos, "nodos")
        _guardar_tabla(calles, CAMPOS_CALLE, r_calles, "calles")
        return [r_nodos, r_calles]
    raise ValueError(f"Formato no soportado {ruta.suffix!r}: use .json o .csv")


def cargar_red(ruta: str | os.PathLike, metrica: str = "peso") -> RedCusco:
    """Carga una red desde .json o .csv (ver ``guardar_red``) y la valida.

    Lanza ValueError con el archivo y registro si hay datos inválidos, nodos repetidos
    o calles que apuntan a nodos inexistentes.
    """
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".json":
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        try:
            return RedCusco.from_dict(contenido, metrica)
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f"{ruta.name}: {error}") from error
    r_nodos, r_calles = _rutas_csv_red(ruta)
    try:
        return RedCusco.from_dict({"nodos": _cargar_tabla(r_nodos, "nodos"),
                                   "calles": _cargar_tabla(r_calles, "calles")}, metrica)
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{ruta.stem}: {error}") from error


def guardar_pedidos(pedidos: Iterable[Pedido], ruta: str | os.PathLike) -> Path:
    """Guarda los pedidos en .json (lista) o .csv (la calle se escribe como "a|b")."""
    ruta = Path(ruta)
    registros = []
    for p in pedidos:
        d = p.to_dict(geo=True)
        if ruta.suffix.lower() == ".csv":
            d["calle"] = "|".join(d["calle"])
        registros.append(d)
    _guardar_tabla(registros, CAMPOS_PEDIDO, ruta, "pedidos")
    return ruta


def cargar_pedidos(ruta: str | os.PathLike, red: RedCusco | None = None) -> list[Pedido]:
    """Carga pedidos desde .json o .csv y valida cada uno (peso > 0, urgencia 1-5, etc.).

    Con 'red' además se comprueba que cada pedido esté sobre una calle existente (y en
    la posición que dice su 't'); si el archivo solo trae x, y se proyecta sobre la
    calle más cercana y se completan calle, t, sector y destino.
    Lanza ValueError con el registro problemático o si hay IDs repetidos.
    """
    ruta = Path(ruta)
    pedidos = _construir(Pedido.from_dict, _cargar_tabla(ruta, "pedidos"), ruta)
    vistos: set[str] = set()
    for p in pedidos:
        if p.id in vistos:
            raise ValueError(f"{ruta.name}: el id {p.id!r} está repetido")
        vistos.add(p.id)
        if red is not None:
            _ajustar_a_la_red(p, red, ruta)
    return pedidos


def _ajustar_a_la_red(p: Pedido, red: RedCusco, ruta: Path) -> None:
    """Comprueba/completa la ubicación de un pedido sobre las calles de 'red'."""
    if not p.calle:
        calle, t, px, py = proyectar_en_calle(p.x, p.y, red)
        p.calle, p.t, p.x, p.y = calle, t, px, py
    else:
        if not red.existe_calle(*p.calle):
            raise ValueError(f"{ruta.name}: el pedido {p.id!r} está sobre la calle "
                             f"{p.calle!r}, que no existe en la red")
        if not 0.0 <= p.t <= 1.0:
            raise ValueError(f"{ruta.name}: el pedido {p.id!r} tiene t = {p.t!r} fuera de [0, 1]")
        # Mandan la calle y t: si el archivo se guardó con otro trazado (recta u OSM), el
        # punto se recoloca sobre el trazado actual en vez de rechazar el archivo.
        p.x, p.y = red.punto_en_calle(p.calle[0], p.calle[1], p.t)
    if not p.sector:
        p.sector = red.nodo_mas_cercano(p.x, p.y)
    if not p.destino:
        p.destino = p.sector
    p.validar()


def guardar_repartidores(repartidores: Iterable[Repartidor], ruta: str | os.PathLike) -> Path:
    ruta = Path(ruta)
    _guardar_tabla([r.to_dict(geo=True) for r in repartidores], CAMPOS_REPARTIDOR, ruta, "repartidores")
    return ruta


def cargar_repartidores(ruta: str | os.PathLike) -> list[Repartidor]:
    ruta = Path(ruta)
    return _construir(Repartidor.from_dict, _cargar_tabla(ruta, "repartidores"), ruta)


# --------------------------------------------------------------------------- Escenario
@dataclass
class Escenario:
    """Todo lo que necesita una simulación: red, pedidos, repartidores y depósito.

    Es el punto único de acceso a los datos para main.py, la GUI y los algoritmos:
    ``Escenario.sintetico()`` o ``Escenario.cargar(...)`` para crearlo, ``obtener_*`` para
    consultarlo y ``crear_red_vial()`` para tener las distancias por calles.
    """
    red: RedCusco
    pedidos: list[Pedido] = field(default_factory=list)
    repartidores: list[Repartidor] = field(default_factory=list)
    deposito: Punto | None = None

    def __post_init__(self) -> None:
        if self.deposito is None:
            self.deposito = crear_deposito(self._nodo_deposito(), self.red)

    def _nodo_deposito(self) -> str:
        if DEPOSITO_NODO in self.red.nodos:
            return DEPOSITO_NODO
        return next(iter(self.red.nodos))

    # -- creación
    @classmethod
    def sintetico(cls, cantidad: int = 18, semilla: int = 7) -> "Escenario":
        """Cusco sintético con 'cantidad' pedidos aleatorios y 3 repartidores."""
        red = crear_red()
        return cls(red, generar_pedidos(cantidad, semilla, red), crear_repartidores())

    @classmethod
    def cargar(cls, ruta_red: str | os.PathLike, ruta_pedidos: str | os.PathLike,
               ruta_repartidores: str | os.PathLike | None = None,
               deposito_nodo: str | None = None) -> "Escenario":
        """Carga el escenario desde archivos .json/.csv y comprueba que todo cuadre.

        Sin 'ruta_repartidores' se usan los tres de ejemplo si sus bases existen en la red.
        El depósito es 'deposito_nodo', o el 'origen' del primer pedido, o "Av. El Sol".
        """
        red = cargar_red(ruta_red)
        pedidos = cargar_pedidos(ruta_pedidos, red)
        if ruta_repartidores is not None:
            repartidores = cargar_repartidores(ruta_repartidores)
        else:
            ejemplo = crear_repartidores()
            repartidores = ejemplo if all(r.nodo in red.nodos for r in ejemplo) else []
        for r in repartidores:
            if r.nodo and r.nodo not in red.nodos:
                raise ValueError(f"El repartidor {r.nombre!r} sale del nodo inexistente {r.nodo!r}")
        nodo = deposito_nodo or next((p.origen for p in pedidos if p.origen in red.nodos), None)
        if nodo is not None and nodo not in red.nodos:
            raise ValueError(f"El depósito está en un nodo inexistente: {nodo!r}")
        return cls(red, pedidos, repartidores, crear_deposito(nodo, red) if nodo else None)

    def guardar(self, directorio: str | os.PathLike, formato: str = "json") -> list[Path]:
        """Guarda red, pedidos y repartidores en 'directorio'. Devuelve los archivos escritos.

        json -> red_cusco.json, pedidos.json, repartidores.json
        csv  -> red_cusco_nodos.csv, red_cusco_calles.csv, pedidos.csv, repartidores.csv
        """
        if formato not in ("json", "csv"):
            raise ValueError("formato debe ser 'json' o 'csv'")
        d = Path(directorio)
        escritos = guardar_red(self.red, d / f"red_cusco.{formato}")
        escritos.append(guardar_pedidos(self.pedidos, d / f"pedidos.{formato}"))
        escritos.append(guardar_repartidores(self.repartidores, d / f"repartidores.{formato}"))
        return escritos

    # -- gestión de pedidos
    def pedido_por_id(self, id_: str) -> Pedido | None:
        return next((p for p in self.pedidos if p.id == id_), None)

    def siguiente_id(self) -> str:
        """Siguiente ID libre con el formato P01, P02, ..."""
        numeros = [int(p.id[1:]) for p in self.pedidos if p.id[1:].isdigit()]
        return f"P{(max(numeros) if numeros else 0) + 1:02d}"

    def agregar_pedido(self, pedido: Pedido) -> Pedido:
        """Agrega un pedido validado: ID único y calle existente en la red."""
        pedido.validar()
        if self.pedido_por_id(pedido.id) is not None:
            raise ValueError(f"Ya existe un pedido con id {pedido.id!r}")
        if pedido.calle and not self.red.existe_calle(*pedido.calle):
            raise ValueError(f"El pedido {pedido.id!r} está sobre una calle que no existe: "
                             f"{pedido.calle!r}")
        self.pedidos.append(pedido)
        return pedido

    def quitar_pedido(self, id_: str) -> bool:
        antes = len(self.pedidos)
        self.pedidos = [p for p in self.pedidos if p.id != id_]
        return len(self.pedidos) < antes

    # -- consultas rápidas (para la GUI y los algoritmos)
    def cuadrante_de(self, x: float, y: float) -> str:
        """'NO', 'NE', 'SO' o 'SE' según el centro de la caja del mapa (N = arriba)."""
        x0, y0, x1, y1 = self.red.limites()
        ns = "N" if y >= (y0 + y1) / 2 else "S"
        eo = "E" if x >= (x0 + x1) / 2 else "O"
        return ns + eo

    def obtener_pedidos_por_zona(
            self, zona: str | tuple[float, float, float, float]) -> list[Pedido]:
        """Pedidos de un cuadrante ('NO', 'NE', 'SO', 'SE') o de una caja (x0, y0, x1, y1),
        por ejemplo una de las zonas que devuelve ``divide_venceras.dividir_en_zonas``."""
        if isinstance(zona, str):
            cuadrante = zona.strip().upper()
            if cuadrante not in CUADRANTES:
                raise ValueError(f"Cuadrante desconocido {zona!r}; use uno de {CUADRANTES}")
            return [p for p in self.pedidos if self.cuadrante_de(p.x, p.y) == cuadrante]
        x0, y0, x1, y1 = zona
        return [p for p in self.pedidos if x0 <= p.x <= x1 and y0 <= p.y <= y1]

    def obtener_pedidos_por_sector(self, sector: str) -> list[Pedido]:
        return [p for p in self.pedidos if p.sector == sector]

    def obtener_pedidos_urgentes(self, umbral: int = 4) -> list[Pedido]:
        return [p for p in self.pedidos if p.es_urgente(umbral)]

    def obtener_pedidos_ordenables(self, criterio: str | None = None,
                                   inverso: bool | None = None) -> list[Pedido]:
        """Pedidos listos para ordenar/asignar: PENDIENTES y alcanzables desde el depósito
        con las calles abiertas actuales (un pedido en una calle bloqueada sigue siendo
        alcanzable desde alguno de sus extremos).

        Con 'criterio' (una clave de ``CRITERIOS_ORDEN``: urgencia, peso, valor,
        valor_por_kg, ventana_fin, id) los devuelve ordenados con MergeSort; 'inverso'
        cambia el sentido por defecto del criterio.
        """
        alcanzables = self.red.nodos_alcanzables(self.deposito.nodo)
        listos = [p for p in self.pedidos
                  if p.estado == ESTADO_PENDIENTE
                  and (not p.calle or any(n in alcanzables for n in p.calle))]
        if criterio is None:
            return listos
        if criterio not in CRITERIOS_ORDEN:
            raise ValueError(f"Criterio desconocido {criterio!r}; use uno de "
                             f"{tuple(CRITERIOS_ORDEN)}")
        clave, mayor_primero = CRITERIOS_ORDEN[criterio]
        return merge_sort(listos, clave, mayor_primero if inverso is None else inverso)

    def reubicar(self) -> None:
        """Vuelve a poner cada pedido, repartidor y el depósito sobre la red actual.

        Hace falta después de cambiar el trazado de las calles o mover nodos (por ejemplo,
        al cargar las calles reales de OpenStreetMap): cada pedido conserva su calle y su
        fracción 't', y los repartidores y el depósito vuelven a su nodo."""
        for p in self.pedidos:
            if p.calle and self.red.existe_calle(*p.calle):
                p.x, p.y = self.red.punto_en_calle(p.calle[0], p.calle[1], p.t)
        for r in self.repartidores:
            if r.nodo in self.red.nodos:
                n = self.red.nodos[r.nodo]
                r.x, r.y = n.x, n.y
        if self.deposito is not None and self.deposito.nodo in self.red.nodos:
            n = self.red.nodos[self.deposito.nodo]
            self.deposito.x, self.deposito.y = n.x, n.y

    def puntos(self) -> list[Any]:
        """Pedidos, repartidores y depósito: todo lo que ``RedVial.preparar`` necesita."""
        return [*self.pedidos, *self.repartidores, self.deposito]

    def crear_red_vial(self, metrica: str | None = None) -> RedVial:
        """RedVial lista para usar: distancias por calles (con calles bloqueadas y tráfico)
        entre todos los puntos del escenario. Hay que llamarla de nuevo si cambian las
        calles o los pedidos. Se pasa ``red_vial.distancia`` como 'dist' a los algoritmos."""
        red_vial = RedVial(red=self.red, metrica=metrica)
        red_vial.preparar(self.puntos())
        return red_vial


if __name__ == "__main__":
    # python -m src.datos [directorio] [json|csv]  ->  escribe los archivos de ejemplo
    import sys
    destino = sys.argv[1] if len(sys.argv) > 1 else "datos_ejemplo"
    formato = sys.argv[2] if len(sys.argv) > 2 else "json"
    for archivo in Escenario.sintetico().guardar(destino, formato):
        print("escrito:", archivo)
