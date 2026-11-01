# Ubicación: src/dudosas.py
# Frases cuyo hablante es dudoso (marcadas al diarizar) y la lógica para revisarlas y corregirlas.
# Sin pantalla: solo trabaja con la lista de párrafos del .blocks.json (con etiquetas genéricas
# "Hablante N"); el menú se encarga de preguntar y de llamar a estas funciones.
import copy
from dataclasses import dataclass
from pathlib import Path

from utils.formatters import cargar_transcripcion, guardar_json

# Cuántos párrafos como máximo se revisan de una vez: más cansa y deja de ser útil
MAXIMO_DUDOSAS = 40
# Un párrafo así de corto, rodeado por la misma otra persona, casi seguro es de ella
MAX_PALABRAS_ENTRE_OTRO = 4
# Orden de revisión: lo más probable de ser un error primero
_PRIORIDAD = {"repartida": 0, "fuera_de_turno": 0, "entre_otro": 1, "borde": 2}


@dataclass
class Dudosa:
    indice: int      # posición del párrafo en la lista
    start: float
    end: float
    texto: str
    actual: str      # etiqueta genérica del hablante actual del párrafo
    otro: str        # etiqueta genérica del hablante alternativo
    motivo: str      # repartida, fuera_de_turno, borde o entre_otro


def nombre_visible(etiqueta: str, nombres: dict) -> str:
    """El nombre puesto a esa etiqueta ("Ana"), o la etiqueta genérica si no tiene."""
    return (nombres or {}).get(etiqueta) or etiqueta


def _normal(texto: str) -> str:
    return " ".join((texto or "").split())


def _posicion(texto: str, frase: str, start: float, inicio: float, fin: float) -> int:
    """
    Dónde empieza la frase dentro del texto del párrafo (ambos normalizados), o -1.
    Solo cuenta si calza con palabras enteras: «no.» no debe encontrarse dentro de «Bueno.»
    (partir ahí cortaría la palabra en dos). Si la frase sale varias veces («Sí.»), se elige
    la más cercana a donde debería estar según su minuto dentro del párrafo.
    """
    if not frase:
        return -1
    candidatas, desde = [], 0
    while (pos := texto.find(frase, desde)) >= 0:
        final = pos + len(frase)
        if (pos == 0 or texto[pos - 1] == " ") and (final == len(texto) or texto[final] == " "):
            candidatas.append(pos)
        desde = pos + 1
    if len(candidatas) <= 1:
        return candidatas[0] if candidatas else -1
    duracion = fin - inicio
    esperada = (start - inicio) / duracion * len(texto) if duracion > 0 else 0
    return min(candidatas, key=lambda p: abs(p - esperada))


def posicion_en_parrafo(parrafo: dict, d: "Dudosa") -> int:
    """Dónde empieza la frase de d en el texto normalizado del párrafo (para resaltarla), o -1."""
    return _posicion(_normal(parrafo.get("text")), d.texto, d.start,
                     parrafo.get("start", d.start), parrafo.get("end", d.end))


def buscar_dudosas(parrafos: list, maximo: int = MAXIMO_DUDOSAS, nombres: dict = None) -> list:
    """
    Las frases a revisar, ordenadas: primero "repartida" y "fuera_de_turno", luego "entre_otro"
    y al final "borde"; dentro de cada grupo, por tiempo. Se corta en `maximo`.
    Usa las marcas "dudosas" de cada párrafo (solo si la frase aún está en su texto y la otra
    persona no es la del párrafo). En .json antiguos, sin marcas, también detecta "entre_otro":
    un párrafo de pocas palabras entre dos párrafos de una misma otra persona.
    Con nombres ({"Hablante 1": "Ana"}), se omiten las dudas entre dos etiquetas con el mismo nombre
    (se unieron con «Es la misma persona que…»): preguntar «¿Ana o Ana?» no tiene sentido.
    """
    encontradas = []
    con_marca = set()
    for i, parrafo in enumerate(parrafos):
        hablante = parrafo.get("speaker")
        if hablante is None:
            continue
        texto = _normal(parrafo.get("text"))
        for marca in parrafo.get("dudosas") or []:
            frase = _normal(marca.get("text"))
            otro = marca.get("otro")
            if (not otro or otro == hablante
                    or _posicion(texto, frase, marca.get("start", parrafo["start"]),
                                 parrafo["start"], parrafo["end"]) < 0):
                continue
            encontradas.append(Dudosa(i, marca.get("start", parrafo["start"]), marca.get("end", parrafo["end"]),
                                      frase, hablante, otro, marca.get("motivo", "borde")))
            con_marca.add(i)

    for i in range(1, len(parrafos) - 1):
        parrafo = parrafos[i]
        hablante = parrafo.get("speaker")
        antes, despues = parrafos[i - 1].get("speaker"), parrafos[i + 1].get("speaker")
        if (hablante is None or i in con_marca or parrafo.get("revisado")
                or len(_normal(parrafo.get("text")).split()) > MAX_PALABRAS_ENTRE_OTRO
                or antes is None or antes != despues or antes == hablante):
            continue
        encontradas.append(Dudosa(i, parrafo["start"], parrafo["end"], _normal(parrafo["text"]),
                                  hablante, antes, "entre_otro"))

    if nombres:
        encontradas = [d for d in encontradas
                       if nombre_visible(d.actual, nombres) != nombre_visible(d.otro, nombres)]
    encontradas.sort(key=lambda d: (_PRIORIDAD.get(d.motivo, 2), d.start))
    return encontradas[:maximo]


def _sin_marca(marcas: list, d: Dudosa) -> list:
    """Las marcas sin la que corresponde a la frase de d."""
    return [m for m in marcas if _normal(m.get("text")) != d.texto or m.get("otro") != d.otro]


def mover_frase(parrafos: list, d: Dudosa, nuevo: str) -> list:
    """
    Una lista NUEVA de párrafos donde la frase de d es del hablante `nuevo` (la de entrada no cambia).
    Si la frase es todo el párrafo, cambia su hablante; si está al principio o al final, se separa
    en su propio párrafo; si está en medio, el párrafo se parte en tres. Un párrafo tocado se une
    con el vecino si este ya es del hablante nuevo. Las demás marcas pasan al trozo que contiene
    su texto y la marca resuelta se quita.
    """
    lista = copy.deepcopy(parrafos)
    if not 0 <= d.indice < len(lista) or nuevo == lista[d.indice].get("speaker"):
        return lista
    original = lista[d.indice]
    texto = _normal(original.get("text"))
    pos = _posicion(texto, d.texto, d.start, original["start"], original["end"])
    if pos < 0:
        return lista
    antes, despues = texto[:pos].strip(), texto[pos + len(d.texto):].strip()
    marcas = _sin_marca(original.get("dudosas") or [], d)
    inicio_p, fin_p = original["start"], original["end"]
    # Los tiempos de la frase se sujetan al párrafo, para que nunca queden al revés
    f_ini = min(max(d.start, inicio_p), fin_p)
    f_fin = min(max(d.end, f_ini), fin_p)

    if not antes and not despues:
        # «revisado»: la persona ya decidió de quién es; sin esto, la frase recién movida (corta y
        # entre dos párrafos de otra persona) se volvería a proponer como «entre_otro»
        entero = {**original, "text": texto, "speaker": nuevo, "revisado": True}
        entero.pop("dudosas", None)
        if marcas:
            entero["dudosas"] = marcas
        piezas = [(entero, True)]
    else:
        # Lo que no cambia de un párrafo partido (se descarta el texto original: ya no vale)
        base = {k: v for k, v in original.items()
                if k not in ("text", "start", "end", "speaker", "dudosas", "texto_original", "revisado")}
        trozos = []  # (texto, start, end, hablante, tocado)
        if antes:
            trozos.append((antes, inicio_p, f_ini, original["speaker"], False))
        trozos.append((d.texto, f_ini, f_fin, nuevo, True))
        if despues:
            trozos.append((despues, f_fin, fin_p, original["speaker"], False))
        piezas = []
        for t, ini, fin, hablante, tocado in trozos:
            propias = [m for m in marcas if _normal(m.get("text")) in t]
            pieza = {**base, "start": ini, "end": fin, "text": t, "speaker": hablante}
            if tocado:
                pieza["revisado"] = True  # ver arriba: que no se vuelva a proponer
            if propias:
                pieza["dudosas"] = propias
            piezas.append((pieza, tocado))
        # Cada marca va a un solo trozo (el primero que la contiene)
        vistas = set()
        for pieza, _ in piezas:
            if "dudosas" in pieza:
                pieza["dudosas"] = [m for m in pieza["dudosas"] if id(m) not in vistas]
                vistas.update(id(m) for m in pieza["dudosas"])
                if not pieza["dudosas"]:
                    del pieza["dudosas"]

    # Se une solo si se tocó: así no se deshacen los cortes por pausa que ya había. Tras unir, la
    # marca de «tocado» es la de la pieza que llega: el trozo movido se une con el anterior y con el
    # siguiente, pero no sigue tragándose los párrafos posteriores del mismo hablante.
    resultado = [(p, False) for p in lista[:d.indice]] + piezas + [(p, False) for p in lista[d.indice + 1:]]
    unidos = []
    for pieza, tocado in resultado:
        if unidos and unidos[-1][0].get("speaker") == pieza.get("speaker") and (tocado or unidos[-1][1]):
            unidos[-1] = (_unir(unidos[-1][0], pieza), tocado)
        else:
            unidos.append((pieza, tocado))
    return [p for p, _ in unidos]


def _unir(a: dict, b: dict) -> dict:
    """Junta dos párrafos seguidos del mismo hablante."""
    unido = {**a, "text": f"{a['text']} {b['text']}".strip(),
             "start": min(a["start"], b["start"]), "end": max(a["end"], b["end"])}
    unido.pop("revisado", None)
    unido.pop("texto_original", None)
    marcas = (a.get("dudosas") or []) + (b.get("dudosas") or [])
    if marcas:
        unido["dudosas"] = marcas
    else:
        unido.pop("dudosas", None)
    return unido


def marcar_bien(parrafos: list, d: Dudosa) -> list:
    """
    Una copia donde la frase de d ya no se propone: se quita su marca. Un "entre_otro" no tiene
    marca, así que el párrafo guarda "revisado": True y buscar_dudosas lo respeta.
    """
    lista = copy.deepcopy(parrafos)
    if not 0 <= d.indice < len(lista):
        return lista
    parrafo = lista[d.indice]
    if d.motivo == "entre_otro":
        parrafo["revisado"] = True
    marcas = _sin_marca(parrafo.get("dudosas") or [], d)
    if marcas:
        parrafo["dudosas"] = marcas
    else:
        parrafo.pop("dudosas", None)
    return lista


def guardar(json_path: Path, parrafos: list) -> tuple:
    """
    Guarda los párrafos en el .json conservando audio, nombres, huellas, título, fecha y duración,
    y rehace el .txt (con los nombres y el encabezado que tenga). Retorna lo que retorna
    procesador.renombrar_hablantes: (ruta del TXT, párrafos con los nombres aplicados).
    """
    # Importación diferida: procesador importa muchas cosas y aquí solo hace falta al guardar
    from src.procesador import renombrar_hablantes

    json_path = Path(json_path)
    datos = cargar_transcripcion(json_path)
    guardar_json(parrafos, json_path, audio=Path(datos["audio"]) if datos["audio"] else None,
                 nombres=datos["nombres"], huellas=datos["huellas"], titulo=datos["titulo"],
                 fecha=datos["fecha"], duracion=datos["duracion"])
    return renombrar_hablantes(json_path, {})
