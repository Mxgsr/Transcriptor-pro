# Ubicación: src/buscar.py
# Búsqueda de una palabra o frase en todas las transcripciones del historial («Mis transcripciones»).
# Sin tildes ni mayúsculas, y con todas las palabras de la consulta dentro del mismo párrafo.
# No imprime nada ni pregunta nada: devuelve coincidencias para que el menú las muestre.
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src import historial
from utils import formatters

logger = logging.getLogger(__name__)

SUFIJO_TXT = ".blocks.txt"
MAXIMO_ETIQUETA = 110
_FECHA_AL_INICIO = re.compile(r"^(\d{4}-\d{2}-\d{2})")


@dataclass
class Coincidencia:
    txt: Path
    json: Optional[Path]
    audio: Optional[Path]
    titulo: str
    fecha: Optional[str]      # AAAA-MM-DD si se sabe
    inicio: float             # segundos donde empieza el párrafo
    hablante: Optional[str]   # ya con el nombre puesto
    fragmento: str


def _normalizar_con_mapa(texto: str) -> tuple:
    """
    Devuelve (texto normalizado, mapa) donde mapa[i] es la posición en el original del
    carácter i del normalizado. Se hace carácter a carácter porque algunas letras compuestas
    cambian de largo al normalizarse, y así el trozo que se muestra no se desfasa.
    """
    salida = []
    mapa = []
    for i, c in enumerate(texto):
        if c.isspace():
            # Espacios seguidos (y saltos de línea) cuentan como uno solo
            if salida and salida[-1] != " ":
                salida.append(" ")
                mapa.append(i)
            continue
        for d in unicodedata.normalize("NFD", c.lower()):
            if unicodedata.category(d) != "Mn":
                salida.append(d)
                mapa.append(i)
    # Sin espacio sobrante al final (al inicio nunca se pone uno)
    if salida and salida[-1] == " ":
        salida.pop()
        mapa.pop()
    return "".join(salida), mapa


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni diacríticos (la ñ queda como n) y espacios colapsados."""
    return _normalizar_con_mapa(texto)[0]


def fragmento(texto: str, consulta: str, largo: int = 90) -> str:
    """
    Un trozo del texto alrededor de la primera coincidencia (de la primera palabra de la consulta),
    cortado en límites de palabra, con «…» donde se cortó.
    """
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) <= largo:
        return texto
    normalizado, mapa = _normalizar_con_mapa(texto)
    palabras = normalizar(consulta).split()
    pos = normalizado.find(palabras[0]) if palabras else -1
    centro = mapa[pos] if 0 <= pos < len(mapa) else 0
    inicio = max(0, centro - largo // 3)
    fin = min(len(texto), inicio + largo)
    inicio = max(0, fin - largo)
    # Cortar en límite de palabra: no dejar media palabra pegada al borde
    if inicio > 0 and texto[inicio - 1] != " ":
        espacio = texto.find(" ", inicio)
        inicio = espacio + 1 if 0 <= espacio < centro else inicio
    if fin < len(texto) and texto[fin] != " ":
        espacio = texto.rfind(" ", inicio, fin)
        fin = espacio if espacio > centro else fin
    trozo = texto[inicio:fin].strip()
    return ("…" if inicio > 0 else "") + trozo + ("…" if fin < len(texto) else "")


def etiqueta(c: Coincidencia) -> str:
    """Una línea para el menú: «2026-11-01 Reunión · 00:12:30 · Ana: …el presupuesto de…»."""
    titulo = c.titulo
    if c.fecha and not titulo.startswith(c.fecha):
        titulo = f"{c.fecha} {titulo}"
    quien = f"{c.hablante}: " if c.hablante else ""
    inicio = f"{titulo} · {formatters.format_timestamp_hhmmss(c.inicio)} · {quien}"
    sobra = MAXIMO_ETIQUETA - len(inicio)
    texto = c.fragmento
    if len(texto) > max(sobra, 20):
        texto = texto[:max(sobra, 20) - 1].rstrip() + "…"
    return inicio + texto


def _parrafos_de(entrada: dict) -> tuple:
    """(titulo, fecha, parrafos) de una transcripción. Lanza si el archivo no se puede leer."""
    json_path = entrada.get("json")
    txt = Path(entrada["txt"])
    nombre = txt.name[:-len(SUFIJO_TXT)] if txt.name.endswith(SUFIJO_TXT) else txt.stem
    if json_path:
        # Importación diferida: el diarizador no hace falta para el resto del programa
        from src.diarizer import aplicar_nombres

        datos = formatters.cargar_transcripcion(json_path)
        parrafos = aplicar_nombres(datos["parrafos"], datos["nombres"])
        titulo = datos["titulo"] or nombre
        fecha = datos["fecha"].isoformat() if datos["fecha"] else None
        return titulo, fecha, parrafos
    encabezado, parrafos = formatters.leer_parrafos_del_txt(txt)
    titulo = encabezado.get("titulo") or nombre
    coincide = _FECHA_AL_INICIO.match(txt.name)
    fecha = coincide.group(1) if coincide else None
    return titulo, fecha, parrafos


def buscar(consulta: str, entradas: Optional[list] = None, maximo: int = 200) -> list:
    """
    Los párrafos que contienen todas las palabras de la consulta (sin importar tildes ni
    mayúsculas), en el orden de las transcripciones y dentro de cada una por tiempo.
    Un archivo ilegible se salta: nunca rompe la búsqueda.
    """
    palabras = normalizar(consulta).split()
    if not palabras:
        return []
    if entradas is None:
        entradas = historial.listar()

    resultado = []
    for entrada in entradas:
        try:
            titulo, fecha, parrafos = _parrafos_de(entrada)
            encontrados = []
            for p in parrafos:
                texto = p.get("text") or ""
                normal = normalizar(texto)
                if all(w in normal for w in palabras):
                    encontrados.append(Coincidencia(
                        txt=Path(entrada["txt"]), json=entrada.get("json"), audio=entrada.get("audio"),
                        titulo=titulo, fecha=fecha, inicio=float(p.get("start") or 0),
                        hablante=p.get("speaker") or None, fragmento=fragmento(texto, consulta),
                    ))
        except Exception as e:  # noqa: BLE001 - un archivo dañado no debe impedir buscar en los demás
            logger.info(f"Se salta {entrada.get('txt')} en la búsqueda: {e}")
            continue
        encontrados.sort(key=lambda c: c.inicio)
        resultado.extend(encontrados)
        if len(resultado) >= maximo:
            return resultado[:maximo]
    return resultado
