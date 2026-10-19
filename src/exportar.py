"""Horas de llegada y exportación de rutas (GPX, CSV y enlaces de Google Maps).

* ``llegadas``: minuto estimado de llegada a cada parada (velocidad del repartidor más un
  tiempo de entrega por parada) y si cae dentro de la ventana del pedido.
* ``a_gpx``: archivo GPX 1.1 (abre en Google Earth, OsmAnd, Maps.me, GPS...). Lleva el
  recorrido por calles (track) y las paradas numeradas (waypoints).
* ``a_csv``: tabla para Excel con el orden de visita, distancias acumuladas y llegadas.
* ``urls_google_maps``: enlaces de Google Maps con las paradas en orden (máx. 25 puntos
  por enlace; si hay más se parte en varios).

Sin dependencias externas.
"""

from __future__ import annotations

import csv
import math
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from xml.sax.saxutils import escape

VELOCIDAD_KMH = 25.0      # si el punto de inicio no tiene velocidad propia
SERVICIO_MIN = 2.0        # minutos para entregar en cada parada
MAX_PUNTOS_GOOGLE = 25    # origen + 23 paradas intermedias + destino


@dataclass
class Llegada:
    pedido: Any
    metros_acumulados: float
    minuto: float               # minuto de llegada desde la salida (minuto 0 de la jornada)

    @property
    def a_tiempo(self) -> bool:
        return self.minuto <= getattr(self.pedido, "ventana_fin", math.inf)

    @property
    def espera(self) -> float:
        """Minutos que habría que esperar si se llega antes de que abra la ventana."""
        return max(0.0, getattr(self.pedido, "ventana_inicio", 0) - self.minuto)


@dataclass
class RutaExportable:
    nombre: str
    color: str
    inicio: Any                       # repartidor (o None para rutas entre nodos)
    orden: list                       # pedidos en orden de visita
    coords: list                      # [(lat, lon), ...] del recorrido por calles
    llegadas: list = field(default_factory=list)


def VELOCIDAD_TEXTO(inicio: Any) -> str:  # noqa: N802 - se usa como constante en la GUI
    return f"{getattr(inicio, 'velocidad_kmh', VELOCIDAD_KMH):g} km/h"


def llegadas(inicio: Any, orden: Iterable[Any], dist: Callable[[Any, Any], float],
             velocidad_kmh: float = VELOCIDAD_KMH, servicio_min: float = SERVICIO_MIN) -> list[Llegada]:
    """Minuto de llegada a cada pedido saliendo de 'inicio' en el minuto 0.

    Si se llega antes de que abra la ventana de un pedido, se espera hasta su inicio.
    Las distancias infinitas (pedido aislado) dan llegada infinita (fuera de plazo)."""
    metros_por_min = velocidad_kmh * 1000 / 60
    salida, minuto, acumulado, previo = [], 0.0, 0.0, inicio
    for p in orden:
        d = dist(previo, p)
        acumulado += d
        minuto += d / metros_por_min
        llegada = Llegada(p, acumulado, minuto)
        salida.append(llegada)
        minuto = max(minuto, getattr(p, "ventana_inicio", 0)) + servicio_min
        previo = p
    return salida


# --------------------------------------------------------------------------- GPX
def a_gpx(rutas: Iterable[RutaExportable], ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<gpx version="1.1" creator="Sistema de Gestión de Rutas Óptimas en Cusco" '
         'xmlns="http://www.topografix.com/GPX/1/1">',
         f'  <metadata><name>Rutas de reparto - Cusco</name><time>{ahora}</time></metadata>']
    rutas = list(rutas)
    for r in rutas:
        for i, ll in enumerate(r.llegadas, 1):
            p = ll.pedido
            desc = (f"{r.nombre}: parada {i}; urgencia {getattr(p, 'urgencia', '')}; "
                    f"{getattr(p, 'peso', '')} kg; S/ {getattr(p, 'valor', '')}; "
                    f"llegada {ll.minuto:.0f} min")
            L.append(f'  <wpt lat="{p.lat:.7f}" lon="{p.lon:.7f}"><name>{escape(f"{i}. {p.id}")}</name>'
                     f'<desc>{escape(desc)}</desc></wpt>')
    for r in rutas:
        if len(r.coords) < 2:
            continue
        L.append(f"  <trk><name>{escape(r.nombre)}</name><trkseg>")
        L.extend(f'    <trkpt lat="{lat:.7f}" lon="{lon:.7f}"/>' for lat, lon in r.coords)
        L.append("  </trkseg></trk>")
    L.append("</gpx>")
    ruta.write_text("\n".join(L) + "\n", encoding="utf-8")
    return ruta


# --------------------------------------------------------------------------- CSV
def a_csv(rutas: Iterable[RutaExportable], ruta: str | Path) -> Path:
    ruta = Path(ruta)
    with ruta.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ruta", "parada", "pedido", "cliente", "urgencia", "peso_kg", "valor_S/", "lat", "lon",
                    "km_acumulados", "llegada_min", "ventana_inicio", "ventana_fin", "a_tiempo"])
        for r in rutas:
            for i, ll in enumerate(r.llegadas, 1):
                p = ll.pedido
                w.writerow([r.nombre, i, p.id, getattr(p, "cliente", ""), getattr(p, "urgencia", ""),
                            getattr(p, "peso", ""), getattr(p, "valor", ""), f"{p.lat:.7f}", f"{p.lon:.7f}",
                            f"{ll.metros_acumulados / 1000:.3f}", f"{ll.minuto:.1f}",
                            getattr(p, "ventana_inicio", ""), getattr(p, "ventana_fin", ""),
                            "sí" if ll.a_tiempo else "no"])
    return ruta


# --------------------------------------------------------------------------- Google Maps
def _par(lat: float, lon: float) -> str:
    return f"{lat:.6f},{lon:.6f}"


def urls_google_maps(r: RutaExportable, modo: str = "driving") -> list[str]:
    """Enlaces https://www.google.com/maps/dir/?api=1 con las paradas en orden.

    Google calcula su propia ruta entre paradas (puede diferir un poco de la del sistema).
    Para rutas sin paradas (backtracking) se usan el inicio y el final del recorrido."""
    if r.orden:
        puntos = []
        if r.inicio is not None:
            puntos.append((r.inicio.lat, r.inicio.lon))
        puntos += [(p.lat, p.lon) for p in r.orden]
    else:
        puntos = [r.coords[0], r.coords[-1]] if len(r.coords) >= 2 else list(r.coords)
    if len(puntos) < 2:
        return []
    urls = []
    i = 0
    while i < len(puntos) - 1:
        trozo = puntos[i:i + MAX_PUNTOS_GOOGLE]
        parametros = {"api": "1", "origin": _par(*trozo[0]), "destination": _par(*trozo[-1]),
                      "travelmode": modo}
        if len(trozo) > 2:
            parametros["waypoints"] = "|".join(_par(*q) for q in trozo[1:-1])
        urls.append("https://www.google.com/maps/dir/?" + urllib.parse.urlencode(parametros, safe=",|"))
        i += MAX_PUNTOS_GOOGLE - 1
    return urls
