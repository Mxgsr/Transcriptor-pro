# Ubicación: src/fragmentos.py
# Fragmentos de audio de cada hablante, para escucharlos antes de ponerles nombre.
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

EXTENSIONES_AUDIO = (".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".mp4", ".mov", ".mkv", ".webm")

# Duración de cada fragmento que se reproduce
SEGUNDOS_POR_FRAGMENTO = 10


def buscar_audio(json_path: Path, audio_guardado: Optional[str]) -> Optional[Path]:
    """
    Devuelve el audio de una transcripción: el guardado en el .json si sigue existiendo,
    o si no, un archivo de audio con el mismo nombre junto al .json (charla.blocks.json -> charla.mp3).
    """
    if audio_guardado and Path(audio_guardado).exists():
        return Path(audio_guardado)
    base = json_path.name.removesuffix(".blocks.json")
    for extension in EXTENSIONES_AUDIO:
        candidato = json_path.with_name(base + extension)
        if candidato.exists():
            return candidato
    return None


def elegir_fragmentos(parrafos: list, hablante: str, maximo: int = 3) -> list:
    """Los párrafos más largos de un hablante: son los que mejor dejan reconocer su voz."""
    propios = [p for p in parrafos if p.get("speaker") == hablante and p.get("text", "").strip()]
    propios.sort(key=lambda p: p["end"] - p["start"], reverse=True)
    return propios[:maximo]


def extraer_fragmento(audio: Path, inicio: float, duracion: float, destino: Path) -> Path:
    """Recorta el audio con ffmpeg (desde inicio, durante duracion segundos) y lo guarda en destino."""
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
        "-ss", f"{max(0.0, inicio):.2f}", "-t", f"{max(0.5, duracion):.2f}",
        "-i", str(audio), "-vn", str(destino),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return destino


def comando_reproductor() -> Optional[list]:
    """afplay viene con macOS; ffplay (de ffmpeg) sirve en otros sistemas."""
    if shutil.which("afplay"):
        return ["afplay"]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
    return None


class Reproductor:
    """Reproduce un archivo en segundo plano, para poder escribir mientras suena."""

    def __init__(self, comando: list):
        self.comando = comando
        self.proceso = None

    def reproducir(self, archivo: Path):
        self.detener()
        self.proceso = subprocess.Popen(
            [*self.comando, str(archivo)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def detener(self):
        if self.proceso is not None and self.proceso.poll() is None:
            self.proceso.terminate()
        self.proceso = None
