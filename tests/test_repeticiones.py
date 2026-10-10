# Ubicación: tests/test_repeticiones.py
import pytest

from src.repeticiones import limpiar_parrafos, limpiar_segmentos, quitar_repeticiones


@pytest.mark.parametrize("antes, despues", [
    # Bucles reales de una transcripción
    ("y me dijo, ¿qué tal? ¿Qué tal? ¿Qué tal? ¿Qué tal? ¿Qué tal?", "y me dijo, ¿qué tal?"),
    ("Todo lo que usted sueña se le cumpla. " + "Un error. " * 29 + "orgullosa de la mujer",
     "Todo lo que usted sueña se le cumpla. Un error. orgullosa de la mujer"),
    ("pijamas de pola y y y y y y y", "pijamas de pola y"),
    ("explicarme y... Bueno... Bueno... Bueno... Bueno... empezamos", "explicarme y... Bueno... empezamos"),
    ("me he visto en la casa, me he visto en la casa, me he visto en la casa, como estoy",
     "me he visto en la casa, como estoy"),
])
def test_quita_los_bucles(antes, despues):
    assert quitar_repeticiones(antes) == despues


@pytest.mark.parametrize("texto", [
    "Sí, sí, sí, porque yo era totalmente diferente.",  # una palabra 3 veces: habla real
    "Hola, Laura. Hola, Laura. ¿Cómo estás?",            # una frase 2 veces
    "Terrible. Terrible. No, estuve más de un año.",
    "",
])
def test_respeta_las_repeticiones_naturales(texto):
    assert quitar_repeticiones(texto) == texto


def test_ignora_tildes_mayusculas_y_puntuacion_al_comparar():
    assert quitar_repeticiones("Qué tal, que tal. ¿QUE TAL? Que tal") == "Qué tal,"


def test_limpiar_segmentos_deja_uno_de_un_bucle_repartido_en_segmentos():
    segmentos = [
        {"start": 0, "end": 2, "text": " Hola."},
        *[{"start": 2 + i, "end": 3 + i, "text": " ¿Qué tal?", "words": []} for i in range(5)],
        {"start": 8, "end": 9, "text": " Bien."},
    ]
    limpios = limpiar_segmentos(segmentos)
    assert [s["text"] for s in limpios] == ["Hola.", "¿Qué tal?", "Bien."]
    assert limpios[1]["start"] == 2
    assert segmentos[1]["text"] == " ¿Qué tal?"  # no cambia los originales


def test_limpiar_segmentos_respeta_dos_seguidos_y_quita_las_palabras_de_un_texto_limpiado():
    segmentos = [
        {"start": 0, "end": 1, "text": "Sí.", "words": [{"word": " Sí.", "start": 0, "end": 1}]},
        {"start": 1, "end": 2, "text": "Sí.", "words": [{"word": " Sí.", "start": 1, "end": 2}]},
        {"start": 2, "end": 5, "text": "Gracias. Gracias. Gracias. Gracias.", "words": [{"word": " Gracias."}] * 4},
    ]
    limpios = limpiar_segmentos(segmentos)
    assert [s["text"] for s in limpios] == ["Sí.", "Sí.", "Gracias."]
    assert "words" in limpios[0]
    assert "words" not in limpios[2]


def test_limpiar_parrafos_guarda_el_original_si_se_pide():
    parrafos = [
        {"start": 0, "end": 1, "text": "Gracias. Gracias. Gracias. Gracias.", "speaker": "Hablante 1"},
        {"start": 1, "end": 2, "text": "De nada."},
    ]
    limpios = limpiar_parrafos(parrafos, guardar_original=True)
    assert limpios[0] == {"start": 0, "end": 1, "text": "Gracias.", "speaker": "Hablante 1",
                          "texto_original": "Gracias. Gracias. Gracias. Gracias."}
    assert "texto_original" not in limpios[1]
    assert "texto_original" not in limpiar_parrafos(parrafos)[0]
