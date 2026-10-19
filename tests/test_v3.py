"""Pruebas de la versión 3: calles reales (trazado), correcciones, exportación,
estadística y experimentos E1-E4.

Ejecutar con: python -m unittest discover -s tests -v
"""

import csv
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from osm_simulado import osm_cuadricula  # noqa: E402

from src import (calles_reales, datos, estadistica, experimentos, exportar,  # noqa: E402
                 programacion_dinamica, traductor, voraz)
from src.modelos import VELOCIDAD_KMH_POR_TIPO, Calle  # noqa: E402
from src.red import RedCusco, RedVial, _Polilinea  # noqa: E402


def escenario_con_trazado(cantidad=18, semilla=7):
    esc = datos.Escenario.sintetico(cantidad, semilla)
    cache = calles_reales.trazar_red(esc.red, osm_cuadricula(calles_reales.caja_de_red(esc.red)))
    calles_reales.aplicar(esc.red, cache)
    esc.reubicar()
    return esc, cache


def largo_xy_m(puntos):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(puntos, puntos[1:])) * traductor.UNIDAD_M


class PruebasPolilinea(unittest.TestCase):
    def setUp(self):
        self.p = _Polilinea([(0, 0), (3, 0), (3, 4)])   # largo 7

    def test_punto_por_fraccion_del_largo(self):
        self.assertEqual(self.p.punto(0), (0, 0))
        self.assertEqual(self.p.punto(1), (3, 4))
        x, y = self.p.punto(3 / 7)
        self.assertAlmostEqual(x, 3)
        self.assertAlmostEqual(y, 0)
        x, y = self.p.punto(5 / 7)
        self.assertAlmostEqual((x, y), (3, 2))

    def test_tramo_en_ambos_sentidos(self):
        ida = self.p.tramo(0.2, 0.8)
        vuelta = self.p.tramo(0.8, 0.2)
        self.assertEqual(ida, vuelta[::-1])
        self.assertIn((3, 0), ida)                       # pasa por la esquina
        self.assertAlmostEqual(largo_xy_m(ida) / 100, 0.6 * 7)

    def test_proyeccion(self):
        d, t, (px, py) = self.p.proyectar(4, 1)
        self.assertAlmostEqual(d, 1)
        self.assertAlmostEqual((px, py), (3, 1))
        self.assertAlmostEqual(t, 4 / 7)


class PruebasTrazadoEnLaRed(unittest.TestCase):
    def test_sin_trazado_todo_sigue_igual_que_antes(self):
        red = datos.crear_red()
        self.assertFalse(red.tiene_trazado_real())
        a, b = red.nodos["San Blas"], red.nodos["Plaza de Armas"]
        x, y = red.punto_en_calle("San Blas", "Plaza de Armas", 0.25)
        self.assertAlmostEqual(x, a.x + 0.25 * (b.x - a.x))
        self.assertAlmostEqual(y, a.y + 0.25 * (b.y - a.y))
        self.assertEqual(red.trazado_latlon("San Blas", "Plaza de Armas"),
                         [traductor.xy_a_latlon(a.x, a.y), traductor.xy_a_latlon(b.x, b.y)])

    def test_establecer_geometria_respeta_el_sentido(self):
        red = datos.crear_red()
        a, b = red.nodos["San Blas"], red.nodos["Plaza de Armas"]
        codo = (a.lat, b.lon)
        red.establecer_geometria("Plaza de Armas", "San Blas", [(b.lat, b.lon), codo, (a.lat, a.lon)])
        c = red.calle("San Blas", "Plaza de Armas")
        self.assertEqual(c.geometria[0], (a.lat, a.lon))     # guardada desde c.origen
        self.assertEqual(len(red.trazado_xy("San Blas", "Plaza de Armas")), 3)
        lat, lon = traductor.xy_a_latlon(*red.punto_en_calle("Plaza de Armas", "San Blas", 0.0))
        self.assertAlmostEqual(lat, b.lat)

    def test_clic_sobre_el_trazado_encuentra_la_calle(self):
        esc, _ = escenario_con_trazado()
        for c in esc.red.calles()[:10]:
            x, y = esc.red.punto_en_calle(c.origen, c.destino, 0.5)
            calle, d, t, px, py = esc.red.calle_mas_cercana(x + 0.001, y)
            self.assertLess(d, 0.05)
            self.assertTrue(0.05 <= t <= 0.95)

    def test_geometria_invalida_da_error(self):
        with self.assertRaises(ValueError):
            Calle("A", "B", 100.0, geometria=[(0, 0)])
        with self.assertRaises(ValueError):
            Calle("A", "B", 100.0, geometria=[(0, 0), (200, 0)])

    def test_serializacion_json_y_csv_con_trazado(self):
        esc, _ = escenario_con_trazado()
        d = esc.red.to_dict()
        self.assertTrue(all("geometria" in c for c in d["calles"]))
        copia = RedCusco.from_dict(json.loads(json.dumps(d)))
        self.assertTrue(copia.tiene_trazado_real())
        self.assertEqual(copia.trazado_xy("San Blas", "Santa Ana"), esc.red.trazado_xy("San Blas", "Santa Ana"))
        with tempfile.TemporaryDirectory() as tmp:
            archivos = datos.guardar_red(esc.red, Path(tmp) / "r.csv")      # CSV: sin geometría
            leida = datos.cargar_red(archivos[0])
            self.assertFalse(leida.tiene_trazado_real())
            self.assertEqual(len(leida.calles()), 29)


class PruebasRedVialConTrazado(unittest.TestCase):
    def test_lo_dibujado_mide_lo_mismo_que_la_distancia(self):
        esc, _ = escenario_con_trazado()
        rv = esc.crear_red_vial()
        rep = esc.repartidores[0]
        for p in esc.pedidos:
            puntos = rv.camino(rep, p)
            self.assertAlmostEqual(largo_xy_m(puntos), rv.distancia(rep, p), delta=1.0)

    def test_ruta_sigue_varias_esquinas(self):
        esc, _ = escenario_con_trazado()
        rv = esc.crear_red_vial()
        rep = esc.repartidores[0]
        orden, total = voraz.ruta_vecino_mas_cercano(rep, esc.pedidos[:6], rv.distancia)
        puntos = rv.ruta(rep, orden)
        self.assertGreater(len(puntos), 2 * len(orden))
        self.assertAlmostEqual(largo_xy_m(puntos), total, delta=2.0)

    def test_sin_camino_devuelve_lista_vacia_y_no_una_recta(self):
        esc = datos.Escenario.sintetico(18, 7)
        destino = "San Sebastián"
        for v, _, _ in esc.red.vecinos_todos(destino):
            esc.red.bloquear_calle(destino, v)
        p = datos.generar_pedidos(1, 3, esc.red)[0]
        p.calle, p.t = ("Wanchaq", "San Sebastián"), 0.9
        p.x, p.y = esc.red.punto_en_calle("Wanchaq", "San Sebastián", 0.9)
        esc.pedidos = [p]
        rv = esc.crear_red_vial()
        rep = esc.repartidores[0]
        self.assertTrue(math.isinf(rv.distancia(rep, p)))
        self.assertEqual(rv.camino(rep, p), [])
        self.assertEqual(rv.ruta(rep, [p]), [])

    def test_distancias_identicas_sin_trazado(self):
        # sin trazado real, la v3 da exactamente las mismas distancias que antes
        esc = datos.Escenario.sintetico(12, 112)
        rv = esc.crear_red_vial()
        _, hk = programacion_dinamica.ruta_optima_held_karp(esc.repartidores[0], esc.pedidos, rv.distancia)
        esc2 = datos.Escenario.sintetico(12, 112)
        rv2 = RedVial(red=esc2.red)
        rv2.preparar(esc2.puntos())
        _, hk2 = programacion_dinamica.ruta_optima_held_karp(esc2.repartidores[0], esc2.pedidos, rv2.distancia)
        self.assertAlmostEqual(hk, hk2)


class PruebasCallesReales(unittest.TestCase):
    def setUp(self):
        self.red = datos.crear_red()
        self.osm = osm_cuadricula(calles_reales.caja_de_red(self.red))

    def test_grafo_excluye_escaleras_y_conecta(self):
        g = calles_reales.construir_grafo(self.osm)
        self.assertGreater(len(g.coords), 1000)
        comp = g.componente_mayor()
        self.assertEqual(len(comp), len(g.ady))
        pequeno = {"elements": [
            {"type": "node", "id": 1, "lat": -13.5, "lon": -71.9},
            {"type": "node", "id": 2, "lat": -13.5, "lon": -71.899},
            {"type": "node", "id": 3, "lat": -13.501, "lon": -71.899},
            {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
            {"type": "way", "id": 11, "nodes": [2, 3], "tags": {"highway": "steps"}},
            {"type": "way", "id": 12, "nodes": [1, 3], "tags": {"highway": "footway"}}]}
        g = calles_reales.construir_grafo(pequeno)
        self.assertEqual(set(g.ady), {1, 2})            # escaleras y veredas no son vías
        self.assertAlmostEqual(g.ady[1][2][0], traductor.haversine_m(-13.5, -71.9, -13.5, -71.899))

    def test_a_estrella_igual_a_dijkstra_en_cuadricula(self):
        g = calles_reales.construir_grafo(self.osm)
        ids = list(g.ady)
        a, b = ids[10], ids[-10]
        camino, largo = g.camino_mas_corto(a, b)
        self.assertEqual(camino[0], a)
        self.assertEqual(camino[-1], b)
        recta = traductor.haversine_m(*g.coords[a], *g.coords[b])
        self.assertGreaterEqual(largo, recta - 1e-6)

    def test_trazar_y_aplicar(self):
        cache = calles_reales.trazar_red(self.red, self.osm)
        self.assertEqual(sum(1 for c in cache["calles"] if c["estado"] == "ok"), 29)
        resumen = calles_reales.aplicar(self.red, cache)
        self.assertEqual(resumen["calles_reales"], 29)
        self.assertEqual(resumen["nodos_movidos"], 16)
        for c in self.red.calles():
            self.assertTrue(c.geometria)
            recta = traductor.haversine_m(*c.geometria[0], *c.geometria[-1])
            self.assertGreaterEqual(c.distancia_m, recta - 1)        # una calle real no es más corta que la recta
            self.assertAlmostEqual(c.tiempo_s, c.distancia_m / (VELOCIDAD_KMH_POR_TIPO[c.tipo] / 3.6))

    def test_volver_al_largo_sintetico(self):
        cache = calles_reales.trazar_red(self.red, self.osm)
        original = {c.clave: c.distancia_m for c in self.red.calles()}
        calles_reales.aplicar(self.red, cache, usar_largo_real=True)
        self.assertNotEqual(original, {c.clave: c.distancia_m for c in self.red.calles()})
        calles_reales.aplicar(self.red, cache, usar_largo_real=False, mover_nodos=False)
        for c in self.red.calles():
            self.assertAlmostEqual(c.distancia_m, original[c.clave])
            self.assertTrue(c.geometria)                                # el dibujo sigue siendo real

    def test_cache_ida_y_vuelta_y_obtener_sin_descargar(self):
        cache = calles_reales.trazar_red(self.red, self.osm)
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "c.json"
            calles_reales.guardar_cache(cache, ruta)
            self.assertEqual(calles_reales.cargar_cache(ruta)["calles"], cache["calles"])
            original = calles_reales.descargar_osm
            calles_reales.descargar_osm = lambda *a, **k: self.fail("no debía descargar")
            try:
                self.assertEqual(calles_reales.obtener(self.red, ruta=ruta)["calles"], cache["calles"])
            finally:
                calles_reales.descargar_osm = original
            (Path(tmp) / "malo.json").write_text("{no es json", encoding="utf-8")
            self.assertIsNone(calles_reales.cargar_cache(Path(tmp) / "malo.json"))

    def test_sin_internet_da_error_claro(self):
        with self.assertRaisesRegex(calles_reales.ErrorDescarga, "internet"):
            calles_reales.descargar_osm((0, 0, 0.001, 0.001), timeout=2,
                                        servidores=("http://127.0.0.1:9/no-hay-servidor",))

    def test_simplificar_quita_puntos_alineados(self):
        pts = [(-13.5 + i * 1e-4, -71.9) for i in range(10)]
        self.assertEqual(calles_reales.simplificar(pts), [pts[0], pts[-1]])

    def test_pedidos_reubicados_y_cargados_de_archivo(self):
        esc, _ = escenario_con_trazado()
        for p in esc.pedidos:
            x, y = esc.red.punto_en_calle(p.calle[0], p.calle[1], p.t)
            self.assertAlmostEqual(p.x, x)
            self.assertAlmostEqual(p.y, y)
        # un archivo guardado con calles rectas se recoloca sobre el trazado (no da error)
        recto = datos.Escenario.sintetico(5, 3)
        with tempfile.TemporaryDirectory() as tmp:
            datos.guardar_pedidos(recto.pedidos, Path(tmp) / "p.json")
            cargados = datos.cargar_pedidos(Path(tmp) / "p.json", esc.red)
            for p in cargados:
                self.assertAlmostEqual(p.x, esc.red.punto_en_calle(p.calle[0], p.calle[1], p.t)[0])

    def test_generar_pedidos_con_trazado_cae_sobre_las_calles(self):
        esc, _ = escenario_con_trazado()
        for p in datos.generar_pedidos(20, 5, esc.red):
            _, d, *_ = esc.red.calle_mas_cercana(p.x, p.y)
            self.assertLess(d, 1e-6)


class PruebasCorrecciones(unittest.TestCase):
    def test_asignacion_voraz_no_asigna_inalcanzables(self):
        esc = datos.Escenario.sintetico(18, 7)
        destino = "San Sebastián"
        for v, _, _ in esc.red.vecinos_todos(destino):
            esc.red.bloquear_calle(destino, v)
        p = esc.pedidos[0]
        p.calle, p.t = ("Wanchaq", "San Sebastián"), 0.95
        p.x, p.y = esc.red.punto_en_calle("Wanchaq", "San Sebastián", 0.95)
        rv = esc.crear_red_vial()
        asignacion, pendientes = voraz.asignar_mas_cercano(esc.pedidos, esc.repartidores, rv.distancia)
        self.assertIn(p.id, [q.id for q in pendientes])
        for lista in asignacion.values():
            for q in lista:
                self.assertFalse(math.isinf(rv.distancia(esc.repartidores[0], q)) and
                                 all(math.isinf(rv.distancia(r, q)) for r in esc.repartidores))

    def test_mochila_voraz_respeta_el_objetivo(self):
        pedidos = datos.generar_pedidos(15, 2)
        _, valor, _ = voraz.mochila_voraz(pedidos, 25, lambda p: p.urgencia)
        elegidos, _, _ = voraz.mochila_voraz(pedidos, 25, lambda p: p.urgencia)
        self.assertEqual(valor, sum(p.urgencia for p in elegidos))
        _, optimo, _ = programacion_dinamica.mochila_01(pedidos, 25, lambda p: p.urgencia)
        self.assertLessEqual(valor, optimo)


class PruebasExportar(unittest.TestCase):
    def setUp(self):
        self.esc = datos.Escenario.sintetico(8, 4)
        self.rv = self.esc.crear_red_vial()
        self.rep = self.esc.repartidores[0]
        self.orden, _ = voraz.ruta_vecino_mas_cercano(self.rep, self.esc.pedidos, self.rv.distancia)

    def test_llegadas_crecientes_y_ventanas(self):
        ll = exportar.llegadas(self.rep, self.orden, self.rv.distancia, 30)
        self.assertEqual(len(ll), len(self.orden))
        self.assertTrue(all(a.minuto <= b.minuto for a, b in zip(ll, ll[1:])))
        primero = ll[0]
        self.assertAlmostEqual(primero.minuto, self.rv.distancia(self.rep, self.orden[0]) / 500)
        self.assertEqual(primero.a_tiempo, primero.minuto <= self.orden[0].ventana_fin)

    def test_gpx_csv_y_google_maps(self):
        coords = traductor.puntos_xy_a_coordenadas(self.rv.ruta(self.rep, self.orden))
        r = exportar.RutaExportable("A", "#000", self.rep, self.orden, coords,
                                    exportar.llegadas(self.rep, self.orden, self.rv.distancia))
        with tempfile.TemporaryDirectory() as tmp:
            gpx = exportar.a_gpx([r], Path(tmp) / "r.gpx").read_text(encoding="utf-8")
            self.assertEqual(gpx.count("<wpt"), len(self.orden))
            self.assertEqual(gpx.count("<trkpt"), len(coords))
            import xml.dom.minidom
            xml.dom.minidom.parseString(gpx)            # XML bien formado
            exportar.a_csv([r], Path(tmp) / "r.csv")
            with (Path(tmp) / "r.csv").open(encoding="utf-8-sig") as f:
                filas = list(csv.DictReader(f))
            self.assertEqual([f["pedido"] for f in filas], [p.id for p in self.orden])
        urls = exportar.urls_google_maps(r)
        self.assertEqual(len(urls), 1)
        self.assertIn("waypoints=", urls[0])
        largo = exportar.RutaExportable("B", "#000", self.rep, self.esc.pedidos * 6, coords, [])
        self.assertGreater(len(exportar.urls_google_maps(largo)), 1)


class PruebasEstadistica(unittest.TestCase):
    def test_wilcoxon_casos_conocidos(self):
        r = estadistica.wilcoxon([1] * 10, "mayor")
        self.assertAlmostEqual(r.w_mas, 55)
        self.assertLess(r.p, 0.01)
        r = estadistica.wilcoxon([0] * 10, "mayor")
        self.assertEqual(r.p, 1.0)
        self.assertEqual(r.empates, 10)
        r = estadistica.wilcoxon([1, -1] * 10, "distinta")
        self.assertAlmostEqual(r.p, 1.0)

    def test_igual_que_scipy_si_esta_instalado(self):
        try:
            from scipy.stats import wilcoxon as w_scipy
        except ImportError:
            self.skipTest("SciPy no está instalado")
        import random
        azar = random.Random(3)
        d = [round(azar.gauss(0.4, 1), 1) if azar.random() > 0.3 else 0.0 for _ in range(30)]
        for alt, nombre in (("mayor", "greater"), ("menor", "less"), ("distinta", "two-sided")):
            ref = w_scipy(d, zero_method="pratt", correction=False, method="approx", alternative=nombre)
            self.assertAlmostEqual(estadistica.wilcoxon(d, alt).p, ref.pvalue, places=10)

    def test_holm(self):
        self.assertEqual(estadistica.holm([0.01, 0.04, 0.03, 0.005]), [0.03, 0.06, 0.06, 0.02])

    def test_bootstrap_reproducible(self):
        a = estadistica.bootstrap_ic([1, 2, 3, 4, 5], remuestreos=500)
        b = estadistica.bootstrap_ic([1, 2, 3, 4, 5], remuestreos=500)
        self.assertEqual(a, b)
        self.assertTrue(1 <= a[0] <= 3 <= a[1] <= 5)


class PruebasExperimentos(unittest.TestCase):
    def test_lote_corto_completo(self):
        cfg = experimentos.Configuracion(semillas=2, repeticiones=0, remuestreos=200)
        with tempfile.TemporaryDirectory() as tmp:
            r = experimentos.ejecutar(cfg, tmp)
            nombres = sorted(p.name for p in Path(tmp).iterdir())
            for e in ("E1_Ruta.csv", "E1_Carga.csv", "E2.csv", "E3a.csv", "E3b.csv", "E4.csv",
                      "resumen.md", "analisis.json"):
                self.assertIn(e, nombres)
        res, a = r["resultados"], r["analisis"]
        self.assertEqual(len(res["E1-Ruta"]), 4 * 2)
        self.assertEqual(len(res["E1-Carga"]), 6 * 2)
        self.assertEqual(len(res["E2"]), 3 * 2)
        self.assertEqual(len(res["E3a"]), 2 * 2)
        self.assertEqual(len(res["E3b"]), 4 * 2)
        self.assertEqual(len(res["E4"]), 2)
        # comprobaciones de corrección del diseño
        self.assertTrue(all(f["dist_vmc_km"] >= f["dist_hk_km"] - 1e-9 for f in res["E1-Ruta"]))
        self.assertTrue(a["E1-Ruta_bt_coincide"])
        self.assertTrue(all(f["valor_pd"] >= f["valor_voraz"] for f in res["E1-Carga"]))
        self.assertEqual(a["H3_coincide_dijkstra_pct"], 100)
        self.assertTrue(all(f["nodos_sin_poda"] >= f["nodos_ryp"] for f in res["E2"]))
        self.assertEqual(len(a["H1"]), 4)
        self.assertEqual(len(a["H2"]), 6)

    def test_mismas_semillas_mismos_resultados(self):
        cfg = experimentos.Configuracion(semillas=2, repeticiones=0, solo=("E1-Carga", "E2"), remuestreos=100)
        r1 = experimentos.ejecutar(cfg)["resultados"]
        r2 = experimentos.ejecutar(cfg)["resultados"]
        quitar = lambda filas: [{k: v for k, v in f.items() if not k.startswith("t_")} for f in filas]  # noqa: E731
        for e in r1:
            self.assertEqual(quitar(r1[e]), quitar(r2[e]))

    def test_cancelar(self):
        cfg = experimentos.Configuracion(semillas=2, repeticiones=0, cancelar=lambda: True)
        with self.assertRaises(experimentos.Cancelado):
            experimentos.ejecutar(cfg)


if __name__ == "__main__":
    unittest.main()
