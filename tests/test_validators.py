# Ubicación: tests/test_validators.py
import logging

import pytest

import utils.validators as validators
from utils.validators import es_url, es_url_valida


@pytest.fixture(autouse=True)
def dominios_por_defecto(monkeypatch):
    # No dependemos del .env local de quien ejecute los tests.
    monkeypatch.setattr(validators, "DOMINIOS_PERMITIDOS", ["youtube.com", "youtu.be"])


@pytest.mark.parametrize("entrada", [
    "http://youtube.com/watch?v=abc",
    "https://youtu.be/abc",
    "HTTPS://YOUTUBE.COM/watch?v=abc",
    "   https://youtube.com/watch?v=abc   ",
])
def test_es_url_reconoce_urls(entrada):
    assert es_url(entrada) is True


@pytest.mark.parametrize("entrada", [
    "audio.mp3",
    "~/Descargas/audio.mp3",
    "/tmp/https://falso.mp3",
    "ftp://youtube.com/video",
    "",
])
def test_es_url_rechaza_rutas_y_otros_esquemas(entrada):
    assert es_url(entrada) is False


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",
    "http://youtu.be/abc",
    "https://m.YouTube.com/watch?v=abc",
])
def test_es_url_valida_acepta_dominios_permitidos(url, caplog):
    with caplog.at_level(logging.WARNING):
        assert es_url_valida(url) is True
    assert "dominios conocidos" not in caplog.text


@pytest.mark.parametrize("url", [
    "ftp://youtube.com/video",
    "youtube.com/watch?v=abc",
    "https://",
    "no es una url",
    "",
])
def test_es_url_valida_rechaza_formato_incorrecto(url):
    assert es_url_valida(url) is False


def test_es_url_valida_dominio_fuera_de_lista_solo_advierte(caplog):
    # Comportamiento actual: un dominio desconocido se acepta pero se registra una advertencia.
    with caplog.at_level(logging.WARNING):
        assert es_url_valida("https://vimeo.com/123") is True
    assert "dominios conocidos" in caplog.text


def test_es_url_valida_maneja_excepciones():
    # urlparse lanza TypeError con un tipo inesperado; la función debe devolver False.
    assert es_url_valida(12345) is False


@pytest.mark.parametrize("url", [
    "https://youtube.com.evil.example/watch?v=abc",  # el dominio conocido como prefijo de otro
    "https://notyoutu.be/abc",                         # el dominio conocido como final sin punto
    "https://youtube.com@evil.example/watch?v=abc",    # credenciales: el host real es evil.example
    "https://evil.example/youtube.com",                # el dominio solo en la ruta
])
def test_es_url_valida_avisa_con_dominios_parecidos(url, caplog):
    # Siguen aceptándose (solo se avisa, decisión del dueño), pero el aviso tiene que salir.
    with caplog.at_level(logging.WARNING):
        assert es_url_valida(url) is True
    assert "dominios conocidos" in caplog.text


@pytest.mark.parametrize("url", [
    "https://youtube.com:443/watch?v=abc",
    "https://usuario@www.youtube.com/watch?v=abc",
    "https://youtube.com./watch?v=abc",
])
def test_es_url_valida_ignora_puerto_y_credenciales(url, caplog):
    with caplog.at_level(logging.WARNING):
        assert es_url_valida(url) is True
    assert "dominios conocidos" not in caplog.text


def test_es_url_valida_aviso_sin_emoji(caplog):
    with caplog.at_level(logging.WARNING):
        es_url_valida("https://vimeo.com/123")
    assert all(ord(c) < 0x2000 for c in caplog.text)


@pytest.mark.parametrize("url", ["javascript://youtube.com/x", "https://:80/x", "http:///ruta"])
def test_es_url_valida_rechaza_otros_esquemas_y_sin_host(url):
    assert es_url_valida(url) is False
