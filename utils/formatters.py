# Ubicación: utils/formatters.py
import json
import math
import logging
from pathlib import Path

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

def format_timestamp_srt(seconds: float) -> str:
    """Convierte segundos a formato HH:MM:SS,mmm para subtítulos."""
    seconds = max(0, seconds)
    ms = int(round((seconds - math.floor(seconds)) * 1000))
    total_seconds = int(math.floor(seconds))
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def texto_con_hablante(seg: dict) -> str:
    """Antepone el nombre del hablante al texto cuando hay diarización."""
    text = seg["text"].strip()
    if text and seg.get("speaker"):
        return f"{seg['speaker']}: {text}"
    return text

def guardar_txt_con_timestamps(segments_agrupados: list, output_path: Path):
    """Guarda los segmentos transcritos en un archivo de texto legible."""
    lines = []
    for seg in segments_agrupados:
        ts = format_timestamp_hhmmss(seg["start"])
        text = texto_con_hablante(seg)
        if text:
            lines.append(f"[{ts}] {text}")

    output_path = Path(output_path)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(lines))
        logger.info(f"Archivo TXT guardado en: {output_path}")
        
    except IOError as e:
        logger.error(f"Error crítico guardando el archivo TXT en {output_path}: {e}")
        raise

def guardar_srt(segments_agrupados: list, output_path: Path):
    """Guarda los segmentos en formato estándar de subtítulos SRT."""
    blocks = []
    for i, seg in enumerate(segments_agrupados, start=1):
        start = format_timestamp_srt(seg["start"])
        end = format_timestamp_srt(seg["end"])
        text = texto_con_hablante(seg)
        if not text:
            continue
        blocks.append(f"{i}\n{start} --> {end}\n{text}\n")

    output_path = Path(output_path)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(blocks))
            
        logger.info(f"Archivo SRT guardado en: {output_path}")
        
    except IOError as e:
        logger.error(f"Error crítico guardando el archivo SRT en {output_path}: {e}")
        raise

def guardar_json(segments_agrupados: list, output_path: Path):
    """Guarda los párrafos en JSON para poder renombrar hablantes sin volver a procesar el audio."""
    output_path = Path(output_path)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(segments_agrupados, f, ensure_ascii=False, indent=2)
        logger.info(f"Archivo JSON guardado en: {output_path}")

    except IOError as e:
        logger.error(f"Error crítico guardando el archivo JSON en {output_path}: {e}")
        raise

def cargar_json(input_path: Path) -> list:
    """Lee los párrafos guardados por guardar_json."""
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        return json.load(f)
