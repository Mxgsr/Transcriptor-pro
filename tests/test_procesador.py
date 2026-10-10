# Ubicación: tests/test_procesador.py
import json
from unittest.mock import MagicMock

from src import procesador


SEGMENTOS = [
    {"start": 0.0, "end": 2.0, "text": "Hola a todos."},
    {"start": 2.1, "end": 4.0, "text": "Bienvenidos."},
]


def test_procesar_archivo_local_genera_solo_txt(tmp_path, monkeypatch):
    audio = tmp_path / "clase.mp3"
    audio.write_bytes(b"")
    transcribir = MagicMock(return_value=SEGMENTOS)
    descargar = MagicMock()
    monkeypatch.setattr(procesador, "transcribir_audio", transcribir)
    monkeypatch.setattr(procesador, "descargar_audio", descargar)

    resultado = procesador.procesar_entrada(str(audio), "tiny")

    descargar.assert_not_called()
    transcribir.assert_called_once_with(audio, model_name="tiny", language="es", mostrar_progreso=True, progreso=None)
    assert resultado.txt_path == tmp_path / "clase.blocks.txt"
    assert resultado.json_path is None
    assert resultado.duracion == 4.0
    assert resultado.txt_path.read_text(encoding="utf-8") == "[00:00:00] Hola a todos. Bienvenidos."
    assert not (tmp_path / "clase.blocks.srt").exists()


def test_procesar_url_descarga_primero(tmp_path, monkeypatch):
    audio = tmp_path / "Video.mp3"
    descargar = MagicMock(return_value=audio)
    monkeypatch.setattr(procesador, "descargar_audio", descargar)
    monkeypatch.setattr(procesador, "transcribir_audio", MagicMock(return_value=SEGMENTOS))

    procesador.procesar_entrada("https://youtube.com/watch?v=abc", "small")

    descargar.assert_called_once_with("https://youtube.com/watch?v=abc", silencioso=False, progreso=None,
                                      carpeta=None)
    assert (tmp_path / "Video.blocks.txt").exists()


def test_procesar_guarda_en_la_carpeta_de_salida(tmp_path, monkeypatch):
    audio = tmp_path / "clase.mp3"
    audio.write_bytes(b"")
    monkeypatch.setattr(procesador, "transcribir_audio", MagicMock(return_value=SEGMENTOS))

    resultado = procesador.procesar_entrada(str(audio), "tiny", salida=tmp_path / "textos" / "nuevos")

    assert resultado.txt_path == tmp_path / "textos" / "nuevos" / "clase.blocks.txt"
    assert resultado.txt_path.exists()
    assert not (tmp_path / "clase.blocks.txt").exists()


def test_procesar_avisa_cada_paso_y_silencia_motores(tmp_path, monkeypatch):
    audio = tmp_path / "Video.mp3"
    descargar = MagicMock(return_value=audio)
    transcribir = MagicMock(return_value=SEGMENTOS)
    monkeypatch.setattr(procesador, "descargar_audio", descargar)
    monkeypatch.setattr(procesador, "transcribir_audio", transcribir)
    pasos = []
    progresar = MagicMock()

    procesador.procesar_entrada("https://youtu.be/abc", "tiny", idioma="en",
                                al_avanzar=pasos.append, al_progresar=progresar, silenciar_motores=True)

    assert pasos == ["Descargando audio", "Transcribiendo"]
    assert descargar.call_args.kwargs == {"silencioso": True, "progreso": progresar, "carpeta": None}
    assert transcribir.call_args.kwargs == {
        "model_name": "tiny", "language": "en", "mostrar_progreso": False, "progreso": progresar,
    }


def test_procesar_con_diarizacion_guarda_json_y_aplica_nombres(tmp_path, monkeypatch):
    audio = tmp_path / "charla.mp3"
    audio.write_bytes(b"")
    monkeypatch.setattr(procesador, "transcribir_audio", MagicMock(return_value=[dict(s) for s in SEGMENTOS]))
    monkeypatch.setattr(procesador, "cargar_pipeline", MagicMock(return_value=object()))
    monkeypatch.setattr(procesador, "diarizar_audio", MagicMock(return_value=[
        {"start": 0.0, "end": 2.05, "speaker": "SPEAKER_00"},
        {"start": 2.05, "end": 4.0, "speaker": "SPEAKER_01"},
    ]))
    pasos = []

    resultado = procesador.procesar_entrada(str(audio), "tiny", diarizar=True,
                                            nombres={"Hablante 2": "Luis"}, al_avanzar=pasos.append)

    assert pasos == ["Preparando hablantes", "Transcribiendo", "Identificando hablantes"]
    assert resultado.json_path == tmp_path / "charla.blocks.json"
    guardado = json.loads(resultado.json_path.read_text(encoding="utf-8"))
    assert guardado["audio"] == str(audio.resolve())
    assert guardado["nombres"] == {"Hablante 2": "Luis"}
    assert [p["speaker"] for p in guardado["parrafos"]] == ["Hablante 1", "Hablante 2"]
    assert [p["speaker"] for p in resultado.parrafos] == ["Hablante 1", "Luis"]
    assert resultado.txt_path.read_text(encoding="utf-8") == (
        "[00:00:00] Hablante 1: Hola a todos.\n\n[00:00:02] Luis: Bienvenidos."
    )


def test_si_falla_la_diarizacion_se_guarda_la_transcripcion_sin_hablantes(tmp_path, monkeypatch):
    audio = tmp_path / "charla.mp3"
    audio.write_bytes(b"")
    monkeypatch.setattr(procesador, "transcribir_audio", MagicMock(return_value=[dict(s) for s in SEGMENTOS]))
    monkeypatch.setattr(procesador, "cargar_pipeline", MagicMock(return_value=object()))
    monkeypatch.setattr(procesador, "diarizar_audio", MagicMock(side_effect=TypeError("expected np.ndarray (got array)")))
    fallos = []

    resultado = procesador.procesar_entrada(str(audio), "large", diarizar=True, al_fallar=fallos.append)

    assert fallos == ["expected np.ndarray (got array)"]
    assert resultado.error_hablantes == "expected np.ndarray (got array)"
    assert resultado.json_path is None
    assert not (tmp_path / "charla.blocks.json").exists()
    assert resultado.txt_path.read_text(encoding="utf-8") == "[00:00:00] Hola a todos. Bienvenidos."


def test_la_transcripcion_se_guarda_antes_de_diarizar(tmp_path, monkeypatch):
    """Si la diarización se interrumpe (Ctrl+C), el .txt ya está en disco."""
    audio = tmp_path / "charla.mp3"
    audio.write_bytes(b"")
    monkeypatch.setattr(procesador, "transcribir_audio", MagicMock(return_value=[dict(s) for s in SEGMENTOS]))
    monkeypatch.setattr(procesador, "cargar_pipeline", MagicMock(return_value=object()))
    monkeypatch.setattr(procesador, "diarizar_audio", MagicMock(side_effect=KeyboardInterrupt))

    try:
        procesador.procesar_entrada(str(audio), "large", diarizar=True)
    except KeyboardInterrupt:
        pass

    assert (tmp_path / "charla.blocks.txt").read_text(encoding="utf-8") == "[00:00:00] Hola a todos. Bienvenidos."


def _json_diarizado(tmp_path, nombres=None):
    from utils.formatters import guardar_json

    json_path = tmp_path / "charla.blocks.json"
    guardar_json([
        {"start": 0, "end": 1, "text": "Hola", "speaker": "Hablante 1"},
        {"start": 1, "end": 2, "text": "Qué tal", "speaker": "Hablante 2"},
    ], json_path, audio="/ya/no/existe.mp3", nombres=nombres)
    return json_path


def test_renombrar_suma_nombres_a_los_guardados(tmp_path):
    json_path = _json_diarizado(tmp_path, nombres={"Hablante 1": "Ana"})

    txt_path, parrafos = procesador.renombrar_hablantes(json_path, {"Hablante 2": "Luis"})

    assert txt_path.read_text(encoding="utf-8") == "[00:00:00] Ana: Hola\n\n[00:00:01] Luis: Qué tal"
    assert json.loads(json_path.read_text(encoding="utf-8"))["nombres"] == {"Hablante 1": "Ana", "Hablante 2": "Luis"}


def test_renombrar_sin_nombres_nuevos_no_toca_el_json(tmp_path):
    json_path = _json_diarizado(tmp_path, nombres={"Hablante 1": "Ana"})
    antes = json_path.read_text(encoding="utf-8")

    procesador.renombrar_hablantes(json_path, {})

    assert json_path.read_text(encoding="utf-8") == antes


def test_leer_transcripcion_busca_el_audio_junto_al_json(tmp_path):
    json_path = _json_diarizado(tmp_path)
    (tmp_path / "charla.mp3").write_bytes(b"")

    datos = procesador.leer_transcripcion(json_path)

    assert datos["audio"] == tmp_path / "charla.mp3"
    assert len(datos["parrafos"]) == 2


def test_procesar_quita_las_frases_repetidas_en_bucle(tmp_path, monkeypatch):
    audio = tmp_path / "clase.mp3"
    audio.write_bytes(b"")
    segmentos = [
        {"start": 0.0, "end": 2.0, "text": " Gracias. Gracias. Gracias. Gracias."},
        *[{"start": 2.0 + i, "end": 3.0 + i, "text": " Un error."} for i in range(4)],
        {"start": 6.0, "end": 7.0, "text": " Seguimos."},
    ]
    monkeypatch.setattr(procesador, "transcribir_audio", MagicMock(return_value=segmentos))

    resultado = procesador.procesar_entrada(str(audio), "tiny")

    assert resultado.txt_path.read_text(encoding="utf-8") == "[00:00:00] Gracias. Un error. Seguimos."
    assert resultado.duracion == 7.0
