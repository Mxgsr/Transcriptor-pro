# Ubicación: src/downloader.py
# Script para preparar la descarga del audio.
import os
import subprocess
import logging
from pathlib import Path

# Importamos las herramientas internas de nuestra propia empresa
from src.config import DOWNLOAD_DIR
from utils.validators import es_url_valida

# Instanciamos el auditor de este departamento
logger = logging.getLogger(__name__)

def descargar_audio(url: str) -> Path:
    """
    Descarga el mejor audio posible de una URL usando yt-dlp.
    Retorna la ruta (Path) del archivo descargado.
    """
    # 1. Filtro de entrada
    if not es_url_valida(url):
        logger.error(f"Se rechazó la descarga. URL inválida: {url}")
        raise ValueError(f"URL inválida o insegura: {url}")

    # 2. Preparamos el destino
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    template = "%(title)s.%(ext)s"
    output_path = str(Path(DOWNLOAD_DIR) / template)

    # 3. Instrucciones para la descarga (yt-dlp)
    cmd = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "-x",
        "--audio-format", "mp3",
        "-o", output_path,
        url,
    ]

    logger.info("Inicia la descarga")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error al descargar el audio: {e.returncode}")
        raise RuntimeError(f"Error crítico en yt-dlp descargando el audio: código {e.returncode}") from e

    # 4. Búscamos el último archivo descargado.
    mp3_files = sorted(Path(DOWNLOAD_DIR).glob("*.mp3"), key=os.path.getmtime)
    if not mp3_files:
        raise FileNotFoundError("No se encontró ningún archivo .mp3 en la carpeta después de la descarga.")
    
    audio_path = mp3_files[-1]    

    logger.info(f"Audio descargado en {audio_path}")
    
    return audio_path