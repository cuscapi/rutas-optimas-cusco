"""Modelos de datos del sistema de rutas de Cusco.

Todas las clases validan sus datos al crearse (``__post_init__``) y se pueden convertir
a/desde diccionarios (``to_dict`` / ``from_dict``) para guardarlas en JSON o CSV.

Unidades:
  * Coordenadas (x, y) de pedidos y nodos: plano local, 1 unidad = 100 m. Cada objeto con
    posición expone además ``lat`` y ``lon`` (coordenadas reales, vía ``traductor``); en los
    nodos la fuente de verdad es (lat, lon) y x, y se derivan de ellas.
  * Distancias de calles: metros. Tiempos: segundos (calles) o minutos (ventanas de pedidos).
  * Peso en kg (entero, porque la mochila 0/1 indexa por kg), volumen en m3.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .traductor import es_latlon_valido, latlon_a_xy, xy_a_latlon

# --------------------------------------------------------------------------- constantes
URGENCIA_MIN = 1
URGENCIA_MAX = 5

ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_ASIGNADO = "ASIGNADO"
ESTADO_ENTREGADO = "ENTREGADO"
ESTADO_CANCELADO = "CANCELADO"
ESTADOS_PEDIDO = (ESTADO_PENDIENTE, ESTADO_ASIGNADO, ESTADO_ENTREGADO, ESTADO_CANCELADO)

ESTADO_ABIERTO = "ABIERTO"
ESTADO_BLOQUEADO = "BLOQUEADO"
ESTADOS_CALLE = (ESTADO_ABIERTO, ESTADO_BLOQUEADO)

METRICAS = ("peso", "distancia", "tiempo")

# Velocidad de circulación libre (km/h) según el tipo de calle.
VELOCIDAD_KMH_POR_TIPO: dict[str, float] = {"avenida": 35.0, "calle": 22.0, "empinada": 12.0}


# --------------------------------------------------------------------------- utilidades
def _es_numero(valor: Any) -> bool:
    """True si 'valor' es un número real finito (los bool no cuentan)."""
    return (isinstance(valor, (int, float)) and not isinstance(valor, bool)
            and math.isfinite(valor))


def _a_entero(valor: Any, campo: str) -> int:
    """Convierte '5', 5.0 o 5 a int; rechaza 5.5, texto o bool."""
    if isinstance(valor, bool):
        raise ValueError(f"'{campo}' debe ser un entero, no {valor!r}")
    if isinstance(valor, int):
        return valor
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"'{campo}' debe ser un entero, no {valor!r}") from None
    if not numero.is_integer():
        raise ValueError(f"'{campo}' debe ser un entero, no {valor!r}")
    return int(numero)


def _a_real(valor: Any, campo: str) -> float:
    """Convierte '3.5' o 3 a float; rechaza texto y bool."""
    if isinstance(valor, bool):
        raise ValueError(f"'{campo}' debe ser un número, no {valor!r}")
    try:
        return float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"'{campo}' debe ser un número, no {valor!r}") from None


def _limpiar(d: Mapping[str, Any]) -> dict[str, Any]:
    """Quita claves con valor vacío ('' o None); así un CSV con celdas vacías usa los defaults."""
    return {k: v for k, v in d.items() if v is not None and v != ""}


def _exigir(d: Mapping[str, Any], requeridos: Iterable[str], nombre: str) -> None:
    faltan = [k for k in requeridos if k not in d]
    if faltan:
        raise ValueError(f"{nombre}: faltan campos obligatorios {faltan}")


def _lanzar_si_hay(errores: list[str], nombre: str) -> None:
    if errores:
        raise ValueError(f"{nombre} inválido: " + "; ".join(errores))


def _validar_geometria(puntos: Any, nombre: str) -> list[tuple[float, float]]:
    """Lista de al menos 2 pares (lat, lon) válidos; ValueError si no."""
    if not isinstance(puntos, (list, tuple)) or len(puntos) < 2:
        raise ValueError(f"{nombre}: la geometría debe tener al menos 2 puntos (lat, lon)")
    salida = []
    for i, par in enumerate(puntos):
        try:
            lat, lon = float(par[0]), float(par[1])
        except (TypeError, ValueError, IndexError):
            raise ValueError(f"{nombre}: punto {i} de la geometría inválido: {par!r}") from None
        if not es_latlon_valido(lat, lon):
            raise ValueError(f"{nombre}: punto {i} de la geometría fuera de rango")
        salida.append((lat, lon))
    return salida


def _posicion(d: Mapping[str, Any], nombre: str) -> tuple[float, float]:
    """(x, y) del plano a partir de un diccionario con 'x' e 'y' o con 'lat' y 'lon'."""
    if "x" in d and "y" in d:
        return _a_real(d["x"], "x"), _a_real(d["y"], "y")
    if "lat" in d and "lon" in d:
        lat, lon = _a_real(d["lat"], "lat"), _a_real(d["lon"], "lon")
        if not es_latlon_valido(lat, lon):
            raise ValueError(f"{nombre}: lat/lon fuera de rango ({lat}, {lon})")
        return latlon_a_xy(lat, lon)
    raise ValueError(f"{nombre}: faltan campos obligatorios ['x', 'y'] (o 'lat' y 'lon')")


# --------------------------------------------------------------------------- Nodo
@dataclass
class Nodo:
    """Intersección de la red vial (un nodo del grafo).

    Se crea con (nombre, x, y) en el plano local o con ``Nodo.desde_latlon``. Siempre
    tiene ``lat`` y ``lon`` (coordenadas reales para el mapa): si se dan, mandan y x, y se
    recalculan a partir de ellas; si no, se derivan de x, y.
    """
    nombre: str
    x: float
    y: float
    lat: float | None = None
    lon: float | None = None

    def __post_init__(self) -> None:
        errores = []
        if not isinstance(self.nombre, str) or not self.nombre.strip():
            errores.append("nombre vacío")
        if self.lat is not None and self.lon is not None:
            if not es_latlon_valido(self.lat, self.lon):
                errores.append(f"lat/lon inválidas ({self.lat!r}, {self.lon!r})")
            else:
                self.x, self.y = latlon_a_xy(self.lat, self.lon)
        elif self.lat is not None or self.lon is not None:
            errores.append("lat y lon deben darse juntas")
        if not (_es_numero(self.x) and _es_numero(self.y)):
            errores.append(f"coordenadas no numéricas ({self.x!r}, {self.y!r})")
        _lanzar_si_hay(errores, f"Nodo {self.nombre!r}")
        if self.lat is None:
            self.lat, self.lon = xy_a_latlon(self.x, self.y)

    @classmethod
    def desde_latlon(cls, nombre: str, lat: float, lon: float) -> "Nodo":
        """Crea el nodo a partir de coordenadas reales (x, y se calculan)."""
        return cls(nombre, 0.0, 0.0, float(lat), float(lon))

    def to_dict(self) -> dict[str, Any]:
        return {"nombre": self.nombre, "lat": self.lat, "lon": self.lon,
                "x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Nodo":
        """Acepta {nombre, lat, lon} (prioridad) o {nombre, x, y}."""
        d = _limpiar(d)
        _exigir(d, ("nombre",), "Nodo")
        nombre = str(d["nombre"])
        if "lat" in d and "lon" in d:
            lat, lon = _a_real(d["lat"], "lat"), _a_real(d["lon"], "lon")
            return cls(nombre, 0.0, 0.0, lat, lon)
        x, y = _posicion(d, f"Nodo {nombre!r}")
        return cls(nombre, x, y)


# --------------------------------------------------------------------------- Calle
@dataclass
class Calle:
    """Tramo de vía entre dos intersecciones (arista no dirigida del grafo).

    distancia_m: longitud en metros. tiempo_s: tiempo de recorrido con la vía libre
    (si es 0 se calcula con la velocidad del 'tipo'). estado: "ABIERTO" | "BLOQUEADO".
    factor_trafico: multiplicador > 0 (1.0 = fluido, 2.0 = el doble de costoso) que
    se aplica al peso y al tiempo.
    """
    origen: str
    destino: str
    distancia_m: float
    tiempo_s: float = 0.0
    estado: str = ESTADO_ABIERTO
    factor_trafico: float = 1.0
    tipo: str = "calle"
    # Trazado real de la calle: [(lat, lon), ...] desde 'origen' hasta 'destino' (por
    # ejemplo, tomado de OpenStreetMap). None = se dibuja como una recta entre los nodos.
    geometria: list | None = field(default=None, compare=False, repr=False)
    fuente_geometria: str = field(default="", compare=False, repr=False)
    # longitud anterior a usar la del trazado real (para poder volver a ella); no se guarda
    distancia_base_m: float | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.estado, str):
            self.estado = self.estado.strip().upper()
        errores = self.errores()
        _lanzar_si_hay(errores, f"Calle {self.origen!r}-{self.destino!r}")
        if self.geometria is not None:
            self.geometria = _validar_geometria(self.geometria, f"Calle {self.origen!r}-{self.destino!r}")
        if self.tiempo_s <= 0:
            self.recalcular_tiempo()

    def recalcular_tiempo(self) -> None:
        """tiempo_s = distancia / velocidad libre del tipo de vía."""
        self.tiempo_s = self.distancia_m / (VELOCIDAD_KMH_POR_TIPO[self.tipo] / 3.6)

    def cambiar_distancia(self, metros: float) -> None:
        """Fija una nueva longitud (por ejemplo, la medida sobre el trazado real) y
        recalcula el tiempo de recorrido."""
        if not _es_numero(metros) or metros <= 0:
            raise ValueError(f"distancia_m debe ser > 0 (es {metros!r})")
        self.distancia_m = float(metros)
        self.recalcular_tiempo()

    # -- validación
    def errores(self) -> list[str]:
        """Lista de problemas de los datos (vacía si todo está bien)."""
        e = []
        for campo in ("origen", "destino"):
            valor = getattr(self, campo)
            if not isinstance(valor, str) or not valor.strip():
                e.append(f"{campo} vacío")
        if self.origen == self.destino:
            e.append("origen y destino son el mismo nodo")
        if not _es_numero(self.distancia_m) or self.distancia_m <= 0:
            e.append(f"distancia_m debe ser > 0 (es {self.distancia_m!r})")
        if not _es_numero(self.tiempo_s) or self.tiempo_s < 0:
            e.append(f"tiempo_s debe ser >= 0 (es {self.tiempo_s!r})")
        if self.estado not in ESTADOS_CALLE:
            e.append(f"estado debe ser uno de {ESTADOS_CALLE} (es {self.estado!r})")
        if not _es_numero(self.factor_trafico) or self.factor_trafico <= 0:
            e.append(f"factor_trafico debe ser > 0 (es {self.factor_trafico!r})")
        if self.tipo not in VELOCIDAD_KMH_POR_TIPO:
            e.append(f"tipo debe ser uno de {tuple(VELOCIDAD_KMH_POR_TIPO)} (es {self.tipo!r})")
        return e

    # -- estado dinámico
    @property
    def clave(self) -> frozenset[str]:
        """Clave no dirigida: igual para (a, b) y (b, a)."""
        return frozenset((self.origen, self.destino))

    @property
    def bloqueada(self) -> bool:
        return self.estado == ESTADO_BLOQUEADO

    def bloquear(self) -> None:
        self.estado = ESTADO_BLOQUEADO

    def desbloquear(self) -> None:
        self.estado = ESTADO_ABIERTO

    def establecer_trafico(self, factor: float) -> None:
        """Fija el multiplicador de tráfico (> 0)."""
        if not _es_numero(factor) or factor <= 0:
            raise ValueError(f"factor_trafico debe ser > 0 (es {factor!r})")
        self.factor_trafico = float(factor)

    # -- costos
    @property
    def peso(self) -> float:
        """Peso para los algoritmos: metros * factor de tráfico."""
        return self.distancia_m * self.factor_trafico

    @property
    def tiempo_efectivo_s(self) -> float:
        """Tiempo de recorrido con el tráfico actual."""
        return self.tiempo_s * self.factor_trafico

    def costo(self, metrica: str = "peso") -> float:
        """Costo de cruzar la calle: 'peso' (m*tráfico), 'distancia' (m) o 'tiempo' (s)."""
        if metrica == "peso":
            return self.peso
        if metrica == "distancia":
            return self.distancia_m
        if metrica == "tiempo":
            return self.tiempo_efectivo_s
        raise ValueError(f"métrica desconocida {metrica!r}; use una de {METRICAS}")

    # -- serialización
    def to_dict(self) -> dict[str, Any]:
        return {"origen": self.origen, "destino": self.destino,
                "distancia_m": self.distancia_m, "tiempo_s": self.tiempo_s,
                "estado": self.estado, "factor_trafico": self.factor_trafico,
                "tipo": self.tipo,
                **({"geometria": [list(p) for p in self.geometria],
                    "fuente_geometria": self.fuente_geometria} if self.geometria else {})}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Calle":
        d = _limpiar(d)
        _exigir(d, ("origen", "destino", "distancia_m"), "Calle")
        return cls(
            origen=str(d["origen"]), destino=str(d["destino"]),
            distancia_m=_a_real(d["distancia_m"], "distancia_m"),
            tiempo_s=_a_real(d.get("tiempo_s", 0.0), "tiempo_s"),
            estado=str(d.get("estado", ESTADO_ABIERTO)),
            factor_trafico=_a_real(d.get("factor_trafico", 1.0), "factor_trafico"),
            tipo=str(d.get("tipo", "calle")),
            geometria=d.get("geometria") if isinstance(d.get("geometria"), list) else None,
            fuente_geometria=str(d.get("fuente_geometria", "")),
        )


# --------------------------------------------------------------------------- Pedido
@dataclass
class Pedido:
    """Un pedido de entrega.

    Las coordenadas (x, y) están en unidades del mapa (1 unidad = 100 m) y son el punto
    de entrega. Está sobre una calle: 'calle' = (a, b) y t en [0, 1] es la fracción del
    recorrido desde a hacia b. 'origen' es el nodo donde se recoge (el depósito) y
    'destino' el nodo de entrega (por defecto, el sector). urgencia (= prioridad) va de
    1 (baja) a 5 (emergencia). peso en kg (entero), volumen_m3 en m3, valor en soles.
    La ventana de tiempo está en minutos desde el inicio de la jornada: se puede
    entregar desde 'ventana_inicio' y el límite es 'ventana_fin'.
    """
    id: str
    cliente: str
    x: float
    y: float
    urgencia: int
    peso: int
    valor: int
    sector: str = ""
    calle: tuple = ()
    t: float = 0.0
    origen: str = ""
    destino: str = ""
    volumen_m3: float = 0.0
    ventana_inicio: int = 0
    ventana_fin: int = 480
    estado: str = ESTADO_PENDIENTE

    def __post_init__(self) -> None:
        self.calle = tuple(self.calle)
        if not self.destino:
            self.destino = self.sector
        self.validar()

    # -- validación
    def errores(self) -> list[str]:
        """Lista de problemas de los datos (vacía si todo está bien)."""
        e = []
        if not isinstance(self.id, str) or not self.id.strip():
            e.append("id vacío")
        if not (_es_numero(self.x) and _es_numero(self.y)):
            e.append(f"coordenadas no numéricas ({self.x!r}, {self.y!r})")
        if (not isinstance(self.urgencia, int) or isinstance(self.urgencia, bool)
                or not URGENCIA_MIN <= self.urgencia <= URGENCIA_MAX):
            e.append(f"urgencia debe ser un entero entre {URGENCIA_MIN} y {URGENCIA_MAX} "
                     f"(es {self.urgencia!r})")
        if not isinstance(self.peso, int) or isinstance(self.peso, bool) or self.peso <= 0:
            e.append(f"peso debe ser un entero de kg > 0 (es {self.peso!r})")
        if not _es_numero(self.valor) or self.valor < 0:
            e.append(f"valor debe ser >= 0 (es {self.valor!r})")
        if not _es_numero(self.volumen_m3) or self.volumen_m3 < 0:
            e.append(f"volumen_m3 debe ser >= 0 (es {self.volumen_m3!r})")
        if len(self.calle) not in (0, 2):
            e.append(f"calle debe ser (origen, destino) o vacía (es {self.calle!r})")
        if not _es_numero(self.t) or not 0.0 <= self.t <= 1.0:
            e.append(f"t debe estar en [0, 1] (es {self.t!r})")
        if (not isinstance(self.ventana_inicio, int) or not isinstance(self.ventana_fin, int)
                or isinstance(self.ventana_inicio, bool) or isinstance(self.ventana_fin, bool)):
            e.append("ventana_inicio y ventana_fin deben ser minutos enteros")
        elif self.ventana_inicio < 0 or self.ventana_fin <= self.ventana_inicio:
            e.append(f"ventana inválida: debe cumplirse 0 <= inicio < fin "
                     f"({self.ventana_inicio}, {self.ventana_fin})")
        if self.estado not in ESTADOS_PEDIDO:
            e.append(f"estado debe ser uno de {ESTADOS_PEDIDO} (es {self.estado!r})")
        return e

    def validar(self) -> None:
        """Lanza ValueError con todos los problemas encontrados."""
        _lanzar_si_hay(self.errores(), f"Pedido {self.id!r}")

    # -- consultas útiles
    @property
    def lat(self) -> float:
        """Latitud real del punto de entrega."""
        return xy_a_latlon(self.x, self.y)[0]

    @property
    def lon(self) -> float:
        """Longitud real del punto de entrega."""
        return xy_a_latlon(self.x, self.y)[1]

    @property
    def prioridad(self) -> int:
        """Alias de 'urgencia'."""
        return self.urgencia

    @property
    def valor_por_kg(self) -> float:
        return self.valor / self.peso

    def es_urgente(self, umbral: int = 4) -> bool:
        return self.urgencia >= umbral

    def en_ventana(self, minuto: float) -> bool:
        """True si entregar en 'minuto' cae dentro de la ventana de tiempo."""
        return self.ventana_inicio <= minuto <= self.ventana_fin

    def holgura(self, minuto: float) -> float:
        """Minutos que faltan para el límite (negativo = ya venció)."""
        return self.ventana_fin - minuto

    # -- serialización
    def to_dict(self, geo: bool = False) -> dict[str, Any]:
        """Diccionario con los campos del Pedido. Con ``geo=True`` agrega lat y lon
        (derivadas de x, y) para los archivos; sin ella, ``Pedido(**p.to_dict())`` funciona."""
        d = {
            "id": self.id, "cliente": self.cliente, "x": self.x, "y": self.y,
            "urgencia": self.urgencia, "peso": self.peso, "valor": self.valor,
            "sector": self.sector, "calle": list(self.calle), "t": self.t,
            "origen": self.origen, "destino": self.destino,
            "volumen_m3": self.volumen_m3,
            "ventana_inicio": self.ventana_inicio, "ventana_fin": self.ventana_fin,
            "estado": self.estado,
        }
        if geo:
            d["lat"], d["lon"] = round(self.lat, 7), round(self.lon, 7)
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Pedido":
        """Crea y valida un Pedido. Acepta 'prioridad' como alias de 'urgencia' y la calle
        como lista [a, b] o como texto "a|b" (formato CSV). Los campos opcionales
        vacíos toman su valor por defecto."""
        d = _limpiar(d)
        if "urgencia" not in d and "prioridad" in d:
            d["urgencia"] = d["prioridad"]
        _exigir(d, ("id", "urgencia", "peso", "valor"), "Pedido")
        x, y = _posicion(d, f"Pedido {d['id']!r}")
        calle = d.get("calle", ())
        if isinstance(calle, str):
            calle = tuple(parte.strip() for parte in calle.split("|"))
        valor = _a_real(d["valor"], "valor")
        return cls(
            id=str(d["id"]), cliente=str(d.get("cliente", f"Cliente {d['id']}")),
            x=x, y=y,
            urgencia=_a_entero(d["urgencia"], "urgencia"),
            peso=_a_entero(d["peso"], "peso"),
            valor=int(valor) if valor.is_integer() else valor,
            sector=str(d.get("sector", "")), calle=tuple(calle),
            t=_a_real(d.get("t", 0.0), "t"),
            origen=str(d.get("origen", "")), destino=str(d.get("destino", "")),
            volumen_m3=_a_real(d.get("volumen_m3", 0.0), "volumen_m3"),
            ventana_inicio=_a_entero(d.get("ventana_inicio", 0), "ventana_inicio"),
            ventana_fin=_a_entero(d.get("ventana_fin", 480), "ventana_fin"),
            estado=str(d.get("estado", ESTADO_PENDIENTE)).strip().upper(),
        )


# --------------------------------------------------------------------------- Repartidor
@dataclass
class Repartidor:
    """Un repartidor con su base de salida y su capacidad de carga (kg y m3)."""
    nombre: str
    x: float
    y: float
    capacidad: int
    color: str
    nodo: str = ""
    capacidad_volumen_m3: float = 3.0
    velocidad_kmh: float = 25.0

    def __post_init__(self) -> None:
        self.validar()

    @property
    def id(self) -> str:
        return self.nombre

    @property
    def lat(self) -> float:
        return xy_a_latlon(self.x, self.y)[0]

    @property
    def lon(self) -> float:
        return xy_a_latlon(self.x, self.y)[1]

    def errores(self) -> list[str]:
        e = []
        if not isinstance(self.nombre, str) or not self.nombre.strip():
            e.append("nombre vacío")
        if not (_es_numero(self.x) and _es_numero(self.y)):
            e.append(f"coordenadas no numéricas ({self.x!r}, {self.y!r})")
        if (not isinstance(self.capacidad, int) or isinstance(self.capacidad, bool)
                or self.capacidad <= 0):
            e.append(f"capacidad debe ser un entero de kg > 0 (es {self.capacidad!r})")
        if not _es_numero(self.capacidad_volumen_m3) or self.capacidad_volumen_m3 <= 0:
            e.append(f"capacidad_volumen_m3 debe ser > 0 (es {self.capacidad_volumen_m3!r})")
        if not _es_numero(self.velocidad_kmh) or self.velocidad_kmh <= 0:
            e.append(f"velocidad_kmh debe ser > 0 (es {self.velocidad_kmh!r})")
        return e

    def validar(self) -> None:
        _lanzar_si_hay(self.errores(), f"Repartidor {self.nombre!r}")

    def puede_cargar(self, peso_total: float, volumen_total: float = 0.0) -> bool:
        """True si una carga de ese peso (kg) y volumen (m3) cabe en el vehículo."""
        return peso_total <= self.capacidad and volumen_total <= self.capacidad_volumen_m3

    def to_dict(self, geo: bool = False) -> dict[str, Any]:
        d = {"nombre": self.nombre, "x": self.x, "y": self.y,
             "capacidad": self.capacidad, "color": self.color, "nodo": self.nodo,
             "capacidad_volumen_m3": self.capacidad_volumen_m3,
             "velocidad_kmh": self.velocidad_kmh}
        if geo:
            d["lat"], d["lon"] = round(self.lat, 7), round(self.lon, 7)
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Repartidor":
        d = _limpiar(d)
        _exigir(d, ("nombre", "capacidad"), "Repartidor")
        x, y = _posicion(d, f"Repartidor {d['nombre']!r}")
        return cls(
            nombre=str(d["nombre"]), x=x, y=y,
            capacidad=_a_entero(d["capacidad"], "capacidad"),
            color=str(d.get("color", "#555555")), nodo=str(d.get("nodo", "")),
            capacidad_volumen_m3=_a_real(d.get("capacidad_volumen_m3", 3.0),
                                         "capacidad_volumen_m3"),
            velocidad_kmh=_a_real(d.get("velocidad_kmh", 25.0), "velocidad_kmh"),
        )


# --------------------------------------------------------------------------- Punto
@dataclass
class Punto:
    """Un punto fijo del mapa ubicado en un cruce (por ejemplo, el depósito)."""
    id: str
    nodo: str
    x: float
    y: float

    @property
    def lat(self) -> float:
        return xy_a_latlon(self.x, self.y)[0]

    @property
    def lon(self) -> float:
        return xy_a_latlon(self.x, self.y)[1]

    def to_dict(self, geo: bool = False) -> dict[str, Any]:
        d = {"id": self.id, "nodo": self.nodo, "x": self.x, "y": self.y}
        if geo:
            d["lat"], d["lon"] = round(self.lat, 7), round(self.lon, 7)
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Punto":
        d = _limpiar(d)
        _exigir(d, ("id", "nodo"), "Punto")
        x, y = _posicion(d, f"Punto {d['id']!r}")
        return cls(str(d["id"]), str(d["nodo"]), x, y)


def distancia(a: Any, b: Any) -> float:
    """Distancia euclidiana entre dos objetos con atributos x e y. O(1)."""
    return math.hypot(a.x - b.x, a.y - b.y)
