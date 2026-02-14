# Ubicación: utils/formatters.py
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

def guardar_txt_con_timestamps(segments_agrupados: list, output_path: Path):
    """Guarda los segmentos transcritos en un archivo de texto legible."""
    lines = []
    for seg in segments_agrupados:
        ts = format_timestamp_hhmmss(seg["start"])
        text = seg["text"].strip()
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
        text = seg["text"].strip()
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