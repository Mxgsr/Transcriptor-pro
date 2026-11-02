# Ubicación: tests/test_vista.py
# Pruebas de la vista de lectura con audio (src/vista.py), sin navegador.
import json
import os
import re
import stat
import sys
from datetime import date

import pytest

from src import vista
from utils.formatters import guardar_json, guardar_txt_con_timestamps

PARRAFOS = [
    {"start": 0.0, "end": 5.0, "speaker": "Hablante 1", "text": "Hola a todos."},
    {"start": 5.0, "end": 12.0, "speaker": "Hablante 2", "text": "Gracias, empecemos </script><b>ya</b>."},
]


def _crear_con_json(carpeta, titulo="Planificación", audio=None):
    json_path = carpeta / "charla.blocks.json"
    txt = carpeta / "charla.blocks.txt"
    guardar_json(PARRAFOS, json_path, audio=audio, nombres={"Hablante 1": "Ana"},
                 titulo=titulo, fecha=date(2026, 10, 30) if titulo else None, duracion=125.0 if titulo else None)
    guardar_txt_con_timestamps(PARRAFOS, txt)
    return txt, json_path


def _datos_en_el_html(html):
    crudo = re.search(r'<script type="application/json" id="datos">(.*?)</script>', html, re.S).group(1)
    return json.loads(crudo)


def test_datos_con_json_aplica_nombres_y_encabezado(tmp_path):
    txt, json_path = _crear_con_json(tmp_path)
    datos = vista.datos_de_vista(txt, json_path)
    assert datos["titulo"] == "Planificación"
    assert datos["fecha"] == "30 de octubre de 2026"
    assert datos["duracion"] == "2 min 05 s"
    assert datos["participantes"] == ["Ana", "Hablante 2"]
    assert datos["parrafos"][0]["speaker"] == "Ana"
    assert datos["audio"] is None


def test_datos_con_json_sin_titulo_usa_el_nombre_del_txt(tmp_path):
    txt, json_path = _crear_con_json(tmp_path, titulo=None)
    datos = vista.datos_de_vista(txt, json_path)
    assert datos["titulo"] == "charla"
    assert datos["fecha"] is None and datos["duracion"] is None


def test_audio_del_json_o_junto_al_json(tmp_path):
    audio = tmp_path / "charla.mp3"
    audio.write_bytes(b"x")
    txt, json_path = _crear_con_json(tmp_path, audio=tmp_path / "otra" / "charla.mp3")
    assert vista.datos_de_vista(txt, json_path)["audio"] == audio  # lo encuentra junto al .json
    otro = tmp_path / "elegido.wav"
    otro.write_bytes(b"x")
    assert vista.datos_de_vista(txt, json_path, audio=otro)["audio"] == otro


def test_datos_sin_json_con_encabezado(tmp_path):
    txt = tmp_path / "2026-10-30 Reunión.blocks.txt"
    txt.write_text("# Reunión de equipo\nFecha: 30 de octubre de 2026\nDuración: 3 s\n"
                   "Participantes: Ana, Luis\n\n[00:00:03] Hola\n\n[00:01:00] Adiós\n", encoding="utf-8")
    datos = vista.datos_de_vista(txt)
    assert datos["titulo"] == "Reunión de equipo"
    assert datos["fecha"] == "30 de octubre de 2026"
    assert datos["participantes"] == ["Ana", "Luis"]
    assert [(p["start"], p["text"], p["speaker"]) for p in datos["parrafos"]] == [(3.0, "Hola", None), (60.0, "Adiós", None)]


def test_datos_sin_json_sin_encabezado(tmp_path):
    txt = tmp_path / "grabacion.blocks.txt"
    txt.write_text("[00:00:01] Hola\n", encoding="utf-8")
    datos = vista.datos_de_vista(txt)
    assert datos["titulo"] == "grabacion"
    assert datos["fecha"] is None and datos["duracion"] is None and datos["participantes"] == []


def test_audio_junto_al_txt_sin_json(tmp_path):
    txt = tmp_path / "grabacion.blocks.txt"
    txt.write_text("[00:00:01] Hola\n", encoding="utf-8")
    (tmp_path / "grabacion.wav").write_bytes(b"x")
    assert vista.datos_de_vista(txt)["audio"] == tmp_path / "grabacion.wav"


def test_html_sin_audio_no_tiene_reproductor_activo(tmp_path):
    txt, json_path = _crear_con_json(tmp_path)
    html = vista.generar_html(vista.datos_de_vista(txt, json_path))
    assert _datos_en_el_html(html)["audio"] is None
    assert "No encontré el audio de esta transcripción; puedes leerla igual." in html
    # el <audio> existe en la plantilla pero oculto y sin src hasta que el JS lo active
    assert "<audio" in html and 'hidden></audio>' in html


def test_html_con_audio_usa_uri_de_archivo(tmp_path):
    audio = tmp_path / "a b.wav"
    audio.write_bytes(b"x")
    txt, json_path = _crear_con_json(tmp_path)
    html = vista.generar_html(vista.datos_de_vista(txt, json_path, audio))
    assert _datos_en_el_html(html)["audio"] == audio.resolve().as_uri()


def test_html_escapa_el_texto_del_usuario(tmp_path):
    txt, json_path = _crear_con_json(tmp_path, titulo="<i>Título</i> & más")
    html = vista.generar_html(vista.datos_de_vista(txt, json_path))
    assert "</script><b>" not in html
    assert "<i>Título</i>" not in html
    assert "\\u003c/script\\u003e" in html
    datos = _datos_en_el_html(html)
    assert datos["parrafos"][1]["text"] == "Gracias, empecemos </script><b>ya</b>."
    assert datos["titulo"] == "<i>Título</i> & más"


def test_ir_a_queda_en_el_html(tmp_path):
    txt, json_path = _crear_con_json(tmp_path)
    datos = vista.datos_de_vista(txt, json_path)
    assert _datos_en_el_html(vista.generar_html(datos, ir_a=7.5))["irA"] == 7.5
    assert _datos_en_el_html(vista.generar_html(datos))["irA"] is None


def test_crear_vista_escribe_en_la_carpeta_de_datos(tmp_path, historial_temporal):
    txt, json_path = _crear_con_json(tmp_path)
    ruta = vista.crear_vista(txt, json_path)
    assert ruta == historial_temporal / "vistas" / "charla.html"
    assert ruta.read_text(encoding="utf-8").startswith("<!doctype html>")
    # se sobrescribe sin error
    assert vista.crear_vista(txt, json_path, ir_a=3) == ruta
    assert _datos_en_el_html(ruta.read_text(encoding="utf-8"))["irA"] == 3


def test_abrir_en_navegador(tmp_path, monkeypatch):
    ruta = tmp_path / "v.html"
    ruta.write_text("x")
    llamadas = []
    monkeypatch.setattr("webbrowser.open", lambda url: llamadas.append(url) or True)
    assert vista.abrir_en_navegador(ruta) is True
    assert llamadas[0].startswith("file://") and "#" not in llamadas[0]

    def falla(url):
        raise RuntimeError("sin navegador")
    monkeypatch.setattr("webbrowser.open", falla)
    assert vista.abrir_en_navegador(ruta) is False


# --- Permisos: la página lleva la transcripción entera ---

@pytest.mark.skipif(sys.platform == "win32", reason="en Windows no hay permisos POSIX")
def test_vista_queda_privada(tmp_path, historial_temporal):
    txt, json_path = _crear_con_json(tmp_path)
    anterior = os.umask(0o022)
    try:
        ruta = vista.crear_vista(txt, json_path)
    finally:
        os.umask(anterior)
    assert stat.S_IMODE(os.stat(ruta).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(ruta.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(historial_temporal).st_mode) == 0o700


def test_vista_mismo_contenido_que_generar_html(tmp_path, historial_temporal):
    txt, json_path = _crear_con_json(tmp_path)
    ruta = vista.crear_vista(txt, json_path, ir_a=2)
    assert ruta.read_bytes() == vista.generar_html(vista.datos_de_vista(txt, json_path), 2).encode("utf-8")


def test_vista_en_windows_no_lanza(tmp_path, historial_temporal, monkeypatch):
    from utils import archivos
    monkeypatch.setattr(archivos, "_es_windows", lambda: True)
    monkeypatch.delattr(archivos.os, "getuid", raising=False)
    monkeypatch.setattr(archivos.os, "chmod", lambda *a, **k: None)
    txt, json_path = _crear_con_json(tmp_path)
    assert vista.crear_vista(txt, json_path).exists()
