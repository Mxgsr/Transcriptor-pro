# Ubicación: utils/validators.py
# Comprueba si un texto es una URL y si tiene buen formato (avisa si el dominio no es uno conocido),
# y limpia las rutas de archivo que el usuario escribe o arrastra a la terminal.
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from src import plataforma
from src.config import DOMINIOS_PERMITIDOS

logger = logging.getLogger(__name__)

def es_url(s: str) -> bool:
    """Verifica si un string tiene el formato básico de una URL."""
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://")

def _dominio_conocido(host: str) -> bool:
    """True si el host es uno de la lista o un subdominio suyo (www.youtube.com sí; youtube.com.evil.example no)."""
    return any(host == dominio or host.endswith("." + dominio) for dominio in DOMINIOS_PERMITIDOS if dominio)


def es_url_valida(url: str) -> bool:
    """
    Valida el formato de la URL (http/https y con host). Si el dominio no está en la lista de
    dominios conocidos (DOMINIOS_PERMITIDOS) solo AVISA en el registro y la acepta igual: no es un
    bloqueo. Es una decisión del dueño, para que se pueda transcribir de otros sitios que yt-dlp entiende.
    """
    try:
        result = urlparse(url)
        # hostname ya viene en minúsculas y sin puerto ni credenciales (usuario@): se compara eso y no
        # netloc, porque "https://youtube.com@evil.example" tiene a youtube.com en netloc.
        host = result.hostname
        if result.scheme not in ("http", "https") or not host:
            return False

        if not _dominio_conocido(host.rstrip(".")):
            logger.warning("Aviso: el dominio no está en la lista de dominios conocidos: %s", host)
            logger.warning("Continuando de todas formas (puedes cancelar con Ctrl+C)...")
        return True
    except Exception as e:
        logger.error(f"Error al validar URL: {e}")
        return False


def limpiar_ruta(texto: str) -> Path:
    """
    Acepta rutas escritas o arrastradas a la terminal: "entre comillas" o con los espacios
    escapados como hace la Terminal del Mac (Mi\\ audio.m4a).
    En Windows la \\ separa carpetas (C:\\Users\\...), así que ahí no se toca.
    """
    texto = texto.strip()
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in "'\"":
        texto = texto[1:-1]
    elif not plataforma.es_windows():
        texto = re.sub(r"\\(.)", r"\1", texto)
    return Path(texto).expanduser()
