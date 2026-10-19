"""Interfaz gráfica del Sistema de Gestión de Rutas Óptimas en Cusco.

Tecnologías: ``customtkinter`` (ventana y controles), ``tkintermapview`` (mapa interactivo
con marcadores, rutas y polígonos) y ``matplotlib`` embebido (gráfica Tiempo vs N).

Principios de diseño
--------------------
* La interfaz NUNCA se congela: todo algoritmo de búsqueda/optimización corre en un hilo
  (``threading.Thread``) y avisa por una ``queue.Queue`` que el hilo principal consulta cada
  80 ms con ``after``. Los hilos no tocan ningún widget (Tk no es seguro entre hilos); solo
  calculan y devuelven resultados. Una tarea larga se puede cancelar con ``threading.Event``.
* El estado vive en un ``datos.Escenario`` (red + pedidos + repartidores + depósito). Los
  algoritmos trabajan en el plano local (x, y); ``traductor`` convierte a (lat, lon) solo al
  dibujar sobre el mapa.
* Colores de ruta: verde = Voraz, azul = Backtracking, naranja = Divide y Vencerás,
  morado = Programación Dinámica; las calles bloqueadas se dibujan en rojo.
* Calles reales: si existe la caché de OpenStreetMap (o se descarga con el botón «Calles
  reales»), cada calle y cada ruta se dibujan siguiendo el trazado real de las vías
  (``calles_reales``); sin ella se dibujan como rectas entre los nodos.
"""

from __future__ import annotations

import math
import os
import queue
import threading
import time
import traceback
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
import tkintermapview
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from PIL import Image, ImageDraw, ImageFont, ImageTk

from . import (backtracking, benchmark, calles_reales, datos, divide_venceras, exportar,
               experimentos, ordenacion, programacion_dinamica, traductor, voraz)
from .modelos import Pedido
from .red import RedVial

# --------------------------------------------------------------------------- constantes
TITULO = "Sistema de Gestión de Rutas Óptimas en Cusco"
COLOR_VORAZ = "#22a559"        # verde
COLOR_BT = "#1f6feb"           # azul
COLOR_DYV = "#f08c00"          # naranja
COLOR_PD = "#8e44ad"           # morado
COLOR_BLOQUEADA = "#e11d2e"    # rojo
COLOR_CALLE = "#8b93a1"
COLOR_PEDIDO = "#2c3e50"
COLOR_SIN_USO = "#b0b7c3"
COLOR_RESALTE = "#ffc107"
COLORES_ZONAS = ["#3b82f6", "#a855f7", "#14b8a6", "#ec4899", "#84cc16", "#06b6d4",
                 "#eab308", "#6366f1", "#f43f5e", "#10b981", "#8b5cf6", "#0ea5e9"]
TODOS = "Todos los pedidos"
MODOS = ("Navegar", "Bloquear / abrir calle", "Agregar pedido")
TILES = {
    "OpenStreetMap": "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
    "CartoDB claro": "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    "Satélite (Esri)": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
                       "MapServer/tile/{z}/{y}/{x}",
}
ORDENES = {
    "Urgencia (mayor primero)": lambda c: (lambda p: p.urgencia, True),
    "Valor S/ (mayor primero)": lambda c: (lambda p: p.valor, True),
    "Peso kg (menor primero)": lambda c: (lambda p: p.peso, False),
    "Valor por kg (mayor primero)": lambda c: (lambda p: p.valor_por_kg, True),
    "Ventana de tiempo (vence antes)": lambda c: (lambda p: p.ventana_fin, False),
    "Distancia al depósito (menor primero)": lambda c: (c.dist_deposito, False),
    "ID": lambda c: (lambda p: p.id, False),
    "Cliente (A-Z)": lambda c: (lambda p: p.cliente.casefold(), False),
}
ALGORITMOS_ORDEN = {"MergeSort": ordenacion.merge_sort, "QuickSort": ordenacion.quick_sort,
                    "HeapSort": ordenacion.heap_sort}
BUSQUEDAS = ("ID - búsqueda binaria", "ID - tabla hash", "Cliente - tabla hash",
             "Cliente contiene...", "Sector (índice)")

_ICONOS: dict = {}


# --------------------------------------------------------------------------- utilidades
def km(metros: float) -> str:
    """Las distancias de la red vial vienen en metros."""
    return f"{metros / 1000:.2f} km"


def _fuente_pil(tam: int):
    try:
        return ImageFont.load_default(size=tam)
    except Exception:  # pragma: no cover - Pillow antiguo
        return ImageFont.load_default()


def crear_icono(forma: str, color: str, tam: int = 22, texto: str | None = None,
                halo: str | None = None, borde: str = "#ffffff") -> ImageTk.PhotoImage:
    """Icono PNG dibujado con PIL (con suavizado) para usarlo como marcador del mapa.

    forma: "circulo" | "triangulo" | "cuadrado" | "rombo" | "equis". 'texto' (por ejemplo el
    número de parada) se escribe en el centro; 'halo' dibuja un anillo de resalte.
    Los iconos se guardan en caché: Tk pierde las imágenes si no se conserva la referencia.
    """
    clave = (forma, color, tam, texto, halo, borde)
    if clave in _ICONOS:
        return _ICONOS[clave]
    s, margen = 4, 4
    lado = tam + 2 * margen
    img = Image.new("RGBA", (lado * s, lado * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c0, c1 = margen * s, (margen + tam) * s
    centro = lado * s / 2
    if halo:
        d.ellipse((c0 - 3 * s, c0 - 3 * s, c1 + 3 * s, c1 + 3 * s), outline=halo, width=3 * s)
    grosor = max(2, tam // 9) * s
    if forma == "circulo":
        d.ellipse((c0, c0, c1, c1), fill=color, outline=borde, width=grosor)
    elif forma == "triangulo":
        d.polygon([(centro, c0), (c1, c1), (c0, c1)], fill=color, outline=borde, width=grosor)
    elif forma == "cuadrado":
        d.rectangle((c0, c0, c1, c1), fill=color, outline=borde, width=grosor)
    elif forma == "rombo":
        d.polygon([(centro, c0), (c1, centro), (centro, c1), (c0, centro)],
                  fill=color, outline=borde, width=grosor)
    elif forma == "equis":
        d.ellipse((c0, c0, c1, c1), fill=color, outline=borde, width=grosor)
        p = tam * s * 0.3
        d.line((centro - p, centro - p, centro + p, centro + p), fill="white", width=2 * s)
        d.line((centro - p, centro + p, centro + p, centro - p), fill="white", width=2 * s)
    if texto:
        fuente = _fuente_pil(max(9, int(tam * 0.55)) * s)
        d.text((centro, centro + (tam * s * 0.08 if forma == "triangulo" else 0)), texto,
               fill="white", font=fuente, anchor="mm")
    img = img.resize((lado, lado), Image.LANCZOS)
    foto = ImageTk.PhotoImage(img)
    _ICONOS[clave] = foto
    return foto


def _a_entero(texto, defecto: int, minimo: int | None = None, maximo: int | None = None) -> int:
    try:
        valor = int(float(str(texto).strip().replace(",", ".")))
    except (TypeError, ValueError):
        valor = defecto
    if minimo is not None:
        valor = max(minimo, valor)
    if maximo is not None:
        valor = min(maximo, valor)
    return valor


def _a_real(texto, defecto: float, minimo: float | None = None, maximo: float | None = None) -> float:
    try:
        valor = float(str(texto).strip().replace(",", "."))
    except (TypeError, ValueError):
        valor = defecto
    if minimo is not None:
        valor = max(minimo, valor)
    if maximo is not None:
        valor = min(maximo, valor)
    return valor


def color_de_curva(nombre: str) -> str:
    """Color estable de cada algoritmo en las gráficas (coincide con los del mapa)."""
    n = nombre.lower()
    if "voraz" in n:
        return COLOR_VORAZ
    if "divide" in n:
        return COLOR_DYV
    if "backtracking" in n:
        return COLOR_BT
    if "memo" in n:
        return "#d946ef"
    if "din" in n or "held" in n:
        return COLOR_PD
    if "merge" in n:
        return "#0ea5e9"
    if "quick" in n:
        return "#f43f5e"
    return "#64748b"


# ======================================================================================
# Aplicación
# ======================================================================================
class App(ctk.CTk):
    """Ventana principal: mapa a la izquierda, pestañas por algoritmo a la derecha y,
    abajo, la bitácora con barra de progreso y botón de cancelar."""

    # ------------------------------------------------------------------ inicio
    def __init__(self, escenario: datos.Escenario | None = None, calles_reales_auto: bool = True) -> None:
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title(TITULO)
        self.geometry("1500x900")
        self.minsize(1200, 720)

        self.esc = escenario or datos.Escenario.sintetico(18, 7)
        self.calles_reales_auto = calles_reales_auto
        self.red_vial: RedVial | None = None
        self.modo = MODOS[0]
        self.asignacion: dict[str, list] = {}
        self.colores_pedido: dict[str, str] = {}
        self.resaltados: set[str] = set()
        self.ultima_seleccion: list = []
        self.rutas_bt: list = []
        self.curvas = None
        self.filas_bench: list = []
        # últimas rutas calculadas (para exportar o abrir en Google Maps)
        self.ultimas_rutas: list[exportar.RutaExportable] = []
        self._descargando_calles = False
        self._cola_calles: queue.Queue | None = None
        # lo que se ve sobre el mapa además de calles/nodos/pedidos
        self.vista = {"rutas": [], "zonas": [], "extras": []}
        self.capas: dict[str, list] = {k: [] for k in
                                       ("zonas", "calles", "rutas", "nodos", "pedidos", "base", "extras")}

        # estado de las tareas en segundo plano
        self._cancelar = threading.Event()
        self._cola: queue.Queue | None = None
        self._ocupado = False
        self._id_banner = None

        self.report_callback_exception = self._error_tk
        self._construir()
        self.after(150, self._inicializar_mapa)
        self.log("Listo. Genera o carga pedidos, bloquea calles con clic en el mapa y prueba "
                 "cada pestaña. Los algoritmos corren en segundo plano.")

    def _error_tk(self, tipo, valor, tb) -> None:
        detalle = "".join(traceback.format_exception(tipo, valor, tb))
        self.log("ERROR inesperado:\n" + detalle)
        self._alerta(f"Error: {valor}", "error")

    # ------------------------------------------------------------------ utilidades UI
    def log(self, texto: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", texto + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _alerta(self, mensaje: str, tipo: str = "aviso", ms: int = 7000) -> None:
        """Banner limpio sobre el mapa (sin ventanas emergentes ni excepciones)."""
        colores = {"error": "#b91c1c", "aviso": "#b45309", "ok": "#15803d"}
        self.banner.configure(text="  " + mensaje + "  ", fg_color=colores.get(tipo, "#b45309"))
        self.banner.place(relx=0.5, y=12, anchor="n")
        self.banner.lift()
        if self._id_banner is not None:
            self.after_cancel(self._id_banner)
        self._id_banner = self.after(ms, self.banner.place_forget)

    def _etq(self, padre, texto, **kw):
        kw.setdefault("wraplength", 480)
        return ctk.CTkLabel(padre, text=texto, anchor="w", justify="left", **kw)

    def _btn(self, padre, texto, comando, color=None, ancho=None, **kw):
        if color:
            kw["fg_color"] = color
            kw["hover_color"] = color
        if ancho:
            kw["width"] = ancho
        return ctk.CTkButton(padre, text=texto, command=comando, height=30, **kw)

    def _fila(self, padre, pady=3):
        f = ctk.CTkFrame(padre, fg_color="transparent")
        f.pack(fill="x", pady=pady)
        return f

    def _seccion(self, padre, titulo):
        ctk.CTkLabel(padre, text=titulo, anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(10, 2))

    def _entrada(self, padre, valor, ancho=70):
        e = ctk.CTkEntry(padre, width=ancho)
        e.insert(0, str(valor))
        return e

    # ------------------------------------------------------------------ construcción
    def _construir(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---- cabecera
        cab = ctk.CTkFrame(self, corner_radius=0)
        cab.grid(row=0, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(cab, text="  " + TITULO, font=ctk.CTkFont(size=18, weight="bold")
                     ).pack(side="left", padx=8, pady=8)
        self.opt_apariencia = ctk.CTkOptionMenu(cab, values=["Claro", "Oscuro"], width=90,
                                                command=self._cambiar_apariencia)
        self.opt_apariencia.pack(side="right", padx=8)
        self.opt_tile = ctk.CTkOptionMenu(cab, values=list(TILES), width=130,
                                          command=self._cambiar_tile)
        self.opt_tile.pack(side="right", padx=4)
        ctk.CTkLabel(cab, text="Mapa:").pack(side="right")
        self._btn(cab, "Centrar", self._centrar_mapa, ancho=70).pack(side="right", padx=8)
        self.btn_calles = self._btn(cab, "Calles reales (OSM)", self._boton_calles_reales,
                                    color="#0f766e", ancho=150)
        self.btn_calles.pack(side="right", padx=4)
        self.lbl_calles = ctk.CTkLabel(cab, text="Calles: rectas", text_color="#b45309")
        self.lbl_calles.pack(side="right", padx=4)
        self.seg_modo = ctk.CTkSegmentedButton(cab, values=list(MODOS), command=self._cambiar_modo)
        self.seg_modo.set(MODOS[0])
        self.seg_modo.pack(side="right", padx=12)
        ctk.CTkLabel(cab, text="Clic en el mapa:").pack(side="right")

        # ---- mapa + leyenda
        izq = ctk.CTkFrame(self, corner_radius=0)
        izq.grid(row=1, column=0, sticky="nsew", padx=(6, 3), pady=6)
        izq.grid_rowconfigure(0, weight=1)
        izq.grid_columnconfigure(0, weight=1)
        self.mapa = tkintermapview.TkinterMapView(izq, corner_radius=6)
        self.mapa.grid(row=0, column=0, sticky="nsew")
        self.mapa.add_left_click_map_command(self._clic_mapa)
        self.mapa.add_right_click_menu_command("Agregar pedido aquí",
                                               lambda c: self._clic_pedido(*c), pass_coords=True)
        self.mapa.add_right_click_menu_command("Bloquear / abrir calle más cercana",
                                               lambda c: self._clic_calle(*c), pass_coords=True)
        self.banner = ctk.CTkLabel(izq, text="", corner_radius=8, text_color="white",
                                   font=ctk.CTkFont(size=14, weight="bold"))
        self._construir_leyenda(izq)

        # ---- pestañas
        self.tabs = ctk.CTkTabview(self, width=580)
        self.tabs.grid(row=1, column=1, sticky="nsew", padx=(3, 6), pady=6)
        self.grid_columnconfigure(1, weight=0, minsize=590)
        for nombre in ("Pedidos", "Voraz", "Divide y Vencerás", "Mochila (PD)",
                       "Backtracking", "Análisis"):
            self.tabs.add(nombre)
        self._tab_pedidos(self.tabs.tab("Pedidos"))
        self._tab_voraz(self.tabs.tab("Voraz"))
        self._tab_dyv(self.tabs.tab("Divide y Vencerás"))
        self._tab_mochila(self.tabs.tab("Mochila (PD)"))
        self._tab_backtracking(self.tabs.tab("Backtracking"))
        self._tab_analisis(self.tabs.tab("Análisis"))

        # ---- pie: bitácora y progreso
        pie = ctk.CTkFrame(self, corner_radius=0)
        pie.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
        pie.grid_columnconfigure(0, weight=1)
        self.txt_log = ctk.CTkTextbox(pie, height=140, font=ctk.CTkFont(family="Consolas", size=12))
        self.txt_log.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self.txt_log.configure(state="disabled")
        lado = ctk.CTkFrame(pie, fg_color="transparent")
        lado.grid(row=0, column=1, sticky="ns", padx=6, pady=6)
        self.lbl_estado = ctk.CTkLabel(lado, text="Inactivo", width=230, anchor="w")
        self.lbl_estado.pack(anchor="w")
        self.barra = ctk.CTkProgressBar(lado, width=230)
        self.barra.set(0)
        self.barra.pack(pady=6)
        self.btn_cancelar = self._btn(lado, "Cancelar tarea", self._cancelar_tarea, color="#b91c1c")
        self.btn_cancelar.pack(fill="x")
        self.btn_cancelar.configure(state="disabled")
        self._btn(lado, "Limpiar mapa", self._limpiar_vistas_y_redibujar, color="#64748b"
                  ).pack(fill="x", pady=(6, 0))
        fila = ctk.CTkFrame(lado, fg_color="transparent")
        fila.pack(fill="x", pady=(6, 0))
        self._btn(fila, "Exportar rutas", self._exportar_rutas, color="#0f766e", ancho=112).pack(side="left")
        self._btn(fila, "Google Maps", self._abrir_google_maps, color="#0f766e", ancho=112
                  ).pack(side="left", padx=(6, 0))
        self._aplicar_estilo_tabla()

    def _construir_leyenda(self, padre) -> None:
        f = ctk.CTkFrame(padre, fg_color="transparent")
        f.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        items = [("━ Voraz", COLOR_VORAZ), ("━ Backtracking", COLOR_BT),
                 ("━ Divide y Vencerás", COLOR_DYV), ("━ Prog. Dinámica", COLOR_PD),
                 ("━ Calle bloqueada", COLOR_BLOQUEADA), ("━ Calle abierta", COLOR_CALLE),
                 ("▲ Repartidor (origen)", "#334155"), ("● Pedido (tamaño = urgencia)", COLOR_PEDIDO),
                 ("◆ Nodo intermedio", "#475569"), ("■ Depósito", "#000000"),
                 ("▭ Subzona", "#3b82f6")]
        for i, (texto, color) in enumerate(items):
            ctk.CTkLabel(f, text=texto, text_color=color, font=ctk.CTkFont(size=12, weight="bold")
                         ).grid(row=i // 6, column=i % 6, padx=8, sticky="w")

    # ------------------------------------------------------------------ pestaña Pedidos
    def _tab_pedidos(self, t) -> None:
        self._seccion(t, "Datos")
        f = self._fila(t)
        ctk.CTkLabel(f, text="Cantidad").pack(side="left")
        self.e_cantidad = self._entrada(f, 18, 55)
        self.e_cantidad.pack(side="left", padx=4)
        ctk.CTkLabel(f, text="Semilla").pack(side="left", padx=(6, 0))
        self.e_semilla = self._entrada(f, 7, 55)
        self.e_semilla.pack(side="left", padx=4)
        self._btn(f, "Generar aleatorios", self._generar).pack(side="left", padx=6)
        f = self._fila(t)
        self._btn(f, "Cargar escenario...", self._cargar_escenario, ancho=150).pack(side="left")
        self._btn(f, "Guardar escenario...", self._guardar_escenario, ancho=150).pack(side="left", padx=6)
        self.opt_formato = ctk.CTkOptionMenu(f, values=["json", "csv"], width=70)
        self.opt_formato.pack(side="left")

        self._seccion(t, "Pedido nuevo (modo «Agregar pedido»: clic en el mapa)")
        f = self._fila(t)
        ctk.CTkLabel(f, text="Urgencia").pack(side="left")
        self.opt_urg = ctk.CTkOptionMenu(f, values=["1", "2", "3", "4", "5"], width=60)
        self.opt_urg.set("3")
        self.opt_urg.pack(side="left", padx=4)
        ctk.CTkLabel(f, text="Peso kg").pack(side="left", padx=(6, 0))
        self.e_peso = self._entrada(f, 5, 50)
        self.e_peso.pack(side="left", padx=4)
        ctk.CTkLabel(f, text="Valor S/").pack(side="left", padx=(6, 0))
        self.e_valor = self._entrada(f, 50, 55)
        self.e_valor.pack(side="left", padx=4)
        self.sw_ids = ctk.CTkSwitch(t, text="Mostrar IDs y nombres en el mapa", command=self._dibujar_todo)
        self.sw_ids.select()
        self.sw_ids.pack(anchor="w", pady=4)
        self.sw_largo_real = ctk.CTkSwitch(t, text="Usar el largo real de las calles (OSM) en las distancias",
                                           command=self._cambiar_largo_real)
        self.sw_largo_real.select()
        self.sw_largo_real.pack(anchor="w", pady=(0, 4))

        self._seccion(t, "Ordenar (MergeSort / QuickSort / HeapSort)")
        f = self._fila(t)
        self.opt_criterio = ctk.CTkOptionMenu(f, values=list(ORDENES), width=250)
        self.opt_criterio.pack(side="left")
        self.opt_alg_orden = ctk.CTkOptionMenu(f, values=list(ALGORITMOS_ORDEN), width=110)
        self.opt_alg_orden.pack(side="left", padx=6)
        self._btn(f, "Ordenar", self._ordenar, ancho=80).pack(side="left")

        self._seccion(t, "Buscar")
        f = self._fila(t)
        self.e_buscar = self._entrada(f, "", 110)
        self.e_buscar.pack(side="left")
        self.opt_busqueda = ctk.CTkOptionMenu(f, values=list(BUSQUEDAS), width=190)
        self.opt_busqueda.pack(side="left", padx=6)
        self._btn(f, "Buscar", self._buscar, ancho=70).pack(side="left")
        f = self._fila(t)
        self.opt_sector = ctk.CTkOptionMenu(f, values=sorted(datos.NODOS), width=190)
        self.opt_sector.pack(side="left")
        self._btn(f, "Quitar resaltado", self._quitar_resaltado, color="#64748b", ancho=130
                  ).pack(side="left", padx=6)
        self._btn(f, "Eliminar seleccionados", self._eliminar_seleccion, color="#b91c1c", ancho=160
                  ).pack(side="left")

        cols = ("id", "cliente", "sector", "urg", "peso", "valor", "dist")
        marco = ctk.CTkFrame(t, fg_color="transparent")
        marco.pack(fill="both", expand=True, pady=(8, 0))
        self.tabla = ttk.Treeview(marco, columns=cols, show="headings", height=9, selectmode="extended")
        for c, a, titulo in zip(cols, (48, 85, 135, 38, 40, 50, 70),
                                ("ID", "Cliente", "Sector", "Urg", "Kg", "S/", "Dist. km")):
            self.tabla.heading(c, text=titulo)
            self.tabla.column(c, width=a, anchor="center")
        sb = ttk.Scrollbar(marco, command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=sb.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tabla.bind("<<TreeviewSelect>>", self._al_elegir_fila)

    # ------------------------------------------------------------------ pestaña Voraz
    def _tab_voraz(self, t) -> None:
        self._etq(t, "Enfoque voraz (Greedy): cada pedido se asigna al repartidor más cercano "
                     "(por calles) con capacidad libre, los más urgentes primero; después cada "
                     "repartidor visita siempre el pedido más próximo a su posición actual. "
                     "Decisiones locales que no se reconsideran: rápido, sin garantía de óptimo."
                  ).pack(fill="x", pady=4)
        self._btn(t, "1) Asignar pedidos al repartidor más cercano", self._asignar_voraz).pack(anchor="w", pady=6)
        f = self._fila(t)
        self.opt_rep_voraz = ctk.CTkOptionMenu(f, values=["-"], width=170)
        self.opt_rep_voraz.pack(side="left")
        self._btn(f, "2) Ruta por vecino más cercano", self._ruta_voraz, color=COLOR_VORAZ
                  ).pack(side="left", padx=8)
        self._btn(t, "Ruta de todos los repartidores", self._rutas_voraz_todos, color=COLOR_VORAZ
                  ).pack(anchor="w", pady=6)

    # ------------------------------------------------------------------ pestaña Divide y Vencerás
    def _tab_dyv(self, t) -> None:
        self._etq(t, "Divide y Vencerás: el mapa se parte por coordenadas (x, y) en cuadrantes "
                     "(quadtree). DIVIDIR en 4 hasta que cada zona tenga pocos pedidos; VENCER "
                     "resolviendo cada zona por separado (óptimo si es chica); COMBINAR: las "
                     "subrutas de zonas adyacentes se empalman por sus extremos y un 2-opt "
                     "repara las costuras donde la ruta cruza la frontera de sector."
                  ).pack(fill="x", pady=4)
        f = self._fila(t)
        ctk.CTkLabel(f, text="Pedidos máx. por zona:").pack(side="left")
        self.lbl_max_zona = ctk.CTkLabel(f, text="6", width=24)
        self.sl_max_zona = ctk.CTkSlider(f, from_=2, to=12, number_of_steps=10, width=170,
                                         command=lambda v: self.lbl_max_zona.configure(text=str(int(v))))
        self.sl_max_zona.set(6)
        self.sl_max_zona.pack(side="left", padx=6)
        self.lbl_max_zona.pack(side="left")
        f = self._fila(t)
        ctk.CTkLabel(f, text="Profundidad máx.:").pack(side="left")
        self.lbl_nivel = ctk.CTkLabel(f, text="3", width=24)
        self.sl_nivel = ctk.CTkSlider(f, from_=1, to=5, number_of_steps=4, width=170,
                                      command=lambda v: self.lbl_nivel.configure(text=str(int(v))))
        self.sl_nivel.set(3)
        self.sl_nivel.pack(side="left", padx=(30, 6))
        self.lbl_nivel.pack(side="left")
        f = self._fila(t)
        ctk.CTkLabel(f, text="Sale desde:").pack(side="left")
        self.opt_rep_dyv = ctk.CTkOptionMenu(f, values=["-"], width=170)
        self.opt_rep_dyv.pack(side="left", padx=6)
        self._btn(t, "Dividir, vencer y combinar (ruta naranja)", self._ejecutar_dyv, color=COLOR_DYV
                  ).pack(anchor="w", pady=6)
        self._btn(t, "Solo mostrar las subzonas", self._solo_subzonas, color="#64748b").pack(anchor="w")
        self._seccion(t, "Reparto de la ciudad entre repartidores (k zonas)")
        f = self._fila(t)
        ctk.CTkLabel(f, text="Zonas k:").pack(side="left")
        self.opt_k = ctk.CTkOptionMenu(f, values=["2", "3"], width=60)
        self.opt_k.set("3")
        self.opt_k.pack(side="left", padx=6)
        self._btn(f, "Dividir entre repartidores", self._repartir_zonas).pack(side="left")

    # ------------------------------------------------------------------ pestaña Mochila
    def _tab_mochila(self, t) -> None:
        self._etq(t, "Programación Dinámica: elegir qué pedidos carga el vehículo maximizando el "
                     "valor sin pasar su capacidad (mochila 0/1). La solución se reconstruye "
                     "hacia atrás sobre la tabla y devuelve los IDs exactos. Se compara con "
                     "la versión voraz."
                  ).pack(fill="x", pady=4)
        f = self._fila(t)
        ctk.CTkLabel(f, text="Pedidos:").pack(side="left")
        self.opt_conjunto = ctk.CTkOptionMenu(f, values=[TODOS], width=190)
        self.opt_conjunto.pack(side="left", padx=6)
        f = self._fila(t)
        ctk.CTkLabel(f, text="Capacidad kg").pack(side="left")
        self.e_cap_kg = self._entrada(f, 30, 55)
        self.e_cap_kg.pack(side="left", padx=4)
        ctk.CTkLabel(f, text="m³").pack(side="left", padx=(6, 0))
        self.e_cap_m3 = self._entrada(f, 3.0, 55)
        self.e_cap_m3.pack(side="left", padx=4)
        ctk.CTkLabel(f, text="Maximizar").pack(side="left", padx=(6, 0))
        self.opt_objetivo = ctk.CTkOptionMenu(f, values=["Valor (S/)", "Prioridad"], width=110)
        self.opt_objetivo.pack(side="left", padx=4)
        for texto, cmd, col in (("PD por tabulación (kg)", lambda: self._mochila("tab"), COLOR_PD),
                                ("PD con memoización (kg)", lambda: self._mochila("memo"), COLOR_PD),
                                ("PD con peso y volumen (kg + m³)", lambda: self._mochila("vol"), COLOR_PD),
                                ("Voraz valor/peso (para comparar)", lambda: self._mochila("voraz"), COLOR_VORAZ)):
            self._btn(t, texto, cmd, color=col).pack(anchor="w", pady=3)
        self._btn(t, "Ruta óptima de lo cargado (Held-Karp)", self._ruta_held_karp, color=COLOR_PD
                  ).pack(anchor="w", pady=(10, 3))
        f = self._fila(t)
        ctk.CTkLabel(f, text="Sale desde:").pack(side="left")
        self.opt_rep_mochila = ctk.CTkOptionMenu(f, values=["-"], width=170)
        self.opt_rep_mochila.pack(side="left", padx=6)

    # ------------------------------------------------------------------ pestaña Backtracking
    def _tab_backtracking(self, t) -> None:
        self._etq(t, "Backtracking: explora rutas entre dos sectores PODANDO las calles "
                     "bloqueadas (rojo) y las ramas más caras que la mejor ruta hallada. Si no "
                     "existe ninguna ruta válida se muestra un aviso claro. Corre en segundo "
                     "plano y se puede cancelar."
                  ).pack(fill="x", pady=4)
        f = self._fila(t)
        nodos = sorted(datos.NODOS)
        ctk.CTkLabel(f, text="Origen").pack(side="left")
        self.opt_origen = ctk.CTkOptionMenu(f, values=nodos, width=150)
        self.opt_origen.set("San Blas")
        self.opt_origen.pack(side="left", padx=4)
        ctk.CTkLabel(f, text="Destino").pack(side="left", padx=(6, 0))
        self.opt_destino = ctk.CTkOptionMenu(f, values=nodos, width=150)
        self.opt_destino.set("Wanchaq")
        self.opt_destino.pack(side="left", padx=4)
        f = self._fila(t)
        self._btn(f, "Ruta más corta (poda)", self._bt_mas_corta, color=COLOR_BT).pack(side="left")
        self._btn(f, "Enumerar todas las rutas", self._bt_enumerar, color=COLOR_BT).pack(side="left", padx=6)
        ctk.CTkLabel(f, text="Cota ×").pack(side="left")
        self.e_cota = self._entrada(f, 1.5, 45)
        self.e_cota.pack(side="left", padx=4)

        marco = ctk.CTkFrame(t, fg_color="transparent")
        marco.pack(fill="x", pady=4)
        self.tabla_rutas = ttk.Treeview(marco, columns=("n", "km", "ruta"), show="headings",
                                        height=4, selectmode="browse")
        for c, a, titulo in (("n", 30, "#"), ("km", 60, "km"), ("ruta", 400, "Recorrido")):
            self.tabla_rutas.heading(c, text=titulo)
            self.tabla_rutas.column(c, width=a, anchor="w" if c == "ruta" else "center")
        self.tabla_rutas.pack(side="left", fill="x", expand=True)
        self.tabla_rutas.bind("<<TreeviewSelect>>", self._mostrar_ruta_elegida)

        self._seccion(t, "Estado de las calles (también con clic en el mapa)")
        f = self._fila(t)
        self._btn(f, "Bloquear / abrir seleccionada", self._alternar_seleccion, ancho=190).pack(side="left")
        self._btn(f, "Abrir todas", self._abrir_todas, color="#64748b", ancho=90).pack(side="left", padx=4)
        self._btn(f, "Cerrar ejemplo", self._cerrar_ejemplo, color="#64748b", ancho=110).pack(side="left")
        f = self._fila(t)
        self._btn(f, "Aislar destino (bloqueo masivo)", self._aislar_destino, color=COLOR_BLOQUEADA,
                  ancho=220).pack(side="left")
        marco = ctk.CTkFrame(t, fg_color="transparent")
        marco.pack(fill="both", expand=True, pady=4)
        self.tabla_calles = ttk.Treeview(marco, columns=("estado", "calle", "m"), show="headings",
                                         height=6, selectmode="browse")
        for c, a, titulo in (("estado", 85, "Estado"), ("calle", 360, "Calle"), ("m", 60, "m")):
            self.tabla_calles.heading(c, text=titulo)
            self.tabla_calles.column(c, width=a, anchor="w" if c == "calle" else "center")
        sb = ttk.Scrollbar(marco, command=self.tabla_calles.yview)
        self.tabla_calles.configure(yscrollcommand=sb.set)
        self.tabla_calles.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tabla_calles.tag_configure("bloqueada", foreground=COLOR_BLOQUEADA)

    # ------------------------------------------------------------------ pestaña Análisis
    def _tab_analisis(self, t) -> None:
        self._etq(t, "Análisis comparativo: corre todos los algoritmos de una familia sobre el "
                     "mismo escenario y mide el tiempo real (time.perf_counter). Luego genera "
                     "la gráfica Tiempo de ejecución vs N para el informe.", wraplength=520
                  ).pack(fill="x", pady=2)
        f = self._fila(t)
        ctk.CTkLabel(f, text="Familia").pack(side="left")
        self.opt_familia = ctk.CTkOptionMenu(f, values=list(benchmark.FAMILIAS), width=110)
        self.opt_familia.pack(side="left", padx=4)
        ctk.CTkLabel(f, text="N").pack(side="left", padx=(6, 0))
        self.e_n = self._entrada(f, 10, 45)
        self.e_n.pack(side="left", padx=4)
        ctk.CTkLabel(f, text="Rep.").pack(side="left")
        self.e_rep = self._entrada(f, 3, 35)
        self.e_rep.pack(side="left", padx=4)
        ctk.CTkLabel(f, text="Máx. s").pack(side="left")
        self.e_max_s = self._entrada(f, 10, 40)
        self.e_max_s.pack(side="left", padx=4)
        f = self._fila(t)
        self.sw_actuales = ctk.CTkSwitch(f, text="Usar los pedidos del mapa")
        self.sw_actuales.pack(side="left")
        self._btn(f, "Ejecutar en lote", self._ejecutar_lote, color=COLOR_PD).pack(side="left", padx=10)

        cols = ("alg", "ms", "km", "val", "opt", "delta", "comp")
        marco = ctk.CTkFrame(t, fg_color="transparent")
        marco.pack(fill="x", pady=4)
        self.tabla_bench = ttk.Treeview(marco, columns=cols, show="headings", height=5)
        for c, a, titulo in (("alg", 180, "Algoritmo"), ("ms", 70, "Tiempo ms"), ("km", 62, "Dist. km"),
                             ("val", 45, "Valor"), ("opt", 55, "Óptimo"), ("delta", 42, "Δ%"),
                             ("comp", 105, "Big-O")):
            self.tabla_bench.heading(c, text=titulo)
            self.tabla_bench.column(c, width=a, minwidth=a, stretch=False,
                                    anchor="w" if c in ("alg", "comp") else "center")
        self.tabla_bench.pack(fill="x")

        self._seccion(t, "Gráfica Tiempo de ejecución vs N")
        f = self._fila(t)
        ctk.CTkLabel(f, text="Tamaños N").pack(side="left")
        self.e_tamanos = self._entrada(f, "4,6,8,10,12,14,20,40,80", 210)
        self.e_tamanos.pack(side="left", padx=4)
        self.sw_log = ctk.CTkSwitch(f, text="Escala log", command=self._redibujar_curvas)
        self.sw_log.select()
        self.sw_log.pack(side="left", padx=6)
        f = self._fila(t)
        self._btn(f, "Generar gráfica", self._generar_curvas, color=COLOR_PD, ancho=130).pack(side="left")
        self._btn(f, "Guardar PNG...", self._guardar_grafica, color="#64748b", ancho=110).pack(side="left", padx=4)
        self._btn(f, "Ampliar", self._ampliar_grafica, color="#64748b", ancho=80).pack(side="left")
        self._seccion(t, "Experimentos de la tesis E1–E4 (CSV + Wilcoxon)")
        f = self._fila(t)
        ctk.CTkLabel(f, text="Semillas").pack(side="left")
        self.e_semillas_exp = self._entrada(f, 30, 45)
        self.e_semillas_exp.pack(side="left", padx=4)
        self.sw_rapido = ctk.CTkSwitch(f, text="Rápido (1 repetición)")
        self.sw_rapido.pack(side="left", padx=6)
        self._btn(f, "Ejecutar y guardar...", self._ejecutar_experimentos, color=COLOR_PD, ancho=150
                  ).pack(side="left")
        self.fig = Figure(figsize=(5.6, 3.0), dpi=100)
        self.canvas_fig = FigureCanvasTkAgg(self.fig, master=t)
        self.canvas_fig.get_tk_widget().pack(fill="both", expand=True, pady=4)
        self._redibujar_curvas()

    # ------------------------------------------------------------------ estilo de tablas
    def _aplicar_estilo_tabla(self) -> None:
        oscuro = ctk.get_appearance_mode() == "Dark"
        fondo, texto, cab = ("#2b2b2b", "#e5e7eb", "#3b3b3b") if oscuro else ("#ffffff", "#111827", "#e5e7eb")
        estilo = ttk.Style()
        estilo.theme_use("clam")
        estilo.configure("Treeview", background=fondo, fieldbackground=fondo, foreground=texto,
                         rowheight=24, borderwidth=0)
        estilo.configure("Treeview.Heading", background=cab, foreground=texto, relief="flat")
        estilo.map("Treeview", background=[("selected", "#2563eb")], foreground=[("selected", "white")])

    def _cambiar_apariencia(self, valor: str) -> None:
        ctk.set_appearance_mode("Dark" if valor == "Oscuro" else "Light")
        self._aplicar_estilo_tabla()

    # ======================================================================================
    # Mapa: inicio, dibujo de capas
    # ======================================================================================
    def _inicializar_mapa(self) -> None:
        self.mapa.set_tile_server(TILES["OpenStreetMap"], max_zoom=19)
        self._centrar_mapa()
        self._refrescar_todo()
        if self.calles_reales_auto:
            self._iniciar_calles_reales(forzar=False, automatico=True)

    def _cambiar_tile(self, nombre: str) -> None:
        self.mapa.set_tile_server(TILES[nombre], max_zoom=19)

    def _centrar_mapa(self) -> None:
        arriba_izq, abajo_der = traductor.caja_a_mapview(self.esc.red.limites(margen=1.0))
        self.mapa.fit_bounding_box(arriba_izq, abajo_der)

    def _borrar(self, capa: str) -> None:
        for objeto in self.capas[capa]:
            try:
                objeto.delete()
            except Exception:  # objeto ya borrado
                pass
        self.capas[capa] = []

    def _icono_pedido(self, p: Pedido):
        color = self.colores_pedido.get(p.id, COLOR_PEDIDO)
        halo = COLOR_RESALTE if p.id in self.resaltados else None
        return crear_icono("circulo", color, 12 + 3 * p.urgencia, halo=halo)

    def _dibujar_calles(self) -> None:
        self._borrar("calles")
        red = self.esc.red
        for c in red.calles():
            puntos = traductor.formatear_para_mapview(red.trazado_latlon(c.origen, c.destino))
            if c.bloqueada:
                self.capas["calles"].append(self.mapa.set_path(puntos, color=COLOR_BLOQUEADA, width=8))
                medio = traductor.xy_a_latlon(*red.punto_en_calle(c.origen, c.destino, 0.5))
                self.capas["calles"].append(self.mapa.set_marker(
                    medio[0], medio[1], text="BLOQUEADA",
                    text_color=COLOR_BLOQUEADA, font=("Arial", 8, "bold"),
                    icon=crear_icono("equis", COLOR_BLOQUEADA, 18)))
            else:
                ancho = 6 if c.factor_trafico >= 1.5 else 4
                color = "#d97706" if c.factor_trafico >= 1.5 else COLOR_CALLE
                self.capas["calles"].append(self.mapa.set_path(puntos, color=color, width=ancho))

    def _dibujar_nodos(self) -> None:
        self._borrar("nodos")
        nombres = self.sw_ids.get() == 1
        icono = crear_icono("rombo", "#64748b", 13)
        for n in self.esc.red.nodos.values():
            self.capas["nodos"].append(self.mapa.set_marker(
                n.lat, n.lon, text=n.nombre if nombres else None, text_color="#334155",
                font=("Arial", 8, "bold"), icon=icono))

    def _dibujar_pedidos(self) -> None:
        self._borrar("pedidos")
        ids = self.sw_ids.get() == 1
        for p in self.esc.pedidos:
            self.capas["pedidos"].append(self.mapa.set_marker(
                p.lat, p.lon, text=p.id if ids or p.id in self.resaltados else None,
                text_color="#111827", font=("Arial", 8, "bold"), icon=self._icono_pedido(p),
                command=self._clic_marcador, data=p.id))

    def _dibujar_base(self) -> None:
        self._borrar("base")
        for r in self.esc.repartidores:
            self.capas["base"].append(self.mapa.set_marker(
                r.lat, r.lon, text=r.nombre, text_color=r.color, font=("Arial", 9, "bold"),
                icon=crear_icono("triangulo", r.color, 26, texto=r.nombre[-1])))
        d = self.esc.deposito
        self.capas["base"].append(self.mapa.set_marker(
            d.lat, d.lon, text="Depósito", text_color="#000000", font=("Arial", 9, "bold"),
            icon=crear_icono("cuadrado", "#000000", 20)))

    def _dibujar_vistas(self) -> None:
        """Zonas (polígonos), rutas (líneas) y marcas extra. Se crean DESPUÉS de las calles para
        que queden encima (tkintermapview apila por tipo: polígono < línea < marcador)."""
        for capa in ("zonas", "rutas", "extras"):
            self._borrar(capa)
        for z in self.vista["zonas"]:
            self.capas["zonas"].append(self.mapa.set_polygon(
                z["coords"], fill_color=z["color"], outline_color=z["color"], border_width=3,
                name=z["nombre"]))
        for r in self.vista["rutas"]:
            if len(r["coords"]) >= 2:
                self.capas["rutas"].append(self.mapa.set_path(r["coords"], color=r["color"],
                                                              width=r.get("ancho", 7)))
        for e in self.vista["extras"]:
            self.capas["extras"].append(self.mapa.set_marker(
                e["lat"], e["lon"], text=e.get("etiqueta"), text_color=e["color"],
                font=("Arial", 8, "bold"),
                icon=crear_icono(e.get("forma", "circulo"), e["color"], e.get("tam", 20),
                                 texto=e.get("texto"))))

    def _dibujar_todo(self) -> None:
        self._dibujar_calles()
        self._dibujar_nodos()
        self._dibujar_pedidos()
        self._dibujar_vistas()
        self._dibujar_base()

    def _redibujar_calles_y_rutas(self) -> None:
        self._dibujar_calles()
        self._dibujar_vistas()

    # ------------------------------------------------------------------ vistas (resultados sobre el mapa)
    def _limpiar_vistas(self) -> None:
        self.vista = {"rutas": [], "zonas": [], "extras": []}

    def _limpiar_vistas_y_redibujar(self) -> None:
        self._limpiar_vistas()
        self.colores_pedido = {}
        self.resaltados = set()
        self._dibujar_pedidos()
        self._dibujar_vistas()

    def _limpiar_resultados(self) -> None:
        """Los datos cambiaron (pedidos o calles): los resultados anteriores ya no valen."""
        self.asignacion = {}
        self.colores_pedido = {}
        self.resaltados = set()
        self.ultima_seleccion = []
        self.rutas_bt = []
        self.ultimas_rutas = []
        self._limpiar_vistas()
        self.tabla_rutas.delete(*self.tabla_rutas.get_children())

    def _agregar_ruta(self, coords, color: str, ancho: int = 7) -> None:
        self.vista["rutas"].append({"coords": coords, "color": color, "ancho": ancho})

    def _agregar_paradas(self, orden, color: str) -> None:
        for i, p in enumerate(orden, 1):
            self.vista["extras"].append({"lat": p.lat, "lon": p.lon, "forma": "circulo",
                                         "color": color, "tam": 22, "texto": str(i)})

    def _ruta_en_mapa(self, inicio, orden, color: str, ancho: int = 7, nombre: str = "Ruta") -> None:
        coords = traductor.puntos_xy_a_coordenadas(self.red_vial.ruta(inicio, orden))
        self._agregar_ruta(coords, color, ancho)
        llegadas = exportar.llegadas(inicio, orden, self.red_vial.distancia,
                                     getattr(inicio, "velocidad_kmh", exportar.VELOCIDAD_KMH))
        self.ultimas_rutas.append(exportar.RutaExportable(nombre, color, inicio, list(orden), coords, llegadas))

    def _log_llegadas(self, nombre: str) -> None:
        """Resumen de horas de llegada y ventanas de entrega de la última ruta 'nombre'."""
        ruta = next((r for r in reversed(self.ultimas_rutas) if r.nombre == nombre), None)
        if ruta is None or not ruta.llegadas:
            return
        a_tiempo = sum(1 for ll in ruta.llegadas if ll.a_tiempo)
        tarde = [f"{ll.pedido.id} ({ll.minuto:.0f} min, vence {ll.pedido.ventana_fin})"
                 for ll in ruta.llegadas if not ll.a_tiempo]
        fin = ruta.llegadas[-1].minuto
        self.log(f"  Llegadas a {exportar.VELOCIDAD_TEXTO(ruta.inicio)} + {exportar.SERVICIO_MIN:g} min por "
                 f"entrega: termina en {fin:.0f} min; {a_tiempo}/{len(ruta.llegadas)} dentro de su ventana"
                 + (f"; fuera de plazo: {', '.join(tarde)}" if tarde else "."))

    # ======================================================================================
    # Datos: refresco y tablas
    # ======================================================================================
    def dist_deposito(self, p) -> float:
        return self.red_vial.distancia(self.esc.deposito, p)

    def _refrescar_red_vial(self) -> None:
        """Recalcula las distancias por calles (cambiaron pedidos o calles bloqueadas)."""
        self.red_vial = self.esc.crear_red_vial()

    def _refrescar_todo(self, redibujar: bool = True) -> None:
        self._refrescar_red_vial()
        self._actualizar_menus()
        self._llenar_tabla()
        self._llenar_calles()
        if redibujar:
            self._dibujar_todo()

    def _actualizar_menus(self) -> None:
        nombres = [r.nombre for r in self.esc.repartidores] or ["-"]
        for menu in (self.opt_rep_voraz, self.opt_rep_dyv, self.opt_rep_mochila):
            actual = menu.get()
            menu.configure(values=nombres)
            menu.set(actual if actual in nombres else nombres[0])
        conjuntos = [TODOS] + [r.nombre for r in self.esc.repartidores]
        actual = self.opt_conjunto.get()
        self.opt_conjunto.configure(values=conjuntos)
        self.opt_conjunto.set(actual if actual in conjuntos else TODOS)
        ks = [str(k) for k in range(2, max(2, len(self.esc.repartidores)) + 1)]
        actual = self.opt_k.get()
        self.opt_k.configure(values=ks)
        self.opt_k.set(actual if actual in ks else ks[-1])
        nodos = sorted(self.esc.red.nodos)
        for menu, defecto in ((self.opt_origen, "San Blas"), (self.opt_destino, "Wanchaq"),
                              (self.opt_sector, nodos[0])):
            actual = menu.get()
            menu.configure(values=nodos)
            menu.set(actual if actual in nodos else (defecto if defecto in nodos else nodos[0]))

    def _llenar_tabla(self) -> None:
        self.tabla.delete(*self.tabla.get_children())
        for p in self.esc.pedidos:
            d = self.dist_deposito(p)
            self.tabla.insert("", "end", iid=p.id, values=(
                p.id, p.cliente, p.sector, p.urgencia, p.peso, p.valor,
                "∞" if math.isinf(d) else f"{d / 1000:.2f}"))

    def _llenar_calles(self) -> None:
        self.tabla_calles.delete(*self.tabla_calles.get_children())
        for i, c in enumerate(self.esc.red.calles()):
            self.tabla_calles.insert("", "end", iid=str(i), values=(
                c.estado, f"{c.origen} — {c.destino}", f"{c.distancia_m:.0f}"),
                tags=("bloqueada",) if c.bloqueada else ())

    def _al_elegir_fila(self, _evento=None) -> None:
        self.resaltados = set(self.tabla.selection())
        self._dibujar_pedidos()

    def _clic_marcador(self, marcador) -> None:
        p = self.esc.pedido_por_id(marcador.data)
        if p is None:
            return
        self.log(f"{p.id}: {p.cliente} | sector {p.sector} | urgencia {p.urgencia} | "
                 f"{p.peso} kg | S/ {p.valor} | ventana {p.ventana_inicio}-{p.ventana_fin} min")
        if self.tabla.exists(p.id):
            self.tabla.selection_set(p.id)
            self.tabla.see(p.id)

    # ======================================================================================
    # Interacción directa con el mapa
    # ======================================================================================
    def _cambiar_modo(self, modo: str) -> None:
        self.modo = modo
        textos = {MODOS[1]: "Haz clic sobre una calle del mapa para bloquearla o abrirla.",
                  MODOS[2]: "Haz clic sobre el mapa para agregar un pedido en la calle más cercana.",
                  MODOS[0]: "Modo navegación: arrastra y usa la rueda para mover el mapa."}
        self.log(textos[modo])

    def _clic_mapa(self, coordenada) -> None:
        lat, lon = coordenada
        if self.modo == MODOS[1]:
            self._clic_calle(lat, lon)
        elif self.modo == MODOS[2]:
            self._clic_pedido(lat, lon)

    def _tolerancia_m(self, pixeles: float = 16.0) -> float:
        metros_por_pixel = 156543.03392 * math.cos(math.radians(self.mapa.get_position()[0])) \
            / (2 ** self.mapa.zoom)
        return max(25.0, pixeles * metros_por_pixel)

    def _edicion_permitida(self) -> bool:
        if self._ocupado:
            self._alerta("Hay una tarea en ejecución: espera o cancélala antes de editar.", "aviso")
            return False
        return True

    def _clic_calle(self, lat: float, lon: float) -> None:
        if not self._edicion_permitida():
            return
        x, y = traductor.latlon_a_xy(lat, lon)
        calle, distancia, *_ = self.esc.red.calle_mas_cercana(x, y)
        if distancia * datos.UNIDAD_M > self._tolerancia_m():
            self._alerta("No hay ninguna calle cerca de ese punto: haz clic sobre una calle.", "aviso", 3500)
            return
        self._cambiar_estado_calle(calle.origen, calle.destino)

    def _cambiar_estado_calle(self, origen: str, destino: str) -> None:
        bloqueada = self.esc.red.alternar_calle(origen, destino)
        self.log(f"Calle {origen} — {destino}: {'BLOQUEADA' if bloqueada else 'ABIERTA'}.")
        self._tras_cambiar_calles()

    def _tras_cambiar_calles(self) -> None:
        self._limpiar_resultados()
        self._refrescar_red_vial()
        self._llenar_tabla()
        self._llenar_calles()
        self._dibujar_calles()
        self._dibujar_pedidos()
        self._dibujar_vistas()

    def _clic_pedido(self, lat: float, lon: float) -> None:
        if not self._edicion_permitida():
            return
        x, y = traductor.latlon_a_xy(lat, lon)
        calle, distancia, t, px, py = self.esc.red.calle_mas_cercana(x, y)
        if distancia * datos.UNIDAD_M > max(400.0, self._tolerancia_m(120)):
            self._alerta("Ese punto está demasiado lejos de las calles de la red.", "aviso", 3500)
            return
        id_ = self.esc.siguiente_id()
        peso = _a_entero(self.e_peso.get(), 5, 1, 500)
        pedido = Pedido(id_, f"Cliente {id_[1:]}", px, py, int(self.opt_urg.get()), peso,
                        _a_entero(self.e_valor.get(), 50, 0), self.esc.red.nodo_mas_cercano(px, py),
                        (calle.origen, calle.destino), t, origen=self.esc.deposito.nodo,
                        volumen_m3=round(max(0.005, peso / 120.0), 3))
        self.esc.agregar_pedido(pedido)
        self.log(f"Pedido {id_} agregado en la calle {calle.origen} — {calle.destino} "
                 f"(sector {pedido.sector}).")
        self._limpiar_resultados()
        self._refrescar_red_vial()
        self._llenar_tabla()
        self._dibujar_pedidos()
        self._dibujar_vistas()

    # ======================================================================================
    # Ejecución en segundo plano (threading)
    # ======================================================================================
    def _correr(self, titulo: str, trabajo, al_terminar) -> None:
        """Ejecuta ``trabajo(cancelar, progreso)`` en un hilo y llama a ``al_terminar(resultado)``
        en el hilo de la interfaz. La interfaz sigue respondiendo todo el tiempo."""
        if self._ocupado:
            self._alerta("Ya hay una tarea en ejecución: espera o cancélala.", "aviso")
            return
        self._ocupado = True
        self._cancelar.clear()
        cola: queue.Queue = queue.Queue()
        self._cola = cola
        self.lbl_estado.configure(text=titulo + "...")
        self.barra.configure(mode="indeterminate")
        self.barra.start()
        self.btn_cancelar.configure(state="normal")

        def progreso(fraccion: float, texto: str = "") -> None:
            cola.put(("prog", fraccion, texto))

        def correr() -> None:
            try:
                cola.put(("ok", trabajo(self._cancelar, progreso)))
            except BaseException:  # noqa: BLE001 - se informa en la bitácora
                cola.put(("err", traceback.format_exc()))

        threading.Thread(target=correr, daemon=True, name="tarea-" + titulo).start()
        self.after(80, self._sondear, al_terminar)

    def _sondear(self, al_terminar) -> None:
        final = None
        try:
            while True:
                mensaje = self._cola.get_nowait()
                if mensaje[0] == "prog":
                    if str(self.barra.cget("mode")) != "determinate":
                        self.barra.stop()
                        self.barra.configure(mode="determinate")
                    self.barra.set(max(0.0, min(1.0, mensaje[1])))
                    if mensaje[2]:
                        self.lbl_estado.configure(text=mensaje[2])
                else:
                    final = mensaje
                    break
        except queue.Empty:
            pass
        if final is None:
            self.after(80, self._sondear, al_terminar)
            return
        self._fin_tarea()
        if final[0] == "err":
            self.log("ERROR en la tarea:\n" + final[1])
            self._alerta("La tarea falló (ver bitácora).", "error")
            return
        try:
            al_terminar(final[1])
        except Exception:  # noqa: BLE001
            self.log("ERROR al mostrar el resultado:\n" + traceback.format_exc())
            self._alerta("No se pudo mostrar el resultado (ver bitácora).", "error")

    def _fin_tarea(self) -> None:
        self.barra.stop()
        self.barra.configure(mode="determinate")
        self.barra.set(0)
        self.lbl_estado.configure(text="Inactivo")
        self.btn_cancelar.configure(state="disabled")
        self._ocupado = False

    def _cancelar_tarea(self) -> None:
        if self._ocupado:
            self._cancelar.set()
            self.lbl_estado.configure(text="Cancelando...")
            self.log("Cancelación solicitada.")

    def esperar_tarea(self, timeout: float = 60.0) -> None:
        """Procesa eventos hasta que termine la tarea en curso (útil en pruebas)."""
        limite = time.time() + timeout
        while self._ocupado and time.time() < limite:
            self.update()
            time.sleep(0.01)
        self.update()

    # ======================================================================================
    # Acciones: datos
    # ======================================================================================
    def _repartidor(self, nombre: str):
        for r in self.esc.repartidores:
            if r.nombre == nombre:
                return r
        return self.esc.repartidores[0] if self.esc.repartidores else None

    def _necesita_repartidores(self) -> bool:
        if not self.esc.repartidores:
            self._alerta("El escenario no tiene repartidores.", "aviso")
            return False
        return True

    def _alcanzables(self, inicio, pedidos: list) -> list:
        """Quita los pedidos a los que no se puede llegar con las calles abiertas."""
        rv = self.red_vial
        buenos = [p for p in pedidos if not math.isinf(rv.distancia(inicio, p))]
        if len(buenos) < len(pedidos):
            ids = {p.id for p in buenos}
            omitidos = [p.id for p in pedidos if p.id not in ids]
            self.log(f"Pedidos inalcanzables por calles bloqueadas (se omiten): {', '.join(omitidos)}")
            self._alerta(f"{len(omitidos)} pedido(s) inalcanzable(s) por bloqueos.", "aviso")
        return buenos

    def _generar(self) -> None:
        if not self._edicion_permitida():
            return
        n = _a_entero(self.e_cantidad.get(), 18, 1, 300)
        semilla = _a_entero(self.e_semilla.get(), 7, 1, 99999)
        self.esc.pedidos = datos.generar_pedidos(n, semilla, self.esc.red, self.esc.deposito.nodo)
        self._limpiar_resultados()
        self._refrescar_todo()
        self.log(f"Generados {n} pedidos aleatorios (semilla {semilla}).")

    def _cargar_escenario(self) -> None:
        if not self._edicion_permitida():
            return
        carpeta = filedialog.askdirectory(title="Carpeta con red_cusco, pedidos y repartidores")
        if not carpeta:
            return

        def buscar(base: str, extensiones=("json", "csv")):
            for ext in extensiones:
                ruta = os.path.join(carpeta, f"{base}.{ext}")
                if os.path.exists(ruta) or (base == "red_cusco" and ext == "csv" and
                                            os.path.exists(os.path.join(carpeta, "red_cusco_nodos.csv"))):
                    return ruta
            return None

        ruta_red, ruta_ped, ruta_rep = buscar("red_cusco"), buscar("pedidos"), buscar("repartidores")
        if not ruta_red or not ruta_ped:
            messagebox.showerror("Cargar escenario",
                                 "La carpeta debe tener red_cusco.json (o red_cusco_nodos.csv y "
                                 "red_cusco_calles.csv) y pedidos.json (o pedidos.csv).")
            return
        try:
            self.esc = datos.Escenario.cargar(ruta_red, ruta_ped, ruta_rep)
        except (ValueError, OSError, KeyError) as error:
            self.log(f"No se pudo cargar el escenario: {error}")
            messagebox.showerror("Cargar escenario", str(error))
            return
        self._limpiar_resultados()
        if not self.esc.red.tiene_trazado_real():
            self._aplicar_cache_calles(calles_reales.cargar_cache(), avisar=False)
        self._refrescar_todo()
        self._centrar_mapa()
        self.log(f"Escenario cargado de {carpeta}: {len(self.esc.red.nodos)} nodos, "
                 f"{len(self.esc.red.calles())} calles, {len(self.esc.pedidos)} pedidos, "
                 f"{len(self.esc.repartidores)} repartidores.")

    def _guardar_escenario(self) -> None:
        carpeta = filedialog.askdirectory(title="Carpeta donde guardar el escenario")
        if not carpeta:
            return
        try:
            archivos = self.esc.guardar(carpeta, self.opt_formato.get())
        except (ValueError, OSError) as error:
            messagebox.showerror("Guardar escenario", str(error))
            return
        self.log("Escenario guardado: " + ", ".join(os.path.basename(str(a)) for a in archivos))

    # ------------------------------------------------------------------ ordenar y buscar
    def _ordenar(self) -> None:
        clave, inverso = ORDENES[self.opt_criterio.get()](self)
        nombre = self.opt_alg_orden.get()
        t0 = time.perf_counter()
        resultado = ALGORITMOS_ORDEN[nombre](self.esc.pedidos, clave, inverso)
        ms = (time.perf_counter() - t0) * 1000
        self.esc.pedidos = resultado
        self._llenar_tabla()
        self.log(f"{nombre} ordenó {len(resultado)} pedidos por «{self.opt_criterio.get()}» "
                 f"en {ms:.3f} ms.")

    def _buscar(self) -> None:
        consulta = self.e_buscar.get().strip()
        metodo = self.opt_busqueda.get()
        pedidos = self.esc.pedidos
        t0 = time.perf_counter()
        detalle = ""
        if metodo == BUSQUEDAS[0]:
            por_id = ordenacion.merge_sort(pedidos, lambda p: p.id.upper())
            pedido, comparaciones = ordenacion.busqueda_binaria(por_id, consulta.upper(),
                                                                lambda p: p.id.upper())
            encontrados = [pedido] if pedido else []
            detalle = f"{comparaciones} comparaciones"
        elif metodo == BUSQUEDAS[1]:
            pedido = ordenacion.IndicePedidos(pedidos).buscar_id(consulta)
            encontrados = [pedido] if pedido else []
            detalle = "1 acceso a la tabla hash"
        elif metodo == BUSQUEDAS[2]:
            encontrados = ordenacion.IndicePedidos(pedidos).buscar_cliente(consulta)
            detalle = "tabla hash por cliente"
        elif metodo == BUSQUEDAS[3]:
            encontrados = ordenacion.IndicePedidos(pedidos).buscar_cliente_parcial(consulta)
            detalle = "recorrido de clientes"
        else:
            sector = self.opt_sector.get()
            encontrados = ordenacion.construir_indice_sectores(pedidos).get(sector, [])
            consulta, detalle = sector, "índice por sector"
        ms = (time.perf_counter() - t0) * 1000
        self.resaltados = {p.id for p in encontrados}
        self.tabla.selection_remove(self.tabla.selection())
        for p in encontrados:
            self.tabla.selection_add(p.id)
        if encontrados:
            self.tabla.see(encontrados[0].id)
            if len(encontrados) == 1:
                self.mapa.set_position(encontrados[0].lat, encontrados[0].lon)
        self._dibujar_pedidos()
        ids = ", ".join(p.id for p in encontrados) or "ninguno"
        self.log(f"Búsqueda «{consulta}» [{metodo}]: {len(encontrados)} resultado(s) ({ids}); "
                 f"{detalle}; {ms:.3f} ms.")
        if not encontrados:
            self._alerta(f"Sin resultados para «{consulta}».", "aviso", 3500)

    def _quitar_resaltado(self) -> None:
        self.tabla.selection_remove(self.tabla.selection())
        self.resaltados = set()
        self._dibujar_pedidos()

    def _eliminar_seleccion(self) -> None:
        if not self._edicion_permitida():
            return
        ids = list(self.tabla.selection())
        if not ids:
            self._alerta("Selecciona uno o más pedidos en la tabla.", "aviso", 3500)
            return
        for id_ in ids:
            self.esc.quitar_pedido(id_)
        self.log(f"Pedidos eliminados: {', '.join(ids)}")
        self._limpiar_resultados()
        self._refrescar_todo()

    # ======================================================================================
    # Acciones: Voraz
    # ======================================================================================
    def _pintar_asignacion(self, asignacion: dict, pendientes: list) -> None:
        self.colores_pedido = {}
        for r in self.esc.repartidores:
            for p in asignacion.get(r.nombre, []):
                self.colores_pedido[p.id] = r.color
        for p in pendientes:
            self.colores_pedido[p.id] = COLOR_SIN_USO

    def _asignar_voraz(self) -> None:
        if not self._necesita_repartidores():
            return
        rv, reps = self.red_vial, list(self.esc.repartidores)
        pedidos = self.esc.obtener_pedidos_ordenables()

        def trabajo(cancelar, progreso):
            t0 = time.perf_counter()
            asignacion, pendientes = voraz.asignar_mas_cercano(pedidos, reps, rv.distancia)
            return asignacion, pendientes, (time.perf_counter() - t0) * 1000

        def listo(res):
            asignacion, pendientes, ms = res
            self.asignacion = asignacion
            self._limpiar_vistas()
            self._pintar_asignacion(asignacion, pendientes)
            self._dibujar_pedidos()
            self._dibujar_vistas()
            self.log(f"Asignación voraz ({ms:.3f} ms, O(n log n + n·m)):")
            for r in reps:
                lista = asignacion[r.nombre]
                self.log(f"  {r.nombre}: {len(lista)} pedidos, {sum(p.peso for p in lista)}/{r.capacidad} kg")
            if pendientes:
                self.log(f"  Sin asignar (capacidad llena o inalcanzables por bloqueos): "
                         f"{', '.join(p.id for p in pendientes)}")

        self._correr("Asignación voraz", trabajo, listo)

    def _trabajo_voraz(self, nombres: list[str]):
        """Trabajo (hilo) que asigna si hace falta y calcula la ruta de cada repartidor."""
        rv, reps = self.red_vial, list(self.esc.repartidores)
        pedidos = self.esc.obtener_pedidos_ordenables()
        previa = dict(self.asignacion)

        def trabajo(cancelar, progreso):
            t0 = time.perf_counter()
            if previa:
                asignacion, pendientes = previa, []
            else:
                asignacion, pendientes = voraz.asignar_mas_cercano(pedidos, reps, rv.distancia)
            rutas = []
            for r in reps:
                if r.nombre in nombres and asignacion.get(r.nombre):
                    lista = [p for p in asignacion[r.nombre] if not math.isinf(rv.distancia(r, p))]
                    if lista:
                        orden, total = voraz.ruta_vecino_mas_cercano(r, lista, rv.distancia)
                        rutas.append((r, orden, total))
            return asignacion, pendientes, rutas, (time.perf_counter() - t0) * 1000
        return trabajo

    def _mostrar_rutas_voraz(self, res) -> None:
        asignacion, pendientes, rutas, ms = res
        if not self.asignacion:
            self.asignacion = asignacion
            self._pintar_asignacion(asignacion, pendientes)
        self._limpiar_vistas()
        if not rutas:
            self._alerta("El repartidor no tiene pedidos asignados.", "aviso")
        self.ultimas_rutas = []
        for r, orden, total in rutas:
            self._ruta_en_mapa(r, orden, COLOR_VORAZ, nombre=r.nombre)
            self._agregar_paradas(orden, r.color)
            self.log(f"{r.nombre} (vecino más cercano, {ms:.3f} ms, O(n²)): "
                     f"{' → '.join(p.id for p in orden)} | {km(total)}")
            self._log_llegadas(r.nombre)
        self._dibujar_pedidos()
        self._dibujar_vistas()

    def _ruta_voraz(self) -> None:
        if self._necesita_repartidores():
            self._correr("Ruta voraz", self._trabajo_voraz([self.opt_rep_voraz.get()]),
                         self._mostrar_rutas_voraz)

    def _rutas_voraz_todos(self) -> None:
        if self._necesita_repartidores():
            self._correr("Rutas voraces", self._trabajo_voraz([r.nombre for r in self.esc.repartidores]),
                         self._mostrar_rutas_voraz)

    # ======================================================================================
    # Acciones: Divide y Vencerás
    # ======================================================================================
    def _pintar_zonas(self, zonas) -> None:
        self.colores_pedido = {}
        for i, z in enumerate(zonas):
            color = COLORES_ZONAS[i % len(COLORES_ZONAS)]
            self.vista["zonas"].append({"coords": traductor.poligono_de_limites(z.limites),
                                        "color": color, "nombre": z.id})
            cx, cy = z.centro
            lat, lon = traductor.xy_a_latlon(cx, cy)
            self.vista["extras"].append({"lat": lat, "lon": lon, "forma": "cuadrado", "tam": 10,
                                         "color": color, "etiqueta": f"{z.id} ({len(z.pedidos)})"})
            for p in z.pedidos:
                self.colores_pedido[p.id] = color

    def _parametros_dyv(self):
        return int(self.sl_max_zona.get()), int(self.sl_nivel.get())

    def _ejecutar_dyv(self) -> None:
        if not self._necesita_repartidores():
            return
        rep = self._repartidor(self.opt_rep_dyv.get())
        pedidos = self._alcanzables(rep, self.esc.obtener_pedidos_ordenables())
        if not pedidos:
            self._alerta("No hay pedidos para rutear.", "aviso")
            return
        max_zona, nivel = self._parametros_dyv()
        rv, limites = self.red_vial, self.esc.red.limites()

        def trabajo(cancelar, progreso):
            t0 = time.perf_counter()
            r = divide_venceras.dividir_y_vencer(rep, pedidos, limites, rv.distancia, max_zona, nivel)
            ms = (time.perf_counter() - t0) * 1000
            _, base = voraz.ruta_vecino_mas_cercano(rep, pedidos, rv.distancia)
            return r, ms, base

        def listo(res):
            r, ms, base = res
            self._limpiar_vistas()
            self._pintar_zonas(r.zonas)
            self.ultimas_rutas = []
            self._ruta_en_mapa(rep, r.orden, COLOR_DYV, nombre=f"{rep.nombre} (DyV)")
            self._agregar_paradas(r.orden, COLOR_DYV)
            for e in r.empalmes:
                lat, lon = traductor.xy_a_latlon(*e.cruce)
                self.vista["extras"].append({"lat": lat, "lon": lon, "forma": "rombo", "tam": 18,
                                             "color": "#c2410c", "etiqueta": f"{e.de_zona}→{e.a_zona}"})
            self._dibujar_pedidos()
            self._dibujar_vistas()
            self.log(f"Divide y Vencerás desde {rep.nombre} ({ms:.2f} ms): {len(r.zonas)} zonas "
                     f"({r.zonas_exactas} resueltas con Held-Karp), {len(r.empalmes)} empalmes de frontera.")
            for z in r.zonas:
                self.log(f"  {z.id} nivel {z.nivel}: {' → '.join(p.id for p in r.subrutas[z.id])}")
            self.log(f"  Orden de zonas: {' → '.join(r.orden_zonas)}")
            self.log(f"  Ruta final: {' → '.join(p.id for p in r.orden)}")
            mejora = (1 - r.distancia / r.distancia_sin_refinar) * 100 if r.distancia_sin_refinar else 0
            self.log(f"  Distancia: {km(r.distancia)} (empalme sin refinar {km(r.distancia_sin_refinar)}, "
                     f"el 2-opt de fronteras mejora {mejora:.1f}%). Vecino más cercano: {km(base)}.")
            self._log_llegadas(f"{rep.nombre} (DyV)")

        self._correr("Divide y Vencerás", trabajo, listo)

    def _solo_subzonas(self) -> None:
        pedidos = self.esc.obtener_pedidos_ordenables()
        max_zona, nivel = self._parametros_dyv()
        limites = self.esc.red.limites()

        def trabajo(cancelar, progreso):
            return divide_venceras.dividir_cuadrantes(pedidos, limites, max_zona, nivel)

        def listo(zonas):
            self._limpiar_vistas()
            self._pintar_zonas(zonas)
            self._dibujar_pedidos()
            self._dibujar_vistas()
            self.log(f"{len(zonas)} subzonas (quadtree, máx. {max_zona} pedidos y profundidad {nivel}):")
            for z in zonas:
                self.log(f"  {z.id}: {len(z.pedidos)} pedidos, vecinas: {', '.join(z.vecinas) or 'ninguna'}")

        self._correr("Subzonas", trabajo, listo)

    def _repartir_zonas(self) -> None:
        if not self._necesita_repartidores():
            return
        k = min(int(self.opt_k.get()), len(self.esc.repartidores))
        pedidos = self.esc.obtener_pedidos_ordenables()
        limites, reps = self.esc.red.limites(), list(self.esc.repartidores)

        def trabajo(cancelar, progreso):
            t0 = time.perf_counter()
            zonas = divide_venceras.dividir_en_zonas(pedidos, k, limites)
            return zonas, (time.perf_counter() - t0) * 1000

        def listo(res):
            zonas, ms = res
            libres = list(reps)
            self._limpiar_vistas()
            self.asignacion = {r.nombre: [] for r in reps}
            self.colores_pedido = {}
            for caja, lista in zonas:
                cx, cy = (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2
                r = min(libres, key=lambda rr: math.hypot(rr.x - cx, rr.y - cy))
                libres.remove(r)
                self.asignacion[r.nombre] = lista
                self.vista["zonas"].append({"coords": traductor.poligono_de_limites(caja),
                                            "color": r.color, "nombre": r.nombre})
                lat, lon = traductor.xy_a_latlon(cx, cy)
                self.vista["extras"].append({"lat": lat, "lon": lon, "forma": "cuadrado", "tam": 10,
                                             "color": r.color, "etiqueta": f"Zona de {r.nombre}"})
                for p in lista:
                    self.colores_pedido[p.id] = r.color
            self._dibujar_pedidos()
            self._dibujar_vistas()
            self.log(f"Ciudad dividida en {k} zonas ({ms:.3f} ms):")
            for r in reps:
                lista = self.asignacion[r.nombre]
                self.log(f"  {r.nombre}: {len(lista)} pedidos, {sum(p.peso for p in lista)} kg")

        self._correr("Reparto por zonas", trabajo, listo)

    # ======================================================================================
    # Acciones: Mochila (Programación Dinámica)
    # ======================================================================================
    def _conjunto_mochila(self):
        nombre = self.opt_conjunto.get()
        if nombre == TODOS:
            return self.esc.obtener_pedidos_ordenables()
        lista = self.asignacion.get(nombre, [])
        if not lista:
            self._alerta(f"{nombre} no tiene pedidos: asigna con Voraz o Divide y Vencerás, "
                         f"o elige «{TODOS}».", "aviso")
            return None
        return lista

    def _mochila(self, tipo: str) -> None:
        candidatos = self._conjunto_mochila()
        if not candidatos:
            if candidatos is not None:
                self._alerta("No hay pedidos para cargar.", "aviso")
            return
        cap_kg = _a_entero(self.e_cap_kg.get(), 30, 1, 5000)
        cap_m3 = _a_real(self.e_cap_m3.get(), 3.0, 0.01, 100.0)
        prioridad = self.opt_objetivo.get() == "Prioridad"
        valor_fn = (lambda p: p.urgencia) if prioridad else (lambda p: p.valor)
        etiquetas = {"tab": "PD tabulación", "memo": "PD memoización",
                     "vol": "PD peso+volumen", "voraz": "Voraz valor/peso"}

        def trabajo(cancelar, progreso):
            t0 = time.perf_counter()
            volumen = None
            if tipo == "tab":
                elegidos, valor, peso = programacion_dinamica.mochila_01(candidatos, cap_kg, valor_fn)
            elif tipo == "memo":
                elegidos, valor, peso = programacion_dinamica.mochila_01_memo(candidatos, cap_kg, valor_fn)
            elif tipo == "vol":
                elegidos, valor, peso, volumen = programacion_dinamica.mochila_01_peso_volumen(
                    candidatos, cap_kg, cap_m3, valor_fn=valor_fn)
            else:
                elegidos, valor, peso = voraz.mochila_voraz(candidatos, cap_kg, valor_fn)
            return elegidos, valor, peso, volumen, (time.perf_counter() - t0) * 1000

        def listo(res):
            elegidos, valor, peso, volumen, ms = res
            ids = {p.id for p in elegidos}
            self._limpiar_vistas()
            self.colores_pedido = {p.id: ("#10b981" if p.id in ids else COLOR_SIN_USO) for p in candidatos}
            self.ultima_seleccion = elegidos
            self._dibujar_pedidos()
            self._dibujar_vistas()
            unidad = "prioridad" if prioridad else "S/"
            extra = f", volumen {volumen:.3f} m³" if volumen is not None else ""
            self.log(f"Mochila {etiquetas[tipo]} ({ms:.3f} ms): valor {unidad} {valor}, peso {peso}/{cap_kg} kg"
                     f"{extra}, {len(elegidos)}/{len(candidatos)} pedidos.")
            self.log(f"  IDs elegidos: {', '.join(p.id for p in elegidos) or 'ninguno'}")

        self._correr("Mochila " + etiquetas[tipo], trabajo, listo)

    def _ruta_held_karp(self) -> None:
        if not self._necesita_repartidores():
            return
        if not self.ultima_seleccion:
            self._alerta("Primero resuelve la mochila (PD o voraz).", "aviso")
            return
        rep = self._repartidor(self.opt_rep_mochila.get())
        seleccion = self._alcanzables(rep, self.ultima_seleccion)
        limite = programacion_dinamica.MAX_PEDIDOS_HELD_KARP
        if len(seleccion) > limite:
            self._alerta(f"Held-Karp admite máximo {limite} pedidos (hay {len(seleccion)}): baja la capacidad.", "aviso")
            return
        rv = self.red_vial

        def trabajo(cancelar, progreso):
            t0 = time.perf_counter()
            orden, total = programacion_dinamica.ruta_optima_held_karp(rep, seleccion, rv.distancia)
            ms = (time.perf_counter() - t0) * 1000
            _, base = voraz.ruta_vecino_mas_cercano(rep, seleccion, rv.distancia)
            return orden, total, ms, base

        def listo(res):
            orden, total, ms, base = res
            self._limpiar_vistas()
            self.ultimas_rutas = []
            self._ruta_en_mapa(rep, orden, COLOR_PD, nombre=f"{rep.nombre} (Held-Karp)")
            self._agregar_paradas(orden, COLOR_PD)
            self._dibujar_pedidos()
            self._dibujar_vistas()
            self.log(f"Held-Karp desde {rep.nombre} ({ms:.1f} ms): {' → '.join(p.id for p in orden)} | "
                     f"{km(total)} (vecino más cercano: {km(base)})")
            self._log_llegadas(f"{rep.nombre} (Held-Karp)")

        self._correr("Held-Karp", trabajo, listo)

    # ======================================================================================
    # Acciones: Backtracking y estado de calles
    # ======================================================================================
    def _extremos_bt(self):
        origen, destino = self.opt_origen.get(), self.opt_destino.get()
        if origen == destino:
            self._alerta("Origen y destino deben ser distintos.", "aviso", 3500)
            return None
        return origen, destino

    def _marcas_origen_destino(self, origen: str, destino: str) -> None:
        for nombre, letra, color in ((origen, "O", "#0f766e"), (destino, "D", "#7c2d12")):
            n = self.esc.red.nodos[nombre]
            self.vista["extras"].append({"lat": n.lat, "lon": n.lon, "forma": "circulo", "tam": 24,
                                         "color": color, "texto": letra,
                                         "etiqueta": "Origen" if letra == "O" else "Destino"})

    def _mostrar_bt(self, r, origen: str, destino: str, camino=None) -> None:
        self._limpiar_vistas()
        self._marcas_origen_destino(origen, destino)
        camino = camino if camino is not None else r.camino
        self.ultimas_rutas = []
        if camino:
            coords = traductor.formatear_para_mapview(self.esc.red.polilinea_camino(camino))
            self._agregar_ruta(coords, COLOR_BT, 8)
            self.ultimas_rutas = [exportar.RutaExportable(f"Backtracking {origen} - {destino}", COLOR_BT,
                                                          None, [], coords, [])]
        self._dibujar_vistas()

    def _bt_mas_corta(self) -> None:
        par = self._extremos_bt()
        if par is None:
            return
        origen, destino = par
        red = self.esc.red.copia()

        def trabajo(cancelar, progreso):
            t0 = time.perf_counter()
            r = backtracking.ruta_mas_corta_segura(red, origen, destino, cancelar, 60.0)
            return r, (time.perf_counter() - t0) * 1000

        def listo(res):
            r, ms = res
            self.rutas_bt = [(r.costo, r.camino)] if r.encontrada else []
            self.tabla_rutas.delete(*self.tabla_rutas.get_children())
            self._mostrar_bt(r, origen, destino)
            if not r.encontrada:
                self._alerta(r.mensaje, "error", 9000)
                self.log(r.mensaje)
                return
            self.tabla_rutas.insert("", "end", iid="0", values=(1, f"{r.costo / 1000:.2f}", " → ".join(r.camino)))
            self.log(f"Backtracking con poda {origen} → {destino} ({ms:.2f} ms): {km(r.costo)} por "
                     f"{' → '.join(r.camino)}")
            self.log(f"  {r.nodos_explorados} nodos explorados, {r.podas_bloqueo} podas por calle "
                     f"bloqueada, {r.podas_cota} podas por cota. {r.mensaje}")

        self._correr("Backtracking (ruta más corta)", trabajo, listo)

    def _bt_enumerar(self) -> None:
        par = self._extremos_bt()
        if par is None:
            return
        origen, destino = par
        factor = _a_real(self.e_cota.get(), 1.5)
        factor = factor if factor >= 1.0 else None
        red = self.esc.red.copia()

        def trabajo(cancelar, progreso):
            t0 = time.perf_counter()
            r = backtracking.enumerar_rutas_validas(red, origen, destino, factor, cancelar=cancelar,
                                                    tiempo_max_s=60.0)
            return r, (time.perf_counter() - t0) * 1000

        def listo(res):
            r, ms = res
            self.rutas_bt = r.rutas
            self.tabla_rutas.delete(*self.tabla_rutas.get_children())
            self._mostrar_bt(r, origen, destino)
            if not r.encontrada:
                self._alerta(r.mensaje, "error", 9000)
                self.log(r.mensaje)
                return
            for i, (costo, camino) in enumerate(r.rutas[:400]):
                self.tabla_rutas.insert("", "end", iid=str(i),
                                        values=(i + 1, f"{costo / 1000:.2f}", " → ".join(camino)))
            self.tabla_rutas.selection_set("0")
            self.log(f"Backtracking {origen} → {destino} ({ms:.1f} ms): {len(r.rutas)} rutas válidas, "
                     f"{r.nodos_explorados} nodos, {r.podas_bloqueo} podas por bloqueo, "
                     f"{r.podas_cota} podas por cota{' (truncado)' if r.truncado else ''}.")
            self.log(f"  Más corta: {km(r.costo)} por {' → '.join(r.camino)}")

        self._correr("Backtracking (todas las rutas)", trabajo, listo)

    def _mostrar_ruta_elegida(self, _evento=None) -> None:
        seleccion = self.tabla_rutas.selection()
        if not seleccion or int(seleccion[0]) >= len(self.rutas_bt):
            return
        _, camino = self.rutas_bt[int(seleccion[0])]
        origen, destino = camino[0], camino[-1]
        self._mostrar_bt(None, origen, destino, camino)

    def _alternar_seleccion(self) -> None:
        if not self._edicion_permitida():
            return
        seleccion = self.tabla_calles.selection()
        if not seleccion:
            self._alerta("Selecciona una calle de la tabla (o haz clic sobre ella en el mapa).", "aviso", 4000)
            return
        calle = self.esc.red.calles()[int(seleccion[0])]
        self._cambiar_estado_calle(calle.origen, calle.destino)

    def _abrir_todas(self) -> None:
        if not self._edicion_permitida():
            return
        self.esc.red.desbloquear_todas()
        self.log("Todas las calles quedaron ABIERTAS.")
        self._tras_cambiar_calles()

    def _cerrar_ejemplo(self) -> None:
        if not self._edicion_permitida():
            return
        for a, b in datos.CALLES_CERRADAS_EJEMPLO:
            if self.esc.red.existe_calle(a, b):
                self.esc.red.bloquear_calle(a, b)
        self.log("Calles de ejemplo bloqueadas: " + ", ".join(f"{a} — {b}" for a, b in datos.CALLES_CERRADAS_EJEMPLO))
        self._tras_cambiar_calles()

    def _aislar_destino(self) -> None:
        if not self._edicion_permitida():
            return
        destino = self.opt_destino.get()
        vecinos = [v for v, _, _ in self.esc.red.vecinos_todos(destino)]
        for v in vecinos:
            self.esc.red.bloquear_calle(destino, v)
        self.log(f"Bloqueo masivo: {len(vecinos)} calles de {destino} bloqueadas. "
                 f"Prueba ahora «Ruta más corta».")
        self._tras_cambiar_calles()

    # ======================================================================================
    # Análisis comparativo y benchmark
    # ======================================================================================
    def _parametros_bench(self):
        return (self.opt_familia.get(),
                _a_entero(self.e_n.get(), 10, 1, 2000),
                _a_entero(self.e_rep.get(), 3, 1, 20),
                _a_real(self.e_max_s.get(), 10.0, 0.5, 600.0),
                _a_entero(self.e_semilla.get(), 7, 1, 99999),
                _a_entero(self.e_cap_kg.get(), 30, 1, 5000))

    def _ejecutar_lote(self) -> None:
        if not self._necesita_repartidores():
            return
        familia, n, repeticiones, max_s, semilla, cap = self._parametros_bench()
        usar_mapa = self.sw_actuales.get() == 1
        red, rv = self.esc.red.copia(), self.red_vial
        rep = self.esc.repartidores[0]
        pedidos_mapa = (self._alcanzables(rep, list(self.esc.obtener_pedidos_ordenables()))
                        if usar_mapa else [])

        def trabajo(cancelar, progreso):
            if usar_mapa:
                ctx = benchmark.Contexto(len(pedidos_mapa), pedidos_mapa, rep, rv.distancia, cap,
                                         red.limites(), cancelar, max_s)
            else:
                ctx = benchmark.contexto_para(n, semilla, red, rep, capacidad_kg=cap, cancelar=cancelar,
                                              tiempo_max_s=max_s, familia=familia)
            return ctx.n, benchmark.comparar(familia, ctx, repeticiones)

        def listo(res):
            tam, filas = res
            self.filas_bench = filas
            self.tabla_bench.delete(*self.tabla_bench.get_children())
            for i, f in enumerate(filas):
                self.tabla_bench.insert("", "end", iid=str(i), values=(
                    f.algoritmo,
                    "—" if f.tiempo_ms is None else f"{f.tiempo_ms:.3f}",
                    "—" if f.distancia_km is None else f"{f.distancia_km:.3f}",
                    "—" if f.valor is None else f"{f.valor:g}",
                    f.optimo_texto,
                    "—" if f.delta_pct is None else f"{f.delta_pct:.1f}",
                    f.complejidad))
            self.log(f"Comparación «{familia}» con N = {tam} (mediana de {repeticiones} repeticiones):")
            for linea in benchmark.a_texto(filas).splitlines():
                self.log("  " + linea)
            for f in filas:
                if f.nota:
                    self.log(f"  · {f.algoritmo}: {f.nota}")

        self._correr(f"Benchmark {familia}", trabajo, listo)

    def _generar_curvas(self) -> None:
        familia, _n, repeticiones, max_s, semilla, cap = self._parametros_bench()
        try:
            tamanos = [int(t) for t in self.e_tamanos.get().replace(";", ",").split(",") if t.strip()]
        except ValueError:
            self._alerta("Los tamaños deben ser enteros separados por comas, ej.: 4,6,8,10,12", "aviso")
            return
        tamanos = [t for t in tamanos if 1 <= t <= 3000]
        if not tamanos:
            self._alerta("Indica al menos un tamaño N entre 1 y 3000.", "aviso")
            return
        red = self.esc.red.copia()

        def trabajo(cancelar, progreso):
            return benchmark.curva_tiempos(familia, tamanos, semilla, red, repeticiones, max_s, cap,
                                           cancelar, progreso)

        def listo(curvas):
            self.curvas = curvas
            self._redibujar_curvas()
            self.log(f"Gráfica Tiempo vs N («{familia}», N = {', '.join(map(str, sorted(set(tamanos))))}).")
            for nota in curvas.notas:
                self.log("  " + nota)
            for nombre, puntos in curvas.series.items():
                self.log(f"  {nombre}: " + ", ".join(f"N={n}: {ms:.3f} ms" for n, ms in puntos))

        self._correr(f"Curvas {familia}", trabajo, listo)

    @staticmethod
    def _dibujar_curvas(fig: Figure, curvas, escala_log: bool) -> None:
        """Dibuja Tiempo de ejecución vs N en 'fig' (fondo blanco, apto para el informe)."""
        fig.clear()
        ax = fig.add_subplot(111)
        hay = curvas is not None and any(curvas.series.values())
        if not hay:
            ax.text(0.5, 0.5, "Pulsa «Generar gráfica» para medir\nTiempo de ejecución vs N",
                    ha="center", va="center", color="#6b7280", transform=ax.transAxes)
            ax.set_axis_off()
            return
        for nombre, puntos in curvas.series.items():
            if not puntos:
                continue
            ns, ms = zip(*puntos)
            ax.plot(ns, [max(m, 1e-4) for m in ms], marker="o", linewidth=2, markersize=5,
                    label=nombre, color=color_de_curva(nombre))
        ax.set_xlabel("Tamaño de entrada N (pedidos)")
        ax.set_ylabel("Tiempo de ejecución (ms)")
        ax.set_title(f"Tiempo de ejecución vs N — {curvas.familia}", fontsize=11)
        ax.grid(True, which="both", alpha=0.3)
        if escala_log:
            ax.set_xscale("log")
            ax.set_yscale("log")
        ax.legend(fontsize=7, loc="best")
        fig.tight_layout()

    def _redibujar_curvas(self) -> None:
        self._dibujar_curvas(self.fig, self.curvas, self.sw_log.get() == 1)
        self.canvas_fig.draw_idle()

    def _guardar_grafica(self) -> None:
        if self.curvas is None or not any(self.curvas.series.values()):
            self._alerta("Primero genera la gráfica.", "aviso", 3500)
            return
        ruta = filedialog.asksaveasfilename(
            title="Guardar gráfica", defaultextension=".png", initialfile="tiempo_vs_n.png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")])
        if not ruta:
            return
        fig = Figure(figsize=(8, 5), dpi=200)
        self._dibujar_curvas(fig, self.curvas, self.sw_log.get() == 1)
        fig.savefig(ruta)
        self.log(f"Gráfica guardada en {ruta}")

    def _ampliar_grafica(self) -> None:
        ventana = ctk.CTkToplevel(self)
        ventana.title("Tiempo de ejecución vs N")
        ventana.geometry("1000x650")
        fig = Figure(figsize=(10, 6.2), dpi=100)
        self._dibujar_curvas(fig, self.curvas, self.sw_log.get() == 1)
        lienzo = FigureCanvasTkAgg(fig, master=ventana)
        lienzo.get_tk_widget().pack(fill="both", expand=True)
        lienzo.draw()
        ventana.after(200, ventana.lift)

    # ======================================================================================
    # Calles reales (OpenStreetMap)
    # ======================================================================================
    def _actualizar_etiqueta_calles(self) -> None:
        red = self.esc.red
        reales = sum(1 for c in red.calles() if c.geometria)
        if reales:
            self.lbl_calles.configure(text=f"Calles reales: {reales}/{len(red.calles())}", text_color="#15803d")
        else:
            self.lbl_calles.configure(text="Calles: rectas (sin trazado real)", text_color="#b45309")

    def _aplicar_cache_calles(self, cache, avisar: bool = True) -> bool:
        """Copia el trazado real a la red del escenario y recoloca pedidos y repartidores."""
        if not cache:
            return False
        resumen = calles_reales.aplicar(self.esc.red, cache, usar_largo_real=self.sw_largo_real.get() == 1)
        if not resumen["calles_reales"]:
            return False
        self.esc.reubicar()
        self._limpiar_resultados()
        self._refrescar_todo()
        self._actualizar_etiqueta_calles()
        self.log(f"Trazado real aplicado: {resumen['calles_reales']} calles siguen las vías de OpenStreetMap"
                 f"{', ' + str(resumen['calles_rectas']) + ' quedan en recta' if resumen['calles_rectas'] else ''}"
                 f"; {resumen['nodos_movidos']} nodos se pegaron a la intersección real más cercana.")
        if avisar:
            self._alerta("Las rutas ahora siguen las calles reales.", "ok", 4000)
        return True

    def _iniciar_calles_reales(self, forzar: bool = False, automatico: bool = False) -> None:
        """Usa la caché de calles reales o la descarga de OSM en un hilo (sin bloquear nada)."""
        if not forzar:
            cache = calles_reales.cargar_cache()
            if cache is not None and calles_reales._cubre_red(cache, self.esc.red):
                self._aplicar_cache_calles(cache, avisar=not automatico)
                return
        if self._descargando_calles:
            self._alerta("Ya se están descargando las calles reales...", "aviso", 3000)
            return
        self._descargando_calles = True
        self.btn_calles.configure(state="disabled")
        self.lbl_calles.configure(text="Descargando calles reales...", text_color="#1d4ed8")
        self.log("Descargando el trazado real de las calles desde OpenStreetMap (solo la primera vez; "
                 "después queda guardado en datos_ejemplo/calles_osm_cusco.json)...")
        red = self.esc.red.copia()
        cola: queue.Queue = queue.Queue()
        self._cola_calles = cola

        def trabajo() -> None:
            try:
                cache = calles_reales.obtener(red, forzar=True,
                                              progreso=lambda f, t: cola.put(("prog", f, t)))
                cola.put(("ok", cache))
            except calles_reales.ErrorDescarga as error:
                cola.put(("err", str(error)))
            except Exception:  # noqa: BLE001
                cola.put(("err", traceback.format_exc()))

        threading.Thread(target=trabajo, daemon=True, name="calles-osm").start()
        self.after(150, self._sondear_calles)

    def _boton_calles_reales(self) -> None:
        """Sin trazado: lo carga de la caché o lo descarga. Con trazado: lo vuelve a descargar."""
        if self.esc.red.tiene_trazado_real():
            if not messagebox.askyesno("Calles reales", "Las calles ya siguen el trazado real.\n"
                                       "¿Descargar de nuevo los datos de OpenStreetMap?"):
                return
            self._iniciar_calles_reales(forzar=True)
        else:
            self._iniciar_calles_reales(forzar=False)

    def _sondear_calles(self) -> None:
        final = None
        try:
            while True:
                m = self._cola_calles.get_nowait()
                if m[0] == "prog":
                    self.lbl_calles.configure(text=m[2][:48])
                else:
                    final = m
                    break
        except queue.Empty:
            pass
        if final is None:
            self.after(150, self._sondear_calles)
            return
        if final[0] == "ok" and self._ocupado:      # se aplica cuando termine la tarea en curso
            self._cola_calles.put(final)
            self.after(300, self._sondear_calles)
            return
        self._descargando_calles = False
        self.btn_calles.configure(state="normal")
        if final[0] == "ok":
            self.log(calles_reales.resumen_texto(final[1]))
            self._aplicar_cache_calles(final[1])
        else:
            self._actualizar_etiqueta_calles()
            self.log("No se pudo obtener el trazado real: " + final[1].splitlines()[-1])
            self._alerta("Sin conexión con OpenStreetMap: las calles siguen en recta. "
                         "Pulsa «Calles reales (OSM)» para reintentar.", "aviso", 9000)

    def _cambiar_largo_real(self) -> None:
        if not self.esc.red.tiene_trazado_real():
            return
        if not self._edicion_permitida():
            return
        cache = calles_reales.cargar_cache()
        if cache:
            usar = self.sw_largo_real.get() == 1
            calles_reales.aplicar(self.esc.red, cache, usar_largo_real=usar, mover_nodos=False)
            self._limpiar_resultados()
            self._refrescar_todo()
            self.log("Distancias: " + ("largo REAL medido sobre las calles de OpenStreetMap." if usar else
                                       "largo SINTÉTICO (distancia geodésica × sinuosidad), como en el plan de tesis."))

    # ======================================================================================
    # Exportar rutas (GPX / CSV) y abrir en Google Maps
    # ======================================================================================
    def _exportar_rutas(self) -> None:
        if not self.ultimas_rutas:
            self._alerta("Primero calcula alguna ruta (Voraz, Divide y Vencerás, Held-Karp o Backtracking).",
                         "aviso", 4500)
            return
        ruta = filedialog.asksaveasfilename(
            title="Exportar rutas", defaultextension=".gpx", initialfile="rutas_cusco.gpx",
            filetypes=[("GPX (GPS, Google Earth, OsmAnd)", "*.gpx"), ("CSV (Excel)", "*.csv")])
        if not ruta:
            return
        try:
            if ruta.lower().endswith(".csv"):
                exportar.a_csv(self.ultimas_rutas, ruta)
            else:
                exportar.a_gpx(self.ultimas_rutas, ruta)
        except OSError as error:
            messagebox.showerror("Exportar rutas", str(error))
            return
        self.log(f"Rutas exportadas a {ruta}")
        self._alerta("Rutas exportadas.", "ok", 3000)

    def _abrir_google_maps(self) -> None:
        rutas = [r for r in self.ultimas_rutas if r.coords]
        if not rutas:
            self._alerta("Primero calcula alguna ruta.", "aviso", 3500)
            return
        for r in rutas:
            for i, url in enumerate(exportar.urls_google_maps(r)):
                self.log(f"Google Maps · {r.nombre}{f' (parte {i + 1})' if i else ''}: {url}")
        try:
            webbrowser.open(exportar.urls_google_maps(rutas[0])[0])
        except Exception:  # noqa: BLE001 - sin navegador: el enlace queda en la bitácora
            pass

    # ======================================================================================
    # Experimentos E1-E4 (módulo experimentos)
    # ======================================================================================
    def _ejecutar_experimentos(self) -> None:
        carpeta = filedialog.askdirectory(title="Carpeta donde guardar los resultados (CSV y resumen)")
        if not carpeta:
            return
        semillas = _a_entero(self.e_semillas_exp.get(), 30, 2, 200)
        rapido = self.sw_rapido.get() == 1
        red = self.esc.red.copia()
        red.desbloquear_todas()

        def trabajo(cancelar, progreso):
            cfg = experimentos.Configuracion(semillas=semillas, repeticiones=1 if rapido else 5,
                                             red=red, cancelar=cancelar, progreso=progreso,
                                             remuestreos=2000 if rapido else 10_000)
            try:
                return experimentos.ejecutar(cfg, carpeta)
            except experimentos.Cancelado:
                return None

        def listo(res):
            if res is None:
                self.log("Experimentos cancelados.")
                return
            a = res["analisis"]
            self.log(f"Experimentos E1–E4 terminados en {res['extra']['duracion_s']:.1f} s "
                     f"({semillas} semillas por configuración). Archivos en {carpeta}:")
            for archivo in res["archivos"]:
                self.log("  " + os.path.basename(str(archivo)))
            for clave in ("H1", "H2", "H3", "H4a", "H4b", "General"):
                for prueba in a.get(clave, []):
                    self.log(f"  {clave} · {prueba['prueba']}: p Holm = {prueba['p_holm']:.4g} → {prueba['decision']}")
            self._alerta("Experimentos listos: revisa resumen.md en la carpeta elegida.", "ok", 6000)

        self._correr("Experimentos E1-E4", trabajo, listo)


def main() -> None:
    App().mainloop()
