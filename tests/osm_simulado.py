"""Datos de OpenStreetMap SIMULADOS para probar sin internet.

Genera una respuesta con el mismo formato que la API Overpass: una cuadrícula de calles
(girada) que cubre la caja pedida. NO son las calles reales de Cusco: solo sirven para
comprobar que la descarga, el trazado y el dibujo funcionan.
"""

import math


def osm_cuadricula(caja, paso_m=90.0, angulo=20.0):
    s, o, n, e = caja
    lat0, lon0 = (s + n) / 2, (o + e) / 2
    m_lat = 111_195.0
    m_lon = m_lat * math.cos(math.radians(lat0))
    radio = math.hypot((n - s) * m_lat, (e - o) * m_lon) / 2 + paso_m
    k = int(radio // paso_m)
    a = math.radians(angulo)

    def latlon(u, v):
        x = u * math.cos(a) - v * math.sin(a)
        y = u * math.sin(a) + v * math.cos(a)
        return lat0 + y / m_lat, lon0 + x / m_lon

    elementos, ids = [], {}

    def nodo(i, j):
        if (i, j) not in ids:
            ids[(i, j)] = len(ids) + 1
            lat, lon = latlon(i * paso_m, j * paso_m)
            elementos.append({"type": "node", "id": ids[(i, j)], "lat": lat, "lon": lon})
        return ids[(i, j)]

    via = 10 ** 6
    for i in range(-k, k + 1):
        elementos.append({"type": "way", "id": via, "nodes": [nodo(i, j) for j in range(-k, k + 1)],
                          "tags": {"highway": "residential" if i % 4 else "primary"}})
        elementos.append({"type": "way", "id": via + 1, "nodes": [nodo(j, i) for j in range(-k, k + 1)],
                          "tags": {"highway": "residential" if i % 5 else "secondary"}})
        via += 2
    # una escalera en diagonal: NO debe usarse (no es vía para vehículos)
    elementos.append({"type": "way", "id": via, "nodes": [nodo(0, 0), nodo(1, 1)],
                      "tags": {"highway": "steps"}})
    return {"elements": elementos}
