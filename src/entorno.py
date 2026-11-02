# Ubicación: src/entorno.py
# El entorno que heredan los programas que lanzamos (PowerShell, ffmpeg, uv, osascript...).
# El token de Hugging Face vive en las variables de entorno de este proceso (config.py lo carga desde el
# .env); ninguno de esos programas lo necesita, así que no se lo pasamos.
# Solo librería estándar.
import os

# Variables con secretos que nunca deben heredar los procesos hijos
SECRETOS = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_HUB_TOKEN")


def sin_secretos(base=None) -> dict:
    """Copia del entorno (o de `base`) sin las variables con secretos."""
    entorno = dict(os.environ if base is None else base)
    for nombre in SECRETOS:
        entorno.pop(nombre, None)
    return entorno
