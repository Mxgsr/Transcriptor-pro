# Ubicación: tests/test_main.py
import sys
from unittest.mock import MagicMock

import pytest

import main


SEGMENTOS = [
    {"start": 0.0, "end": 2.0, "text": "Hola a todos."},
    {"start": 2.1, "end": 4.0, "text": "Bienvenidos."},
]


def test_procesar_archivo_local_genera_txt_y_srt(tmp_path, monkeypatch):
    audio = tmp_path / "clase.mp3"
    audio.write_bytes(b"")
    transcribir = MagicMock(return_value=SEGMENTOS)
    descargar = MagicMock()
    monkeypatch.setattr(main, "transcribir_audio", transcribir)
    monkeypatch.setattr(main, "descargar_audio", descargar)

    main.procesar_entrada(str(audio), "tiny")

    descargar.assert_not_called()
    transcribir.assert_called_once_with(audio, model_name="tiny")
    assert (tmp_path / "clase.blocks.txt").read_text(encoding="utf-8") == (
        "[00:00:00] Hola a todos. Bienvenidos."
    )
    assert (tmp_path / "clase.blocks.srt").read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:04,000\nHola a todos. Bienvenidos.\n"
    )


def test_procesar_url_descarga_primero(tmp_path, monkeypatch):
    audio = tmp_path / "Video.mp3"
    descargar = MagicMock(return_value=audio)
    monkeypatch.setattr(main, "descargar_audio", descargar)
    monkeypatch.setattr(main, "transcribir_audio", MagicMock(return_value=SEGMENTOS))

    main.procesar_entrada("https://youtube.com/watch?v=abc", "small")

    descargar.assert_called_once_with("https://youtube.com/watch?v=abc")
    assert (tmp_path / "Video.blocks.txt").exists()
    assert (tmp_path / "Video.blocks.srt").exists()


def test_main_sale_con_codigo_1_ante_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "audio.mp3", "--model", "tiny"])
    monkeypatch.setattr(main, "procesar_entrada", MagicMock(side_effect=RuntimeError("boom")))

    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 1


def test_main_pasa_argumentos(monkeypatch):
    procesar = MagicMock()
    monkeypatch.setattr(sys, "argv", ["main.py", "audio.mp3", "--model", "tiny"])
    monkeypatch.setattr(main, "procesar_entrada", procesar)

    main.main()
    procesar.assert_called_once_with("audio.mp3", "tiny")
