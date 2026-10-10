# Ubicación: tests/test_ajustes.py
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
