# Ubicación: tests/test_ajustes.py
import os
import sys
import types
from pathlib import Path

from src import ajustes, config, historial


def test_sin_cambios_vale_lo_de_fabrica():
    assert ajustes.valor("idioma") == "es"
    assert ajustes.valor("modelo") == config.DEFAULT_MODEL
    assert ajustes.valor("modelo_corrector") == config.CORRECTOR_MODEL
    assert ajustes.valor("modo_hablantes") == ajustes.PREGUNTAR
    assert ajustes.carpeta("carpeta_descargas") == Path(config.DOWNLOAD_DIR)
    assert ajustes.carpeta("carpeta_salida") is None


def test_lo_guardado_gana(tmp_path):
    ajustes.guardar(idioma="en", modelo="turbo", carpeta_salida="~/Textos", modo_correccion=ajustes.SIEMPRE)

    assert ajustes.valor("idioma") == "en"
    assert ajustes.valor("modelo") == "turbo"
    assert ajustes.carpeta("carpeta_salida") == Path.home() / "Textos"
    assert ajustes.valor("modo_correccion") == ajustes.SIEMPRE


def test_se_guarda_con_las_preferencias_del_menu():
    historial.guardar_preferencias(modelo="large")  # lo que hace el menú al transcribir
    assert ajustes.valor("modelo") == "large"


def test_vacio_o_modo_desconocido_vuelve_a_lo_de_fabrica():
    ajustes.guardar(carpeta_salida="", modo_hablantes="a veces")
    assert ajustes.carpeta("carpeta_salida") is None
    assert ajustes.valor("modo_hablantes") == ajustes.PREGUNTAR


def test_sin_internet_viene_apagado_y_no_toca_nada_al_arrancar(monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    assert ajustes.valor("sin_internet") is False

    ajustes.aplicar_sin_internet()

    assert "HF_HUB_OFFLINE" not in os.environ
    assert not ajustes.sin_internet_activo()


def test_sin_internet_elegido_se_aplica_al_arrancar(monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    ajustes.guardar(sin_internet=True)

    ajustes.aplicar_sin_internet()

    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert ajustes.sin_internet_activo()


def test_sin_internet_corrige_huggingface_hub_si_ya_se_importo(monkeypatch):
    constantes = types.SimpleNamespace(HF_HUB_OFFLINE=False)
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", constantes)
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")

    ajustes.aplicar_sin_internet(True)
    assert constantes.HF_HUB_OFFLINE is True and os.environ["HF_HUB_OFFLINE"] == "1"

    ajustes.aplicar_sin_internet(False)
    assert constantes.HF_HUB_OFFLINE is False and os.environ["HF_HUB_OFFLINE"] == "0"


def test_telemetria_de_pyannote_y_hugging_face_apagada():
    assert os.environ["PYANNOTE_METRICS_ENABLED"] == "false"
    assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"
