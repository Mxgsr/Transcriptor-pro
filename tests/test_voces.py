# Ubicación: tests/test_voces.py
# Pruebas del reconocimiento de personas por la voz (huellas guardadas en voces.json).
# conftest.py apunta TRANSCRIPTOR_HOME a una carpeta temporal: cada test empieza sin voces.
import json
import os
import stat
import sys
import math

import pytest

from src import historial, voces


def _archivo():
    return historial.carpeta() / voces.ARCHIVO_VOCES


# Huellas de juguete de 4 valores (las reales tienen 256): las tres primeras son casi perpendiculares
ANA = [1.0, 0.0, 0.0, 0.0]
LUIS = [0.0, 1.0, 0.0, 0.0]
EVA = [0.0, 0.0, 1.0, 0.0]


def _mezcla(a, b, peso_b):
    """Una huella entre a y b; con peso_b chico se parece mucho a a."""
    return [x * (1 - peso_b) + y * peso_b for x, y in zip(a, b)]


# --- similitud ---

def test_similitud_coseno():
    assert voces.similitud(ANA, ANA) == pytest.approx(1.0)
    assert voces.similitud(ANA, LUIS) == pytest.approx(0.0)
    assert voces.similitud([1, 1, 0, 0], ANA) == pytest.approx(1 / math.sqrt(2))
    # No depende del largo del vector, solo de la dirección
    assert voces.similitud([5, 0, 0, 0], ANA) == pytest.approx(1.0)


def test_similitud_de_huellas_que_no_se_pueden_comparar_es_cero():
    assert voces.similitud(ANA, [1.0, 0.0]) == 0.0              # largos distintos (otro modelo)
    assert voces.similitud(ANA, [0.0, 0.0, 0.0, 0.0]) == 0.0
    assert voces.similitud(ANA, [float("nan"), 0, 0, 0]) == 0.0


# --- recordar, conocidas, olvidar ---

def test_recordar_guarda_la_huella_normalizada():
    assert voces.recordar("Ana", [3.0, 4.0, 0.0, 0.0])

    guardado = json.loads(_archivo().read_text(encoding="utf-8"))
    assert guardado["Ana"]["huella"] == [0.6, 0.8, 0.0, 0.0]
    assert guardado["Ana"]["veces"] == 1
    assert isinstance(guardado["Ana"]["actualizada"], float)
    assert voces.conocidas() == ["Ana"]


def test_recordar_otra_vez_promedia_con_la_anterior():
    voces.recordar("Ana", ANA)
    voces.recordar("Ana", LUIS)   # mismo peso: queda justo entre las dos

    guardado = json.loads(_archivo().read_text(encoding="utf-8"))["Ana"]
    assert guardado["veces"] == 2
    assert guardado["huella"] == pytest.approx([1 / math.sqrt(2), 1 / math.sqrt(2), 0, 0], abs=1e-5)

    voces.recordar("Ana", ANA)    # ahora lo anterior pesa 2 y lo nuevo 1
    guardado = json.loads(_archivo().read_text(encoding="utf-8"))["Ana"]
    assert guardado["veces"] == 3
    x, y = 2 / math.sqrt(2) + 1, 2 / math.sqrt(2)
    largo = math.hypot(x, y)
    assert guardado["huella"] == pytest.approx([x / largo, y / largo, 0, 0], abs=1e-5)


def test_las_huellas_anteriores_pesan_como_maximo_peso_maximo(monkeypatch):
    monkeypatch.setattr(voces, "PESO_MAXIMO", 1)
    voces.recordar("Ana", ANA)
    voces.recordar("Ana", ANA)
    voces.recordar("Ana", LUIS)   # con tope 1, lo nuevo pesa lo mismo que todo lo anterior

    guardado = json.loads(_archivo().read_text(encoding="utf-8"))["Ana"]
    assert guardado["veces"] == 3
    assert guardado["huella"][0] == pytest.approx(guardado["huella"][1], abs=1e-5)


def test_recordar_con_huella_de_otro_largo_empieza_de_cero():
    voces.recordar("Ana", ANA)
    voces.recordar("Ana", [0.0, 1.0])

    guardado = json.loads(_archivo().read_text(encoding="utf-8"))["Ana"]
    assert guardado == {**guardado, "huella": [0.0, 1.0], "veces": 1}


@pytest.mark.parametrize("nombre, huella", [
    ("", ANA), ("   ", ANA), ("Ana", None), ("Ana", []), ("Ana", [0, 0, 0, 0]), ("Ana", [float("nan"), 1, 0, 0]),
])
def test_recordar_sin_nombre_o_huella_valida_no_guarda_nada(nombre, huella):
    assert voces.recordar(nombre, huella) is False
    assert not _archivo().exists()


def test_recordar_nombrados_omite_etiquetas_genericas_y_hablantes_sin_huella():
    huellas = {"Hablante 1": ANA, "Hablante 2": LUIS, "Hablante 3": EVA}
    nombres = {"Hablante 1": " Ana ", "Hablante 2": "Hablante 2", "Hablante 4": "Luis", "Hablante 3": ""}

    assert voces.recordar_nombrados(nombres, huellas) == ["Ana"]
    assert voces.conocidas() == ["Ana"]


def test_conocidas_en_orden_alfabetico():
    for nombre, huella in [("luis", LUIS), ("Ana", ANA), ("Eva", EVA)]:
        voces.recordar(nombre, huella)
    assert voces.conocidas() == ["Ana", "Eva", "luis"]


def test_olvidar_una_y_todas():
    voces.recordar("Ana", ANA)
    voces.recordar("Luis", LUIS)

    assert voces.olvidar("Ana") is True
    assert voces.olvidar("Ana") is False
    assert voces.conocidas() == ["Luis"]

    voces.olvidar_todas()
    assert voces.conocidas() == []
    assert voces.parecidos({"Hablante 1": LUIS}) == {}


# --- parecidos ---

def test_parecidos_propone_a_la_persona_mas_parecida_sobre_el_umbral():
    voces.recordar("Ana", ANA)
    voces.recordar("Luis", LUIS)

    propuestas = voces.parecidos({
        "Hablante 1": _mezcla(LUIS, ANA, 0.1),   # casi Luis
        "Hablante 2": _mezcla(ANA, LUIS, 0.2),   # casi Ana
        "Hablante 3": EVA,                      # nadie conocido
    })

    assert set(propuestas) == {"Hablante 1", "Hablante 2"}
    assert propuestas["Hablante 1"][0] == "Luis"
    assert propuestas["Hablante 2"][0] == "Ana"
    assert propuestas["Hablante 1"][1] == pytest.approx(voces.similitud(_mezcla(LUIS, ANA, 0.1), LUIS), abs=1e-3)


def test_parecidos_respeta_el_umbral():
    voces.recordar("Ana", ANA)
    huella = [1.0, 1.0, 0.0, 0.0]   # similitud 0,707 con Ana

    assert voces.parecidos({"Hablante 1": huella}, umbral=0.7)["Hablante 1"][0] == "Ana"
    assert voces.parecidos({"Hablante 1": huella}, umbral=0.75) == {}


def test_parecidos_no_repite_persona_y_gana_el_mas_parecido():
    voces.recordar("Ana", ANA)
    voces.recordar("Luis", LUIS)

    propuestas = voces.parecidos({
        "Hablante 1": _mezcla(ANA, LUIS, 0.3),    # se parece a Ana
        "Hablante 2": _mezcla(ANA, LUIS, 0.05),   # se parece más a Ana
    }, umbral=0.1)

    assert propuestas["Hablante 2"][0] == "Ana"
    # Ana ya está tomada: Hablante 1 queda con su siguiente opción, que también supera el umbral
    assert propuestas["Hablante 1"][0] == "Luis"

    # Con el umbral normal, Luis no alcanza y Hablante 1 queda sin propuesta
    assert voces.parecidos({
        "Hablante 1": _mezcla(ANA, LUIS, 0.3),
        "Hablante 2": _mezcla(ANA, LUIS, 0.05),
    }) == {"Hablante 2": ("Ana", pytest.approx(voces.similitud(_mezcla(ANA, LUIS, 0.05), ANA), abs=1e-3))}


def test_parecidos_sin_voces_o_sin_huellas_no_propone_nada():
    assert voces.parecidos({"Hablante 1": ANA}) == {}
    voces.recordar("Ana", ANA)
    assert voces.parecidos({}) == {}
    assert voces.parecidos(None) == {}


def test_umbral_razonable():
    assert 0 < voces.UMBRAL < 1


# --- archivo dañado ---

@pytest.mark.parametrize("contenido", ["{esto no es json", "[1, 2, 3]", '"texto"', ""])
def test_archivo_danado_es_como_no_tener_voces(contenido):
    historial.carpeta().mkdir(parents=True, exist_ok=True)
    _archivo().write_text(contenido, encoding="utf-8")

    assert voces.conocidas() == []
    assert voces.parecidos({"Hablante 1": ANA}) == {}
    assert voces.olvidar("Ana") is False
    # Y se puede volver a guardar encima
    assert voces.recordar("Ana", ANA)
    assert voces.conocidas() == ["Ana"]


def test_entradas_estropeadas_se_ignoran_y_las_buenas_sirven():
    historial.carpeta().mkdir(parents=True, exist_ok=True)
    _archivo().write_text(json.dumps({
        "Ana": {"huella": ANA, "veces": 2},
        "Luis": {"huella": "no es una lista"},
        "Eva": [1, 2, 3],
        "Rosa": {"huella": [0, 0, 0, 0]},
        "Pía": {"huella": LUIS, "veces": "muchas"},
    }), encoding="utf-8")

    assert voces.conocidas() == ["Ana", "Pía"]
    assert voces.parecidos({"Hablante 1": ANA}) == {"Hablante 1": ("Ana", 1.0)}
    voces.recordar("Pía", LUIS)   # "veces" inválido cuenta como 1
    assert json.loads(_archivo().read_text(encoding="utf-8"))["Pía"]["veces"] == 2


def test_si_no_se_puede_escribir_no_falla(monkeypatch, tmp_path):
    # La carpeta del programa es un archivo: no se puede crear voces.json dentro
    bloqueo = tmp_path / "bloqueo"
    bloqueo.write_text("", encoding="utf-8")
    monkeypatch.setenv("TRANSCRIPTOR_HOME", str(bloqueo))

    voces.recordar("Ana", ANA)
    voces.olvidar_todas()
    assert voces.conocidas() == []


def test_volver_a_guardar_la_misma_transcripcion_no_suma_dos_veces():
    voces.recordar_nombrados({"Hablante 1": "Ana"}, {"Hablante 1": [1.0, 0.0, 0.0]}, fuente="/r/a.blocks.json")
    voces.recordar_nombrados({"Hablante 1": "Ana"}, {"Hablante 1": [1.0, 0.0, 0.0]}, fuente="/r/a.blocks.json")

    assert voces._cargar()["Ana"]["veces"] == 1


def test_corregir_nombres_cruzados_deja_cada_voz_limpia():
    huellas = {"Hablante 1": [1.0, 0.0, 0.0], "Hablante 2": [0.0, 1.0, 0.0]}
    # Antes de esta reunión ya se conocía a Ana por otra
    voces.recordar("Ana", [1.0, 0.0, 0.0], origen="/r/vieja.blocks.json#Hablante 1")
    voces.recordar_nombrados({"Hablante 1": "Luis", "Hablante 2": "Ana"}, huellas, fuente="/r/a.blocks.json")

    voces.recordar_nombrados({"Hablante 1": "Ana", "Hablante 2": "Luis"}, huellas, fuente="/r/a.blocks.json")

    guardadas = voces._cargar()
    assert guardadas["Luis"]["huella"] == [0.0, 1.0, 0.0] and guardadas["Luis"]["veces"] == 1
    # Ana ya tenía historia: restar es aproximado, pero su voz vuelve a ser claramente la suya
    assert guardadas["Ana"]["veces"] == 2
    assert voces.similitud(guardadas["Ana"]["huella"], [1.0, 0.0, 0.0]) > 0.95
    propuestas = voces.parecidos({"Hablante 1": [1.0, 0.0, 0.0], "Hablante 2": [0.0, 1.0, 0.0]})
    assert propuestas["Hablante 1"][0] == "Ana" and propuestas["Hablante 2"] == ("Luis", 1.0)


def test_voces_json_danado_se_aparta_y_no_se_pierde():
    _archivo().parent.mkdir(parents=True, exist_ok=True)
    _archivo().write_text('{"Ana": {"huella": [1, 0', encoding="utf-8")

    assert voces.conocidas() == []
    voces.recordar("Luis", LUIS)

    assert voces.conocidas() == ["Luis"]
    assert (historial.carpeta() / "voces.json.corrupto").read_text(encoding="utf-8") == '{"Ana": {"huella": [1, 0'


def test_voces_json_que_no_es_un_objeto_no_rompe():
    _archivo().parent.mkdir(parents=True, exist_ok=True)
    _archivo().write_text("[1, 2]", encoding="utf-8")
    assert voces.conocidas() == []
    assert voces.olvidar("Ana") is False


# --- Permisos: las huellas son datos biométricos y solo las puede leer quien usa el programa ---

@pytest.mark.skipif(sys.platform == "win32", reason="en Windows no hay permisos POSIX")
def test_voces_json_queda_0600_aunque_el_umask_sea_022():
    anterior = os.umask(0o022)
    try:
        voces.recordar("Ana", ANA)
    finally:
        os.umask(anterior)
    assert stat.S_IMODE(os.stat(_archivo()).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(historial.carpeta()).st_mode) == 0o700


def test_voces_en_windows_no_lanza(monkeypatch):
    from utils import archivos
    monkeypatch.setattr(archivos, "_es_windows", lambda: True)
    monkeypatch.delattr(archivos.os, "getuid", raising=False)
    monkeypatch.setattr(archivos.os, "chmod", lambda *a, **k: None)
    assert voces.recordar("Ana", ANA)
    assert voces.conocidas() == ["Ana"]
