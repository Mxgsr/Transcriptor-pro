# Ubicación: src/ajustes.py
# La configuración del programa (menú "Configuración"): los valores por defecto que puedes
# cambiar sin tocar el .env. Se guardan con las preferencias del menú, en ~/.transcriptor/,
# así que elegir un modelo al transcribir también lo deja como el de por defecto.
# Mientras no cambies algo aquí, vale lo del .env (o el valor de fábrica).
import os
import sys
from pathlib import Path
from typing import Optional

from src import config, historial

# Modos para las preguntas de hablantes y corrección al transcribir desde el menú
PREGUNTAR, SIEMPRE, NUNCA = "preguntar", "siempre", "nunca"
MODOS = (PREGUNTAR, SIEMPRE, NUNCA)


def _de_fabrica() -> dict:
    return {
        "idioma": "es",
        "modelo": config.DEFAULT_MODEL,
        "modelo_corrector": config.CORRECTOR_MODEL,
        "carpeta_descargas": config.DOWNLOAD_DIR,
        "carpeta_salida": None,  # junto al audio
        "modo_hablantes": PREGUNTAR,
        "modo_correccion": PREGUNTAR,
        # Nombres y siglas que la corrección debe escribir bien ("COSAM, OSL, señorita Catalina")
        "vocabulario": "",
        # Sin internet: los modelos se cargan solo de lo ya descargado (ver aplicar_sin_internet)
        "sin_internet": False,
    }


def valor(clave: str):
    """El valor elegido en Configuración, o el de fábrica si nunca se cambió."""
    elegido = historial.preferencias().get(clave)
    if elegido in (None, ""):
        return _de_fabrica()[clave]
    if clave.startswith("modo_") and elegido not in MODOS:
        return PREGUNTAR
    return elegido


def carpeta(clave: str) -> Optional[Path]:
    """Una carpeta de la configuración como Path (None si no hay)."""
    ruta = valor(clave)
    return Path(ruta).expanduser() if ruta else None


def guardar(**cambios):
    historial.guardar_preferencias(**cambios)


def aplicar_sin_internet(activado: Optional[bool] = None):
    """
    Con "Sin internet", los modelos se cargan solo de lo ya descargado: no se le pregunta a
    Hugging Face si hay versiones nuevas. Un modelo que todavía no se descargó da error.
    Sin argumento (al arrancar) solo lo enciende si está elegido en Configuración, para no apagar
    un HF_HUB_OFFLINE=1 puesto en el .env. Al cambiarlo en el menú se aplica en los dos sentidos.
    """
    if activado is None:
        if not valor("sin_internet"):
            return
        activado = True
    os.environ["HF_HUB_OFFLINE"] = "1" if activado else "0"
    # huggingface_hub lee la variable una sola vez, al importarse: si ya se importó, la corregimos ahí
    constantes = sys.modules.get("huggingface_hub.constants")
    if constantes is not None:
        constantes.HF_HUB_OFFLINE = activado


def sin_internet_activo() -> bool:
    return os.getenv("HF_HUB_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")
