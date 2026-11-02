# Ubicación: tests/test_historial.py
import json
import os
import stat
import sys

import pytest

from src import historial


def _crear(ruta, contenido="[00:00:00] Hola\n"):
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def test_sin_historial_la_lista_esta_vacia():
    assert historial.listar() == []
    assert historial.preferencias() == {}


def test_registrar_y_listar_de_la_mas_reciente_a_la_mas_antigua(tmp_path):
    a = _crear(tmp_path / "a.blocks.txt")
    b = _crear(tmp_path / "b.blocks.txt")
    b_json = _crear(tmp_path / "b.blocks.json", "{}")

    historial.registrar(a, duracion=60)
    historial.registrar(b, b_json, tmp_path / "b.mp3", 90)

    entradas = historial.listar()
    assert [e["txt"].name for e in entradas] == ["b.blocks.txt", "a.blocks.txt"]
    assert entradas[0]["json"] == b_json.resolve()
    assert entradas[0]["audio"] == (tmp_path / "b.mp3").resolve()
    assert entradas[1]["json"] is None
    assert entradas[1]["duracion"] == 60


def test_registrar_otra_vez_la_sube_sin_duplicarla_y_conserva_lo_que_sabia(tmp_path):
    a = _crear(tmp_path / "a.blocks.txt")
    b = _crear(tmp_path / "b.blocks.txt")
    historial.registrar(a, audio_path=tmp_path / "a.mp3", duracion=60)
    historial.registrar(b)

    historial.registrar(a)

    entradas = historial.listar()
    assert [e["txt"].name for e in entradas] == ["a.blocks.txt", "b.blocks.txt"]
    assert entradas[0]["duracion"] == 60
    assert entradas[0]["audio"] == (tmp_path / "a.mp3").resolve()


def test_oculta_las_que_ya_no_existen(tmp_path):
    a = _crear(tmp_path / "a.blocks.txt")
    a_json = _crear(tmp_path / "a.blocks.json", "{}")
    historial.registrar(a, a_json)
    historial.registrar(tmp_path / "borrada.blocks.txt")

    a_json.unlink()

    [entrada] = historial.listar()
    assert entrada["txt"].name == "a.blocks.txt"
    assert entrada["json"] is None


def test_historial_danado_no_impide_seguir(historial_temporal, tmp_path):
    historial_temporal.mkdir()
    (historial_temporal / historial.ARCHIVO_HISTORIAL).write_text("{esto no es json", encoding="utf-8")
    (historial_temporal / historial.ARCHIVO_PREFERENCIAS).write_text("[1, 2]", encoding="utf-8")

    assert historial.listar() == []
    assert historial.preferencias() == {}

    historial.registrar(_crear(tmp_path / "a.blocks.txt"))
    assert len(historial.listar()) == 1


def test_guarda_como_mucho_max_entradas(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "MAX_ENTRADAS", 3)
    for i in range(5):
        historial.registrar(_crear(tmp_path / f"{i}.blocks.txt"))

    assert [e["txt"].name for e in historial.listar()] == ["4.blocks.txt", "3.blocks.txt", "2.blocks.txt"]


def test_preferencias_se_suman(historial_temporal):
    historial.guardar_preferencias(modelo="turbo", hablantes=True)
    historial.guardar_preferencias(modelo="large")

    assert historial.preferencias() == {"modelo": "large", "hablantes": True}
    guardado = json.loads((historial_temporal / historial.ARCHIVO_PREFERENCIAS).read_text(encoding="utf-8"))
    assert guardado == {"modelo": "large", "hablantes": True}


# --- Personas del equipo ----------------------------------------------------

def test_sin_personas_la_lista_esta_vacia():
    assert historial.personas() == []


def test_personas_mas_usadas_primero_y_luego_las_mas_recientes(historial_temporal):
    historial.recordar_personas(["Ana"])
    historial.recordar_personas(["Luis"])
    historial.recordar_personas(["Marta"])
    historial.recordar_personas(["Luis"])
    # Luis: 2 veces. Ana y Marta: 1; Marta es más reciente
    assert historial.personas() == ["Luis", "Marta", "Ana"]

    guardado = json.loads((historial_temporal / historial.ARCHIVO_PERSONAS).read_text(encoding="utf-8"))
    assert guardado["Luis"]["veces"] == 2 and "ultima" in guardado["Luis"]


def test_un_nombre_repetido_en_la_misma_llamada_cuenta_una_vez():
    historial.recordar_personas(["Ana", "Ana", " Ana "])
    historial.recordar_personas(["Luis"])
    historial.recordar_personas(["Luis"])
    assert historial.personas() == ["Luis", "Ana"]


def test_ignora_vacios_y_etiquetas_genericas(historial_temporal):
    historial.recordar_personas(["", "   ", "Hablante 1", "Hablante 12", None, "Ana"])
    assert historial.personas() == ["Ana"]


def test_sin_nombres_validos_no_crea_el_archivo(historial_temporal):
    historial.recordar_personas(["Hablante 2", ""])
    assert not (historial_temporal / historial.ARCHIVO_PERSONAS).exists()


def test_personas_danado_se_trata_como_vacio(historial_temporal):
    historial_temporal.mkdir()
    (historial_temporal / historial.ARCHIVO_PERSONAS).write_text("{no es json", encoding="utf-8")
    assert historial.personas() == []

    historial.recordar_personas(["Ana"])
    assert historial.personas() == ["Ana"]


def test_personas_con_contenido_raro_no_rompe(historial_temporal):
    historial_temporal.mkdir()
    (historial_temporal / historial.ARCHIVO_PERSONAS).write_text(
        json.dumps({"Ana": 3, "Luis": {"veces": "x"}, "Hablante 1": {"veces": 9}}), encoding="utf-8")
    assert historial.personas() == ["Luis"]
    historial.recordar_personas(["Luis"])
    assert historial.personas() == ["Luis"]


def test_preferencias_danadas_se_apartan_y_se_empieza_de_cero():
    ruta = historial.carpeta() / historial.ARCHIVO_PREFERENCIAS
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("{roto", encoding="utf-8")
    assert historial.preferencias() == {}
    historial.guardar_preferencias(modelo="small")
    assert (historial.carpeta() / "preferencias.json.corrupto").read_text(encoding="utf-8") == "{roto"
    assert historial.preferencias() == {"modelo": "small"}


def test_preferencias_con_bom_se_leen():
    ruta = historial.carpeta() / historial.ARCHIVO_PREFERENCIAS
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"\xef\xbb\xbf" + b'{"modelo": "tiny"}')
    assert historial.preferencias() == {"modelo": "tiny"}


def test_guardar_preferencias_desde_varios_hilos_no_pierde_claves():
    import threading

    hilos = [threading.Thread(target=historial.guardar_preferencias, kwargs={f"k{i}": i}) for i in range(20)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert historial.preferencias() == {f"k{i}": i for i in range(20)}


# --- Permisos: la carpeta de datos y lo que guarda son privados ------------------------------------

solo_posix = pytest.mark.skipif(sys.platform == "win32", reason="en Windows no hay permisos POSIX")


@pytest.fixture
def umask_022():
    anterior = os.umask(0o022)
    yield
    os.umask(anterior)


def _modo(ruta):
    return stat.S_IMODE(os.stat(ruta).st_mode)


def _guardar_todo(tmp_path):
    historial.registrar(_crear(tmp_path / "a.blocks.txt"))
    historial.guardar_preferencias(modelo="small")
    historial.recordar_personas(["Ana"])


@solo_posix
def test_historial_preferencias_y_personas_quedan_privados(tmp_path, umask_022):
    _guardar_todo(tmp_path)
    assert _modo(historial.carpeta()) == 0o700
    for nombre in (historial.ARCHIVO_HISTORIAL, historial.ARCHIVO_PREFERENCIAS, historial.ARCHIVO_PERSONAS):
        assert _modo(historial.carpeta() / nombre) == 0o600, nombre
    # El .txt de la reunión, fuera de la carpeta de datos, no se toca
    assert _modo(tmp_path / "a.blocks.txt") == 0o644


@solo_posix
def test_carpeta_de_datos_de_antes_se_aprieta(umask_022):
    historial.carpeta().mkdir(parents=True)
    os.chmod(historial.carpeta(), 0o755)
    historial.guardar_preferencias(modelo="small")
    assert _modo(historial.carpeta()) == 0o700


def test_mismo_contenido_que_antes(tmp_path):
    historial.guardar_preferencias(modelo="small", idioma="es")
    texto = (historial.carpeta() / historial.ARCHIVO_PREFERENCIAS).read_text(encoding="utf-8")
    assert texto == json.dumps({"modelo": "small", "idioma": "es"}, ensure_ascii=False, indent=2)


def test_en_windows_guardar_no_lanza(tmp_path, monkeypatch):
    from utils import archivos
    monkeypatch.setattr(archivos, "_es_windows", lambda: True)
    monkeypatch.delattr(archivos.os, "getuid", raising=False)
    monkeypatch.setattr(archivos.os, "chmod", lambda *a, **k: None)
    _guardar_todo(tmp_path)
    assert historial.preferencias() == {"modelo": "small"}
    assert historial.personas()
    assert historial.listar()
