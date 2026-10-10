# Ubicación: src/procesador.py
# Orquesta el flujo completo sin escribir en pantalla.
# Quien lo llama (la CLI) decide cómo mostrar el avance y el resultado.
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.config import HF_TOKEN, DIARIZATION_MODEL, DIARIZATION_DEVICE
from src.diarizer import cargar_pipeline, diarizar_audio, asignar_hablantes, aplicar_nombres
from src.downloader import descargar_audio
from src.transcriber import transcribir_audio, agrupar_segmentos_en_parrafos
from src.fragmentos import buscar_audio
from src.repeticiones import limpiar_segmentos, limpiar_parrafos
from utils.formatters import guardar_txt_con_timestamps, guardar_json, cargar_transcripcion
from utils.validators import es_url

# Configuramos el registro de eventos para este archivo
logger = logging.getLogger(__name__)


@dataclass
class Resultado:
    """Lo que produjo una transcripción, para que la CLI arme el resumen final."""
    audio_path: Path
    txt_path: Path
    json_path: Optional[Path]  # solo existe si la diarización salió bien
    parrafos: list             # ya con los nombres aplicados
    duracion: float            # segundos de audio transcritos
    error_hablantes: Optional[str] = None  # por qué falló la diarización, si falló


def _sin_aviso(paso: str):
    pass


def procesar_entrada(entrada: str, modelo: str, diarizar: bool = False, nombres: dict = None,
                     num_hablantes: int = None, min_hablantes: int = None, max_hablantes: int = None,
                     idioma: str = "es", salida: Path = None, carpeta_descargas: Path = None,
                     al_avanzar: Callable[[str], None] = _sin_aviso,
                     al_fallar: Callable[[str], None] = _sin_aviso,
                     al_progresar: Optional[Callable] = None,
                     silenciar_motores: bool = False) -> Resultado:
    """
    Controla el flujo principal del programa:
    Descarga -> Transcripción -> (Diarización) -> Agrupación -> Guardado.

    al_avanzar recibe el nombre de cada paso al empezar, para mostrar el progreso.
    al_progresar(completado, total, unidad) informa el avance dentro del paso actual
    (unidad: "bytes" en la descarga, "audio" en segundos al transcribir, None si es una fracción).
    al_fallar recibe el error si falla la diarización: la transcripción se guarda igual, sin hablantes.
    silenciar_motores oculta la salida propia de yt-dlp y mlx-whisper.
    carpeta_descargas es dónde guardar el audio de una URL (por defecto, DOWNLOAD_DIR del .env).
    """
    nombres = nombres or {}

    # Cargamos la diarización antes de transcribir para fallar rápido si falta el token
    pipeline = None
    if diarizar:
        al_avanzar("Preparando hablantes")
        pipeline = cargar_pipeline(HF_TOKEN, DIARIZATION_MODEL, DIARIZATION_DEVICE)

    # PASO 1: Obtener la ruta local del archivo de audio
    if es_url(entrada):
        logger.info(f"Detectada URL. Iniciando descarga de: {entrada}")
        al_avanzar("Descargando audio")
        # Esto ejecutará yt-dlp y nos devolverá la ruta del archivo descargado.
        audio_path = descargar_audio(entrada, silencioso=silenciar_motores, progreso=al_progresar,
                                     carpeta=carpeta_descargas)
    else:
        logger.info(f"Detectado archivo local: {entrada}")
        # Convierte el texto de la ruta en un objeto Path de Python
        audio_path = Path(entrada).expanduser()

    # PASO 2: Procesar el audio con Whisper
    logger.info(f"Iniciando transcripción con el modelo: {modelo}")
    al_avanzar("Transcribiendo")
    # Esto cargará el modelo en memoria y devolverá la lista de diccionarios.
    segmentos = transcribir_audio(audio_path, model_name=modelo, language=idioma,
                                  mostrar_progreso=not silenciar_motores, progreso=al_progresar)
    duracion = max((s["end"] for s in segmentos), default=0.0)
    # Quita las frases que Whisper repitió en bucle ("Gracias. Gracias. Gracias...")
    segmentos = limpiar_segmentos(segmentos)

    # PASO 3: Escribir la transcripción en el disco duro antes de diarizar,
    # para no perderla si la diarización falla o se interrumpe.
    # Por defecto junto al audio; con salida, en esa carpeta. (.mp3 -> .blocks.txt)
    carpeta = Path(salida).expanduser() if salida else audio_path.parent
    carpeta.mkdir(parents=True, exist_ok=True)
    txt_path = carpeta / f"{audio_path.stem}.blocks.txt"
    json_path = None
    error_hablantes = None

    logger.info("Agrupando los segmentos en párrafos legibles...")
    # Esta función procesa la lista cruda y la divide según las pausas y puntos.
    parrafos = limpiar_parrafos(agrupar_segmentos_en_parrafos(segmentos))
    guardar_txt_con_timestamps(parrafos, txt_path)

    # PASO 4 (opcional): identificar hablantes y re-escribir el TXT con sus nombres
    if pipeline is not None:
        al_avanzar("Identificando hablantes")
        try:
            turnos = diarizar_audio(pipeline, audio_path, num_hablantes, min_hablantes, max_hablantes,
                                    progreso=al_progresar)
            # Copias: si algo falla a medias, los segmentos originales quedan intactos
            con_hablantes = asignar_hablantes([dict(s) for s in segmentos], turnos)
        except Exception as e:
            error_hablantes = str(e) or type(e).__name__
            logger.info(f"No se pudo identificar a los hablantes; la transcripción se guardó sin ellos. Motivo: {error_hablantes}")
            al_fallar(error_hablantes)
        else:
            # Al partir los segmentos por hablante el texto sale de sus palabras: se limpia otra vez
            parrafos = limpiar_parrafos(agrupar_segmentos_en_parrafos(con_hablantes))
            # El JSON guarda las etiquetas genéricas para poder renombrar después sin re-procesar
            json_path = txt_path.with_suffix(".json")
            guardar_json(parrafos, json_path, audio=audio_path.resolve(), nombres=nombres)
            parrafos = aplicar_nombres(parrafos, nombres)
            guardar_txt_con_timestamps(parrafos, txt_path)

    logger.info("Proceso completado con éxito.")

    return Resultado(
        audio_path=audio_path,
        txt_path=txt_path,
        json_path=json_path,
        parrafos=parrafos,
        duracion=duracion,
        error_hablantes=error_hablantes,
    )


def leer_transcripcion(json_path: Path) -> dict:
    """
    Lee un .blocks.json: {"audio": Path o None, "nombres": dict, "parrafos": list (etiquetas originales)}.
    Si el audio no está donde se guardó (o el .json es antiguo), lo busca junto al .json.
    """
    datos = cargar_transcripcion(json_path)
    datos["audio"] = buscar_audio(Path(json_path), datos["audio"])
    return datos


def renombrar_hablantes(json_path: Path, nombres: dict) -> tuple:
    """
    Re-escribe el TXT de una transcripción ya diarizada con los nombres indicados,
    sumados a los que ya tenía guardados el .json. Sin nombres nuevos, el .json no se toca
    (así se respetan los cambios hechos a mano) y solo se rehace el TXT.
    Retorna (ruta del TXT, párrafos con los nombres aplicados).
    """
    logger.info(f"Aplicando nombres de hablantes a: {json_path}")
    datos = cargar_transcripcion(json_path)
    mapa = {**datos["nombres"], **nombres}
    if mapa != datos["nombres"]:
        guardar_json(datos["parrafos"], json_path, audio=datos["audio"], nombres=mapa)
    parrafos = aplicar_nombres(datos["parrafos"], mapa)
    txt_path = json_path.with_suffix(".txt")
    guardar_txt_con_timestamps(parrafos, txt_path)
    logger.info("Nombres aplicados con éxito.")
    return txt_path, parrafos
