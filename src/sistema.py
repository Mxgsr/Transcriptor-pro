# Ubicación: src/sistema.py
# Abrir cosas con el sistema operativo: un archivo con su programa (o mostrar dónde está) y una página web.
# Vive aparte para que el menú y «Leer con el audio» no repitan el mismo código por plataforma.
import os
import shutil
import subprocess
from pathlib import Path

from src import plataforma


def abrir(archivo: Path, revelar: bool = False):
    """Abre el archivo con su programa (o muestra dónde está, con revelar)."""
    if plataforma.es_mac():
        comando = ["open", "-R", str(archivo)] if revelar else ["open", str(archivo)]
    elif plataforma.es_windows():
        if not revelar:
            # os.startfile no acepta un entorno propio: el programa asociado hereda el de este proceso.
            # Se acepta porque lo abre el Explorador (ShellExecute), no un comando nuestro.
            os.startfile(str(archivo))
            return
        from src import rutas_windows

        # explorer quiere la ruta pegada a /select, entre comillas (por los espacios). El explorer.exe
        # va con su ruta completa: por nombre, Windows usaría uno que esté en la carpeta actual.
        comando = f'"{rutas_windows.explorer()}" /select,"{archivo}"'
    elif shutil.which("xdg-open"):
        comando = ["xdg-open", str(archivo.parent if revelar else archivo)]
    else:
        # Importación diferida: cli importa mucho y aquí solo hace falta para este aviso
        from rich.markup import escape

        from src.cli import consola

        consola.print(f"Está en [cyan]{escape(str(archivo))}[/]")
        return
    # El programa que abre el archivo no necesita el token de Hugging Face: no lo hereda
    from src.entorno import sin_secretos

    subprocess.run(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, env=sin_secretos())


def abrir_pagina(url: str) -> bool:
    """Abre la dirección en el navegador. True si se pudo; nunca lanza errores."""
    try:
        import webbrowser

        return bool(webbrowser.open(url))
    except Exception:
        return False
