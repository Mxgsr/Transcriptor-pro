# Ubicación: tests/test_downloader.py
import os
import subprocess
from unittest.mock import MagicMock

import pytest

import src.downloader as downloader


@pytest.fixture
def carpeta_descargas(tmp_path, monkeypatch):
    carpeta = tmp_path / "downloads"
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", str(carpeta))
    return carpeta


def simular_yt_dlp(monkeypatch, carpeta, nombre="Video.mp3"):
    """Simula yt-dlp creando un .mp3 en la carpeta de descargas."""
    def fake_run(cmd, check):
        (carpeta / nombre).write_bytes(b"audio")
        return subprocess.CompletedProcess(cmd, 0)

    run = MagicMock(side_effect=fake_run)
    monkeypatch.setattr(downloader.subprocess, "run", run)
    return run


def test_descargar_rechaza_url_invalida(carpeta_descargas, monkeypatch):
    run = MagicMock()
    monkeypatch.setattr(downloader.subprocess, "run", run)

    with pytest.raises(ValueError):
        downloader.descargar_audio("no-es-url")
    run.assert_not_called()


def test_descargar_llama_yt_dlp_y_devuelve_mp3(carpeta_descargas, monkeypatch):
    url = "https://youtube.com/watch?v=abc"
    run = simular_yt_dlp(monkeypatch, carpeta_descargas)

    resultado = downloader.descargar_audio(url)

    assert resultado == carpeta_descargas / "Video.mp3"
    cmd = run.call_args.args[0]
    assert cmd[0] == "yt-dlp"
    assert cmd[-1] == url
    assert ["--audio-format", "mp3"] == cmd[cmd.index("--audio-format"):cmd.index("--audio-format") + 2]
    assert cmd[cmd.index("-o") + 1] == str(carpeta_descargas / "%(title)s.%(ext)s")
    assert run.call_args.kwargs == {"check": True}


def test_descargar_elige_el_mp3_mas_reciente(carpeta_descargas, monkeypatch):
    carpeta_descargas.mkdir()
    viejo = carpeta_descargas / "Viejo.mp3"
    viejo.write_bytes(b"audio")
    os.utime(viejo, (1_000_000, 1_000_000))
    simular_yt_dlp(monkeypatch, carpeta_descargas, nombre="Nuevo.mp3")

    assert downloader.descargar_audio("https://youtu.be/abc").name == "Nuevo.mp3"


def test_descargar_error_de_yt_dlp(carpeta_descargas, monkeypatch):
    def fake_run(cmd, check):
        raise subprocess.CalledProcessError(returncode=2, cmd=cmd)

    monkeypatch.setattr(downloader.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="código 2"):
        downloader.descargar_audio("https://youtube.com/watch?v=abc")


def test_descargar_sin_mp3_resultante(carpeta_descargas, monkeypatch):
    monkeypatch.setattr(
        downloader.subprocess, "run",
        lambda cmd, check: subprocess.CompletedProcess(cmd, 0),
    )

    with pytest.raises(FileNotFoundError):
        downloader.descargar_audio("https://youtube.com/watch?v=abc")
