# src/config.py
import os
from pathlib import Path

from dotenv import load_dotenv

# 1. Cargamos la caja fuerte (.env)
# Primero el .env del proyecto (como siempre). Después el de ~/.transcriptor/, que es donde lo deja
# el instalador: instalado con uv tool, el programa no vive en la carpeta del proyecto.
# Lo que ya esté definido no se pisa, así que el .env del proyecto manda.
load_dotenv()
load_dotenv(Path(os.getenv("TRANSCRIPTOR_HOME", "~/.transcriptor")).expanduser() / ".env")

# Privacidad: pyannote (identificar hablantes) envía por defecto a sus servidores cuánto dura cada
# audio y cuántos hablantes se pidieron, y Hugging Face también junta estadísticas de uso.
# Las apagamos. Quien quiera compartirlas puede poner PYANNOTE_METRICS_ENABLED=true en su .env.
os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "false")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# 2. Configuración de Auditoría (Logging)
# La configura la CLI (src/cli.py) al arrancar, según se pida o no el detalle (-v).

# 3. Variables Globales (PEP 8: Constantes siempre en MAYÚSCULAS)
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "medium")
# Dónde corre la transcripción con faster-whisper (Windows y Macs con Intel): cpu, o cuda para
# una GPU NVIDIA (necesita CUDA 12 y cuDNN 9 instalados). En Mac con chip Apple no se usa.
TRANSCRIPTION_DEVICE = os.getenv("TRANSCRIPTION_DEVICE", "cpu")

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

# 6. Diarización (identificar hablantes)
# El token de Hugging Face es un secreto: vive solo en el .env.
HF_TOKEN = os.getenv("HF_TOKEN")
DIARIZATION_MODEL = os.getenv("DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1")
# Dónde corre la diarización: auto (GPU del Mac si está disponible), mps, cuda o cpu
DIARIZATION_DEVICE = os.getenv("DIARIZATION_DEVICE", "auto")

# 7. Corrección con IA local (transcriptor corregir)
# Nombre corto (qwen3-4b, qwen3-8b, gemma4-e4b) o un repo de mlx-community en Hugging Face
CORRECTOR_MODEL = os.getenv("CORRECTOR_MODEL", "qwen3-8b")
