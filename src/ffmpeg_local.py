# Ubicación: src/ffmpeg_local.py
# ffmpeg sin instalar nada aparte: yt-dlp (pasar a mp3), mlx-whisper (leer el audio) y los
# fragmentos de cada hablante lo buscan con el nombre "ffmpeg". Si el computador no lo tiene,
# usamos el que trae el paquete imageio-ffmpeg (viene con Transcriptor) y lo ponemos en el PATH.
# ruta_ffmpeg() da la ruta completa para lo que lanzamos nosotros (los fragmentos): en Windows, un
# ffmpeg.exe en la carpeta actual (la del audio) se ejecutaría en vez del bueno (ver rutas_windows).
import logging
import os
import shutil
from pathlib import Path

from src import plataforma, rutas_windows

logger = logging.getLogger(__name__)


def _carpeta_bin() -> Path:
    return Path(os.getenv("TRANSCRIPTOR_HOME", "~/.transcriptor")).expanduser() / "bin"


def _nombre_ejecutable() -> str:
    return "ffmpeg.exe" if plataforma.es_windows() else "ffmpeg"


def ruta_ffmpeg() -> str:
    """
    La ruta completa del ffmpeg a usar, en este orden: el de ~/.transcriptor/bin (el que deja
    asegurar_ffmpeg), el de imageio-ffmpeg, uno del PATH que no esté en la carpeta actual, y como
    último recurso el nombre "ffmpeg" (si no hay ninguno, falla igual que antes).
    """
    propio = _carpeta_bin() / _nombre_ejecutable()
    if propio.is_file():  # is_file sigue el enlace: un enlace roto no cuenta
        return str(propio)
    try:
        import imageio_ffmpeg  # Importación diferida: puede no estar instalado

        ejecutable = imageio_ffmpeg.get_ffmpeg_exe()
        # imageio puede devolver el nombre suelto «ffmpeg» (si usa el del PATH): sin ruta absoluta no sirve,
        # porque Path("ffmpeg").is_file() miraría la carpeta actual
        if ejecutable and os.path.isabs(ejecutable) and Path(ejecutable).is_file():
            return str(Path(ejecutable).resolve())
    except Exception as e:
        logger.debug(f"No hay ffmpeg de imageio-ffmpeg: {e}")
    return rutas_windows.buscar_programa("ffmpeg") or "ffmpeg"


def asegurar_ffmpeg() -> bool:
    """
    Deja un comando "ffmpeg" disponible para este proceso. Retorna True si hay ffmpeg.
    Nunca impide usar el programa: si algo falla, se sigue como antes (sin ffmpeg).
    """
    # buscar_programa y no shutil.which: en Windows, un ffmpeg.exe en la carpeta actual no cuenta
    if rutas_windows.buscar_programa("ffmpeg"):
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
    destino = carpeta / _nombre_ejecutable()
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        if destino.is_symlink() and destino.resolve() != ejecutable.resolve():
            destino.unlink()  # apunta a una instalación anterior
        # Una copia cortada a medias (otro tamaño que el original) se trata como si no existiera
        if destino.exists() and not destino.is_symlink() and destino.stat().st_size != ejecutable.stat().st_size:
            try:
                destino.unlink()
            except OSError:
                pass  # en uso por otro proceso (Windows): seguimos con la copia que ya hay, que sirve
        if not destino.exists():
            try:
                destino.symlink_to(ejecutable)
            except OSError:
                # Windows no deja crear enlaces sin permisos de administrador: copiamos el archivo.
                # Se copia a un temporal y se renombra, para no dejar un ffmpeg.exe roto si se corta.
                temporal = destino.with_name(destino.name + ".tmp")
                try:
                    shutil.copy2(ejecutable, temporal)
                    os.replace(temporal, destino)
                finally:
                    temporal.unlink(missing_ok=True)
    except OSError as e:
        logger.debug(f"No se pudo preparar ffmpeg en {carpeta}: {e}")
        return False

    os.environ["PATH"] = str(carpeta) + os.pathsep + os.environ.get("PATH", "")
    return True
