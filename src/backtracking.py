"""Backtracking (búsqueda exhaustiva con poda) sobre el grafo de Cusco.

Dos problemas:

* Rutas entre dos nodos evitando calles BLOQUEADAS: ``ruta_mas_corta_segura`` (la más corta,
  ramificación y poda) y ``enumerar_rutas_validas`` (todas las rutas simples). Ambas poda
  EXPLÍCITAMENTE las calles bloqueadas (y las cuentan) y devuelven un ``ResultadoRuta``: si
  no hay ruta no lanzan excepciones, devuelven ``encontrada=False`` con un mensaje listo
  para mostrar en pantalla ("Ruta no encontrada ...").
* Orden de visita de varios pedidos: ``orden_optimo_bt`` (búsqueda exhaustiva de
  permutaciones con cota inferior).

Las tres aceptan ``cancelar`` (un ``threading.Event`` o una función sin argumentos) y
``tiempo_max_s`` para poder correr en un hilo sin dejar la interfaz colgada.

Abajo siguen las versiones originales (``todas_las_rutas`` y ``ruta_mas_corta_bt``) que
reciben un grafo de adyacencia y un conjunto ``cerradas``.
"""

import math
import time
from dataclasses import dataclass, field

from .ordenacion import merge_sort

_REVISAR_CADA = 256  # cada cuántos nodos se mira el reloj / la bandera de cancelación


@dataclass
class ResultadoRuta:
    """Resultado de una búsqueda por backtracking (nunca lanza para "sin ruta")."""
    encontrada: bool = False
    costo: float = math.inf
    camino: list = field(default_factory=list)
    rutas: list = field(default_factory=list)   # [(costo, [nodos])] ordenadas por costo
    mensaje: str = ""
    nodos_explorados: int = 0
    podas_bloqueo: int = 0   # calles bloqueadas omitidas
    podas_cota: int = 0      # ramas descartadas porque ya costaban >= la mejor ruta / cota
    cancelado: bool = False
    truncado: bool = False   # se alcanzó un límite (tiempo, nodos o rutas)


def _funcion_de_parada(cancelar, tiempo_max_s):
    """Devuelve una función () -> motivo|None que dice si hay que parar."""
    limite = None if tiempo_max_s is None else time.perf_counter() + tiempo_max_s

    def parar():
        if cancelar is not None:
            pedido = cancelar() if callable(cancelar) else cancelar.is_set()
            if pedido:
                return "cancelado"
        if limite is not None and time.perf_counter() > limite:
            return "tiempo"
        return None
    return parar


def _validar_extremos(red, origen, destino):
    """Mensaje de error si algún extremo no existe; None si todo bien."""
    for nombre, nodo in (("origen", origen), ("destino", destino)):
        if nodo not in red.nodos:
            return f"Ruta no encontrada: el {nombre} {nodo!r} no existe en la red."
    return None


def _mensaje_sin_ruta(red, origen, destino):
    bloqueadas = len(red.bloqueadas())
    return (f"Ruta no encontrada: no existe un camino abierto de {origen} a {destino} "
            f"({bloqueadas} calle{'s' if bloqueadas != 1 else ''} bloqueada"
            f"{'s' if bloqueadas != 1 else ''}).")


def ruta_mas_corta_segura(red, origen, destino, cancelar=None, tiempo_max_s=None,
                          metrica=None):
    """Ruta más corta de 'origen' a 'destino' por backtracking con ramificación y poda.

    Elegir: un vecino no visitado. Verificar: si la calle está BLOQUEADA se poda (se cuenta
    en ``podas_bloqueo``); si el costo parcial ya es >= al de la mejor ruta hallada se poda
    (``podas_cota``). Avanzar: llamada recursiva. Retroceder: desmarcar el nodo. Los
    vecinos se prueban de más barato a más caro para encontrar pronto una buena cota.

    Antes de buscar comprueba con un BFS (O(V + E)) que el destino sea alcanzable por calles
    abiertas: si no lo es devuelve ``encontrada=False`` y el mensaje "Ruta no encontrada ..."
    sin explorar nada (evita una búsqueda exponencial inútil con bloqueos masivos).

    Peor caso O(b^d) (exponencial); con poda explora muy pocos nodos en la práctica.
    Nunca lanza excepciones por falta de ruta; ``cancelado``/``truncado`` indican paradas.
    """
    r = ResultadoRuta()
    error = _validar_extremos(red, origen, destino)
    if error:
        r.mensaje = error
        return r
    if origen == destino:
        r.encontrada, r.costo, r.camino = True, 0.0, [origen]
        r.mensaje = "Origen y destino son el mismo nodo."
        return r
    if not red.es_alcanzable(origen, destino):
        r.mensaje = _mensaje_sin_ruta(red, origen, destino)
        return r

    parar = _funcion_de_parada(cancelar, tiempo_max_s)
    visitado = {origen}
    camino = [origen]
    mejor = {"costo": math.inf, "camino": []}

    def retroceder(nodo, costo):
        r.nodos_explorados += 1
        if r.nodos_explorados % _REVISAR_CADA == 0 and parar():
            return True
        if nodo == destino:
            mejor["costo"], mejor["camino"] = costo, list(camino)
            return False
        for vecino, c, bloqueada in sorted(red.vecinos_todos(nodo, metrica), key=lambda t: t[1]):
            if vecino in visitado:
                continue
            if bloqueada:                       # poda: calle bloqueada
                r.podas_bloqueo += 1
                continue
            if costo + c >= mejor["costo"]:     # poda: cota
                r.podas_cota += 1
                continue
            visitado.add(vecino)
            camino.append(vecino)
            detener = retroceder(vecino, costo + c)
            camino.pop()
            visitado.remove(vecino)
            if detener:
                return True
        return False

    detenido = retroceder(origen, 0.0)
    if detenido:
        motivo = parar()
        r.cancelado, r.truncado = motivo == "cancelado", True
    if mejor["camino"]:
        r.encontrada, r.costo, r.camino = True, mejor["costo"], mejor["camino"]
        r.rutas = [(r.costo, r.camino)]
        r.mensaje = ("Búsqueda interrumpida: se muestra la mejor ruta hallada hasta ahora."
                     if detenido else "Ruta óptima encontrada.")
    else:
        r.mensaje = ("Búsqueda interrumpida antes de hallar una ruta." if detenido
                     else _mensaje_sin_ruta(red, origen, destino))
    return r


def enumerar_rutas_validas(red, origen, destino, factor_cota=None, max_rutas=2000,
                           max_nodos=400000, cancelar=None, tiempo_max_s=None, metrica=None):
    """Todas las rutas simples de 'origen' a 'destino' sin calles bloqueadas.

    'factor_cota' (por ejemplo 1.5) poda las ramas cuyo costo parcial supera ese múltiplo de
    la ruta más corta (calculada antes con ``ruta_mas_corta_segura``); None = sin cota.
    max_rutas, max_nodos, ``cancelar`` y ``tiempo_max_s`` evitan que la búsqueda se descontrole.
    Devuelve un ``ResultadoRuta`` con ``rutas`` ordenadas por costo (la mejor es ``camino``).
    Peor caso exponencial.
    """
    r = ResultadoRuta()
    error = _validar_extremos(red, origen, destino)
    if error:
        r.mensaje = error
        return r
    if origen == destino:
        r.encontrada, r.costo, r.camino, r.rutas = True, 0.0, [origen], [(0.0, [origen])]
        r.mensaje = "Origen y destino son el mismo nodo."
        return r
    if not red.es_alcanzable(origen, destino):
        r.mensaje = _mensaje_sin_ruta(red, origen, destino)
        return r

    cota = None
    if factor_cota is not None:
        base = ruta_mas_corta_segura(red, origen, destino, cancelar, tiempo_max_s, metrica)
        if not base.encontrada:
            return base
        cota = base.costo * max(1.0, factor_cota)

    parar = _funcion_de_parada(cancelar, tiempo_max_s)
    visitado = {origen}
    camino = [origen]
    rutas = []

    def retroceder(nodo, costo):
        r.nodos_explorados += 1
        if r.nodos_explorados % _REVISAR_CADA == 0 and parar():
            return True
        if len(rutas) >= max_rutas or r.nodos_explorados >= max_nodos:
            r.truncado = True
            return True
        if nodo == destino:
            rutas.append((costo, list(camino)))
            return False
        for vecino, c, bloqueada in red.vecinos_todos(nodo, metrica):
            if vecino in visitado:
                continue
            if bloqueada:
                r.podas_bloqueo += 1
                continue
            if cota is not None and costo + c > cota:
                r.podas_cota += 1
                continue
            visitado.add(vecino)
            camino.append(vecino)
            detener = retroceder(vecino, costo + c)
            camino.pop()
            visitado.remove(vecino)
            if detener:
                return True
        return False

    detenido = retroceder(origen, 0.0)
    if detenido:
        r.truncado = True
        r.cancelado = parar() == "cancelado"
    r.rutas = merge_sort(rutas, lambda t: t[0])
    if r.rutas:
        r.encontrada, (r.costo, r.camino) = True, r.rutas[0]
        r.mensaje = (f"{len(r.rutas)} rutas válidas"
                     + (" (búsqueda truncada por límite)." if r.truncado else "."))
    else:
        r.mensaje = _mensaje_sin_ruta(red, origen, destino)
    return r


def orden_optimo_bt(inicio, pedidos, dist, cancelar=None, tiempo_max_s=None):
    """Orden de visita de costo mínimo por backtracking (búsqueda exhaustiva con poda).

    Explora permutaciones de los pedidos desde 'inicio' (ruta abierta). Poda: (1) cota del
    mejor orden encontrado (empieza con el del vecino más cercano) y (2) cota inferior
    admisible: cada pedido pendiente debe ser "entrado" por alguna arista de costo >= su
    entrada mínima, así que costo parcial + suma de entradas mínimas >= mejor => se descarta.

    Devuelve (orden, costo, estadísticas) con estadísticas = {"nodos", "podas", "completo",
    "cancelado"}; ``completo`` es True solo si terminó sin parar, es decir, si el orden es
    ÓPTIMO garantizado. Peor caso O(n!) (por eso ``tiempo_max_s``).
    """
    n = len(pedidos)
    stats = {"nodos": 0, "podas": 0, "completo": True, "cancelado": False}
    if n == 0:
        return [], 0.0, stats
    d = [[dist(a, b) for b in pedidos] for a in pedidos]
    d0 = [dist(inicio, p) for p in pedidos]
    inf = math.inf

    # cota inicial: vecino más cercano
    usados_nn, actual, orden_nn, costo_nn = [False] * n, -1, [], 0.0
    for _ in range(n):
        fila = d0 if actual == -1 else d[actual]
        j = min((k for k in range(n) if not usados_nn[k]), key=lambda k: fila[k])
        costo_nn += fila[j]
        usados_nn[j] = True
        orden_nn.append(j)
        actual = j
    mejor = {"costo": costo_nn, "orden": orden_nn}

    entrada_min = [min([d0[j]] + [d[i][j] for i in range(n) if i != j]) for j in range(n)]
    parar = _funcion_de_parada(cancelar, tiempo_max_s)
    usado = [False] * n
    orden = []

    def retroceder(actual, costo, cota_resto):
        stats["nodos"] += 1
        if stats["nodos"] % _REVISAR_CADA == 0 and parar():
            return True
        if len(orden) == n:
            if costo < mejor["costo"]:
                mejor["costo"], mejor["orden"] = costo, list(orden)
            return False
        fila = d0 if actual == -1 else d[actual]
        for j in sorted((k for k in range(n) if not usado[k]), key=lambda k: fila[k]):
            nuevo = costo + fila[j]
            nueva_cota = cota_resto - entrada_min[j]
            if nuevo + nueva_cota >= mejor["costo"] - 1e-9:
                stats["podas"] += 1
                continue
            usado[j] = True
            orden.append(j)
            detener = retroceder(j, nuevo, nueva_cota)
            orden.pop()
            usado[j] = False
            if detener:
                return True
        return False

    detenido = retroceder(-1, 0.0, sum(entrada_min))
    if detenido:
        stats["completo"] = False
        stats["cancelado"] = parar() == "cancelado"
    return [pedidos[j] for j in mejor["orden"]], mejor["costo"], stats


# ======================================================================================
# Versiones originales (grafo de adyacencia + conjunto 'cerradas')
# ======================================================================================


def todas_las_rutas(grafo, origen, destino, cerradas=frozenset(), cota=None,
                    max_rutas=5000, max_nodos=400000):
    """Encuentra rutas simples (sin repetir nodos) de origen a destino.

    Elegir: un vecino no visitado. Verificar: la calle no esta cerrada y el costo
    parcial no pasa de 'cota' (poda). Avanzar: llamada recursiva. Retroceder:
    desmarcar el nodo y sacarlo del camino.

    Devuelve (rutas ordenadas por costo [(costo, [nodos])], estadisticas).
    Peor caso O(b^d) (exponencial); la cota y las calles cerradas podan ramas.
    max_rutas y max_nodos evitan que la interfaz se cuelgue.
    """
    rutas = []
    stats = {"nodos": 0, "podas": 0, "truncado": False}
    visitado = {origen}
    camino = [origen]

    def retroceder(nodo, costo):
        stats["nodos"] += 1
        if nodo == destino:
            rutas.append((costo, list(camino)))
            return
        for vecino, c in grafo[nodo]:
            if stats["truncado"]:
                return
            if len(rutas) >= max_rutas or stats["nodos"] >= max_nodos:
                stats["truncado"] = True
                return
            if vecino in visitado or frozenset((nodo, vecino)) in cerradas:
                continue
            nuevo = costo + c
            if cota is not None and nuevo > cota:
                stats["podas"] += 1
                continue
            visitado.add(vecino)
            camino.append(vecino)
            retroceder(vecino, nuevo)
            camino.pop()
            visitado.remove(vecino)

    retroceder(origen, 0.0)
    return merge_sort(rutas, lambda r: r[0]), stats


def ruta_mas_corta_bt(grafo, origen, destino, cerradas=frozenset()):
    """Backtracking con ramificacion y poda (branch and bound) para la ruta mas corta.

    Cada vez que encuentra una ruta, su costo pasa a ser la cota: cualquier camino
    parcial que ya cueste igual o mas se poda. Prueba primero las calles baratas.

    Devuelve (costo, [nodos], estadisticas); (inf, [], stats) si no hay ruta.
    Peor caso exponencial, pero en la practica explora muy pocos nodos.
    """
    mejor = {"costo": math.inf, "camino": []}
    stats = {"nodos": 0, "podas": 0, "truncado": False}
    visitado = {origen}
    camino = [origen]

    def retroceder(nodo, costo):
        stats["nodos"] += 1
        if costo >= mejor["costo"]:
            stats["podas"] += 1
            return
        if nodo == destino:
            mejor["costo"] = costo
            mejor["camino"] = list(camino)
            return
        for vecino, c in sorted(grafo[nodo], key=lambda t: t[1]):
            if vecino in visitado or frozenset((nodo, vecino)) in cerradas:
                continue
            visitado.add(vecino)
            camino.append(vecino)
            retroceder(vecino, costo + c)
            camino.pop()
            visitado.remove(vecino)

    retroceder(origen, 0.0)
    return mejor["costo"], mejor["camino"], stats
