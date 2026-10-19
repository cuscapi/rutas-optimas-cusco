"""Ordenacion y busqueda de pedidos (estructuras, ordenacion y busqueda)."""


def merge_sort(datos, clave, inverso=False):
    """MergeSort estable. Divide en mitades, ordena y fusiona.

    Tiempo O(n log n) en todos los casos, espacio O(n).
    Recurrencia: T(n) = 2T(n/2) + O(n).
    """
    if len(datos) <= 1:
        return list(datos)
    medio = len(datos) // 2
    izq = merge_sort(datos[:medio], clave, inverso)
    der = merge_sort(datos[medio:], clave, inverso)
    return _fusionar(izq, der, clave, inverso)


def _fusionar(izq, der, clave, inverso):
    """Fusiona dos listas ya ordenadas en una sola. O(n)."""
    resultado = []
    i = j = 0
    while i < len(izq) and j < len(der):
        a, b = clave(izq[i]), clave(der[j])
        tomar_izq = a >= b if inverso else a <= b
        if tomar_izq:
            resultado.append(izq[i])
            i += 1
        else:
            resultado.append(der[j])
            j += 1
    resultado.extend(izq[i:])
    resultado.extend(der[j:])
    return resultado


def heap_sort(datos, clave, inverso=False):
    """HeapSort: construye un max-heap y extrae el mayor repetidamente.

    Tiempo O(n log n) en todos los casos, espacio extra O(1) (copia aparte).
    No es estable.
    """
    arr = list(datos)
    n = len(arr)

    def hundir(raiz, fin):
        while True:
            mayor = raiz
            izq, der = 2 * raiz + 1, 2 * raiz + 2
            if izq < fin and clave(arr[izq]) > clave(arr[mayor]):
                mayor = izq
            if der < fin and clave(arr[der]) > clave(arr[mayor]):
                mayor = der
            if mayor == raiz:
                return
            arr[raiz], arr[mayor] = arr[mayor], arr[raiz]
            raiz = mayor

    for i in range(n // 2 - 1, -1, -1):
        hundir(i, n)
    for fin in range(n - 1, 0, -1):
        arr[0], arr[fin] = arr[fin], arr[0]
        hundir(0, fin)
    if inverso:
        arr.reverse()
    return arr


def busqueda_binaria(ordenada, valor, clave):
    """Busqueda binaria sobre una lista ordenada por 'clave'.

    Devuelve (elemento o None, numero de comparaciones). O(log n).
    """
    izq, der = 0, len(ordenada) - 1
    comparaciones = 0
    while izq <= der:
        medio = (izq + der) // 2
        comparaciones += 1
        k = clave(ordenada[medio])
        if k == valor:
            return ordenada[medio], comparaciones
        if k < valor:
            izq = medio + 1
        else:
            der = medio - 1
    return None, comparaciones


def construir_indice_sectores(pedidos):
    """Indice {sector: [pedidos]} para buscar por sector. Construccion O(n)."""
    indice = {}
    for p in pedidos:
        indice.setdefault(p.sector, []).append(p)
    return indice


def quick_sort(datos, clave, inverso=False):
    """QuickSort con pivote aleatorio y partición en tres (menores / iguales / mayores).

    Iterativo (pila explícita) para no desbordar la recursión con datos muy repetidos.
    Tiempo promedio O(n log n), peor caso O(n^2) (improbable con pivote aleatorio),
    espacio O(n) en esta versión funcional. No es estable.
    """
    import random
    arr = list(datos)
    if len(arr) <= 1:
        return arr
    azar = random.Random(len(arr))  # semilla fija: resultados reproducibles
    resultado = []
    pila = [arr]
    # Se apilan en orden inverso para que los trozos salgan de menor a mayor.
    while pila:
        trozo = pila.pop()
        if isinstance(trozo, tuple):          # bloque de iguales ya resuelto
            resultado.extend(trozo[0])
            continue
        if len(trozo) <= 1:
            resultado.extend(trozo)
            continue
        pivote = clave(trozo[azar.randrange(len(trozo))])
        menores = [e for e in trozo if clave(e) < pivote]
        iguales = [e for e in trozo if clave(e) == pivote]
        mayores = [e for e in trozo if clave(e) > pivote]
        pila.append(mayores)
        pila.append((iguales,))
        pila.append(menores)
    if inverso:
        resultado.reverse()
    return resultado


class IndicePedidos:
    """Índices hash para buscar pedidos sin recorrer la lista.

    * ``por_id``: diccionario id -> pedido (búsqueda O(1) promedio).
    * ``por_cliente``: diccionario nombre normalizado -> [pedidos] (O(1) promedio).
    La construcción es O(n). Después de agregar o quitar pedidos hay que reconstruirlo.
    """

    def __init__(self, pedidos):
        self.por_id = {}
        self.por_cliente = {}
        for p in pedidos:
            self.por_id[p.id.upper()] = p
            self.por_cliente.setdefault(self._normalizar(p.cliente), []).append(p)

    @staticmethod
    def _normalizar(texto):
        return " ".join(str(texto).split()).casefold()

    def buscar_id(self, id_):
        """Pedido con ese ID (sin distinguir mayúsculas) o None. O(1)."""
        return self.por_id.get(str(id_).strip().upper())

    def buscar_cliente(self, nombre):
        """Lista de pedidos de ese cliente (nombre exacto, sin mayúsculas ni espacios
        sobrantes). O(1)."""
        return list(self.por_cliente.get(self._normalizar(nombre), []))

    def buscar_cliente_parcial(self, texto):
        """Pedidos cuyo cliente contiene 'texto'. Recorre los clientes: O(c)."""
        clave = self._normalizar(texto)
        return [p for nombre, lista in self.por_cliente.items() if clave in nombre for p in lista]
