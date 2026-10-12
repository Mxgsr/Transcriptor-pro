# Ubicación: src/plataforma.py
# Qué partes del programa funcionan en este computador.
# - Transcribir: en todos (mlx-whisper en Mac con chip Apple, faster-whisper en el resto).
# - Identificar hablantes (pyannote): en todos menos los Mac con Intel (ya no hay PyTorch nuevo para ellos).
# - Corregir con IA (mlx-lm): solo en Mac con chip Apple.
import platform
import sys

SIN_HABLANTES = "Identificar hablantes no está disponible en Macs con procesador Intel."
SIN_CORRECCION = "Corregir con IA por ahora solo funciona en Macs con chip Apple (M1 o posterior)."


def es_mac_con_chip_apple() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def hablantes_disponible() -> bool:
    return sys.platform != "darwin" or es_mac_con_chip_apple()


def correccion_disponible() -> bool:
    return es_mac_con_chip_apple()
