# Ubicación: utils/formatters.py
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

# Nuestro auditor local
logger = logging.getLogger(__name__)

def format_timestamp_hhmmss(seconds: float) -> str:
    """Convierte segundos a formato HH:MM:SS."""
    seconds = max(0, seconds)
    total_seconds = int(round(seconds))
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

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
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(encabezado + "\n\n".join(lines))
        logger.info(f"Archivo TXT guardado en: {output_path}")
        
    except IOError as e:
        logger.error(f"Error crítico guardando el archivo TXT en {output_path}: {e}")
        raise

def guardar_json(segments_agrupados: list, output_path: Path, audio: Path = None, nombres: dict = None,
                 huellas: dict = None, titulo: str = None, fecha: date = None, duracion: float = None):
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
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
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
    with open(input_path, encoding="utf-8") as f:
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

def cargar_json(input_path: Path) -> list:
    """Lee los párrafos guardados por guardar_json."""
    return cargar_transcripcion(input_path)["parrafos"]
