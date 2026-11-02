# Ubicación: src/aviso.py
# Utilidades del sistema operativo para las transcripciones largas (Mac, Windows y Linux):
# - sin_dormir(): que el computador no se duerma mientras se transcribe.
# - notificar(): aviso del sistema, con sonido, al terminar.
# - copiar_al_portapapeles(): copia un texto conservando tildes, ñ y emojis.
# - confirmar_cancelar(): que un Ctrl+C accidental no tire a la basura una hora de trabajo.
# Solo usa la librería estándar. Los programas que lanza no heredan el token de Hugging Face
# (src/entorno.py). Nada de aquí debe romper una transcripción: los fallos se ignoran.
import base64
import contextlib
import ctypes
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time

from src import plataforma, rutas_windows
from src.entorno import sin_secretos

logger = logging.getLogger(__name__)

# Constantes de Windows para SetThreadExecutionState (evita que el equipo se suspenda).
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

# Identidad de PowerShell: Windows solo muestra avisos de apps "conocidas", y esta siempre existe.
_APP_ID_POWERSHELL = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

# El texto del usuario NUNCA se pega dentro de estos scripts: viaja en variables de entorno
# (AVISO_TITULO, AVISO_MENSAJE, AVISO_ARCHIVO) y el script las lee con $env:. Así no hay inyección.
# CreateTextNode guarda el texto tal cual (el XML lo escapa solo).
_PS_TOAST = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textos = $xml.GetElementsByTagName('text')
$textos.Item(0).AppendChild($xml.CreateTextNode($env:AVISO_TITULO)) | Out-Null
$textos.Item(1).AppendChild($xml.CreateTextNode($env:AVISO_MENSAJE)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_APP_ID_POWERSHELL}').Show($toast)
"""

# Leemos el archivo como UTF-8 explícito: así las tildes no se dañan según la configuración regional.
_PS_PORTAPAPELES = "Get-Content -Raw -Encoding UTF8 -LiteralPath $env:AVISO_ARCHIVO | Set-Clipboard"

# Sin el ejecutable: se pone al lanzar, con su ruta completa (rutas_windows.powershell()), para que
# Windows no use un powershell.exe que alguien haya dejado en la carpeta actual.
_PS_BASE = ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]

# Script de AppleScript fijo; título y mensaje llegan como argumentos (argv), sin escapar nada.
_APPLESCRIPT = [
    "-e", "on run argv",
    "-e", 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"',
    "-e", "end run",
]


def _sin_ventana() -> int:
    """Evita que parpadee una ventana negra de consola en Windows (la constante solo existe allí)."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _powershell(script: str, entorno: dict, timeout: float) -> bool:
    """Ejecuta un script fijo de PowerShell con datos por variables de entorno. True si terminó bien."""
    # -EncodedCommand (UTF-16LE en base64) evita problemas de comillas y de codificación en la consola.
    codificado = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    resultado = subprocess.run(
        [rutas_windows.powershell(), *_PS_BASE, "-EncodedCommand", codificado],
        # Las variables propias (AVISO_*) se suman al entorno, pero sin el token de Hugging Face
        env=sin_secretos({**os.environ, **entorno}),
        capture_output=True,
        timeout=timeout,
        creationflags=_sin_ventana(),
    )
    return resultado.returncode == 0


# ---------------------------------------------------------------------------
# 1. Que el computador no se duerma
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def sin_dormir():
    """Mantiene el computador despierto durante el bloque. Si algo falla, la transcripción sigue igual."""
    proceso = None
    windows_activo = False

    try:
        if plataforma.es_mac():
            # -i: no dormir por inactividad. -w: caffeinate se cierra solo si este programa muere de golpe.
            # start_new_session: Ctrl+C en la terminal llega a todo el grupo de procesos; sin esto,
            # el primer Ctrl+C (el que solo pide confirmación) mataría a caffeinate.
            proceso = subprocess.Popen(
                ["caffeinate", "-i", "-w", str(os.getpid())],
                env=sin_secretos(),  # caffeinate no necesita el token de Hugging Face
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        elif plataforma.es_windows():
            # El estado es por hilo: sirve porque la transcripción corre en el hilo que llama aquí.
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            windows_activo = True
    except Exception as error:
        logger.debug("No se pudo evitar que el equipo se duerma: %s", error)

    try:
        yield
    finally:
        try:
            if proceso is not None:
                proceso.terminate()
                with contextlib.suppress(Exception):
                    proceso.wait(timeout=2)
            if windows_activo:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception as error:
            logger.debug("No se pudo soltar el bloqueo de suspensión: %s", error)


# ---------------------------------------------------------------------------
# 2. Notificación con sonido
# ---------------------------------------------------------------------------
def notificar(titulo: str, mensaje: str) -> None:
    """Muestra un aviso del sistema con sonido. Nunca lanza errores ni espera mucho."""
    try:
        if plataforma.es_mac():
            subprocess.run(
                ["osascript", *_APPLESCRIPT, titulo, mensaje],
                env=sin_secretos(),
                capture_output=True,
                timeout=5,
            )
        elif plataforma.es_windows():
            # Se eligió PowerShell + API de avisos de Windows 10/11 porque no necesita instalar nada.
            # El pitido va aparte y primero: si el aviso no sale (Asistente de concentración, etc.),
            # al menos se oye algo.
            try:
                import winsound

                winsound.MessageBeep()
            except Exception as error:
                logger.debug("No se pudo reproducir el sonido: %s", error)
            _powershell(_PS_TOAST, {"AVISO_TITULO": titulo, "AVISO_MENSAJE": mensaje}, timeout=10)
        else:
            if shutil.which("notify-send"):
                subprocess.run(
                    ["notify-send", titulo, mensaje], env=sin_secretos(), capture_output=True, timeout=5
                )
    except Exception as error:
        logger.debug("No se pudo mostrar la notificación: %s", error)


# ---------------------------------------------------------------------------
# 3. Portapapeles
# ---------------------------------------------------------------------------
def copiar_al_portapapeles(texto: str) -> bool:
    """Copia el texto al portapapeles conservando tildes, ñ y emojis. True si lo logró."""
    if not texto:
        return False  # nada que copiar (y Set-Clipboard de Windows falla con un texto vacío)
    try:
        if plataforma.es_mac():
            # Sin LANG UTF-8, pbcopy daña las tildes cuando se lanza desde algunos entornos.
            entorno = sin_secretos({**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"})
            resultado = subprocess.run(
                ["pbcopy"], input=texto.encode("utf-8"), env=entorno, timeout=10, capture_output=True
            )
            return resultado.returncode == 0

        if plataforma.es_windows():
            # Se eligió PowerShell + archivo temporal UTF-8 en vez de la API Win32 por ctypes:
            # es más corto y evita errores de memoria con punteros de 64 bits.
            descriptor, ruta = tempfile.mkstemp(suffix=".txt", prefix="aviso_")
            try:
                with os.fdopen(descriptor, "wb") as archivo:
                    archivo.write(texto.encode("utf-8"))
                return _powershell(_PS_PORTAPAPELES, {"AVISO_ARCHIVO": ruta}, timeout=15)
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(ruta)

        if shutil.which("wl-copy"):
            comando = ["wl-copy"]
        elif shutil.which("xclip"):
            comando = ["xclip", "-selection", "clipboard"]
        else:
            return False
        resultado = subprocess.run(
            comando, input=texto.encode("utf-8"), env=sin_secretos(), timeout=10, capture_output=True
        )
        return resultado.returncode == 0
    except Exception as error:
        logger.debug("No se pudo copiar al portapapeles: %s", error)
        return False


# ---------------------------------------------------------------------------
# 4. Ctrl+C con confirmación
# ---------------------------------------------------------------------------
MENSAJE_CONFIRMAR = "¿Seguro? Aprieta Ctrl+C otra vez para cancelar."


@contextlib.contextmanager
def confirmar_cancelar(despues_de: float = 60, avisar=None, ventana: float = 5, reloj=time.monotonic):
    """Pide un segundo Ctrl+C para cancelar, pero solo cuando ya hay trabajo que perder.

    - Antes de `despues_de` segundos: Ctrl+C cancela como siempre (KeyboardInterrupt).
    - Después: el primer Ctrl+C solo avisa; otro dentro de `ventana` segundos cancela.
    `reloj` se puede cambiar en los tests. Fuera del hilo principal no hace nada.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    inicio = reloj()
    estado = {"ultimo_aviso": None}

    def manejador(numero_senal, marco):
        ahora = reloj()
        if ahora - inicio < despues_de:
            raise KeyboardInterrupt
        ultimo = estado["ultimo_aviso"]
        if ultimo is not None and ahora - ultimo <= ventana:
            raise KeyboardInterrupt
        estado["ultimo_aviso"] = ahora
        if avisar is not None:
            try:
                avisar(MENSAJE_CONFIRMAR)
            except Exception as error:
                logger.debug("No se pudo mostrar el aviso de cancelación: %s", error)

    try:
        anterior = signal.signal(signal.SIGINT, manejador)
    except (ValueError, OSError) as error:
        logger.debug("No se pudo instalar el manejador de Ctrl+C: %s", error)
        yield
        return

    try:
        yield
    finally:
        with contextlib.suppress(ValueError, OSError):
            signal.signal(signal.SIGINT, anterior)
