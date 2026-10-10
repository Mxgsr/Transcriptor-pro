# Ubicación: tests/test_fragmentos.py
from unittest.mock import MagicMock

from src import fragmentos


def test_buscar_audio_usa_el_guardado_si_existe(tmp_path):
    audio = tmp_path / "otra_carpeta.mp3"
    audio.write_bytes(b"")
    assert fragmentos.buscar_audio(tmp_path / "charla.blocks.json", str(audio)) == audio


def test_buscar_audio_lo_busca_junto_al_json(tmp_path):
    (tmp_path / "charla.m4a").write_bytes(b"")
    (tmp_path / "charla.blocks.txt").write_text("", encoding="utf-8")

    encontrado = fragmentos.buscar_audio(tmp_path / "charla.blocks.json", "/ya/no/existe.mp3")

    assert encontrado == tmp_path / "charla.m4a"


def test_buscar_audio_sin_audio(tmp_path):
    assert fragmentos.buscar_audio(tmp_path / "charla.blocks.json", None) is None


def test_elegir_fragmentos_prefiere_los_parrafos_mas_largos():
    parrafos = [
        {"start": 0, "end": 2, "text": "Corto", "speaker": "Hablante 1"},
        {"start": 2, "end": 30, "text": "Largo", "speaker": "Hablante 1"},
        {"start": 30, "end": 40, "text": "Del otro", "speaker": "Hablante 2"},
        {"start": 40, "end": 50, "text": "Medio", "speaker": "Hablante 1"},
        {"start": 50, "end": 90, "text": "  ", "speaker": "Hablante 1"},
    ]
    elegidos = fragmentos.elegir_fragmentos(parrafos, "Hablante 1", maximo=2)
    assert [p["text"] for p in elegidos] == ["Largo", "Medio"]


def test_extraer_fragmento_llama_a_ffmpeg(tmp_path, monkeypatch):
    run = MagicMock()
    monkeypatch.setattr(fragmentos.subprocess, "run", run)

    fragmentos.extraer_fragmento(tmp_path / "a.mp3", 75.5, 10, tmp_path / "f.wav")

    cmd = run.call_args.args[0]
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-ss") + 1] == "75.50"
    assert cmd[cmd.index("-t") + 1] == "10.00"
    assert cmd[cmd.index("-i") + 1] == str(tmp_path / "a.mp3")
    assert cmd[-1] == str(tmp_path / "f.wav")


def test_comando_reproductor_prefiere_afplay(monkeypatch):
    monkeypatch.setattr(fragmentos.shutil, "which", lambda c: "/usr/bin/" + c if c in ("afplay", "ffplay") else None)
    assert fragmentos.comando_reproductor() == ["afplay"]
    monkeypatch.setattr(fragmentos.shutil, "which", lambda c: "/usr/bin/ffplay" if c == "ffplay" else None)
    assert fragmentos.comando_reproductor()[0] == "ffplay"
    monkeypatch.setattr(fragmentos.shutil, "which", lambda c: None)
    assert fragmentos.comando_reproductor() is None


def test_reproductor_detiene_lo_anterior(monkeypatch, tmp_path):
    procesos = []

    def popen(cmd, **kwargs):
        proceso = MagicMock()
        proceso.poll.return_value = None
        procesos.append((cmd, proceso))
        return proceso

    monkeypatch.setattr(fragmentos.subprocess, "Popen", popen)
    reproductor = fragmentos.Reproductor(["afplay"])

    reproductor.reproducir(tmp_path / "1.wav")
    reproductor.reproducir(tmp_path / "2.wav")
    reproductor.detener()

    assert [cmd for cmd, _ in procesos] == [["afplay", str(tmp_path / "1.wav")], ["afplay", str(tmp_path / "2.wav")]]
    assert all(p.terminate.called for _, p in procesos)
