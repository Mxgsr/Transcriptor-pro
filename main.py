# Ubicación: main.py
import argparse
import logging
import sys
from pathlib import Path

# 1. Importamos las funciones específicas de nuestros módulos
from src.config import DEFAULT_MODEL
from src.downloader import descargar_audio
from src.transcriber import transcribir_audio, agrupar_segmentos_en_parrafos
from utils.formatters import guardar_txt_con_timestamps, guardar_srt
from utils.validators import es_url

# Configuramos el registro de eventos para este archivo
logger = logging.getLogger(__name__)

def procesar_entrada(entrada: str, modelo: str):
    """
    Controla el flujo principal del programa:
    Descarga -> Transcripción -> Agrupación -> Guardado.
    """
    
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
    
    logger.info("Agrupando los segmentos en párrafos legibles...")
    # Esta función procesa la lista cruda y la divide según las pausas y puntos.
    parrafos = agrupar_segmentos_en_parrafos(segmentos)

    # PASO 3: Escribir los resultados en el disco duro
    # Generamos las rutas de salida reemplazando la extensión (.mp3) por .blocks.txt y .blocks.srt
    txt_path = audio_path.with_suffix(".blocks.txt")
    srt_path = audio_path.with_suffix(".blocks.srt")

    logger.info("Guardando los archivos finales...")

    guardar_txt_con_timestamps(parrafos, txt_path)
    
    guardar_srt(parrafos, srt_path)
    
    logger.info("Proceso completado con éxito.")


def main():
    """
    Configura el parser de la línea de comandos para recibir argumentos.
    Ejemplo de uso esperado: python main.py https://youtube.com/... --model small
    """
    parser = argparse.ArgumentParser(description="Transcriptor de audio y video usando Whisper.")
    
    # Definimos los argumentos requeridos y opcionales
    parser.add_argument("entrada", help="URL de YouTube o ruta a un archivo de audio local.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Modelo de Whisper a usar (por defecto: {DEFAULT_MODEL})")

    # Extraemos los valores ingresados por el usuario
    args = parser.parse_args()

    # Ejecutamos la función principal dentro de un bloque try-except
    # para capturar cualquier error no manejado y salir limpiamente del sistema.
    try:
        procesar_entrada(args.entrada, args.model)
    except Exception as e:
        logger.critical(f"El programa se detuvo por un error crítico: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()