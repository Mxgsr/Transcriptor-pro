# Ubicación: tests/test_transcriber.py
import pytest

from src.transcriber import agrupar_segmentos_en_parrafos, transcribir_audio


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


# --- agrupar_segmentos_en_parrafos ---

def test_agrupar_lista_vacia():
    assert agrupar_segmentos_en_parrafos([]) == []


def test_agrupar_un_solo_segmento():
    assert agrupar_segmentos_en_parrafos([seg(0.0, 2.0, "  Hola.  ")]) == [
        seg(0.0, 2.0, "Hola.")
    ]


def test_agrupar_une_segmentos_sin_pausa():
    segmentos = [seg(0.0, 1.0, "Hola"), seg(1.1, 2.0, "a todos."), seg(2.1, 3.0, "Bienvenidos.")]
    assert agrupar_segmentos_en_parrafos(segmentos) == [
        seg(0.0, 3.0, "Hola a todos. Bienvenidos.")
    ]


def test_agrupar_corta_por_pausa_larga():
    largo = "a" * 150
    segmentos = [seg(0.0, 5.0, largo), seg(7.0, 9.0, "Nuevo tema.")]
    assert agrupar_segmentos_en_parrafos(segmentos) == [
        seg(0.0, 5.0, largo),
        seg(7.0, 9.0, "Nuevo tema."),
    ]


def test_agrupar_pausa_larga_no_corta_si_el_parrafo_es_corto():
    # Por debajo de min_chars_for_pause_break la pausa no basta para cortar.
    corto = "a" * 149
    segmentos = [seg(0.0, 5.0, corto), seg(10.0, 12.0, "Sigue.")]
    assert agrupar_segmentos_en_parrafos(segmentos) == [
        seg(0.0, 12.0, f"{corto} Sigue.")
    ]


def test_agrupar_pausa_corta_no_corta():
    largo = "a" * 200
    segmentos = [seg(0.0, 5.0, largo), seg(6.9, 8.0, "Sigue.")]
    assert len(agrupar_segmentos_en_parrafos(segmentos)) == 1


def test_agrupar_corta_por_largo_al_terminar_oracion():
    largo = "a" * 599 + "."
    segmentos = [seg(0.0, 30.0, largo), seg(30.1, 32.0, "Otra oración.")]
    assert agrupar_segmentos_en_parrafos(segmentos) == [
        seg(0.0, 30.0, largo),
        seg(30.1, 32.0, "Otra oración."),
    ]


@pytest.mark.parametrize("signo", ["?", "!", "¿", "¡"])
def test_agrupar_corta_por_largo_con_otros_signos(signo):
    largo = "a" * 599 + signo
    segmentos = [seg(0.0, 30.0, largo), seg(30.1, 32.0, "Otra.")]
    assert len(agrupar_segmentos_en_parrafos(segmentos)) == 2


def test_agrupar_largo_sin_punto_final_no_corta():
    largo = "a" * 700
    segmentos = [seg(0.0, 30.0, largo), seg(30.1, 32.0, "continúa")]
    assert agrupar_segmentos_en_parrafos(segmentos) == [
        seg(0.0, 32.0, f"{largo} continúa")
    ]


def test_agrupar_ignora_segmentos_vacios():
    segmentos = [seg(0.0, 1.0, "Hola."), seg(1.0, 2.0, "   "), seg(2.0, 3.0, "Chao.")]
    assert agrupar_segmentos_en_parrafos(segmentos) == [seg(0.0, 3.0, "Hola. Chao.")]


def test_agrupar_descarta_parrafo_final_vacio():
    segmentos = [seg(0.0, 1.0, "")]
    assert agrupar_segmentos_en_parrafos(segmentos) == []


def test_agrupar_parametros_personalizados():
    segmentos = [seg(0.0, 1.0, "Uno."), seg(1.6, 2.0, "Dos.")]
    resultado = agrupar_segmentos_en_parrafos(
        segmentos, pause_threshold=0.5, min_chars_for_pause_break=1
    )
    assert resultado == [seg(0.0, 1.0, "Uno."), seg(1.6, 2.0, "Dos.")]


# --- transcribir_audio (Whisper mockeado) ---

def test_transcribir_archivo_inexistente(tmp_path, modelo_whisper):
    with pytest.raises(FileNotFoundError):
        transcribir_audio(tmp_path / "no_existe.mp3", model_name="tiny")
    modelo_whisper.load_model.assert_not_called()


def test_transcribir_devuelve_segmentos(tmp_path, modelo_whisper):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"")
    segmentos = [seg(0.0, 1.0, "Hola.")]
    modelo_whisper.transcribe.return_value = {"text": "Hola.", "segments": segmentos}

    assert transcribir_audio(audio, model_name="tiny") == segmentos
    modelo_whisper.load_model.assert_called_once_with("tiny", device="cpu")
    modelo_whisper.transcribe.assert_called_once_with(str(audio), language="es", verbose=False)


def test_transcribir_respeta_idioma(tmp_path, modelo_whisper):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"")
    modelo_whisper.transcribe.return_value = {"text": "", "segments": [seg(0, 1, "Hi.")]}

    transcribir_audio(audio, model_name="tiny", language="en")
    assert modelo_whisper.transcribe.call_args.kwargs["language"] == "en"


def test_transcribir_sin_segmentos_devuelve_texto_completo(tmp_path, modelo_whisper):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"")
    modelo_whisper.transcribe.return_value = {"text": "  Todo junto.  ", "segments": []}

    assert transcribir_audio(audio, model_name="tiny") == [seg(0.0, 0.0, "Todo junto.")]


def test_transcribir_propaga_error_al_cargar_modelo(tmp_path, modelo_whisper):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"")
    modelo_whisper.load_model.side_effect = RuntimeError("modelo no encontrado")

    with pytest.raises(RuntimeError, match="modelo no encontrado"):
        transcribir_audio(audio, model_name="inexistente")


def test_transcribir_propaga_error_del_motor(tmp_path, modelo_whisper):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"")
    modelo_whisper.transcribe.side_effect = RuntimeError("fallo")

    with pytest.raises(RuntimeError, match="fallo"):
        transcribir_audio(audio, model_name="tiny")
