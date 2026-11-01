# Ubicación: src/voces.py
# Reconoce a las personas por la voz entre una grabación y otra.
# Cuando a un hablante se le pone nombre, se guarda su "huella de voz" (el embedding que da
# pyannote) en voces.json, dentro de la carpeta del programa; en la siguiente transcripción
# cada hablante se compara con esas huellas para proponer su nombre. Todo queda en el computador.
# Es Python puro (sin numpy): son unas pocas huellas de ~256 valores y la CLI lo importa rápido.
import re
import time
from typing import Optional

from src import historial
from src.diarizer import DECIMALES_HUELLA, ETIQUETA_GENERICA, normalizar_huella

ARCHIVO_VOCES = "voces.json"

# Parecido mínimo (similitud coseno, de -1 a 1) para proponer un nombre.
# Las huellas son centroides de WeSpeaker ResNet34 (el modelo de embeddings de
# speaker-diarization-community-1): el promedio de toda la voz de una persona en la reunión.
# Con ese modelo, dos trozos cortos de la misma persona suelen dar 0,6-0,8 y de personas
# distintas 0,0-0,3; el punto de equilibrio en VoxCeleb queda cerca de 0,3-0,4. Al promediar
# minutos de voz la misma persona sube (0,7-0,9), pero dos personas en la misma sala y con el
# mismo micrófono también se acercan más que en VoxCeleb. 0,6 queda en medio, del lado prudente:
# es mejor no proponer nada que proponer el nombre equivocado.
# HAY QUE AJUSTARLO con 3-4 reuniones reales de Max: mirar la similitud de cada persona consigo
# misma y con las demás (parecidos(..., umbral=-1) las muestra todas) y dejarlo entre ambas.
UMBRAL = 0.6

# Al actualizar la huella de alguien, las anteriores pesan como máximo esto: así la huella
# sigue adaptándose si cambia el micrófono o la sala, en vez de quedar fija para siempre.
PESO_MAXIMO = 10
# De dónde salió cada huella guardada (para no sumarla dos veces); con las últimas basta
MAX_ORIGENES = 200

# "Hablante 3" no es una persona: no se recuerda
_ETIQUETA_SIN_NOMBRE = re.compile(rf"^{ETIQUETA_GENERICA} \d+$")


def _cargar() -> dict:
    """Las voces guardadas {nombre: {"huella": [...], "veces": int, "actualizada": float}}.
    Si el archivo falta o está dañado, no hay voces; las entradas estropeadas se ignoran."""
    datos = historial._leer(ARCHIVO_VOCES, {})
    voces = {}
    for nombre, entrada in datos.items():
        if not isinstance(entrada, dict):
            continue
        huella = normalizar_huella(entrada.get("huella") or [])
        if huella is None:
            continue
        veces = entrada.get("veces")
        origenes = entrada.get("origenes")
        voces[nombre] = {
            "huella": huella,
            "veces": veces if isinstance(veces, int) and veces > 0 else 1,
            "actualizada": entrada.get("actualizada"),
            "origenes": [o for o in origenes if isinstance(o, str)] if isinstance(origenes, list) else [],
        }
    return voces


def similitud(a: list, b: list) -> float:
    """Similitud coseno entre dos huellas (1 = misma dirección). 0 si no se pueden comparar
    (largos distintos, p. ej. si cambió el modelo, o alguna inválida)."""
    a, b = normalizar_huella(a), normalizar_huella(b)
    if a is None or b is None or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def recordar(nombre: str, huella: list, origen: Optional[str] = None) -> bool:
    """
    Guarda la huella de una persona. Si ya la conocía, la mezcla con la anterior
    (promedio ponderado por las veces que se ha oído, normalizado), así mejora con cada reunión.
    origen ("<ruta del .json>#Hablante 1") identifica de dónde sale la huella: la misma huella no se
    suma dos veces a la misma persona (al cambiar otros nombres de esa transcripción se vuelve a guardar).
    Retorna False si no había nada que guardar (sin nombre, huella inválida o ya sumada).
    """
    nombre = (nombre or "").strip()
    nueva = normalizar_huella(huella or [])
    if not nombre or nueva is None:
        return False

    voces = _cargar()
    anterior = voces.get(nombre)
    if anterior and origen and origen in anterior["origenes"]:
        return False
    if anterior and len(anterior["huella"]) == len(nueva):
        peso = min(anterior["veces"], PESO_MAXIMO)
        mezcla = normalizar_huella([peso * v + n for v, n in zip(anterior["huella"], nueva)])
        # Si se anulan (casi imposible), se queda la nueva
        huella_final, veces = mezcla or nueva, anterior["veces"] + 1
        origenes = anterior["origenes"]
    else:
        # Primera vez, o la huella anterior es de otro modelo (otro largo): se empieza de cero
        huella_final, veces, origenes = nueva, 1, []
    if origen:
        origenes = [*origenes, origen][-MAX_ORIGENES:]

    voces[nombre] = {
        "huella": [round(v, DECIMALES_HUELLA) for v in huella_final],
        "veces": veces,
        "actualizada": time.time(),
        "origenes": origenes,
    }
    historial._escribir(ARCHIVO_VOCES, voces)
    return True


def quitar_origen(origen: str, huella: list, salvo: Optional[str] = None) -> list:
    """
    Deshace lo que una huella sumó a otras personas (salvo a `salvo`): pasa cuando se corrige un
    nombre mal puesto ("Luis,Ana" en vez de "Ana,Luis"), para que la voz de Ana no quede mezclada
    con la de Luis. Si esa persona solo se conocía por esta huella, se olvida. Como las huellas
    guardadas son promedios normalizados, restar es aproximado, pero basta para separarlas.
    Retorna los nombres corregidos.
    """
    quitada = normalizar_huella(huella or [])
    if not origen:
        return []
    voces = _cargar()
    corregidos = []
    for nombre, voz in list(voces.items()):
        if nombre == salvo or origen not in voz["origenes"]:
            continue
        corregidos.append(nombre)
        if voz["veces"] <= 1 or quitada is None or len(quitada) != len(voz["huella"]):
            del voces[nombre]
            continue
        peso = min(voz["veces"], PESO_MAXIMO)
        resto = normalizar_huella([peso * v - q for v, q in zip(voz["huella"], quitada)])
        if resto is None:
            del voces[nombre]
            continue
        voz["huella"] = [round(v, DECIMALES_HUELLA) for v in resto]
        voz["veces"] -= 1
        voz["origenes"] = [o for o in voz["origenes"] if o != origen]
        voz["actualizada"] = time.time()
    if corregidos:
        historial._escribir(ARCHIVO_VOCES, voces)
    return corregidos


def recordar_nombrados(nombres: dict, huellas: dict, fuente: Optional[str] = None) -> list:
    """
    Recuerda a cada hablante que tiene nombre y huella: nombres es {"Hablante 1": "Ana"} y
    huellas {"Hablante 1": [floats]} (las del .blocks.json). Quien lleva la etiqueta genérica
    se omite. fuente (la ruta del .blocks.json) permite volver a llamarla tras cada cambio de nombres
    sin sumar dos veces la misma huella, y corregir a quien se le había dado antes. Retorna los nombres guardados.
    """
    pendientes = []
    for etiqueta, nombre in (nombres or {}).items():
        nombre = (nombre or "").strip()
        if not nombre or _ETIQUETA_SIN_NOMBRE.match(nombre) or etiqueta not in (huellas or {}):
            continue
        pendientes.append((etiqueta, nombre, f"{fuente}#{etiqueta}" if fuente else None))
    # Primero se deshacen todas las asignaciones equivocadas y después se suma: así, al corregir
    # nombres cruzados (Ana <-> Luis), cada voz queda limpia y no un promedio restado a medias
    for etiqueta, nombre, origen in pendientes:
        if origen:
            quitar_origen(origen, huellas[etiqueta], salvo=nombre)
    return [nombre for etiqueta, nombre, origen in pendientes if recordar(nombre, huellas[etiqueta], origen)]


def parecidos(huellas: dict, umbral: float = UMBRAL) -> dict:
    """
    Para cada hablante de una transcripción ({"Hablante 1": [floats], ...}), la persona conocida
    que más se le parece, si supera el umbral: {"Hablante 1": ("Ana", 0.83), ...}.
    Una persona se propone para un solo hablante: si dos se parecen a Ana, gana el más parecido
    y el otro puede quedar con su siguiente opción (si también supera el umbral).
    """
    voces = _cargar()
    pares = [
        (similitud(huella, voz["huella"]), etiqueta, nombre)
        for etiqueta, huella in (huellas or {}).items()
        for nombre, voz in voces.items()
    ]
    # De más a menos parecido; el resto del orden solo hace el resultado predecible ante empates
    pares.sort(key=lambda par: (-par[0], par[1], par[2]))

    propuestas, usados = {}, set()
    for parecido, etiqueta, nombre in pares:
        if parecido < umbral:
            break
        if etiqueta in propuestas or nombre in usados:
            continue
        propuestas[etiqueta] = (nombre, round(parecido, 3))
        usados.add(nombre)
    return propuestas


def conocidas() -> list:
    """Los nombres de las personas cuya voz está guardada, en orden alfabético."""
    return sorted(_cargar(), key=str.casefold)


def olvidar(nombre: str) -> bool:
    """Borra la huella de una persona. Retorna False si no estaba."""
    voces = historial._leer(ARCHIVO_VOCES, {})
    if nombre not in voces:
        return False
    del voces[nombre]
    historial._escribir(ARCHIVO_VOCES, voces)
    return True


def olvidar_todas():
    """Borra todas las huellas guardadas."""
    historial._escribir(ARCHIVO_VOCES, {})
