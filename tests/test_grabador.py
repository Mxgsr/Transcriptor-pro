# Ubicación: tests/test_grabador.py
# El Grabador de Max (app aparte) llama a `transcriptor transcribir <mezcla> -d --sin-preguntas -o <carpeta>`
# y después lee `<nombre del audio>.blocks.txt` en esa carpeta. Este test fija ese contrato de punta a punta:
# mismo nombre de archivo, mismo formato del .txt, sin encabezado, sin preguntas y sin notificaciones.
import logging
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from src import aviso, cli, procesador
from src.cli import app


@pytest.fixture(autouse=True)
def restaurar_logging():
    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    yield
    raiz.handlers[:] = handlers
    raiz.setLevel(nivel)


def test_la_llamada_del_grabador_no_cambia(tmp_path, monkeypatch):
    grabacion = tmp_path / "2026-11-01_1000_equipo"
    grabacion.mkdir()
    audio = grabacion / "equipo_mezcla.m4a"
    audio.write_bytes(b"")

    monkeypatch.setattr(procesador, "transcribir_audio", MagicMock(return_value=[
        {"start": 0.0, "end": 2.0, "text": "Hola a todos."},
        {"start": 2.1, "end": 4.0, "text": "Bienvenidos."},
    ]))
    monkeypatch.setattr(procesador, "cargar_pipeline", MagicMock(return_value=object()))
    monkeypatch.setattr(procesador, "diarizar_audio", MagicMock(return_value=[
        {"start": 0.0, "end": 2.05, "speaker": "SPEAKER_00"},
        {"start": 2.05, "end": 4.0, "speaker": "SPEAKER_01"},
    ]))
    # Aunque haya una persona delante, --sin-preguntas no pregunta ni avisa
    monkeypatch.setattr(cli, "_es_interactivo", lambda: True)
    notificar = MagicMock()
    monkeypatch.setattr(aviso, "notificar", notificar)
    monkeypatch.setattr(aviso, "sin_dormir", MagicMock())
    from src import menu
    monkeypatch.setattr(menu, "elegir", MagicMock(side_effect=AssertionError("no debe preguntar")))
    monkeypatch.setattr(menu, "texto", MagicMock(side_effect=AssertionError("no debe preguntar")))

    resultado = runner_invoke(["transcribir", str(audio), "-d", "--sin-preguntas", "-o", str(grabacion)])

    assert resultado.exit_code == 0, resultado.output
    txt = grabacion / "equipo_mezcla.blocks.txt"
    assert txt.read_text(encoding="utf-8") == (
        "[00:00:00] Hablante 1: Hola a todos.\n\n[00:00:02] Hablante 2: Bienvenidos."
    )
    assert (grabacion / "equipo_mezcla.blocks.json").exists()
    notificar.assert_not_called()


def runner_invoke(argumentos):
    return CliRunner().invoke(app, argumentos)


def test_si_fallan_los_hablantes_el_blocks_txt_existe_igual(tmp_path, monkeypatch):
    # Si preparar pyannote falla (sin clave, sin internet), el Grabador debe tener igual su transcripción.
    # La CLI pasa continuar_sin_hablantes=True con --sin-preguntas; aquí se prueba a nivel procesador,
    # que es donde vive el cambio, y de extremo a extremo si la CLI ya lo pasa.
    audio = tmp_path / "equipo_mezcla.m4a"
    audio.write_bytes(b"")
    monkeypatch.setattr(procesador, "transcribir_audio", MagicMock(return_value=[
        {"start": 0.0, "end": 2.0, "text": "Hola a todos."},
        {"start": 2.1, "end": 4.0, "text": "Bienvenidos."},
    ]))
    monkeypatch.setattr(procesador, "cargar_pipeline", MagicMock(side_effect=RuntimeError("falta HF_TOKEN")))

    resultado = procesador.procesar_entrada(str(audio), "small", diarizar=True, salida=tmp_path,
                                            continuar_sin_hablantes=True)

    txt = tmp_path / "equipo_mezcla.blocks.txt"
    assert resultado.txt_path == txt
    assert txt.read_text(encoding="utf-8") == "[00:00:00] Hola a todos. Bienvenidos."  # sin hablantes, un solo párrafo
    assert not (tmp_path / "equipo_mezcla.blocks.json").exists()
    assert resultado.error_hablantes == "falta HF_TOKEN"


def test_cli_del_grabador_deja_el_txt_aunque_falle_la_preparacion_de_hablantes(tmp_path, monkeypatch):
    # De punta a punta por la CLI: -d --sin-preguntas sin poder preparar pyannote (p. ej. sin clave de
    # Hugging Face) ya no sale con error: la transcripción queda sin hablantes y el Grabador la lee igual.
    audio = tmp_path / "equipo_mezcla.m4a"
    audio.write_bytes(b"")
    monkeypatch.setattr(procesador, "transcribir_audio", MagicMock(return_value=[
        {"start": 0.0, "end": 2.0, "text": "Hola a todos."},
        {"start": 2.1, "end": 4.0, "text": "Bienvenidos."},
    ]))
    monkeypatch.setattr(procesador, "cargar_pipeline", MagicMock(side_effect=RuntimeError("falta HF_TOKEN")))
    monkeypatch.setattr(cli, "_es_interactivo", lambda: True)
    notificar = MagicMock()
    monkeypatch.setattr(aviso, "notificar", notificar)
    monkeypatch.setattr(aviso, "sin_dormir", MagicMock())

    resultado = runner_invoke(["transcribir", str(audio), "-d", "--sin-preguntas", "-o", str(tmp_path)])

    assert resultado.exit_code == 0, resultado.output
    assert (tmp_path / "equipo_mezcla.blocks.txt").read_text(encoding="utf-8") == (
        "[00:00:00] Hola a todos. Bienvenidos."
    )
    notificar.assert_not_called()
