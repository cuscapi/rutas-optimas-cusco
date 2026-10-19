"""Estadística para los experimentos (sin dependencias: solo la biblioteca estándar).

* ``wilcoxon``: prueba de rangos con signo de Wilcoxon para datos pareados, con el
  tratamiento de empates de Pratt (1959) y aproximación normal (adecuada con N = 30).
* ``holm``: ajuste de Holm (1979) para varias pruebas de una misma hipótesis.
* ``bootstrap_ic``: intervalo de confianza por bootstrap de percentiles.

Los resultados coinciden con ``scipy.stats.wilcoxon(..., zero_method="pratt",
correction=False, method="approx")`` (se verifica en las pruebas si SciPy está instalado).
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Sequence


@dataclass
class ResultadoWilcoxon:
    n: int                # pares
    empates: int          # pares con diferencia 0
    w_mas: float          # suma de rangos de las diferencias positivas
    z: float
    p: float
    r: float              # tamaño del efecto r = z / sqrt(N)
    alternativa: str      # "mayor", "menor" o "distinta"

    @property
    def efecto(self) -> str:
        a = abs(self.r)
        return "grande" if a >= 0.5 else "mediano" if a >= 0.3 else "pequeño" if a >= 0.1 else "nulo"


def _rangos(valores: Sequence[float]) -> list[float]:
    """Rangos 1..n con promedio en los empates."""
    orden = sorted(range(len(valores)), key=lambda i: valores[i])
    rangos = [0.0] * len(valores)
    i = 0
    while i < len(orden):
        j = i
        while j + 1 < len(orden) and valores[orden[j + 1]] == valores[orden[i]]:
            j += 1
        promedio = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rangos[orden[k]] = promedio
        i = j + 1
    return rangos


def _normal_sf(z: float) -> float:
    """P(Z > z) de la normal estándar."""
    return 0.5 * math.erfc(z / math.sqrt(2))


def wilcoxon(diferencias: Sequence[float], alternativa: str = "mayor",
             tolerancia: float = 1e-12) -> ResultadoWilcoxon:
    """Wilcoxon de rangos con signo sobre d_i = línea base - método (o lo que se indique).

    'alternativa': "mayor" (H_a: mediana > 0), "menor" o "distinta" (bilateral).
    Diferencias con |d| <= tolerancia cuentan como empates (método de Pratt: entran en el
    ranking y luego se quitan de las sumas y de la media/varianza).
    """
    if alternativa not in ("mayor", "menor", "distinta"):
        raise ValueError("alternativa debe ser 'mayor', 'menor' o 'distinta'")
    d = [0.0 if abs(x) <= tolerancia else float(x) for x in diferencias]
    n = len(d)
    if n == 0:
        raise ValueError("No hay diferencias")
    rangos = _rangos([abs(x) for x in d])
    ceros = sum(1 for x in d if x == 0)
    w_mas = sum(r for r, x in zip(rangos, d) if x > 0)
    media = n * (n + 1) / 4 - ceros * (ceros + 1) / 4
    var = n * (n + 1) * (2 * n + 1) - ceros * (ceros + 1) * (2 * ceros + 1)
    # corrección por rangos repetidos (sin contar los ceros)
    conteo: dict[float, int] = {}
    for r, x in zip(rangos, d):
        if x != 0:
            conteo[r] = conteo.get(r, 0) + 1
    var -= 0.5 * sum(t * (t * t - 1) for t in conteo.values())
    var /= 24
    if var <= 0:
        return ResultadoWilcoxon(n, ceros, w_mas, 0.0, 1.0, 0.0, alternativa)
    z = (w_mas - media) / math.sqrt(var)
    if alternativa == "mayor":
        p = _normal_sf(z)
    elif alternativa == "menor":
        p = _normal_sf(-z)
    else:
        p = min(1.0, 2 * _normal_sf(abs(z)))
    return ResultadoWilcoxon(n, ceros, w_mas, z, p, z / math.sqrt(n), alternativa)


def holm(valores_p: Sequence[float]) -> list[float]:
    """Valores p ajustados por Holm (mismo orden que la entrada)."""
    m = len(valores_p)
    orden = sorted(range(m), key=lambda i: valores_p[i])
    ajustados = [0.0] * m
    maximo = 0.0
    for k, i in enumerate(orden):
        maximo = max(maximo, min(1.0, (m - k) * valores_p[i]))
        ajustados[i] = maximo
    return ajustados


def bootstrap_ic(valores: Sequence[float], estadistico=statistics.fmean, nivel: float = 0.95,
                 remuestreos: int = 10_000, semilla: int = 12345) -> tuple[float, float]:
    """IC por bootstrap de percentiles (Efron y Tibshirani, 1993)."""
    datos = list(valores)
    if not datos:
        return (math.nan, math.nan)
    azar = random.Random(semilla)
    n = len(datos)
    estimaciones = sorted(estadistico([datos[azar.randrange(n)] for _ in range(n)])
                          for _ in range(remuestreos))
    alfa = (1 - nivel) / 2
    bajo = estimaciones[int(math.floor(alfa * (remuestreos - 1)))]
    alto = estimaciones[int(math.ceil((1 - alfa) * (remuestreos - 1)))]
    return bajo, alto


def describir(valores: Sequence[float]) -> dict:
    datos = [v for v in valores if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not datos:
        return {"n": 0}
    return {"n": len(datos), "media": statistics.fmean(datos), "mediana": statistics.median(datos),
            "min": min(datos), "max": max(datos),
            "de": statistics.stdev(datos) if len(datos) > 1 else 0.0}
