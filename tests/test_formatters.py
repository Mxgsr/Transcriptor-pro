# Ubicación: tests/test_formatters.py
import pytest

from utils.formatters import (
    format_timestamp_hhmmss,
    format_timestamp_srt,
    guardar_srt,
    guardar_txt_con_timestamps,
)


@pytest.mark.parametrize("segundos, esperado", [
    (0, "00:00:00"),
    (59.4, "00:00:59"),
    (59.6, "00:01:00"),
    (61, "00:01:01"),
    (3600, "01:00:00"),
    (3725, "01:02:05"),
    (-5, "00:00:00"),
])
def test_format_timestamp_hhmmss(segundos, esperado):
    assert format_timestamp_hhmmss(segundos) == esperado


@pytest.mark.parametrize("segundos, esperado", [
    (0, "00:00:00,000"),
    (1.5, "00:00:01,500"),
    (61.25, "00:01:01,250"),
    (3725.007, "01:02:05,007"),
    (-1, "00:00:00,000"),
])
def test_format_timestamp_srt(segundos, esperado):
    assert format_timestamp_srt(segundos) == esperado


PARRAFOS = [
    {"start": 0.0, "end": 4.2, "text": " Hola a todos. "},
    {"start": 65.5, "end": 70.0, "text": "Segundo párrafo."},
]


def test_guardar_txt_con_timestamps(tmp_path):
    salida = tmp_path / "audio.blocks.txt"
    guardar_txt_con_timestamps(PARRAFOS, salida)

    assert salida.read_text(encoding="utf-8") == (
        "[00:00:00] Hola a todos.\n\n"
        "[00:01:06] Segundo párrafo."
    )


def test_guardar_txt_omite_parrafos_vacios(tmp_path):
    salida = tmp_path / "audio.blocks.txt"
    parrafos = [
        {"start": 0.0, "end": 1.0, "text": "   "},
        {"start": 2.0, "end": 3.0, "text": "Texto."},
    ]
    guardar_txt_con_timestamps(parrafos, salida)

    assert salida.read_text(encoding="utf-8") == "[00:00:02] Texto."


def test_guardar_txt_acepta_ruta_como_string(tmp_path):
    salida = tmp_path / "audio.blocks.txt"
    guardar_txt_con_timestamps(PARRAFOS, str(salida))
    assert salida.exists()


def test_guardar_srt(tmp_path):
    salida = tmp_path / "audio.blocks.srt"
    guardar_srt(PARRAFOS, salida)

    assert salida.read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:04,200\nHola a todos.\n"
        "\n"
        "2\n00:01:05,500 --> 00:01:10,000\nSegundo párrafo.\n"
    )


def test_guardar_srt_omite_parrafos_vacios(tmp_path):
    salida = tmp_path / "audio.blocks.srt"
    parrafos = [
        {"start": 0.0, "end": 1.0, "text": "Uno."},
        {"start": 1.0, "end": 2.0, "text": ""},
        {"start": 2.0, "end": 3.0, "text": "Tres."},
    ]
    guardar_srt(parrafos, salida)

    bloques = salida.read_text(encoding="utf-8").split("\n\n")
    assert len(bloques) == 2
    assert bloques[0].endswith("Uno.")
    assert bloques[1].endswith("Tres.\n")


def test_guardar_lista_vacia_crea_archivo_vacio(tmp_path):
    txt = tmp_path / "vacio.txt"
    srt = tmp_path / "vacio.srt"
    guardar_txt_con_timestamps([], txt)
    guardar_srt([], srt)
    assert txt.read_text(encoding="utf-8") == ""
    assert srt.read_text(encoding="utf-8") == ""


def test_guardar_propaga_error_de_escritura(tmp_path):
    carpeta_inexistente = tmp_path / "no_existe" / "audio.txt"
    with pytest.raises(IOError):
        guardar_txt_con_timestamps(PARRAFOS, carpeta_inexistente)
    with pytest.raises(IOError):
        guardar_srt(PARRAFOS, carpeta_inexistente)
