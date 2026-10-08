# Ubicación: tests/conftest.py
import sys
import types
from unittest.mock import MagicMock

import pytest


# Reemplazamos el módulo "whisper" antes de que src.transcriber lo importe.
# Así los tests no necesitan instalar torch ni descargar modelos.
def _load_model_no_mockeado(*args, **kwargs):
    raise RuntimeError("whisper.load_model no está mockeado en este test")


whisper_falso = types.ModuleType("whisper")
whisper_falso.load_model = _load_model_no_mockeado
sys.modules["whisper"] = whisper_falso


@pytest.fixture
def modelo_whisper(monkeypatch):
    """Simula whisper.load_model y devuelve el modelo falso para configurar su resultado."""
    import src.transcriber as transcriber

    modelo = MagicMock()
    load_model = MagicMock(return_value=modelo)
    monkeypatch.setattr(transcriber.whisper, "load_model", load_model)
    modelo.load_model = load_model
    return modelo


@pytest.fixture(autouse=True)
def sin_subprocess_real(monkeypatch):
    """Evita que cualquier test ejecute yt-dlp de verdad por accidente."""
    import src.downloader as downloader

    def _run_no_mockeado(*args, **kwargs):
        raise RuntimeError("subprocess.run no está mockeado en este test")

    monkeypatch.setattr(downloader.subprocess, "run", _run_no_mockeado)
