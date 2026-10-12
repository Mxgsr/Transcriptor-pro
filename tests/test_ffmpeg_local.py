# Ubicación: tests/test_ffmpeg_local.py
import os
import sys
import types

from src import ffmpeg_local


def _imageio_falso(monkeypatch, ejecutable):
    modulo = types.ModuleType("imageio_ffmpeg")
    modulo.get_ffmpeg_exe = lambda: str(ejecutable)
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", modulo)


def test_si_ya_hay_ffmpeg_no_toca_nada(monkeypatch, historial_temporal):
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: "/usr/bin/ffmpeg")
    path_antes = os.environ["PATH"]

    assert ffmpeg_local.asegurar_ffmpeg() is True
    assert os.environ["PATH"] == path_antes
    assert not (historial_temporal / "bin").exists()


def test_sin_ffmpeg_usa_el_de_imageio_y_lo_pone_en_el_path(monkeypatch, tmp_path, historial_temporal):
    ejecutable = tmp_path / "ffmpeg-macos-aarch64-v7.1"
    ejecutable.write_text("binario")
    _imageio_falso(monkeypatch, ejecutable)
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: None)
    monkeypatch.setenv("PATH", "/usr/bin")

    assert ffmpeg_local.asegurar_ffmpeg() is True

    acceso = historial_temporal / "bin" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    assert acceso.read_text() == "binario"
    assert os.environ["PATH"].split(os.pathsep)[0] == str(historial_temporal / "bin")


def test_rehace_el_acceso_si_apunta_a_una_instalacion_anterior(monkeypatch, tmp_path, historial_temporal):
    viejo, nuevo = tmp_path / "ffmpeg-v6", tmp_path / "ffmpeg-v7"
    viejo.write_text("viejo")
    nuevo.write_text("nuevo")
    (historial_temporal / "bin").mkdir(parents=True)
    (historial_temporal / "bin" / "ffmpeg").symlink_to(viejo)
    viejo.unlink()  # la instalación anterior ya no existe
    _imageio_falso(monkeypatch, nuevo)
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: None)
    monkeypatch.setattr(ffmpeg_local.sys, "platform", "darwin")

    assert ffmpeg_local.asegurar_ffmpeg() is True
    assert (historial_temporal / "bin" / "ffmpeg").read_text() == "nuevo"


def test_sin_ffmpeg_ni_imageio_sigue_sin_fallar(monkeypatch):
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: None)
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)

    assert ffmpeg_local.asegurar_ffmpeg() is False
