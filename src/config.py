# Ubicación: src/config.py
# Configuración general: lee los .env, apaga la telemetría y deja las constantes que usa el resto.
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 1. Cargamos la caja fuerte (.env)
# Primero el .env de la raíz del proyecto (como siempre), y solo si existe. Va con ruta explícita a
# propósito: load_dotenv() sin ruta busca hacia arriba desde esta carpeta y, instalado con uv tool,
# acabaría leyendo un ~/.env cualquiera (que podría traer HF_ENDPOINT, HTTPS_PROXY...). En una
# instalación con uv esta ruta no existe y no pasa nada.
# Después el de ~/.transcriptor/, que es donde lo deja el instalador.
# Lo que ya esté definido (en el entorno real o en el .env anterior) no se pisa.
_ENV_PROYECTO = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PROYECTO.is_file():
    load_dotenv(_ENV_PROYECTO)
load_dotenv(Path(os.getenv("TRANSCRIPTOR_HOME", "~/.transcriptor")).expanduser() / ".env")

# Privacidad: pyannote (identificar hablantes) envía por defecto a sus servidores cuánto dura cada
# audio y cuántos hablantes se pidieron, y Hugging Face también junta estadísticas de uso.
# Las apagamos. Quien quiera compartirlas puede poner PYANNOTE_METRICS_ENABLED=true en su .env.
os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "false")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# Seguridad en Windows: al lanzar un programa por su nombre ("ffmpeg"), Windows lo busca primero en
# la carpeta actual, que puede ser la del audio; un ffmpeg.exe dejado ahí (p. ej. dentro de un zip
# descargado) se ejecutaría. Nuestro código ya usa rutas completas (src/rutas_windows.py), pero
# yt-dlp y Whisper llaman a "ffmpeg" por nombre. Esta variable le pide a cmd (y a shutil.which desde Python 3.12) que no mire la carpeta actual; la heredan
# también los procesos que lanzamos. No está documentado que CreateProcess la respete: es una ayuda extra, y la
# protección real son las rutas completas (yt-dlp recibe ffmpeg_location).
# setdefault: si alguien la configuró a propósito, se respeta. No se ha probado en un Windows real.
if sys.platform == "win32":
    os.environ.setdefault("NoDefaultCurrentDirectoryInExePath", "1")

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


# 5. Dominios conocidos
# Leemos el string del .env y lo cortamos por las comas para crear una lista de Python.
# Si por algún motivo no existe en el .env, le damos una lista básica de emergencia.
# No bloquea nada: una URL de otro dominio solo genera un aviso (utils/validators.py).
dominios = os.getenv("DOMINIOS_PERMITIDOS", "youtube.com,youtu.be")
DOMINIOS_PERMITIDOS = [dominio.strip().lower() for dominio in dominios.split(",")]

# 6. Diarización (identificar hablantes)
# El token de Hugging Face es un secreto: vive solo en el .env.
HF_TOKEN = os.getenv("HF_TOKEN")
DIARIZATION_MODEL = os.getenv("DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1")
# Dónde corre la diarización: auto (GPU del Mac si está disponible), mps, cuda o cpu
DIARIZATION_DEVICE = os.getenv("DIARIZATION_DEVICE", "auto")

