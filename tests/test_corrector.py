# Ubicación: tests/test_corrector.py
import json
import sys
import types
from unittest.mock import MagicMock

import pytest

from src import corrector
from src.corrector import (
    APLICADA, RECHAZADA, SIN_CAMBIOS, DESCARTADA,
    Correccion, completar, contar_letras_cambiadas, corregir_parrafos, evaluar,
    guardar_correccion, leer_entrada, limpiar_respuesta, resolver_modelo, rutas_de_salida,
)


def test_resolver_modelo():
    assert resolver_modelo("qwen3-8b") == "mlx-community/Qwen3-8B-4bit"
    assert resolver_modelo("mlx-community/Otro-4bit") == "mlx-community/Otro-4bit"
    with pytest.raises(ValueError, match="qwen3-4b"):
        resolver_modelo("gpt")


@pytest.mark.parametrize("respuesta, esperado", [
    ("Hola, ¿qué tal?", "Hola, ¿qué tal?"),
    ("<think>\nveamos\n</think>\n\nHola, ¿qué tal?", "Hola, ¿qué tal?"),
    ("Texto corregido: Hola, ¿qué tal?", "Hola, ¿qué tal?"),
    ('"Hola, ¿qué tal?"', "Hola, ¿qué tal?"),
    ("«Hola, ¿qué tal?»", "Hola, ¿qué tal?"),
    ("Hola,\n¿qué   tal?\n", "Hola, ¿qué tal?"),
])
def test_limpiar_respuesta(respuesta, esperado):
    assert limpiar_respuesta(respuesta, "hola que tal") == esperado


def test_limpiar_respuesta_respeta_comillas_del_original():
    assert limpiar_respuesta('"Cita" y "otra"', '"cita" y "otra"') == '"Cita" y "otra"'


def test_tildes_mayusculas_puntuacion_y_espacios_no_cuentan_como_cambio():
    assert contar_letras_cambiadas("y como esta tu mama", "Y, ¿cómo está tu mamá?") == (0, 15)
    assert contar_letras_cambiadas("por que no", "¿Porque no?") == (0, 8)


def test_cuenta_letras_cambiadas_quitadas_y_anadidas():
    # vamoshaberquepasa -> vamosaverquepasa: sobra la h y la b pasa a v
    assert contar_letras_cambiadas("vamos haber que pasa", "vamos a ver qué pasa") == (2, 17)
    assert contar_letras_cambiadas("uno dos tres cuatro", "uno cuatro") == (7, 16)


def test_evaluar():
    assert evaluar("hola", "hola", 0.15).estado == SIN_CAMBIOS
    assert evaluar("hola que tal", "Hola, ¿qué tal?", 0.15).estado == APLICADA
    assert evaluar("hola que tal", "", 0.15).estado == RECHAZADA


def test_evaluar_permite_arreglar_una_palabra_en_parrafos_cortos():
    # Es más de un 15 % de las letras, pero en un párrafo corto arreglar una palabra es normal
    assert evaluar("si ella", "Sí, Estela.", 0.15).estado == APLICADA


def test_evaluar_acepta_correcciones_tipicas_de_whisper():
    original = "bueno vamos haber que pasa con esto por que nadie lo sabe"
    propuesta = "Bueno, vamos a ver qué pasa con esto, porque nadie lo sabe."
    assert evaluar(original, propuesta, 0.15).estado == APLICADA


def test_evaluar_rechaza_si_cambia_demasiado():
    original = " ".join(f"palabra{i}" for i in range(40))
    resumen = " ".join(f"palabra{i}" for i in range(30))  # se comió 10 de 40 (25 %)
    correccion = evaluar(original, resumen, 0.15)
    assert correccion.estado == RECHAZADA
    assert correccion.cambio > 0.15
    assert correccion.texto_final == original
    assert evaluar(original, resumen, 0.30).estado == APLICADA


def test_corregir_parrafos_pasa_el_contexto_anterior_ya_corregido():
    respuestas = {"hola que tal": "Hola, ¿qué tal?", "bien y tu": "Bien, ¿y tú?"}
    generar = MagicMock(side_effect=lambda texto, contexto: respuestas[texto])
    parrafos = [{"text": " hola que tal "}, {"text": ""}, {"text": "bien y tu"}]

    resultado = list(corregir_parrafos(parrafos, generar))

    assert [c.texto_final for c in resultado] == ["Hola, ¿qué tal?", "", "Bien, ¿y tú?"]
    assert generar.call_count == 2  # el vacío no pasa por el modelo
    assert generar.call_args_list[0].args == ("hola que tal", "")
    # Un párrafo vacío no borra el contexto
    assert generar.call_args_list[1].args == ("bien y tu", "Hola, ¿qué tal?")
    assert [c.estado for c in resultado] == [APLICADA, SIN_CAMBIOS, APLICADA]


def test_corregir_parrafos_usa_el_original_como_contexto_si_se_rechaza():
    original = " ".join(f"palabra{i}" for i in range(40))
    generar = MagicMock(side_effect=["Resumen corto.", "Segundo."])
    resultado = list(corregir_parrafos([{"text": original}, {"text": "segundo"}], generar))
    assert resultado[0].estado == RECHAZADA
    assert generar.call_args_list[1].args == ("segundo", original)


def test_completar_deja_el_resto_como_estaba():
    hechas = [Correccion("a", "A.", 0.0, APLICADA)]
    todas = completar([{"text": "a"}, {"text": " b "}], hechas)
    assert [c.texto_final for c in todas] == ["A.", "b"]


def test_cargar_generador_usa_mlx_lm_sin_pensar_y_en_temperatura_cero(monkeypatch):
    tokenizer = MagicMock()
    tokenizer.apply_chat_template.return_value = [1, 2, 3]
    tokenizer.encode.return_value = [0] * 10
    mlx_lm = types.ModuleType("mlx_lm")
    mlx_lm.load = MagicMock(return_value=("modelo", tokenizer))
    mlx_lm.generate = MagicMock(return_value="Hola.")
    sample_utils = types.ModuleType("mlx_lm.sample_utils")
    sample_utils.make_sampler = MagicMock(return_value="sampler")
    monkeypatch.setitem(sys.modules, "mlx_lm", mlx_lm)
    monkeypatch.setitem(sys.modules, "mlx_lm.sample_utils", sample_utils)

    generar = corrector.cargar_generador("mlx-community/Qwen3-8B-4bit", silencioso=False)

    assert generar("hola", "antes") == "Hola."
    mlx_lm.load.assert_called_once_with("mlx-community/Qwen3-8B-4bit")
    sample_utils.make_sampler.assert_called_once_with(temp=0.0)
    mensajes = tokenizer.apply_chat_template.call_args.args[0]
    assert "Texto a corregir:\nhola" in mensajes[0]["content"]
    assert "antes" in mensajes[0]["content"]
    assert tokenizer.apply_chat_template.call_args.kwargs["enable_thinking"] is False
    assert mlx_lm.generate.call_args.args == ("modelo", tokenizer, [1, 2, 3])
    assert mlx_lm.generate.call_args.kwargs == {"max_tokens": 84, "sampler": "sampler"}


def test_cargar_generador_sin_mlx_lm_dice_como_instalarlo(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlx_lm", None)
    with pytest.raises(RuntimeError, match=r"\[correccion\]"):
        corrector.cargar_generador("x/y")


@pytest.mark.parametrize("nombre, txt, js", [
    ("Clase.blocks.json", "Clase.corregido.blocks.txt", "Clase.corregido.blocks.json"),
    ("Clase.blocks.txt", "Clase.corregido.blocks.txt", "Clase.corregido.blocks.json"),
    ("notas.txt", "notas.corregido.blocks.txt", "notas.corregido.blocks.json"),
])
def test_rutas_de_salida(tmp_path, nombre, txt, js):
    assert rutas_de_salida(tmp_path / nombre) == (tmp_path / txt, tmp_path / js)


TXT_CON_HABLANTES = (
    "[00:00:00] Ana: hola que tal\n\n"
    "[00:00:05] Luis: bien y tu\n\n"
    "[00:01:02] Ana: Mira: te cuento"
)


def test_leer_txt_con_hablantes(tmp_path):
    ruta = tmp_path / "c.blocks.txt"
    ruta.write_text(TXT_CON_HABLANTES, encoding="utf-8")

    datos = leer_entrada(ruta)

    assert datos["origen"] == ruta
    assert datos["parrafos"] == [
        {"start": 0, "end": 5, "text": "hola que tal", "speaker": "Ana"},
        {"start": 5, "end": 62, "text": "bien y tu", "speaker": "Luis"},
        {"start": 62, "end": 62, "text": "Mira: te cuento", "speaker": "Ana"},
    ]


def test_leer_txt_sin_hablantes_no_confunde_un_dos_puntos_suelto(tmp_path):
    ruta = tmp_path / "c.blocks.txt"
    ruta.write_text("[00:00:00] Mira: esto es asi\n\n[00:00:09] Y luego otra cosa", encoding="utf-8")
    parrafos = leer_entrada(ruta)["parrafos"]
    assert parrafos[0] == {"start": 0, "end": 9, "text": "Mira: esto es asi"}
    assert "speaker" not in parrafos[1]


def test_leer_txt_que_no_es_una_transcripcion(tmp_path):
    ruta = tmp_path / "c.txt"
    ruta.write_text("Lista de la compra", encoding="utf-8")
    with pytest.raises(ValueError, match="hh:mm:ss"):
        leer_entrada(ruta)


def test_leer_entrada_prefiere_el_json_si_esta_al_lado(tmp_path):
    (tmp_path / "c.blocks.txt").write_text("[00:00:00] Ana: hola", encoding="utf-8")
    (tmp_path / "c.blocks.json").write_text(json.dumps({
        "audio": "/a/c.mp3", "nombres": {"Hablante 1": "Ana"},
        "parrafos": [{"start": 0.0, "end": 2.0, "text": " hola", "speaker": "Hablante 1"}],
    }), encoding="utf-8")

    datos = leer_entrada(tmp_path / "c.blocks.txt")

    assert datos["origen"] == tmp_path / "c.blocks.json"
    assert datos["nombres"] == {"Hablante 1": "Ana"}
    assert datos["parrafos"][0]["speaker"] == "Hablante 1"


def test_leer_entrada_errores(tmp_path):
    with pytest.raises(FileNotFoundError):
        leer_entrada(tmp_path / "no.blocks.json")
    (tmp_path / "audio.mp3").write_bytes(b"")
    with pytest.raises(ValueError, match=".blocks.json"):
        leer_entrada(tmp_path / "audio.mp3")


def test_guardar_correccion_no_toca_el_original_y_guarda_el_rastro(tmp_path):
    origen = tmp_path / "c.blocks.json"
    origen.write_text("original", encoding="utf-8")
    datos = {
        "origen": origen, "audio": "/a/c.mp3", "nombres": {"Hablante 1": "Ana"},
        "parrafos": [
            {"start": 0.0, "end": 4.0, "text": " hola que tal", "speaker": "Hablante 1"},
            {"start": 4.0, "end": 9.0, "text": "bien", "speaker": "Hablante 2"},
            {"start": 9.0, "end": 12.0, "text": "otro", "speaker": "Hablante 1"},
            {"start": 12.0, "end": 15.0, "text": "y mas", "speaker": "Hablante 2"},
        ],
    }
    correcciones = [
        Correccion("hola que tal", "Hola, ¿qué tal?", 0.0, APLICADA),
        Correccion("bien", "bien", 0.0, SIN_CAMBIOS),
        Correccion("otro", "Algo muy distinto.", 1.0, RECHAZADA),
        Correccion("y mas", "Y más.", 0.0, DESCARTADA),
    ]

    txt_path, json_path = guardar_correccion(datos, correcciones)

    assert origen.read_text(encoding="utf-8") == "original"
    assert txt_path.read_text(encoding="utf-8") == (
        "[00:00:00] Ana: Hola, ¿qué tal?\n\n"
        "[00:00:04] Hablante 2: bien\n\n"
        "[00:00:09] Ana: otro\n\n"
        "[00:00:12] Hablante 2: y mas"
    )
    guardado = json.loads(json_path.read_text(encoding="utf-8"))
    assert guardado["audio"] == "/a/c.mp3"
    assert guardado["nombres"] == {"Hablante 1": "Ana"}
    p = guardado["parrafos"]
    assert p[0] == {"start": 0.0, "end": 4.0, "text": "Hola, ¿qué tal?", "speaker": "Hablante 1",
                    "texto_original": " hola que tal"}
    assert p[1] == {"start": 4.0, "end": 9.0, "text": "bien", "speaker": "Hablante 2"}
    assert p[2]["text"] == "otro" and p[2]["correccion_no_aplicada"] == "Algo muy distinto."
    assert p[3]["text"] == "y mas" and p[3]["correccion_no_aplicada"] == "Y más."


def test_cargar_generador_fuera_de_mac_con_chip_apple_lo_explica(monkeypatch):
    from src import plataforma

    monkeypatch.setitem(sys.modules, "mlx_lm", None)
    monkeypatch.setattr(plataforma, "correccion_disponible", lambda: False)

    with pytest.raises(RuntimeError, match="solo funciona en Macs con chip Apple"):
        corrector.cargar_generador("mlx-community/Qwen3-8B-4bit")


# --- Mayúsculas al seguir una frase y exclamaciones ---

def test_no_pone_mayuscula_si_el_parrafo_sigue_la_frase_anterior():
    respuestas = {"y fuimos al": "Y fuimos al", "centro de salud. luego": "Centro de salud. Luego"}
    generar = MagicMock(side_effect=lambda texto, contexto: respuestas[texto])
    parrafos = [{"text": "y fuimos al", "speaker": "Ana"}, {"text": "centro de salud. luego", "speaker": "Ana"}]

    resultado = list(corregir_parrafos(parrafos, generar))

    assert [c.texto_final for c in resultado] == ["Y fuimos al", "centro de salud. Luego"]


def test_con_otro_hablante_o_tras_un_punto_si_pone_mayuscula():
    respuestas = {"y fuimos al": "Y fuimos al", "centro": "Centro.", "sí": "Sí."}
    generar = MagicMock(side_effect=lambda texto, contexto: respuestas[texto])
    parrafos = [{"text": "y fuimos al", "speaker": "Ana"}, {"text": "centro", "speaker": "Luis"},
                {"text": "sí", "speaker": "Luis"}]

    resultado = list(corregir_parrafos(parrafos, generar))

    assert [c.texto_final for c in resultado] == ["Y fuimos al", "Centro.", "Sí."]


def test_respeta_la_mayuscula_que_ya_tenia_el_original():
    respuestas = {"y fuimos con": "Y fuimos con", "Catalina al centro": "Catalina al centro."}
    generar = MagicMock(side_effect=lambda texto, contexto: respuestas[texto])

    resultado = list(corregir_parrafos([{"text": "y fuimos con"}, {"text": "Catalina al centro"}], generar))

    assert resultado[1].texto_final == "Catalina al centro."


@pytest.mark.parametrize("original,propuesta,esperado", [
    ("que bonito", "¿Qué bonito?", "¡Qué bonito!"),
    ("y dijo que bueno que viniste", "Y dijo: ¿qué bueno que viniste?", "Y dijo: ¡qué bueno que viniste!"),
    ("que tal como estas", "¿Qué tal? ¿Cómo estás?", "¿Qué tal? ¿Cómo estás?"),       # preguntas de verdad
    ("¿que bonito?", "¿Qué bonito?", "¿Qué bonito?"),                               # ya era pregunta
    ("que bonito no", "¿Qué bonito, no?", "¿Qué bonito, no?"),                      # busca que le den la razón
])
def test_un_que_exclamativo_no_se_vuelve_pregunta(original, propuesta, esperado):
    generar = MagicMock(return_value=propuesta)
    [correccion] = corregir_parrafos([{"text": original}], generar)
    assert correccion.propuesta == esperado


def test_las_instrucciones_piden_no_preguntar_exclamaciones():
    from src.corrector import INSTRUCCIONES
    assert "exclamación" in INSTRUCCIONES
    # Pedirle que siguiera la frase en minúscula hacía que quitara mayúsculas por todas partes
    assert "sin punto" not in INSTRUCCIONES


# --- Palabras cambiadas por otras que no suenan igual ---

@pytest.mark.parametrize("original,propuesta,esperado", [
    # Cambios que empeoran: se deja la palabra original, con la puntuación del modelo
    ("y lloro mucho", "Y llamo mucho.", "Y lloro mucho."),
    ("quiero verla otra vez", "Quiero vérala otra vez.", "Quiero verla otra vez."),
    ("aceptarla asi", "Aceptala así.", "Aceptarla así."),
    ("no reje tu vida", "No rechazo tu vida.", "No reje tu vida."),
    # Arreglos de palabras mal oídas (suenan igual o casi): se aplican
    ("vamos haber que pasa", "Vamos a ver qué pasa.", "Vamos a ver qué pasa."),
    ("valla al centro", "Vaya al centro.", "Vaya al centro."),
    ("en el cozán trabajamos", "En el COSAM trabajamos.", "En el COSAM trabajamos."),
    ("por que no viniste", "¿Porque no viniste?", "¿Porque no viniste?"),
])
def test_deshace_las_palabras_cambiadas_por_otras(original, propuesta, esperado):
    generar = MagicMock(return_value=propuesta)
    [correccion] = corregir_parrafos([{"text": original}], generar)
    assert correccion.texto_final == esperado


def test_si_solo_cambiaba_palabras_por_otras_queda_sin_cambios():
    [correccion] = corregir_parrafos([{"text": "lloro"}], MagicMock(return_value="llamo"))
    assert correccion.estado == SIN_CAMBIOS


# --- Vocabulario ---

def test_el_vocabulario_va_en_las_instrucciones():
    from src.corrector import armar_mensajes
    [mensaje] = armar_mensajes("la suyenta catalina", "", "COSAM, señorita Catalina")
    assert "escríbelo exactamente así: COSAM, señorita Catalina." in mensaje["content"]
    [sin] = armar_mensajes("hola", "")
    assert "Nombres y siglas" not in sin["content"]


@pytest.mark.parametrize("original,propuesta,esperado", [
    ("y la suyenta catalina me ayudó", "Y la señorita Catalina me ayudó.", "Y la señorita Catalina me ayudó."),
    ("estoy yendo a fosam", "Estoy yendo a COSAM.", "Estoy yendo a COSAM."),
    # Una palabra que no es del vocabulario sigue sin poder cambiarse por otra
    ("y lloro mucho", "Y llamo mucho.", "Y lloro mucho."),
])
def test_los_cambios_que_ponen_palabras_del_vocabulario_se_respetan(original, propuesta, esperado):
    generar = MagicMock(return_value=propuesta)
    [correccion] = corregir_parrafos([{"text": original}], generar, vocabulario="COSAM, OSL, FOSIS, señorita Catalina")
    assert correccion.texto_final == esperado


def test_preparar_vocabulario():
    from src.corrector import preparar_vocabulario
    assert preparar_vocabulario("  COSAM ;OSL,, cosam\nFOSIS. ") == "COSAM, OSL, FOSIS"
    assert preparar_vocabulario(None) == ""


# --- Lo que la IA no puede quitar (casos reales) ---

@pytest.mark.parametrize("original,propuesta,esperado", [
    # Palabras borradas
    ("Qué bonito escucharla.", "¿Bonito escucharla.", "¡Qué bonito escucharla!"),
    ("y entonces me dijo que sí", "Y me dijo que sí.", "Y entonces me dijo que sí."),
    # "¿Qué bueno." a medio camino
    ("Qué bueno.", "¿Qué bueno.", "¡Qué bueno!"),
    # Mayúsculas al inicio de frase
    ("Súper. ¿Y cómo influye este emprendimiento", "Súper. ¿y cómo influye este emprendimiento?",
     "Súper. ¿Y cómo influye este emprendimiento?"),
    ("Terminar mi estudio.", "terminar mi estudio.", "Terminar mi estudio."),
    ("apoya bastante Y bueno, ella", "apoya bastante. y bueno, ella", "apoya bastante. Y bueno, ella"),
    # A media frase, una palabra común sí puede ir en minúscula
    ("que era un amor Ella fue para mí", "que era un amor ella fue para mí", "que era un amor ella fue para mí"),
    # Tras puntos suspensivos la frase suele seguir
    ("porque usted... Está resfriado", "porque usted... está resfriado", "porque usted... está resfriado"),
])
def test_la_ia_no_borra_palabras_ni_mayusculas(original, propuesta, esperado):
    # Otro párrafo de la transcripción con "ella" y "está" en minúscula: son palabras comunes
    parrafos = [{"text": original}, {"text": "ella está bien"}]
    correccion, _ = corregir_parrafos(parrafos, MagicMock(side_effect=[propuesta, "ella está bien"]))
    assert correccion.texto_final == esperado


def test_un_nombre_conserva_la_mayuscula_a_media_frase():
    # "Pasán" nunca va en minúscula en la transcripción: es un nombre; "ella" sí
    parrafos = [{"text": "Yo fui a Pasán, Pasán se llama porque Ella vino"}, {"text": "y ella también"}]
    generar = MagicMock(side_effect=["yo fui a pasán, pasán se llama porque ella vino", "y ella también"])
    primera, _ = corregir_parrafos(parrafos, generar)
    assert primera.texto_final == "Yo fui a Pasán, Pasán se llama porque ella vino"


def test_la_ia_no_quita_un_nombre_del_vocabulario():
    [correccion] = corregir_parrafos([{"text": "me inscribió en el FOSIS."}], MagicMock(return_value="Me inscribió en el FOSI."),
                                     vocabulario="FOSIS")
    assert correccion.texto_final == "Me inscribió en el FOSIS."


def test_un_nombre_a_medio_arreglar_por_la_ia_se_completa():
    [correccion] = corregir_parrafos([{"text": "y con el fosi que me salió"}],
                                     MagicMock(return_value="Y con el FOSI que me salió."), vocabulario="FOSIS")
    assert correccion.texto_final == "Y con el FOSIS que me salió."


# --- Vocabulario sin IA ---

_VOCABULARIO = "COSAM, OSL, FOSIS, Señorita Catalina"


@pytest.mark.parametrize("texto,esperado", [
    ("ahora estoy yendo a Cozán, ahí también", "ahora estoy yendo a COSAM, ahí también"),
    ("la iglesia, de Cosal, y aquí", "la iglesia, de COSAM, y aquí"),
    ("se juntaron con Avanzo ASL, la iglesia", "se juntaron con Avanzo OSL, la iglesia"),
    ("me inscribió en el FOSI. Me dijo", "me inscribió en el FOSIS. Me dijo"),
    ("Y la suyenta Catalina empezó", "Y la señorita Catalina empezó"),
    ("Teotir y la Sirena Catalina me", "Teotir y la señorita Catalina me"),
    ("aunque la Sra. Catalina me", "aunque la señorita Catalina me"),
    ("Suyita Catalina me ayudó", "Señorita Catalina me ayudó"),
    # Lo que no se toca
    ("Yo nací en Santa Catalina, me", "Yo nací en Santa Catalina, me"),
    ("hay cosas que no", "hay cosas que no"),
    ("Cosas que pasan.", "Cosas que pasan."),
    ("y la señorita Catalina", "y la señorita Catalina"),
])
def test_aplicar_vocabulario(texto, esperado):
    from src.corrector import aplicar_vocabulario
    [parrafo], cambios = aplicar_vocabulario([{"text": texto}], _VOCABULARIO)
    assert parrafo["text"] == esperado
    assert cambios == (texto != esperado)


def test_aplicar_vocabulario_no_cambia_palabras_que_salen_en_minuscula():
    from src.corrector import aplicar_vocabulario
    # "Cosas" con mayúscula a media frase, pero "cosas" sale muchas veces: es una palabra común
    parrafos = [{"text": "son Cosas de la vida"}] + [{"text": "hay cosas"}] * 3
    nuevos, cambios = aplicar_vocabulario(parrafos, "COSAM")
    assert cambios == 0 and nuevos[0]["text"] == "son Cosas de la vida"


def test_aplicar_vocabulario_guarda_el_original_y_no_toca_la_entrada():
    from src.corrector import aplicar_vocabulario
    parrafos = [{"text": "voy a Cozán", "speaker": "A"}, {"text": "bien", "texto_original": "bien bien"}]
    nuevos, cambios = aplicar_vocabulario(parrafos, "COSAM", guardar_original=True)
    assert cambios == 1
    assert nuevos[0] == {"text": "voy a COSAM", "speaker": "A", "texto_original": "voy a Cozán"}
    assert nuevos[1] == {"text": "bien", "texto_original": "bien bien"}
    assert parrafos[0]["text"] == "voy a Cozán"


def test_aplicar_vocabulario_vacio():
    from src.corrector import aplicar_vocabulario
    nuevos, cambios = aplicar_vocabulario([{"text": "voy a Cozán"}], "")
    assert cambios == 0 and nuevos == [{"text": "voy a Cozán"}]
