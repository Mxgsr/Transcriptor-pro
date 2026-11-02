# Ubicación: tests/test_rutas_windows.py
# Pruebas de src/rutas_windows.py. No hay Windows aquí: se simula sys.platform y SystemRoot, y la
# "carpeta actual" es una carpeta temporal. Lo que se prueba es que nunca se use un programa
# dejado en la carpeta actual (la del audio) y que en Mac/Linux todo quede como estaba.
import os
import shutil
import subprocess
import sys
from pathlib import PureWindowsPath

from src import rutas_windows


def test_powershell_y_explorer_con_ruta_completa_en_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("SystemRoot", raising=False)

    powershell = PureWindowsPath(rutas_windows.powershell())
    explorer = PureWindowsPath(rutas_windows.explorer())

    assert powershell == PureWindowsPath(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    assert explorer == PureWindowsPath(r"C:\Windows\explorer.exe")
    assert powershell.is_absolute() and explorer.is_absolute()


def test_respeta_windows_instalado_en_otra_carpeta(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", r"D:\WINNT")

    assert rutas_windows.powershell() == r"D:\WINNT\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert rutas_windows.explorer() == r"D:\WINNT\explorer.exe"


def test_systemroot_vacia_usa_c_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", "")

    assert rutas_windows.explorer() == r"C:\Windows\explorer.exe"


def test_fuera_de_windows_los_nombres_no_cambian(monkeypatch):
    for plataforma in ("darwin", "linux"):
        monkeypatch.setattr(sys, "platform", plataforma)
        assert rutas_windows.powershell() == "powershell"
        assert rutas_windows.explorer() == "explorer"


def test_buscar_programa_fuera_de_windows_es_shutil_which(monkeypatch, tmp_path):
    # En Mac/Linux no se toca nada, aunque el resultado esté en la carpeta actual
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda c: str(tmp_path / c))

    assert rutas_windows.buscar_programa("ffmpeg") == str(tmp_path / "ffmpeg")


def test_buscar_programa_en_windows_descarta_la_carpeta_actual(monkeypatch, tmp_path):
    actual = tmp_path / "audio"
    actual.mkdir()
    (actual / "ffmpeg.exe").write_text("plantado")
    monkeypatch.chdir(actual)
    monkeypatch.setattr(sys, "platform", "win32")
    # "." , vacía y relativa también apuntan a la carpeta actual: se saltan
    monkeypatch.setenv("PATH", os.pathsep.join([".", "", "audio", str(actual)]))
    monkeypatch.setenv("PATHEXT", ".EXE")
    monkeypatch.setattr(shutil, "which", lambda c: str(actual / "ffmpeg.exe"))

    assert rutas_windows.buscar_programa("ffmpeg") is None


def test_buscar_programa_en_windows_descarta_rutas_relativas(monkeypatch, tmp_path):
    # Antes de Python 3.12, shutil.which en Windows puede devolver ".\ffmpeg.EXE"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(shutil, "which", lambda c: os.path.join(".", "ffmpeg.EXE"))

    assert rutas_windows.buscar_programa("ffmpeg") is None


def test_buscar_programa_en_windows_acepta_el_del_path(monkeypatch, tmp_path):
    bueno = tmp_path / "programas" / "ffmpeg.exe"
    bueno.parent.mkdir()
    bueno.write_text("binario")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda c: str(bueno))

    assert rutas_windows.buscar_programa("ffmpeg") == str(bueno)


def test_buscar_programa_con_extension_no_la_repite(monkeypatch, tmp_path):
    actual, bueno = tmp_path / "audio", tmp_path / "programas"
    for carpeta in (actual, bueno):
        carpeta.mkdir()
        (carpeta / "ffplay.exe").write_text("x")
    monkeypatch.chdir(actual)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("PATH", str(bueno))
    monkeypatch.setattr(shutil, "which", lambda c: str(actual / "ffplay.exe"))

    assert rutas_windows.buscar_programa("ffplay.exe") == str(bueno / "ffplay.exe")


def test_config_pone_la_variable_solo_en_windows(tmp_path):
    # En otro proceso: importar config carga los .env, y así no se toca el entorno de las pruebas
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entorno = {k: v for k, v in os.environ.items() if k != "NoDefaultCurrentDirectoryInExePath"}
    entorno["TRANSCRIPTOR_HOME"] = str(tmp_path)
    # dotenv y pathlib se importan antes de fingir Windows: shutil, por dentro, cargaría módulos
    # que solo existen en un Windows de verdad
    codigo = (
        "import os, sys, pathlib, dotenv; sys.platform = sys.argv[1]; import src.config; "
        "print(os.environ.get('NoDefaultCurrentDirectoryInExePath', 'no'))"
    )

    def valor(plataforma, **extra):
        resultado = subprocess.run(
            [sys.executable, "-c", codigo, plataforma], cwd=tmp_path, env={**entorno, "PYTHONPATH": raiz, **extra},
            capture_output=True, text=True, check=True,
        )
        return resultado.stdout.strip()

    assert valor("win32") == "1"
    assert valor("darwin") == "no"
    assert valor("linux") == "no"
    # Si alguien la configuró a propósito, se respeta
    assert valor("win32", NoDefaultCurrentDirectoryInExePath="0") == "0"
