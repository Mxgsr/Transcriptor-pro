# Ubicación: src/clic_derecho.py
# «Transcribir con Transcriptor» en el clic derecho de los archivos.
# - Mac: una Acción rápida de Automator (un .workflow en ~/Library/Services) que aparece en
#   clic derecho > Acciones rápidas, y abre una ventana de Terminal con `transcriptor en-fila ARCHIVO...`.
# - Windows: un acceso directo (.lnk) en la carpeta «Enviar a» (clic derecho > Enviar a > Transcriptor)
#   que abre el programa directamente, sin pasar por cmd (ver más abajo por qué).
# - La fila: `en-fila` puede lanzarse varias veces seguidas (un clic derecho por archivo); un candado
#   (un bloqueo del sistema sobre fila.lock) hace que cada lanzamiento espere a que termine el anterior y no compitan por el modelo.
# Solo librería estándar. Todo devuelve bool y nunca lanza errores (se registran con logger).
# IMPORTANTE: el .workflow de Mac está escrito de memoria, imitando uno de Automator; hay que
# probarlo en un Mac real. Lo de Windows tampoco se ha probado en un Windows real.
import base64
import errno
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

from src import plataforma, rutas_windows
from src.entorno import sin_secretos

logger = logging.getLogger(__name__)

NOMBRE = "Transcribir con Transcriptor"
TEXTO_DONDE = ("Haz clic derecho en un audio o video y elige «Transcribir con Transcriptor» "
               "(en algunos computadores está dentro de «Acciones rápidas» o «Enviar a»).")

SEGUNDOS_ESPERA_FILA = 5

# Extensiones que se aceptan en `en-fila` (las mismas que usa fragmentos.py para buscar el audio)
EXTENSIONES = (".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma", ".aiff", ".aif", ".caf",
               ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv", ".3gp")


def disponible() -> bool:
    return plataforma.es_mac() or plataforma.es_windows()


def es_audio_o_video(ruta) -> bool:
    return Path(ruta).suffix.lower() in EXTENSIONES


def comando_del_programa() -> list:
    """
    Cómo llamar a este mismo programa con rutas absolutas: el clic derecho se ejecuta sin el PATH
    de la terminal, así que «transcriptor» a secas no se encontraría.
    """
    # buscar_programa (no shutil.which): en Windows no mira la carpeta actual. Un .bat/.cmd no sirve de
    # destino del acceso directo: volvería a pasar por cmd, justo lo que se evita (ver _instalar_windows).
    encontrado = rutas_windows.buscar_programa("transcriptor")
    if encontrado and not encontrado.lower().endswith((".bat", ".cmd")):
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
    # Abre una ventana de Terminal con la transcripción: ahí se ve el avance y, al terminar, se
    # ponen los nombres de los hablantes como desde el menú. (Primero corría escondido en segundo
    # plano y no se veía nada hasta el aviso final: Max lo probó y no sabía cuánto llevaba ni cómo
    # nombrar a los hablantes.) Se escribe un .command temporal con el comando y los archivos ya
    # entre comillas, y `open -a Terminal` lo abre: así no hace falta permiso para controlar Terminal.
    # El .command se borra solo al empezar. El PATH extra es para el ffmpeg de Homebrew.
    return (
        'f="${TMPDIR:-/tmp}/transcriptor-$$-$RANDOM.command"\n'
        '{\n'
        "  print -r -- '#!/bin/zsh'\n"
        "  print -r -- 'rm -f \"$0\"'\n"
        "  print -r -- 'export PATH=\"/opt/homebrew/bin:/usr/local/bin:$PATH\"'\n"
        f"  print -r -- {shlex.quote(comando)}' en-fila '${{(q)@}}\n"
        '} > "$f"\n'
        'chmod +x "$f"\n'
        'open -a Terminal "$f"\n'
    )


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
        subprocess.run(["/System/Library/CoreServices/pbs", "-update"], capture_output=True, timeout=15,
                       env=sin_secretos())
    except Exception as error:
        logger.debug("No se pudo refrescar los servicios: %s", error)
    return True


# ---------------------------------------------------------------------------
# Windows: carpeta «Enviar a»
# ---------------------------------------------------------------------------
# Antes era un Transcriptor.cmd con `"programa" en-fila %*`. Era peligroso: el Explorador solo pone
# comillas a las rutas con espacios, así que un archivo llamado `x&calc&.mp3` llegaba sin comillas y
# cmd ejecutaba lo que hubiera tras el `&` (también `|`, `^`, `<`, `>`). Ahora es un acceso directo
# (.lnk) que apunta directo al programa: Windows le añade los archivos elegidos como argumentos del
# proceso, con su propia citación, sin pasar nunca por un intérprete de comandos.
def _carpeta_enviar_a() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "SendTo"


def _ruta_lnk() -> Path:
    # El nombre del archivo (sin .lnk) es lo que se ve en el menú «Enviar a»
    return _carpeta_enviar_a() / "Transcriptor.lnk"


def _ruta_cmd_antiguo() -> Path:
    """El .cmd de versiones anteriores: se borra al instalar y se reconoce para poder quitarlo."""
    return _carpeta_enviar_a() / "Transcriptor.cmd"


def _ruta_powershell() -> str:
    # Ruta absoluta: «powershell» a secas se buscaría en el PATH y en la carpeta actual, donde
    # alguien podría haber dejado otro programa con ese nombre.
    return rutas_windows.powershell()


# Script FIJO: las rutas y nombres llegan por variables de entorno, nunca pegados en el texto, para
# que una comilla, un `$` o una tilde en la carpeta del usuario no se interpreten como código.
_PS_ACCESO_DIRECTO = """$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$acceso = $shell.CreateShortcut($env:TRANSCRIPTOR_LNK)
$acceso.TargetPath = $env:TRANSCRIPTOR_DESTINO
$acceso.Arguments = $env:TRANSCRIPTOR_ARGUMENTOS
$acceso.WorkingDirectory = $env:TRANSCRIPTOR_CARPETA
$acceso.WindowStyle = 1
$acceso.Description = $env:TRANSCRIPTOR_DESCRIPCION
$acceso.IconLocation = $env:TRANSCRIPTOR_ICONO
$acceso.Save()
"""


def _datos_acceso_directo() -> dict:
    """Las variables de entorno que lee _PS_ACCESO_DIRECTO."""
    destino, *resto = comando_del_programa()
    return {
        "TRANSCRIPTOR_LNK": str(_ruta_lnk()),
        "TRANSCRIPTOR_DESTINO": destino,
        # Si el programa es [python.exe, main.py], main.py va como argumento, con las comillas que
        # espera Windows (list2cmdline sigue las mismas reglas con que el programa las vuelve a separar).
        "TRANSCRIPTOR_ARGUMENTOS": subprocess.list2cmdline([*resto, "en-fila"]),
        # La carpeta personal y no la del archivo: así el programa no arranca dentro de una carpeta
        # cualquiera (una descarga, un USB) donde podría haber archivos que se carguen por accidente.
        "TRANSCRIPTOR_CARPETA": str(Path.home()),
        "TRANSCRIPTOR_DESCRIPCION": NOMBRE,
        "TRANSCRIPTOR_ICONO": f"{destino},0",
    }


def _instalar_windows() -> bool:
    _carpeta_enviar_a().mkdir(parents=True, exist_ok=True)
    # Primero se borra el .cmd antiguo, aunque luego falle el acceso directo: es mejor quedarse sin
    # clic derecho (el menú lo dirá) que con el que permitía ejecutar comandos por el nombre del archivo.
    antiguo = _ruta_cmd_antiguo()
    if antiguo.exists():
        antiguo.unlink()
    # -EncodedCommand (UTF-16LE en base64), como en aviso.py: sin problemas de comillas ni de codificación
    codificado = base64.b64encode(_PS_ACCESO_DIRECTO.encode("utf-16-le")).decode("ascii")
    resultado = subprocess.run(
        [_ruta_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", codificado],
        # Los datos del acceso directo van por variables propias; el token de Hugging Face, no
        env=sin_secretos({**os.environ, **_datos_acceso_directo()}),
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # sin ventana negra que parpadee
    )
    if resultado.returncode != 0:
        detalle = (resultado.stderr or b"").decode("utf-8", "replace").strip()
        logger.warning("PowerShell no pudo crear el acceso de «Enviar a» (código %s): %s",
                       resultado.returncode, detalle)
        return False
    if not _ruta_lnk().exists():
        logger.warning("PowerShell terminó bien pero no apareció %s", _ruta_lnk())
        return False
    return True


# ---------------------------------------------------------------------------
# Interfaz común
# ---------------------------------------------------------------------------
def instalar() -> bool:
    try:
        if plataforma.es_mac():
            return _instalar_mac()
        if plataforma.es_windows():
            return _instalar_windows()
    except Exception as error:
        logger.warning("No se pudo instalar el clic derecho: %s", error)
    return False


def _rutas_instaladas() -> list:
    """Lo que puede haber instalado. En Windows también el .cmd antiguo, para que se pueda quitar."""
    if plataforma.es_mac():
        return [_ruta_workflow()]
    if plataforma.es_windows():
        return [_ruta_lnk(), _ruta_cmd_antiguo()]
    return []


def migrar_si_hace_falta() -> bool:
    """
    En Windows, quien tenía el «Enviar a» antiguo (Transcriptor.cmd, vulnerable a nombres de archivo con &)
    pasa solo al acceso directo nuevo, sin preguntar ni mostrar nada. Nunca lanza.
    """
    try:
        if plataforma.es_windows() and _ruta_cmd_antiguo().exists() and not _ruta_lnk().exists():
            return instalar()
    except Exception as error:
        logger.debug("No se pudo migrar el clic derecho: %s", error)
    return False


def instalado() -> bool:
    try:
        return any(ruta.exists() for ruta in _rutas_instaladas())
    except Exception as error:
        logger.debug("No se pudo revisar el clic derecho: %s", error)
        return False


def quitar() -> bool:
    try:
        rutas = _rutas_instaladas()
        if not rutas:
            return False
        for ruta in rutas:
            if ruta.is_dir():
                shutil.rmtree(ruta)
            elif ruta.exists():
                ruta.unlink()
        if plataforma.es_mac():
            try:
                subprocess.run(["/System/Library/CoreServices/pbs", "-update"], capture_output=True, timeout=15,
                               env=sin_secretos())
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


# El candado es un bloqueo del sistema operativo sobre fila.lock ABIERTO, no la mera existencia del
# archivo. Antes era un archivo con el PID creado en exclusiva, y fallaba de dos maneras: dos procesos
# que veían a la vez un candado abandonado podían terminar los dos dentro, y en Windows los PID se
# reutilizan (la fila podía quedarse esperando a un proceso ajeno hasta 24 h). Con el bloqueo del
# sistema, si el proceso muere el sistema lo suelta solo, y un fila.lock que haya quedado tirado
# (incluido uno del formato antiguo) no bloquea nada.
_abiertos = {}  # {ruta del candado: descriptor abierto}, para que soltar_candado lo encuentre


def _bloquear(descriptor: int) -> bool:
    """Intenta bloquear sin esperar. True si se pudo; False si otro proceso lo tiene."""
    # Importación diferida: fcntl solo existe en Mac/Linux y msvcrt solo en Windows
    if plataforma.es_windows():
        import msvcrt
        os.lseek(descriptor, 0, os.SEEK_SET)  # msvcrt bloquea desde la posición actual: siempre el byte 0
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as error:
            # EACCES / EDEADLOCK = «otro lo tiene». Cualquier otro error (carpeta que no admite bloqueos):
            # mejor transcribir sin fila que esperar para siempre, igual que en Mac/Linux.
            if error.errno in (errno.EACCES, errno.EDEADLK, errno.EAGAIN):
                return False
            logger.warning("No se pudo bloquear la fila, sigo sin esperar turno: %s", error)
        return True
    import fcntl
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, PermissionError):
        return False
    except OSError as error:
        # La carpeta no admite bloqueos (p. ej. una carpeta de red): mejor transcribir sin fila que no transcribir
        logger.warning("No se pudo bloquear la fila, sigo sin esperar turno: %s", error)
    return True


def _desbloquear(descriptor: int):
    if plataforma.es_windows():
        import msvcrt
        os.lseek(descriptor, 0, os.SEEK_SET)  # el mismo byte que se bloqueó
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def _es_el_mismo_archivo(descriptor: int, ruta: Path) -> bool:
    """
    Si el que soltaba el candado borró fila.lock justo cuando lo abríamos, nuestro bloqueo es sobre un
    archivo que ya no está en la carpeta, y otro proceso podría crear uno nuevo y entrar a la vez.
    Por eso, ya con el bloqueo, se comprueba que la ruta sigue siendo el archivo que tenemos abierto.
    """
    try:
        abierto, en_carpeta = os.fstat(descriptor), os.stat(ruta)
    except OSError:
        return False
    return (abierto.st_dev, abierto.st_ino) == (en_carpeta.st_dev, en_carpeta.st_ino)


def _cerrar(descriptor: int):
    try:
        os.close(descriptor)
    except OSError:
        pass


def tomar_candado(esperar: Callable[[float], None] = time.sleep, al_esperar: Callable[[], None] = None) -> Path:
    """Espera su turno y toma el candado de la fila. Devuelve la ruta para soltarla luego con soltar_candado."""
    ruta = _ruta_candado()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    avisado = False
    reintentos = 0
    while True:
        descriptor = os.open(ruta, os.O_RDWR | os.O_CREAT, 0o644)
        if _bloquear(descriptor):
            # En Windows no hace falta: un archivo abierto no se puede borrar, así que esa carrera no existe
            # (y st_ino no es fiable en todos los sistemas de archivos).
            if plataforma.es_windows() or _es_el_mismo_archivo(descriptor, ruta):
                break
            # Era el archivo que acababan de borrar: se vuelve a intentar enseguida con el nuevo
            try:
                _desbloquear(descriptor)
            except OSError:
                pass
            _cerrar(descriptor)
            reintentos += 1
            if reintentos < 5:
                continue
            # Si la comprobación falla una y otra vez no es una carrera: no girar sin parar, esperar un poco
            esperar(SEGUNDOS_ESPERA_FILA)
            continue
        _cerrar(descriptor)
        if not avisado and al_esperar:
            al_esperar()
            avisado = True
        esperar(SEGUNDOS_ESPERA_FILA)
    # El PID es solo para que una persona sepa quién lo tiene; el bloqueo no depende de él
    try:
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, str(os.getpid()).encode("ascii"))
    except OSError as error:
        logger.debug("No se pudo escribir el PID en el candado: %s", error)
    _abiertos[ruta] = descriptor
    return ruta


def soltar_candado(ruta: Path):
    """Suelta y borra el candado. Soltarlo dos veces, o uno que no es nuestro, no hace nada."""
    descriptor = _abiertos.pop(ruta, None)
    if descriptor is None:
        return
    # En Mac/Linux se borra ANTES de desbloquear: así quien estaba esperando con el archivo viejo
    # abierto ve que ya no es el de la carpeta (_es_el_mismo_archivo) y crea uno nuevo. En Windows no
    # se puede borrar un archivo abierto: se borra después de cerrarlo (si otro ya lo abrió, falla y
    # se queda; no importa, el bloqueo es lo que cuenta).
    if not plataforma.es_windows():
        _borrar_candado(ruta)
    try:
        _desbloquear(descriptor)
    except OSError as error:
        logger.debug("No se pudo desbloquear el candado de la fila: %s", error)
    _cerrar(descriptor)
    if plataforma.es_windows():
        _borrar_candado(ruta)


def _borrar_candado(ruta: Path):
    try:
        ruta.unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        logger.debug("No se pudo borrar el candado de la fila: %s", error)
