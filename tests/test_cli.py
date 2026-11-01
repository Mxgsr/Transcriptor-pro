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

pytestmark = pytest.mark.usefixtures("sin_red_ni_modelos_en_el_menu")


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


def test_el_resumen_desde_el_menu_no_nombra_comandos(procesar, capsys):
    from src import cli

    cli.ejecutar_transcripcion("clase.mp3", "turbo", hablantes=True, desde_menu=True)
    salida = capsys.readouterr().out
    assert "Ana (75 %), Hablante 2 (25 %)" in salida
    assert "Cambiar nombres" not in salida and "transcriptor nombres" not in salida


def test_el_resumen_desde_la_cli_sigue_mostrando_como_cambiar_nombres(procesar, capsys):
    from src import cli

    cli.ejecutar_transcripcion("clase.mp3", "turbo", hablantes=True)
    assert 'transcriptor nombres' in capsys.readouterr().out


@pytest.mark.parametrize("desde_menu, texto", [
    (True, "«Cambiar nombres de hablantes»"), (False, "transcriptor nombres -e"),
])
def test_nombres_sin_terminar_segun_de_donde_se_viene(monkeypatch, procesar, capsys, desde_menu, texto):
    from src import cli

    monkeypatch.setattr(cli, "_es_interactivo", lambda: True)
    from src import menu
    monkeypatch.setattr(menu, "elegir", MagicMock(side_effect=KeyboardInterrupt))
    cli.ejecutar_transcripcion("clase.mp3", "turbo", hablantes=True, desde_menu=desde_menu)
    assert texto in " ".join(capsys.readouterr().out.split())


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
        {"start": 30, "end": 35, "text": "Gracias por invitarme a este programa.", "speaker": "Hablante 2"},
        {"start": 35, "end": 40, "text": "Un placer.", "speaker": "Hablante 1"},
    ], json_path, audio=audio)
    return audio, json_path


@pytest.fixture
def preguntas(monkeypatch):
    """
    Simula las listas con flechas (menu.elegir) y el campo de texto (menu.texto) con respuestas en cola.
    Para elegir, la respuesta es el TEXTO de la opción ("Ponerle nombre"); "ESC" simula la tecla Esc.
    Registra cada pregunta en .hechas como (mensaje, [textos de las opciones], texto_volver).
    """
    from src import menu

    class Preguntas:
        def __init__(self):
            self.cola = []
            self.hechas = []

        def poner(self, *respuestas):
            self.cola.extend(respuestas)

    p = Preguntas()

    def elegir(mensaje, opciones, defecto=None, volver=True, texto_volver=menu.VOLVER):
        textos = [o[0] if isinstance(o, tuple) else o for o in opciones]
        p.hechas.append((mensaje, textos, texto_volver if volver else None, defecto))
        respuesta = p.cola.pop(0)
        if respuesta == "ESC" or (volver and respuesta == texto_volver):
            raise menu.Atras
        for o in opciones:
            if (o[0] if isinstance(o, tuple) else o) == respuesta:
                return o[1] if isinstance(o, tuple) else o
        raise AssertionError(f"«{respuesta}» no está entre {textos}")

    def texto(mensaje, validar=None, defecto="", volver=True):
        p.hechas.append((mensaje, "texto", None, None))
        respuesta = p.cola.pop(0)
        if respuesta == "ESC":
            raise menu.Atras
        if validar and validar(respuesta) is not True:
            raise AssertionError(f"texto no válido: {respuesta!r}")
        return respuesta

    monkeypatch.setattr(menu, "elegir", elegir)
    monkeypatch.setattr(menu, "texto", texto)
    return p


def _procesar_diarizado(monkeypatch, tmp_path):
    audio, json_path = _transcripcion_diarizada(tmp_path)
    from utils.formatters import cargar_json

    monkeypatch.setattr(procesador, "procesar_entrada", lambda *a, **k: procesador.Resultado(
        audio_path=audio, txt_path=tmp_path / "charla.blocks.txt", json_path=json_path,
        parrafos=cargar_json(json_path), duracion=40.0))
    return json_path


SI_NOMBRES = "Sí, escucharlos y ponerles nombre"


def test_al_terminar_ofrece_escuchar_y_nombrar(monkeypatch, tmp_path, escucha, preguntas):
    _procesar_diarizado(monkeypatch, tmp_path)

    # Hablante 1 tiene dos fragmentos: oye el segundo y le pone Ana. Hablante 2: Luis.
    preguntas.poner(SI_NOMBRES,
                    "Otro fragmento", "Ponerle nombre", "Ana",
                    "Ponerle nombre", "Luis")

    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d"])

    assert resultado.exit_code == 0, resultado.output
    primera = preguntas.hechas[0]
    assert primera[0] == "Se detectaron 2 hablantes. ¿Les pongo nombre?"
    assert primera[1] == [SI_NOMBRES] and primera[2] == "Ahora no"
    assert escucha["recortes"] == [(0, 10), (35, 5), (30, 5)]
    assert (tmp_path / "charla.blocks.txt").read_text(encoding="utf-8") == (
        "[00:00:00] Ana: Bienvenidos al programa.\n\n[00:00:30] Luis: Gracias por invitarme a este programa."
        "\n\n[00:00:35] Ana: Un placer."
    )
    assert "Ana (88 %), Luis (12 %)" in resultado.output
    # Los nombres quedan guardados para la próxima vez
    from src import historial
    assert set(historial.personas()) == {"Ana", "Luis"}


def test_al_terminar_se_puede_decir_ahora_no(monkeypatch, tmp_path, escucha, preguntas):
    _procesar_diarizado(monkeypatch, tmp_path)
    preguntas.poner("Ahora no")

    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d"])

    assert resultado.exit_code == 0, resultado.output
    assert escucha["reproducidos"] == []
    assert "Hablante 1 (88 %)" in resultado.output
    from src import historial
    assert historial.personas() == []


def test_esc_en_la_pregunta_inicial_es_ahora_no(monkeypatch, tmp_path, escucha, preguntas):
    _procesar_diarizado(monkeypatch, tmp_path)
    preguntas.poner("ESC")

    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d"])

    assert resultado.exit_code == 0, resultado.output
    assert "Hablante 1 (88 %)" in resultado.output


def test_sin_preguntas_o_con_nombres_no_pregunta(procesar, escucha, preguntas):
    for opciones in (["-d", "--sin-preguntas"], ["-d", "-n", "Ana"]):
        resultado = runner.invoke(app, ["transcribir", "clase.mp3", *opciones])
        assert resultado.exit_code == 0, resultado.output
        assert "Se detectaron" not in resultado.output
    assert preguntas.hechas == []


def test_sin_terminal_interactiva_no_pregunta(monkeypatch, tmp_path, preguntas):
    _procesar_diarizado(monkeypatch, tmp_path)
    # Sin la fixture `escucha`, el runner no es una terminal: cero preguntas
    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d"])

    assert resultado.exit_code == 0, resultado.output
    assert preguntas.hechas == []


def test_con_nombres_dados_se_recuerdan(procesar):
    from src import historial

    resultado = runner.invoke(app, ["transcribir", "clase.mp3", "-d", "--sin-preguntas", "-n", "Ana,Luis"])

    assert resultado.exit_code == 0, resultado.output
    assert set(historial.personas()) == {"Ana", "Luis"}


def test_un_fallo_al_recordar_no_rompe_nada(monkeypatch, procesar):
    from src import historial

    def falla(nombres):
        raise RuntimeError("disco lleno")

    monkeypatch.setattr(historial, "recordar_personas", falla)
    resultado = runner.invoke(app, ["transcribir", "clase.mp3", "-d", "--sin-preguntas", "-n", "Ana"])
    assert resultado.exit_code == 0, resultado.output


def test_nombres_escuchar(tmp_path, escucha, preguntas):
    _, json_path = _transcripcion_diarizada(tmp_path)

    # Escuchar otra vez · Ana · Dejar como está "Hablante 2"
    preguntas.poner("Escuchar otra vez", "Ponerle nombre", "Ana", "Dejar como está")
    resultado = runner.invoke(app, ["nombres", str(json_path), "-e"])

    assert resultado.exit_code == 0, resultado.output
    assert escucha["reproducidos"] == ["Hablante 1-0.wav", "Hablante 1-0.wav", "Hablante 2-0.wav"]
    assert (tmp_path / "charla.blocks.txt").read_text(encoding="utf-8").startswith(
        "[00:00:00] Ana: Bienvenidos al programa.\n\n[00:00:30] Hablante 2: Gracias")
    assert json.loads(json_path.read_text(encoding="utf-8"))["nombres"] == {"Hablante 1": "Ana"}


def test_nombres_escuchar_sin_audio_muestra_solo_texto(tmp_path, escucha, preguntas):
    audio, json_path = _transcripcion_diarizada(tmp_path)
    audio.unlink()

    preguntas.poner("Ponerle nombre", "Ana", "Ponerle nombre", "Luis")
    resultado = runner.invoke(app, ["nombres", str(json_path), "-e"])

    assert resultado.exit_code == 0, resultado.output
    assert "No encuentro el audio" in resultado.output
    assert escucha["reproducidos"] == []
    # Sin reproductor no se ofrece «Escuchar otra vez»
    assert all("Escuchar otra vez" not in opciones for _, opciones, _, _ in preguntas.hechas if opciones != "texto")


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
    assert "El detalle quedó guardado en" in resultado.output
    assert "-v" not in resultado.output


def test_sin_internet_y_modelo_no_descargado_lo_explica(monkeypatch):
    class LocalEntryNotFoundError(FileNotFoundError):
        pass

    def falla(*args, **kwargs):
        try:
            raise LocalEntryNotFoundError("Cannot find the requested files in the disk cache")
        except LocalEntryNotFoundError as e:
            raise RuntimeError("El motor falló") from e

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setattr(procesador, "procesar_entrada", falla)

    resultado = runner.invoke(app, ["transcribir", "clase.mp3"])

    assert resultado.exit_code == 1
    assert "Sin internet" in resultado.output
    assert "disk cache" not in resultado.output


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


# --- _escuchar_y_nombrar: cada camino de las listas -------------------------

def _tres_hablantes():
    return [
        {"start": 0, "end": 30, "text": "Bienvenidos.", "speaker": "Hablante 1"},
        {"start": 30, "end": 50, "text": "Gracias.", "speaker": "Hablante 2"},
        {"start": 50, "end": 60, "text": "Un placer.", "speaker": "Hablante 3"},
        {"start": 60, "end": 65, "text": "Más de lo mismo.", "speaker": "Hablante 3"},
    ]


def _nombrar(parrafos=None, actuales=None, audio="charla.mp3", sugerencias=None):
    from src import cli
    return cli._escuchar_y_nombrar(parrafos or _tres_hablantes(), actuales or {},
                                   Path(audio) if audio else None, sugerencias)


def test_elegir_una_persona_guardada(escucha, preguntas):
    from src import historial
    historial.recordar_personas(["Ana", "Luis"])
    historial.recordar_personas(["Luis"])
    preguntas.poner("Ponerle nombre", "Luis",
                    "Dejar como está", "Dejar como está")

    assert _nombrar() == {"Hablante 1": "Luis"}
    mensaje, opciones, _, _ = preguntas.hechas[1]
    assert mensaje == "¿Cómo se llama?"
    assert opciones == ["Luis", "Ana", "Otro nombre…"]  # el más usado primero


def test_las_personas_ya_asignadas_no_se_vuelven_a_ofrecer(escucha, preguntas):
    from src import historial
    historial.recordar_personas(["Ana", "Luis"])
    preguntas.poner("Ponerle nombre", "Ana",
                    "Ponerle nombre", "Luis",
                    "Dejar como está")

    assert _nombrar() == {"Hablante 1": "Ana", "Hablante 2": "Luis"}
    # Al segundo solo le queda Luis; Ana ya es el Hablante 1
    assert preguntas.hechas[3][1] == ["Luis", "Otro nombre…"]


def test_otro_nombre_y_validacion(escucha, preguntas):
    from src import cli, historial
    historial.recordar_personas(["Ana"])
    preguntas.poner("Ponerle nombre", "Otro nombre…", "Marta",
                    "Dejar como está", "Dejar como está")

    assert _nombrar() == {"Hablante 1": "Marta"}
    # Un nombre vacío no pasa la validación del campo de texto
    assert cli._validar_nombre("   ") is not True
    assert cli._validar_nombre("Marta") is True


def test_sin_personas_guardadas_va_directo_a_escribir(escucha, preguntas):
    preguntas.poner("Ponerle nombre", "Marta", "Dejar como está", "Dejar como está")

    assert _nombrar() == {"Hablante 1": "Marta"}
    assert preguntas.hechas[1][1] == "texto"


def test_esc_al_escribir_o_elegir_nombre_vuelve_a_la_lista_del_hablante(escucha, preguntas):
    from src import historial
    # Sin personas: Esc al escribir
    preguntas.poner("Ponerle nombre", "ESC", "Dejar como está", "Dejar como está", "Dejar como está")
    assert _nombrar() == {}
    assert preguntas.hechas[0][0] == preguntas.hechas[2][0] == "¿Quién es Hablante 1?"

    # Con personas: Esc en la lista de personas y en «Otro nombre…»
    historial.recordar_personas(["Ana"])
    preguntas.hechas.clear()
    preguntas.poner("Ponerle nombre", "ESC",
                    "Ponerle nombre", "Otro nombre…", "ESC",
                    "Ponerle nombre", "Ana",
                    "Dejar como está", "Dejar como está")
    assert _nombrar() == {"Hablante 1": "Ana"}


def test_misma_persona_que_une_los_dos_en_el_texto(tmp_path, escucha, preguntas):
    audio, json_path = _transcripcion_diarizada(tmp_path)
    # Hablante 1 = Ana; Hablante 2 = la misma persona que Ana
    preguntas.poner("Ponerle nombre", "Ana",
                    "Es la misma persona que…", "Ana")

    resultado = runner.invoke(app, ["nombres", str(json_path), "-e"])

    assert resultado.exit_code == 0, resultado.output
    assert preguntas.hechas[3][0] == "¿Con quién?" and preguntas.hechas[3][1] == ["Ana"]
    texto = (tmp_path / "charla.blocks.txt").read_text(encoding="utf-8")
    assert "Hablante" not in texto
    assert texto.count("Ana:") == 3
    assert json.loads(json_path.read_text(encoding="utf-8"))["nombres"] == {"Hablante 1": "Ana", "Hablante 2": "Ana"}


def test_misma_persona_no_se_ofrece_al_primero_ni_si_todos_tienen_su_nombre(escucha, preguntas):
    preguntas.poner("Dejar como está", "Dejar como está", "Dejar como está")
    _nombrar()
    assert "Es la misma persona que…" not in preguntas.hechas[0][1]
    assert "Es la misma persona que…" in preguntas.hechas[1][1]


def test_misma_persona_ofrece_el_nombre_nuevo_de_los_anteriores(escucha, preguntas):
    preguntas.poner("Ponerle nombre", "Ana",
                    "Dejar como está",
                    "Es la misma persona que…", "Ana")
    assert _nombrar() == {"Hablante 1": "Ana", "Hablante 3": "Ana"}
    # Para el Hablante 3: Ana (nueva) y Hablante 2 (sin cambiar)
    assert preguntas.hechas[-1][1] == ["Ana", "Hablante 2"]


def test_esc_en_misma_persona_vuelve_a_la_lista(escucha, preguntas):
    preguntas.poner("Dejar como está",
                    "Es la misma persona que…", "ESC",
                    "Dejar como está",
                    "Dejar como está")
    assert _nombrar() == {}
    assert preguntas.hechas[1][0] == preguntas.hechas[3][0] == "¿Quién es Hablante 2?"


def test_esc_en_la_lista_del_hablante_es_dejar_como_esta(escucha, preguntas):
    preguntas.poner("ESC", "ESC", "ESC")
    assert _nombrar() == {}
    # Era una pregunta por hablante: no se abortó todo
    assert len(preguntas.hechas) == 3
    assert preguntas.hechas[0][2] == "Dejar como está"


def test_escuchar_otra_vez_y_otro_fragmento(escucha, preguntas):
    # Hablante 3 tiene dos fragmentos
    preguntas.poner("Dejar como está", "Dejar como está",
                    "Escuchar otra vez", "Otro fragmento", "Otro fragmento", "Dejar como está")
    assert _nombrar() == {}
    assert escucha["reproducidos"] == [
        "Hablante 1-0.wav", "Hablante 2-0.wav",
        "Hablante 3-0.wav", "Hablante 3-0.wav", "Hablante 3-1.wav", "Hablante 3-0.wav"]
    assert "Otro fragmento" not in preguntas.hechas[0][1]  # Hablante 1 solo tiene uno
    assert "Otro fragmento" in preguntas.hechas[2][1]


def test_sin_audio_no_se_ofrece_escuchar_otra_vez(escucha, preguntas):
    preguntas.poner("Dejar como está", "Dejar como está", "Dejar como está")
    _nombrar(audio=None)
    assert all("Escuchar otra vez" not in o for _, o, _, _ in preguntas.hechas)


def test_poner_el_mismo_nombre_que_ya_tiene_no_cambia_nada(escucha, preguntas):
    preguntas.poner("Ponerle nombre", "Ana", "Dejar como está", "Dejar como está")
    assert _nombrar(actuales={"Hablante 1": "Ana"}) == {}


def test_sugerencia_es_la_primera_opcion_y_la_de_por_defecto(escucha, preguntas):
    preguntas.poner("Es Ana", "Dejar como está", "Ponerle nombre", "Marta")

    mapa = _nombrar(sugerencias={"Hablante 1": "Ana", "Hablante 3": "Luis"})

    assert mapa == {"Hablante 1": "Ana", "Hablante 3": "Marta"}
    primera = preguntas.hechas[0]
    assert primera[1][0] == "Es Ana" and primera[3] == "sugerido"
    assert primera[1][1] == "Ponerle nombre"
    # Sin sugerencia para el Hablante 2, la lista no cambia
    assert not preguntas.hechas[1][1][0].startswith("Es ")
    assert preguntas.hechas[2][1][0] == "Es Luis"


def test_ctrl_c_en_las_listas_sube(escucha, monkeypatch):
    from src import menu
    monkeypatch.setattr(menu, "elegir", MagicMock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        _nombrar()


def test_nombres_escuchar_recuerda_las_personas(tmp_path, escucha, preguntas):
    from src import historial
    _, json_path = _transcripcion_diarizada(tmp_path)
    preguntas.poner("Ponerle nombre", "Ana", "Dejar como está")

    resultado = runner.invoke(app, ["nombres", str(json_path), "-e"])

    assert resultado.exit_code == 0, resultado.output
    assert historial.personas() == ["Ana"]


def test_nombres_con_lista_recuerda_las_personas(tmp_path):
    from src import historial
    _, json_path = _transcripcion_diarizada(tmp_path)

    resultado = runner.invoke(app, ["nombres", str(json_path), "Ana,Luis"])

    assert resultado.exit_code == 0, resultado.output
    assert set(historial.personas()) == {"Ana", "Luis"}


def test_no_se_propone_un_nombre_ya_dado_a_otro_hablante(escucha, preguntas):
    # El Hablante 1 se llamó Ana a mano: para el Hablante 3 ya no se ofrece "Es Ana" (uniría a dos personas)
    preguntas.poner("Ponerle nombre", "Ana", "Dejar como está", "Dejar como está")

    _nombrar(sugerencias={"Hablante 3": "Ana"})

    assert "Es Ana" not in preguntas.hechas[-1][1]
    assert "Es la misma persona que…" in preguntas.hechas[-1][1]


# --- Revisar frases dudosas ------------------------------------------------------

def _con_dudosas(tmp_path, con_audio=True):
    """Una charla con dos frases dudosas (en el párrafo de Luis y en el de la tercera persona)."""
    from utils.formatters import guardar_json

    audio = tmp_path / "debate.mp3"
    if con_audio:
        audio.write_bytes(b"")
    json_path = tmp_path / "debate.blocks.json"
    guardar_json([
        {"start": 0, "end": 10, "text": "Bienvenidos a todos.", "speaker": "Hablante 1"},
        {"start": 10, "end": 20, "text": "Gracias por venir. Sí claro.", "speaker": "Hablante 2",
         "dudosas": [{"text": "Sí claro.", "start": 15, "end": 20, "otro": "Hablante 1", "motivo": "borde"}]},
        {"start": 20, "end": 30, "text": "Empecemos con el orden del día de hoy.", "speaker": "Hablante 1"},
        {"start": 30, "end": 40, "text": "Yo opino distinto sobre el tema. Eso sí.", "speaker": "Hablante 3",
         "dudosas": [{"text": "Eso sí.", "start": 36, "end": 40, "otro": "Hablante 2", "motivo": "borde"}]},
    ], json_path, audio=audio if con_audio else None, nombres={"Hablante 1": "Ana", "Hablante 2": "Luis"})
    return json_path


def _revisar(json_path):
    from src import cli, menu
    return cli._revisar_dudosas(json_path, menu)


def _parrafos_guardados(json_path):
    from utils.formatters import cargar_transcripcion
    return cargar_transcripcion(json_path)["parrafos"]


def test_revisar_mover_la_frase_a_la_otra_persona(escucha, preguntas, tmp_path, capsys):
    json_path = _con_dudosas(tmp_path)
    preguntas.poner("Es de Ana", "Terminar la revisión")

    assert _revisar(json_path) == 1

    mensaje, opciones, texto_volver, _ = preguntas.hechas[0]
    assert opciones == ["Escuchar", "Es de Ana", "Está bien (es de Luis)", "Es de otra persona…"]
    assert texto_volver == "Terminar la revisión"
    salida = capsys.readouterr().out
    assert "Frase 1 de 2" in salida and "Corregí 1 frase." in salida
    parrafos = _parrafos_guardados(json_path)
    assert (parrafos[1]["speaker"], parrafos[1]["text"]) == ("Hablante 2", "Gracias por venir.")
    assert parrafos[2]["speaker"] == "Hablante 1" and parrafos[2]["text"].startswith("Sí claro.")
    # El .txt se rehizo con los nombres
    assert "Luis: Gracias por venir." in (tmp_path / "debate.blocks.txt").read_text(encoding="utf-8")


def test_revisar_muestra_el_contexto_y_cuenta_las_frases(escucha, preguntas, tmp_path, capsys):
    json_path = _con_dudosas(tmp_path)
    preguntas.poner("Es de Ana", "Terminar la revisión")

    _revisar(json_path)

    salida = capsys.readouterr().out
    # Al mover una frase se vuelve a calcular la lista: lo que quedó corto entre dos párrafos de Ana también se propone
    assert "Frase 1 de 2" in salida and "Frase 2 de 2" in salida
    assert "Ana: Bienvenidos a todos." in salida                     # párrafo anterior
    assert "Luis: Gracias por venir. Sí claro." in salida            # párrafo de la frase
    assert "Ana: Empecemos con el orden del día de hoy." in salida   # párrafo siguiente


def test_revisar_esta_bien_guarda_y_no_se_vuelve_a_proponer(escucha, preguntas, tmp_path, capsys):
    from src import dudosas
    json_path = _con_dudosas(tmp_path)
    preguntas.poner("Está bien (es de Luis)", "Está bien (es de Hablante 3)")

    assert _revisar(json_path) == 0

    assert "Revisión guardada." in capsys.readouterr().out
    assert dudosas.buscar_dudosas(_parrafos_guardados(json_path)) == []


def test_revisar_es_de_otra_persona(escucha, preguntas, tmp_path):
    json_path = _con_dudosas(tmp_path)
    preguntas.poner("Es de otra persona…", "Hablante 3", "Terminar la revisión")

    assert _revisar(json_path) == 1

    # Solo se ofrecen los demás hablantes (no el actual ni el otro)
    assert preguntas.hechas[1][0] == "¿De quién es?" and preguntas.hechas[1][1] == ["Hablante 3"]
    parrafos = _parrafos_guardados(json_path)
    assert any(p["speaker"] == "Hablante 3" and p["text"].startswith("Sí claro.") for p in parrafos)


def test_revisar_esc_en_otra_persona_vuelve_a_la_misma_frase(escucha, preguntas, tmp_path):
    json_path = _con_dudosas(tmp_path)
    preguntas.poner("Es de otra persona…", "ESC", "Terminar la revisión")

    assert _revisar(json_path) == 0
    assert [h[0] for h in preguntas.hechas] == ["¿De quién es la frase marcada?", "¿De quién es?",
                                                 "¿De quién es la frase marcada?"]


def test_revisar_terminar_o_esc_guardan_lo_hecho(escucha, preguntas, tmp_path):
    for final in ("Terminar la revisión", "ESC"):
        json_path = _con_dudosas(tmp_path)
        preguntas.poner("Es de Ana", final)

        assert _revisar(json_path) == 1
        assert _parrafos_guardados(json_path)[1]["text"] == "Gracias por venir."


def test_revisar_terminar_sin_cambios_no_toca_el_archivo(escucha, preguntas, tmp_path):
    json_path = _con_dudosas(tmp_path)
    antes = json_path.read_bytes()
    preguntas.poner("Terminar la revisión")

    assert _revisar(json_path) == 0
    assert json_path.read_bytes() == antes


def test_revisar_ctrl_c_guarda_lo_hecho(escucha, preguntas, tmp_path, monkeypatch):
    from src import menu
    json_path = _con_dudosas(tmp_path)
    preguntas.poner("Es de Ana")
    original = menu.elegir

    def con_ctrl_c(*args, **kwargs):
        if preguntas.cola:
            return original(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(menu, "elegir", con_ctrl_c)

    assert _revisar(json_path) == 1
    assert _parrafos_guardados(json_path)[1]["text"] == "Gracias por venir."


def test_revisar_escuchar_reproduce_la_frase_y_vuelve_a_preguntar(escucha, preguntas, tmp_path):
    json_path = _con_dudosas(tmp_path)
    preguntas.poner("Escuchar", "Está bien (es de Luis)", "Terminar la revisión")

    _revisar(json_path)

    assert escucha["recortes"] == [(14.5, 6.0)]  # desde medio segundo antes hasta medio segundo después
    assert len(escucha["reproducidos"]) == 1
    # Después de escuchar pregunta lo mismo de nuevo
    assert preguntas.hechas[1][1] == preguntas.hechas[0][1]


def test_revisar_sin_audio_no_ofrece_escuchar(escucha, preguntas, tmp_path):
    json_path = _con_dudosas(tmp_path, con_audio=False)
    preguntas.poner("Terminar la revisión")

    _revisar(json_path)

    assert "Escuchar" not in preguntas.hechas[0][1]


def test_revisar_sin_frases_dudosas(escucha, preguntas, tmp_path, capsys):
    _, json_path = _transcripcion_diarizada(tmp_path)
    from utils.formatters import guardar_json, cargar_transcripcion
    guardar_json([{"start": 0, "end": 5, "text": "Hola a todos.", "speaker": "Hablante 1"}], json_path)

    assert _revisar(json_path) == 0
    assert "No hay frases dudosas." in capsys.readouterr().out
    assert preguntas.hechas == []


def _procesar_con_dudosas(monkeypatch, tmp_path):
    from utils.formatters import cargar_json
    json_path = _con_dudosas(tmp_path)
    monkeypatch.setattr(procesador, "procesar_entrada", lambda *a, **k: procesador.Resultado(
        audio_path=tmp_path / "debate.mp3", txt_path=tmp_path / "debate.blocks.txt", json_path=json_path,
        parrafos=cargar_json(json_path), duracion=40.0))
    return json_path


def test_ofrece_revisar_despues_de_poner_nombres(monkeypatch, tmp_path, escucha, preguntas):
    json_path = _procesar_con_dudosas(monkeypatch, tmp_path)
    preguntas.poner("Ahora no",
                    "Sí, revisarlas", "Es de Ana", "Terminar la revisión")

    resultado = runner.invoke(app, ["transcribir", "debate.mp3", "-d"])

    assert resultado.exit_code == 0, resultado.output
    mensajes = [h[0] for h in preguntas.hechas]
    assert "Hay 2 frases en las que dudé de quién habla. ¿Las revisamos?" in mensajes
    oferta = next(h for h in preguntas.hechas if h[0].startswith("Hay 2 frases"))
    assert oferta[2] == "Ahora no (puedes hacerlo luego desde la transcripción)"
    assert _parrafos_guardados(json_path)[1]["text"] == "Gracias por venir."


def test_se_puede_no_revisar_las_dudosas(monkeypatch, tmp_path, escucha, preguntas):
    json_path = _procesar_con_dudosas(monkeypatch, tmp_path)
    antes = json_path.read_bytes()
    preguntas.poner("Ahora no", "ESC")

    resultado = runner.invoke(app, ["transcribir", "debate.mp3", "-d"])

    assert resultado.exit_code == 0, resultado.output
    assert json_path.read_bytes() == antes


def test_sin_preguntas_no_ofrece_revisar(monkeypatch, tmp_path, escucha, preguntas):
    _procesar_con_dudosas(monkeypatch, tmp_path)

    resultado = runner.invoke(app, ["transcribir", "debate.mp3", "-d", "--sin-preguntas"])

    assert resultado.exit_code == 0, resultado.output
    assert preguntas.hechas == []
