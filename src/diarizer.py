# Ubicación: src/diarizer.py
# Identifica quién habla y cuándo (diarización) usando pyannote.audio,
# y cruza ese resultado con los segmentos de Whisper.
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ETIQUETA_GENERICA = "Hablante"


def cargar_pipeline(hf_token: str, modelo: str):
    """
    Carga el pipeline de diarización desde Hugging Face.
    Se hace antes de transcribir para fallar rápido si falta el token
    o no se aceptaron las condiciones del modelo.
    """
    # 1. Filtro de entrada: sin token no hay descarga del modelo
    if not hf_token:
        raise ValueError(
            "Falta HF_TOKEN en el archivo .env. La diarización necesita un token de Hugging Face "
            "(ver README, sección Diarización)."
        )

    # Importación diferida: pyannote es pesado y solo se necesita con --diarizar
    try:
        from pyannote.audio import Pipeline
    except ImportError as e:
        raise ImportError(
            "pyannote.audio no está instalado. Ejecuta: pip install -r requirements-diarizacion.txt"
        ) from e

    logger.info(f"Cargando modelo de diarización: {modelo}")
    try:
        pipeline = Pipeline.from_pretrained(modelo, token=hf_token)
    except Exception as e:
        logger.error(f"No se pudo cargar el modelo de diarización '{modelo}'. Detalles: {e}")
        raise

    # pyannote devuelve None cuando el modelo es privado y no se aceptaron sus condiciones
    if pipeline is None:
        raise RuntimeError(
            f"No se pudo descargar '{modelo}'. Acepta sus condiciones de uso en "
            f"https://huggingface.co/{modelo} con la cuenta dueña del token."
        )

    return pipeline


def diarizar_audio(pipeline, audio_path: Path, num_hablantes: int = None,
                   min_hablantes: int = None, max_hablantes: int = None) -> list:
    """
    Ejecuta la diarización sobre el audio.
    Retorna una lista de turnos: [{"start": float, "end": float, "speaker": str}, ...]
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"No se encontró el audio en: {audio_path}")

    import torch
    import whisper

    # Decodificamos con el mismo ffmpeg que usa Whisper (16 kHz, mono) y le pasamos
    # la onda ya cargada a pyannote, así no dependemos de su propio decodificador.
    audio = whisper.load_audio(str(audio_path))
    entrada = {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": whisper.audio.SAMPLE_RATE}

    logger.info(f"Comienza la diarización del archivo: {audio_path}")
    try:
        resultado = pipeline(
            entrada,
            num_speakers=num_hablantes,
            min_speakers=min_hablantes,
            max_speakers=max_hablantes,
        )
    except Exception as e:
        logger.error(f"El motor de diarización falló: {e}")
        raise

    # La versión "exclusive" no tiene voces solapadas: es la indicada para alinear con texto
    anotacion = getattr(resultado, "exclusive_speaker_diarization", resultado)

    turnos = [
        {"start": turno.start, "end": turno.end, "speaker": hablante}
        for turno, _, hablante in anotacion.itertracks(yield_label=True)
    ]
    logger.info(f"Diarización completa: {len({t['speaker'] for t in turnos})} hablante(s) detectado(s).")
    return turnos


def asignar_hablantes(segmentos: list, turnos: list) -> list:
    """
    Asigna a cada segmento de Whisper el hablante con más tiempo solapado.
    Si un segmento no se solapa con ningún turno, toma el turno más cercano.
    Los hablantes se renombran como "Hablante 1", "Hablante 2"... en orden de aparición.
    """
    if not turnos:
        logger.warning("La diarización no detectó hablantes. Se omiten las etiquetas.")
        return segmentos

    for seg in segmentos:
        solapes = {}
        for turno in turnos:
            solape = min(seg["end"], turno["end"]) - max(seg["start"], turno["start"])
            if solape > 0:
                solapes[turno["speaker"]] = solapes.get(turno["speaker"], 0.0) + solape

        if solapes:
            seg["speaker"] = max(solapes, key=solapes.get)
        else:
            centro = (seg["start"] + seg["end"]) / 2
            cercano = min(turnos, key=lambda t: _distancia(centro, t))
            seg["speaker"] = cercano["speaker"]

    # Etiquetas legibles y estables: el primero que habla es "Hablante 1"
    etiquetas = {}
    for seg in segmentos:
        if seg["speaker"] not in etiquetas:
            etiquetas[seg["speaker"]] = f"{ETIQUETA_GENERICA} {len(etiquetas) + 1}"
        seg["speaker"] = etiquetas[seg["speaker"]]

    return segmentos


def _distancia(punto: float, turno: dict) -> float:
    if turno["start"] <= punto <= turno["end"]:
        return 0.0
    return min(abs(punto - turno["start"]), abs(punto - turno["end"]))


def parsear_nombres(texto: str) -> dict:
    """
    Convierte el texto de --nombres en un mapa {"Hablante N": "Nombre"}.
    Acepta nombres en orden de aparición ("Ana,Luis") o por número ("2=Luis,1=Ana").
    """
    nombres = {}
    if not texto:
        return nombres

    for posicion, item in enumerate(texto.split(","), start=1):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            numero, nombre = (parte.strip() for parte in item.split("=", 1))
            if not numero.isdigit():
                raise ValueError(f"En --nombres, '{numero}' debe ser el número del hablante (ej: 2=Luis).")
            posicion = int(numero)
        else:
            nombre = item
        if not nombre:
            raise ValueError(f"En --nombres, falta el nombre para el hablante {posicion}.")
        nombres[f"{ETIQUETA_GENERICA} {posicion}"] = nombre

    return nombres


def aplicar_nombres(parrafos: list, nombres: dict) -> list:
    """Retorna una copia de los párrafos con los hablantes renombrados. Los que no estén en el mapa conservan su etiqueta."""
    return [
        {**p, "speaker": nombres.get(p["speaker"], p["speaker"])} if "speaker" in p else dict(p)
        for p in parrafos
    ]
