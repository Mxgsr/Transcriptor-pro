# src/config.py
import os
import logging
from dotenv import load_dotenv

# 1. Cargamos la caja fuerte (.env)
load_dotenv()

# 2. Configuración de Auditoría (Logging)
def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

setup_logger()
logger = logging.getLogger(__name__)

# 3. Variables Globales (PEP 8: Constantes siempre en MAYÚSCULAS)
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "medium")

# 4. Filtro de Entrada (Validación Temprana)
# Documentación del porqué: Es mejor que el programa "explote" rápido y aquí, 
# avisando que falta configuración, a que falle más adelante borrando archivos.
if not DOWNLOAD_DIR:
    raise ValueError("El directorio de descarga no puede estar vacío. Revisa tu archivo .env.")

# Ubicación: src/config.py (al final del archivo)

# 5. Listas de Seguridad
# Leemos el string del .env y lo cortamos por las comas para crear una lista de Python.
# Si por algún motivo no existe en el .env, le damos una lista básica de emergencia.
dominios = os.getenv("DOMINIOS_PERMITIDOS", "youtube.com,youtu.be")
DOMINIOS_PERMITIDOS = [dominio.strip().lower() for dominio in dominios.split(",")]