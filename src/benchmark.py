"""Benchmark de rendimiento y análisis Big-O de los algoritmos del proyecto.

Sin dependencias de la interfaz: ``gui.py`` lo llama desde un hilo y dibuja los resultados.

* ``comparar``: ejecuta TODOS los algoritmos de una familia sobre el MISMO escenario y mide
  el tiempo real con ``time.perf_counter()`` (mediana de varias repeticiones si el
  algoritmo es rápido). Devuelve filas con tiempo (ms), distancia total (km) y si el
  resultado es óptimo garantizado.
* ``curva_tiempos``: mide el tiempo para distintos tamaños de entrada N (la gráfica
  "Tiempo de ejecución vs N" del informe).

Familias: "Rutas" (visitar N pedidos desde un repartidor), "Mochila" (qué pedidos cargar) y
"Ordenación". Todas las rutas se miden con la MISMA matriz de distancias por calles
(``RedVial``), que se prepara una sola vez y no entra en el tiempo medido.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import backtracking, datos, divide_venceras, ordenacion, programacion_dinamica, voraz
from .red import RedCusco, RedVial

FAMILIAS = ("Rutas", "Mochila", "Ordenación")


# --------------------------------------------------------------------------- estructuras
@dataclass
class Contexto:
    """Todo lo que necesita un algoritmo para correr sobre un escenario de tamaño n."""
    n: int
    pedidos: list
    inicio: Any = None
    dist: Callable | None = None
    capacidad_kg: int = 30
    limites: tuple = datos.LIMITES
    cancelar: Any = None
    tiempo_max_s: float = 10.0


@dataclass
class Algoritmo:
    nombre: str
    ejecutar: Callable[[Contexto], dict]   # devuelve {"distancia_m"|"valor"|None, "optimo", "nota"}
    complejidad: str
    max_n: int | None = None               # tamaño máximo razonable (None = sin tope)


@dataclass
class FilaBenchmark:
    algoritmo: str
    tiempo_ms: float | None
    distancia_km: float | None = None
    valor: float | None = None
    optimo: bool | None = None            # True/False; None si no aplica
    complejidad: str = ""
    delta_pct: float | None = None        # % de más frente al mejor resultado óptimo conocido
    nota: str = ""

    @property
    def optimo_texto(self) -> str:
        return {True: "Sí", False: "No"}.get(self.optimo, "—")


# --------------------------------------------------------------------------- algoritmos
def _ruta_voraz(c: Contexto) -> dict:
    _, total = voraz.ruta_vecino_mas_cercano(c.inicio, c.pedidos, c.dist)
    return {"distancia_m": total, "optimo": False}


def _ruta_dyv(c: Contexto) -> dict:
    r = divide_venceras.dividir_y_vencer(c.inicio, c.pedidos, c.limites, c.dist)
    return {"distancia_m": r.distancia, "optimo": False,
            "nota": f"{len(r.zonas)} zonas, {len(r.empalmes)} empalmes"}


def _ruta_pd(c: Contexto) -> dict:
    _, total = programacion_dinamica.ruta_optima_held_karp(c.inicio, c.pedidos, c.dist)
    return {"distancia_m": total, "optimo": True}


def _ruta_bt(c: Contexto) -> dict:
    _, total, st = backtracking.orden_optimo_bt(c.inicio, c.pedidos, c.dist, c.cancelar,
                                                c.tiempo_max_s)
    nota = f"{st['nodos']} nodos, {st['podas']} podas"
    if not st["completo"]:
        nota = "tiempo agotado o cancelado: no garantiza el óptimo; " + nota
    return {"distancia_m": total, "optimo": st["completo"], "nota": nota}


def _mochila_voraz(c: Contexto) -> dict:
    _, valor, peso = voraz.mochila_voraz(c.pedidos, c.capacidad_kg)
    return {"valor": valor, "optimo": False, "nota": f"{peso}/{c.capacidad_kg} kg"}


def _mochila_pd(c: Contexto) -> dict:
    _, valor, peso = programacion_dinamica.mochila_01(c.pedidos, c.capacidad_kg)
    return {"valor": valor, "optimo": True, "nota": f"{peso}/{c.capacidad_kg} kg"}


def _mochila_memo(c: Contexto) -> dict:
    _, valor, peso = programacion_dinamica.mochila_01_memo(c.pedidos, c.capacidad_kg)
    return {"valor": valor, "optimo": True, "nota": f"{peso}/{c.capacidad_kg} kg"}


def _clave_orden(p):
    return (p.urgencia, -p.ventana_fin, p.id)


def _orden(funcion):
    def correr(c: Contexto) -> dict:
        resultado = funcion(c.pedidos, _clave_orden, True)
        ok = all(_clave_orden(a) >= _clave_orden(b) for a, b in zip(resultado, resultado[1:]))
        return {"optimo": None, "nota": "orden correcto" if ok else "ORDEN INCORRECTO"}
    return correr


ALGORITMOS: dict[str, list[Algoritmo]] = {
    "Rutas": [
        Algoritmo("Voraz (vecino más cercano)", _ruta_voraz, "O(n²)"),
        Algoritmo("Divide y Vencerás (cuadrantes + empalme)", _ruta_dyv, "O(n²) (2-opt) / O(n log n) dividir"),
        Algoritmo("Prog. Dinámica (Held-Karp)", _ruta_pd, "O(n²·2ⁿ)",
                  max_n=programacion_dinamica.MAX_PEDIDOS_HELD_KARP),
        Algoritmo("Backtracking (ramificación y poda)", _ruta_bt, "O(n!) peor caso", max_n=14),
    ],
    "Mochila": [
        Algoritmo("Voraz (valor/peso)", _mochila_voraz, "O(n log n)"),
        Algoritmo("Prog. Dinámica (tabulación)", _mochila_pd, "O(n·W)"),
        Algoritmo("Prog. Dinámica (memoización)", _mochila_memo, "O(n·W)"),
    ],
    "Ordenación": [
        Algoritmo("MergeSort", _orden(ordenacion.merge_sort), "O(n log n)"),
        Algoritmo("QuickSort", _orden(ordenacion.quick_sort), "O(n log n) promedio"),
        Algoritmo("HeapSort", _orden(ordenacion.heap_sort), "O(n log n)"),
    ],
}


# --------------------------------------------------------------------------- medición
def medir(funcion: Callable[[], Any], repeticiones: int = 3,
          rapido_ms: float = 50.0) -> tuple[Any, float]:
    """Ejecuta 'funcion' y devuelve (resultado, tiempo en ms) con ``time.perf_counter()``.

    La primera ejecución fija el resultado. Si tardó menos de 'rapido_ms' se repite hasta
    'repeticiones' veces y se reporta la mediana (reduce el ruido del sistema operativo);
    si fue lenta se deja esa única medición.
    """
    t0 = time.perf_counter()
    resultado = funcion()
    primero = (time.perf_counter() - t0) * 1000
    tiempos = [primero]
    if primero < rapido_ms:
        for _ in range(max(0, repeticiones - 1)):
            t0 = time.perf_counter()
            funcion()
            tiempos.append((time.perf_counter() - t0) * 1000)
    return resultado, statistics.median(tiempos)


def _parar(cancelar) -> bool:
    if cancelar is None:
        return False
    return cancelar() if callable(cancelar) else cancelar.is_set()


def contexto_para(n: int, semilla: int, red: RedCusco, repartidor=None, deposito=None,
                  capacidad_kg: int = 30, cancelar=None, tiempo_max_s: float = 10.0,
                  familia: str = "Rutas") -> Contexto:
    """Escenario de n pedidos aleatorios (misma semilla = mismos datos) con distancias por calles."""
    pedidos = datos.generar_pedidos(n, semilla, red)
    repartidor = repartidor or datos.crear_repartidores()[0]
    contexto = Contexto(n, pedidos, repartidor, None, capacidad_kg,
                        limites=red.limites(), cancelar=cancelar, tiempo_max_s=tiempo_max_s)
    if familia == "Rutas":
        rv = RedVial(red=red)
        rv.preparar(pedidos + [repartidor])
        contexto.dist = rv.distancia
    return contexto


# --------------------------------------------------------------------------- comparación
def comparar(familia: str, contexto: Contexto, repeticiones: int = 3) -> list[FilaBenchmark]:
    """Corre todos los algoritmos de 'familia' sobre el mismo escenario.

    Devuelve una fila por algoritmo. ``delta_pct`` compara cada distancia con la mejor
    distancia ÓPTIMA garantizada de la tabla (o con la menor si ninguna lo es). Los
    algoritmos que no soportan ese tamaño quedan con ``tiempo_ms=None`` y una nota.
    """
    if familia not in ALGORITMOS:
        raise ValueError(f"Familia desconocida {familia!r}; use una de {FAMILIAS}")
    filas: list[FilaBenchmark] = []
    for alg in ALGORITMOS[familia]:
        if _parar(contexto.cancelar):
            break
        if alg.max_n is not None and contexto.n > alg.max_n:
            filas.append(FilaBenchmark(alg.nombre, None, complejidad=alg.complejidad,
                                       nota=f"omitido: n={contexto.n} > {alg.max_n} (explosión exponencial)"))
            continue
        resultado, ms = medir(lambda a=alg: a.ejecutar(contexto), repeticiones)
        metros = resultado.get("distancia_m")
        filas.append(FilaBenchmark(
            alg.nombre, ms,
            distancia_km=None if metros is None else metros / 1000.0,
            valor=resultado.get("valor"), optimo=resultado.get("optimo"),
            complejidad=alg.complejidad, nota=resultado.get("nota", "")))

    # brecha frente al mejor resultado (distancias: menor es mejor; valores: mayor es mejor)
    con_dist = [f for f in filas if f.distancia_km is not None]
    if con_dist:
        optimas = [f.distancia_km for f in con_dist if f.optimo]
        referencia = min(optimas) if optimas else min(f.distancia_km for f in con_dist)
        for f in con_dist:
            f.delta_pct = (f.distancia_km / referencia - 1) * 100 if referencia > 0 else 0.0
    con_valor = [f for f in filas if f.valor is not None]
    if con_valor:
        optimos = [f.valor for f in con_valor if f.optimo]
        referencia = max(optimos) if optimos else max(f.valor for f in con_valor)
        for f in con_valor:
            f.delta_pct = (1 - f.valor / referencia) * 100 if referencia > 0 else 0.0
    return filas


def a_texto(filas: list[FilaBenchmark]) -> str:
    """Matriz comparativa como texto alineado (para el log o el informe)."""
    encabezado = f"{'Algoritmo':<44}{'Tiempo (ms)':>13}{'Dist. (km)':>12}{'Valor':>8}{'Óptimo':>8}{'Δ%':>8}"
    lineas = [encabezado, "-" * len(encabezado)]
    for f in filas:
        t = "—" if f.tiempo_ms is None else f"{f.tiempo_ms:.3f}"
        d = "—" if f.distancia_km is None else f"{f.distancia_km:.3f}"
        v = "—" if f.valor is None else f"{f.valor:g}"
        dp = "—" if f.delta_pct is None else f"{f.delta_pct:.1f}"
        lineas.append(f"{f.algoritmo:<44}{t:>13}{d:>12}{v:>8}{f.optimo_texto:>8}{dp:>8}")
    return "\n".join(lineas)


# --------------------------------------------------------------------------- curva T(n)
@dataclass
class Curvas:
    """Resultado de ``curva_tiempos``: para cada algoritmo, los puntos (n, ms) medidos."""
    familia: str
    series: dict[str, list[tuple[int, float]]] = field(default_factory=dict)
    notas: list[str] = field(default_factory=list)


def curva_tiempos(familia: str, tamanos: list[int], semilla: int = 7, red: RedCusco | None = None,
                  repeticiones: int = 3, tiempo_max_s: float = 10.0, capacidad_kg: int = 30,
                  cancelar=None, progreso: Callable[[float, str], None] | None = None,
                  algoritmos: list[str] | None = None) -> Curvas:
    """Mide el tiempo de cada algoritmo para cada tamaño N en 'tamanos'.

    Un algoritmo deja de medirse para tamaños mayores cuando supera su ``max_n`` o cuando
    agota 'tiempo_max_s' (así la curva exponencial "se corta" en vez de colgar el programa).
    Para "Ordenación" y "Mochila" el eje N es la cantidad de pedidos; la capacidad de la
    mochila crece con N (3 kg por pedido) para que el problema siga siendo interesante.
    """
    if familia not in ALGORITMOS:
        raise ValueError(f"Familia desconocida {familia!r}; use una de {FAMILIAS}")
    red = red or datos.crear_red()
    tamanos = sorted({int(n) for n in tamanos if int(n) >= 1})
    if not tamanos:
        raise ValueError("Indica al menos un tamaño N >= 1")
    elegidos = [a for a in ALGORITMOS[familia] if algoritmos is None or a.nombre in algoritmos]
    curvas = Curvas(familia, {a.nombre: [] for a in elegidos})
    vivos = {a.nombre for a in elegidos}
    total_pasos = len(tamanos)

    for paso, n in enumerate(tamanos, 1):
        if _parar(cancelar):
            curvas.notas.append("Medición cancelada.")
            break
        if progreso:
            progreso((paso - 1) / total_pasos, f"Midiendo N = {n} ({paso}/{total_pasos})")
        cap = capacidad_kg if familia != "Mochila" else max(capacidad_kg, 3 * n)
        ctx = contexto_para(n, semilla, red, capacidad_kg=cap, cancelar=cancelar,
                            tiempo_max_s=tiempo_max_s, familia=familia)
        for alg in elegidos:
            if alg.nombre not in vivos:
                continue
            if alg.max_n is not None and n > alg.max_n:
                vivos.discard(alg.nombre)
                curvas.notas.append(f"{alg.nombre}: se omite desde N = {n} (tope {alg.max_n}).")
                continue
            resultado, ms = medir(lambda a=alg: a.ejecutar(ctx), repeticiones)
            curvas.series[alg.nombre].append((n, ms))
            if resultado.get("optimo") is False and "tiempo agotado" in resultado.get("nota", ""):
                vivos.discard(alg.nombre)
                curvas.notas.append(f"{alg.nombre}: agotó {tiempo_max_s:g} s en N = {n}; "
                                    f"no se mide con tamaños mayores.")
    if progreso:
        progreso(1.0, "Medición terminada")
    return curvas
