# Ubicación: utils/formatters.py
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

from utils.archivos import escribir_json, escribir_texto

# Nuestro auditor local
logger = logging.getLogger(__name__)

# Hay tres formatos de tiempo, cada uno para un uso distinto (no se pueden unir sin cambiar lo que se ve):
# - format_timestamp_hhmmss: fijo y con ceros ("00:42:10"), para el .txt que lee el Grabador; redondea.
# - formato_reloj: corto ("42:10" o "1:02:05"), para el avance y los fragmentos en pantalla; trunca.
# - formato_duracion: en palabras ("1 min 48 s"), para resúmenes y avisos.
def format_timestamp_hhmmss(seconds: float) -> str:
    """Convierte segundos a formato HH:MM:SS."""
    seconds = max(0, seconds)
    total_seconds = int(round(seconds))
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def formato_reloj(segundos: float) -> str:
    """Convierte segundos a '42:10' o '1:02:05'."""
    segundos = int(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def formato_duracion(segundos: float) -> str:
    """Convierte segundos a un texto corto: '3 s', '1 min 48 s', '1 h 02 min'."""
    segundos = int(round(segundos))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"

# A mano, sin locale: en Windows el idioma del sistema puede no ser español
MESES_COMPLETOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                   "septiembre", "octubre", "noviembre", "diciembre"]

def fecha_en_espanol(fecha: date) -> str:
    """date(2026, 10, 30) -> '30 de octubre de 2026'."""
    return f"{fecha.day} de {MESES_COMPLETOS[fecha.month - 1]} de {fecha.year}"

def a_fecha(valor) -> Optional[date]:
    """Acepta un date, un texto AAAA-MM-DD o None; lo que no se entienda da None."""
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None

# Lo que Windows o Mac no permiten en un nombre de archivo, más los caracteres de control
_PROHIBIDOS_EN_NOMBRE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
LARGO_MAXIMO_NOMBRE = 120

def nombre_de_archivo_seguro(texto: str, defecto: str = "Reunión") -> str:
    """Quita lo que no se puede usar en un nombre de archivo y lo acorta. Sin nada útil, devuelve defecto."""
    limpio = _PROHIBIDOS_EN_NOMBRE.sub("", texto)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    # Windows no admite espacios ni puntos al final (ni "..")
    limpio = limpio[:LARGO_MAXIMO_NOMBRE].rstrip(" .")
    return limpio.lstrip() or defecto

def participantes_en_orden(parrafos: list) -> list:
    """Los nombres de los hablantes en orden de aparición, sin repetir."""
    vistos = []
    for p in parrafos:
        hablante = p.get("speaker")
        if hablante and hablante not in vistos:
            vistos.append(hablante)
    return vistos

def encabezado_de_transcripcion(titulo: str, fecha: Optional[date], duracion: Optional[float],
                                parrafos: list) -> str:
    """
    El bloque de arriba del .txt (título, fecha, duración, participantes) y una línea en blanco.
    Las líneas de las que no hay dato (p. ej. participantes sin hablantes) no se escriben.
    """
    lineas = [f"# {titulo}"]
    if fecha:
        lineas.append(f"Fecha: {fecha_en_espanol(fecha)}")
    if duracion:
        lineas.append(f"Duración: {formato_duracion(duracion)}")
    participantes = participantes_en_orden(parrafos)
    if participantes:
        lineas.append(f"Participantes: {', '.join(participantes)}")
    return "\n".join(lineas) + "\n\n"

def texto_con_hablante(seg: dict) -> str:
    """Antepone el nombre del hablante al texto cuando hay diarización."""
    text = seg["text"].strip()
    if text and seg.get("speaker"):
        return f"{seg['speaker']}: {text}"
    return text

def guardar_txt_con_timestamps(segments_agrupados: list, output_path: Path, encabezado: str = ""):
    """Guarda los segmentos transcritos en un archivo de texto legible (con encabezado arriba, si se da)."""
    lines = []
    for seg in segments_agrupados:
        ts = format_timestamp_hhmmss(seg["start"])
        text = texto_con_hablante(seg)
        if text:
            lines.append(f"[{ts}] {text}")

    output_path = Path(output_path)
    try:
        escribir_texto(output_path, encabezado + "\n\n".join(lines), crear_carpeta=False)
        logger.info(f"Archivo TXT guardado en: {output_path}")
        
    except IOError as e:
        logger.error(f"Error crítico guardando el archivo TXT en {output_path}: {e}")
        raise

def guardar_json(segments_agrupados: list, output_path: Path, audio: Optional[Path] = None,
                 nombres: Optional[dict] = None, huellas: Optional[dict] = None, titulo: Optional[str] = None,
                 fecha: Optional[date] = None, duracion: Optional[float] = None):
    """
    Guarda los párrafos en JSON para poder renombrar hablantes sin volver a procesar el audio.
    También guarda la ruta del audio (para escuchar a cada hablante después) y los nombres
    asignados, como {"Hablante 1": "Ana"}; los párrafos conservan las etiquetas originales.
    huellas es la huella de voz de cada hablante ({"Hablante 1": [floats]}), para reconocerlo
    en otras grabaciones; si no hay, la clave no se escribe.
    titulo, fecha (se guarda como AAAA-MM-DD) y duracion permiten rehacer el encabezado del .txt
    al poner nombres; sin título esas claves no se escriben (el .txt queda sin encabezado).
    """
    output_path = Path(output_path)
    datos = {
        "audio": str(audio) if audio else None,
        "nombres": nombres or {},
        "parrafos": segments_agrupados,
    }
    if huellas:
        datos["huellas"] = huellas
    if titulo is not None:
        datos["titulo"] = titulo
        datos["fecha"] = fecha.isoformat() if fecha else None
        datos["duracion"] = duracion
    try:
        escribir_json(output_path, datos, crear_carpeta=False)
        logger.info(f"Archivo JSON guardado en: {output_path}")

    except IOError as e:
        logger.error(f"Error crítico guardando el archivo JSON en {output_path}: {e}")
        raise

def cargar_transcripcion(input_path: Path) -> dict:
    """
    Lee lo guardado por guardar_json: {"audio": str o None, "nombres": dict, "parrafos": list,
    "huellas": dict}. También acepta el formato antiguo (solo la lista de párrafos) y los .json
    de antes de las huellas (quedan con "huellas" vacío).
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {input_path}")
    # utf-8-sig: el Bloc de notas de Windows guarda con BOM y json.load fallaría. Aquí NO se aparta
    # el archivo como .corrupto: si lo editó a mano e quedó inválido, se debe ver el error y arreglarlo.
    with open(input_path, encoding="utf-8-sig") as f:
        datos = json.load(f)
    if isinstance(datos, list):
        return {"audio": None, "nombres": {}, "parrafos": datos, "huellas": {},
                "titulo": None, "fecha": None, "duracion": None}
    huellas = datos.get("huellas")
    return {
        "audio": datos.get("audio"),
        "nombres": datos.get("nombres") or {},
        "parrafos": datos.get("parrafos", []),
        # Si alguien la estropeó a mano, se ignora: las huellas son un extra, no deben impedir abrir el archivo
        "huellas": huellas if isinstance(huellas, dict) else {},
        # Solo las transcripciones hechas desde el menú tienen título (y encabezado)
        "titulo": datos.get("titulo") if isinstance(datos.get("titulo"), str) else None,
        "fecha": a_fecha(datos.get("fecha")),
        "duracion": datos.get("duracion") if isinstance(datos.get("duracion"), (int, float)) else None,
    }

# Líneas del encabezado que escribe encabezado_de_transcripcion (en ese orden)
_CLAVES_ENCABEZADO = {"Fecha": "fecha", "Duración": "duracion", "Participantes": "participantes"}
_LINEA_CON_HORA = re.compile(r"^\[(\d{2,}):(\d{2}):(\d{2})\]\s?(.*)$")

def leer_parrafos_del_txt(txt_path: Path) -> tuple:
    """
    Lee un .blocks.txt (para cuando no hay .blocks.json, p. ej. sin hablantes).
    Retorna (encabezado, parrafos): encabezado es {"titulo", "fecha", "duracion", "participantes"}
    con los textos tal cual (o {} si el archivo no tiene encabezado); cada párrafo es
    {"start": segundos, "text": texto}. El hablante no se separa del texto: sin .json no se puede
    saber si "Ana: hola" es un hablante o parte de la frase.
    """
    # utf-8-sig: un .txt guardado de nuevo con el Bloc de notas puede llevar BOM, y con él la primera
    # línea ya no empieza con «# » ni con «[» (se perdía el título o el primer párrafo)
    lineas = Path(txt_path).read_text(encoding="utf-8-sig").splitlines()
    encabezado = {}
    resto = lineas
    if lineas and lineas[0].startswith("# "):
        encabezado["titulo"] = lineas[0][2:].strip()
        resto = lineas[1:]
        while resto and not _LINEA_CON_HORA.match(resto[0]):
            clave, _, valor = resto[0].partition(": ")
            if clave in _CLAVES_ENCABEZADO and valor:
                encabezado[_CLAVES_ENCABEZADO[clave]] = valor.strip()
            resto = resto[1:]

    parrafos = []
    for linea in resto:
        coincidencia = _LINEA_CON_HORA.match(linea)
        if coincidencia:
            h, m, s, texto = coincidencia.groups()
            parrafos.append({"start": float(int(h) * 3600 + int(m) * 60 + int(s)), "text": texto.strip()})
        elif linea.strip() and parrafos:
            # Un párrafo partido en varias líneas (editado a mano): sigue siendo el mismo
            parrafos[-1]["text"] = f"{parrafos[-1]['text']} {linea.strip()}".strip()
    return encabezado, parrafos
