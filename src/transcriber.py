# Ubicación: src/transcriber.py

import mlx_whisper
import logging
import sys
import types
from contextlib import contextmanager
from pathlib import Path

# Nuestro auditor local
logger = logging.getLogger(__name__)

# Nombres cortos de --model -> modelos convertidos a MLX en Hugging Face (mlx-community)
MODELOS_MLX = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}

def resolver_modelo(model_name: str) -> str:
    """
    Traduce el nombre de --model al repositorio MLX correspondiente.
    Un valor con "/" se usa tal cual (repo de Hugging Face o carpeta local).
    """
    if "/" in model_name:
        return model_name
    try:
        return MODELOS_MLX[model_name]
    except KeyError:
        opciones = ", ".join(MODELOS_MLX)
        raise ValueError(
            f"Modelo '{model_name}' no reconocido. Usa uno de: {opciones}, "
            "o un repo de Hugging Face (ej: mlx-community/whisper-small-mlx)."
        ) from None

# Ajustes contra las alucinaciones de Whisper (una frase repetida en bucle, texto inventado en silencios):
# - condition_on_previous_text=False: cada trozo no usa el texto anterior como pista, así un error no se arrastra.
# - word_timestamps=True: la hora de cada palabra. La necesita el ajuste siguiente, y la diarización
#   la usa para asignar cada palabra a su hablante.
# - hallucination_silence_threshold: si un trozo dudoso está rodeado de más de estos segundos de
#   silencio, se lo salta (ahí es donde Whisper suele inventar).
AJUSTES_CONTRA_BUCLES = {
    "condition_on_previous_text": False,
    "word_timestamps": True,
    "hallucination_silence_threshold": 2.0,
}

# mlx-whisper mide su avance en "frames" de 10 ms (100 por segundo de audio)
FRAMES_POR_SEGUNDO = 100


class _BarraHaciaCallback:
    """Se hace pasar por la barra tqdm de mlx-whisper y reenvía el avance (en segundos de audio)."""

    def __init__(self, progreso, total=None, **kwargs):
        self.progreso = progreso
        self.total = total / FRAMES_POR_SEGUNDO if total else None
        self.n = 0

    def __enter__(self):
        self.progreso(0, self.total, "audio")
        return self

    def __exit__(self, *args):
        return False

    def update(self, n=1):
        self.n += n
        self.progreso(self.n / FRAMES_POR_SEGUNDO, self.total, "audio")


@contextmanager
def _capturar_barra_de_mlx(progreso):
    """
    mlx-whisper no ofrece un callback de progreso, solo su barra tqdm.
    Mientras dura la transcripción, cambiamos esa barra por _BarraHaciaCallback.
    Si su estructura interna cambia, simplemente no hay progreso (la transcripción sigue igual).
    """
    modulo = sys.modules.get("mlx_whisper.transcribe")
    if progreso is None or modulo is None or not hasattr(modulo, "tqdm"):
        yield False
        return
    original = modulo.tqdm
    modulo.tqdm = types.SimpleNamespace(tqdm=lambda *args, **kwargs: _BarraHaciaCallback(progreso, **kwargs))
    try:
        yield True
    finally:
        modulo.tqdm = original


def transcribir_audio(audio_path: Path, model_name: str, language: str = "es", mostrar_progreso: bool = True,
                      progreso=None) -> list:
    """
    Toma un archivo de audio y usa Whisper (MLX, acelerado en Apple Silicon) para convertirlo en texto.
    Retorna una lista de diccionarios (segmentos).
    Con mostrar_progreso=False se oculta la barra propia de mlx-whisper (la CLI muestra la suya).
    progreso(segundos_transcritos, segundos_totales, "audio") se llama a medida que avanza.
    """
    # 1. Filtro de Entrada (El Guardia)
    if not audio_path.exists():
        logger.error(f"El archivo {audio_path} no existe. Revisar la ruta.")
        raise FileNotFoundError(f"No se encontró el audio en: {audio_path}")

    repo = resolver_modelo(model_name)
    logger.info(f"Usando modelo {model_name} ({repo}). La primera vez se descarga de Hugging Face.")
    logger.info(f"Comienza la transcripción del archivo: {audio_path}")

    # mlx_whisper carga el modelo dentro de transcribe(), así que aquí también
    # aparecen los errores de descarga o de un modelo inexistente.
    try:
        with _capturar_barra_de_mlx(progreso) as capturada:
            result = mlx_whisper.transcribe(
                str(audio_path),
                path_or_hf_repo=repo,
                language=language,
                # False activa la barra de progreso de mlx-whisper (la nuestra, si está capturada);
                # None no muestra nada
                verbose=False if (mostrar_progreso or capturada) else None,
                **AJUSTES_CONTRA_BUCLES,
            )
    except Exception as e:
        logger.error(f"El motor falló durante la transcripción con '{repo}': {e}")
        raise

    segments = result.get("segments", [])
    
    if not segments:
        logger.warning("No se detectaron segmentos de audio claros. Retornando texto vacío.")
        return [{"start": 0.0, "end": 0.0, "text": result.get("text", "").strip()}]

    return segments

def agrupar_segmentos_en_parrafos(segments: list, pause_threshold: float = 2.0, max_chars: int = 600, min_chars_for_pause_break: int = 150) -> list:
    """
    Agrupa los segmentos de Whisper en párrafos legibles basados en pausas y longitud.
    Si los segmentos traen "speaker" (diarización), también corta cuando cambia el hablante.
    """
    if not segments:
        return []

    parrafos = []
    current_start = segments[0]["start"]
    current_end = segments[0]["end"]
    current_texts = [segments[0]["text"].strip()]
    current_speaker = segments[0].get("speaker")

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
        corte_por_hablante = seg.get("speaker") != current_speaker

        if corte_por_pausa or corte_por_largo or corte_por_hablante:
            parrafos.append(_nuevo_parrafo(current_start, current_end, texto_actual, current_speaker))
            current_speaker = seg.get("speaker")
            current_start = seg_start
            current_end = seg_end
            current_texts = [seg_text] if seg_text else []
        else:
            current_end = seg_end
            if seg_text:
                current_texts.append(seg_text)

    texto_final = current_text()
    if texto_final:
        parrafos.append(_nuevo_parrafo(current_start, current_end, texto_final, current_speaker))

    return parrafos

def _nuevo_parrafo(start: float, end: float, text: str, speaker) -> dict:
    parrafo = {"start": start, "end": end, "text": text}
    if speaker is not None:
        parrafo["speaker"] = speaker
    return parrafo