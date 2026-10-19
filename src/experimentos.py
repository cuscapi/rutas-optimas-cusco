"""Experimentos E1 a E4 del plan de tesis, ejecutados en lote y guardados en CSV.

Implementa exactamente el diseño del capítulo 7 (Tablas 7.3 a 7.6):

=========  ===========================================  ============  =========
Exp.       Factores                                      Config.       Instancias
=========  ===========================================  ============  =========
E1-Ruta    n ∈ {6, 8, 10, 12}                            4             120
E1-Carga   n ∈ {15, 25, 40} × W ∈ {25, 30}               6             180
E2         calles bloqueadas ∈ {0, 2, 4}                 3              90
E3a        n = 12 × m ∈ {4, 6}                           2              60
E3b        n ∈ {24, 36} × m ∈ {4, 6}                     4             120
E4         36 pedidos, 3 repartidores, 2 bloqueos        1              30
=========  ===========================================  ============  =========

Protocolo de medición (Johnson, 2002): una ejecución de calentamiento que no se registra,
5 ejecuciones medidas con ``time.perf_counter()`` y el recolector de basura desactivado,
y se reporta la mediana. Los métodos exponenciales tienen un tope de 10 s.

Análisis: Wilcoxon de rangos con signo (Pratt para empates), ajuste de Holm por familia,
tamaño del efecto r = z/√N e IC 95 % por bootstrap (``estadistica``).

Uso (desde la carpeta del proyecto, sin abrir la interfaz):

    python -m src.experimentos                       # 30 semillas, todo (unos minutos)
    python -m src.experimentos --semillas 5 --rapido # prueba corta
    python -m src.experimentos --solo E1-Ruta E2     # algunos experimentos
    python -m src.experimentos --calles-reales       # con el trazado de OpenStreetMap
"""

from __future__ import annotations

import csv
import gc
import json
import math
import os
import platform
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import (backtracking, datos, divide_venceras, estadistica, programacion_dinamica,
               voraz)
from .red import RedCusco, RedVial

EXPERIMENTOS = ("E1-Ruta", "E1-Carga", "E2", "E3a", "E3b", "E4")


@dataclass
class Configuracion:
    semillas: int = 30                 # semillas 1..N por configuración
    repeticiones: int = 5              # ejecuciones medidas (más 1 de calentamiento)
    tiempo_max_s: float = 10.0         # tope de los métodos exponenciales
    solo: tuple = EXPERIMENTOS
    red: RedCusco | None = None        # None = red de Cusco del proyecto
    cancelar: Any = None               # threading.Event o función sin argumentos
    progreso: Callable[[float, str], None] | None = None
    remuestreos: int = 10_000          # bootstrap


class Cancelado(Exception):
    pass


# --------------------------------------------------------------------------- utilidades
def _parar(cfg: Configuracion) -> None:
    c = cfg.cancelar
    if c is not None and (c() if callable(c) else c.is_set()):
        raise Cancelado()


def medir(funcion: Callable[[], Any], repeticiones: int = 5) -> tuple[Any, float]:
    """(resultado, mediana en ms): 1 calentamiento + 'repeticiones' con gc desactivado.
    Si el calentamiento tarda más de 2 s se registra solo esa medición (método lento)."""
    activo = gc.isenabled()
    gc.disable()
    try:
        t0 = time.perf_counter()
        resultado = funcion()
        calentamiento = (time.perf_counter() - t0) * 1000
        if calentamiento > 2000 or repeticiones <= 0:
            return resultado, calentamiento
        tiempos = []
        for _ in range(repeticiones):
            t0 = time.perf_counter()
            funcion()
            tiempos.append((time.perf_counter() - t0) * 1000)
        return resultado, statistics.median(tiempos)
    finally:
        if activo:
            gc.enable()


def _red_base(cfg: Configuracion) -> RedCusco:
    return cfg.red.copia() if cfg.red is not None else datos.crear_red()


def _repartidor_a(red: RedCusco):
    rep = datos.crear_repartidores()[0]
    if rep.nodo in red.nodos:
        rep.x, rep.y = red.nodos[rep.nodo].x, red.nodos[rep.nodo].y
    return rep


def _red_vial(red: RedCusco, puntos: list) -> RedVial:
    rv = RedVial(red=red)
    rv.preparar(puntos)
    return rv


def _escribir_csv(ruta: Path, filas: list[dict]) -> None:
    if not filas:
        return
    campos = list(filas[0])
    for f in filas[1:]:
        for k in f:
            if k not in campos:
                campos.append(k)
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=campos)
        escritor.writeheader()
        for f in filas:
            escritor.writerow({k: (round(v, 6) if isinstance(v, float) else v) for k, v in f.items()})


def _km(m: float) -> float:
    return m / 1000.0


# --------------------------------------------------------------------------- E1
def e1_ruta(cfg: Configuracion, avance: Callable[[str], None]) -> list[dict]:
    filas = []
    for n in (6, 8, 10, 12):
        for s in range(1, cfg.semillas + 1):
            _parar(cfg)
            avance(f"E1-Ruta n={n} semilla {s}")
            red = _red_base(cfg)
            pedidos = datos.generar_pedidos(n, s, red)
            rep = _repartidor_a(red)
            rv = _red_vial(red, pedidos + [rep])
            (o_v, d_v), t_v = medir(lambda: voraz.ruta_vecino_mas_cercano(rep, pedidos, rv.distancia), cfg.repeticiones)
            (o_h, d_h), t_h = medir(lambda: programacion_dinamica.ruta_optima_held_karp(rep, pedidos, rv.distancia), cfg.repeticiones)
            t0 = time.perf_counter()
            _, d_b, st = backtracking.orden_optimo_bt(rep, pedidos, rv.distancia, cfg.cancelar, cfg.tiempo_max_s)
            t_b = (time.perf_counter() - t0) * 1000
            filas.append({"semilla": s, "n": n, "dist_vmc_km": _km(d_v), "dist_hk_km": _km(d_h),
                          "brecha_pct": (d_v / d_h - 1) * 100 if d_h else 0.0,
                          "dist_bt_km": _km(d_b), "bt_completo": st["completo"],
                          "bt_coincide_hk": abs(d_b - d_h) < 1e-6 if st["completo"] else "",
                          "nodos_bt": st["nodos"], "t_vmc_ms": t_v, "t_hk_ms": t_h, "t_bt_ms": t_b})
    return filas


def e1_carga(cfg: Configuracion, avance) -> list[dict]:
    filas = []
    for n in (15, 25, 40):
        for w in (25, 30):
            for s in range(1, cfg.semillas + 1):
                _parar(cfg)
                avance(f"E1-Carga n={n} W={w} semilla {s}")
                pedidos = datos.generar_pedidos(n, s, _red_base(cfg))
                (_, v_v, p_v), t_v = medir(lambda: voraz.mochila_voraz(pedidos, w), cfg.repeticiones)
                (_, v_p, p_p), t_p = medir(lambda: programacion_dinamica.mochila_01(pedidos, w), cfg.repeticiones)
                filas.append({"semilla": s, "n": n, "W": w, "valor_voraz": v_v, "valor_pd": v_p,
                              "pct_optimo": 100 * v_v / v_p if v_p else 100.0,
                              "peso_voraz": p_v, "peso_pd": p_p, "t_voraz_ms": t_v, "t_pd_ms": t_p})
    return filas


# --------------------------------------------------------------------------- E2
def e2(cfg: Configuracion, avance) -> tuple[list[dict], list[dict]]:
    filas, reemplazadas = [], []
    base = _red_base(cfg)
    nombres = sorted(base.nodos)
    calles = [(c.origen, c.destino) for c in base.calles()]
    for nivel in (0, 2, 4):
        semilla, conseguidas = 0, 0
        while conseguidas < cfg.semillas:
            semilla += 1
            _parar(cfg)
            avance(f"E2 bloqueos={nivel} semilla {semilla}")
            azar = random.Random(semilla * 1000 + nivel)
            origen, destino = azar.sample(nombres, 2)
            bloqueadas = azar.sample(calles, nivel)
            red = base.copia()
            for a, b in bloqueadas:
                red.bloquear_calle(a, b)
            texto_bloq = "; ".join(f"{a}-{b}" for a, b in bloqueadas)
            d_dij, _ = voraz.dijkstra(red.a_adyacencia(), origen, destino)
            ryp = backtracking.ruta_mas_corta_segura(red, origen, destino, cfg.cancelar, cfg.tiempo_max_s)
            if not ryp.encontrada:
                sin = backtracking.enumerar_rutas_validas(red, origen, destino, None, 10**7, 10**7)
                reemplazadas.append({"nivel": nivel, "semilla": semilla, "origen": origen, "destino": destino,
                                     "bloqueadas": texto_bloq,
                                     "todas_coinciden_sin_ruta": math.isinf(d_dij) and not sin.encontrada})
                continue
            sin = backtracking.enumerar_rutas_validas(red, origen, destino, None, 10**7, 10**7,
                                                      cfg.cancelar, cfg.tiempo_max_s)
            cota = backtracking.enumerar_rutas_validas(red, origen, destino, 1.5, 10**7, 10**7,
                                                       cfg.cancelar, cfg.tiempo_max_s)
            conseguidas += 1
            filas.append({
                "nivel_bloqueo": nivel, "semilla": semilla, "origen": origen, "destino": destino,
                "bloqueadas": texto_bloq,
                "rutas_sin_poda": len(sin.rutas), "nodos_sin_poda": sin.nodos_explorados,
                "rutas_cota": len(cota.rutas), "nodos_cota": cota.nodos_explorados,
                "podas_cota_variante_b": cota.podas_cota,
                "nodos_ryp": ryp.nodos_explorados, "podas_bloqueo_ryp": ryp.podas_bloqueo,
                "podas_cota_ryp": ryp.podas_cota, "dist_ryp_km": _km(ryp.costo),
                "dist_dijkstra_km": _km(d_dij), "coincide_dijkstra": abs(ryp.costo - d_dij) < 1e-6,
                "reduccion_pct": 100 * (1 - ryp.nodos_explorados / sin.nodos_explorados) if sin.nodos_explorados else 0.0,
                "truncado": sin.truncado or cota.truncado or ryp.truncado,
            })
    return filas, reemplazadas


# --------------------------------------------------------------------------- E3
def e3a(cfg: Configuracion, avance) -> list[dict]:
    filas = []
    for s in range(1, cfg.semillas + 1):
        _parar(cfg)
        red = _red_base(cfg)
        pedidos = datos.generar_pedidos(12, s, red)
        rep = _repartidor_a(red)
        rv = _red_vial(red, pedidos + [rep])
        limites = red.limites()
        avance(f"E3a semilla {s}")
        (_, d_h), t_h = medir(lambda: programacion_dinamica.ruta_optima_held_karp(rep, pedidos, rv.distancia), cfg.repeticiones)
        for m in (4, 6):
            r, t_d = medir(lambda: divide_venceras.dividir_y_vencer(rep, pedidos, limites, rv.distancia, m, 4), cfg.repeticiones)
            filas.append({"semilla": s, "n": 12, "m": m, "dist_hk_km": _km(d_h), "dist_dyv_km": _km(r.distancia),
                          "exceso_pct": (r.distancia / d_h - 1) * 100 if d_h else 0.0,
                          "t_hk_ms": t_h, "t_dyv_ms": t_d, "aceleracion": t_h / t_d if t_d else math.inf,
                          "zonas": len(r.zonas)})
    return filas


def e3b(cfg: Configuracion, avance) -> list[dict]:
    filas = []
    for n in (24, 36):
        for s in range(1, cfg.semillas + 1):
            _parar(cfg)
            red = _red_base(cfg)
            pedidos = datos.generar_pedidos(n, s, red)
            rep = _repartidor_a(red)
            rv = _red_vial(red, pedidos + [rep])
            limites = red.limites()
            avance(f"E3b n={n} semilla {s}")
            (_, d_v), t_v = medir(lambda: voraz.ruta_vecino_mas_cercano(rep, pedidos, rv.distancia), cfg.repeticiones)
            for m in (4, 6):
                r, t_d = medir(lambda: divide_venceras.dividir_y_vencer(rep, pedidos, limites, rv.distancia, m, 4), cfg.repeticiones)
                filas.append({"semilla": s, "n": n, "m": m, "dist_vmc_km": _km(d_v), "dist_dyv_km": _km(r.distancia),
                              "diferencia_pct": (1 - r.distancia / d_v) * 100 if d_v else 0.0,
                              "t_vmc_ms": t_v, "t_dyv_ms": t_d, "zonas": len(r.zonas)})
    return filas


# --------------------------------------------------------------------------- E4
def flujo_voraz(pedidos, reps, rv) -> dict:
    asignacion, pendientes = voraz.asignar_mas_cercano(pedidos, reps, rv.distancia)
    km_total, valor, atendidos = 0.0, 0, 0
    for r in reps:
        lista = asignacion[r.nombre]
        if lista:
            _, total = voraz.ruta_vecino_mas_cercano(r, lista, rv.distancia)
            km_total += total
            valor += sum(p.valor for p in lista)
            atendidos += len(lista)
    return {"valor": valor, "atendidos": atendidos, "metros": km_total}


def flujo_integrado(pedidos, reps, rv, limites) -> dict:
    """Zonas (una por repartidor) + mochila 0/1 + Held-Karp (o DyV si carga > 12)."""
    zonas = divide_venceras.dividir_en_zonas(pedidos, len(reps), limites)
    libres = list(reps)
    km_total, valor, atendidos = 0.0, 0, 0
    for caja, lista in zonas:
        cx, cy = (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2
        r = min(libres, key=lambda rr: math.hypot(rr.x - cx, rr.y - cy))
        libres.remove(r)
        candidatos = [p for p in lista if not math.isinf(rv.distancia(r, p))]
        elegidos, v, _ = programacion_dinamica.mochila_01(candidatos, r.capacidad)
        if not elegidos:
            continue
        if len(elegidos) <= programacion_dinamica.MAX_PEDIDOS_HELD_KARP:
            _, total = programacion_dinamica.ruta_optima_held_karp(r, elegidos, rv.distancia)
        else:
            total = divide_venceras.dividir_y_vencer(r, elegidos, limites, rv.distancia).distancia
        km_total += total
        valor += v
        atendidos += len(elegidos)
    return {"valor": valor, "atendidos": atendidos, "metros": km_total}


def e4(cfg: Configuracion, avance) -> list[dict]:
    filas = []
    base = _red_base(cfg)
    calles = [(c.origen, c.destino) for c in base.calles()]
    for s in range(1, cfg.semillas + 1):
        _parar(cfg)
        avance(f"E4 semilla {s}")
        red = base.copia()
        pedidos = datos.generar_pedidos(36, s, red)
        bloqueadas = random.Random(s * 7 + 4).sample(calles, 2)
        for a, b in bloqueadas:
            red.bloquear_calle(a, b)
        reps = datos.crear_repartidores()
        for r in reps:
            r.x, r.y = red.nodos[r.nodo].x, red.nodos[r.nodo].y
        rv = _red_vial(red, pedidos + reps)
        limites = red.limites()
        fv, t_v = medir(lambda: flujo_voraz(pedidos, reps, rv), cfg.repeticiones)
        fi, t_i = medir(lambda: flujo_integrado(pedidos, reps, rv, limites), cfg.repeticiones)
        filas.append({
            "semilla": s, "bloqueadas": "; ".join(f"{a}-{b}" for a, b in bloqueadas),
            "valor_voraz": fv["valor"], "valor_integrado": fi["valor"],
            "atendidos_voraz": fv["atendidos"], "atendidos_integrado": fi["atendidos"],
            "km_voraz": _km(fv["metros"]), "km_integrado": _km(fi["metros"]),
            "km_por_pedido_voraz": _km(fv["metros"]) / fv["atendidos"] if fv["atendidos"] else 0.0,
            "km_por_pedido_integrado": _km(fi["metros"]) / fi["atendidos"] if fi["atendidos"] else 0.0,
            "t_voraz_ms": t_v, "t_integrado_ms": t_i})
    return filas


# --------------------------------------------------------------------------- análisis
def _prueba(nombre, filas, filtro, dif, alternativa, cfg) -> dict:
    sub = [f for f in filas if filtro(f)]
    d = [dif(f) for f in sub]
    w = estadistica.wilcoxon(d, alternativa)
    ic = estadistica.bootstrap_ic(d, remuestreos=cfg.remuestreos)
    return {"prueba": nombre, "N": w.n, "empates": w.empates, "media_d": statistics.fmean(d),
            "mediana_d": statistics.median(d), "IC95_bajo": ic[0], "IC95_alto": ic[1],
            "W+": w.w_mas, "z": w.z, "p": w.p, "r": w.r, "efecto": w.efecto, "alternativa": alternativa}


def _familia(pruebas: list[dict]) -> list[dict]:
    ajust = estadistica.holm([p["p"] for p in pruebas])
    for p, a in zip(pruebas, ajust):
        p["p_holm"] = a
        p["decision"] = "se rechaza H0" if a < 0.05 else "no se rechaza H0"
    return pruebas


def analizar(res: dict, cfg: Configuracion) -> dict:
    """Pruebas de hipótesis (Tabla 7.6) sobre los resultados de ``ejecutar``."""
    a: dict[str, Any] = {}
    if "E1-Ruta" in res:
        f = res["E1-Ruta"]
        a["H1"] = _familia([_prueba(f"E1-Ruta n={n}: d = VMC - HK (km)", f, lambda x, n=n: x["n"] == n,
                                    lambda x: x["dist_vmc_km"] - x["dist_hk_km"], "mayor", cfg)
                            for n in (6, 8, 10, 12)])
        a["E1-Ruta_bt_coincide"] = all(x["bt_coincide_hk"] in (True, "") for x in f)
    if "E1-Carga" in res:
        f = res["E1-Carga"]
        a["H2"] = _familia([_prueba(f"E1-Carga n={n} W={w}: d = PD - voraz (S/)", f,
                                    lambda x, n=n, w=w: x["n"] == n and x["W"] == w,
                                    lambda x: x["valor_pd"] - x["valor_voraz"], "mayor", cfg)
                            for n in (15, 25, 40) for w in (25, 30)])
    if "E2" in res:
        f = res["E2"]
        a["H3"] = _familia([_prueba(f"E2 bloqueos={k}: d = nodos sin poda - nodos RyP", f,
                                    lambda x, k=k: x["nivel_bloqueo"] == k,
                                    lambda x: x["nodos_sin_poda"] - x["nodos_ryp"], "mayor", cfg)
                            for k in (0, 2, 4)])
        a["H3_coincide_dijkstra_pct"] = 100 * sum(1 for x in f if x["coincide_dijkstra"]) / len(f) if f else 0
    if "E3a" in res:
        f = res["E3a"]
        a["H4a"] = _familia([_prueba(f"E3a m={m}: d = t HK - t DyV (ms)", f, lambda x, m=m: x["m"] == m,
                                     lambda x: x["t_hk_ms"] - x["t_dyv_ms"], "mayor", cfg) for m in (4, 6)])
        a["E3a_distancia"] = _familia([_prueba(f"E3a m={m}: d = dist DyV - dist HK (km)", f,
                                               lambda x, m=m: x["m"] == m,
                                               lambda x: x["dist_dyv_km"] - x["dist_hk_km"], "distinta", cfg)
                                       for m in (4, 6)])
    if "E3b" in res:
        f = res["E3b"]
        a["H4b"] = _familia([_prueba(f"E3b n={n} m={m}: d = VMC - DyV (km)", f,
                                     lambda x, n=n, m=m: x["n"] == n and x["m"] == m,
                                     lambda x: x["dist_vmc_km"] - x["dist_dyv_km"], "distinta", cfg)
                             for n in (24, 36) for m in (4, 6)])
    if "E4" in res:
        f = res["E4"]
        a["General"] = _familia([_prueba("E4: d = valor integrado - valor voraz (S/)", f, lambda x: True,
                                         lambda x: x["valor_integrado"] - x["valor_voraz"], "mayor", cfg)])
        tiempos = [x["t_integrado_ms"] for x in f]
        if tiempos:
            a["General_tiempo"] = {"mediana_ms": statistics.median(tiempos), "max_ms": max(tiempos),
                                   "cumple_nielsen": statistics.median(tiempos) <= 1000 and max(tiempos) <= 10000}
    return a


# --------------------------------------------------------------------------- informe
def _equipo() -> dict:
    return {"fecha": datetime.now().isoformat(timespec="seconds"), "python": sys.version.split()[0],
            "sistema": platform.platform(), "procesador": platform.processor() or platform.machine(),
            "nucleos": os.cpu_count()}


def _resumen_md(res: dict, analisis: dict, cfg: Configuracion, extra: dict) -> str:
    L = ["# Resultados de los experimentos E1 a E4", "",
         f"- Fecha: {extra['equipo']['fecha']}",
         f"- Equipo: {extra['equipo']['procesador']} ({extra['equipo']['nucleos']} núcleos), "
         f"{extra['equipo']['sistema']}, Python {extra['equipo']['python']}",
         f"- Semillas por configuración: 1 a {cfg.semillas}; repeticiones medidas: {cfg.repeticiones} "
         f"(+1 de calentamiento); tope de métodos exponenciales: {cfg.tiempo_max_s:g} s",
         f"- Red: {extra['red']}", f"- Duración total: {extra['duracion_s']:.1f} s", ""]

    def tabla(pruebas):
        L.append("| Prueba | N | Empates | Media d | IC 95 % | z | p | p Holm | r | Decisión |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for p in pruebas:
            L.append(f"| {p['prueba']} | {p['N']} | {p['empates']} | {p['media_d']:.4g} | "
                     f"[{p['IC95_bajo']:.4g}; {p['IC95_alto']:.4g}] | {p['z']:.3f} | {p['p']:.4g} | "
                     f"{p['p_holm']:.4g} | {p['r']:.2f} ({p['efecto']}) | {p['decision']} |")
        L.append("")

    if "E1-Ruta" in res:
        f = res["E1-Ruta"]
        L += ["## E1-Ruta: vecino más cercano frente a Held-Karp (H1)", ""]
        for n in (6, 8, 10, 12):
            s = [x for x in f if x["n"] == n]
            if s:
                L.append(f"- n = {n}: brecha media {statistics.fmean(x['brecha_pct'] for x in s):.2f} %, "
                         f"máxima {max(x['brecha_pct'] for x in s):.2f} %, tiempo mediano VMC "
                         f"{statistics.median(x['t_vmc_ms'] for x in s):.3f} ms y HK "
                         f"{statistics.median(x['t_hk_ms'] for x in s):.3f} ms.")
        L.append(f"- Backtracking coincide con Held-Karp en todas las instancias completas: "
                 f"{'sí' if analisis.get('E1-Ruta_bt_coincide') else 'NO'}.")
        L.append("")
        tabla(analisis["H1"])
    if "E1-Carga" in res:
        f = res["E1-Carga"]
        L += ["## E1-Carga: mochila voraz frente a mochila 0/1 (H2)", ""]
        for n in (15, 25, 40):
            for w in (25, 30):
                s = [x for x in f if x["n"] == n and x["W"] == w]
                if s:
                    L.append(f"- n = {n}, W = {w} kg: la voraz logra en promedio "
                             f"{statistics.fmean(x['pct_optimo'] for x in s):.2f} % del óptimo.")
        L.append("")
        tabla(analisis["H2"])
    if "E2" in res:
        f = res["E2"]
        L += ["## E2: backtracking con calles bloqueadas (H3)", ""]
        for k in (0, 2, 4):
            s = [x for x in f if x["nivel_bloqueo"] == k]
            if s:
                L.append(f"- {k} bloqueos: nodos sin poda (mediana) {statistics.median(x['nodos_sin_poda'] for x in s):.0f}, "
                         f"con cota {statistics.median(x['nodos_cota'] for x in s):.0f}, con RyP "
                         f"{statistics.median(x['nodos_ryp'] for x in s):.0f}; reducción media "
                         f"{statistics.fmean(x['reduccion_pct'] for x in s):.1f} %.")
        L.append(f"- RyP coincide con Dijkstra en el {analisis.get('H3_coincide_dijkstra_pct', 0):.0f} % "
                 f"de las instancias. Instancias reemplazadas por destino aislado: {len(extra.get('E2_reemplazadas', []))}.")
        L.append("")
        tabla(analisis["H3"])
    if "E3a" in res:
        f = res["E3a"]
        L += ["## E3a: Held-Karp único frente a divide y vencerás (H4, tiempo)", ""]
        for m in (4, 6):
            s = [x for x in f if x["m"] == m]
            if s:
                L.append(f"- m = {m}: aceleración mediana {statistics.median(x['aceleracion'] for x in s):.1f}×, "
                         f"exceso de distancia medio {statistics.fmean(x['exceso_pct'] for x in s):.2f} %.")
        L.append("")
        tabla(analisis["H4a"])
        L.append("Distancia (bilateral, descriptiva):")
        L.append("")
        tabla(analisis["E3a_distancia"])
    if "E3b" in res:
        f = res["E3b"]
        L += ["## E3b: vecino más cercano frente a divide y vencerás con muchos pedidos (H4, distancia)", ""]
        for n in (24, 36):
            for m in (4, 6):
                s = [x for x in f if x["n"] == n and x["m"] == m]
                if s:
                    L.append(f"- n = {n}, m = {m}: DyV es en promedio "
                             f"{statistics.fmean(x['diferencia_pct'] for x in s):.2f} % más corto que VMC.")
        L.append("")
        tabla(analisis["H4b"])
    if "E4" in res:
        f = res["E4"]
        L += ["## E4: flujo voraz frente a flujo integrado (hipótesis general)", ""]
        L.append(f"- Valor entregado medio: voraz S/ {statistics.fmean(x['valor_voraz'] for x in f):.1f}, "
                 f"integrado S/ {statistics.fmean(x['valor_integrado'] for x in f):.1f}.")
        L.append(f"- Pedidos atendidos medios: voraz {statistics.fmean(x['atendidos_voraz'] for x in f):.1f}, "
                 f"integrado {statistics.fmean(x['atendidos_integrado'] for x in f):.1f}.")
        L.append(f"- km por pedido: voraz {statistics.fmean(x['km_por_pedido_voraz'] for x in f):.3f}, "
                 f"integrado {statistics.fmean(x['km_por_pedido_integrado'] for x in f):.3f}.")
        t = analisis.get("General_tiempo", {})
        if t:
            L.append(f"- Tiempo del flujo integrado: mediana {t['mediana_ms']:.1f} ms, máximo {t['max_ms']:.1f} ms "
                     f"→ {'cumple' if t['cumple_nielsen'] else 'NO cumple'} el criterio de Nielsen (≤ 1 s y ≤ 10 s).")
        L.append("")
        tabla(analisis["General"])
    L.append("Archivos CSV con todas las instancias en esta misma carpeta. Semillas registradas en cada fila.")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- ejecución
FUNCIONES = {"E1-Ruta": e1_ruta, "E1-Carga": e1_carga, "E2": e2, "E3a": e3a, "E3b": e3b, "E4": e4}
PESO = {"E1-Ruta": 4, "E1-Carga": 6, "E2": 3, "E3a": 2, "E3b": 4, "E4": 1}


def ejecutar(cfg: Configuracion, carpeta: str | os.PathLike | None = None) -> dict:
    """Corre los experimentos de ``cfg.solo``. Si se da 'carpeta' guarda los CSV, el
    resumen (Markdown) y el análisis (JSON). Devuelve {"resultados", "analisis", "archivos"}."""
    inicio = time.perf_counter()
    elegidos = [e for e in EXPERIMENTOS if e in cfg.solo]
    total = sum(PESO[e] * cfg.semillas for e in elegidos) or 1
    hechos = [0]

    def avance(texto: str) -> None:
        hechos[0] += 1
        if cfg.progreso:
            cfg.progreso(min(0.99, hechos[0] / total), texto)

    resultados: dict[str, list[dict]] = {}
    extra: dict[str, Any] = {"equipo": _equipo()}
    for e in elegidos:
        salida = FUNCIONES[e](cfg, avance)
        if e == "E2":
            resultados[e], extra["E2_reemplazadas"] = salida
        else:
            resultados[e] = salida
    analisis = analizar(resultados, cfg)
    red = cfg.red if cfg.red is not None else datos.crear_red()
    extra["red"] = (f"{len(red.nodos)} nodos, {len(red.calles())} calles; trazado "
                    f"{'real (OpenStreetMap)' if red.tiene_trazado_real() else 'recto (distancia geodésica × sinuosidad)'}")
    extra["duracion_s"] = time.perf_counter() - inicio
    archivos = []
    if carpeta is not None:
        d = Path(carpeta)
        d.mkdir(parents=True, exist_ok=True)
        for e, filas in resultados.items():
            ruta = d / f"{e.replace('-', '_')}.csv"
            _escribir_csv(ruta, filas)
            archivos.append(ruta)
        if extra.get("E2_reemplazadas"):
            ruta = d / "E2_reemplazadas.csv"
            _escribir_csv(ruta, extra["E2_reemplazadas"])
            archivos.append(ruta)
        ruta = d / "resumen.md"
        ruta.write_text(_resumen_md(resultados, analisis, cfg, extra), encoding="utf-8")
        archivos.append(ruta)
        ruta = d / "analisis.json"
        ruta.write_text(json.dumps({"analisis": analisis, "equipo": extra["equipo"], "red": extra["red"],
                                    "semillas": cfg.semillas, "repeticiones": cfg.repeticiones},
                                   ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        archivos.append(ruta)
    if cfg.progreso:
        cfg.progreso(1.0, "Experimentos terminados.")
    return {"resultados": resultados, "analisis": analisis, "archivos": archivos, "extra": extra}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - interfaz de terminal
    import argparse
    p = argparse.ArgumentParser(description="Experimentos E1-E4 del plan de tesis (CSV + Wilcoxon).")
    p.add_argument("--salida", default="resultados_experimentos", help="carpeta de salida")
    p.add_argument("--semillas", type=int, default=30, help="instancias por configuración (semillas 1..N)")
    p.add_argument("--rapido", action="store_true", help="1 repetición y 2 000 remuestreos (para probar)")
    p.add_argument("--solo", nargs="*", choices=EXPERIMENTOS, help="experimentos a correr")
    p.add_argument("--calles-reales", action="store_true", help="usar el trazado y largo reales de OSM (caché)")
    args = p.parse_args(argv)
    red = None
    if args.calles_reales:
        from . import calles_reales
        red = datos.crear_red()
        cache = calles_reales.cargar_cache()
        if cache is None:
            print("No hay caché de calles reales: ejecuta antes  python -m src.calles_reales")
            return 1
        calles_reales.aplicar(red, cache)
    cfg = Configuracion(semillas=args.semillas, repeticiones=1 if args.rapido else 5,
                        solo=tuple(args.solo) if args.solo else EXPERIMENTOS, red=red,
                        remuestreos=2000 if args.rapido else 10_000,
                        progreso=lambda f, t: print(f"\r[{f * 100:5.1f} %] {t:<60}", end="", flush=True))
    r = ejecutar(cfg, args.salida)
    print()
    for a in r["archivos"]:
        print("escrito:", a)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
