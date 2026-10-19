"""Pruebas de los algoritmos. Ejecutar con: python -m unittest discover -s tests -v"""

import itertools
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import (backtracking, datos, divide_venceras, ordenacion,
                 programacion_dinamica, voraz)
from src.modelos import Pedido, distancia
from src.red import RedVial


def pedido(id_, x, y, urgencia=1, peso=1, valor=1):
    return Pedido(id_, f"Cliente {id_}", x, y, urgencia, peso, valor)


class PruebasOrdenacion(unittest.TestCase):
    def setUp(self):
        self.pedidos = datos.generar_pedidos(40, 3)

    def test_merge_sort_por_urgencia(self):
        res = ordenacion.merge_sort(self.pedidos, lambda p: p.urgencia, inverso=True)
        self.assertEqual([p.urgencia for p in res],
                         sorted((p.urgencia for p in self.pedidos), reverse=True))

    def test_heap_sort_por_distancia(self):
        clave = lambda p: p.x + p.y
        res = ordenacion.heap_sort(self.pedidos, clave)
        self.assertEqual([clave(p) for p in res], sorted(clave(p) for p in self.pedidos))

    def test_merge_sort_es_estable(self):
        res = ordenacion.merge_sort(self.pedidos, lambda p: p.urgencia)
        esperado = sorted(self.pedidos, key=lambda p: p.urgencia)
        self.assertEqual([p.id for p in res], [p.id for p in esperado])

    def test_busqueda_binaria(self):
        por_id = ordenacion.merge_sort(self.pedidos, lambda p: p.id)
        encontrado, comparaciones = ordenacion.busqueda_binaria(por_id, "P17", lambda p: p.id)
        self.assertEqual(encontrado.id, "P17")
        self.assertLessEqual(comparaciones, math.ceil(math.log2(len(por_id))) + 1)
        self.assertIsNone(ordenacion.busqueda_binaria(por_id, "P99", lambda p: p.id)[0])

    def test_indice_sectores(self):
        indice = ordenacion.construir_indice_sectores(self.pedidos)
        self.assertEqual(sum(len(v) for v in indice.values()), len(self.pedidos))


class PruebasVoraz(unittest.TestCase):
    def test_vecino_mas_cercano_simple(self):
        inicio = pedido("S", 0, 0)
        ps = [pedido("A", 10, 0), pedido("B", 1, 0), pedido("C", 5, 0)]
        orden, total = voraz.ruta_vecino_mas_cercano(inicio, ps)
        self.assertEqual([p.id for p in orden], ["B", "C", "A"])
        self.assertAlmostEqual(total, 10.0)

    def test_asignacion_respeta_capacidad(self):
        ps = datos.generar_pedidos(25, 5)
        reps = datos.crear_repartidores()
        asignacion, pendientes = voraz.asignar_mas_cercano(ps, reps)
        for r in reps:
            self.assertLessEqual(sum(p.peso for p in asignacion[r.nombre]), r.capacidad)
        asignados = sum(len(v) for v in asignacion.values())
        self.assertEqual(asignados + len(pendientes), len(ps))

    def test_mochila_voraz_no_pasa_capacidad(self):
        ps = datos.generar_pedidos(15, 2)
        _, _, peso = voraz.mochila_voraz(ps, 25)
        self.assertLessEqual(peso, 25)

    def test_dijkstra_conocido(self):
        grafo = datos.construir_grafo()
        costo, camino = voraz.dijkstra(grafo, "San Blas", "Wanchaq")
        self.assertEqual(camino[0], "San Blas")
        self.assertEqual(camino[-1], "Wanchaq")
        esperado = sum(datos.costo_calle(a, b) for a, b in zip(camino, camino[1:]))
        self.assertAlmostEqual(costo, esperado)
        # ningún otro camino simple conocido (los directos de abajo) es más corto
        for alterno in (["San Blas", "Plaza de Armas", "Av. El Sol", "Coricancha", "Av. Pardo", "Wanchaq"],
                        ["San Blas", "Zaguán del Cielo", "Av. de la Cultura", "Wanchaq"]):
            self.assertLessEqual(costo, datos.crear_red().costo_camino(alterno) + 1e-6)

    def test_dijkstra_igual_a_networkx(self):
        try:
            import networkx as nx
        except ImportError:
            self.skipTest("networkx no está instalado")
        from src import traductor
        red = datos.crear_red()
        g = traductor.a_networkx(red)
        for origen, destino in (("San Blas", "Wanchaq"), ("San Pedro", "San Sebastián"),
                                ("Santa Ana", "Mercado Central")):
            costo, camino = voraz.dijkstra(red, origen, destino)
            self.assertAlmostEqual(costo, nx.dijkstra_path_length(g, origen, destino, "peso"), places=6)
            self.assertAlmostEqual(red.costo_camino(camino), costo, places=6)


class PruebasDivideVenceras(unittest.TestCase):
    def test_zonas_cubren_todos_los_pedidos(self):
        ps = datos.generar_pedidos(30, 9)
        for k in (2, 3, 4):
            zonas = divide_venceras.dividir_en_zonas(ps, k, datos.LIMITES)
            self.assertEqual(len(zonas), k)
            ids = sorted(p.id for _, lista in zonas for p in lista)
            self.assertEqual(ids, sorted(p.id for p in ps))

    def test_pedidos_dentro_de_sus_limites(self):
        ps = datos.generar_pedidos(30, 4)
        for (x0, y0, x1, y1), lista in divide_venceras.dividir_en_zonas(ps, 3, datos.LIMITES):
            for p in lista:
                self.assertTrue(x0 <= p.x <= x1 and y0 <= p.y <= y1)


def mochila_fuerza_bruta(ps, capacidad):
    mejor = 0
    for r in range(len(ps) + 1):
        for comb in itertools.combinations(ps, r):
            if sum(p.peso for p in comb) <= capacidad:
                mejor = max(mejor, sum(p.valor for p in comb))
    return mejor


class PruebasProgramacionDinamica(unittest.TestCase):
    def test_mochila_igual_a_fuerza_bruta(self):
        for semilla in range(1, 6):
            ps = datos.generar_pedidos(10, semilla)
            _, valor, peso = programacion_dinamica.mochila_01(ps, 20)
            self.assertEqual(valor, mochila_fuerza_bruta(ps, 20))
            self.assertLessEqual(peso, 20)

    def test_mochila_caso_clasico(self):
        ps = [pedido("A", 0, 0, peso=1, valor=1), pedido("B", 0, 0, peso=3, valor=4),
              pedido("C", 0, 0, peso=4, valor=5), pedido("D", 0, 0, peso=5, valor=7)]
        elegidos, valor, _ = programacion_dinamica.mochila_01(ps, 7)
        self.assertEqual(valor, 9)
        self.assertEqual(sorted(p.id for p in elegidos), ["B", "C"])

    def test_held_karp_igual_a_fuerza_bruta(self):
        inicio = pedido("S", 20, 20)
        ps = datos.generar_pedidos(7, 11)
        _, total = programacion_dinamica.ruta_optima_held_karp(inicio, ps)
        mejor = math.inf
        for perm in itertools.permutations(ps):
            costo = distancia(inicio, perm[0]) + sum(
                distancia(perm[i], perm[i + 1]) for i in range(len(perm) - 1))
            mejor = min(mejor, costo)
        self.assertAlmostEqual(total, mejor)

    def test_held_karp_no_es_peor_que_voraz(self):
        inicio = pedido("S", 20, 20)
        ps = datos.generar_pedidos(9, 21)
        _, optimo = programacion_dinamica.ruta_optima_held_karp(inicio, ps)
        _, heuristica = voraz.ruta_vecino_mas_cercano(inicio, ps)
        self.assertLessEqual(optimo, heuristica + 1e-9)


class PruebasBacktracking(unittest.TestCase):
    def setUp(self):
        self.grafo = datos.construir_grafo()

    def test_mejor_ruta_coincide_con_dijkstra(self):
        rutas, _ = backtracking.todas_las_rutas(self.grafo, "San Blas", "Wanchaq")
        costo, _ = voraz.dijkstra(self.grafo, "San Blas", "Wanchaq")
        self.assertAlmostEqual(rutas[0][0], costo, places=6)

    def test_calles_cerradas_se_evitan(self):
        cerradas = {datos.clave_calle(a, b) for a, b in datos.CALLES_CERRADAS_EJEMPLO}
        rutas, _ = backtracking.todas_las_rutas(self.grafo, "San Blas", "Wanchaq", cerradas)
        self.assertGreater(len(rutas), 0)
        for _, camino in rutas:
            for a, b in zip(camino, camino[1:]):
                self.assertNotIn(datos.clave_calle(a, b), cerradas)
        costo, _ = voraz.dijkstra(self.grafo, "San Blas", "Wanchaq", cerradas)
        self.assertAlmostEqual(rutas[0][0], costo, places=6)

    def test_poda_con_cota_explora_menos(self):
        _, sin_poda = backtracking.todas_las_rutas(self.grafo, "San Blas", "Wanchaq")
        base, _ = voraz.dijkstra(self.grafo, "San Blas", "Wanchaq")
        _, con_poda = backtracking.todas_las_rutas(self.grafo, "San Blas", "Wanchaq", cota=base * 1.5)
        self.assertLess(con_poda["nodos"], sin_poda["nodos"])

    def test_branch_and_bound_encuentra_el_optimo(self):
        cerradas = {datos.clave_calle(a, b) for a, b in datos.CALLES_CERRADAS_EJEMPLO}
        costo, camino, _ = backtracking.ruta_mas_corta_bt(self.grafo, "San Blas", "Wanchaq", cerradas)
        esperado, _ = voraz.dijkstra(self.grafo, "San Blas", "Wanchaq", cerradas)
        self.assertAlmostEqual(costo, esperado, places=6)
        self.assertEqual(camino[0], "San Blas")
        self.assertEqual(camino[-1], "Wanchaq")

    def test_sin_ruta_si_se_aisla_el_destino(self):
        cerradas = {datos.clave_calle("San Sebastián", "Wanchaq"),
                    datos.clave_calle("San Sebastián", "Av. Pardo")}
        costo, camino, _ = backtracking.ruta_mas_corta_bt(self.grafo, "San Blas", "San Sebastián", cerradas)
        self.assertEqual(costo, math.inf)
        self.assertEqual(camino, [])


class PruebasRedVial(unittest.TestCase):
    def setUp(self):
        self.pedidos = datos.generar_pedidos(18, 7)
        self.reps = datos.crear_repartidores()
        self.deposito = datos.crear_deposito()
        self.todos = self.pedidos + self.reps + [self.deposito]

    def test_pedidos_estan_sobre_calles(self):
        for p in self.pedidos:
            a, b = p.calle
            self.assertIn((a, b), datos.CALLES)
            xa, ya = datos.NODOS[a]
            xb, yb = datos.NODOS[b]
            self.assertAlmostEqual(p.x, xa + p.t * (xb - xa))
            self.assertAlmostEqual(p.y, ya + p.t * (yb - ya))

    def test_distancia_por_calles_no_baja_de_la_recta(self):
        red = RedVial()
        red.preparar(self.todos)
        for a in self.pedidos:
            for b in self.pedidos:
                self.assertGreaterEqual(red.distancia(a, b), distancia(a, b) - 1e-9)

    def test_distancia_simetrica_y_cero_consigo_mismo(self):
        red = RedVial()
        red.preparar(self.todos)
        for a in self.pedidos:
            self.assertAlmostEqual(red.distancia(a, a), 0.0)
            for b in self.pedidos:
                self.assertAlmostEqual(red.distancia(a, b), red.distancia(b, a))

    def test_calles_cerradas_dejan_distancias_finitas(self):
        cerradas = {datos.clave_calle(a, b) for a, b in datos.CALLES_CERRADAS_EJEMPLO}
        red = RedVial(cerradas)
        red.preparar(self.todos)
        for a in self.todos:
            for b in self.todos:
                self.assertTrue(math.isfinite(red.distancia(a, b)))

    def test_cerrar_calles_no_acorta_distancias(self):
        abierta, cerrada = RedVial(), RedVial(
            {datos.clave_calle(a, b) for a, b in datos.CALLES_CERRADAS_EJEMPLO})
        abierta.preparar(self.todos)
        cerrada.preparar(self.todos)
        for a in self.pedidos:
            for b in self.pedidos:
                self.assertGreaterEqual(cerrada.distancia(a, b), abierta.distancia(a, b) - 1e-9)

    def test_camino_empieza_y_termina_en_los_puntos(self):
        red = RedVial()
        red.preparar(self.todos)
        a, b = self.pedidos[0], self.pedidos[5]
        camino = red.camino(a, b)
        self.assertAlmostEqual(camino[0][0], a.x)
        self.assertAlmostEqual(camino[0][1], a.y)
        self.assertAlmostEqual(camino[-1][0], b.x)
        self.assertAlmostEqual(camino[-1][1], b.y)

    def test_longitud_del_camino_igual_a_la_distancia(self):
        red = RedVial()
        red.preparar(self.todos)
        a, b = self.reps[0], self.pedidos[3]
        camino = red.camino(a, b)
        largo = sum(math.hypot(camino[i + 1][0] - camino[i][0], camino[i + 1][1] - camino[i][1])
                    for i in range(len(camino) - 1))
        # el camino dibujado son cuerdas rectas entre nodos (unidades de 100 m); la distancia
        # por calles las alarga con el factor de sinuosidad (entre 1.10 y 1.35)
        recta = largo * datos.UNIDAD_M
        self.assertLessEqual(recta, red.distancia(a, b) + 1e-6)
        self.assertGreaterEqual(recta * max(datos.SINUOSIDAD.values()), red.distancia(a, b) - 1e-6)

    def test_voraz_y_held_karp_usan_calles(self):
        red = RedVial()
        red.preparar(self.todos)
        rep, ps = self.reps[0], self.pedidos[:8]
        _, voraz_calles = voraz.ruta_vecino_mas_cercano(rep, ps, red.distancia)
        _, optimo_calles = programacion_dinamica.ruta_optima_held_karp(rep, ps, red.distancia)
        self.assertLessEqual(optimo_calles, voraz_calles + 1e-9)


if __name__ == "__main__":
    unittest.main()
