"""Pruebas de modelos, red vial dinámica y carga/guardado de datos.

Ejecutar con: python -m unittest discover -s tests -v
"""

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import backtracking, datos, voraz
from src.modelos import Calle, Pedido, Punto, Repartidor
from src.red import RedCusco, RedVial


def pedido(**cambios):
    base = dict(id="P01", cliente="Ana", x=20.0, y=23.0, urgencia=3, peso=5, valor=50)
    base.update(cambios)
    return Pedido(**base)


class PruebasModelos(unittest.TestCase):
    def test_pedido_ida_y_vuelta_por_diccionario(self):
        for p in datos.generar_pedidos(10, 4):
            self.assertEqual(Pedido.from_dict(p.to_dict()), p)

    def test_pedido_sobrevive_a_json(self):
        p = datos.generar_pedidos(1, 2)[0]
        self.assertEqual(Pedido.from_dict(json.loads(json.dumps(p.to_dict()))), p)

    def test_validaciones_de_pedido(self):
        casos = [dict(peso=0), dict(peso=-3), dict(peso=2.5), dict(urgencia=0),
                 dict(urgencia=6), dict(id=""), dict(valor=-1), dict(volumen_m3=-0.1),
                 dict(t=1.5, calle=("a", "b")), dict(ventana_inicio=60, ventana_fin=30),
                 dict(estado="XX"), dict(x=float("nan"))]
        for cambios in casos:
            with self.subTest(cambios=cambios), self.assertRaises(ValueError):
                pedido(**cambios)

    def test_from_dict_pide_campos_obligatorios(self):
        with self.assertRaisesRegex(ValueError, "faltan"):
            Pedido.from_dict({"id": "P1", "x": 1, "y": 1})

    def test_from_dict_acepta_texto_de_csv_y_alias(self):
        p = Pedido.from_dict({"id": "P9", "x": "20", "y": "23", "prioridad": "4", "peso": "7",
                              "valor": "60", "calle": "Plaza de Armas|Av. El Sol",
                              "t": "0.5", "cliente": "", "volumen_m3": ""})
        self.assertEqual((p.urgencia, p.peso, p.prioridad), (4, 7, 4))
        self.assertEqual(p.calle, ("Plaza de Armas", "Av. El Sol"))
        self.assertEqual(p.cliente, "Cliente P9")

    def test_ventana_y_holgura(self):
        p = pedido(ventana_inicio=30, ventana_fin=90)
        self.assertTrue(p.en_ventana(60))
        self.assertFalse(p.en_ventana(10))
        self.assertEqual(p.holgura(80), 10)

    def test_calle_valida_y_calcula_tiempo(self):
        c = Calle("A", "B", 1000.0, tipo="avenida")
        self.assertAlmostEqual(c.tiempo_s, 1000 / (35 / 3.6))
        for malo in (dict(distancia_m=0), dict(factor_trafico=0), dict(estado="X"),
                     dict(tipo="autopista"), dict(destino="A")):
            args = dict(origen="A", destino="B", distancia_m=100.0)
            args.update(malo)
            with self.subTest(malo=malo), self.assertRaises(ValueError):
                Calle(**args)

    def test_calle_ida_y_vuelta_y_costos(self):
        c = Calle("A", "B", 500.0, factor_trafico=2.0, estado="bloqueado")
        self.assertEqual(c.estado, "BLOQUEADO")
        self.assertEqual(Calle.from_dict(c.to_dict()), c)
        self.assertEqual(c.costo("peso"), 1000.0)
        self.assertEqual(c.costo("distancia"), 500.0)
        self.assertAlmostEqual(c.costo("tiempo"), 2 * c.tiempo_s)
        self.assertEqual(c.clave, frozenset(("A", "B")))

    def test_repartidor_y_punto(self):
        r = datos.crear_repartidores()[0]
        self.assertEqual(Repartidor.from_dict(r.to_dict()), r)
        self.assertTrue(r.puede_cargar(30, 1.0))
        self.assertFalse(r.puede_cargar(31))
        with self.assertRaises(ValueError):
            Repartidor("X", 0, 0, 0, "#000")
        p = datos.crear_deposito()
        self.assertEqual(Punto.from_dict(p.to_dict()), p)


class PruebasRedCusco(unittest.TestCase):
    def setUp(self):
        self.red = datos.crear_red()

    def test_tamano_de_la_red(self):
        self.assertEqual(len(self.red), 16)
        self.assertEqual(len(self.red.calles()), 29)

    def test_bloquear_y_desbloquear(self):
        self.assertTrue(self.red.bloquear_calle("San Blas", "Zaguán del Cielo"))
        self.assertFalse(self.red.bloquear_calle("Zaguán del Cielo", "San Blas"))  # idempotente
        self.assertTrue(self.red.esta_bloqueada("San Blas", "Zaguán del Cielo"))
        self.assertTrue(self.red.desbloquear_calle("San Blas", "Zaguán del Cielo"))
        self.assertFalse(self.red.esta_bloqueada("San Blas", "Zaguán del Cielo"))

    def test_calle_inexistente(self):
        with self.assertRaises(KeyError):
            self.red.bloquear_calle("San Blas", "Wanchaq")

    def test_vecinos_validos_filtran_bloqueadas(self):
        antes = {v for v, _ in self.red.obtener_vecinos_validos("San Blas")}
        self.assertIn("Zaguán del Cielo", antes)
        self.red.bloquear_calle("San Blas", "Zaguán del Cielo")
        despues = {v for v, _ in self.red.obtener_vecinos_validos("San Blas")}
        self.assertEqual(despues, antes - {"Zaguán del Cielo"})
        # y del otro lado también
        self.assertNotIn("San Blas", {v for v, _ in self.red.obtener_vecinos_validos("Zaguán del Cielo")})

    def test_factor_de_trafico_multiplica_el_peso(self):
        base = dict(self.red.obtener_vecinos_validos("San Blas"))["Santa Ana"]
        self.red.establecer_trafico("San Blas", "Santa Ana", 3.0)
        self.assertAlmostEqual(dict(self.red.obtener_vecinos_validos("San Blas"))["Santa Ana"], 3 * base)
        dist = dict(self.red.obtener_vecinos_validos("San Blas", "distancia"))["Santa Ana"]
        self.assertAlmostEqual(dist, base)  # la distancia no cambia
        self.red.restablecer_trafico()
        self.assertAlmostEqual(dict(self.red.obtener_vecinos_validos("San Blas"))["Santa Ana"], base)
        with self.assertRaises(ValueError):
            self.red.establecer_trafico("San Blas", "Santa Ana", 0)

    def test_la_red_se_usa_directo_como_grafo(self):
        """Dijkstra y Backtracking aceptan la red sin parámetro 'cerradas'."""
        self.red.bloquear_calle("San Blas", "Zaguán del Cielo")
        self.red.bloquear_calle("Zaguán del Cielo", "Av. de la Cultura")
        costo, camino = voraz.dijkstra(self.red, "San Blas", "Wanchaq")
        cerradas = {datos.clave_calle(a, b) for a, b in datos.CALLES_CERRADAS_EJEMPLO}
        esperado, _ = voraz.dijkstra(datos.construir_grafo(datos.crear_red()), "San Blas", "Wanchaq", cerradas)
        self.assertAlmostEqual(costo, esperado)
        for a, b in zip(camino, camino[1:]):
            self.assertFalse(self.red.esta_bloqueada(a, b))
        rutas, _ = backtracking.todas_las_rutas(self.red, "San Blas", "Wanchaq")
        self.assertGreater(len(rutas), 0)
        self.assertAlmostEqual(rutas[0][0], costo, places=6)
        for _, c in rutas:
            self.assertEqual(self.red.costo_camino(c), self.red.costo_camino(c, "peso"))  # ninguna cruza bloqueadas
        c2, _, _ = backtracking.ruta_mas_corta_bt(self.red, "San Blas", "Wanchaq")
        self.assertAlmostEqual(c2, costo, places=6)

    def test_alcanzabilidad(self):
        self.red.bloquear_calle("San Sebastián", "Wanchaq")
        self.assertTrue(self.red.es_alcanzable("San Blas", "San Sebastián"))
        self.red.bloquear_calle("San Sebastián", "Av. Pardo")
        self.assertFalse(self.red.es_alcanzable("San Blas", "San Sebastián"))

    def test_costo_camino_rechaza_calles_bloqueadas(self):
        self.red.bloquear_calle("San Blas", "Santa Ana")
        with self.assertRaises(ValueError):
            self.red.costo_camino(["San Blas", "Santa Ana"])

    def test_ida_y_vuelta_y_copia_independiente(self):
        self.red.bloquear_calle("San Blas", "Santa Ana")
        self.red.establecer_trafico("Wanchaq", "San Sebastián", 1.8)
        igual = RedCusco.from_dict(self.red.to_dict())
        self.assertEqual(igual.to_dict(), self.red.to_dict())
        copia = self.red.copia()
        copia.desbloquear_todas()
        self.assertTrue(self.red.esta_bloqueada("San Blas", "Santa Ana"))

    def test_from_dict_detecta_referencias_rotas(self):
        d = self.red.to_dict()
        d["calles"].append(Calle("San Blas", "Narnia", 100.0).to_dict())
        with self.assertRaisesRegex(ValueError, "inexistente"):
            RedCusco.from_dict(d)
        d = self.red.to_dict()
        d["calles"].append(d["calles"][0])
        with self.assertRaisesRegex(ValueError, "ya existe"):
            RedCusco.from_dict(d)


class PruebasRedVialDinamica(unittest.TestCase):
    def setUp(self):
        self.red = datos.crear_red()
        self.esc = datos.Escenario(self.red, datos.generar_pedidos(12, 3, self.red),
                                   datos.crear_repartidores())

    def test_calles_bloqueadas_de_la_red_afectan_las_distancias(self):
        abierta = self.esc.crear_red_vial()
        self.red.bloquear_calle("San Blas", "Zaguán del Cielo")
        self.red.bloquear_calle("Zaguán del Cielo", "Av. de la Cultura")
        cerrada = self.esc.crear_red_vial()
        for a in self.esc.pedidos:
            for b in self.esc.pedidos:
                self.assertGreaterEqual(cerrada.distancia(a, b), abierta.distancia(a, b) - 1e-9)
        self.assertTrue(any(cerrada.distancia(a, b) > abierta.distancia(a, b) + 1e-6
                            for a in self.esc.pedidos for b in self.esc.pedidos))

    def test_equivale_a_pasar_cerradas_a_mano(self):
        self.red.bloquear_calle("San Blas", "Santa Ana")
        por_red = self.esc.crear_red_vial()
        a_mano = RedVial({datos.clave_calle("San Blas", "Santa Ana")}, datos.crear_red())
        a_mano.preparar(self.esc.puntos())
        for a in self.esc.pedidos:
            for b in self.esc.pedidos:
                self.assertAlmostEqual(por_red.distancia(a, b), a_mano.distancia(a, b))

    def test_el_trafico_encarece_y_la_metrica_distancia_lo_ignora(self):
        self.red.establecer_trafico("Plaza de Armas", "Av. El Sol", 4.0)
        con = self.esc.crear_red_vial()
        solo_dist = self.esc.crear_red_vial("distancia")
        libre = RedVial(red=datos.crear_red())
        libre.preparar(self.esc.puntos())
        for a in self.esc.pedidos:
            for b in self.esc.pedidos:
                self.assertGreaterEqual(con.distancia(a, b), libre.distancia(a, b) - 1e-9)
                self.assertAlmostEqual(solo_dist.distancia(a, b), libre.distancia(a, b))

    def test_pedido_con_calle_en_sentido_contrario(self):
        p = self.esc.pedidos[0]
        a, b = p.calle
        invertido = Pedido(**{**p.to_dict(), "calle": (b, a), "t": 1 - p.t, "id": "INV"})
        rv = RedVial(red=self.red)
        rv.preparar([p, invertido])
        self.assertAlmostEqual(rv.distancia(p, invertido), 0.0, places=6)

    def test_pedido_en_calle_inexistente_da_error_claro(self):
        malo = pedido(calle=("San Blas", "Wanchaq"), t=0.5)
        with self.assertRaisesRegex(ValueError, "no existe"):
            RedVial(red=self.red).preparar([malo])


class PruebasGeneracion(unittest.TestCase):
    def test_misma_semilla_mismos_datos(self):
        self.assertEqual(datos.generar_pedidos(20, 5), datos.generar_pedidos(20, 5))
        self.assertNotEqual(datos.generar_pedidos(20, 5), datos.generar_pedidos(20, 6))

    def test_pedidos_coherentes(self):
        red = datos.crear_red()
        ids = set()
        for p in datos.generar_pedidos(60, 11, red):
            self.assertNotIn(p.id, ids)
            ids.add(p.id)
            p.validar()
            self.assertTrue(red.existe_calle(*p.calle))
            self.assertEqual(p.origen, datos.DEPOSITO_NODO)
            self.assertEqual(p.destino, p.sector)
            self.assertIn(p.sector, red.nodos)
            self.assertGreater(p.volumen_m3, 0)
            self.assertGreaterEqual(p.ventana_fin - p.ventana_inicio, 15)

    def test_ventana_alcanzable_desde_el_deposito(self):
        """Ningún pedido vence antes de poder llegar a él con el tráfico actual."""
        red = datos.crear_red()
        datos.aplicar_trafico_aleatorio(red, 3)
        esc = datos.Escenario(red, datos.generar_pedidos(40, 8, red), datos.crear_repartidores())
        rv = RedVial(red=red, metrica="tiempo")
        rv.preparar(esc.puntos())
        for p in esc.pedidos:
            minutos = rv.distancia(esc.deposito, p) / 60
            self.assertGreaterEqual(p.ventana_fin, minutos - 1e-9)

    def test_urgentes_tienen_plazos_mas_cortos(self):
        ps = datos.generar_pedidos(200, 1)
        media = lambda u: (lambda xs: sum(xs) / len(xs))(
            [p.ventana_fin - p.ventana_inicio for p in ps if p.urgencia == u])
        self.assertLess(media(5), media(1))


class PruebasArchivos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.red = datos.crear_red()
        self.red.bloquear_calle("San Blas", "Santa Ana")
        self.red.establecer_trafico("Wanchaq", "San Sebastián", 1.75)
        self.pedidos = datos.generar_pedidos(15, 9, self.red)

    def test_red_json_y_csv(self):
        for nombre in ("red_cusco.json", "red_cusco.csv"):
            with self.subTest(nombre=nombre):
                escritos = datos.guardar_red(self.red, self.dir / nombre)
                self.assertTrue(all(p.exists() for p in escritos))
                leida = datos.cargar_red(self.dir / nombre)
                self.assertEqual(leida.to_dict(), self.red.to_dict())
                self.assertTrue(leida.esta_bloqueada("San Blas", "Santa Ana"))

    def test_pedidos_json_y_csv(self):
        for nombre in ("pedidos.json", "pedidos.csv"):
            with self.subTest(nombre=nombre):
                datos.guardar_pedidos(self.pedidos, self.dir / nombre)
                self.assertEqual(datos.cargar_pedidos(self.dir / nombre, self.red), self.pedidos)

    def test_json_con_acentos_legibles(self):
        datos.guardar_red(self.red, self.dir / "r.json")
        self.assertIn("Zaguán del Cielo", (self.dir / "r.json").read_text(encoding="utf-8"))

    def test_pedidos_invalidos_dan_error_con_registro(self):
        malo = [p.to_dict() for p in self.pedidos[:3]]
        malo[1]["peso"] = -4
        (self.dir / "p.json").write_text(json.dumps(malo), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "registro 2.*peso"):
            datos.cargar_pedidos(self.dir / "p.json")

    def test_ids_repetidos(self):
        d = [self.pedidos[0].to_dict(), self.pedidos[0].to_dict()]
        (self.dir / "p.json").write_text(json.dumps(d), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "repetido"):
            datos.cargar_pedidos(self.dir / "p.json")

    def test_pedido_en_calle_inexistente_con_red(self):
        d = self.pedidos[0].to_dict()
        d["calle"] = ["San Blas", "Wanchaq"]
        (self.dir / "p.json").write_text(json.dumps([d]), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no existe"):
            datos.cargar_pedidos(self.dir / "p.json", self.red)

    def test_pedido_solo_con_coordenadas_se_proyecta_en_la_calle(self):
        (self.dir / "p.json").write_text(json.dumps([
            {"id": "X1", "x": 20.5, "y": 22.0, "urgencia": 2, "peso": 3, "valor": 30}]),
            encoding="utf-8")
        p = datos.cargar_pedidos(self.dir / "p.json", self.red)[0]
        self.assertTrue(self.red.existe_calle(*p.calle))
        self.assertIn(p.sector, self.red.nodos)
        self.assertEqual(p.destino, p.sector)

    def test_red_invalida(self):
        d = self.red.to_dict()
        d["calles"][0]["distancia_m"] = -5
        (self.dir / "r.json").write_text(json.dumps(d), encoding="utf-8")
        with self.assertRaises(ValueError):
            datos.cargar_red(self.dir / "r.json")

    def test_formato_no_soportado(self):
        with self.assertRaises(ValueError):
            datos.guardar_pedidos(self.pedidos, self.dir / "p.xml")

    def test_escenario_ida_y_vuelta(self):
        for formato in ("json", "csv"):
            with self.subTest(formato=formato):
                esc = datos.Escenario(self.red, self.pedidos, datos.crear_repartidores())
                d = self.dir / formato
                esc.guardar(d, formato)
                nuevo = datos.Escenario.cargar(d / f"red_cusco.{formato}", d / f"pedidos.{formato}",
                                               d / f"repartidores.{formato}")
                self.assertEqual(nuevo.pedidos, esc.pedidos)
                self.assertEqual(nuevo.repartidores, esc.repartidores)
                self.assertEqual(nuevo.red.to_dict(), esc.red.to_dict())
                self.assertEqual(nuevo.deposito, esc.deposito)


class PruebasConsultas(unittest.TestCase):
    def setUp(self):
        self.esc = datos.Escenario.sintetico(30, 7)

    def test_cuadrantes_particionan_los_pedidos(self):
        total = []
        for c in datos.CUADRANTES:
            total += self.esc.obtener_pedidos_por_zona(c)
        self.assertEqual(sorted(p.id for p in total), sorted(p.id for p in self.esc.pedidos))
        with self.assertRaises(ValueError):
            self.esc.obtener_pedidos_por_zona("CENTRO")

    def test_zona_por_caja_y_cuadrante_son_coherentes(self):
        x0, y0, x1, y1 = self.esc.red.limites()
        xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
        por_caja = self.esc.obtener_pedidos_por_zona((x0, ym, xm, y1))
        por_nombre = self.esc.obtener_pedidos_por_zona("NO")
        self.assertEqual({p.id for p in por_nombre} - {p.id for p in por_caja}, set())

    def test_ordenables_excluye_entregados(self):
        self.assertEqual(len(self.esc.obtener_pedidos_ordenables()), 30)
        self.esc.pedidos[0].estado = "ENTREGADO"
        self.assertEqual(len(self.esc.obtener_pedidos_ordenables()), 29)

    def test_ordenables_excluye_inalcanzables(self):
        """Red A - B - C con el depósito en A: al bloquear A-B, lo que hay en B-C queda aislado."""
        red = RedCusco()
        for nombre, x in (("A", 0), ("B", 10), ("C", 20)):
            red.agregar_nodo(nombre, x, 0)
        red.agregar_calle(Calle("A", "B", 1000.0))
        red.agregar_calle(Calle("B", "C", 1000.0))
        cerca = pedido(id="AB", x=5, y=0, calle=("A", "B"), t=0.5, sector="A")
        lejos = pedido(id="BC", x=15, y=0, calle=("B", "C"), t=0.5, sector="B")
        esc = datos.Escenario(red, [cerca, lejos], [], datos.crear_deposito("A", red))
        self.assertEqual({p.id for p in esc.obtener_pedidos_ordenables()}, {"AB", "BC"})
        red.bloquear_calle("A", "B")
        # AB sigue accesible desde A (calle bloqueada pero con su extremo alcanzable); BC no
        self.assertEqual({p.id for p in esc.obtener_pedidos_ordenables()}, {"AB"})

    def test_ordenables_con_criterio(self):
        ps = self.esc.obtener_pedidos_ordenables("urgencia")
        self.assertEqual([p.urgencia for p in ps], sorted((p.urgencia for p in ps), reverse=True))
        ps = self.esc.obtener_pedidos_ordenables("ventana_fin")
        self.assertEqual([p.ventana_fin for p in ps], sorted(p.ventana_fin for p in ps))
        ps = self.esc.obtener_pedidos_ordenables("peso", inverso=True)
        self.assertEqual([p.peso for p in ps], sorted((p.peso for p in ps), reverse=True))
        with self.assertRaises(ValueError):
            self.esc.obtener_pedidos_ordenables("color")

    def test_agregar_y_quitar(self):
        nuevo = self.esc.siguiente_id()
        self.assertEqual(nuevo, "P31")
        p = datos.generar_pedidos(1, 99)[0]
        p.id = nuevo
        self.esc.agregar_pedido(p)
        with self.assertRaises(ValueError):
            self.esc.agregar_pedido(p)
        self.assertTrue(self.esc.quitar_pedido(nuevo))
        self.assertFalse(self.esc.quitar_pedido(nuevo))

    def test_algoritmos_con_el_escenario(self):
        """Flujo completo: escenario -> red vial -> algoritmos que usan 'dist'."""
        rv = self.esc.crear_red_vial()
        rep = self.esc.repartidores[0]
        ps = self.esc.obtener_pedidos_ordenables("urgencia")[:7]
        orden, total = voraz.ruta_vecino_mas_cercano(rep, ps, rv.distancia)
        self.assertEqual(len(orden), 7)
        self.assertTrue(math.isfinite(total))
        asignacion, pendientes = voraz.asignar_mas_cercano(self.esc.pedidos, self.esc.repartidores,
                                                           rv.distancia)
        self.assertEqual(sum(len(v) for v in asignacion.values()) + len(pendientes), 30)


if __name__ == "__main__":
    unittest.main()
