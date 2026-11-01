# Ubicación: tests/test_buscar.py
# Pruebas de la búsqueda en las transcripciones: tildes, mayúsculas, todas las palabras,
# con y sin .json, archivos dañados, límite de resultados, fragmento y etiqueta del menú.
from datetime import date

from src import buscar, historial
from utils import formatters

PARRAFOS = [
    {"start": 0.0, "end": 5.0, "text": "Hola a todos, empezamos.", "speaker": "Hablante 1"},
    {"start": 750.0, "end": 760.0, "text": "Revisemos el Presupuesto de marketing.", "speaker": "Hablante 2"},
    {"start": 800.0, "end": 810.0, "text": "El presupuesto está aprobado.", "speaker": "Hablante 1"},
]


def _con_json(carpeta, nombre="2026-11-01 Reunión", titulo="Reunión", nombres=None):
    txt = carpeta / f"{nombre}.blocks.txt"
    js = carpeta / f"{nombre}.blocks.json"
    enc = formatters.encabezado_de_transcripcion(titulo, date(2026, 11, 1), 900, PARRAFOS)
    formatters.guardar_txt_con_timestamps(PARRAFOS, txt, enc)
    formatters.guardar_json(PARRAFOS, js, nombres=nombres or {}, titulo=titulo, fecha=date(2026, 11, 1))
    return {"txt": txt, "json": js, "audio": None, "duracion": 900, "fecha": 1.0}


def _sin_json(carpeta, nombre="2026-10-30 Charla", titulo="Charla"):
    txt = carpeta / f"{nombre}.blocks.txt"
    sin_hablante = [{"start": p["start"], "text": p["text"]} for p in PARRAFOS]
    enc = formatters.encabezado_de_transcripcion(titulo, None, None, sin_hablante) if titulo else ""
    formatters.guardar_txt_con_timestamps(sin_hablante, txt, enc)
    return {"txt": txt, "json": None, "audio": None, "duracion": None, "fecha": 0.5}


def test_normalizar():
    assert buscar.normalizar("  Presupuésto   NIÑO\n") == "presupuesto nino"


def test_acentos_y_mayusculas(tmp_path):
    entrada = _con_json(tmp_path)
    resultado = buscar.buscar("Presupuésto", [entrada])
    assert [c.inicio for c in resultado] == [750.0, 800.0]


def test_todas_las_palabras(tmp_path):
    entrada = _con_json(tmp_path)
    assert len(buscar.buscar("presupuesto marketing", [entrada])) == 1
    assert buscar.buscar("presupuesto vacaciones", [entrada]) == []


def test_consulta_vacia(tmp_path):
    assert buscar.buscar("   ", [_con_json(tmp_path)]) == []


def test_con_json_aplica_los_nombres(tmp_path):
    entrada = _con_json(tmp_path, nombres={"Hablante 2": "Ana"})
    c = buscar.buscar("marketing", [entrada])[0]
    assert c.hablante == "Ana"
    assert c.titulo == "Reunión"
    assert c.fecha == "2026-11-01"
    assert c.json == entrada["json"]


def test_sin_json_salta_el_encabezado(tmp_path):
    entrada = _sin_json(tmp_path)
    assert buscar.buscar("charla", [entrada]) == []
    c = buscar.buscar("marketing", [entrada])[0]
    assert c.titulo == "Charla"
    assert c.fecha == "2026-10-30"
    assert c.hablante is None
    assert c.inicio == 750.0


def test_sin_json_ni_encabezado_usa_el_nombre(tmp_path):
    entrada = _sin_json(tmp_path, nombre="audio", titulo=None)
    c = buscar.buscar("marketing", [entrada])[0]
    assert c.titulo == "audio"
    assert c.fecha is None


def test_archivo_danado_se_salta(tmp_path):
    malo_json = tmp_path / "malo.blocks.json"
    malo_json.write_text("{no es json", encoding="utf-8")
    malo = {"txt": tmp_path / "malo.blocks.txt", "json": malo_json, "audio": None}
    faltante = {"txt": tmp_path / "no_existe.blocks.txt", "json": None, "audio": None}
    bueno = _con_json(tmp_path)
    resultado = buscar.buscar("presupuesto", [malo, faltante, bueno])
    assert len(resultado) == 2


def test_orden_y_maximo(tmp_path):
    a = _con_json(tmp_path, nombre="a")
    b = _sin_json(tmp_path, nombre="b")
    todas = buscar.buscar("presupuesto", [a, b])
    assert [c.txt.name for c in todas] == ["a.blocks.txt"] * 2 + ["b.blocks.txt"] * 2
    assert len(buscar.buscar("presupuesto", [a, b], maximo=3)) == 3


def test_fragmento_corto_queda_igual():
    assert buscar.fragmento("Hola mundo", "mundo") == "Hola mundo"


def test_fragmento_con_puntos_y_limites_de_palabra():
    texto = " ".join(f"palabra{i}" for i in range(40)) + " Presupuésto " + " ".join(f"final{i}" for i in range(40))
    f = buscar.fragmento(texto, "presupuesto", largo=60)
    assert f.startswith("…") and f.endswith("…")
    assert "Presupuésto" in f
    for parte in f.strip("…").split():
        assert parte.startswith(("palabra", "final", "Presup")) and (parte[-1].isdigit() or parte == "Presupuésto")


def test_fragmento_al_inicio_solo_puntos_detras():
    texto = "presupuesto " + "x" * 5 + " " + " ".join(["relleno"] * 30)
    f = buscar.fragmento(texto, "presupuesto", largo=40)
    assert not f.startswith("…") and f.endswith("…")


def test_fragmento_con_normalizacion_que_cambia_el_largo():
    # «ǆ» (una letra) se descompone en varias al normalizar; no debe desfasar el trozo
    texto = "ǆǆǆǆǆǆǆǆǆǆ " * 5 + "el presupuesto sube " + "relleno " * 20
    f = buscar.fragmento(texto, "presupuesto", largo=50)
    assert "presupuesto" in f


def test_etiqueta_completa():
    c = buscar.Coincidencia(txt=None, json=None, audio=None, titulo="Reunión", fecha="2026-11-01",
                            inicio=750.0, hablante="Ana", fragmento="…el presupuesto de…")
    assert buscar.etiqueta(c) == "2026-11-01 Reunión · 00:12:30 · Ana: …el presupuesto de…"


def test_etiqueta_no_repite_fecha_ni_inventa_hablante():
    c = buscar.Coincidencia(txt=None, json=None, audio=None, titulo="2026-11-01 Reunión", fecha="2026-11-01",
                            inicio=5.0, hablante=None, fragmento="hola")
    assert buscar.etiqueta(c) == "2026-11-01 Reunión · 00:00:05 · hola"
    sin_fecha = buscar.Coincidencia(txt=None, json=None, audio=None, titulo="Charla", fecha=None,
                                    inicio=5.0, hablante=None, fragmento="hola")
    assert buscar.etiqueta(sin_fecha) == "Charla · 00:00:05 · hola"


def test_etiqueta_se_recorta():
    c = buscar.Coincidencia(txt=None, json=None, audio=None, titulo="Reunión", fecha="2026-11-01",
                            inicio=5.0, hablante="Ana", fragmento="palabra " * 40)
    linea = buscar.etiqueta(c)
    assert len(linea) <= buscar.MAXIMO_ETIQUETA
    assert linea.endswith("…")


def test_usa_el_historial_por_defecto(tmp_path):
    entrada = _con_json(tmp_path)
    historial.registrar(entrada["txt"], entrada["json"])
    resultado = buscar.buscar("aprobado")
    assert len(resultado) == 1
    assert resultado[0].txt == entrada["txt"].resolve()
