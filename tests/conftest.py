# Ubicación: tests/conftest.py
import sys
import types
from unittest.mock import MagicMock

import pytest


# Reemplazamos el módulo "mlx_whisper" antes de que src.transcriber lo importe.
# Así los tests no necesitan MLX (solo existe en Apple Silicon) ni descargar modelos.
def _transcribe_no_mockeado(*args, **kwargs):
    raise RuntimeError("mlx_whisper.transcribe no está mockeado en este test")


mlx_whisper_falso = types.ModuleType("mlx_whisper")
mlx_whisper_falso.transcribe = _transcribe_no_mockeado
sys.modules["mlx_whisper"] = mlx_whisper_falso


@pytest.fixture
def mlx_transcribe(monkeypatch):
    """Simula mlx_whisper.transcribe y devuelve el mock para configurar su resultado."""
    import src.transcriber as transcriber

    transcribe = MagicMock()
    monkeypatch.setattr(transcriber.mlx_whisper, "transcribe", transcribe)
    return transcribe


@pytest.fixture(autouse=True)
def sin_yt_dlp_real(monkeypatch):
    """Evita que cualquier test descargue de verdad con yt-dlp por accidente."""
    yt_dlp_falso = types.ModuleType("yt_dlp")

    def _youtube_dl_no_mockeado(*args, **kwargs):
        raise RuntimeError("yt_dlp.YoutubeDL no está mockeado en este test")

    yt_dlp_falso.YoutubeDL = _youtube_dl_no_mockeado
    yt_dlp_falso.utils = types.SimpleNamespace(DownloadError=type("DownloadError", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "yt_dlp", yt_dlp_falso)


@pytest.fixture(autouse=True)
def historial_temporal(monkeypatch, tmp_path):
    """El historial y las preferencias del menú se guardan en una carpeta temporal, no en ~/.transcriptor."""
    carpeta = tmp_path / "transcriptor-home"
    monkeypatch.setenv("TRANSCRIPTOR_HOME", str(carpeta))
    return carpeta
