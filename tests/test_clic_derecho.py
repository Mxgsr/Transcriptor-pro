# Ubicación: tests/test_clic_derecho.py
# Pruebas del clic derecho: el comando oculto `en-fila` (con la transcripción simulada) y la
# instalación en Mac (Automator) y Windows (Enviar a), simuladas con sys.platform y carpetas temporales.
import os
import plistlib
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from src import ajustes, aviso, clic_derecho, cli, config, historial, plataforma
from src.cli import app


@pytest.fixture
def audios(tmp_path):
    carpeta = tmp_path / "audios"
    carpeta.mkdir()
    lista = []
    for nombre in ("a.m4a", "b.mp3"):
        ruta = carpeta / nombre
        ruta.write_bytes(b"")
        lista.append(ruta)
    return lista


@pytest.fixture
def entorno(monkeypatch):
    """Notificaciones y transcripción simuladas; devuelve (transcribir, notificar)."""
    notificar = MagicMock()
    monkeypatch.setattr(aviso, "notificar", notificar)
    transcribir = MagicMock(side_effect=lambda *a, **k: SimpleNamespace(duracion=65))
    monkeypatch.setattr(cli, "ejecutar_transcripcion", transcribir)
    monkeypatch.setattr(cli, "_hablantes_para_clic_derecho", lambda: False)
    return transcribir, notificar


def lanzar(*archivos):
    return CliRunner().invoke(app, ["en-fila", *map(str, archivos)])


def test_en_fila_esta_oculto():
    salida = CliRunner().invoke(app, ["--help"]).output
    assert "en-fila" not in salida


def test_usa_la_configuracion_y_el_titulo(audios, entorno, tmp_path):
    transcribir, notificar = entorno
    ajustes.guardar(modelo="small", idioma="en", carpeta_salida=str(tmp_path / "salida"))
    resultado = lanzar(audios[0])
    assert resultado.exit_code == 0, resultado.output
    args, kwargs = transcribir.call_args
    assert args[0] == str(audios[0]) and args[1] == "small"
    assert kwargs["idioma"] == "en"
    assert kwargs["salida"] == tmp_path / "salida"
    assert kwargs["sin_preguntas"] is True and kwargs["desde_menu"] is True
    assert kwargs["titulo"] == "a"
    assert isinstance(kwargs["fecha"], date)
    assert kwargs["hablantes"] is False
    notificar.assert_called_once_with("Transcripción lista", "Listo: a, 1 min 05 s")


def test_salta_inexistentes_y_lo_que_no_es_audio(audios, entorno, tmp_path):
    transcribir, notificar = entorno
    texto = tmp_path / "nota.txt"
    texto.write_text("hola")
    resultado = lanzar(tmp_path / "no_existe.mp3", texto, audios[0])
    assert resultado.exit_code == 0
    assert transcribir.call_count == 1


def test_un_nombre_con_corchetes_se_muestra_tal_cual(audios, entorno, tmp_path):
    # Rich leía «[final]» del nombre como una etiqueta de estilo y la borraba del aviso
    transcribir, _ = entorno
    raro = tmp_path / "notas [final].txt"
    raro.write_text("hola")
    resultado = lanzar(raro, audios[0])
    assert resultado.exit_code == 0, resultado.output
    assert transcribir.call_count == 1
    assert "notas [final].txt" in resultado.output


def test_sigue_tras_un_fallo_y_sale_con_1(audios, entorno):
    transcribir, notificar = entorno
    transcribir.side_effect = [typer.Exit(1), SimpleNamespace(duracion=5)]
    resultado = lanzar(*audios)
    assert resultado.exit_code == 1
    assert transcribir.call_count == 2
    assert notificar.call_args_list[0].args == (
        "No pude transcribir", "a.m4a. Abre Transcriptor para ver el detalle.")
    assert notificar.call_args_list[1].args[0] == "Transcripción lista"


def test_hablantes_segun_configuracion(monkeypatch):
    import importlib.util
    monkeypatch.setattr(config, "HF_TOKEN", "hf_x")
    monkeypatch.setattr(plataforma, "hablantes_disponible", lambda: True)
    monkeypatch.setattr(importlib.util, "find_spec", lambda nombre: object())
    assert cli._hablantes_para_clic_derecho() is True
    ajustes.guardar(modo_hablantes=ajustes.NUNCA)
    assert cli._hablantes_para_clic_derecho() is False
    ajustes.guardar(modo_hablantes=ajustes.SIEMPRE)
    monkeypatch.setattr(config, "HF_TOKEN", None)
    assert cli._hablantes_para_clic_derecho() is False


# --- La fila --------------------------------------------------------------------

def test_el_candado_se_borra_siempre(audios, entorno):
    transcribir, _ = entorno
    transcribir.side_effect = RuntimeError("explotó")
    lanzar(audios[0])
    assert not (historial.carpeta() / "fila.lock").exists()


def test_espera_mientras_otro_proceso_vivo_tiene_el_candado(monkeypatch):
    candado = historial.carpeta() / "fila.lock"
    candado.parent.mkdir(parents=True, exist_ok=True)
    candado.write_text("4242")
    monkeypatch.setattr(clic_derecho, "_proceso_vive", lambda pid: True)
    esperas = []

    def esperar(segundos):
        esperas.append(segundos)
        if len(esperas) == 2:
            candado.unlink()  # el otro terminó

    ruta = clic_derecho.tomar_candado(esperar=esperar)
    assert esperas == [5, 5]
    assert ruta.read_text() == str(os.getpid())


def test_toma_un_candado_viejo(monkeypatch):
    candado = historial.carpeta() / "fila.lock"
    candado.parent.mkdir(parents=True, exist_ok=True)
    candado.write_text("4242")
    monkeypatch.setattr(clic_derecho, "_proceso_vive", lambda pid: False)
    esperar = MagicMock()
    ruta = clic_derecho.tomar_candado(esperar=esperar)
    esperar.assert_not_called()
    assert ruta.read_text() == str(os.getpid())


def test_candado_de_mas_de_un_dia_se_toma(monkeypatch):
    candado = historial.carpeta() / "fila.lock"
    candado.parent.mkdir(parents=True, exist_ok=True)
    candado.write_text("4242")
    viejo = candado.stat().st_mtime - 25 * 3600
    os.utime(candado, (viejo, viejo))
    monkeypatch.setattr(clic_derecho, "_proceso_vive", lambda pid: True)
    assert clic_derecho.tomar_candado(esperar=MagicMock()).exists()


# --- Mac ------------------------------------------------------------------------

def test_mac_crea_el_workflow_y_se_quita(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(clic_derecho.subprocess, "run", MagicMock())
    monkeypatch.setattr(clic_derecho, "comando_del_programa", lambda: ["/opt/mi programa/transcriptor"])
    assert clic_derecho.disponible() and not clic_derecho.instalado()
    assert clic_derecho.instalar() is True and clic_derecho.instalado()

    base = tmp_path / "Library/Services/Transcribir con Transcriptor.workflow/Contents"
    info = plistlib.loads((base / "Info.plist").read_bytes())
    servicio = info["NSServices"][0]
    assert servicio["NSMenuItem"] == {"default": "Transcribir con Transcriptor"}
    assert servicio["NSMessage"] == "runWorkflowAsService"
    assert servicio["NSRequiredContext"] == {"NSApplicationIdentifier": "com.apple.finder"}
    assert "public.audio" in servicio["NSSendFileTypes"]

    flujo = plistlib.loads((base / "document.wflow").read_bytes())
    accion = flujo["actions"][0]["action"]
    parametros = accion["ActionParameters"]
    assert accion["BundleIdentifier"] == "com.apple.RunShellScript"
    assert parametros["shell"] == "/bin/zsh" and parametros["inputMethod"] == 1
    assert "'/opt/mi programa/transcriptor' en-fila" in parametros["COMMAND_STRING"]
    assert '"$@"' in parametros["COMMAND_STRING"]
    assert flujo["workflowMetaData"]["workflowTypeIdentifier"] == "com.apple.Automator.servicesMenu"

    assert clic_derecho.quitar() is True
    assert not clic_derecho.instalado()


# --- Windows --------------------------------------------------------------------

def test_windows_crea_el_cmd_en_ascii_con_userprofile(tmp_path, monkeypatch):
    perfil = tmp_path / "José"
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("USERPROFILE", str(perfil))
    monkeypatch.setattr(clic_derecho, "comando_del_programa",
                        lambda: [str(perfil / ".local/bin/transcriptor.exe")])
    assert clic_derecho.instalar() is True and clic_derecho.instalado()

    crudo = (tmp_path / "AppData/Microsoft/Windows/SendTo/Transcriptor.cmd").read_bytes()
    assert not crudo.startswith(b"\xef\xbb\xbf")
    crudo.decode("ascii")  # sin tildes
    lineas = crudo.decode().splitlines()
    assert lineas[0] == "@echo off" and lineas[1].startswith("chcp 65001")
    assert '"%USERPROFILE%\\.local\\bin\\transcriptor.exe" en-fila %*' in lineas
    assert lineas[-1] == "if errorlevel 1 pause"

    assert clic_derecho.quitar() is True
    assert not clic_derecho.instalado()


def test_en_linux_no_hay_clic_derecho(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert not clic_derecho.disponible()
    assert clic_derecho.instalar() is False and clic_derecho.quitar() is False
    assert clic_derecho.instalado() is False
