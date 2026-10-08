# Ubicación: main.py
import argparse
import logging
import sys
from pathlib import Path

# 1. Importamos las funciones específicas de nuestros módulos
from src.config import DEFAULT_MODEL, HF_TOKEN, DIARIZATION_MODEL
from src.diarizer import cargar_pipeline, diarizar_audio, asignar_hablantes, parsear_nombres, aplicar_nombres
from src.downloader import descargar_audio
from src.transcriber import transcribir_audio, agrupar_segmentos_en_parrafos
from utils.formatters import guardar_txt_con_timestamps, guardar_srt, guardar_json, cargar_json
from utils.validators import es_url

# Configuramos el registro de eventos para este archivo
logger = logging.getLogger(__name__)

def procesar_entrada(entrada: str, modelo: str, diarizar: bool = False, nombres: dict = None,
                     num_hablantes: int = None, min_hablantes: int = None, max_hablantes: int = None):
    """
    Controla el flujo principal del programa:
    Descarga -> Transcripción -> (Diarización) -> Agrupación -> Guardado.
    """
    nombres = nombres or {}

    # Atajo: un .blocks.json de una ejecución anterior solo se re-escribe con los nombres nuevos
    if not es_url(entrada) and entrada.endswith(".blocks.json"):
        renombrar_hablantes(Path(entrada).expanduser(), nombres)
        return

    # Cargamos la diarización antes de transcribir para fallar rápido si falta el token
    pipeline = cargar_pipeline(HF_TOKEN, DIARIZATION_MODEL) if diarizar else None

    # PASO 1: Obtener la ruta local del archivo de audio
    if es_url(entrada):
        logger.info(f"Detectada URL. Iniciando descarga de: {entrada}")
        # Esto ejecutará yt-dlp y nos devolverá la ruta del archivo descargado.
        audio_path = descargar_audio(entrada)
    else:
        logger.info(f"Detectado archivo local: {entrada}")
        # Convierte el texto de la ruta en un objeto Path de Python
        audio_path = Path(entrada).expanduser()

    # PASO 2: Procesar el audio con Whisper
    logger.info(f"Iniciando transcripción con el modelo: {modelo}")
    # Esto cargará el modelo en memoria y devolverá la lista de diccionarios.
    segmentos = transcribir_audio(audio_path, model_name=modelo)

    if pipeline is not None:
        turnos = diarizar_audio(pipeline, audio_path, num_hablantes, min_hablantes, max_hablantes)
        segmentos = asignar_hablantes(segmentos, turnos)
    
    logger.info("Agrupando los segmentos en párrafos legibles...")
    # Esta función procesa la lista cruda y la divide según las pausas y puntos.
    parrafos = agrupar_segmentos_en_parrafos(segmentos)

    # PASO 3: Escribir los resultados en el disco duro
    # Generamos las rutas de salida reemplazando la extensión (.mp3) por .blocks.txt y .blocks.srt
    txt_path = audio_path.with_suffix(".blocks.txt")
    srt_path = audio_path.with_suffix(".blocks.srt")

    logger.info("Guardando los archivos finales...")

    if pipeline is not None:
        # El JSON guarda las etiquetas genéricas para poder renombrar después sin re-procesar
        guardar_json(parrafos, audio_path.with_suffix(".blocks.json"))
        parrafos = aplicar_nombres(parrafos, nombres)

    guardar_txt_con_timestamps(parrafos, txt_path)
    
    guardar_srt(parrafos, srt_path)
    
    logger.info("Proceso completado con éxito.")


def renombrar_hablantes(json_path: Path, nombres: dict):
    """Re-escribe el TXT y el SRT de una transcripción ya diarizada con los nombres indicados."""
    logger.info(f"Aplicando nombres de hablantes a: {json_path}")
    parrafos = aplicar_nombres(cargar_json(json_path), nombres)
    guardar_txt_con_timestamps(parrafos, json_path.with_suffix(".txt"))
    guardar_srt(parrafos, json_path.with_suffix(".srt"))
    logger.info("Nombres aplicados con éxito.")


def main():
    """
    Configura el parser de la línea de comandos para recibir argumentos.
    Ejemplo de uso esperado: python main.py https://youtube.com/... --model small
    """
    parser = argparse.ArgumentParser(description="Transcriptor de audio y video usando Whisper.")
    
    # Definimos los argumentos requeridos y opcionales
    parser.add_argument("entrada", help="URL de YouTube o ruta a un archivo de audio local.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Modelo de Whisper a usar (por defecto: {DEFAULT_MODEL})")
    parser.add_argument("--diarizar", action="store_true", help="Identifica a los hablantes (requiere HF_TOKEN en .env).")
    parser.add_argument("--nombres", help='Nombres de los hablantes en orden de aparición ("Ana,Luis") o por número ("2=Luis,1=Ana"). Activa --diarizar.')
    parser.add_argument("--hablantes", type=int, help="Número exacto de hablantes, si se conoce (mejora la precisión).")
    parser.add_argument("--min-hablantes", type=int, help="Número mínimo de hablantes esperado.")
    parser.add_argument("--max-hablantes", type=int, help="Número máximo de hablantes esperado.")

    # Extraemos los valores ingresados por el usuario
    args = parser.parse_args()

    # Ejecutamos la función principal dentro de un bloque try-except
    # para capturar cualquier error no manejado y salir limpiamente del sistema.
    try:
        procesar_entrada(
            args.entrada,
            args.model,
            diarizar=args.diarizar or bool(args.nombres) or any(
                n is not None for n in (args.hablantes, args.min_hablantes, args.max_hablantes)
            ),
            nombres=parsear_nombres(args.nombres),
            num_hablantes=args.hablantes,
            min_hablantes=args.min_hablantes,
            max_hablantes=args.max_hablantes,
        )
    except Exception as e:
        logger.critical(f"El programa se detuvo por un error crítico: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()