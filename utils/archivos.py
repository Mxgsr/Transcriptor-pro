# Ubicación: utils/archivos.py
# Leer y escribir archivos sin perder datos: escritura atómica (o queda el archivo viejo completo
# o queda el nuevo completo, nunca uno a medias) y lectura de JSON que, si encuentra el archivo
# dañado, lo aparta como «.corrupto» en vez de dejar que la siguiente escritura lo borre.
# También los archivos y carpetas «privados» (solo los puede leer quien los creó) para lo que vive en
# ~/.transcriptor: huellas de voz, historial, la clave de Hugging Face, transcripciones en vistas/...
# En un Mac compartido, con los permisos normales (755/644) otros usuarios podrían leerlos.
# Solo librería estándar: lo usan formatters, historial, voces, vista, errores y modelos.
import json
import logging
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

def _umask_actual() -> int:
    anterior = os.umask(0)
    os.umask(anterior)
    return anterior


# Permisos de un archivo nuevo: los normales del sistema (respeta el umask de quien lo ejecuta), como cuando
# se escribía con open(); mkstemp crea con 0600 y por eso hay que ponerlos a mano.
_PERMISOS_NUEVO = 0o666 & ~_umask_actual()


def _es_windows() -> bool:
    return os.name == "nt"


def _reemplazar(origen, destino):
    """os.replace con unos reintentos en Windows: si el antivirus, OneDrive o el buscador tienen el destino
    abierto un instante, el reemplazo falla con PermissionError y suele funcionar medio segundo después."""
    intentos = 6 if _es_windows() else 1
    for intento in range(intentos):
        try:
            os.replace(origen, destino)
            return
        except PermissionError:
            if intento == intentos - 1:
                raise
            time.sleep(0.15)


def _es_mio(info: os.stat_result) -> bool:
    """Si el archivo o carpeta es del usuario que ejecuta. Sin getuid (Windows) se da por hecho que sí."""
    getuid = getattr(os, "getuid", None)
    return getuid is None or info.st_uid == getuid()


def crear_carpeta_privada(ruta) -> Path:
    """
    Crea la carpeta (y las de arriba si faltan) de modo que solo la pueda abrir quien la creó (0700).
    Si ya existía con permisos más abiertos y es nuestra, la aprieta a 0700: así quien ya tenía
    ~/.transcriptor de antes de este cambio también queda protegido. Nunca toca la carpeta personal
    ni carpetas de otro dueño. Los fallos de permisos se ignoran (la carpeta sigue sirviendo igual).
    En Windows los permisos POSIX no aplican (os.chmod solo cambia «solo lectura»): ahí solo se crea.
    Sí lanza OSError si la carpeta no se puede crear, igual que mkdir.
    """
    ruta = Path(ruta)
    ya_existia = ruta.is_dir()
    ruta.mkdir(parents=True, exist_ok=True)
    if _es_windows():
        return ruta
    try:
        if not ya_existia:
            # mkdir aplica el umask (con 022 quedaría 755): por eso el chmod explícito
            os.chmod(ruta, 0o700)
            return ruta
        info = ruta.stat()
        abierta = stat.S_IMODE(info.st_mode) & 0o077
        es_casa = os.path.realpath(ruta) == os.path.realpath(Path.home())
        if abierta and _es_mio(info) and not es_casa:
            os.chmod(ruta, stat.S_IMODE(info.st_mode) & 0o700)
    except OSError as e:
        logger.debug(f"No se pudo restringir el permiso de {ruta}: {e}")
    return ruta


def _escribir_atomico(ruta, texto: str, crear_carpeta: bool = True, privado: bool = False):
    """Escribe en un temporal ÚNICO de la misma carpeta y lo cambia por el destino con os.replace.
    Con privado=True el archivo queda 0600 aunque el destino tuviera otros permisos."""
    # Si la ruta es un enlace, se escribe en el archivo real (como hacía open()), no se reemplaza el enlace
    ruta = Path(os.path.realpath(ruta))
    if crear_carpeta:
        if privado and not ruta.parent.is_dir():
            # Lo privado no debería quedar en una carpeta recién creada que cualquiera puede listar
            crear_carpeta_privada(ruta.parent)
        else:
            ruta.parent.mkdir(parents=True, exist_ok=True)
    # Temporal único (no «nombre.tmp»): dos procesos o hilos guardando a la vez no se pisan el temporal.
    # Misma carpeta para que os.replace sea atómico (no cruza discos).
    fd, nombre_temporal = tempfile.mkstemp(dir=ruta.parent, prefix=ruta.name + ".", suffix=".tmp")
    try:
        # newline por defecto: igual que open(..., "w") de antes (en Windows sigue siendo \r\n)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            # Sin fsync, un corte de luz puede dejar el reemplazo hecho pero con el contenido vacío
            os.fsync(f.fileno())
        # Privado: mkstemp ya crea el temporal con 0600 desde el primer instante, así que basta con no
        # ampliarlos (un chmod a 0600 después dejaría un momento en que otro podría abrirlo).
        if not privado:
            try:
                permisos = stat.S_IMODE(ruta.stat().st_mode)
            except OSError:
                permisos = _PERMISOS_NUEVO
            os.chmod(nombre_temporal, permisos)
        _reemplazar(nombre_temporal, ruta)
    except BaseException:
        try:
            os.unlink(nombre_temporal)
        except OSError:
            pass
        raise


def escribir_texto(ruta, texto: str, crear_carpeta: bool = True, privado: bool = False):
    """Guarda un texto en UTF-8 de forma atómica. Crea la carpeta si falta (salvo crear_carpeta=False:
    formatters conserva el error de antes cuando la carpeta de salida no existe).
    privado=True: solo lo puede leer quien lo creó (0600). Sin él, los permisos normales (umask), que
    es lo que necesitan los .txt/.json junto al audio para que el Grabador u Obsidian los lean."""
    _escribir_atomico(ruta, texto, crear_carpeta, privado)


def escribir_json(ruta, datos, crear_carpeta: bool = True, privado: bool = False):
    """Guarda datos como JSON legible (UTF-8, sin escapar tildes) de forma atómica."""
    _escribir_atomico(ruta, json.dumps(datos, ensure_ascii=False, indent=2), crear_carpeta, privado)


def _apartar_corrupto(ruta: Path) -> Optional[Path]:
    """Mueve el archivo dañado a «<nombre>.corrupto» (o .corrupto.2, .3...). None si no se pudo."""
    destino = ruta.with_name(ruta.name + ".corrupto")
    n = 2
    while destino.exists():
        destino = ruta.with_name(f"{ruta.name}.corrupto.{n}")
        n += 1
    try:
        os.replace(ruta, destino)
    except OSError as e:
        logger.warning(f"No se pudo apartar {ruta} como {destino.name}: {e}")
        return None
    return destino


def leer_json(ruta, por_defecto: Any = None):
    """
    Lee un JSON. Tolera BOM (el Bloc de notas de Windows lo agrega). Si el archivo no existe
    devuelve por_defecto. Si está dañado, lo aparta como «.corrupto» (así la próxima escritura no
    borra datos que alguien podría recuperar), avisa en el registro y devuelve por_defecto.
    """
    ruta = Path(ruta)
    try:
        texto = ruta.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return por_defecto
    except UnicodeDecodeError:
        texto = None
    except OSError as e:
        logger.warning(f"No se pudo leer {ruta}: {e}")
        return por_defecto
    try:
        if texto is None:
            raise ValueError("no es UTF-8")
        return json.loads(texto)
    except ValueError:
        apartado = _apartar_corrupto(ruta)
        if apartado:
            logger.warning(f"{ruta.name} estaba dañado; se guardó una copia como {apartado.name}")
        else:
            logger.warning(f"{ruta.name} está dañado y no se pudo apartar")
        return por_defecto
