# Ubicación: src/ajustes.py
# La configuración del programa (menú "Configuración"): los valores por defecto que puedes
# cambiar sin tocar el .env. Se guardan con las preferencias del menú, en ~/.transcriptor/,
# así que elegir un modelo al transcribir también lo deja como el de por defecto.
# Mientras no cambies algo aquí, vale lo del .env (o el valor de fábrica).
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
