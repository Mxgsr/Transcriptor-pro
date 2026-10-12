# Ubicación: tests/test_cli.py
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from src import procesador
from src.cli import app, _duracion, _texto_hablantes

runner = CliRunner()


@pytest.fixture(autouse=True)
def restaurar_logging():
    """La CLI reconfigura el logging raíz; lo dejamos como estaba para los demás tests."""
    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    yield
    raiz.handlers[:] = handlers
    raiz.setLevel(nivel)


@pytest.fixture
def procesar(monkeypatch, tmp_path):
    """Simula procesar_entrada: anuncia sus pasos y devuelve un resultado."""
    def fake(entrada, modelo, al_avanzar, al_progresar=None, **kwargs):
        al_avanzar("Transcribiendo")
        diarizado = kwargs.get("diarizar")
        return procesador.Resultado(
            audio_path=tmp_path / "clase.mp3",
            txt_path=tmp_path / "clase.blocks.txt",
            json_path=tmp_path / "clase.blocks.json" if diarizado else None,
            parrafos=[
                {"start": 0, "end": 30, "text": "Hola", "speaker": "Ana"},
                {"start": 30, "end": 40, "text": "Qué tal", "speaker": "Hablante 2"},
            ] if diarizado else [{"start": 0, "end": 40, "text": "Hola"}],
            duracion=108.0,
        )

    mock = MagicMock(side_effect=fake)
    monkeypatch.setattr(procesador, "procesar_entrada", mock)
    return mock


def test_sin_argumentos_muestra_la_ayuda():
    resultado = runner.invoke(app, [])
    assert "transcribir" in resultado.output
    assert "nombres" in resultado.output


def test_transcribir_pasa_las_opciones(procesar, tmp_path):
    resultado = runner.invoke(app, [
        "transcribir", "clase.mp3", "-m", "small", "-i", "en", "-o", str(tmp_path / "salida"),
    ])

    assert resultado.exit_code == 0, resultado.output
    args, kwargs = procesar.call_args
    assert args == ("clase.mp3", "small")
    assert kwargs["diarizar"] is False
    assert kwargs["nombres"] == {}
    assert kwargs["idioma"] == "en"
    assert kwargs["salida"] == tmp_path / "salida"
    assert kwargs["silenciar_motores"] is True
    assert "✓ Transcribiendo" in resultado.output
    assert "Listo" in resultado.output
    assert "1 min 48 s" in resultado.output
    assert "Hablantes" not in resultado.output


def test_transcribir_usa_el_modelo_por_defecto(procesar, monkeypatch):
    from src import config
    resultado = runner.invoke(app, ["transcribir", "clase.mp3"])
    assert resultado.exit_code == 0, resultado.output
    assert procesar.call_args.args[1] == config.DEFAULT_MODEL


def test_transcribir_con_hablantes_muestra_reparto_y_como_renombrar(procesar):
    resultado = runner.invoke(app, ["transcribir", "clase.mp3", "-d", "--num", "2", "-n", "Ana"])

    assert resultado.exit_code == 0, resultado.output
    kwargs = procesar.call_args.kwargs
    assert kwargs["diarizar"] is True
    assert kwargs["num_hablantes"] == 2
    assert kwargs["nombres"] == {"Hablante 1": "Ana"}
    assert "Ana (75 %), Hablante 2 (25 %)" in resultado.output
    assert "transcriptor nombres" in resultado.output
    assert "Activé" not in resultado.output


@pytest.mark.parametrize("opciones", [["--nombres", "Ana,Luis"], ["--num", "2"], ["--min", "1"], ["--max", "3"]])
def test_opciones_de_hablantes_activan_la_diarizacion_avisando(procesar, opciones):
    resultado = runner.invoke(app, ["transcribir", "clase.mp3", *opciones])

    assert resultado.exit_code == 0, resultado.output
    assert procesar.call_args.kwargs["diarizar"] is True
    assert "Activé la identificación de hablantes" in resultado.output


def test_fallo_de_hablantes_termina_con_aviso_y_la_transcripcion(monkeypatch, tmp_path):
    def falla_hablantes(entrada, modelo, al_avanzar, al_fallar, **kwargs):
        al_avanzar("Transcribiendo")
        al_avanzar("Identificando hablantes")
        al_fallar("expected np.ndarray (got array)")
        return procesador.Resultado(
            audio_path=tmp_path / "clase.mp3", txt_path=tmp_path / "clase.blocks.txt", json_path=None,
            parrafos=[{"start": 0, "end": 40, "text": "Hola"}], duracion=40.0,
            error_hablantes="expected np.ndarray (got array)",
        )

    monkeypatch.setattr(procesador, "procesar_entrada", falla_hablantes)

    resultado = runner.invoke(app, ["transcribir", "clase.mp3", "-d"])

    assert resultado.exit_code == 0, resultado.output
    assert "✓ Transcribiendo" in resultado.output
    assert "✗ Identificando hablantes" in resultado.output
    assert "Listo, sin hablantes" in resultado.output
    assert "se guardó sin ellos" in resultado.output
    assert "transcriptor nombres" not in resultado.output


def test_muestra_barra_con_porcentaje_y_audio_transcrito(monkeypatch, tmp_path):
    def con_progreso(entrada, modelo, al_avanzar, al_progresar, **kwargs):
        al_avanzar("Descargando audio")
        al_progresar(6_200_000, 12_400_000, "bytes")
        al_avanzar("Transcribiendo")
        al_progresar(750.0, 2530.0, "audio")
        raise RuntimeError("corte para ver el estado a medio camino")

    monkeypatch.setattr(procesador, "procesar_entrada", con_progreso)

    resultado = runner.invoke(app, ["transcribir", "clase.mp3"])

    assert "✓ Descargando audio" in resultado.output
    assert "100%" in resultado.output
    assert "✗ Transcribiendo" in resultado.output
    assert "30%" in resultado.output
    assert "12:30 / 42:10" in resultado.output


def test_con_detalle_no_se_captura_el_progreso(procesar):
    runner.invoke(app, ["transcribir", "clase.mp3", "-v"])
    assert procesar.call_args.kwargs["al_progresar"] is None


def test_sin_detalle_se_ocultan_los_avisos_de_pyannote(procesar):
    import warnings

    with warnings.catch_warnings(record=True) as capturados:
        warnings.simplefilter("always")
        runner.invoke(app, ["transcribir", "clase.mp3"])
        warnings.warn_explicit("std(): degrees of freedom is <= 0", UserWarning,
                               "pooling.py", 103, module="pyannote.audio.models.blocks.pooling")
        warnings.warn_explicit("otro aviso", UserWarning, "x.py", 1, module="src.algo")

    assert [str(w.message) for w in capturados] == ["otro aviso"]


@pytest.fixture
def escucha(monkeypatch):
    """Terminal interactiva simulada: registra qué fragmentos se recortan y reproducen."""
    import src.cli as cli

    monkeypatch.setattr(cli, "_es_interactivo", lambda: True)
    monkeypatch.setattr(cli.fragmentos, "comando_reproductor", lambda: ["afplay"])
    registro = {"recortes": [], "reproducidos": []}

    def extraer(audio, inicio, duracion, destino):
        registro["recortes"].append((inicio, duracion))
        destino.write_bytes(b"")
        return destino

    class ReproductorFalso:
        def __init__(self, comando):
            pass

        def reproducir(self, archivo):
            registro["reproducidos"].append(archivo.name)

        def detener(self):
            pass

    monkeypatch.setattr(cli.fragmentos, "extraer_fragmento", extraer)
    monkeypatch.setattr(cli.fragmentos, "Reproductor", ReproductorFalso)
    return registro


def _transcripcion_diarizada(tmp_path):
    from utils.formatters import guardar_json

    audio = tmp_path / "charla.mp3"
    audio.write_bytes(b"")
    json_path = tmp_path / "charla.blocks.json"
    guardar_json([
        {"start": 0, "end": 30, "text": "Bienvenidos al programa.", "speaker": "Hablante 1"},
        {"start": 30, "end": 35, "text": "Gracias por invitarme.", "speaker": "Hablante 2"},
        {"start": 35, "end": 40, "text": "Un placer.", "speaker": "Hablante 1"},
    ], json_path, audio=audio)
    return audio, json_path


def test_al_terminar_ofrece_escuchar_y_nombrar(monkeypatch, tmp_path, escucha):
    audio, json_path = _transcripcion_diarizada(tmp_path)
    from utils.formatters import cargar_json

    def fake(entrada, modelo, al_avanzar, **kwargs):
        al_avanzar("Transcribiendo")
        return procesador.Resultado(audio_path=audio, txt_path=tmp_path / "charla.blocks.txt", json_path=json_path,
                                    parrafos=cargar_json(json_path), duracion=40.0)

    monkeypatch.setattr(procesador, "procesar_entrada", fake)

    # s: sí quiero escuchar · Ana · o: otro fragmento · Luis
    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d"], input="s\nAna\no\nLuis\n")

    assert resultado.exit_code == 0, resultado.output
    assert "Se detectaron 2 hablante(s)" in resultado.output
    assert escucha["recortes"] == [(0, 10), (30, 5)]
    assert (tmp_path / "charla.blocks.txt").read_text(encoding="utf-8") == (
        "[00:00:00] Ana: Bienvenidos al programa.\n\n[00:00:30] Luis: Gracias por invitarme."
        "\n\n[00:00:35] Ana: Un placer."
    )
    assert "Ana (88 %), Luis (12 %)" in resultado.output
    assert "No hay más fragmentos" in resultado.output


def test_al_terminar_se_puede_decir_que_no(monkeypatch, tmp_path, escucha):
    audio, json_path = _transcripcion_diarizada(tmp_path)
    from utils.formatters import cargar_json

    monkeypatch.setattr(procesador, "procesar_entrada", lambda *a, **k: procesador.Resultado(
        audio_path=audio, txt_path=tmp_path / "charla.blocks.txt", json_path=json_path,
        parrafos=cargar_json(json_path), duracion=40.0))

    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d"], input="n\n")

    assert resultado.exit_code == 0, resultado.output
    assert escucha["reproducidos"] == []
    assert "Hablante 1 (88 %)" in resultado.output


def test_sin_preguntas_o_con_nombres_no_pregunta(procesar, escucha):
    for opciones in (["-d", "--sin-preguntas"], ["-d", "-n", "Ana"]):
        resultado = runner.invoke(app, ["transcribir", "clase.mp3", *opciones])
        assert resultado.exit_code == 0, resultado.output
        assert "Se detectaron" not in resultado.output


def test_nombres_escuchar(tmp_path, escucha):
    _, json_path = _transcripcion_diarizada(tmp_path)

    # r: repetir · Ana · Enter: dejar "Hablante 2"
    resultado = runner.invoke(app, ["nombres", str(json_path), "-e"], input="r\nAna\n\n")

    assert resultado.exit_code == 0, resultado.output
    assert escucha["reproducidos"] == ["Hablante 1-0.wav", "Hablante 1-0.wav", "Hablante 2-0.wav"]
    assert (tmp_path / "charla.blocks.txt").read_text(encoding="utf-8").startswith(
        "[00:00:00] Ana: Bienvenidos al programa.\n\n[00:00:30] Hablante 2: Gracias")
    assert json.loads(json_path.read_text(encoding="utf-8"))["nombres"] == {"Hablante 1": "Ana"}


def test_nombres_escuchar_sin_audio_muestra_solo_texto(tmp_path, escucha):
    audio, json_path = _transcripcion_diarizada(tmp_path)
    audio.unlink()

    resultado = runner.invoke(app, ["nombres", str(json_path), "-e"], input="Ana\nLuis\n")

    assert resultado.exit_code == 0, resultado.output
    assert "No encuentro el audio" in resultado.output
    assert escucha["reproducidos"] == []


def test_nombres_escuchar_con_lista_es_error(tmp_path, escucha):
    _, json_path = _transcripcion_diarizada(tmp_path)
    resultado = runner.invoke(app, ["nombres", str(json_path), "Ana", "-e"])
    assert resultado.exit_code == 2


def test_nombres_invalidos_es_error_de_uso(procesar):
    resultado = runner.invoke(app, ["transcribir", "clase.mp3", "--nombres", "x=Ana"])
    assert resultado.exit_code == 2
    procesar.assert_not_called()


def test_error_muestra_recuadro_y_sale_con_1(monkeypatch):
    monkeypatch.setattr(procesador, "procesar_entrada", MagicMock(side_effect=FileNotFoundError("No se encontró el audio")))

    resultado = runner.invoke(app, ["transcribir", "no_existe.mp3"])

    assert resultado.exit_code == 1
    assert "No se encontró el audio" in resultado.output
    assert "-v" in resultado.output


def test_error_marca_el_paso_que_fallo(monkeypatch):
    def falla(entrada, modelo, al_avanzar, **kwargs):
        al_avanzar("Transcribiendo")
        raise RuntimeError("boom")

    monkeypatch.setattr(procesador, "procesar_entrada", falla)

    resultado = runner.invoke(app, ["transcribir", "clase.mp3"])

    assert resultado.exit_code == 1
    assert "✗ Transcribiendo" in resultado.output


def test_detalle_muestra_pasos_sin_animacion_y_motores(procesar):
    resultado = runner.invoke(app, ["transcribir", "clase.mp3", "-v"])

    assert resultado.exit_code == 0, resultado.output
    assert procesar.call_args.kwargs["silenciar_motores"] is False
    assert "▸ Transcribiendo" in resultado.output


def test_nombres_reescribe_el_txt(tmp_path):
    json_path = tmp_path / "charla.blocks.json"
    json_path.write_text(
        '[{"start": 0, "end": 1, "text": "Hola", "speaker": "Hablante 1"},'
        ' {"start": 1, "end": 2, "text": "Qué tal", "speaker": "Hablante 2"}]',
        encoding="utf-8",
    )

    resultado = runner.invoke(app, ["nombres", str(json_path), "2=Luis,1=Ana"])

    assert resultado.exit_code == 0, resultado.output
    assert (tmp_path / "charla.blocks.txt").read_text(encoding="utf-8") == (
        "[00:00:00] Ana: Hola\n\n[00:00:01] Luis: Qué tal"
    )
    assert "Ana (50 %), Luis (50 %)" in resultado.output


def test_nombres_sin_lista_rehace_el_txt_con_lo_editado_en_el_json(tmp_path):
    json_path = tmp_path / "charla.blocks.json"
    json_path.write_text(
        '[{"start": 0, "end": 1, "text": "Hola", "speaker": "Ana"},'
        ' {"start": 1, "end": 2, "text": "Qué tal", "speaker": "Luis"},'
        ' {"start": 2, "end": 3, "text": "Bien", "speaker": "Hablante 3"}]',
        encoding="utf-8",
    )
    (tmp_path / "charla.blocks.txt").write_text("versión vieja", encoding="utf-8")

    resultado = runner.invoke(app, ["nombres", str(json_path)])

    assert resultado.exit_code == 0, resultado.output
    assert (tmp_path / "charla.blocks.txt").read_text(encoding="utf-8") == (
        "[00:00:00] Ana: Hola\n\n[00:00:01] Luis: Qué tal\n\n[00:00:02] Hablante 3: Bien"
    )
    assert "actualizada desde el .json" in resultado.output


def test_nombres_con_json_roto_explica_donde(tmp_path):
    json_path = tmp_path / "charla.blocks.json"
    json_path.write_text('[{"start": 0, "end": 1, "text": "Hola" "speaker": "Ana"}]', encoding="utf-8")

    resultado = runner.invoke(app, ["nombres", str(json_path)])

    assert resultado.exit_code == 1
    assert "no es un JSON válido (línea 1" in resultado.output


def test_nombres_con_archivo_inexistente(tmp_path):
    resultado = runner.invoke(app, ["nombres", str(tmp_path / "no.blocks.json"), "Ana"])
    assert resultado.exit_code == 2


@pytest.mark.parametrize("segundos, texto", [(3, "3 s"), (108, "1 min 48 s"), (3725, "1 h 02 min")])
def test_duracion(segundos, texto):
    assert _duracion(segundos) == texto


def test_texto_hablantes_sin_hablantes():
    assert _texto_hablantes([{"start": 0, "end": 1, "text": "Hola"}]) == "ninguno detectado"


# --- corregir ---

@pytest.fixture
def modelo_falso(monkeypatch):
    """Simula el modelo de corrección: corrige según un diccionario y registra con qué se cargó."""
    from src import corrector

    registro = {"repo": None, "respuestas": {}}

    def cargar(repo, silencioso=True, vocabulario=""):
        registro["repo"] = repo
        registro["vocabulario"] = vocabulario
        return lambda texto, contexto: registro["respuestas"].get(texto, texto)

    monkeypatch.setattr(corrector, "cargar_generador", cargar)
    monkeypatch.setattr(corrector, "modelo_descargado", lambda repo: True)
    return registro


def test_corregir_guarda_aparte_y_resume(tmp_path, modelo_falso):
    _, json_path = _transcripcion_diarizada(tmp_path)
    original = json_path.read_text(encoding="utf-8")
    modelo_falso["respuestas"] = {"Gracias por invitarme.": "Gracias por invitarme, de verdad."}

    resultado = runner.invoke(app, ["corregir", str(json_path), "-m", "qwen3-4b"])

    assert resultado.exit_code == 0, resultado.output
    assert modelo_falso["repo"] == "mlx-community/Qwen3-4B-4bit"
    assert "✓ Corrigiendo" in resultado.output
    assert "1 de 3 párrafos" in resultado.output
    assert json_path.read_text(encoding="utf-8") == original
    corregido = tmp_path / "charla.corregido.blocks.txt"
    assert "[00:00:30] Hablante 2: Gracias por invitarme, de verdad." in corregido.read_text(encoding="utf-8")
    assert (tmp_path / "charla.corregido.blocks.json").exists()


def test_corregir_quita_las_repeticiones_antes_de_la_ia(tmp_path, modelo_falso, monkeypatch):
    from src import corrector
    from utils.formatters import guardar_json, cargar_json

    json_path = tmp_path / "charla.blocks.json"
    bucle = "Gracias. " * 20 + "Pero lo que tengo ahora es por mi esfuerzo."
    guardar_json([{"start": 0, "end": 30, "text": bucle, "speaker": "Hablante 1"}], json_path)
    vistos = []
    monkeypatch.setattr(corrector, "cargar_generador",
                        lambda repo, silencioso=True, vocabulario="": lambda texto, contexto: vistos.append(texto) or texto)

    resultado = runner.invoke(app, ["corregir", str(json_path)])

    assert resultado.exit_code == 0, resultado.output
    assert vistos == ["Gracias. Pero lo que tengo ahora es por mi esfuerzo."]
    assert "quitadas en 1 párrafo" in resultado.output
    corregido = cargar_json(tmp_path / "charla.corregido.blocks.json")[0]
    assert corregido["text"] == "Gracias. Pero lo que tengo ahora es por mi esfuerzo."
    assert corregido["texto_original"] == bucle


def test_corregir_usa_el_modelo_por_defecto(tmp_path, modelo_falso):
    _, json_path = _transcripcion_diarizada(tmp_path)
    resultado = runner.invoke(app, ["corregir", str(json_path)])
    assert resultado.exit_code == 0, resultado.output
    assert modelo_falso["repo"] == "mlx-community/Qwen3-8B-4bit"


def test_corregir_usa_el_modelo_de_la_configuracion(tmp_path, modelo_falso):
    from src import ajustes
    ajustes.guardar(modelo_corrector="qwen3-4b")
    _, json_path = _transcripcion_diarizada(tmp_path)
    resultado = runner.invoke(app, ["corregir", str(json_path)])
    assert resultado.exit_code == 0, resultado.output
    assert modelo_falso["repo"] == "mlx-community/Qwen3-4B-4bit"


def test_corregir_avisa_de_los_parrafos_rechazados(tmp_path, modelo_falso):
    _, json_path = _transcripcion_diarizada(tmp_path)
    modelo_falso["respuestas"] = {"Bienvenidos al programa.": "Hoy hablaremos de algo completamente distinto."}

    resultado = runner.invoke(app, ["corregir", str(json_path), "--max-cambio", "20"])

    assert resultado.exit_code == 0, resultado.output
    assert "1 párrafo cambiaba demasiado" in resultado.output
    assert "0:00" in resultado.output
    texto = (tmp_path / "charla.corregido.blocks.txt").read_text(encoding="utf-8")
    assert "Bienvenidos al programa." in texto


def test_corregir_revisar_pregunta_cada_cambio(tmp_path, modelo_falso, monkeypatch):
    import src.cli as cli

    monkeypatch.setattr(cli, "_es_interactivo", lambda: True)
    _, json_path = _transcripcion_diarizada(tmp_path)
    modelo_falso["respuestas"] = {
        "Bienvenidos al programa.": "¡Bienvenidos al programa!",
        "Un placer.": "Un placer, de verdad.",
    }

    resultado = runner.invoke(app, ["corregir", str(json_path), "-r"], input="\nn\n")

    assert resultado.exit_code == 0, resultado.output
    assert "2 párrafos con cambios" in resultado.output
    assert "1 de 3 párrafos" in resultado.output
    assert "Descartados" in resultado.output
    texto = (tmp_path / "charla.corregido.blocks.txt").read_text(encoding="utf-8")
    assert "¡Bienvenidos al programa!" in texto
    assert "Un placer.\n" not in texto and texto.endswith("Un placer.")


def test_corregir_revisar_sin_terminal_es_error(tmp_path, modelo_falso):
    _, json_path = _transcripcion_diarizada(tmp_path)
    resultado = runner.invoke(app, ["corregir", str(json_path), "-r"])
    assert resultado.exit_code == 2
    assert "terminal interactiva" in resultado.output


def test_corregir_interrumpido_guarda_lo_hecho(tmp_path, modelo_falso, monkeypatch):
    from src import corrector

    _, json_path = _transcripcion_diarizada(tmp_path)

    def cargar(repo, silencioso=True, vocabulario=""):
        respuestas = iter(["¡Bienvenidos al programa!"])

        def generar(texto, contexto):
            try:
                return next(respuestas)
            except StopIteration:
                raise KeyboardInterrupt
        return generar

    monkeypatch.setattr(corrector, "cargar_generador", cargar)

    resultado = runner.invoke(app, ["corregir", str(json_path)])

    assert resultado.exit_code == 0, resultado.output
    assert "Interrumpido" in resultado.output
    assert "solo los primeros 1" in resultado.output
    texto = (tmp_path / "charla.corregido.blocks.txt").read_text(encoding="utf-8")
    assert texto.startswith("[00:00:00] Hablante 1: ¡Bienvenidos al programa!")
    assert "Gracias por invitarme." in texto


def test_corregir_modelo_desconocido_es_error_de_uso(tmp_path, modelo_falso):
    _, json_path = _transcripcion_diarizada(tmp_path)
    resultado = runner.invoke(app, ["corregir", str(json_path), "-m", "gpt"])
    assert resultado.exit_code == 2
    assert "Modelo desconocido" in resultado.output


def test_corregir_archivo_inexistente(tmp_path, modelo_falso):
    resultado = runner.invoke(app, ["corregir", str(tmp_path / "no.blocks.json")])
    assert resultado.exit_code == 1
    assert "No se encontró" in resultado.output


def test_corregir_avisa_cuando_descarga_el_modelo(tmp_path, modelo_falso, monkeypatch):
    from src import corrector

    monkeypatch.setattr(corrector, "modelo_descargado", lambda repo: False)
    _, json_path = _transcripcion_diarizada(tmp_path)
    resultado = runner.invoke(app, ["corregir", str(json_path)])
    assert "Descargando modelo" in resultado.output


def test_sin_argumentos_en_una_terminal_abre_el_menu(monkeypatch):
    from src import cli, menu
    iniciar = MagicMock()
    monkeypatch.setattr(cli, "_es_interactivo", lambda: True)
    monkeypatch.setattr(menu, "iniciar", iniciar)

    resultado = runner.invoke(app, [])

    assert resultado.exit_code == 0, resultado.output
    iniciar.assert_called_once()


def test_transcribir_anota_en_el_historial(procesar, tmp_path):
    from src import historial
    (tmp_path / "clase.blocks.txt").write_text("[00:00:00] Hola\n", encoding="utf-8")

    resultado = runner.invoke(app, ["transcribir", "clase.mp3"])

    assert resultado.exit_code == 0, resultado.output
    [entrada] = historial.listar()
    assert entrada["txt"] == (tmp_path / "clase.blocks.txt").resolve()
    assert entrada["duracion"] == 108.0


def test_transcribir_usa_la_configuracion(procesar, tmp_path):
    from src import ajustes
    ajustes.guardar(modelo="turbo", idioma="en", carpeta_salida=str(tmp_path / "textos"),
                    carpeta_descargas=str(tmp_path / "audios"))

    resultado = runner.invoke(app, ["transcribir", "https://youtu.be/abc"])

    assert resultado.exit_code == 0, resultado.output
    args, kwargs = procesar.call_args
    assert args[1] == "turbo"
    assert kwargs["idioma"] == "en"
    assert kwargs["salida"] == tmp_path / "textos"
    assert kwargs["carpeta_descargas"] == tmp_path / "audios"


def test_las_opciones_ganan_a_la_configuracion(procesar, tmp_path):
    from src import ajustes
    ajustes.guardar(modelo="turbo", idioma="en", carpeta_salida=str(tmp_path / "textos"))

    resultado = runner.invoke(app, ["transcribir", "clase.mp3", "-m", "tiny", "-i", "pt", "-o", str(tmp_path / "otra")])

    assert resultado.exit_code == 0, resultado.output
    args, kwargs = procesar.call_args
    assert (args[1], kwargs["idioma"], kwargs["salida"]) == ("tiny", "pt", tmp_path / "otra")


def test_corregir_usa_el_vocabulario(tmp_path, modelo_falso):
    from src import ajustes
    _, json_path = _transcripcion_diarizada(tmp_path)
    ajustes.guardar(vocabulario="FOSIS")

    resultado = runner.invoke(app, ["corregir", str(json_path)])
    assert resultado.exit_code == 0, resultado.output
    assert modelo_falso["vocabulario"] == "FOSIS"
    assert "Vocabulario: FOSIS" in resultado.output

    resultado = runner.invoke(app, ["corregir", str(json_path), "--vocabulario", "COSAM ;OSL,, cosam"])
    assert resultado.exit_code == 0, resultado.output
    assert modelo_falso["vocabulario"] == "COSAM, OSL"

    # Vacío: sin vocabulario esta vez, aunque haya uno en la configuración
    resultado = runner.invoke(app, ["corregir", str(json_path), "--vocabulario", ""])
    assert resultado.exit_code == 0, resultado.output
    assert modelo_falso["vocabulario"] == ""


def test_corregir_arregla_los_nombres_del_vocabulario_sin_ia(tmp_path, modelo_falso):
    from utils.formatters import guardar_json
    json_path = tmp_path / "charla.blocks.json"
    guardar_json([
        {"start": 0, "end": 30, "text": "Ahora voy a Cozán, y con la suyenta Catalina.", "speaker": "Hablante 1"},
        {"start": 30, "end": 35, "text": "Qué bien.", "speaker": "Hablante 2"},
    ], json_path, audio=None)

    resultado = runner.invoke(app, ["corregir", str(json_path), "--vocabulario", "COSAM, señorita Catalina"])
    assert resultado.exit_code == 0, resultado.output
    assert "2 nombres corregidos" in resultado.output
    corregido = json.loads((tmp_path / "charla.corregido.blocks.json").read_text(encoding="utf-8"))
    primero = corregido["parrafos"][0]
    assert primero["text"] == "Ahora voy a COSAM, y con la señorita Catalina."
    assert primero["texto_original"] == "Ahora voy a Cozán, y con la suyenta Catalina."
