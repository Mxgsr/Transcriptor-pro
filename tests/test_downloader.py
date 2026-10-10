# Ubicación: tests/test_downloader.py
import sys
import types
from unittest.mock import MagicMock

import pytest

import src.downloader as downloader


class DownloadError(Exception):
    pass


@pytest.fixture
def carpeta_descargas(tmp_path, monkeypatch):
    carpeta = tmp_path / "downloads"
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", str(carpeta))
    return carpeta


def simular_yt_dlp(monkeypatch, carpeta, nombre="Video.mp3", progreso=(), error=None):
    """
    Simula yt_dlp.YoutubeDL: anuncia el progreso indicado, crea el .mp3
    y devuelve su ruta como lo hace yt-dlp en requested_downloads.
    Retorna el mock de YoutubeDL para revisar las opciones recibidas.
    """
    def fake_youtube_dl(opciones):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl

        def extract_info(url, download):
            if error:
                raise DownloadError(error)
            for estado in progreso:
                for hook in opciones["progress_hooks"]:
                    hook(estado)
            ruta = carpeta / nombre
            ruta.write_bytes(b"audio")
            return {"title": "Video", "requested_downloads": [{"filepath": str(ruta)}]}

        ydl.extract_info.side_effect = extract_info
        return ydl

    yt_dlp = types.ModuleType("yt_dlp")
    yt_dlp.YoutubeDL = MagicMock(side_effect=fake_youtube_dl)
    yt_dlp.utils = types.SimpleNamespace(DownloadError=DownloadError)
    monkeypatch.setitem(sys.modules, "yt_dlp", yt_dlp)
    return yt_dlp.YoutubeDL


def test_descargar_rechaza_url_invalida(carpeta_descargas, monkeypatch):
    youtube_dl = simular_yt_dlp(monkeypatch, carpeta_descargas)

    with pytest.raises(ValueError):
        downloader.descargar_audio("no-es-url")
    youtube_dl.assert_not_called()


def test_descargar_usa_yt_dlp_y_devuelve_el_mp3(carpeta_descargas, monkeypatch):
    youtube_dl = simular_yt_dlp(monkeypatch, carpeta_descargas)

    resultado = downloader.descargar_audio("https://youtube.com/watch?v=abc")

    assert resultado == carpeta_descargas / "Video.mp3"
    opciones = youtube_dl.call_args.args[0]
    assert opciones["format"] == "bestaudio/best"
    assert opciones["outtmpl"] == str(carpeta_descargas / "%(title)s.%(ext)s")
    assert opciones["postprocessors"] == [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
    assert opciones["quiet"] is False


def test_descargar_devuelve_el_archivo_de_esta_descarga_no_el_mas_reciente(carpeta_descargas, monkeypatch):
    carpeta_descargas.mkdir()
    (carpeta_descargas / "Otro.mp3").write_bytes(b"audio")
    simular_yt_dlp(monkeypatch, carpeta_descargas, nombre="Nuevo.mp3")

    assert downloader.descargar_audio("https://youtu.be/abc").name == "Nuevo.mp3"


def test_descargar_silencioso(carpeta_descargas, monkeypatch):
    youtube_dl = simular_yt_dlp(monkeypatch, carpeta_descargas)

    downloader.descargar_audio("https://youtu.be/abc", silencioso=True)

    opciones = youtube_dl.call_args.args[0]
    assert opciones["quiet"] and opciones["no_warnings"] and opciones["noprogress"]


def test_descargar_informa_el_progreso_en_bytes(carpeta_descargas, monkeypatch):
    simular_yt_dlp(monkeypatch, carpeta_descargas, progreso=[
        {"status": "downloading", "downloaded_bytes": 100, "total_bytes": 400},
        {"status": "downloading", "downloaded_bytes": 300, "total_bytes_estimate": 410},
        {"status": "finished", "downloaded_bytes": 400, "total_bytes": 400},
    ])
    avance = []

    downloader.descargar_audio("https://youtu.be/abc", progreso=lambda *args: avance.append(args))

    assert avance == [(100, 400, "bytes"), (300, 410, "bytes")]


def test_descargar_error_de_yt_dlp(carpeta_descargas, monkeypatch):
    simular_yt_dlp(monkeypatch, carpeta_descargas, error="Video unavailable")

    with pytest.raises(RuntimeError, match="Video unavailable"):
        downloader.descargar_audio("https://youtube.com/watch?v=abc")


def test_descargar_sin_mp3_resultante(carpeta_descargas, monkeypatch):
    youtube_dl = simular_yt_dlp(monkeypatch, carpeta_descargas)
    ydl = MagicMock()
    ydl.__enter__.return_value = ydl
    ydl.extract_info.return_value = {"requested_downloads": [{"filepath": str(carpeta_descargas / "no.mp3")}]}
    youtube_dl.side_effect = None
    youtube_dl.return_value = ydl

    with pytest.raises(FileNotFoundError):
        downloader.descargar_audio("https://youtube.com/watch?v=abc")


def test_descargar_en_la_carpeta_indicada(carpeta_descargas, monkeypatch, tmp_path):
    otra = tmp_path / "mis descargas"
    youtube_dl = simular_yt_dlp(monkeypatch, otra)

    resultado = downloader.descargar_audio("https://youtube.com/watch?v=abc", carpeta=otra)

    assert resultado == otra / "Video.mp3"
    assert youtube_dl.call_args.args[0]["outtmpl"] == str(otra / "%(title)s.%(ext)s")
    assert not carpeta_descargas.exists()
