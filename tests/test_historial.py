# Ubicación: tests/test_historial.py
import json

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
