# Ubicación: src/downloader.py
# Script para preparar la descarga del audio.
import os
import logging
from pathlib import Path

# Importamos las herramientas internas de nuestra propia empresa
from src.config import DOWNLOAD_DIR
from utils.validators import es_url_valida

# Instanciamos el auditor de este departamento
logger = logging.getLogger(__name__)

def descargar_audio(url: str, silencioso: bool = False, progreso=None, carpeta: Path = None) -> Path:
    """
    Descarga el mejor audio posible de una URL usando yt-dlp y lo convierte a mp3.
    Retorna la ruta (Path) del archivo descargado.
    Con silencioso=True, yt-dlp solo escribe en pantalla si hay un error.
    progreso(descargados, total, "bytes") se llama a medida que avanza la descarga.
    carpeta es dónde guardarlo (por defecto, DOWNLOAD_DIR del .env).
    """
    # 1. Filtro de entrada
    if not es_url_valida(url):
        logger.error(f"Se rechazó la descarga. URL inválida: {url}")
        raise ValueError(f"URL inválida o insegura: {url}")

    # Importación diferida: yt-dlp solo hace falta al descargar
    import yt_dlp

    # 2. Preparamos el destino
    destino = Path(carpeta or DOWNLOAD_DIR).expanduser()
    os.makedirs(destino, exist_ok=True)
    template = "%(title)s.%(ext)s"
    output_path = str(destino / template)

    def _al_descargar(estado: dict):
        if progreso is not None and estado.get("status") == "downloading":
            total = estado.get("total_bytes") or estado.get("total_bytes_estimate")
            progreso(estado.get("downloaded_bytes") or 0, total, "bytes")

    # 3. Instrucciones para la descarga (equivalen a: yt-dlp -f bestaudio/best -x --audio-format mp3)
    opciones = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        "progress_hooks": [_al_descargar],
        "quiet": silencioso,
        "no_warnings": silencioso,
        "noprogress": silencioso,
    }

    logger.info("Inicia la descarga")
    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Error al descargar el audio: {e}")
        raise RuntimeError(f"Error crítico en yt-dlp descargando el audio: {e}") from e

    # 4. yt-dlp nos dice la ruta final (ya convertida a mp3), sin tener que adivinarla
    descargas = info.get("requested_downloads") or [{}]
    ruta = descargas[0].get("filepath")
    if not ruta or not Path(ruta).exists():
        raise FileNotFoundError("yt-dlp terminó, pero no se encontró el .mp3 descargado.")

    audio_path = Path(ruta)
    logger.info(f"Audio descargado en {audio_path}")

    return audio_path
