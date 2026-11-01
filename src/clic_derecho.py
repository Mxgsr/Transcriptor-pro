# Ubicación: src/clic_derecho.py
# «Transcribir con Transcriptor» en el clic derecho de los archivos.
# - Mac: una Acción rápida de Automator (un .workflow en ~/Library/Services) que aparece en
#   clic derecho > Acciones rápidas, y llama a `transcriptor en-fila ARCHIVO...`.
# - Windows: un acceso en la carpeta «Enviar a» (clic derecho > Enviar a > Transcriptor).
# - La fila: `en-fila` puede lanzarse varias veces seguidas (un clic derecho por archivo); un candado
#   (fila.lock) hace que cada lanzamiento espere a que termine el anterior y no compitan por el modelo.
# Solo librería estándar. Todo devuelve bool y nunca lanza errores (se registran con logger).
# IMPORTANTE: el .workflow de Mac está escrito de memoria, imitando uno de Automator; hay que
# probarlo en un Mac real. Lo de Windows tampoco se ha probado en un Windows real.
import ctypes
import logging
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

NOMBRE = "Transcribir con Transcriptor"
TEXTO_DONDE = ("Haz clic derecho en un audio o video y elige «Transcribir con Transcriptor» "
               "(en algunos computadores está dentro de «Acciones rápidas» o «Enviar a»).")

# Un candado de más de estas horas se considera abandonado si no se puede saber si su proceso vive
HORAS_CANDADO_VIEJO = 24
SEGUNDOS_ESPERA_FILA = 5

# Extensiones que se aceptan en `en-fila` (las mismas que usa fragmentos.py para buscar el audio)
EXTENSIONES = (".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma", ".aiff", ".aif", ".caf",
               ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv", ".3gp")


def disponible() -> bool:
    return sys.platform in ("darwin", "win32")


def es_audio_o_video(ruta) -> bool:
    return Path(ruta).suffix.lower() in EXTENSIONES


def comando_del_programa() -> list:
    """
    Cómo llamar a este mismo programa con rutas absolutas: el clic derecho se ejecuta sin el PATH
    de la terminal, así que «transcriptor» a secas no se encontraría.
    """
    encontrado = shutil.which("transcriptor")
    if encontrado:
        return [encontrado]
    main = Path(__file__).resolve().parent.parent / "main.py"
    # src/cli.py no tiene `if __name__ == "__main__"`, así que `-m src.cli` no sirve: se usa main.py
    return [sys.executable, str(main)]


# ---------------------------------------------------------------------------
# Mac: Acción rápida de Automator
# ---------------------------------------------------------------------------
def _ruta_workflow() -> Path:
    return Path.home() / "Library" / "Services" / f"{NOMBRE}.workflow"


# Tipos de archivo que acepta la acción: audio, video y audiovisual
_TIPOS_MAC = ["public.audio", "public.movie", "public.audiovisual-content"]


def _script_mac() -> str:
    comando = " ".join(shlex.quote(parte) for parte in comando_del_programa())
    # Se deja en SEGUNDO PLANO (nohup ... &!) a propósito: un servicio de Automator que dura horas
    # puede ser cortado por el sistema, y mientras no termina el clic derecho parece "colgado".
    # En segundo plano la acción termina al instante y la transcripción sigue sola; el aviso de
    # «Transcripción lista» (notificación) reemplaza al engranaje de Automator. Si se lanzan varios
    # archivos seguidos, el candado de la fila los ordena. El PATH extra es para que se encuentren
    # ffmpeg y compañía de Homebrew, que un servicio no ve.
    return ('export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
            f'nohup {comando} en-fila "$@" >/dev/null 2>&1 &!\n')


def _info_plist_mac() -> dict:
    return {
        "NSServices": [{
            "NSMenuItem": {"default": NOMBRE},
            "NSMessage": "runWorkflowAsService",
            "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
            "NSSendFileTypes": list(_TIPOS_MAC),
        }],
    }


def _document_wflow_mac() -> dict:
    """La estructura que escribe Automator para un servicio con una sola acción «Ejecutar script de shell»."""
    return {
        "AMApplicationBuild": "523",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [{
            "action": {
                "AMAccepts": {"Container": "List", "Optional": True, "Types": ["com.apple.cocoa.string"]},
                "AMActionVersion": "2.0.3",
                "AMApplication": ["Automator"],
                "AMParameterProperties": {
                    "COMMAND_STRING": {}, "CheckedForUserDefaultShell": {}, "inputMethod": {},
                    "shell": {}, "source": {},
                },
                "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
                "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
                "ActionName": "Run Shell Script",
                "ActionParameters": {
                    "COMMAND_STRING": _script_mac(),
                    "CheckedForUserDefaultShell": True,
                    "inputMethod": 1,  # 1 = pasar la entrada como argumentos ("$@")
                    "shell": "/bin/zsh",
                    "source": "",
                },
                "BundleIdentifier": "com.apple.RunShellScript",
                "CFBundleVersion": "2.0.3",
                "CanShowSelectedItemsWhenRun": False,
                "CanShowWhenRun": True,
                "Category": ["AMCategoryUtilities"],
                "Class Name": "RunShellScriptAction",
                "InputUUID": str(uuid.uuid4()).upper(),
                "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
                "OutputUUID": str(uuid.uuid4()).upper(),
                "UUID": str(uuid.uuid4()).upper(),
                "UnlocalizedApplications": ["Automator"],
                "arguments": {},
                "isViewVisible": True,
                "location": "309.000000:253.000000",
                "nibPath": "/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib",
            },
            "isViewVisible": True,
        }],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {},
            "applicationPaths": [],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 15,
            "processesInput": False,
            "serviceApplicationBundleID": "com.apple.finder",
            "serviceApplicationPath": "/System/Library/CoreServices/Finder.app",
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": 0,
            "systemImageName": "NSActionTemplate",
            "useAutomaticInputType": False,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }


def _instalar_mac() -> bool:
    contenido = _ruta_workflow() / "Contents"
    contenido.mkdir(parents=True, exist_ok=True)
    with open(contenido / "Info.plist", "wb") as archivo:
        plistlib.dump(_info_plist_mac(), archivo)
    with open(contenido / "document.wflow", "wb") as archivo:
        plistlib.dump(_document_wflow_mac(), archivo)
    # Que el Finder se entere sin cerrar sesión (si no funciona, aparece tras reiniciar la sesión)
    try:
        subprocess.run(["/System/Library/CoreServices/pbs", "-update"], capture_output=True, timeout=15)
    except Exception as error:
        logger.debug("No se pudo refrescar los servicios: %s", error)
    return True


# ---------------------------------------------------------------------------
# Windows: carpeta «Enviar a»
# ---------------------------------------------------------------------------
def _ruta_cmd() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "SendTo" / "Transcriptor.cmd"


def _ruta_para_cmd(parte: str) -> str:
    """Con %USERPROFILE% en lugar de la carpeta personal: el archivo queda en ASCII aunque el usuario tenga tildes."""
    perfil = os.environ.get("USERPROFILE")
    if perfil:
        try:
            relativa = Path(parte).relative_to(perfil)
            return "%USERPROFILE%\\" + str(relativa).replace("/", "\\")
        except ValueError:
            pass
    return parte


def _texto_cmd() -> str:
    programa = " ".join(f'"{_ruta_para_cmd(parte)}"' for parte in comando_del_programa())
    lineas = [
        "@echo off",
        "chcp 65001 >nul",  # consola en UTF-8: que las tildes del nombre del archivo se lean bien
        f"{programa} en-fila %*",
        # Si algo falló, la ventana se queda abierta para poder leerlo
        "if errorlevel 1 pause",
    ]
    return "\r\n".join(lineas) + "\r\n"


def _instalar_windows() -> bool:
    ruta = _ruta_cmd()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 SIN BOM: el BOM se leería como parte de la primera línea y rompería el «@echo off».
    # Normalmente el archivo es ASCII puro (por el %USERPROFILE%); UTF-8 + chcp 65001 cubre el resto.
    ruta.write_bytes(_texto_cmd().encode("utf-8"))
    return True


# ---------------------------------------------------------------------------
# Interfaz común
# ---------------------------------------------------------------------------
def instalar() -> bool:
    try:
        if sys.platform == "darwin":
            return _instalar_mac()
        if sys.platform == "win32":
            return _instalar_windows()
    except Exception as error:
        logger.warning("No se pudo instalar el clic derecho: %s", error)
    return False


def _ruta_instalada():
    if sys.platform == "darwin":
        return _ruta_workflow()
    if sys.platform == "win32":
        return _ruta_cmd()
    return None


def instalado() -> bool:
    try:
        ruta = _ruta_instalada()
        return ruta is not None and ruta.exists()
    except Exception as error:
        logger.debug("No se pudo revisar el clic derecho: %s", error)
        return False


def quitar() -> bool:
    try:
        ruta = _ruta_instalada()
        if ruta is None:
            return False
        if ruta.is_dir():
            shutil.rmtree(ruta)
        elif ruta.exists():
            ruta.unlink()
        if sys.platform == "darwin":
            try:
                subprocess.run(["/System/Library/CoreServices/pbs", "-update"], capture_output=True, timeout=15)
            except Exception as error:
                logger.debug("No se pudo refrescar los servicios: %s", error)
        return True
    except Exception as error:
        logger.warning("No se pudo quitar el clic derecho: %s", error)
        return False


# ---------------------------------------------------------------------------
# La fila: un candado para que las transcripciones se hagan de a una
# ---------------------------------------------------------------------------
def _ruta_candado() -> Path:
    from src import historial
    return historial.carpeta() / "fila.lock"


def _proceso_vive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
        kernel32 = ctypes.windll.kernel32
        manejador = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not manejador:
            return False
        try:
            codigo = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(manejador, ctypes.byref(codigo))) and codigo.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(manejador)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe, aunque sea de otro usuario
    except OSError:
        return False
    return True


def _candado_abandonado(ruta: Path) -> bool:
    """True si el candado es de un proceso que ya no existe (o tan viejo que no puede ser de una transcripción viva)."""
    try:
        if time.time() - ruta.stat().st_mtime > HORAS_CANDADO_VIEJO * 3600:
            return True
        return not _proceso_vive(int(ruta.read_text(encoding="utf-8").strip()))
    except FileNotFoundError:
        return False  # lo soltaron justo ahora: el próximo intento lo tomará
    except (OSError, ValueError):
        # Vacío o ilegible: probablemente el otro proceso lo está escribiendo en este instante.
        # Lo damos por abandonado solo si lleva rato así.
        try:
            return time.time() - ruta.stat().st_mtime > 60
        except OSError:
            return False


def tomar_candado(esperar: Callable[[float], None] = time.sleep, al_esperar: Callable[[], None] = None) -> Path:
    """Espera su turno y toma el candado de la fila. Devuelve la ruta para soltarla luego con soltar_candado."""
    ruta = _ruta_candado()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    avisado = False
    while True:
        try:
            descriptor = os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _candado_abandonado(ruta):
                try:
                    ruta.unlink()
                except OSError:
                    pass
                continue
            if not avisado and al_esperar:
                al_esperar()
                avisado = True
            esperar(SEGUNDOS_ESPERA_FILA)
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
            archivo.write(str(os.getpid()))
        return ruta


def soltar_candado(ruta: Path):
    try:
        ruta.unlink()
    except OSError as error:
        logger.debug("No se pudo borrar el candado de la fila: %s", error)
