# Ubicación: utils/formatters.py
import json
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

def guardar_json(segments_agrupados: list, output_path: Path, audio: Path = None, nombres: dict = None):
    """
    Guarda los párrafos en JSON para poder renombrar hablantes sin volver a procesar el audio.
    También guarda la ruta del audio (para escuchar a cada hablante después) y los nombres
    asignados, como {"Hablante 1": "Ana"}; los párrafos conservan las etiquetas originales.
    """
    output_path = Path(output_path)
    datos = {
        "audio": str(audio) if audio else None,
        "nombres": nombres or {},
        "parrafos": segments_agrupados,
    }
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        logger.info(f"Archivo JSON guardado en: {output_path}")

    except IOError as e:
        logger.error(f"Error crítico guardando el archivo JSON en {output_path}: {e}")
        raise

def cargar_transcripcion(input_path: Path) -> dict:
    """
    Lee lo guardado por guardar_json: {"audio": str o None, "nombres": dict, "parrafos": list}.
    También acepta el formato antiguo (solo la lista de párrafos).
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        datos = json.load(f)
    if isinstance(datos, list):
        return {"audio": None, "nombres": {}, "parrafos": datos}
    return {
        "audio": datos.get("audio"),
        "nombres": datos.get("nombres") or {},
        "parrafos": datos.get("parrafos", []),
    }

def cargar_json(input_path: Path) -> list:
    """Lee los párrafos guardados por guardar_json."""
    return cargar_transcripcion(input_path)["parrafos"]
