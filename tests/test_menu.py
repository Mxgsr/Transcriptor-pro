# Ubicación: tests/test_menu.py
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer

from src import ajustes, cli, historial, menu


class Guion:
    """
    Responde las preguntas del menú en orden. Cada respuesta es (parte de la pregunta, respuesta):
    si la pregunta no es la esperada, o la respuesta no está entre las opciones, el test falla.
    Una respuesta KeyboardInterrupt simula Ctrl+C, y menu.Atras elegir "← Volver" (o Esc).
    """

    def __init__(self, monkeypatch):
        self.pendientes = []
        self.hechas = []  # (pregunta, opciones, defecto)
        monkeypatch.setattr(menu, "elegir", self._elegir)
        monkeypatch.setattr(menu, "si_no",
                            lambda m, defecto=True, volver=True: self._elegir(m, [True, False], defecto, volver))
        monkeypatch.setattr(menu, "texto", self._escrito)
        monkeypatch.setattr(menu, "ruta", self._escrito)

    def __call__(self, *respuestas):
        self.pendientes.extend(respuestas)
        return self

    def _siguiente(self, mensaje, volver):
        assert self.pendientes, f"Pregunta sin respuesta en el guion: {mensaje}"
        esperada, respuesta = self.pendientes.pop(0)
        assert esperada in mensaje, f"Esperaba «{esperada}» y preguntó «{mensaje}»"
        if respuesta is KeyboardInterrupt:
            raise KeyboardInterrupt
        if respuesta is menu.Atras:
            assert volver, f"«{mensaje}» no ofrece volver atrás"
            raise menu.Atras
        return respuesta

    def _elegir(self, mensaje, opciones, defecto=None, volver=True):
        valores = [o[1] if isinstance(o, tuple) else o for o in opciones]
        self.hechas.append((mensaje, opciones, defecto))
        respuesta = self._siguiente(mensaje, volver)
        assert respuesta in valores, f"«{respuesta}» no está entre las opciones de «{mensaje}»: {valores}"
        return respuesta

    def _escrito(self, mensaje, validar=None, volver=True, **kwargs):
        self.hechas.append((mensaje, None, kwargs.get("defecto")))
        respuesta = self._siguiente(mensaje, volver)
        if validar:
            assert validar(respuesta) is True, validar(respuesta)
        return respuesta

    def opciones_de(self, parte):
        return next(o for m, o, _ in self.hechas if parte in m)

    def defecto_de(self, parte):
        return next(d for m, _, d in self.hechas if parte in m)


@pytest.fixture
def guion(monkeypatch):
    g = Guion(monkeypatch)
    yield g
    assert not g.pendientes, f"Quedaron respuestas sin usar: {g.pendientes}"


@pytest.fixture
def instalado(monkeypatch):
    """Por defecto, como en el Mac de Max: diarización y corrección instaladas."""
    modulos = {"pyannote.audio": True, "mlx_lm": True}
    monkeypatch.setattr(menu, "_instalado", lambda modulo: modulos[modulo])
    return modulos


@pytest.fixture
def comandos(monkeypatch, tmp_path):
    """Simula los comandos de la CLI que corre el menú."""
    txt = tmp_path / "entrevista.blocks.txt"
    json_path = tmp_path / "entrevista.blocks.json"

    def transcribir(**opciones):
        txt.write_text("[00:00:00] Hablante 1: Hola\n", encoding="utf-8")
        con_hablantes = opciones["hablantes"]
        if con_hablantes:
            json_path.write_text(json.dumps({"audio": None, "nombres": {}, "parrafos": [
                {"start": 0, "end": 5, "text": "Hola", "speaker": "Hablante 1"},
                {"start": 5, "end": 9, "text": "Qué tal", "speaker": "Hablante 2"},
            ]}), encoding="utf-8")
        return SimpleNamespace(txt_path=txt, json_path=json_path if con_hablantes else None)

    simulados = SimpleNamespace(
        transcribir=MagicMock(side_effect=transcribir),
        corregir=MagicMock(return_value=tmp_path / "entrevista.corregido.blocks.txt"),
        poner_nombres=MagicMock(return_value=txt),
        txt=txt,
        json=json_path,
    )
    monkeypatch.setattr(cli, "ejecutar_transcripcion", simulados.transcribir)
    monkeypatch.setattr(cli, "corregir", simulados.corregir)
    monkeypatch.setattr(cli, "poner_nombres", simulados.poner_nombres)
    return simulados


@pytest.fixture
def audio(tmp_path):
    archivo = tmp_path / "mi audio.m4a"
    archivo.write_bytes(b"audio")
    return archivo


# --- Transcribir --------------------------------------------------------------

def test_transcribir_con_hablantes_y_correccion(guion, instalado, comandos, audio):
    guion(
        ("¿De dónde viene?", "archivo"),
        ("Arrastra el archivo", str(audio).replace(" ", "\\ ")),  # como lo deja la Terminal al arrastrar
        ("¿Qué modelo uso?", "turbo"),
        ("¿Identifico quién habla?", True),
        ("¿Cuántas personas hablan?", "3"),
        ("¿Corrijo el texto con IA", True),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "salir"),
    )

    assert menu.flujo_transcribir() is False

    comandos.transcribir.assert_called_once_with(
        entrada=str(audio), modelo="turbo", hablantes=True, num=3, minimo=None, idioma="es", salida=None,
        carpeta_descargas=Path("downloads"))
    comandos.corregir.assert_called_once_with(archivo=comandos.json, modelo="qwen3-8b")
    assert historial.preferencias() == {
        "origen": "archivo", "modelo": "turbo", "hablantes": True, "cuantos": "3", "corregir": True}


def test_transcribir_ofrece_lo_ultimo_que_elegiste(guion, instalado, comandos):
    historial.guardar_preferencias(origen="enlace", modelo="large", hablantes=False, corregir=True)
    guion(
        ("¿De dónde viene?", "enlace"),
        ("Pega el enlace", "https://youtu.be/abc"),
        ("¿Qué modelo uso?", "large"),
        ("¿Identifico quién habla?", False),
        ("¿Corrijo el texto con IA", False),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    assert menu.flujo_transcribir() is True

    assert guion.defecto_de("¿De dónde viene?") == "enlace"
    assert guion.defecto_de("¿Qué modelo uso?") == "large"
    assert guion.defecto_de("¿Identifico quién habla?") is False
    assert guion.defecto_de("¿Corrijo el texto") is True
    comandos.transcribir.assert_called_once_with(
        entrada="https://youtu.be/abc", modelo="large", hablantes=False, num=None, minimo=None,
        idioma="es", salida=None, carpeta_descargas=Path("downloads"))
    comandos.corregir.assert_not_called()


def test_mas_opciones_cambia_idioma_y_carpeta(guion, instalado, comandos, audio, tmp_path):
    guion(
        ("¿De dónde viene?", "archivo"),
        ("Arrastra el archivo", f'"{audio}"'),
        ("¿Qué modelo uso?", "small"),
        ("¿Identifico quién habla?", False),
        ("¿Corrijo el texto con IA", False),
        ("¿Empiezo?", "mas"),
        ("¿Qué quieres cambiar?", "idioma"),
        ("¿En qué idioma", "otro"),
        ("Código del idioma", "JA"),
        ("¿Qué quieres cambiar?", "carpeta"),
        ("Carpeta donde guardar", str(tmp_path)),
        ("¿Qué quieres cambiar?", menu.Atras),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    _, opciones = comandos.transcribir.call_args
    assert opciones["idioma"] == "ja"
    assert opciones["salida"] == tmp_path
    # El idioma no se recuerda: la próxima vez vuelve a ser español
    assert "idioma" not in historial.preferencias()


def test_cancelar_no_transcribe_ni_guarda_preferencias(guion, instalado, comandos):
    guion(
        ("¿De dónde viene?", "enlace"),
        ("Pega el enlace", "https://youtu.be/abc"),
        ("¿Qué modelo uso?", "turbo"),
        ("¿Identifico quién habla?", False),
        ("¿Corrijo el texto con IA", False),
        ("¿Empiezo?", "cancelar"),
    )

    assert menu.flujo_transcribir() is True
    comandos.transcribir.assert_not_called()
    assert historial.preferencias() == {}


def test_sin_diarizacion_ni_correccion_instaladas_no_las_pregunta(guion, instalado, comandos, capsys):
    instalado.update({"pyannote.audio": False, "mlx_lm": False})
    guion(
        ("¿De dónde viene?", "enlace"),
        ("Pega el enlace", "https://youtu.be/abc"),
        ("¿Qué modelo uso?", "turbo"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    assert comandos.transcribir.call_args.kwargs["hablantes"] is False
    assert 'uv pip install -e ".[diarizacion]"' in " ".join(capsys.readouterr().out.split())


def test_si_la_transcripcion_falla_vuelve_al_menu_sin_corregir(guion, instalado, comandos):
    comandos.transcribir.side_effect = typer.Exit(1)
    guion(
        ("¿De dónde viene?", "enlace"),
        ("Pega el enlace", "https://youtu.be/abc"),
        ("¿Qué modelo uso?", "turbo"),
        ("¿Identifico quién habla?", False),
        ("¿Corrijo el texto con IA", True),
        ("¿Empiezo?", "empezar"),
    )

    assert menu.flujo_transcribir() is True
    comandos.corregir.assert_not_called()


def test_el_modelo_del_env_aparece_aunque_no_este_en_la_lista(monkeypatch):
    opciones = menu._opciones_con_descripcion(menu.MODELOS_WHISPER, "mlx-community/mi-whisper")
    assert opciones[-1][1] == "mlx-community/mi-whisper"
    assert [valor for _, valor in opciones[:2]] == ["turbo", "large"]
    assert opciones[0][0].startswith("turbo ")


@pytest.mark.parametrize("cuantos, esperado", [
    (None, (None, None)), ("No lo sé", (None, None)), ("2", (2, None)), ("5 o más", (None, 5)),
])
def test_numero_de_hablantes(cuantos, esperado):
    assert menu.numero_de_hablantes(cuantos) == esperado


# --- Corregir, nombres y Mis transcripciones ------------------------------------

@pytest.fixture
def con_historial(comandos):
    """Una transcripción con hablantes ya hecha y anotada en el historial."""
    comandos.transcribir(hablantes=True)
    historial.registrar(comandos.txt, comandos.json, duracion=4210)
    return comandos


def test_corregir_una_del_historial(guion, instalado, con_historial):
    guion(
        ("¿Cuál quieres corregir?", 0),
        ("¿Qué modelo de IA?", "qwen3-4b"),
        ("¿Quieres revisar cada cambio", True),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_corregir()

    con_historial.corregir.assert_called_once_with(archivo=con_historial.json, modelo="qwen3-4b", revisar=True)
    etiqueta = guion.opciones_de("¿Cuál quieres corregir?")[0][0]
    assert etiqueta.startswith("entrevista · hoy ")
    assert "1 h 10 min · Hablante 1, Hablante 2" in etiqueta
    assert historial.preferencias() == {"modelo_corrector": "qwen3-4b", "revisar": True}


def test_corregir_sin_mlx_lm_explica_como_instalarlo(guion, instalado, con_historial, capsys):
    instalado["mlx_lm"] = False
    guion(("¿Cuál quieres corregir?", 0), ("¿Y ahora?", "menu"))

    menu.flujo_corregir()

    con_historial.corregir.assert_not_called()
    assert 'uv pip install -e ".[correccion]"' in " ".join(capsys.readouterr().err.split())


def test_corregir_buscando_otro_archivo_lo_anota_en_el_historial(guion, instalado, comandos, tmp_path):
    otra = tmp_path / "otra.blocks.txt"
    otra.write_text("[00:00:00] Hola\n", encoding="utf-8")
    guion(
        ("Arrastra el .blocks.json o el .blocks.txt", str(otra)),  # historial vacío: va directo a buscar
        ("¿Qué modelo de IA?", "qwen3-8b"),
        ("¿Quieres revisar cada cambio", False),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_corregir()

    comandos.corregir.assert_called_once_with(archivo=otra, modelo="qwen3-8b", revisar=False)
    assert [e["txt"] for e in historial.listar()] == [otra.resolve()]


def test_nombres_escribiendo_la_lista(guion, instalado, con_historial):
    guion(
        ("¿A cuál le cambio los nombres?", 0),
        ("¿Cómo?", "lista"),
        ("Nombres en orden de aparición", "Ana, Luis"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_nombres()

    con_historial.poner_nombres.assert_called_once_with(archivo=con_historial.json, lista="Ana, Luis", escuchar=False)


def test_nombres_escuchando(guion, instalado, con_historial):
    guion(("¿A cuál le cambio los nombres?", 0), ("¿Cómo?", "escuchar"), ("¿Y ahora?", "menu"))

    menu.flujo_nombres()

    con_historial.poner_nombres.assert_called_once_with(archivo=con_historial.json, lista=None, escuchar=True)


def test_nombres_solo_ofrece_las_que_tienen_hablantes(guion, instalado, comandos, tmp_path):
    sin_hablantes = tmp_path / "solo-texto.blocks.txt"
    sin_hablantes.write_text("[00:00:00] Hola\n", encoding="utf-8")
    historial.registrar(sin_hablantes)
    guion(("Arrastra el .blocks.json", KeyboardInterrupt))

    with pytest.raises(KeyboardInterrupt):
        menu.flujo_nombres()


def test_mis_transcripciones_vacia(guion, capsys):
    assert menu.flujo_mis_transcripciones() is True
    assert "Todavía no hay transcripciones" in capsys.readouterr().out


def test_mis_transcripciones_abrir_y_mostrar_en_carpeta(guion, instalado, con_historial, monkeypatch):
    abrir = MagicMock()
    monkeypatch.setattr(menu, "abrir", abrir)
    guion(
        ("¿Cuál?", 0),
        ("¿Qué hago con entrevista?", "abrir"),
        ("¿Algo más", "carpeta"),
        ("¿Algo más", "salir"),
    )

    assert menu.flujo_mis_transcripciones() is False

    assert abrir.call_args_list[0].args == (con_historial.txt,)
    assert abrir.call_args_list[1].args == (con_historial.txt,)
    assert abrir.call_args_list[1].kwargs == {"revelar": True}


def test_acciones_ofrecen_la_version_corregida_si_existe(guion, con_historial, tmp_path):
    (tmp_path / "entrevista.corregido.blocks.txt").write_text("[00:00:00] Hola.\n", encoding="utf-8")
    guion(("¿Y ahora?", "menu"))

    menu.acciones_sobre(con_historial.txt, con_historial.json, "¿Y ahora?")

    valores = [valor for _, valor in guion.opciones_de("¿Y ahora?")]
    assert valores[:3] == ["abrir", "abrir_corregida", "corregir"]
    assert "Corregir otra vez" in [t for t, _ in guion.opciones_de("¿Y ahora?")]


# --- Menú principal -----------------------------------------------------------

def test_menu_vuelve_tras_ctrl_c_y_sale(guion, monkeypatch, capsys):
    flujo = MagicMock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(menu, "flujo_transcribir", flujo)
    guion(
        ("¿Qué quieres hacer?", "transcribir"),
        ("¿Qué quieres hacer?", "salir"),
    )

    menu.iniciar()

    flujo.assert_called_once()
    salida = capsys.readouterr().out
    assert "Volviendo al menú" in salida
    assert "Hasta luego" in salida


def test_ctrl_c_en_el_menu_principal_sale(guion, capsys):
    guion(("¿Qué quieres hacer?", KeyboardInterrupt))

    menu.iniciar()

    assert "Hasta luego" in capsys.readouterr().out


def test_salir_desde_una_transcripcion_cierra_el_menu(guion, monkeypatch):
    monkeypatch.setattr(menu, "flujo_mis_transcripciones", lambda: False)
    guion(("¿Qué quieres hacer?", "mis"))

    menu.iniciar()


def test_error_de_un_comando_se_muestra_y_el_menu_sigue(capsys):
    def comando():
        raise typer.BadParameter("No encuentro el archivo .json: x.json")

    assert menu._ejecutar(comando) is None
    assert "No encuentro el archivo .json" in capsys.readouterr().err


# --- Utilidades ---------------------------------------------------------------

@pytest.mark.parametrize("escrito, esperado", [
    ("/Users/max/Mi\\ audio\\ (1).m4a", "/Users/max/Mi audio (1).m4a"),
    ("'/Users/max/Mi audio.m4a'", "/Users/max/Mi audio.m4a"),
    ('  "/tmp/a b.mp3"  ', "/tmp/a b.mp3"),
    ("/tmp/normal.mp3 ", "/tmp/normal.mp3"),
])
def test_limpiar_ruta(escrito, esperado):
    assert menu.limpiar_ruta(escrito) == Path(esperado)


def test_limpiar_ruta_expande_la_carpeta_personal():
    assert menu.limpiar_ruta("~/a.mp3") == Path.home() / "a.mp3"


def test_validaciones(audio, tmp_path):
    assert menu._validar_archivo(str(audio)) is True
    assert menu._validar_archivo(str(tmp_path / "no.mp3")) == "No encuentro ese archivo."
    assert "carpeta" in menu._validar_archivo(str(tmp_path))
    assert "blocks.json" in menu._validar_transcripcion(str(audio))
    assert menu._validar_enlace("https://youtu.be/x") is True
    assert menu._validar_enlace("youtu.be/x") is not True
    assert menu._validar_nombres("Ana, Luis") is True
    assert menu._validar_nombres("  ") is not True
    assert menu._validar_carpeta("") is True
    assert menu._validar_carpeta(str(audio)) is not True


def test_cuando():
    ahora = datetime(2026, 10, 8, 15, 0)
    assert menu.cuando(datetime(2026, 10, 8, 10, 42).timestamp(), ahora) == "hoy 10:42"
    assert menu.cuando(datetime(2026, 10, 7, 18, 5).timestamp(), ahora) == "ayer 18:05"
    assert menu.cuando(datetime(2026, 10, 3, 9, 0).timestamp(), ahora) == "3 oct"
    assert menu.cuando(datetime(2025, 12, 24, 9, 0).timestamp(), ahora) == "24 dic 2025"


def test_elegir_con_questionary_de_verdad():
    """Las flechas y Enter funcionan con questionary (sin terminal: entrada simulada)."""
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    opciones = [("Uno", 1), ("Dos", 2), ("Tres", 3)]
    with create_pipe_input() as entrada, create_app_session(input=entrada, output=DummyOutput()):
        entrada.send_text("\x1b[B\r")  # flecha abajo + Enter, empezando desde el valor por defecto
        assert menu.elegir("¿Cuál?", opciones, defecto=2) == 3

    with create_pipe_input() as entrada, create_app_session(input=entrada, output=DummyOutput()):
        entrada.send_text("\r")  # un valor por defecto que ya no existe se ignora
        assert menu.elegir("¿Cuál?", opciones, defecto="viejo") == 1

    with create_pipe_input() as entrada, create_app_session(input=entrada, output=DummyOutput()):
        entrada.send_text("\x03")  # Ctrl+C
        with pytest.raises(KeyboardInterrupt):
            menu.elegir("¿Cuál?", opciones)


# --- Configuración ------------------------------------------------------------

def test_configuracion_cambia_y_guarda_cada_ajuste(guion, instalado, tmp_path, capsys):
    descargas, textos = tmp_path / "Descargas YT", tmp_path / "Textos"
    guion(
        ("¿Qué quieres cambiar?", "idioma"),
        ("Idioma por defecto", "en"),
        ("¿Algo más?", "modelo"),
        ("Modelo de transcripción", "large"),
        ("¿Algo más?", "modelo_corrector"),
        ("Modelo de IA para corregir", "qwen3-4b"),
        ("¿Algo más?", "modo_hablantes"),
        ("¿Identifico quién habla", ajustes.SIEMPRE),
        ("¿Algo más?", "modo_correccion"),
        ("¿Corrijo el texto", ajustes.NUNCA),
        ("¿Algo más?", "carpeta_descargas"),
        ("Carpeta para el audio", str(descargas).replace(" ", "\\ ")),
        ("¿Algo más?", "carpeta_salida"),
        ("¿Dónde guardo", "carpeta"),
        ("Carpeta para las transcripciones", str(textos)),
        ("¿Algo más?", menu.Atras),
    )

    assert menu.flujo_configuracion() is True

    assert ajustes.valor("idioma") == "en"
    assert ajustes.valor("modelo") == "large"
    assert ajustes.valor("modelo_corrector") == "qwen3-4b"
    assert ajustes.valor("modo_hablantes") == ajustes.SIEMPRE
    assert ajustes.valor("modo_correccion") == ajustes.NUNCA
    assert ajustes.carpeta("carpeta_descargas") == descargas.resolve()
    assert ajustes.carpeta("carpeta_salida") == textos.resolve()
    assert capsys.readouterr().out.count("Guardado") == 7
    # Cada opción muestra su valor actual
    ultima = [t for t, _ in [h for h in guion.hechas if h[0] == "¿Algo más?"][-1][1]]
    assert "Idioma: Inglés" in ultima
    assert "Identificar hablantes: siempre" in ultima
    assert "Corregir al terminar: nunca" in ultima


def test_configuracion_volver_a_guardar_junto_al_audio(guion, instalado, tmp_path):
    ajustes.guardar(carpeta_salida=str(tmp_path))
    guion(
        ("¿Qué quieres cambiar?", "carpeta_salida"),
        ("¿Dónde guardo", "junto"),
        ("¿Algo más?", menu.Atras),
    )

    menu.flujo_configuracion()

    assert ajustes.carpeta("carpeta_salida") is None
    assert guion.defecto_de("¿Dónde guardo") == "carpeta"


def test_configuracion_ctrl_c_en_una_pregunta_vuelve_a_la_lista(guion, instalado):
    guion(
        ("¿Qué quieres cambiar?", "modelo"),
        ("Modelo de transcripción", KeyboardInterrupt),
        ("¿Algo más?", menu.Atras),
    )

    menu.flujo_configuracion()

    assert historial.preferencias() == {}


def test_configuracion_avisa_si_falta_instalar_algo(guion, instalado, capsys):
    instalado.update({"pyannote.audio": False, "mlx_lm": False})
    guion(
        ("¿Qué quieres cambiar?", "modo_hablantes"),
        ("¿Identifico quién habla", ajustes.SIEMPRE),
        ("¿Algo más?", menu.Atras),
    )

    menu.flujo_configuracion()

    assert 'uv pip install -e ".[diarizacion]"' in " ".join(capsys.readouterr().out.split())


def test_carpeta_de_descargas_de_fabrica_explica_donde_queda():
    assert "donde ejecutas transcriptor" in menu._texto_descargas()


def test_transcribir_respeta_la_configuracion(guion, instalado, comandos, tmp_path):
    ajustes.guardar(idioma="en", carpeta_salida=str(tmp_path / "textos"), carpeta_descargas=str(tmp_path / "yt"),
                    modo_hablantes=ajustes.SIEMPRE, modo_correccion=ajustes.NUNCA, modelo_corrector="qwen3-4b")
    historial.guardar_preferencias(hablantes=False)
    guion(
        ("¿De dónde viene?", "enlace"),
        ("Pega el enlace", "https://youtu.be/abc"),
        ("¿Qué modelo uso?", "turbo"),
        ("¿Cuántas personas hablan?", "2"),  # no pregunta si identificar: siempre
        ("¿Empiezo?", "empezar"),            # ni si corregir: nunca
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    comandos.transcribir.assert_called_once_with(
        entrada="https://youtu.be/abc", modelo="turbo", hablantes=True, num=2, minimo=None, idioma="en",
        salida=tmp_path / "textos", carpeta_descargas=tmp_path / "yt")
    comandos.corregir.assert_not_called()
    # La respuesta anterior a "¿Identifico quién habla?" se conserva para cuando vuelva a preguntar
    assert historial.preferencias()["hablantes"] is False
    assert ajustes.valor("modelo") == "turbo"


def test_transcribir_corrige_siempre_con_el_modelo_configurado(guion, instalado, comandos):
    ajustes.guardar(modo_hablantes=ajustes.NUNCA, modo_correccion=ajustes.SIEMPRE, modelo_corrector="gemma4-e4b")
    guion(
        ("¿De dónde viene?", "enlace"),
        ("Pega el enlace", "https://youtu.be/abc"),
        ("¿Qué modelo uso?", "turbo"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    assert comandos.transcribir.call_args.kwargs["hablantes"] is False
    comandos.corregir.assert_called_once_with(archivo=comandos.txt, modelo="gemma4-e4b")


def test_corta():
    assert menu.corta(Path.home() / "Descargas") == "~/Descargas"
    assert menu.corta(Path("/Volumes/Disco")) == "/Volumes/Disco"


# --- Volver atrás -------------------------------------------------------------

def test_transcribir_volver_atras_repite_la_pregunta_anterior_con_lo_respondido(guion, instalado, comandos, audio):
    guion(
        ("¿De dónde viene?", "archivo"),
        ("Arrastra el archivo", str(audio)),
        ("¿Qué modelo uso?", menu.Atras),        # me equivoqué de archivo
        ("Arrastra el archivo", menu.Atras),     # en realidad era un enlace
        ("¿De dónde viene?", "enlace"),
        ("Pega el enlace", "https://youtu.be/abc"),
        ("¿Qué modelo uso?", "small"),
        ("¿Identifico quién habla?", True),
        ("¿Cuántas personas hablan?", "2"),
        ("¿Corrijo el texto con IA", False),
        ("¿Empiezo?", menu.Atras),               # quiero revisar antes de empezar
        ("¿Corrijo el texto con IA", menu.Atras),
        ("¿Cuántas personas hablan?", menu.Atras),
        ("¿Identifico quién habla?", False),
        ("¿Corrijo el texto con IA", False),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    # Al volver, cada pregunta ofrece lo que ya se había respondido
    defectos = [(m, d) for m, _, d in guion.hechas]
    assert ("Arrastra el archivo aquí o escribe su ruta (Tab completa):", str(audio)) in defectos
    assert [d for m, d in defectos if "¿De dónde viene?" in m] == [None, "archivo"]
    assert [d for m, d in defectos if "¿Cuántas personas" in m][-1] == "2"
    assert [d for m, d in defectos if "¿Identifico" in m][-1] is True
    _, opciones = comandos.transcribir.call_args
    assert (opciones["entrada"], opciones["modelo"], opciones["hablantes"]) == ("https://youtu.be/abc", "small", False)


def test_volver_en_la_primera_pregunta_sale_del_flujo(guion, instalado, comandos):
    guion(("¿De dónde viene?", menu.Atras))

    with pytest.raises(menu.Atras):
        menu.flujo_transcribir()
    comandos.transcribir.assert_not_called()


def test_volver_se_salta_las_preguntas_que_no_se_hicieron(guion, instalado, comandos):
    ajustes.guardar(modo_hablantes=ajustes.SIEMPRE, modo_correccion=ajustes.NUNCA)
    guion(
        ("¿De dónde viene?", "enlace"),
        ("Pega el enlace", "https://youtu.be/abc"),
        ("¿Qué modelo uso?", "turbo"),
        ("¿Cuántas personas hablan?", "3"),
        ("¿Empiezo?", menu.Atras),
        ("¿Cuántas personas hablan?", menu.Atras),   # no hubo "¿Identifico quién habla?": vuelve al modelo
        ("¿Qué modelo uso?", "large"),
        ("¿Cuántas personas hablan?", "3"),
        ("¿Empiezo?", "cancelar"),
    )

    assert menu.flujo_transcribir() is True
    comandos.transcribir.assert_not_called()


def test_mas_opciones_volver_regresa_a_empiezo(guion, instalado, comandos):
    guion(
        ("¿De dónde viene?", "enlace"),
        ("Pega el enlace", "https://youtu.be/abc"),
        ("¿Qué modelo uso?", "turbo"),
        ("¿Identifico quién habla?", False),
        ("¿Corrijo el texto con IA", False),
        ("¿Empiezo?", "mas"),
        ("¿Qué quieres cambiar?", "idioma"),
        ("¿En qué idioma", menu.Atras),             # no cambia nada
        ("¿Qué quieres cambiar?", "carpeta"),
        ("Carpeta donde guardar", menu.Atras),
        ("¿Qué quieres cambiar?", menu.Atras),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    _, opciones = comandos.transcribir.call_args
    assert (opciones["idioma"], opciones["salida"]) == ("es", None)


def test_corregir_volver_desde_el_modelo_regresa_a_elegir_la_transcripcion(guion, instalado, con_historial):
    guion(
        ("¿Cuál quieres corregir?", 0),
        ("¿Qué modelo de IA?", "qwen3-4b"),
        ("¿Quieres revisar cada cambio", menu.Atras),
        ("¿Qué modelo de IA?", menu.Atras),
        ("¿Cuál quieres corregir?", 0),
        ("¿Qué modelo de IA?", "qwen3-8b"),
        ("¿Quieres revisar cada cambio", False),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_corregir()

    assert [d for m, _, d in guion.hechas if "¿Qué modelo de IA?" in m] == ["qwen3-8b", "qwen3-4b", "qwen3-8b"]
    con_historial.corregir.assert_called_once_with(archivo=con_historial.json, modelo="qwen3-8b", revisar=False)


def test_buscar_otro_archivo_y_volver_regresa_a_la_lista(guion, instalado, con_historial):
    guion(
        ("¿Cuál quieres corregir?", "buscar"),
        ("Arrastra el .blocks.json", menu.Atras),
        ("¿Cuál quieres corregir?", menu.Atras),
    )

    with pytest.raises(menu.Atras):
        menu.flujo_corregir()
    con_historial.corregir.assert_not_called()


def test_nombres_volver_desde_la_lista_de_nombres(guion, instalado, con_historial):
    guion(
        ("¿A cuál le cambio los nombres?", 0),
        ("¿Cómo?", "lista"),
        ("Nombres en orden de aparición", menu.Atras),
        ("¿Cómo?", "escuchar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_nombres()

    assert guion.defecto_de("¿Cómo?") is None
    con_historial.poner_nombres.assert_called_once_with(archivo=con_historial.json, lista=None, escuchar=True)


def test_mis_transcripciones_volver_regresa_a_la_lista(guion, instalado, con_historial):
    guion(
        ("¿Cuál?", 0),
        ("¿Qué hago con entrevista?", menu.Atras),
        ("¿Cuál?", 0),
        ("¿Qué hago con entrevista?", "menu"),
    )

    assert menu.flujo_mis_transcripciones() is True


def test_volver_desde_un_flujo_regresa_al_menu_principal(guion, capsys):
    guion(
        ("¿Qué quieres hacer?", "configuracion"),
        ("¿Qué quieres cambiar?", menu.Atras),
        ("¿Qué quieres hacer?", "mis"),          # historial vacío: avisa y vuelve
        ("¿Qué quieres hacer?", "salir"),
    )

    menu.iniciar()

    assert "Volviendo al menú" not in capsys.readouterr().out


def test_el_menu_principal_no_ofrece_volver(guion):
    guion(("¿Qué quieres hacer?", "salir"))
    menu.iniciar()
    valores = [v for _, v in guion.opciones_de("¿Qué quieres hacer?")]
    assert valores[-1] == "salir"


def _responder(teclas, pregunta):
    """Hace una pregunta real de questionary escribiendo las teclas dadas."""
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    with create_pipe_input() as entrada, create_app_session(input=entrada, output=DummyOutput()):
        entrada.send_text(teclas)
        return pregunta()


def test_volver_y_esc_con_questionary_de_verdad():
    opciones = [("Uno", 1), ("Dos", 2)]
    # "← Volver" es la última opción
    with pytest.raises(menu.Atras):
        _responder("\x1b[B\x1b[B\r", lambda: menu.elegir("¿Cuál?", opciones))
    # Esc en una lista, en un texto y en una ruta
    with pytest.raises(menu.Atras):
        _responder("\x1b", lambda: menu.elegir("¿Cuál?", opciones))
    with pytest.raises(menu.Atras):
        _responder("ho\x1b", lambda: menu.texto("¿Nombre?"))
    with pytest.raises(menu.Atras):
        _responder("/tm\x1b", lambda: menu.ruta("¿Dónde?"))
    # Sin volver no hay "← Volver": tras la última opción se vuelve a la primera
    assert _responder("\x1b[B\x1b[B\r", lambda: menu.elegir("¿Cuál?", opciones, volver=False)) == 1
    # Lo normal sigue igual
    assert _responder("hola\r", lambda: menu.texto("¿Nombre?")) == "hola"
