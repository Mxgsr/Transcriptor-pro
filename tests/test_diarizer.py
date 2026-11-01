# Ubicación: tests/test_diarizer.py
import json
import sys
from unittest.mock import MagicMock

import pytest

from src import procesador
from src.diarizer import asignar_hablantes, parsear_nombres, aplicar_nombres, cargar_pipeline, diarizar_audio
from src.transcriber import agrupar_segmentos_en_parrafos
from utils.formatters import guardar_txt_con_timestamps


def _seg(start, end, text):
    return {"start": start, "end": end, "text": text}


def test_asignar_hablantes_por_mayor_solape_y_orden_de_aparicion():
    segmentos = [_seg(0, 2, "Hola"), _seg(2, 4, "Qué tal"), _seg(4, 6, "Bien")]
    turnos = [
        {"start": 0.0, "end": 2.2, "speaker": "SPEAKER_07"},
        {"start": 2.2, "end": 4.0, "speaker": "SPEAKER_03"},
        {"start": 4.0, "end": 6.0, "speaker": "SPEAKER_07"},
    ]
    resultado = asignar_hablantes(segmentos, turnos)
    assert [s["speaker"] for s in resultado] == ["Hablante 1", "Hablante 2", "Hablante 1"]


def test_asignar_hablantes_sin_solape_toma_el_turno_mas_cercano():
    segmentos = [_seg(0, 1, "Hola"), _seg(10, 11, "Adiós")]
    turnos = [
        {"start": 0.0, "end": 1.0, "speaker": "A"},
        {"start": 1.0, "end": 2.0, "speaker": "B"},
    ]
    resultado = asignar_hablantes(segmentos, turnos)
    assert resultado[1]["speaker"] == "Hablante 2"


def test_asignar_hablantes_sin_turnos_no_etiqueta():
    segmentos = [_seg(0, 1, "Hola")]
    assert "speaker" not in asignar_hablantes(segmentos, [])[0]


def _pal(start, end, word):
    return {"start": start, "end": end, "word": word}


TURNOS_AB = [
    {"start": 0.0, "end": 3.0, "speaker": "A"},
    {"start": 3.0, "end": 6.0, "speaker": "B"},
]


def _palabras(texto, inicio, paso=0.3):
    """Palabras seguidas de paso segundos cada una, como las da mlx-whisper (" hola")."""
    return [_pal(inicio + i * paso, inicio + (i + 1) * paso, " " + w) for i, w in enumerate(texto.split())]


def _con_palabras(palabras):
    return {"start": palabras[0]["start"], "end": palabras[-1]["end"],
            "text": "".join(p["word"] for p in palabras), "words": palabras}


def test_asignar_hablantes_parte_el_segmento_donde_cambia_el_hablante():
    segmento = {"start": 0.0, "end": 6.0, "text": " ¿Cómo se llamaba el curso? No me acuerdo.", "words": [
        _pal(0.0, 0.5, " ¿Cómo"), _pal(0.5, 1.0, " se"), _pal(1.0, 1.8, " llamaba"),
        _pal(1.8, 2.2, " el"), _pal(2.2, 2.9, " curso?"),
        _pal(3.2, 3.6, " No"), _pal(3.6, 3.9, " me"), _pal(3.9, 4.8, " acuerdo."),
    ]}
    resultado = asignar_hablantes([segmento], TURNOS_AB)
    assert [(s["speaker"], s["text"], s["start"], s["end"]) for s in resultado] == [
        ("Hablante 1", "¿Cómo se llamaba el curso?", 0.0, 2.9),
        ("Hablante 2", "No me acuerdo.", 3.2, 4.8),
    ]


def test_asignar_hablantes_con_un_solo_hablante_deja_una_frase():
    segmento = _con_palabras(_palabras("Hola a todos.", 0.0))
    resultado = asignar_hablantes([segmento], TURNOS_AB)
    assert [(s["speaker"], s["text"]) for s in resultado] == [("Hablante 1", "Hola a todos.")]


def test_asignar_hablantes_una_palabra_suelta_en_medio_de_frase_no_cambia_de_hablante():
    turnos = [
        {"start": 0.0, "end": 1.0, "speaker": "A"},
        {"start": 1.0, "end": 1.3, "speaker": "B"},
        {"start": 1.3, "end": 3.0, "speaker": "A"},
    ]
    segmento = {"start": 0.0, "end": 3.0, "text": " voy a comprar más mercadería", "words": [
        _pal(0.0, 0.5, " voy"), _pal(0.5, 1.0, " a"), _pal(1.0, 1.3, " comprar"),
        _pal(1.3, 1.8, " más"), _pal(1.8, 3.0, " mercadería"),
    ]}
    resultado = asignar_hablantes([segmento], turnos)
    assert [s["speaker"] for s in resultado] == ["Hablante 1"]


def test_asignar_hablantes_la_palabra_que_abre_una_pregunta_va_con_la_pregunta():
    # Los tiempos dejan "¿Y" en el turno de quien terminaba de hablar
    palabras = _palabras("cosas que me gustan a mí. ¿Y cómo se llamaba el curso?", 0.0)
    turnos = [{"start": 0.0, "end": 2.1, "speaker": "A"}, {"start": 2.1, "end": 9.0, "speaker": "B"}]
    resultado = asignar_hablantes([_con_palabras(palabras)], turnos)
    assert [(s["speaker"], s["text"]) for s in resultado] == [
        ("Hablante 1", "cosas que me gustan a mí."),
        ("Hablante 2", "¿Y cómo se llamaba el curso?"),
    ]


def test_asignar_hablantes_junta_una_frase_repartida_en_dos_segmentos():
    # Whisper cortó el segmento en "en el" y los tiempos ponen "FOSI." en el turno del otro
    primero = _palabras("Y me inscribió en el", 0.0)
    segundo = _palabras("FOSI.", 1.5)
    turnos = [{"start": 0.0, "end": 1.5, "speaker": "A"}, {"start": 1.5, "end": 9.0, "speaker": "B"}]
    resultado = asignar_hablantes([_con_palabras(primero), _con_palabras(segundo)], turnos)
    assert [(s["speaker"], s["text"]) for s in resultado] == [("Hablante 1", "Y me inscribió en el FOSI.")]


def test_asignar_hablantes_parte_una_frase_larga_sin_puntuacion_si_ambos_lados_son_largos():
    palabras = _palabras("estoy comprando poleras y pijamas qué bueno y cómo se llama", 0.0)
    turnos = [{"start": 0.0, "end": 1.5, "speaker": "A"}, {"start": 1.5, "end": 9.0, "speaker": "B"}]
    resultado = asignar_hablantes([_con_palabras(palabras)], turnos)
    assert [(s["speaker"], s["text"]) for s in resultado] == [
        ("Hablante 1", "estoy comprando poleras y pijamas"),
        ("Hablante 2", "qué bueno y cómo se llama"),
    ]


def test_asignar_hablantes_un_silencio_largo_separa_frases():
    palabras = _palabras("bien gracias", 0.0) + _palabras("y usted", 1.5)
    turnos = [{"start": 0.0, "end": 1.0, "speaker": "A"}, {"start": 1.0, "end": 9.0, "speaker": "B"}]
    resultado = asignar_hablantes([_con_palabras(palabras)], turnos)
    assert [(s["speaker"], s["text"]) for s in resultado] == [("Hablante 1", "bien gracias"),
                                                             ("Hablante 2", "y usted")]


def test_asignar_hablantes_respeta_una_respuesta_corta_entre_frases():
    turnos = [
        {"start": 0.0, "end": 1.0, "speaker": "A"},
        {"start": 1.0, "end": 2.0, "speaker": "B"},
        {"start": 2.0, "end": 3.0, "speaker": "A"},
    ]
    segmento = {"start": 0.0, "end": 3.0, "text": " No. ¿Ninguna? No.", "words": [
        _pal(0.0, 0.8, " No."), _pal(1.1, 1.8, " ¿Ninguna?"), _pal(2.2, 2.8, " No."),
    ]}
    resultado = asignar_hablantes([segmento], turnos)
    assert [(s["speaker"], s["text"]) for s in resultado] == [
        ("Hablante 1", "No."), ("Hablante 2", "¿Ninguna?"), ("Hablante 1", "No."),
    ]


def test_asignar_hablantes_mezcla_segmentos_con_y_sin_palabras_en_orden():
    con = _con_palabras(_palabras("Hola a todos.", 0.0))
    sin = {"start": 4.0, "end": 5.0, "text": "Gracias."}
    resultado = asignar_hablantes([con, sin], TURNOS_AB)
    assert [(s["speaker"], s["text"]) for s in resultado] == [("Hablante 1", "Hola a todos."),
                                                             ("Hablante 2", "Gracias.")]


def test_parsear_nombres_por_orden_y_por_numero():
    assert parsear_nombres(" Ana , Luis ,") == {"Hablante 1": "Ana", "Hablante 2": "Luis"}
    assert parsear_nombres("2=Luis") == {"Hablante 2": "Luis"}
    assert parsear_nombres(None) == {}


@pytest.mark.parametrize("texto", ["x=Ana", "2="])
def test_parsear_nombres_invalidos(texto):
    with pytest.raises(ValueError):
        parsear_nombres(texto)


def test_aplicar_nombres_no_modifica_el_original():
    parrafos = [{"start": 0, "end": 1, "text": "Hola", "speaker": "Hablante 1"}]
    renombrados = aplicar_nombres(parrafos, {"Hablante 1": "Ana"})
    assert renombrados[0]["speaker"] == "Ana"
    assert parrafos[0]["speaker"] == "Hablante 1"


def test_agrupar_corta_al_cambiar_de_hablante():
    segmentos = [
        {**_seg(0, 1, "Hola."), "speaker": "Hablante 1"},
        {**_seg(1, 2, "Hola."), "speaker": "Hablante 2"},
        {**_seg(2, 3, "Qué tal."), "speaker": "Hablante 2"},
    ]
    parrafos = agrupar_segmentos_en_parrafos(segmentos)
    assert [(p["speaker"], p["text"]) for p in parrafos] == [
        ("Hablante 1", "Hola."),
        ("Hablante 2", "Hola. Qué tal."),
    ]


def test_txt_incluye_hablante(tmp_path):
    parrafos = [{"start": 2, "end": 3, "text": "Bien, gracias.", "speaker": "Luis"}]
    guardar_txt_con_timestamps(parrafos, tmp_path / "a.txt")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "[00:00:02] Luis: Bien, gracias."


def test_cargar_pipeline_sin_token_falla():
    with pytest.raises(ValueError, match="HF_TOKEN"):
        cargar_pipeline(None, "pyannote/modelo")


def test_cargar_pipeline_modelo_sin_aceptar_condiciones(monkeypatch):
    pyannote_audio = MagicMock()
    pyannote_audio.Pipeline.from_pretrained.return_value = None
    monkeypatch.setitem(sys.modules, "pyannote.audio", pyannote_audio)
    with pytest.raises(RuntimeError, match="condiciones"):
        cargar_pipeline("hf_token", "pyannote/modelo")


def test_renombrar_desde_json_sin_reprocesar(tmp_path, monkeypatch):
    json_path = tmp_path / "audio.blocks.json"
    json_path.write_text(json.dumps([
        {"start": 0, "end": 1, "text": "Hola", "speaker": "Hablante 1"},
        {"start": 1, "end": 2, "text": "Qué tal", "speaker": "Hablante 2"},
    ]), encoding="utf-8")
    monkeypatch.setattr(procesador, "transcribir_audio", MagicMock(side_effect=AssertionError("no debe transcribir")))

    txt_path, _ = procesador.renombrar_hablantes(json_path, {"Hablante 2": "Pedro"})

    assert txt_path == tmp_path / "audio.blocks.txt"
    assert (tmp_path / "audio.blocks.txt").read_text(encoding="utf-8") == (
        "[00:00:00] Hablante 1: Hola\n\n[00:00:01] Pedro: Qué tal"
    )
    assert not (tmp_path / "audio.blocks.srt").exists()


class _ArrayDeMLX:
    """Imita un mx.array: se puede convertir a numpy, pero no es un np.ndarray."""

    def __init__(self, valores):
        self.valores = valores

    def __array__(self, dtype=None, copy=None):
        import numpy as np
        return np.array(self.valores, dtype=dtype)


def test_diarizar_convierte_el_audio_de_mlx_a_numpy(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"")

    # mlx_whisper.audio.load_audio devuelve un mx.array, no un np.ndarray
    audio_mlx = MagicMock()
    audio_mlx.load_audio.return_value = _ArrayDeMLX([0.0, 0.5, -0.5])
    audio_mlx.SAMPLE_RATE = 16000
    monkeypatch.setitem(sys.modules, "mlx_whisper.audio", audio_mlx)

    # torch.from_numpy solo acepta np.ndarray (es lo que fallaba)
    def from_numpy(valor):
        if not isinstance(valor, np.ndarray):
            raise TypeError(f"expected np.ndarray (got {type(valor).__name__})")
        tensor = MagicMock()
        tensor.unsqueeze.return_value = valor[None, :]
        return tensor

    torch = MagicMock()
    torch.from_numpy.side_effect = from_numpy
    monkeypatch.setitem(sys.modules, "torch", torch)

    turno = MagicMock(start=0.0, end=1.0)
    anotacion = MagicMock()
    anotacion.itertracks.return_value = [(turno, None, "SPEAKER_00")]
    pipeline = MagicMock(return_value=MagicMock(exclusive_speaker_diarization=anotacion))

    turnos = diarizar_audio(pipeline, audio, num_hablantes=2, progreso=lambda *a: None)

    assert turnos == [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
    entrada = pipeline.call_args.args[0]
    assert entrada["sample_rate"] == 16000
    assert entrada["waveform"].dtype == np.float32
    assert entrada["waveform"].tolist() == [[0.0, 0.5, -0.5]]
    assert pipeline.call_args.kwargs["num_speakers"] == 2
    assert callable(pipeline.call_args.kwargs["hook"])


def test_hook_de_progreso_une_las_etapas_de_pyannote_en_una_barra():
    from src.diarizer import _hook_de_progreso

    avance = []
    hook = _hook_de_progreso(lambda *a: avance.append(a))

    hook("segmentation", None, file={}, completed=0, total=10)
    hook("segmentation", None, file={}, completed=10, total=10)
    hook("segmentation", object(), file={})          # aviso de fin de etapa, sin números
    hook("speaker_counting", object(), file={})
    hook("embeddings", None, file={}, completed=2, total=4)
    hook("embeddings", None, file={}, completed=4, total=4)

    assert avance == [(0.0, 1.0, None), (0.25, 1.0, None), (0.625, 1.0, None), (1.0, 1.0, None)]


# --- Dispositivo (GPU del Mac) ---

class _Dispositivo:
    def __init__(self, tipo):
        self.type = tipo

    def __eq__(self, otro):
        return isinstance(otro, _Dispositivo) and otro.type == self.type

    def __repr__(self):
        return self.type


def _torch_falso(mps=False, cuda=False):
    torch = MagicMock()
    torch.device.side_effect = _Dispositivo
    torch.backends.mps.is_available.return_value = mps
    torch.cuda.is_available.return_value = cuda
    return torch


@pytest.mark.parametrize("mps, cuda, preferido, esperado", [
    (True, False, "auto", "mps"),
    (False, True, "auto", "cuda"),
    (False, False, "auto", "cpu"),
    (True, False, "cpu", "cpu"),
])
def test_elegir_dispositivo(monkeypatch, mps, cuda, preferido, esperado):
    from src.diarizer import elegir_dispositivo

    monkeypatch.setitem(sys.modules, "torch", _torch_falso(mps=mps, cuda=cuda))
    assert elegir_dispositivo(preferido).type == esperado


def test_cargar_pipeline_usa_la_gpu_y_lotes_grandes(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _torch_falso(mps=True))
    pipeline = MagicMock(embedding_batch_size=1, segmentation_batch_size=1)
    pyannote_audio = MagicMock()
    pyannote_audio.Pipeline.from_pretrained.return_value = pipeline
    monkeypatch.setitem(sys.modules, "pyannote.audio", pyannote_audio)

    assert cargar_pipeline("hf_token", "pyannote/modelo") is pipeline

    pipeline.to.assert_called_once_with(_Dispositivo("mps"))
    assert pipeline.embedding_batch_size == 32
    assert pipeline.segmentation_batch_size == 32


def test_cargar_pipeline_si_la_gpu_falla_queda_en_cpu(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _torch_falso(mps=True))
    pipeline = MagicMock()
    pipeline.to.side_effect = [RuntimeError("MPS no disponible"), pipeline]
    pyannote_audio = MagicMock()
    pyannote_audio.Pipeline.from_pretrained.return_value = pipeline
    monkeypatch.setitem(sys.modules, "pyannote.audio", pyannote_audio)

    cargar_pipeline("hf_token", "pyannote/modelo")

    assert pipeline.to.call_args.args[0] == _Dispositivo("cpu")


def test_diarizar_reintenta_en_cpu_si_falla_en_la_gpu(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"")
    audio_mlx = MagicMock()
    audio_mlx.load_audio.return_value = np.zeros(3, dtype=np.float32)
    audio_mlx.SAMPLE_RATE = 16000
    monkeypatch.setitem(sys.modules, "mlx_whisper.audio", audio_mlx)
    monkeypatch.setitem(sys.modules, "torch", _torch_falso(mps=True))

    turno = MagicMock(start=0.0, end=1.0)
    anotacion = MagicMock()
    anotacion.itertracks.return_value = [(turno, None, "SPEAKER_00")]
    pipeline = MagicMock(side_effect=[RuntimeError("fallo en MPS"), MagicMock(exclusive_speaker_diarization=anotacion)])
    pipeline.device = _Dispositivo("mps")

    turnos = diarizar_audio(pipeline, audio)

    assert turnos == [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
    pipeline.to.assert_called_once_with(_Dispositivo("cpu"))
    assert pipeline.call_count == 2


def test_diarizar_en_cpu_no_reintenta(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"")
    audio_mlx = MagicMock()
    audio_mlx.load_audio.return_value = np.zeros(3, dtype=np.float32)
    audio_mlx.SAMPLE_RATE = 16000
    monkeypatch.setitem(sys.modules, "mlx_whisper.audio", audio_mlx)
    monkeypatch.setitem(sys.modules, "torch", _torch_falso())

    pipeline = MagicMock(side_effect=RuntimeError("fallo"))
    pipeline.device = _Dispositivo("cpu")

    with pytest.raises(RuntimeError, match="fallo"):
        diarizar_audio(pipeline, audio)
    assert pipeline.call_count == 1


# --- Huellas de voz (salida de pyannote.audio 4) ---

class _Anotacion:
    """Lo mínimo de pyannote.core.Annotation que usa el programa."""
    def __init__(self, pistas):
        self.pistas = pistas  # [(inicio, fin, etiqueta), ...]

    def itertracks(self, yield_label=False):
        return [(MagicMock(start=i, end=f), None, e) for i, f, e in self.pistas]

    def labels(self):
        return sorted({e for _, _, e in self.pistas})


class _DiarizeOutput:
    """Misma forma que pyannote.audio 4 (DiarizeOutput): speaker_embeddings va en el orden de
    speaker_diarization.labels(), que puede tener hablantes que no salen en la versión exclusiva."""
    def __init__(self, pistas, exclusivas, speaker_embeddings):
        self.speaker_diarization = _Anotacion(pistas)
        self.exclusive_speaker_diarization = _Anotacion(exclusivas)
        self.speaker_embeddings = speaker_embeddings


def _preparar_diarizacion(tmp_path, monkeypatch, salida):
    np = pytest.importorskip("numpy")
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"")
    audio_mlx = MagicMock()
    audio_mlx.load_audio.return_value = np.zeros(3, dtype=np.float32)
    audio_mlx.SAMPLE_RATE = 16000
    monkeypatch.setitem(sys.modules, "mlx_whisper.audio", audio_mlx)
    monkeypatch.setitem(sys.modules, "torch", _torch_falso())
    pipeline = MagicMock(return_value=salida)
    pipeline.device = _Dispositivo("cpu")
    return pipeline, audio


PISTAS = [(0.0, 2.0, "SPEAKER_01"), (2.0, 4.0, "SPEAKER_00"), (3.5, 4.5, "SPEAKER_02")]
# SPEAKER_02 solo habla encima de otro: no sale en la versión exclusiva
EXCLUSIVAS = [(0.0, 2.0, "SPEAKER_01"), (2.0, 4.0, "SPEAKER_00")]


def test_diarizar_devuelve_la_huella_de_cada_hablante(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    # Filas en el orden de labels(): SPEAKER_00, SPEAKER_01, SPEAKER_02
    embeddings = np.array([[3.0, 4.0, 0.0], [0.0, 0.0, 2.0], [1.0, 1.0, 1.0]])
    pipeline, audio = _preparar_diarizacion(tmp_path, monkeypatch, _DiarizeOutput(PISTAS, EXCLUSIVAS, embeddings))

    huellas = {}
    turnos = diarizar_audio(pipeline, audio, huellas=huellas)

    assert [t["speaker"] for t in turnos] == ["SPEAKER_01", "SPEAKER_00"]
    # Normalizadas (largo 1), redondeadas a 5 decimales y como floats de Python (para el JSON)
    assert huellas == {
        "SPEAKER_00": [0.6, 0.8, 0.0],
        "SPEAKER_01": [0.0, 0.0, 1.0],
        "SPEAKER_02": [0.57735, 0.57735, 0.57735],
    }
    assert all(type(v) is float for h in huellas.values() for v in h)
    json.dumps(huellas)
    # pyannote 4 da los embeddings sin pedirlos: no se pasa ningún parámetro extra
    assert "return_embeddings" not in pipeline.call_args.kwargs


def test_diarizar_sin_pedir_huellas_sigue_igual(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    salida = _DiarizeOutput(PISTAS, EXCLUSIVAS, np.ones((3, 3)))
    pipeline, audio = _preparar_diarizacion(tmp_path, monkeypatch, salida)

    assert diarizar_audio(pipeline, audio) == [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_01"},
        {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_00"},
    ]


def test_diarizar_omite_huellas_con_nan_o_de_ceros(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    # pyannote rellena con ceros cuando hay más hablantes que centroides; un embedding puede salir NaN
    embeddings = np.array([[np.nan, 1.0, 0.0], [0.0, 0.0, 0.0], [0.0, 2.0, 0.0]])
    pipeline, audio = _preparar_diarizacion(tmp_path, monkeypatch, _DiarizeOutput(PISTAS, EXCLUSIVAS, embeddings))

    huellas = {}
    turnos = diarizar_audio(pipeline, audio, huellas=huellas)

    assert len(turnos) == 2
    assert huellas == {"SPEAKER_02": [0.0, 1.0, 0.0]}


@pytest.mark.parametrize("salida", [
    _DiarizeOutput(PISTAS, EXCLUSIVAS, None),                  # agrupación "oracle": sin centroides
    _DiarizeOutput(PISTAS, EXCLUSIVAS, [[1.0, 0.0]]),           # no calzan con los hablantes
    _DiarizeOutput(PISTAS, EXCLUSIVAS, "basura"),
    _Anotacion(EXCLUSIVAS),                                    # pyannote 3 o legacy=True: solo la anotación
], ids=["sin_embeddings", "no_calzan", "basura", "solo_anotacion"])
def test_diarizar_sin_huellas_utiles_no_falla(tmp_path, monkeypatch, salida):
    pipeline, audio = _preparar_diarizacion(tmp_path, monkeypatch, salida)

    huellas = {}
    turnos = diarizar_audio(pipeline, audio, huellas=huellas)

    assert [t["speaker"] for t in turnos] == ["SPEAKER_01", "SPEAKER_00"]
    assert huellas == {}


def test_diarizar_si_leer_las_huellas_explota_sigue_sin_ellas(tmp_path, monkeypatch):
    salida = _DiarizeOutput(PISTAS, EXCLUSIVAS, None)
    salida.speaker_diarization = MagicMock()
    salida.speaker_diarization.labels.side_effect = RuntimeError("raro")
    salida.speaker_embeddings = [[1.0]]
    pipeline, audio = _preparar_diarizacion(tmp_path, monkeypatch, salida)

    huellas = {}
    assert len(diarizar_audio(pipeline, audio, huellas=huellas)) == 2
    assert huellas == {}


def test_asignar_hablantes_informa_el_cambio_de_etiquetas_y_traduce_huellas():
    from src.diarizer import traducir_huellas

    segmentos = [_seg(0, 2, "Hola"), _seg(2, 4, "Qué tal")]
    turnos = [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_03"},
        {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_00"},
        {"start": 9.0, "end": 9.5, "speaker": "SPEAKER_01"},   # sin texto: no recibe etiqueta
    ]
    etiquetas = {}
    asignar_hablantes(segmentos, turnos, etiquetas=etiquetas)

    assert etiquetas == {"SPEAKER_03": "Hablante 1", "SPEAKER_00": "Hablante 2"}
    huellas = {"SPEAKER_00": [0.0, 1.0], "SPEAKER_01": [1.0, 0.0], "SPEAKER_03": [0.6, 0.8]}
    assert traducir_huellas(huellas, etiquetas) == {"Hablante 1": [0.6, 0.8], "Hablante 2": [0.0, 1.0]}


def test_asignar_hablantes_sin_turnos_deja_las_etiquetas_vacias():
    etiquetas = {}
    asignar_hablantes([_seg(0, 1, "Hola")], [], etiquetas=etiquetas)
    assert etiquetas == {}


# --- Frases con hablante dudoso (clave "dudosa" de cada segmento) ---

def _turno(inicio, fin, hablante):
    return {"start": inicio, "end": fin, "speaker": hablante}


def test_dudosa_repartida_cuando_una_palabra_votaba_por_otro_y_se_absorbio():
    # La última palabra (2,1 a 2,4 s) cae en el turno de B, pero es un trozo de 1 palabra: se suma a A
    palabras = _palabras("uno dos tres cuatro cinco seis siete ocho", 0.0)
    cierre = _palabras("Listo ya.", 3.0)
    turnos = [_turno(0.0, 2.0, "A"), _turno(2.0, 6.0, "B")]
    resultado = asignar_hablantes([_con_palabras(palabras), _con_palabras(cierre)], turnos)
    assert resultado[0]["speaker"] == "Hablante 1"
    assert resultado[0]["dudosa"] == {"otro": "Hablante 2", "motivo": "repartida"}
    assert resultado[0]["text"] == "uno dos tres cuatro cinco seis siete ocho"


def test_dudosa_fuera_de_turno_cuando_no_se_solapa_con_ningun_turno_y_hay_otro_cerca():
    palabras = _palabras("bueno entonces", 2.3)  # 2,3 a 2,9 s: entre el turno de A y el de B
    despues = _palabras("Hola a todos de nuevo en esta reunión.", 4.2)
    turnos = [_turno(0.0, 2.0, "A"), _turno(4.0, 7.0, "B")]
    resultado = asignar_hablantes([_con_palabras(palabras), _con_palabras(despues)], turnos)
    assert resultado[0]["speaker"] == "Hablante 1"
    assert resultado[0]["dudosa"] == {"otro": "Hablante 2", "motivo": "fuera_de_turno"}


def test_dudosa_fuera_de_turno_no_se_marca_si_el_otro_turno_esta_lejos():
    palabras = _palabras("bueno entonces", 2.3)
    despues = _palabras("Hola a todos de nuevo en esta reunión.", 9.2)
    turnos = [_turno(0.0, 2.0, "A"), _turno(9.0, 12.0, "B")]
    resultado = asignar_hablantes([_con_palabras(palabras), _con_palabras(despues)], turnos)
    assert resultado[0].get("dudosa", {}).get("motivo") != "fuera_de_turno"


def test_dudosa_borde_en_una_frase_corta_pegada_a_un_cambio_de_hablante():
    largo1 = _palabras("eso es lo que pasó ayer en la oficina.", 0.0)  # 8 palabras, 2,4 s
    corta = _palabras("Sí.", 3.1)
    largo2 = _palabras("entonces seguimos con el tema de la semana pasada.", 3.6)
    turnos = [_turno(0.0, 3.0, "A"), _turno(3.0, 3.5, "B"), _turno(3.5, 8.0, "A")]
    resultado = asignar_hablantes([_con_palabras(largo1), _con_palabras(corta), _con_palabras(largo2)], turnos)
    assert [s["speaker"] for s in resultado] == ["Hablante 1", "Hablante 2", "Hablante 1"]
    assert resultado[1]["dudosa"] == {"otro": "Hablante 1", "motivo": "borde"}
    assert "dudosa" not in resultado[0] and "dudosa" not in resultado[2]


def test_dudosa_borde_no_pisa_una_marca_repartida():
    # 6 palabras pegadas a un cambio (candidata a borde) y con una palabra absorbida: queda "repartida"
    palabras = _palabras("uno dos tres cuatro cinco seis", 0.0)
    cierre = _palabras("Ya.", 2.6)
    turnos = [_turno(0.0, 1.5, "A"), _turno(1.5, 6.0, "B")]
    resultado = asignar_hablantes([_con_palabras(palabras), _con_palabras(cierre)], turnos)
    assert resultado[0]["dudosa"]["motivo"] == "repartida"


def test_sin_dudas_no_hay_clave_y_el_texto_no_cambia():
    palabras = _palabras("esto lo dice una sola persona durante un buen rato seguido.", 0.0)
    resultado = asignar_hablantes([_con_palabras(palabras)], [_turno(0.0, 6.0, "A")])
    assert len(resultado) == 1
    assert "dudosa" not in resultado[0]
    assert resultado[0]["text"] == "esto lo dice una sola persona durante un buen rato seguido."


def test_dudosa_se_descarta_si_la_otra_persona_nunca_habla_como_principal():
    # C solo tiene un turno cerca, pero ninguna frase es suya: no tendría etiqueta "Hablante N"
    palabras = _palabras("bueno entonces", 2.3)
    despues = _palabras("Hola a todos de nuevo en esta reunión.", 6.0)
    turnos = [_turno(0.0, 2.0, "A"), _turno(3.5, 4.0, "C"), _turno(5.9, 9.0, "A")]
    etiquetas = {}
    resultado = asignar_hablantes([_con_palabras(palabras), _con_palabras(despues)], turnos, etiquetas=etiquetas)
    assert all("dudosa" not in s for s in resultado)
    assert set(etiquetas) == {"A"}


def test_dudosa_nunca_coincide_con_el_hablante_de_la_frase():
    largo = _palabras("eso es lo que pasó ayer en la oficina.", 0.0)
    corta = _palabras("Sí.", 3.1)
    turnos = [_turno(0.0, 3.0, "A"), _turno(3.0, 6.0, "B")]
    for s in asignar_hablantes([_con_palabras(largo), _con_palabras(corta)], turnos):
        assert s.get("dudosa", {}).get("otro") != s["speaker"]
