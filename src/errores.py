# Ubicación: src/errores.py
# Errores con salida: guarda el detalle de cada error en un archivo (para pedir ayuda sin abrir
# una terminal con -v) y traduce los errores comunes a un mensaje simple para quien no es técnico.
# Funciones pequeñas y sin librerías pesadas, para poder probarlas una por una.
import errno
import platform
import socket
import sys
import traceback
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

# Cuántos archivos de error se conservan (los más recientes)
MAX_ARCHIVOS = 30

MENSAJE_FALTA_TOKEN = ("Para identificar hablantes falta tu clave de Hugging Face. "
                       "Vuelve a ejecutar el instalador y pégala cuando te la pida.")
MENSAJE_SIN_INTERNET = ("No hay conexión a internet (o no se pudo llegar al servidor). "
                        "Revisa tu conexión y vuelve a intentarlo.")
MENSAJE_NO_ES_AUDIO = "Ese archivo no parece ser de audio o video, o está dañado."
MENSAJE_DISCO_LLENO = "El disco está lleno. Libera espacio y vuelve a intentarlo."

# Nombres de tipo de las librerías de red (se miran por nombre para no importarlas)
_TIPOS_SIN_INTERNET = {"ConnectionError", "ConnectError", "ConnectTimeout", "NewConnectionError", "MaxRetryError"}

# Textos típicos (en minúsculas)
_TEXTOS_SIN_INTERNET = (
    "getaddrinfo", "failed to resolve", "temporary failure in name resolution", "network is unreachable",
    "no address associated", "max retries exceeded", "name or service not known", "nodename nor servname",
)
_TEXTOS_NO_ES_AUDIO = (
    "invalid data found when processing input", "does not contain any stream", "could not find codec",
    "failed to load audio", "moov atom not found",
)


def cadena(e: BaseException) -> list:
    """El error y todas sus causas (__cause__ / __context__), sin repetirse ni caer en ciclos."""
    vistos, lista = set(), []
    while e is not None and id(e) not in vistos:
        vistos.add(id(e))
        lista.append(e)
        e = e.__cause__ or e.__context__
    return lista


def _textos(errores: list) -> str:
    return " | ".join(str(x) for x in errores).lower()


def falta_token(errores: list) -> bool:
    """El ValueError de diarizer.cargar_pipeline cuando no hay clave de Hugging Face."""
    return any(isinstance(x, ValueError) and str(x).startswith("Falta HF_TOKEN") for x in errores)


def sin_internet(errores: list) -> bool:
    for x in errores:
        if isinstance(x, (urllib.error.URLError, socket.gaierror)):
            return True
        if type(x).__name__ in _TIPOS_SIN_INTERNET:
            return True
    texto = _textos(errores)
    return any(t in texto for t in _TEXTOS_SIN_INTERNET)


def no_es_audio(errores: list) -> bool:
    texto = _textos(errores)
    return any(t in texto for t in _TEXTOS_NO_ES_AUDIO)


def disco_lleno(errores: list) -> bool:
    return any(isinstance(x, OSError) and x.errno == errno.ENOSPC for x in errores)


def archivo_no_encontrado(errores: list) -> Optional[str]:
    """La ruta que no existe, si el error la trae (si no, el mensaje del error ya dice qué pasó)."""
    for x in errores:
        if isinstance(x, FileNotFoundError) and x.filename:
            return str(x.filename)
    return None


def mensaje_simple(e: BaseException) -> Optional[str]:
    """El mensaje para personas no técnicas si el error es uno de los comunes; None si no se reconoce."""
    errores = cadena(e)
    if falta_token(errores):
        return MENSAJE_FALTA_TOKEN
    if disco_lleno(errores):
        return MENSAJE_DISCO_LLENO
    ruta = archivo_no_encontrado(errores)
    if ruta:
        return f"No encuentro el archivo: {ruta}"
    if sin_internet(errores):
        return MENSAJE_SIN_INTERNET
    if no_es_audio(errores):
        return MENSAJE_NO_ES_AUDIO
    return None


# --- Archivo con el detalle ---------------------------------------------------

def carpeta_errores() -> Path:
    from src import historial
    return historial.carpeta() / "errores"


def _version() -> str:
    try:
        # Importación diferida: actualizar importa ajustes e historial, y no hace falta al cargar este módulo
        from src import actualizar
        version = actualizar.version_instalada()
    except Exception:
        return "desconocida"
    # version_instalada() responde "0" cuando no pudo saber la versión
    return "desconocida" if version == "0" else version


def _sin_secretos(texto: str) -> str:
    """Quita la clave de Hugging Face si por casualidad aparece en el texto."""
    try:
        from src import config
        token = getattr(config, "HF_TOKEN", None)
    except Exception:
        token = None
    return texto.replace(token, "***") if token else texto


def armar_detalle(e: BaseException, ahora: Optional[datetime] = None) -> str:
    """El texto del archivo de error. A propósito NO incluye variables de entorno."""
    ahora = ahora or datetime.now()
    seguimiento = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    lineas = [
        f"Fecha: {ahora:%Y-%m-%d %H:%M:%S}",
        f"Versión del programa: {_version()}",
        f"Sistema: {platform.platform()} ({sys.platform}, {platform.machine()})",
        f"Python: {platform.python_version()}",
        f"Comando: {' '.join(sys.argv)}",
        f"Error: {type(e).__name__}: {e}",
        "",
        seguimiento,
    ]
    return _sin_secretos("\n".join(lineas))


def guardar_detalle(e: BaseException) -> Optional[Path]:
    """Guarda el detalle en <historial>/errores/AAAA-MM-DD_HHMMSS.txt. Si no se puede, None (nunca lanza)."""
    try:
        ahora = datetime.now()
        # Privada: el detalle trae rutas, nombres de archivo y el comando usado
        from src import historial
        carpeta = historial.carpeta_privada("errores")
        base = f"{ahora:%Y-%m-%d_%H%M%S}"
        ruta, n = carpeta / f"{base}.txt", 2
        while ruta.exists():  # dos errores en el mismo segundo
            ruta = carpeta / f"{base}_{n}.txt"
            n += 1
        from utils.archivos import escribir_texto
        escribir_texto(ruta, armar_detalle(e, ahora), privado=True)
        _limpiar_viejos(carpeta)
        return ruta
    except Exception:
        return None


def _limpiar_viejos(carpeta: Path):
    """Deja solo los MAX_ARCHIVOS más recientes (el nombre lleva la fecha, así que ordena solo)."""
    archivos = sorted(carpeta.glob("*.txt"))
    for viejo in archivos[:-MAX_ARCHIVOS]:
        try:
            viejo.unlink()
        except OSError:
            pass


def ruta_corta(ruta: Path) -> str:
    """La ruta con ~ en lugar de la carpeta personal, para que se lea mejor."""
    try:
        relativa = Path(ruta).relative_to(Path.home())
    except (ValueError, RuntimeError):
        return str(ruta)
    return str(Path("~") / relativa)
