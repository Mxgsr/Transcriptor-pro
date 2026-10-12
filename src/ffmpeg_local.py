# Ubicación: src/ffmpeg_local.py
# ffmpeg sin instalar nada aparte: yt-dlp (pasar a mp3), mlx-whisper (leer el audio) y los
# fragmentos de cada hablante lo buscan con el nombre "ffmpeg". Si el computador no lo tiene,
# usamos el que trae el paquete imageio-ffmpeg (viene con Transcriptor) y lo ponemos en el PATH.
import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _carpeta_bin() -> Path:
    return Path(os.getenv("TRANSCRIPTOR_HOME", "~/.transcriptor")).expanduser() / "bin"


def asegurar_ffmpeg() -> bool:
    """
    Deja un comando "ffmpeg" disponible para este proceso. Retorna True si hay ffmpeg.
    Nunca impide usar el programa: si algo falla, se sigue como antes (sin ffmpeg).
    """
    if shutil.which("ffmpeg"):
        return True
    try:
        import imageio_ffmpeg
        ejecutable = Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception as e:
        logger.debug(f"No hay ffmpeg de imageio-ffmpeg: {e}")
        return False

    # El ejecutable de imageio-ffmpeg tiene otro nombre (ffmpeg-macos-aarch64-v7.1...):
    # le hacemos un acceso con el nombre "ffmpeg" en ~/.transcriptor/bin.
    carpeta = _carpeta_bin()
    destino = carpeta / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        if destino.is_symlink() and destino.resolve() != ejecutable.resolve():
            destino.unlink()  # apunta a una instalación anterior
        if not destino.exists():
            try:
                destino.symlink_to(ejecutable)
            except OSError:
                # Windows no deja crear enlaces sin permisos de administrador: copiamos el archivo
                shutil.copy2(ejecutable, destino)
    except OSError as e:
        logger.debug(f"No se pudo preparar ffmpeg en {carpeta}: {e}")
        return False

    os.environ["PATH"] = str(carpeta) + os.pathsep + os.environ.get("PATH", "")
    return True
