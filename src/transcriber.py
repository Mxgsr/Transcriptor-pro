# Ubicación: src/transcriber.py

import whisper
import logging
from pathlib import Path

# Nuestro auditor local
logger = logging.getLogger(__name__)

def transcribir_audio(audio_path: Path, model_name: str, language: str = "es") -> list:
    """
    Toma un archivo de audio y usa Whisper para convertirlo en texto.
    Retorna una lista de diccionarios (segmentos).
    """
    # 1. Filtro de Entrada (El Guardia)
    if not audio_path.exists():
        logger.error(f"El archivo {audio_path} no existe. Revisar la ruta.")
        raise FileNotFoundError(f"No se encontró el audio en: {audio_path}")

    # Forzamos CPU por problemas conocidos de estabilidad
    device = "cpu" 
    
    # TODO 2: Usa logger.info() para avisar que estamos cargando el modelo: {model_name}
    logger.info(f"Cargado modelo {model_name}")
    
    try:
        model = whisper.load_model(model_name, device=device)
    except Exception as e:
        logger.error(f"Error crítico: No se pudo cargar el modelo '{model_name}'. Detalles: {e}")
        raise

    logger.info(f"Comienza la transcripción del archivo: {audio_path}")
    
    try:
        result = model.transcribe(str(audio_path), language=language, verbose=False)
    except Exception as e:
        logger.error(f"El motor falló durante la transcripción: {e}")
        raise

    segments = result.get("segments", [])
    
    if not segments:
        logger.warning("No se detectaron segmentos de audio claros. Retornando texto vacío.")
        return [{"start": 0.0, "end": 0.0, "text": result.get("text", "").strip()}]

    return segments

def agrupar_segmentos_en_parrafos(segments: list, pause_threshold: float = 2.0, max_chars: int = 600, min_chars_for_pause_break: int = 150) -> list:
    """Agrupa los segmentos de Whisper en párrafos legibles basados en pausas y longitud."""
    if not segments:
        return []

    parrafos = []
    current_start = segments[0]["start"]
    current_end = segments[0]["end"]
    current_texts = [segments[0]["text"].strip()]

    def current_text():
        return " ".join(t for t in current_texts if t)

    for prev, seg in zip(segments, segments[1:]):
        seg_start = seg["start"]
        seg_end = seg["end"]
        seg_text = seg["text"].strip()

        gap = seg_start - prev["end"]
        texto_actual = current_text()
        largo_actual = len(texto_actual)

        termina_en_punto = texto_actual.endswith((".", "?", "!", "¿", "¡"))

        corte_por_pausa = gap >= pause_threshold and largo_actual >= min_chars_for_pause_break
        corte_por_largo = largo_actual >= max_chars and termina_en_punto

        if corte_por_pausa or corte_por_largo:
            parrafos.append({
                "start": current_start,
                "end": current_end,
                "text": texto_actual
            })
            current_start = seg_start
            current_end = seg_end
            current_texts = [seg_text] if seg_text else []
        else:
            current_end = seg_end
            if seg_text:
                current_texts.append(seg_text)

    texto_final = current_text()
    if texto_final:
        parrafos.append({
            "start": current_start,
            "end": current_end,
            "text": texto_final
        })

    return parrafos