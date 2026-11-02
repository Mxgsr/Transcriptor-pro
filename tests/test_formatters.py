# Ubicación: tests/test_formatters.py
import json

import pytest

from utils import formatters

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
    from utils.formatters import guardar_json, cargar_transcripcion

    parrafos = [{"start": 0, "end": 1, "text": "Hola", "speaker": "Hablante 1"}]
    nuevo = tmp_path / "nuevo.blocks.json"
    guardar_json(parrafos, nuevo, audio=tmp_path / "a.mp3", nombres={"Hablante 1": "Ana"})

    assert cargar_transcripcion(nuevo) == {
        "audio": str(tmp_path / "a.mp3"), "nombres": {"Hablante 1": "Ana"}, "parrafos": parrafos, "huellas": {},
        "titulo": None, "fecha": None, "duracion": None,
    }
    assert cargar_transcripcion(nuevo)["parrafos"] == parrafos

    antiguo = tmp_path / "antiguo.blocks.json"
    antiguo.write_text('[{"start": 0, "end": 1, "text": "Hola", "speaker": "Ana"}]', encoding="utf-8")
    assert cargar_transcripcion(antiguo) == {
        "audio": None, "nombres": {}, "parrafos": [{"start": 0, "end": 1, "text": "Hola", "speaker": "Ana"}],
        "huellas": {}, "titulo": None, "fecha": None, "duracion": None,
    }


def test_json_guarda_y_lee_las_huellas(tmp_path):
    from utils.formatters import guardar_json, cargar_transcripcion

    parrafos = [{"start": 0, "end": 1, "text": "Hola", "speaker": "Hablante 1"}]
    huellas = {"Hablante 1": [0.6, -0.8]}
    ruta = tmp_path / "a.blocks.json"
    guardar_json(parrafos, ruta, nombres={}, huellas=huellas)

    assert json.loads(ruta.read_text(encoding="utf-8"))["huellas"] == huellas
    assert cargar_transcripcion(ruta)["huellas"] == huellas


def test_json_sin_huellas_no_escribe_la_clave(tmp_path):
    from utils.formatters import guardar_json

    ruta = tmp_path / "a.blocks.json"
    guardar_json([], ruta, huellas={})
    assert "huellas" not in json.loads(ruta.read_text(encoding="utf-8"))


def test_json_con_huellas_estropeadas_se_lee_sin_ellas(tmp_path):
    from utils.formatters import cargar_transcripcion

    ruta = tmp_path / "a.blocks.json"
    ruta.write_text('{"audio": null, "nombres": {}, "parrafos": [], "huellas": [1, 2]}', encoding="utf-8")
    assert cargar_transcripcion(ruta)["huellas"] == {}


def test_fecha_en_espanol_no_depende_del_sistema():
    from datetime import date
    from utils.formatters import fecha_en_espanol

    assert fecha_en_espanol(date(2026, 10, 30)) == "30 de octubre de 2026"
    assert fecha_en_espanol(date(2026, 3, 1)) == "1 de marzo de 2026"


def test_formato_duracion():
    from utils.formatters import formato_duracion

    assert [formato_duracion(s) for s in (3, 108, 3900)] == ["3 s", "1 min 48 s", "1 h 05 min"]


def test_nombre_de_archivo_seguro():
    from utils.formatters import nombre_de_archivo_seguro

    assert nombre_de_archivo_seguro('a\\b/c:d*e?f"g<h>i|j\x07k') == "abcdefghijk"
    assert nombre_de_archivo_seguro("  Hola   mundo. . ") == "Hola mundo"
    assert nombre_de_archivo_seguro('???') == "Reunión"
    assert len(nombre_de_archivo_seguro("x" * 500)) <= 120


def test_encabezado_sin_participantes_omite_la_linea():
    from datetime import date
    from utils.formatters import encabezado_de_transcripcion

    assert encabezado_de_transcripcion("Mi reunión", date(2026, 10, 30), 3900, [{"text": "Hola"}]) == (
        "# Mi reunión\nFecha: 30 de octubre de 2026\nDuración: 1 h 05 min\n\n"
    )


def test_leer_parrafos_del_txt_con_y_sin_encabezado(tmp_path):
    from datetime import date
    from utils.formatters import encabezado_de_transcripcion, guardar_txt_con_timestamps, leer_parrafos_del_txt

    txt = tmp_path / "r.blocks.txt"
    encabezado = encabezado_de_transcripcion("Plan", date(2026, 11, 1), 65, [{"speaker": "Ana"}])
    guardar_txt_con_timestamps([{"start": 0, "text": "hola", "speaker": "Ana"}, {"start": 3725, "text": "chao"}],
                               txt, encabezado)
    cabecera, parrafos = leer_parrafos_del_txt(txt)
    assert cabecera == {"titulo": "Plan", "fecha": "1 de noviembre de 2026", "duracion": "1 min 05 s",
                        "participantes": "Ana"}
    assert parrafos == [{"start": 0.0, "text": "Ana: hola"}, {"start": 3725.0, "text": "chao"}]

    guardar_txt_con_timestamps([{"start": 5, "text": "hola"}], txt)
    assert leer_parrafos_del_txt(txt) == ({}, [{"start": 5.0, "text": "hola"}])


def test_leer_parrafos_del_txt_con_bom(tmp_path):
    # Un .txt vuelto a guardar con el Bloc de notas puede empezar con BOM: no debe perderse la primera línea
    from utils.formatters import leer_parrafos_del_txt

    txt = tmp_path / "r.blocks.txt"
    txt.write_bytes("[00:00:05] hola\n\n[00:00:09] chao".encode("utf-8-sig"))
    assert leer_parrafos_del_txt(txt) == ({}, [{"start": 5.0, "text": "hola"}, {"start": 9.0, "text": "chao"}])
    txt.write_bytes("# Plan\n\n[00:00:05] hola".encode("utf-8-sig"))
    assert leer_parrafos_del_txt(txt) == ({"titulo": "Plan"}, [{"start": 5.0, "text": "hola"}])


# --- escritura atómica y BOM ---

def test_salidas_byte_a_byte_iguales_a_las_de_antes(tmp_path):
    parrafos = [{"start": 0, "text": "Hola ñandú", "speaker": "Ana"}, {"start": 65, "text": "Qué tal"}]
    txt, js = tmp_path / "r.blocks.txt", tmp_path / "r.blocks.json"
    formatters.guardar_txt_con_timestamps(parrafos, txt, encabezado="# T\n\n")
    formatters.guardar_json(parrafos, js, audio=tmp_path / "r.mp3", nombres={"Hablante 1": "Ana"})
    assert txt.read_bytes() == "# T\n\n[00:00:00] Ana: Hola ñandú\n\n[00:01:05] Qué tal".encode("utf-8")
    esperado = json.dumps({"audio": str(tmp_path / "r.mp3"), "nombres": {"Hablante 1": "Ana"},
                           "parrafos": parrafos}, ensure_ascii=False, indent=2)
    assert js.read_bytes() == esperado.encode("utf-8")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r.blocks.json", "r.blocks.txt"]


def test_cargar_transcripcion_con_bom(tmp_path):
    ruta = tmp_path / "b.blocks.json"
    ruta.write_bytes(b"\xef\xbb\xbf" + json.dumps({"parrafos": [{"start": 0, "text": "a"}]}).encode("utf-8"))
    assert formatters.cargar_transcripcion(ruta)["parrafos"] == [{"start": 0, "text": "a"}]


def test_json_editado_a_mano_e_invalido_da_error_y_no_se_aparta(tmp_path):
    ruta = tmp_path / "m.blocks.json"
    ruta.write_text("{ roto", encoding="utf-8")
    with pytest.raises(ValueError):
        formatters.cargar_transcripcion(ruta)
    assert ruta.exists() and not (tmp_path / "m.blocks.json.corrupto").exists()


@pytest.mark.parametrize("segundos, texto", [(0, "0:00"), (9, "0:09"), (2530.9, "42:10"), (3725, "1:02:05")])
def test_formato_reloj(segundos, texto):
    from utils.formatters import formato_reloj

    assert formato_reloj(segundos) == texto
