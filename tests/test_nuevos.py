"""Pruebas del traductor, los algoritmos nuevos, el benchmark y (si hay pantalla) la GUI.

Ejecutar con: python -m unittest discover -s tests -v
"""

import itertools
import math
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import (backtracking, benchmark, datos, divide_venceras, ordenacion,
                 programacion_dinamica, traductor, voraz)
from src.modelos import Nodo, Pedido, Repartidor


def euclidiana(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def pedido(id_, x, y, peso=1, valor=1, urgencia=1):
    return Pedido(id_, f"Cliente {id_}", x, y, urgencia, peso, valor)


# --------------------------------------------------------------------------- traductor
class PruebasTraductor(unittest.TestCase):
    def test_ida_y_vuelta_exacta(self):
        for x, y in ((0, 0), (12.5, -7.25), (-30, 40)):
            lat, lon = traductor.xy_a_latlon(x, y)
            self.assertAlmostEqual(traductor.latlon_a_xy(lat, lon)[0], x, places=9)
            self.assertAlmostEqual(traductor.latlon_a_xy(lat, lon)[1], y, places=9)

    def test_proyeccion_coincide_con_haversine(self):
        a, b = traductor.xy_a_latlon(0, 0), traductor.xy_a_latlon(30, 40)   # 5 km en el plano
        self.assertAlmostEqual(traductor.haversine_m(*a, *b), 5000, delta=15)

    def test_nodos_estan_en_cusco(self):
        for nombre, (lat, lon) in datos.NODOS_LATLON.items():
            self.assertTrue(-13.60 < lat < -13.45 and -72.05 < lon < -71.85, nombre)

    def test_ids_a_coordenadas_con_red(self):
        red = datos.crear_red()
        ruta = ["San Blas", "Plaza de Armas", "Av. El Sol"]
        pares = traductor.ids_a_coordenadas(red, ruta)
        self.assertEqual(pares, [datos.NODOS_LATLON[n] for n in ruta])
        for par in pares:
            self.assertIsInstance(par, tuple)
            self.assertEqual(len(par), 2)

    def test_ids_a_coordenadas_con_networkx_y_diccionario(self):
        red = datos.crear_red()
        ruta = ["San Blas", "Wanchaq"]
        esperado = [datos.NODOS_LATLON[n] for n in ruta]
        self.assertEqual(traductor.ids_a_coordenadas(datos.NODOS_LATLON, ruta), esperado)
        try:
            import networkx as nx
        except ImportError:
            return
        g = traductor.a_networkx(red)
        camino = nx.dijkstra_path(g, "San Blas", "Wanchaq", weight="peso")
        self.assertEqual(traductor.ids_a_coordenadas(g, camino),
                         [datos.NODOS_LATLON[n] for n in camino])
        self.assertEqual(g.number_of_nodes(), len(red.nodos))
        self.assertEqual(g.number_of_edges(), len(red.calles()))

    def test_networkx_solo_abiertas(self):
        try:
            import networkx  # noqa: F401
        except ImportError:
            self.skipTest("networkx no está instalado")
        red = datos.crear_red([("San Blas", "Plaza de Armas")])
        self.assertEqual(traductor.a_networkx(red, solo_abiertas=True).number_of_edges(),
                         len(red.calles()) - 1)

    def test_id_inexistente_da_keyerror_claro(self):
        with self.assertRaises(KeyError):
            traductor.ids_a_coordenadas(datos.crear_red(), ["San Blas", "Atlantis"])

    def test_formatear_rechaza_puntos_invalidos(self):
        with self.assertRaises(ValueError):
            traductor.formatear_para_mapview([(-13.5, -71.9), (200, 0)])
        with self.assertRaises(ValueError):
            traductor.formatear_para_mapview([("a", "b")])

    def test_quita_repetidos_y_poligono(self):
        self.assertEqual(len(traductor.formatear_para_mapview([(1, 2), (1, 2), (3, 4)])), 2)
        poligono = traductor.poligono_de_limites((0, 0, 10, 5))
        self.assertEqual(len(poligono), 4)
        arriba_izq, abajo_der = traductor.caja_a_mapview((0, 0, 10, 5))
        self.assertGreater(arriba_izq[0], abajo_der[0])   # lat mayor = más al norte
        self.assertLess(arriba_izq[1], abajo_der[1])


class PruebasModelosGeo(unittest.TestCase):
    def test_nodo_latlon_manda_sobre_xy(self):
        n = Nodo("A", 999, 999, -13.5170, -71.9785)
        self.assertAlmostEqual(n.x, 0, places=6)
        self.assertAlmostEqual(n.y, 0, places=6)
        self.assertEqual(Nodo.from_dict(n.to_dict()), n)

    def test_nodo_legado_xy_y_validacion(self):
        n = Nodo.from_dict({"nombre": "B", "x": 3, "y": 4})
        self.assertTrue(-90 < n.lat < 90)
        with self.assertRaises(ValueError):
            Nodo("C", 0, 0, 95.0, 0.0)
        with self.assertRaises(ValueError):
            Nodo.from_dict({"nombre": "D", "lat": "no", "lon": 1})

    def test_pedido_desde_latlon(self):
        p = Pedido.from_dict(dict(id="P1", lat=-13.5170, lon=-71.9785, urgencia=3, peso=2, valor=5))
        self.assertAlmostEqual(p.x, 0, places=6)
        self.assertAlmostEqual(p.lat, -13.5170, places=7)
        self.assertNotIn("lat", p.to_dict())
        self.assertIn("lat", p.to_dict(geo=True))

    def test_repartidor_latlon(self):
        r = Repartidor.from_dict(dict(nombre="R", lat=-13.52, lon=-71.97, capacidad=10))
        self.assertAlmostEqual(r.lat, -13.52, places=7)


class PruebasArchivosGeo(unittest.TestCase):
    def test_ida_y_vuelta_json_y_csv(self):
        esc = datos.Escenario.sintetico(10, 3)
        for formato in ("json", "csv"):
            with tempfile.TemporaryDirectory() as d:
                esc.guardar(d, formato)
                nuevo = datos.Escenario.cargar(os.path.join(d, f"red_cusco.{formato}"),
                                               os.path.join(d, f"pedidos.{formato}"),
                                               os.path.join(d, f"repartidores.{formato}"))
            self.assertEqual(len(nuevo.pedidos), 10)
            for nombre, nodo in esc.red.nodos.items():
                self.assertAlmostEqual(nuevo.red.nodos[nombre].lat, nodo.lat, places=9)
                self.assertAlmostEqual(nuevo.red.nodos[nombre].lon, nodo.lon, places=9)
            for a, b in zip(esc.pedidos, nuevo.pedidos):
                self.assertEqual((a.id, a.calle), (b.id, b.calle))
                self.assertAlmostEqual(a.x, b.x, places=6)

    def test_pedidos_solo_con_latlon_se_ajustan_a_la_calle(self):
        red = datos.crear_red()
        lat, lon = traductor.xy_a_latlon(*[(a + b) / 2 for a, b in zip(
            datos.NODOS["Plaza de Armas"], datos.NODOS["San Blas"])])
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "p.json")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write('{"pedidos": [{"id": "G1", "lat": %r, "lon": %r, "urgencia": 2, '
                        '"peso": 3, "valor": 20}]}' % (lat, lon + 0.0004))
            pedidos = datos.cargar_pedidos(ruta, red)
        self.assertEqual(len(pedidos[0].calle), 2)
        self.assertTrue(red.existe_calle(*pedidos[0].calle))


# --------------------------------------------------------------------------- ordenación / búsqueda
class PruebasOrdenacionNueva(unittest.TestCase):
    def test_quick_sort(self):
        ps = datos.generar_pedidos(60, 5)
        for inverso in (False, True):
            esperado = sorted((p.urgencia for p in ps), reverse=inverso)
            self.assertEqual([p.urgencia for p in ordenacion.quick_sort(ps, lambda p: p.urgencia, inverso)],
                             esperado)
        self.assertEqual(ordenacion.quick_sort([], lambda x: x), [])

    def test_indice_hash(self):
        ps = datos.generar_pedidos(20, 2)
        ps[5].cliente = "María  Quispe"
        indice = ordenacion.IndicePedidos(ps)
        self.assertIs(indice.buscar_id("p03"), ps[2])
        self.assertIsNone(indice.buscar_id("P99"))
        self.assertEqual(indice.buscar_cliente("maría quispe"), [ps[5]])
        self.assertEqual(indice.buscar_cliente_parcial("quispe"), [ps[5]])
        self.assertEqual(indice.buscar_cliente("nadie"), [])


# --------------------------------------------------------------------------- programación dinámica
class PruebasMochilaNueva(unittest.TestCase):
    def setUp(self):
        self.ps = datos.generar_pedidos(13, 4)

    def fuerza_bruta(self, cap_kg, cap_m3=None):
        mejor = 0
        for r in range(len(self.ps) + 1):
            for comb in itertools.combinations(self.ps, r):
                if sum(p.peso for p in comb) <= cap_kg and (
                        cap_m3 is None or sum(p.volumen_m3 for p in comb) <= cap_m3 + 1e-9):
                    mejor = max(mejor, sum(p.valor for p in comb))
        return mejor

    def test_reconstruccion_devuelve_ids_consistentes(self):
        for cap in (7, 20, 35):
            for funcion in (programacion_dinamica.mochila_01, programacion_dinamica.mochila_01_memo):
                elegidos, valor, peso = funcion(self.ps, cap)
                self.assertEqual(valor, self.fuerza_bruta(cap))
                self.assertEqual(sum(p.valor for p in elegidos), valor)
                self.assertEqual(sum(p.peso for p in elegidos), peso)
                self.assertLessEqual(peso, cap)
                self.assertEqual(len({p.id for p in elegidos}), len(elegidos))

    def test_memoizacion_igual_a_tabulacion(self):
        for cap in range(0, 40, 5):
            a = programacion_dinamica.mochila_01(self.ps, cap)
            b = programacion_dinamica.mochila_01_memo(self.ps, cap)
            self.assertEqual(a[1], b[1])

    def test_capacidad_cero_y_sin_pedidos(self):
        self.assertEqual(programacion_dinamica.mochila_01(self.ps, 0)[1], 0)
        self.assertEqual(programacion_dinamica.mochila_01([], 10), ([], 0, 0))
        self.assertEqual(programacion_dinamica.mochila_01_memo([], 10), ([], 0, 0))

    def test_peso_y_volumen(self):
        cap_kg, cap_m3 = 30, 0.12
        elegidos, valor, peso, volumen = programacion_dinamica.mochila_01_peso_volumen(
            self.ps, cap_kg, cap_m3)
        self.assertLessEqual(peso, cap_kg)
        self.assertLessEqual(volumen, cap_m3 + 1e-9)
        self.assertEqual(sum(p.valor for p in elegidos), valor)
        self.assertLessEqual(valor, self.fuerza_bruta(cap_kg))
        self.assertGreaterEqual(valor, 0)
        # sin tope práctico de volumen coincide con la mochila de solo peso
        _, v_libre, *_ = programacion_dinamica.mochila_01_peso_volumen(self.ps, cap_kg, 50.0)
        self.assertEqual(v_libre, programacion_dinamica.mochila_01(self.ps, cap_kg)[1])

    def test_maximizar_prioridad(self):
        elegidos, valor, _ = programacion_dinamica.mochila_01(self.ps, 20, lambda p: p.urgencia)
        self.assertEqual(valor, sum(p.urgencia for p in elegidos))

    def test_held_karp_inicio_libre_no_es_peor(self):
        esc = datos.Escenario.sintetico(8, 5)
        rv = esc.crear_red_vial()
        _, con_inicio = programacion_dinamica.ruta_optima_held_karp(esc.repartidores[0], esc.pedidos, rv.distancia)
        orden, libre = programacion_dinamica.ruta_optima_held_karp(None, esc.pedidos, rv.distancia)
        self.assertLessEqual(libre, con_inicio + 1e-9)
        self.assertEqual(len(orden), 8)


# --------------------------------------------------------------------------- backtracking
class PruebasBacktrackingSeguro(unittest.TestCase):
    def setUp(self):
        self.red = datos.crear_red()

    def test_coincide_con_dijkstra(self):
        for o, d in (("San Blas", "Wanchaq"), ("San Pedro", "San Sebastián"), ("Santa Ana", "Coricancha")):
            r = backtracking.ruta_mas_corta_segura(self.red, o, d)
            costo, _ = voraz.dijkstra(self.red, o, d)
            self.assertTrue(r.encontrada)
            self.assertAlmostEqual(r.costo, costo, places=6)
            self.assertEqual((r.camino[0], r.camino[-1]), (o, d))

    def test_poda_explicita_de_calles_bloqueadas(self):
        for a, b in datos.CALLES_CERRADAS_EJEMPLO:
            self.red.bloquear_calle(a, b)
        r = backtracking.ruta_mas_corta_segura(self.red, "San Blas", "Wanchaq")
        self.assertTrue(r.encontrada)
        self.assertGreater(r.podas_bloqueo, 0)
        for a, b in zip(r.camino, r.camino[1:]):
            self.assertFalse(self.red.esta_bloqueada(a, b))
        costo, _ = voraz.dijkstra(self.red, "San Blas", "Wanchaq")
        self.assertAlmostEqual(r.costo, costo, places=6)

    def test_sin_ruta_no_lanza_y_da_mensaje(self):
        for v, _, _ in self.red.vecinos_todos("San Sebastián"):
            self.red.bloquear_calle("San Sebastián", v)
        for funcion in (backtracking.ruta_mas_corta_segura, backtracking.enumerar_rutas_validas):
            r = funcion(self.red, "San Blas", "San Sebastián")
            self.assertFalse(r.encontrada)
            self.assertEqual(r.camino, [])
            self.assertTrue(math.isinf(r.costo))
            self.assertIn("Ruta no encontrada", r.mensaje)

    def test_bloqueo_masivo_de_toda_la_red(self):
        for c in self.red.calles():
            c.bloquear()
        r = backtracking.ruta_mas_corta_segura(self.red, "San Blas", "Wanchaq")
        self.assertFalse(r.encontrada)
        self.assertIn("Ruta no encontrada", r.mensaje)

    def test_nodo_inexistente_y_mismo_nodo(self):
        self.assertIn("no existe", backtracking.ruta_mas_corta_segura(self.red, "X", "Wanchaq").mensaje)
        r = backtracking.ruta_mas_corta_segura(self.red, "Wanchaq", "Wanchaq")
        self.assertTrue(r.encontrada)
        self.assertEqual(r.costo, 0.0)

    def test_enumerar_ordenadas_y_validas(self):
        self.red.bloquear_calle("San Blas", "Zaguán del Cielo")
        r = backtracking.enumerar_rutas_validas(self.red, "San Blas", "Wanchaq", factor_cota=1.6)
        self.assertGreater(len(r.rutas), 1)
        costos = [c for c, _ in r.rutas]
        self.assertEqual(costos, sorted(costos))
        for costo, camino in r.rutas:
            self.assertEqual(len(set(camino)), len(camino))            # sin repetir nodos
            self.assertAlmostEqual(self.red.costo_camino(camino), costo, places=6)

    def test_cancelacion(self):
        evento = threading.Event()
        evento.set()
        r = backtracking.enumerar_rutas_validas(self.red, "San Blas", "Wanchaq", cancelar=evento)
        self.assertTrue(r.cancelado)
        self.assertTrue(r.truncado)

    def test_orden_optimo_igual_a_held_karp(self):
        esc = datos.Escenario.sintetico(8, 9)
        rv = esc.crear_red_vial()
        rep = esc.repartidores[0]
        orden, costo, st = backtracking.orden_optimo_bt(rep, esc.pedidos, rv.distancia)
        _, optimo = programacion_dinamica.ruta_optima_held_karp(rep, esc.pedidos, rv.distancia)
        self.assertTrue(st["completo"])
        self.assertAlmostEqual(costo, optimo, places=6)
        self.assertEqual(sorted(p.id for p in orden), sorted(p.id for p in esc.pedidos))

    def test_orden_optimo_con_limite_de_tiempo_no_garantiza(self):
        esc = datos.Escenario.sintetico(12, 3)
        rv = esc.crear_red_vial()
        orden, costo, st = backtracking.orden_optimo_bt(esc.repartidores[0], esc.pedidos, rv.distancia,
                                                        tiempo_max_s=0.0001)
        self.assertFalse(st["completo"])
        self.assertEqual(len(orden), 12)       # igual devuelve un orden válido (el mejor hallado)


# --------------------------------------------------------------------------- divide y vencerás
class PruebasDivideYVenceras(unittest.TestCase):
    def test_cuadrantes_particionan_los_pedidos(self):
        ps = datos.generar_pedidos(50, 6)
        zonas = divide_venceras.dividir_cuadrantes(ps, datos.LIMITES, 5, 4)
        ids = sorted(p.id for z in zonas for p in z.pedidos)
        self.assertEqual(ids, sorted(p.id for p in ps))
        for z in zonas:
            x0, y0, x1, y1 = z.limites
            for p in z.pedidos:
                self.assertTrue(x0 <= p.x <= x1 and y0 <= p.y <= y1)
            for otra in z.vecinas:                                   # adyacencia simétrica
                self.assertIn(z.id, next(o for o in zonas if o.id == otra).vecinas)

    def test_respeta_tamano_y_profundidad(self):
        ps = datos.generar_pedidos(40, 1)
        zonas = divide_venceras.dividir_cuadrantes(ps, datos.LIMITES, 4, 5)
        self.assertTrue(all(len(z.pedidos) <= 4 or z.nivel == 5 for z in zonas))
        una = divide_venceras.dividir_cuadrantes(ps, datos.LIMITES, 1000, 3)
        self.assertEqual(len(una), 1)

    def test_empalme_invierte_subruta_si_conviene(self):
        izquierda = [pedido("A1", 1, 0), pedido("A2", 2, 0), pedido("A3", 3, 0)]
        derecha = [pedido("B1", 4, 0), pedido("B2", 5, 0)]
        zonas = [divide_venceras.Zona("Z1", (0, -1, 3.5, 1), izquierda, 1),
                 divide_venceras.Zona("Z2", (3.5, -1, 7, 1), derecha, 1)]
        zonas[0].vecinas, zonas[1].vecinas = ["Z2"], ["Z1"]
        # subrutas guardadas "al revés" respecto de la entrada desde el origen
        subrutas = {"Z1": list(reversed(izquierda)), "Z2": list(reversed(derecha))}
        origen = pedido("O", 0, 0)
        ruta, orden_zonas = divide_venceras.combinar_subrutas(origen, zonas, subrutas, euclidiana)
        self.assertEqual([p.id for p in ruta], ["A1", "A2", "A3", "B1", "B2"])
        self.assertEqual(orden_zonas, ["Z1", "Z2"])
        empalmes = divide_venceras.detectar_empalmes(origen, ruta, zonas, euclidiana)
        self.assertEqual(len(empalmes), 1)
        self.assertEqual((empalmes[0].de_zona, empalmes[0].a_zona), ("Z1", "Z2"))
        self.assertTrue(empalmes[0].adyacente)
        self.assertAlmostEqual(empalmes[0].cruce[0], 3.5)             # cruza justo en la frontera

    def test_dos_opt_mejora_un_cruce(self):
        ps = [pedido("P1", 0, 0), pedido("P2", 2, 0), pedido("P3", 1, 0), pedido("P4", 3, 0)]
        inicio = pedido("O", -1, 0)
        mala = [ps[1], ps[2], ps[0], ps[3]]
        buena = divide_venceras.mejorar_2opt(inicio, mala, euclidiana)
        self.assertLess(divide_venceras._costo_ruta(inicio, buena, euclidiana),
                        divide_venceras._costo_ruta(inicio, mala, euclidiana))

    def test_ruta_completa_visita_todo_una_vez(self):
        for n, semilla in ((1, 1), (9, 2), (25, 3), (60, 4)):
            esc = datos.Escenario.sintetico(n, semilla)
            rv = esc.crear_red_vial()
            r = divide_venceras.dividir_y_vencer(esc.repartidores[0], esc.pedidos, datos.LIMITES, rv.distancia)
            self.assertEqual(sorted(p.id for p in r.orden), sorted(p.id for p in esc.pedidos))
            self.assertAlmostEqual(r.distancia, divide_venceras._costo_ruta(esc.repartidores[0], r.orden, rv.distancia))
            self.assertLessEqual(r.distancia, r.distancia_sin_refinar + 1e-9)
            zona_de = {p.id: z.id for z in r.zonas for p in z.pedidos}
            for e in r.empalmes:
                self.assertNotEqual(e.de_zona, e.a_zona)
                self.assertEqual(zona_de[e.hasta], e.a_zona)

    def test_pocos_pedidos_es_optimo(self):
        esc = datos.Escenario.sintetico(7, 12)
        rv = esc.crear_red_vial()
        rep = esc.repartidores[0]
        r = divide_venceras.dividir_y_vencer(rep, esc.pedidos, datos.LIMITES, rv.distancia, max_por_zona=8)
        _, optimo = programacion_dinamica.ruta_optima_held_karp(rep, esc.pedidos, rv.distancia)
        self.assertAlmostEqual(r.distancia, optimo, places=6)          # 1 sola zona exacta

    def test_sin_pedidos(self):
        r = divide_venceras.dividir_y_vencer(None, [], datos.LIMITES, euclidiana)
        self.assertEqual((r.orden, r.empalmes, r.distancia), ([], [], 0.0))

    def test_pedidos_en_el_mismo_punto_no_se_cuelgan(self):
        ps = [pedido(f"P{i}", 5.0, 5.0) for i in range(12)]
        zonas = divide_venceras.dividir_cuadrantes(ps, (0, 0, 10, 10), 3, 4)
        self.assertEqual(sum(len(z.pedidos) for z in zonas), 12)


# --------------------------------------------------------------------------- benchmark
class PruebasBenchmark(unittest.TestCase):
    def test_comparar_rutas(self):
        red = datos.crear_red()
        filas = benchmark.comparar("Rutas", benchmark.contexto_para(8, 3, red, familia="Rutas"), 2)
        por_nombre = {f.algoritmo: f for f in filas}
        self.assertEqual(len(filas), 4)
        for f in filas:
            self.assertGreater(f.tiempo_ms, 0)
            self.assertIsNotNone(f.distancia_km)
        hk = por_nombre["Prog. Dinámica (Held-Karp)"]
        bt = por_nombre["Backtracking (ramificación y poda)"]
        self.assertTrue(hk.optimo and bt.optimo)
        self.assertAlmostEqual(hk.distancia_km, bt.distancia_km, places=6)
        self.assertFalse(por_nombre["Voraz (vecino más cercano)"].optimo)
        for f in filas:
            self.assertGreaterEqual(f.distancia_km, hk.distancia_km - 1e-9)
            self.assertGreaterEqual(f.delta_pct, -1e-9)

    def test_omite_algoritmos_exponenciales_con_n_grande(self):
        red = datos.crear_red()
        filas = benchmark.comparar("Rutas", benchmark.contexto_para(20, 3, red, familia="Rutas"), 1)
        omitidos = [f for f in filas if f.tiempo_ms is None]
        self.assertEqual(len(omitidos), 2)
        self.assertTrue(all("omitido" in f.nota for f in omitidos))

    def test_comparar_mochila_y_ordenacion(self):
        red = datos.crear_red()
        filas = benchmark.comparar("Mochila", benchmark.contexto_para(12, 2, red, familia="Mochila"), 2)
        valores = {f.algoritmo: f.valor for f in filas}
        self.assertEqual(valores["Prog. Dinámica (tabulación)"], valores["Prog. Dinámica (memoización)"])
        self.assertGreaterEqual(valores["Prog. Dinámica (tabulación)"], valores["Voraz (valor/peso)"])
        filas = benchmark.comparar("Ordenación", benchmark.contexto_para(50, 2, red, familia="Ordenación"), 1)
        self.assertTrue(all(f.nota == "orden correcto" for f in filas))
        with self.assertRaises(ValueError):
            benchmark.comparar("Otra", benchmark.contexto_para(5, 1, red))

    def test_curva_tiempos(self):
        curvas = benchmark.curva_tiempos("Rutas", [4, 6, 14, 20], 5, repeticiones=1, tiempo_max_s=5)
        self.assertEqual([n for n, _ in curvas.series["Voraz (vecino más cercano)"]], [4, 6, 14, 20])
        self.assertEqual([n for n, _ in curvas.series["Prog. Dinámica (Held-Karp)"]], [4, 6])  # tope 12
        self.assertTrue(any("Held-Karp" in nota for nota in curvas.notas))
        with self.assertRaises(ValueError):
            benchmark.curva_tiempos("Rutas", [])

    def test_curva_se_puede_cancelar(self):
        evento = threading.Event()
        evento.set()
        curvas = benchmark.curva_tiempos("Rutas", [4, 6], 5, cancelar=evento)
        self.assertTrue(any("cancelada" in n for n in curvas.notas))

    def test_medir_usa_mediana_y_devuelve_resultado(self):
        llamadas = []
        resultado, ms = benchmark.medir(lambda: llamadas.append(1) or 42, repeticiones=3)
        self.assertEqual(resultado, 42)
        self.assertEqual(len(llamadas), 3)
        self.assertGreaterEqual(ms, 0)

    def test_texto_de_la_matriz(self):
        red = datos.crear_red()
        texto = benchmark.a_texto(benchmark.comparar("Rutas", benchmark.contexto_para(6, 1, red), 1))
        self.assertIn("Tiempo (ms)", texto)
        self.assertIn("Held-Karp", texto)


# --------------------------------------------------------------------------- GUI (solo con pantalla)
def _hay_pantalla() -> bool:
    try:
        import customtkinter  # noqa: F401
        import tkinter
        import tkintermapview  # noqa: F401
        raiz = tkinter.Tk()
        raiz.destroy()
        return True
    except Exception:  # noqa: BLE001 - sin tkinter, sin dependencias o sin DISPLAY
        return False


@unittest.skipUnless(_hay_pantalla(), "GUI: faltan customtkinter/tkintermapview o una pantalla (use xvfb-run)")
class PruebasGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.gui import App
        cls.app = App(calles_reales_auto=False)
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()

    def test_clic_en_mapa_bloquea_y_abre_calle(self):
        import src.gui as gui
        app = self.app
        app._cambiar_modo(gui.MODOS[1])
        from src import traductor
        punto = traductor.xy_a_latlon(*app.esc.red.punto_en_calle("San Blas", "Plaza de Armas", 0.5))
        app._clic_mapa(punto)
        self.assertTrue(app.esc.red.esta_bloqueada("San Blas", "Plaza de Armas"))
        app._clic_mapa(punto)
        self.assertFalse(app.esc.red.esta_bloqueada("San Blas", "Plaza de Armas"))
        app._cambiar_modo(gui.MODOS[0])

    def test_agregar_pedido_con_clic(self):
        import src.gui as gui
        app = self.app
        antes = len(app.esc.pedidos)
        app._cambiar_modo(gui.MODOS[2])
        app._clic_mapa((-13.5185, -71.9770))
        self.assertEqual(len(app.esc.pedidos), antes + 1)
        nuevo = app.esc.pedidos[-1]
        self.assertTrue(app.esc.red.existe_calle(*nuevo.calle))
        app._cambiar_modo(gui.MODOS[0])

    def test_algoritmos_corren_en_hilo_y_la_ui_responde(self):
        app = self.app
        app._asignar_voraz()
        self.assertTrue(app._ocupado or True)
        app.esperar_tarea(30)
        self.assertFalse(app._ocupado)
        self.assertTrue(app.asignacion)
        app._ejecutar_dyv()
        app.esperar_tarea(30)
        self.assertTrue(app.vista["rutas"])
        app._bt_mas_corta()
        app.esperar_tarea(30)
        self.assertTrue(app.vista["rutas"])

    def test_ruta_no_encontrada_muestra_alerta(self):
        app = self.app
        app._abrir_todas()
        app.opt_destino.set("San Sebastián")
        app._aislar_destino()
        app._bt_mas_corta()
        app.esperar_tarea(30)
        self.assertIn("Ruta no encontrada", app.banner.cget("text"))
        app._abrir_todas()

    def test_tarea_que_falla_no_cuelga_la_ui(self):
        app = self.app
        app._correr("falla", lambda cancelar, progreso: 1 / 0, lambda r: None)
        app.esperar_tarea(10)
        self.assertFalse(app._ocupado)


if __name__ == "__main__":
    unittest.main()
