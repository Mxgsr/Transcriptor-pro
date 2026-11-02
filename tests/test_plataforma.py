# Ubicación: tests/test_plataforma.py
# Pruebas de src/plataforma.py: es_windows / es_mac / es_linux leen sys.platform en cada llamada.
import pytest

from src import plataforma


@pytest.mark.parametrize("sistema, windows, mac, linux", [
    ("win32", True, False, False),
    ("darwin", False, True, False),
    ("linux", False, False, True),
])
def test_detecta_el_sistema(monkeypatch, sistema, windows, mac, linux):
    monkeypatch.setattr("sys.platform", sistema)
    assert (plataforma.es_windows(), plataforma.es_mac(), plataforma.es_linux()) == (windows, mac, linux)
