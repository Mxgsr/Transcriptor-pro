# Ubicación: src/transcriber.py

import logging
import sys
import types
from contextlib import contextmanager
from pathlib import Path

from src.config import TRANSCRIPTION_DEVICE

# Dos motores de Whisper, con los mismos modelos y los mismos ajustes:
# - mlx-whisper: usa la GPU de los Mac con chip Apple (M1 o posterior). Es el más rápido ahí.
# - faster-whisper: funciona en Windows, Linux y Macs con Intel (CPU, o GPU NVIDIA con CUDA).
# Cada computador instala solo el que le sirve (ver pyproject.toml).
try:
    import mlx_whisper
except ImportError:
    mlx_whisper = None

MOTOR_MLX = "mlx-whisper"
MOTOR_FASTER = "faster-whisper"

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

# Los mismos nombres cortos -> modelos de faster-whisper (los descarga él mismo de Hugging Face)
MODELOS_FASTER = {
    "tiny": "tiny",
    "base": "base",
    "small": "small",
    "medium": "medium",
    "large": "large-v3",
    "large-v2": "large-v2",
    "large-v3": "large-v3",
    "turbo": "turbo",
    "large-v3-turbo": "large-v3-turbo",
}


def motor() -> str:
    """El motor de Whisper instalado en este computador."""
    return MOTOR_MLX if mlx_whisper is not None else MOTOR_FASTER


def resolver_modelo(model_name: str) -> str:
    """
    Traduce el nombre de --model al modelo correspondiente del motor instalado.
    Un valor con "/" se usa tal cual (repo de Hugging Face o carpeta local).
    """
    if "/" in model_name:
        return model_name
    modelos = MODELOS_MLX if motor() == MOTOR_MLX else MODELOS_FASTER
    try:
        return modelos[model_name]
    except KeyError:
        opciones = ", ".join(modelos)
        ejemplo = "mlx-community/whisper-small-mlx" if motor() == MOTOR_MLX else "Systran/faster-whisper-small"
        raise ValueError(
            f"Modelo '{model_name}' no reconocido. Usa uno de: {opciones}, "
            f"o un repo de Hugging Face (ej: {ejemplo})."
        ) from None


# Frecuencia del audio que esperan los dos motores
SAMPLE_RATE = 16000


def cargar_audio(audio_path: Path):
    """El audio como onda de numpy (float32, mono, 16 kHz), decodificado igual que lo hace Whisper."""
    import numpy as np

    if motor() == MOTOR_MLX:
        from mlx_whisper.audio import load_audio
        # load_audio devuelve un mx.array de MLX: lo pasamos a numpy
        return np.array(load_audio(str(audio_path)), dtype=np.float32)
    from faster_whisper.audio import decode_audio
    return np.asarray(decode_audio(str(audio_path), sampling_rate=SAMPLE_RATE), dtype=np.float32)


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
                      progreso=None, opciones: dict = None) -> list:
    """
    Toma un archivo de audio y usa Whisper para convertirlo en texto, con el motor instalado
    (mlx-whisper en Mac con chip Apple, faster-whisper en el resto).
    Retorna una lista de diccionarios (segmentos).
    Con mostrar_progreso=False se oculta la barra propia del motor (la CLI muestra la suya).
    progreso(segundos_transcritos, segundos_totales, "audio") se llama a medida que avanza.
    opciones son ajustes extra de Whisper que entienden los dos motores (por ejemplo initial_prompt).
    """
    # 1. Filtro de Entrada (El Guardia)
    if not audio_path.exists():
        logger.error(f"El archivo {audio_path} no existe. Revisar la ruta.")
        raise FileNotFoundError(f"No se encontró el audio en: {audio_path}")

    repo = resolver_modelo(model_name)
    ajustes = {**AJUSTES_CONTRA_BUCLES, **(opciones or {})}
    logger.info(f"Usando modelo {model_name} ({repo}) con {motor()}. La primera vez se descarga de Hugging Face.")
    logger.info(f"Comienza la transcripción del archivo: {audio_path}")

    # Los motores cargan el modelo al transcribir, así que aquí también
    # aparecen los errores de descarga o de un modelo inexistente.
    try:
        if motor() == MOTOR_MLX:
            result = _transcribir_con_mlx(audio_path, repo, language, mostrar_progreso, progreso, ajustes)
        else:
            result = _transcribir_con_faster_whisper(audio_path, repo, language, progreso, ajustes)
    except Exception as e:
        logger.error(f"El motor falló durante la transcripción con '{repo}': {e}")
        raise

    segments = result.get("segments", [])
    
    if not segments:
        logger.warning("No se detectaron segmentos de audio claros. Retornando texto vacío.")
        return [{"start": 0.0, "end": 0.0, "text": result.get("text", "").strip()}]

    return segments


def _transcribir_con_mlx(audio_path: Path, repo: str, language: str, mostrar_progreso: bool, progreso,
                         ajustes: dict) -> dict:
    with _capturar_barra_de_mlx(progreso) as capturada:
        return mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=repo,
            language=language,
            # False activa la barra de progreso de mlx-whisper (la nuestra, si está capturada);
            # None no muestra nada
            verbose=False if (mostrar_progreso or capturada) else None,
            **ajustes,
        )


def _transcribir_con_faster_whisper(audio_path: Path, repo: str, language: str, progreso, ajustes: dict) -> dict:
    """
    faster-whisper entrega los segmentos de a uno (un generador): el avance es hasta dónde llegó.
    Devuelve lo mismo que mlx-whisper: {"text", "segments": [{"start", "end", "text", "words"}]}.
    """
    from faster_whisper import WhisperModel

    # En la CPU, int8 es varias veces más rápido que float32 y casi igual de preciso.
    # En una GPU NVIDIA, "auto" elige float16.
    dispositivo = TRANSCRIPTION_DEVICE
    modelo = WhisperModel(repo, device=dispositivo, compute_type="int8" if dispositivo == "cpu" else "auto")
    trozos, info = modelo.transcribe(str(audio_path), language=language, **ajustes)

    total = getattr(info, "duration", None) or None
    if progreso is not None:
        progreso(0, total, "audio")
    segmentos = []
    for trozo in trozos:
        segmento = {"start": trozo.start, "end": trozo.end, "text": trozo.text}
        if trozo.words:
            segmento["words"] = [
                {"word": p.word, "start": p.start, "end": p.end, "probability": p.probability}
                for p in trozo.words
            ]
        segmentos.append(segmento)
        if progreso is not None:
            progreso(min(trozo.end, total) if total else trozo.end, total, "audio")
    if progreso is not None and total:
        progreso(total, total, "audio")
    return {"text": "".join(s["text"] for s in segmentos), "segments": segmentos}

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