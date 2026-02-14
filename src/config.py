# src/config.py
import os
import logging
from dotenv import load_dotenv

# 1. Cargamos la caja fuerte
load_dotenv()

# 2. Configuración de Auditoría (Logging)
# Documentación del porqué: Usamos logging en lugar de print() para tener trazabilidad 
# de la hora exacta, el nivel de gravedad (INFO, WARNING, ERROR) y el mensaje.
# TODO: Configura el logging básico de Python usando logging.basicConfig()
# Pista: Define el nivel en logging.INFO y usa un formato como '%(asctime)s - %(levelname)s - %(message)s'
def setup_logger():
    # Escribe tu código aquí
    pass

setup_logger()
logger = logging.getLogger(__name__)

# 3. Variables Globales
# Usamos os.getenv() para leer el .env. Le pasamos un segundo parámetro como "salvavidas" 
# (valor por defecto) en caso de que alguien borre el archivo .env por error.
# Nota PEP 8: Las constantes a nivel de módulo siempre van en MAYÚSCULAS_CON_GUIONES_BAJOS.
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "medium")

# TODO: Filtro de Entrada / Validación
# ¿Qué pasa si alguien en el .env pone DOWNLOAD_DIR="" (un string vacío)?
# Agrega un bloque if aquí que lance un ValueError si DOWNLOAD_DIR está vacío.