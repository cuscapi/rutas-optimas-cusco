"""Red vial de Cusco.

Dos clases:

* ``RedCusco``: el grafo de intersecciones (nodos) y calles (aristas) con estado dinámico
  por calle (ABIERTO/BLOQUEADO y factor de tráfico). Se puede pasar directamente como
  ``grafo`` a ``voraz.dijkstra`` o ``backtracking.*``: ``red[nodo]`` devuelve solo los
  vecinos alcanzables por calles abiertas.
* ``RedVial``: inserta los pedidos como nodos sobre sus calles y calcula la distancia por
  calles entre todos los puntos (la que usan Voraz, Held-Karp y la GUI).
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Iterable, Iterator

from .modelos import METRICAS, Calle, Nodo
from .traductor import latlon_a_xy, xy_a_latlon
from .voraz import dijkstra_todos

Adyacencia = dict[str, list[tuple[str, float]]]
Punto2D = tuple[float, float]


# ====================================================================== polilíneas
# Una calle puede tener su trazado real (lista de puntos). Estas funciones trabajan en el
# plano local (x, y) y miden las posiciones como fracción 't' del largo del trazado, de
# modo que un pedido en t = 0.3 está al 30 % del recorrido real de la calle.
class _Polilinea:
    __slots__ = ("pts", "acum", "largo")

    def __init__(self, pts: list[Punto2D]) -> None:
        limpios = [pts[0]]
        for p in pts[1:]:
            if math.hypot(p[0] - limpios[-1][0], p[1] - limpios[-1][1]) > 1e-9:
                limpios.append(p)
        if len(limpios) == 1:
            limpios.append(limpios[0])
        self.pts = limpios
        self.acum = [0.0]
        for a, b in zip(limpios, limpios[1:]):
            self.acum.append(self.acum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.largo = self.acum[-1]

    def _indice(self, distancia: float) -> int:
        """Índice i del segmento [i, i+1] que contiene la distancia acumulada dada."""
        bajo, alto = 0, len(self.acum) - 2
        while bajo < alto:
            medio = (bajo + alto + 1) // 2
            if self.acum[medio] <= distancia:
                bajo = medio
            else:
                alto = medio - 1
        return max(0, bajo)

    def punto(self, t: float) -> Punto2D:
        t = min(1.0, max(0.0, t))
        if self.largo == 0:
            return self.pts[0]
        d = t * self.largo
        i = self._indice(d)
        seg = self.acum[i + 1] - self.acum[i]
        f = 0.0 if seg == 0 else (d - self.acum[i]) / seg
        (x0, y0), (x1, y1) = self.pts[i], self.pts[i + 1]
        return (x0 + f * (x1 - x0), y0 + f * (y1 - y0))

    def tramo(self, t0: float, t1: float) -> list[Punto2D]:
        """Puntos del trazado entre las fracciones t0 y t1 (en ese sentido)."""
        if t0 > t1:
            return list(reversed(self.tramo(t1, t0)))
        t0, t1 = max(0.0, t0), min(1.0, t1)
        salida = [self.punto(t0)]
        if self.largo > 0:
            d0, d1 = t0 * self.largo, t1 * self.largo
            salida.extend(p for p, a in zip(self.pts, self.acum) if d0 < a < d1)
        salida.append(self.punto(t1))
        return salida

    def proyectar(self, x: float, y: float) -> tuple[float, float, Punto2D]:
        """(distancia del punto al trazado, t del punto más cercano, ese punto)."""
        mejor = (math.inf, 0.0, self.pts[0])
        for i, (a, b) in enumerate(zip(self.pts, self.pts[1:])):
            dx, dy = b[0] - a[0], b[1] - a[1]
            l2 = dx * dx + dy * dy
            f = 0.0 if l2 == 0 else min(1.0, max(0.0, ((x - a[0]) * dx + (y - a[1]) * dy) / l2))
            px, py = a[0] + f * dx, a[1] + f * dy
            d = math.hypot(x - px, y - py)
            if d < mejor[0]:
                t = 0.0 if self.largo == 0 else (self.acum[i] + f * math.sqrt(l2)) / self.largo
                mejor = (d, t, (px, py))
        return mejor


class RedCusco:
    """Grafo no dirigido de intersecciones y calles con estado dinámico.

    Cada ``Calle`` guarda ``estado`` ("ABIERTO" | "BLOQUEADO") y ``factor_trafico``.
    ``metrica`` elige qué costo devuelven los vecinos: "peso" (metros * tráfico, por
    defecto), "distancia" (metros) o "tiempo" (segundos con tráfico).
    """

    def __init__(self, metrica: str = "peso") -> None:
        self._validar_metrica(metrica)
        self.metrica = metrica
        self.nodos: dict[str, Nodo] = {}
        self._calles: dict[frozenset[str], Calle] = {}
        self._adyacentes: dict[str, dict[str, Calle]] = {}
        self._polilineas: dict[frozenset[str], _Polilinea] = {}

    @staticmethod
    def _validar_metrica(metrica: str) -> None:
        if metrica not in METRICAS:
            raise ValueError(f"métrica desconocida {metrica!r}; use una de {METRICAS}")

    # ------------------------------------------------------------------ construcción
    def agregar_nodo(self, nombre: str, x: float, y: float,
                     lat: float | None = None, lon: float | None = None) -> Nodo:
        """Agrega una intersección (en el plano x, y o con lat/lon reales).

        Si se dan ``lat`` y ``lon`` mandan sobre x, y. Lanza ValueError si el nombre ya existe.
        """
        if nombre in self.nodos:
            raise ValueError(f"El nodo {nombre!r} ya existe")
        nodo = Nodo(nombre, float(x), float(y), lat, lon)
        self.nodos[nombre] = nodo
        self._adyacentes[nombre] = {}
        return nodo

    def agregar_calle(self, calle: Calle) -> Calle:
        """Agrega una calle entre dos nodos existentes (sin duplicados)."""
        for extremo in (calle.origen, calle.destino):
            if extremo not in self.nodos:
                raise ValueError(f"La calle {calle.origen!r}-{calle.destino!r} usa el nodo "
                                 f"inexistente {extremo!r}")
        if calle.clave in self._calles:
            raise ValueError(f"La calle {calle.origen!r}-{calle.destino!r} ya existe")
        self._calles[calle.clave] = calle
        self._adyacentes[calle.origen][calle.destino] = calle
        self._adyacentes[calle.destino][calle.origen] = calle
        return calle

    # ------------------------------------------------------------------ consulta básica
    def calle(self, origen: str, destino: str) -> Calle:
        """Devuelve la calle entre dos nodos (en cualquier orden). KeyError si no existe."""
        try:
            return self._calles[frozenset((origen, destino))]
        except KeyError:
            raise KeyError(f"No existe la calle {origen!r} - {destino!r}") from None

    def existe_calle(self, origen: str, destino: str) -> bool:
        return frozenset((origen, destino)) in self._calles

    def calles(self) -> list[Calle]:
        """Todas las calles, en el orden en que se agregaron."""
        return list(self._calles.values())

    # ------------------------------------------------------------------ estado de las vías
    def bloquear_calle(self, origen: str, destino: str) -> bool:
        """Marca la calle como BLOQUEADO. Devuelve True si cambió de estado."""
        c = self.calle(origen, destino)
        cambio = not c.bloqueada
        c.bloquear()
        return cambio

    def desbloquear_calle(self, origen: str, destino: str) -> bool:
        """Marca la calle como ABIERTO. Devuelve True si cambió de estado."""
        c = self.calle(origen, destino)
        cambio = c.bloqueada
        c.desbloquear()
        return cambio

    def alternar_calle(self, origen: str, destino: str) -> bool:
        """Invierte el estado de la calle. Devuelve True si quedó bloqueada."""
        c = self.calle(origen, destino)
        if c.bloqueada:
            c.desbloquear()
        else:
            c.bloquear()
        return c.bloqueada

    def esta_bloqueada(self, origen: str, destino: str) -> bool:
        return self.calle(origen, destino).bloqueada

    def bloqueadas(self) -> frozenset[frozenset[str]]:
        """Claves (frozenset de 2 nodos) de las calles bloqueadas. Sirve como el
        parámetro ``cerradas`` de dijkstra, backtracking y RedVial."""
        return frozenset(k for k, c in self._calles.items() if c.bloqueada)

    def desbloquear_todas(self) -> None:
        for c in self._calles.values():
            c.desbloquear()

    def establecer_trafico(self, origen: str, destino: str, factor: float) -> None:
        """Fija el multiplicador de tráfico de una calle (1.0 = fluido)."""
        self.calle(origen, destino).establecer_trafico(factor)

    def restablecer_trafico(self) -> None:
        for c in self._calles.values():
            c.establecer_trafico(1.0)

    # ------------------------------------------------------------------ vecinos y grafo
    def obtener_vecinos_validos(self, nodo: str,
                                metrica: str | None = None) -> list[tuple[str, float]]:
        """Vecinos de 'nodo' alcanzables por calles ABIERTAS: [(vecino, costo), ...].

        Las calles bloqueadas se filtran, así que Backtracking, Voraz y Dijkstra no las
        usan. El costo depende de la métrica ("peso", "distancia" o "tiempo").
        Tiempo O(grado del nodo). KeyError si el nodo no existe.
        """
        metrica = metrica or self.metrica
        self._validar_metrica(metrica)
        try:
            vecinos = self._adyacentes[nodo]
        except KeyError:
            raise KeyError(f"No existe el nodo {nodo!r}") from None
        return [(v, c.costo(metrica)) for v, c in vecinos.items() if not c.bloqueada]

    def vecinos_todos(self, nodo: str,
                      metrica: str | None = None) -> list[tuple[str, float, bool]]:
        """TODOS los vecinos de 'nodo', también por calles bloqueadas: [(vecino, costo, bloqueada)].

        Lo usa el backtracking para podar explícitamente las calles bloqueadas (y contarlas).
        KeyError si el nodo no existe. O(grado del nodo).
        """
        metrica = metrica or self.metrica
        self._validar_metrica(metrica)
        try:
            vecinos = self._adyacentes[nodo]
        except KeyError:
            raise KeyError(f"No existe el nodo {nodo!r}") from None
        return [(v, c.costo(metrica), c.bloqueada) for v, c in vecinos.items()]

    def a_adyacencia(self, metrica: str | None = None) -> Adyacencia:
        """Lista de adyacencia {nodo: [(vecino, costo), ...]} sin las calles bloqueadas.
        Es una foto: si luego cambia el estado de las calles hay que volver a pedirla
        (o usar la propia red como grafo). O(V + E)."""
        return {n: self.obtener_vecinos_validos(n, metrica) for n in self.nodos}

    # La red se comporta como el dict de adyacencia que esperan los algoritmos.
    def __getitem__(self, nodo: str) -> list[tuple[str, float]]:
        return self.obtener_vecinos_validos(nodo)

    def get(self, nodo: str, defecto: Any = ()) -> Any:
        if nodo not in self.nodos:
            return defecto
        return self.obtener_vecinos_validos(nodo)

    def __contains__(self, nodo: object) -> bool:
        return nodo in self.nodos

    def __iter__(self) -> Iterator[str]:
        return iter(self.nodos)

    def __len__(self) -> int:
        return len(self.nodos)

    # ------------------------------------------------------------------ análisis
    def nodos_alcanzables(self, origen: str) -> set[str]:
        """Nodos a los que se llega desde 'origen' por calles abiertas (BFS, O(V + E))."""
        if origen not in self.nodos:
            raise KeyError(f"No existe el nodo {origen!r}")
        vistos = {origen}
        cola = deque([origen])
        while cola:
            actual = cola.popleft()
            for vecino, _ in self.obtener_vecinos_validos(actual):
                if vecino not in vistos:
                    vistos.add(vecino)
                    cola.append(vecino)
        return vistos

    def es_alcanzable(self, origen: str, destino: str) -> bool:
        return destino in self.nodos_alcanzables(origen)

    def costo_camino(self, camino: Iterable[str], metrica: str | None = None) -> float:
        """Suma el costo de un camino [n0, n1, ...]. ValueError si cruza una calle bloqueada."""
        metrica = metrica or self.metrica
        nodos = list(camino)
        total = 0.0
        for a, b in zip(nodos, nodos[1:]):
            c = self.calle(a, b)
            if c.bloqueada:
                raise ValueError(f"El camino cruza la calle bloqueada {a!r} - {b!r}")
            total += c.costo(metrica)
        return total

    def nodo_mas_cercano(self, x: float, y: float) -> str:
        """Nombre del nodo más cercano a (x, y). O(V)."""
        return min(self.nodos.values(), key=lambda n: math.hypot(n.x - x, n.y - y)).nombre

    def calle_mas_cercana(self, x: float, y: float) -> tuple[Calle, float, float, float, float]:
        """Calle más cercana al punto (x, y) del plano.

        Devuelve (calle, distancia, t, px, py): 'distancia' en unidades del plano (100 m) del
        punto a la calle, 't' en [0.05, 0.95] la fracción del recorrido desde ``calle.origen``
        hacia ``calle.destino`` del punto proyectado, y (px, py) ese punto sobre la calle. Si
        la calle tiene trazado real (``geometria``) se mide sobre ese trazado; si no, sobre la
        recta entre sus nodos. Sirve para convertir un clic del mapa en una calle o en un
        pedido. O(E · puntos del trazado).
        """
        if not self._calles:
            raise ValueError("La red no tiene calles")
        mejor = None
        for c in self._calles.values():
            poli = self._polilinea(c)
            d, t, _ = poli.proyectar(x, y)
            if mejor is None or d < mejor[1]:
                mejor = (c, d, t)
        calle, distancia, t = mejor
        t = min(0.95, max(0.05, t))
        px, py = self._polilinea(calle).punto(t)
        return calle, distancia, t, px, py

    # ------------------------------------------------------------------ trazado de las calles
    def _polilinea(self, calle: Calle) -> _Polilinea:
        poli = self._polilineas.get(calle.clave)
        if poli is None:
            a, b = self.nodos[calle.origen], self.nodos[calle.destino]
            if calle.geometria:
                pts = [latlon_a_xy(lat, lon) for lat, lon in calle.geometria]
                # el trazado siempre empieza y termina en los nodos de la calle
                if math.hypot(pts[0][0] - a.x, pts[0][1] - a.y) > 1e-6:
                    pts.insert(0, (a.x, a.y))
                if math.hypot(pts[-1][0] - b.x, pts[-1][1] - b.y) > 1e-6:
                    pts.append((b.x, b.y))
            else:
                pts = [(a.x, a.y), (b.x, b.y)]
            poli = _Polilinea(pts)
            self._polilineas[calle.clave] = poli
        return poli

    def _invalidar_trazados(self) -> None:
        self._polilineas.clear()

    def establecer_geometria(self, origen: str, destino: str, puntos: list | None,
                             fuente: str = "osm", usar_largo_m: float | None = None) -> None:
        """Fija el trazado real de una calle: [(lat, lon), ...] desde 'origen' hasta 'destino'
        (se invierte solo si la calle está guardada al revés). None lo quita (recta).
        Con 'usar_largo_m' también cambia la longitud de la calle (y su tiempo)."""
        c = self.calle(origen, destino)
        if puntos is None:
            c.geometria, c.fuente_geometria = None, ""
        else:
            pts = [(float(lat), float(lon)) for lat, lon in puntos]
            if len(pts) < 2:
                raise ValueError("La geometría necesita al menos 2 puntos")
            if c.origen != origen:
                pts.reverse()
            c.geometria, c.fuente_geometria = pts, fuente
        if usar_largo_m is not None:
            c.cambiar_distancia(usar_largo_m)
        self._polilineas.pop(c.clave, None)

    def tiene_trazado_real(self) -> bool:
        """True si al menos una calle tiene geometría real."""
        return any(c.geometria for c in self._calles.values())

    def mover_nodo(self, nombre: str, lat: float, lon: float) -> None:
        """Cambia la posición real de un nodo (por ejemplo, para pegarlo a la calle real)."""
        n = self.nodos[nombre]
        n.lat, n.lon = float(lat), float(lon)
        n.x, n.y = latlon_a_xy(n.lat, n.lon)
        self._invalidar_trazados()

    def trazado_xy(self, origen: str, destino: str) -> list[Punto2D]:
        """Puntos (x, y) de la calle recorrida de 'origen' a 'destino'."""
        c = self.calle(origen, destino)
        pts = list(self._polilinea(c).pts)
        return pts if c.origen == origen else pts[::-1]

    def trazado_latlon(self, origen: str, destino: str) -> list[tuple[float, float]]:
        """Puntos (lat, lon) de la calle recorrida de 'origen' a 'destino' (para dibujarla)."""
        return [xy_a_latlon(x, y) for x, y in self.trazado_xy(origen, destino)]

    def punto_en_calle(self, origen: str, destino: str, t: float) -> Punto2D:
        """Punto (x, y) a la fracción 't' del recorrido de la calle medido desde 'origen'."""
        c = self.calle(origen, destino)
        return self._polilinea(c).punto(t if c.origen == origen else 1 - t)

    def tramo_calle(self, calle: Calle, t0: float, t1: float) -> list[Punto2D]:
        """Puntos (x, y) del trazado de 'calle' entre t0 y t1 (fracciones desde calle.origen)."""
        return self._polilinea(calle).tramo(t0, t1)

    def largo_trazado_m(self, origen: str, destino: str) -> float:
        """Largo del trazado (o de la recta) en metros, medido en el plano local."""
        from .traductor import UNIDAD_M
        return self._polilinea(self.calle(origen, destino)).largo * UNIDAD_M

    def polilinea_camino(self, camino: Iterable[str]) -> list[tuple[float, float]]:
        """Camino de nodos [n0, n1, ...] -> puntos (lat, lon) siguiendo el trazado de cada calle.

        Sirve para dibujar las rutas del backtracking sobre las calles reales."""
        nodos = list(camino)
        if len(nodos) == 1:
            n = self.nodos[nodos[0]]
            return [(n.lat, n.lon)]
        salida: list[tuple[float, float]] = []
        for a, b in zip(nodos, nodos[1:]):
            tramo = self.trazado_latlon(a, b)
            salida.extend(tramo if not salida else tramo[1:])
        return salida

    def limites(self, margen: float = 2.0) -> tuple[float, float, float, float]:
        """Caja (x0, y0, x1, y1) que contiene todos los nodos, con un margen."""
        xs = [n.x for n in self.nodos.values()]
        ys = [n.y for n in self.nodos.values()]
        for c in self._calles.values():
            if c.geometria:
                for x, y in self._polilinea(c).pts:
                    xs.append(x)
                    ys.append(y)
        return (min(xs) - margen, min(ys) - margen, max(xs) + margen, max(ys) + margen)

    # ------------------------------------------------------------------ serialización
    def to_dict(self) -> dict[str, Any]:
        return {"nodos": [n.to_dict() for n in self.nodos.values()],
                "calles": [c.to_dict() for c in self._calles.values()]}

    @classmethod
    def from_dict(cls, d: dict[str, Any], metrica: str = "peso") -> "RedCusco":
        """Reconstruye y valida una red. ValueError si falta algo o hay referencias rotas."""
        if "nodos" not in d or "calles" not in d:
            raise ValueError("La red debe tener las claves 'nodos' y 'calles'")
        red = cls(metrica)
        for n in d["nodos"]:
            nodo = Nodo.from_dict(n)
            red.agregar_nodo(nodo.nombre, nodo.x, nodo.y, nodo.lat, nodo.lon)
        for c in d["calles"]:
            red.agregar_calle(Calle.from_dict(c))
        return red

    def copia(self) -> "RedCusco":
        """Copia independiente (cambiar estados en la copia no afecta al original)."""
        return RedCusco.from_dict(self.to_dict(), self.metrica)


# ====================================================================== RedVial
def _cadena(unir, inicio: str, items: list[tuple[str, float]], largo: float,
            desde_b: bool, final: str | None = None) -> None:
    """Une 'inicio' con los puntos de una calle en orden, y opcionalmente con 'final'.

    items = [(clave_del_nodo, t)] ordenados por t (fracción desde el origen de la calle).
    ``unir(u, v, costo, t_u, t_v)`` recibe también las fracciones (medidas desde el
    origen de la calle) de los dos extremos del tramo, para poder dibujarlo después.
    """
    previo, t_previo = inicio, 0.0
    for clave, t_orig in items:
        t = (1 - t_orig) if desde_b else t_orig
        unir(previo, clave, (t - t_previo) * largo,
             (1 - t_previo) if desde_b else t_previo, t_orig)
        previo, t_previo = clave, t
    if final is not None:
        unir(previo, final, (1 - t_previo) * largo,
             (1 - t_previo) if desde_b else t_previo, 0.0 if desde_b else 1.0)


class RedVial:
    """Grafo de calles con los pedidos insertados como nodos sobre sus calles.

    Cada pedido parte su calle en dos tramos; así la distancia entre dos pedidos es
    el camino mínimo (Dijkstra) por calles. Una calle cerrada no se puede cruzar,
    pero sus pedidos siguen siendo accesibles desde el extremo más cercano.

    'red' es la RedCusco a usar (por defecto, la de Cusco sintético). Las calles
    BLOQUEADAS de la red y las pasadas en 'cerradas' se tratan como cerradas, y el
    factor de tráfico se aplica al costo. 'metrica' elige "peso", "distancia" o
    "tiempo" (por defecto la métrica de la red): las distancias salen en metros
    (o segundos).
    """

    def __init__(self, cerradas: Iterable[frozenset[str]] = frozenset(),
                 red: RedCusco | None = None, metrica: str | None = None) -> None:
        self.cerradas = frozenset(cerradas)
        self.red = red
        self.metrica = metrica
        self.coords: dict[str, tuple[float, float]] = {}
        self.nodo_de: dict[str, str] = {}
        self.dist: dict[str, dict[str, float]] = {}
        self.padre: dict[str, dict[str, str]] = {}
        # (u, v) -> (calle, t_u, t_v): qué parte de qué calle es cada arista del grafo
        self.tramos: dict[tuple[str, str], tuple[Calle, float, float]] = {}
        self._red: RedCusco | None = None

    def preparar(self, puntos: list[Any]) -> None:
        """Construye el grafo aumentado y calcula distancias entre todos los puntos.

        Tiempo O(m (V + E) log V) con m puntos (un Dijkstra por punto).
        """
        red = self.red
        if red is None:
            from . import datos  # import tardío: datos importa este módulo
            red = datos.crear_red()
        self._red = red
        metrica = self.metrica or red.metrica
        cerradas = self.cerradas | red.bloqueadas()

        grafo: dict[str, list[tuple[str, float]]] = {n: [] for n in red.nodos}
        self.coords = {n.nombre: (float(n.x), float(n.y)) for n in red.nodos.values()}
        self.nodo_de = {}
        por_calle: dict[frozenset[str], list[tuple[str, float]]] = {}
        for p in puntos:
            if getattr(p, "nodo", ""):
                self.nodo_de[p.id] = p.nodo
                continue
            if len(p.calle) != 2 or not red.existe_calle(*p.calle):
                raise ValueError(f"El punto {p.id!r} está sobre la calle {tuple(p.calle)!r}, "
                                 f"que no existe en la red")
            calle = red.calle(*p.calle)
            t = p.t if p.calle[0] == calle.origen else 1 - p.t  # orientación de la calle
            clave = "@" + p.id
            self.nodo_de[p.id] = clave
            self.coords[clave] = (p.x, p.y)
            por_calle.setdefault(calle.clave, []).append((clave, t))

        self.tramos = {}
        for calle in red.calles():
            a, b = calle.origen, calle.destino
            largo = calle.costo(metrica)

            def unir(u: str, v: str, costo: float, t_u: float, t_v: float, calle=calle) -> None:
                grafo.setdefault(u, []).append((v, costo))
                grafo.setdefault(v, []).append((u, costo))
                self.tramos[(u, v)] = (calle, t_u, t_v)
                self.tramos[(v, u)] = (calle, t_v, t_u)

            items = sorted(por_calle.get(calle.clave, []), key=lambda it: it[1])
            if calle.clave in cerradas:
                _cadena(unir, a, [it for it in items if it[1] < 0.5], largo, False)
                _cadena(unir, b, [it for it in reversed(items) if it[1] >= 0.5], largo, True)
            else:
                _cadena(unir, a, items, largo, False, final=b)

        self.dist = {}
        self.padre = {}
        for p in puntos:
            d, par = dijkstra_todos(grafo, self.nodo_de[p.id])
            self.dist[p.id] = {q.id: d.get(self.nodo_de[q.id], math.inf) for q in puntos}
            self.padre[p.id] = par

    def distancia(self, a: Any, b: Any) -> float:
        """Distancia por calles entre dos puntos ya preparados. O(1)."""
        return self.dist[a.id][b.id]

    def nodos_camino(self, a: Any, b: Any) -> list[str]:
        """Nodos del grafo aumentado recorridos de a hasta b ([] si no hay camino)."""
        origen, destino = self.nodo_de[a.id], self.nodo_de[b.id]
        padres = self.padre[a.id]
        nodos = [destino]
        while nodos[-1] != origen:
            if nodos[-1] not in padres:
                return []
            nodos.append(padres[nodos[-1]])
        nodos.reverse()
        return nodos

    def camino(self, a: Any, b: Any) -> list[tuple[float, float]]:
        """Coordenadas (x, y) del recorrido por calles de a hasta b, siguiendo el trazado
        real de cada calle si lo tiene. Lista vacía si las calles bloqueadas lo impiden
        (antes se devolvía una recta, que en el mapa parecía un camino que no existe)."""
        nodos = self.nodos_camino(a, b)
        if not nodos:
            return []
        if len(nodos) == 1:
            return [self.coords[nodos[0]]]
        puntos: list[tuple[float, float]] = []
        for u, v in zip(nodos, nodos[1:]):
            calle, t_u, t_v = self.tramos[(u, v)]
            if self._red is not None:
                tramo = self._red.tramo_calle(calle, t_u, t_v)
            else:
                tramo = [self.coords[u], self.coords[v]]
            puntos.extend(tramo if not puntos else tramo[1:])
        return puntos

    def ruta(self, inicio: Any, orden: Iterable[Any]) -> list[tuple[float, float]]:
        """Recorrido completo por calles: inicio, luego cada punto de 'orden'. Los tramos
        imposibles (destino aislado por bloqueos) se omiten."""
        coordenadas: list[tuple[float, float]] = []
        previo = inicio
        for p in orden:
            tramo = self.camino(previo, p)
            if tramo:
                coordenadas.extend(tramo if not coordenadas else tramo[1:])
            previo = p
        return coordenadas
