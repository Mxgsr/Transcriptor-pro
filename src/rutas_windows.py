# Ubicación: src/rutas_windows.py
# Rutas seguras para los programas que Transcriptor lanza en Windows.
# El porqué: Windows, al lanzar un programa por su nombre ("powershell", "explorer", "ffmpeg"),
# lo busca PRIMERO en la carpeta actual y después en System32 y el PATH. Si la carpeta actual es la
# del audio (clic derecho, o una terminal donde se hizo `cd` ahí) y alguien dejó un powershell.exe
# junto al audio (por ejemplo, dentro de un zip descargado), se ejecutaría ese en vez del de Windows.
# Por eso aquí se usan rutas completas del sistema y se descarta lo que esté en la carpeta actual.
# En Mac y Linux eso no pasa (no buscan en la carpeta actual), así que allí todo queda como estaba.
# Solo librería estándar. No se ha probado en un Windows real.
import ntpath
import os
import shutil
import sys
from typing import Optional


def _carpeta_windows() -> str:
    """C:\\Windows, o donde esté instalado Windows (variable SystemRoot)."""
    return os.environ.get("SystemRoot") or "C:\\Windows"


def powershell() -> str:
    """El PowerShell que trae Windows, con su ruta completa. Fuera de Windows, el nombre tal cual."""
    if sys.platform != "win32":
        return "powershell"
    # ntpath y no os.path: es una ruta de Windows aunque las pruebas corran en Linux
    return ntpath.join(_carpeta_windows(), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def explorer() -> str:
    """El Explorador de archivos de Windows, con su ruta completa. Fuera de Windows, el nombre."""
    if sys.platform != "win32":
        return "explorer"
    return ntpath.join(_carpeta_windows(), "explorer.exe")


def _en_la_carpeta_actual(ruta: str) -> bool:
    """True si la ruta es relativa (se resuelve contra la carpeta actual) o está en la carpeta actual."""
    if not os.path.isabs(ruta):
        return True
    try:
        carpeta = os.path.normcase(os.path.abspath(os.getcwd()))
    except OSError:
        return False  # la carpeta actual ya no existe: nada puede venir de ella
    return os.path.normcase(os.path.dirname(os.path.abspath(ruta))) == carpeta


def buscar_programa(nombre: str) -> Optional[str]:
    """
    Como shutil.which, pero en Windows nunca devuelve un programa de la carpeta actual.
    Fuera de Windows es exactamente shutil.which.
    """
    encontrado = shutil.which(nombre)
    if sys.platform != "win32" or encontrado is None or not _en_la_carpeta_actual(encontrado):
        return encontrado
    # El primero que encontró Windows estaba en la carpeta actual: buscamos a mano en cada carpeta
    # del PATH, saltando las relativas y la carpeta actual, por si hay uno legítimo después.
    # A mano y no con shutil.which(path=...): antes de Python 3.12, en Windows ese which vuelve a
    # mirar primero la carpeta actual aunque se le dé otra.
    _, extension = ntpath.splitext(nombre)
    extensiones = [""] if extension else [
        e for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e
    ]
    for carpeta in os.environ.get("PATH", "").split(os.pathsep):
        carpeta = carpeta.strip().strip('"')
        if not carpeta or not os.path.isabs(carpeta):
            continue
        for ext in extensiones:
            candidato = os.path.join(carpeta, nombre + ext)
            if os.path.isfile(candidato) and not _en_la_carpeta_actual(candidato):
                return candidato
    return None
