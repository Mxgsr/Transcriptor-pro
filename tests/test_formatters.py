# Ubicación: tests/test_formatters.py
import pytest

from utils.formatters import (
    format_timestamp_hhmmss,
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


def test_guardar_lista_vacia_crea_archivo_vacio(tmp_path):
    txt = tmp_path / "vacio.txt"
    guardar_txt_con_timestamps([], txt)
    assert txt.read_text(encoding="utf-8") == ""


def test_guardar_propaga_error_de_escritura(tmp_path):
    carpeta_inexistente = tmp_path / "no_existe" / "audio.txt"
    with pytest.raises(IOError):
        guardar_txt_con_timestamps(PARRAFOS, carpeta_inexistente)


def test_json_guarda_audio_y_nombres_y_lee_el_formato_antiguo(tmp_path):
    from utils.formatters import guardar_json, cargar_transcripcion, cargar_json

    parrafos = [{"start": 0, "end": 1, "text": "Hola", "speaker": "Hablante 1"}]
    nuevo = tmp_path / "nuevo.blocks.json"
    guardar_json(parrafos, nuevo, audio=tmp_path / "a.mp3", nombres={"Hablante 1": "Ana"})

    assert cargar_transcripcion(nuevo) == {
        "audio": str(tmp_path / "a.mp3"), "nombres": {"Hablante 1": "Ana"}, "parrafos": parrafos,
    }
    assert cargar_json(nuevo) == parrafos

    antiguo = tmp_path / "antiguo.blocks.json"
    antiguo.write_text('[{"start": 0, "end": 1, "text": "Hola", "speaker": "Ana"}]', encoding="utf-8")
    assert cargar_transcripcion(antiguo) == {
        "audio": None, "nombres": {}, "parrafos": [{"start": 0, "end": 1, "text": "Hola", "speaker": "Ana"}],
    }
