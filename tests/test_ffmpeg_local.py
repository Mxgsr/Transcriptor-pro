# Ubicación: tests/test_ffmpeg_local.py
import os
import sys
import types
from pathlib import Path

import pytest

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
    monkeypatch.setattr("sys.platform", "darwin")

    assert ffmpeg_local.asegurar_ffmpeg() is True
    assert (historial_temporal / "bin" / "ffmpeg").read_text() == "nuevo"


def test_sin_ffmpeg_ni_imageio_sigue_sin_fallar(monkeypatch):
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: None)
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)

    assert ffmpeg_local.asegurar_ffmpeg() is False


def test_una_copia_cortada_se_rehace(monkeypatch, tmp_path, historial_temporal):
    ejecutable = tmp_path / "ffmpeg-v7"
    ejecutable.write_text("binario completo")
    (historial_temporal / "bin").mkdir(parents=True)
    (historial_temporal / "bin" / "ffmpeg").write_text("bin")  # copia cortada: otro tamaño
    _imageio_falso(monkeypatch, ejecutable)
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: None)
    monkeypatch.setattr("sys.platform", "darwin")

    assert ffmpeg_local.asegurar_ffmpeg() is True
    assert (historial_temporal / "bin" / "ffmpeg").read_text() == "binario completo"


def test_si_la_copia_falla_no_deja_un_ffmpeg_roto(monkeypatch, tmp_path, historial_temporal):
    ejecutable = tmp_path / "ffmpeg-v7"
    ejecutable.write_text("binario")
    _imageio_falso(monkeypatch, ejecutable)
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: None)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(Path, "symlink_to", lambda *a, **k: (_ for _ in ()).throw(OSError("sin permisos")))

    def copia_cortada(origen, destino):
        Path(destino).write_text("bin")
        raise OSError("disco lleno")

    monkeypatch.setattr(ffmpeg_local.shutil, "copy2", copia_cortada)

    assert ffmpeg_local.asegurar_ffmpeg() is False
    assert list((historial_temporal / "bin").iterdir()) == []


# --- ruta_ffmpeg: la ruta completa para lo que lanzamos nosotros ------------------------------

def test_ruta_ffmpeg_prefiere_el_de_la_carpeta_bin(monkeypatch, tmp_path, historial_temporal):
    propio = historial_temporal / "bin" / "ffmpeg"
    propio.parent.mkdir(parents=True)
    propio.write_text("binario")
    monkeypatch.setattr("sys.platform", "darwin")
    _imageio_falso(monkeypatch, tmp_path / "otro")

    assert ffmpeg_local.ruta_ffmpeg() == str(propio)


def test_ruta_ffmpeg_usa_el_de_imageio_si_no_hay_bin(monkeypatch, tmp_path):
    ejecutable = tmp_path / "ffmpeg-v7"
    ejecutable.write_text("binario")
    _imageio_falso(monkeypatch, ejecutable)
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: pytest.fail("no hacía falta buscar en el PATH"))

    assert ffmpeg_local.ruta_ffmpeg() == str(ejecutable.resolve())


def test_ruta_ffmpeg_sin_imageio_usa_el_del_path(monkeypatch):
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)  # no instalado: no debe fallar
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: "/usr/bin/ffmpeg")

    assert ffmpeg_local.ruta_ffmpeg() == "/usr/bin/ffmpeg"


def test_ruta_ffmpeg_en_windows_no_usa_el_de_la_carpeta_actual(monkeypatch, tmp_path):
    # Un ffmpeg.exe dejado junto al audio (la carpeta actual) no se usa; sí el del PATH que va después
    audio = tmp_path / "descargas"
    bueno = tmp_path / "programas"
    for carpeta in (audio, bueno):
        carpeta.mkdir()
        (carpeta / "ffmpeg.exe").write_text("binario")
    monkeypatch.chdir(audio)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(audio), str(bueno)]))
    monkeypatch.setenv("PATHEXT", ".com;.exe")  # en minúsculas: Linux distingue, Windows no
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: str(audio / "ffmpeg.exe"))

    assert ffmpeg_local.ruta_ffmpeg() == str(bueno / "ffmpeg.exe")


def test_ruta_ffmpeg_sin_nada_queda_el_nombre(monkeypatch):
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: None)

    assert ffmpeg_local.ruta_ffmpeg() == "ffmpeg"


def test_en_windows_un_ffmpeg_en_la_carpeta_actual_no_cuenta_como_instalado(monkeypatch, tmp_path, historial_temporal):
    # Si contara, asegurar_ffmpeg no prepararía el bueno y yt-dlp/Whisper usarían el plantado
    audio = tmp_path / "descargas"
    audio.mkdir()
    (audio / "ffmpeg.exe").write_text("plantado")
    ejecutable = tmp_path / "ffmpeg-v7"
    ejecutable.write_text("binario")
    _imageio_falso(monkeypatch, ejecutable)
    monkeypatch.chdir(audio)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("PATH", str(tmp_path / "vacia"))
    monkeypatch.setattr(ffmpeg_local.shutil, "which", lambda c: str(audio / "ffmpeg.exe"))

    assert ffmpeg_local.asegurar_ffmpeg() is True
    assert (historial_temporal / "bin" / "ffmpeg.exe").read_text() == "binario"
    assert os.environ["PATH"].split(os.pathsep)[0] == str(historial_temporal / "bin")


def test_ruta_ffmpeg_no_acepta_un_nombre_suelto_de_imageio(monkeypatch, tmp_path):
    # imageio devuelve «ffmpeg» a secas si usa el del PATH; Path("ffmpeg") apuntaría a la carpeta actual
    monkeypatch.setenv("TRANSCRIPTOR_HOME", str(tmp_path / "casa"))
    (tmp_path / "ffmpeg").write_text("#!/bin/sh\n")
    monkeypatch.chdir(tmp_path)
    falso = type("F", (), {"get_ffmpeg_exe": staticmethod(lambda: "ffmpeg")})
    monkeypatch.setitem(__import__("sys").modules, "imageio_ffmpeg", falso)
    assert ffmpeg_local.ruta_ffmpeg() != str(tmp_path / "ffmpeg")
