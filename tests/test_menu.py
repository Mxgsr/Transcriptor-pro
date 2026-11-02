# Ubicación: tests/test_menu.py
import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pytest
import typer

from src import ajustes, cli, historial, menu

pytestmark = pytest.mark.usefixtures("sin_red_ni_modelos_en_el_menu")


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

    def _elegir(self, mensaje, opciones, defecto=None, volver=True, texto_volver=None):
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
    """Por defecto, como en el Mac de Max: diarización instalada."""
    modulos = {"pyannote.audio": True}
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
        poner_nombres=MagicMock(return_value=txt),
        txt=txt,
        json=json_path,
    )
    monkeypatch.setattr(cli, "ejecutar_transcripcion", simulados.transcribir)
    monkeypatch.setattr(cli, "poner_nombres", simulados.poner_nombres)
    return simulados


@pytest.fixture
def audio(tmp_path):
    archivo = tmp_path / "mi audio.m4a"
    archivo.write_bytes(b"audio")
    return archivo


# --- Transcribir --------------------------------------------------------------

def test_transcribir_con_hablantes(guion, instalado, comandos, audio):
    ajustes.guardar(modelo="turbo")
    guion(
        ("Arrastra el archivo o pega el enlace", str(audio).replace(" ", "\\ ")),  # como lo deja la Terminal al arrastrar
        ("¿Identifico quién habla?", "3"),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "salir"),
    )

    assert menu.flujo_transcribir() is False

    comandos.transcribir.assert_called_once_with(
        entrada=str(audio), modelo="turbo", hablantes=True, num=3, minimo=None, idioma="es", salida=None,
        carpeta_descargas=Path("downloads"), desde_menu=True,
        titulo="Reunión de prueba", fecha=ANY)
    assert historial.preferencias() == {"modelo": "turbo", "hablantes": True, "cuantos": "3"}


def test_transcribir_ofrece_lo_ultimo_que_elegiste(guion, instalado, comandos):
    # "origen" es de una versión anterior: se ignora sin romper
    historial.guardar_preferencias(origen="enlace", modelo="large", hablantes=False)
    guion(
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),
        ("¿Identifico quién habla?", menu.NO_IDENTIFICAR),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "mas"),
        ("¿Qué quieres cambiar?", "modelo"),
        ("¿Qué modelo uso?", "large"),
        ("¿Qué quieres cambiar?", menu.Atras),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    assert menu.flujo_transcribir() is True

    assert guion.defecto_de("¿Identifico quién habla?") == menu.NO_IDENTIFICAR
    assert guion.defecto_de("¿Qué modelo uso?") == "large"
    comandos.transcribir.assert_called_once_with(
        entrada="https://youtu.be/abc", modelo="large", hablantes=False, num=None, minimo=None,
        idioma="es", salida=None, carpeta_descargas=Path("downloads"), desde_menu=True,
        titulo="Reunión de prueba", fecha=ANY)


def test_mas_opciones_cambia_idioma_y_carpeta(guion, instalado, comandos, audio, tmp_path):
    guion(
        ("Arrastra el archivo o pega el enlace", f'"{audio}"'),
        ("¿Identifico quién habla?", menu.NO_IDENTIFICAR),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "mas"),
        ("¿Qué quieres cambiar?", "modelo"),
        ("¿Qué modelo uso?", "small"),
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
    assert opciones["modelo"] == "small"
    # Modelo e idioma son solo para esta vez: el de Configuración (el que usa el Grabador) no cambia
    assert "modelo" not in historial.preferencias()
    assert ajustes.valor("modelo") != "small"
    assert "idioma" not in historial.preferencias()


def test_cancelar_no_transcribe_ni_guarda_preferencias(guion, instalado, comandos):
    guion(
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),
        ("¿Identifico quién habla?", menu.NO_IDENTIFICAR),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "cancelar"),
    )

    assert menu.flujo_transcribir() is True
    comandos.transcribir.assert_not_called()
    assert historial.preferencias() == {}


def test_sin_diarizacion_instalada_no_pregunta_por_hablantes(guion, instalado, comandos, capsys):
    instalado.update({"pyannote.audio": False})
    guion(
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    assert comandos.transcribir.call_args.kwargs["hablantes"] is False
    # Al transcribir no se avisa de instalaciones: eso queda en Configuración
    salida = capsys.readouterr().out
    assert "instalador" not in salida and "uv pip" not in salida


def test_si_la_transcripcion_falla_vuelve_al_menu(guion, instalado, comandos):
    comandos.transcribir.side_effect = typer.Exit(1)
    guion(
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),
        ("¿Identifico quién habla?", menu.NO_IDENTIFICAR),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "empezar"),
    )

    assert menu.flujo_transcribir() is True


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


def test_un_solo_campo_para_archivo_o_enlace(audio, tmp_path):
    validar = menu._validar_archivo_o_enlace
    assert validar("https://youtu.be/x") is True
    assert validar(str(audio)) is True
    assert validar("   ") is not True
    assert validar("youtu.be/x") == "No encuentro ese archivo."
    assert "carpeta" in validar(str(tmp_path))


def test_el_enlace_se_usa_tal_cual_y_el_archivo_se_limpia(guion, instalado, comandos, audio):
    ajustes.guardar(modo_hablantes=ajustes.NUNCA)
    guion(
        ("Arrastra el archivo o pega el enlace", f"'{audio}'"),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )
    menu.flujo_transcribir()
    assert comandos.transcribir.call_args.kwargs["entrada"] == str(audio)


def test_hablantes_preguntar_ofrece_no_identificar_y_recuerda(guion, instalado, comandos):
    historial.guardar_preferencias(hablantes=True, cuantos="4")
    guion(
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),
        ("¿Identifico quién habla?", "5 o más"),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )
    menu.flujo_transcribir()
    valores = [v for _, v in guion.opciones_de("¿Identifico")]
    assert valores == [menu.NO_IDENTIFICAR, menu.NO_LO_SE, "2", "3", "4", "5 o más"]
    assert guion.defecto_de("¿Identifico") == "4"
    kw = comandos.transcribir.call_args.kwargs
    assert (kw["hablantes"], kw["num"], kw["minimo"]) == (True, None, 5)
    assert historial.preferencias()["hablantes"] is True
    assert historial.preferencias()["cuantos"] == "5 o más"


def test_hablantes_siempre_solo_pregunta_cuantos(guion, instalado, comandos):
    ajustes.guardar(modo_hablantes=ajustes.SIEMPRE)
    guion(
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),
        ("¿Cuántas personas hablan?", menu.NO_LO_SE),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )
    menu.flujo_transcribir()
    assert menu.NO_IDENTIFICAR not in guion.opciones_de("¿Cuántas")
    kw = comandos.transcribir.call_args.kwargs
    assert (kw["hablantes"], kw["num"], kw["minimo"]) == (True, None, None)


def test_hablantes_nunca_no_pregunta(guion, instalado, comandos):
    ajustes.guardar(modo_hablantes=ajustes.NUNCA)
    guion(
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )
    menu.flujo_transcribir()
    assert comandos.transcribir.call_args.kwargs["hablantes"] is False


def test_elegir_transcripcion_con_hablantes_acepta_el_txt_si_existe_el_json(guion, comandos, tmp_path):
    comandos.transcribir(hablantes=True)
    assert menu._validar_con_hablantes(str(comandos.txt)) is True
    assert menu._validar_con_hablantes(str(comandos.json)) is True
    solo = tmp_path / "solo.blocks.txt"
    solo.write_text("[00:00:00] Hola\n", encoding="utf-8")
    assert "hablantes" in menu._validar_con_hablantes(str(solo))
    guion(("Arrastra la transcripción", str(comandos.txt)))
    assert menu.elegir_transcripcion("¿Cuál?", solo_con_hablantes=True) == comandos.json


def test_el_menu_no_menciona_comandos_ni_archivos_tecnicos(guion, comandos, con_historial):
    guion(("¿A cuál le cambio los nombres?", 0))
    guion(("¿Cómo?", "lista"), ("Nombres en orden de aparición", "Ana, Luis"), ("¿Y ahora?", "menu"))
    menu.flujo_nombres()
    assert [v for _, v in guion.opciones_de("¿Cómo?")] == ["escuchar", "lista"]


# --- Nombres y Mis transcripciones ------------------------------------

@pytest.fixture
def con_historial(comandos):
    """Una transcripción con hablantes ya hecha y anotada en el historial."""
    comandos.transcribir(hablantes=True)
    historial.registrar(comandos.txt, comandos.json, duracion=4210)
    return comandos


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
    guion(("Arrastra la transcripción", KeyboardInterrupt))

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
    assert ".blocks.txt" in menu._validar_transcripcion(str(audio))
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
        ("¿Algo más?", "modo_hablantes"),
        ("¿Identifico quién habla", ajustes.SIEMPRE),
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
    assert ajustes.valor("modo_hablantes") == ajustes.SIEMPRE
    assert ajustes.carpeta("carpeta_descargas") == descargas.resolve()
    assert ajustes.carpeta("carpeta_salida") == textos.resolve()
    assert capsys.readouterr().out.count("Guardado") == 5
    # Cada opción muestra su valor actual
    ultima = [t for t, _ in [h for h in guion.hechas if h[0] == "¿Algo más?"][-1][1]]
    assert "Idioma: Inglés" in ultima
    assert "Identificar hablantes: siempre" in ultima


def test_configuracion_sin_internet(guion, instalado, monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    guion(
        ("¿Qué quieres cambiar?", "sin_internet"),
        ("¿Uso solo los modelos ya descargados?", True),
        ("¿Algo más?", menu.Atras),
    )

    menu.flujo_configuracion()

    assert ajustes.valor("sin_internet") is True
    # Se aplica al momento, sin tener que volver a abrir el programa
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert guion.defecto_de("¿Uso solo los modelos ya descargados?") is False
    ultima = [t for t, _ in [h for h in guion.hechas if h[0] == "¿Algo más?"][-1][1]]
    assert "Sin internet: sí" in ultima


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
    instalado.update({"pyannote.audio": False})
    guion(
        ("¿Qué quieres cambiar?", "modo_hablantes"),
        ("¿Identifico quién habla", ajustes.SIEMPRE),
        ("¿Algo más?", menu.Atras),
    )

    menu.flujo_configuracion()

    salida = " ".join(capsys.readouterr().out.split())
    assert "falta un componente. Vuelve a ejecutar el instalador." in salida
    assert "uv pip" not in salida


def test_carpeta_de_descargas_de_fabrica_explica_donde_queda():
    assert "donde ejecutas transcriptor" in menu._texto_descargas()


def test_transcribir_respeta_la_configuracion(guion, instalado, comandos, tmp_path):
    ajustes.guardar(idioma="en", carpeta_salida=str(tmp_path / "textos"), carpeta_descargas=str(tmp_path / "yt"),
                    modo_hablantes=ajustes.SIEMPRE, modelo="turbo")
    historial.guardar_preferencias(hablantes=False)
    guion(
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),
        ("¿Cuántas personas hablan?", "2"),  # no pregunta si identificar: siempre
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    comandos.transcribir.assert_called_once_with(
        entrada="https://youtu.be/abc", modelo="turbo", hablantes=True, num=2, minimo=None, idioma="en",
        salida=tmp_path / "textos", carpeta_descargas=tmp_path / "yt", desde_menu=True,
        titulo="Reunión de prueba", fecha=ANY)
    # La respuesta anterior a "¿Identifico quién habla?" se conserva para cuando vuelva a preguntar
    assert historial.preferencias()["hablantes"] is False
    assert ajustes.valor("modelo") == "turbo"


def test_corta():
    assert menu.corta(Path.home() / "Descargas") == "~/Descargas"
    assert menu.corta(Path("/Volumes/Disco")) == "/Volumes/Disco"


# --- Volver atrás -------------------------------------------------------------

def test_transcribir_volver_atras_repite_la_pregunta_anterior_con_lo_respondido(guion, instalado, comandos, audio):
    guion(
        ("Arrastra el archivo o pega el enlace", str(audio)),
        ("¿Identifico quién habla?", "2"),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", menu.Atras),               # quiero revisar antes de empezar
        ("¿Cómo se llama esta reunión?", menu.Atras),
        ("¿Identifico quién habla?", menu.Atras),
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),  # en realidad era un enlace
        ("¿Identifico quién habla?", menu.NO_IDENTIFICAR),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    # Al volver, cada pregunta ofrece lo que ya se había respondido
    defectos = [(m, d) for m, _, d in guion.hechas]
    assert [d for m, d in defectos if "Arrastra el archivo" in m] == ["", str(audio)]
    assert [d for m, d in defectos if "¿Identifico" in m] == ["No lo sé", "2", "2"]
    _, opciones = comandos.transcribir.call_args
    assert (opciones["entrada"], opciones["hablantes"]) == ("https://youtu.be/abc", False)


def test_volver_en_la_primera_pregunta_sale_del_flujo(guion, instalado, comandos):
    guion(("Arrastra el archivo o pega el enlace", menu.Atras))

    with pytest.raises(menu.Atras):
        menu.flujo_transcribir()
    comandos.transcribir.assert_not_called()


def test_volver_se_salta_las_preguntas_que_no_se_hicieron(guion, instalado, comandos):
    ajustes.guardar(modo_hablantes=ajustes.NUNCA)
    guion(
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", menu.Atras),   # vuelve al nombre
        ("¿Cómo se llama esta reunión?", menu.Atras),   # no hubo pregunta de hablantes: vuelve al archivo
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/otro"),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "cancelar"),
    )

    assert menu.flujo_transcribir() is True
    comandos.transcribir.assert_not_called()


def test_mas_opciones_volver_regresa_a_empiezo(guion, instalado, comandos):
    guion(
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),
        ("¿Identifico quién habla?", menu.NO_IDENTIFICAR),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "mas"),
        ("¿Qué quieres cambiar?", "modelo"),
        ("¿Qué modelo uso?", menu.Atras),           # no cambia nada
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
    assert (opciones["idioma"], opciones["salida"], opciones["modelo"]) == ("es", None, ajustes.valor("modelo"))


def test_buscar_otro_archivo_y_volver_regresa_a_la_lista(guion, instalado, con_historial):
    guion(
        ("¿A cuál le cambio los nombres?", "buscar"),
        ("Arrastra la transcripción", menu.Atras),
        ("¿A cuál le cambio los nombres?", menu.Atras),
    )

    with pytest.raises(menu.Atras):
        menu.flujo_nombres()
    con_historial.poner_nombres.assert_not_called()


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


def test_elegir_con_texto_de_volver_propio():
    """«Dejar como está» hace de «← Volver» (y de Esc) en las preguntas de nombres de hablantes."""
    opciones = [("Ponerle nombre", 1)]
    with pytest.raises(menu.Atras):
        _responder("\x1b[B\r", lambda: menu.elegir("¿Quién?", opciones, texto_volver="Dejar como está"))
    assert _responder("\r", lambda: menu.elegir("¿Quién?", opciones, texto_volver="Dejar como está")) == 1


def test_en_mac_intel_no_ofrece_instalar_hablantes(guion, instalado, comandos, capsys, monkeypatch):
    from src import plataforma

    instalado.update({"pyannote.audio": False})
    monkeypatch.setattr(plataforma, "hablantes_disponible", lambda: False)
    guion(
        ("Arrastra el archivo o pega el enlace", "https://youtu.be/abc"),
        ("¿Cómo se llama esta reunión?", "Reunión de prueba"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    # Al transcribir no se avisa; el motivo se da en Configuración
    assert "uv pip install" not in capsys.readouterr().out
    guion(("¿Qué quieres cambiar?", "modo_hablantes"), ("¿Identifico quién habla", ajustes.SIEMPRE),
          ("¿Algo más?", menu.Atras))
    menu.flujo_configuracion()
    salida = " ".join(capsys.readouterr().out.split())
    assert "no está disponible en este computador" in salida
    assert "uv pip install" not in salida and "instalador" not in salida


def test_limpiar_ruta_en_windows_respeta_las_barras(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")

    assert str(menu.limpiar_ruta(r"C:\Users\max\audio.m4a")) == str(Path(r"C:\Users\max\audio.m4a"))
    assert str(menu.limpiar_ruta(r'"C:\Users\max\Mi audio.m4a"')) == str(Path(r"C:\Users\max\Mi audio.m4a"))




# --- Nombre de la reunión (fecha de grabación) -------------------------------------

def test_fecha_de_grabacion_usa_la_mas_antigua_entre_creacion_y_modificacion(tmp_path, monkeypatch):
    from datetime import date

    archivo = tmp_path / "a.m4a"
    archivo.write_bytes(b"x")
    antigua = datetime(2026, 10, 30, 9, 0).timestamp()
    reciente = datetime(2026, 11, 1, 9, 0).timestamp()

    class Info:  # como el stat de un Mac: se copió el archivo (creación nueva), la modificación se conserva
        st_birthtime, st_mtime, st_ctime = reciente, antigua, reciente

    monkeypatch.setattr(Path, "stat", lambda self: Info())
    assert menu.fecha_de_grabacion(str(archivo)) == date(2026, 10, 30)

    Info.st_birthtime, Info.st_mtime = antigua, reciente  # creación más antigua que la modificación
    assert menu.fecha_de_grabacion(str(archivo)) == date(2026, 10, 30)


def test_fecha_de_grabacion_sin_birthtime_usa_la_modificacion(tmp_path):
    from datetime import date

    archivo = tmp_path / "a.m4a"
    archivo.write_bytes(b"x")
    os.utime(archivo, (0, datetime(2026, 5, 4, 12, 0).timestamp()))

    assert menu.fecha_de_grabacion(str(archivo)) == date(2026, 5, 4)


def test_fecha_de_grabacion_de_un_enlace_o_archivo_ausente_es_hoy(tmp_path):
    from datetime import date

    assert menu.fecha_de_grabacion("https://youtu.be/abc") == date.today()
    assert menu.fecha_de_grabacion(str(tmp_path / "no existe.mp3")) == date.today()


def test_separar_fecha_y_titulo():
    from datetime import date

    propuesta = date(2026, 10, 30)
    assert menu.separar_fecha_y_titulo("Reunión de equipo", propuesta) == (propuesta, "Reunión de equipo")
    assert menu.separar_fecha_y_titulo("2026-09-01 Cierre", propuesta) == (date(2026, 9, 1), "Cierre")
    assert menu.separar_fecha_y_titulo("2026-09-01", propuesta) == (date(2026, 9, 1), "Reunión")
    assert menu.separar_fecha_y_titulo("  ", propuesta) == (propuesta, "Reunión")
    # Una fecha imposible no es fecha: queda como parte del título
    assert menu.separar_fecha_y_titulo("2026-13-45 Algo", propuesta) == (propuesta, "2026-13-45 Algo")


def test_el_paso_del_nombre_propone_la_fecha_de_grabacion(guion, instalado, comandos, audio):
    os.utime(audio, (0, datetime(2026, 10, 30, 12, 0).timestamp()))
    guion(
        ("Arrastra el archivo o pega el enlace", str(audio)),
        ("¿Identifico quién habla?", menu.NO_IDENTIFICAR),
        ("¿Cómo se llama esta reunión?", "2026-10-30 Reunión"),   # Enter: acepta el valor por defecto
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    assert guion.defecto_de("¿Cómo se llama esta reunión?") == "2026-10-30 Reunión"
    opciones = comandos.transcribir.call_args.kwargs
    assert (opciones["titulo"], opciones["fecha"].isoformat()) == ("Reunión", "2026-10-30")


def test_el_paso_del_nombre_respeta_la_fecha_que_escribe_el_usuario(guion, instalado, comandos, audio, capsys):
    guion(
        ("Arrastra el archivo o pega el enlace", str(audio)),
        ("¿Identifico quién habla?", menu.NO_IDENTIFICAR),
        ("¿Cómo se llama esta reunión?", "2025-01-15 Planificación"),
        ("¿Empiezo?", "empezar"),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    opciones = comandos.transcribir.call_args.kwargs
    assert (opciones["titulo"], opciones["fecha"].isoformat()) == ("Planificación", "2025-01-15")
    assert "2025-01-15 Planificación" in " ".join(capsys.readouterr().out.split())  # el resumen muestra el nombre


def test_el_nombre_escrito_se_ofrece_de_nuevo_al_volver(guion, instalado, comandos, audio):
    guion(
        ("Arrastra el archivo o pega el enlace", str(audio)),
        ("¿Identifico quién habla?", menu.NO_IDENTIFICAR),
        ("¿Cómo se llama esta reunión?", "Mi reunión"),
        ("¿Empiezo?", menu.Atras),
        ("¿Cómo se llama esta reunión?", menu.Atras),
        ("¿Identifico quién habla?", menu.NO_IDENTIFICAR),
        ("¿Cómo se llama esta reunión?", "Mi reunión"),
        ("¿Empiezo?", "cancelar"),
    )

    menu.flujo_transcribir()

    defectos = [d for m, _, d in guion.hechas if "¿Cómo se llama" in m]
    assert defectos[1] == "Mi reunión" and defectos[2] == "Mi reunión"


# --- Copiar al portapapeles --------------------------------------------------------

def test_copiar_transcripcion_copia_el_txt_tal_cual(tmp_path, monkeypatch, capsys):
    txt = tmp_path / "x.blocks.txt"
    contenido = "# Reunión\nFecha: 30 de octubre de 2026\n\n[00:00:00] Ana: ¿Qué tal? Ñandú, canción"
    txt.write_text(contenido, encoding="utf-8")
    copiar = MagicMock(return_value=True)
    monkeypatch.setattr(menu.aviso, "copiar_al_portapapeles", copiar)

    assert menu.copiar_transcripcion(txt) is True

    copiar.assert_called_once_with(contenido)
    assert "Copiada. Puedes pegarla en Claude para hacer la minuta." in capsys.readouterr().out


def test_copiar_transcripcion_avisa_si_no_se_pudo(tmp_path, monkeypatch, capsys):
    txt = tmp_path / "x.blocks.txt"
    txt.write_text("hola", encoding="utf-8")
    monkeypatch.setattr(menu.aviso, "copiar_al_portapapeles", MagicMock(return_value=False))

    assert menu.copiar_transcripcion(txt) is False

    salida = capsys.readouterr()
    assert "Copiada" not in salida.out
    assert "abrirla y copiarla a mano" in (salida.err + salida.out).replace("\n", " ")


def test_copiar_transcripcion_de_un_archivo_que_no_existe_avisa(tmp_path, monkeypatch):
    copiar = MagicMock(return_value=True)
    monkeypatch.setattr(menu.aviso, "copiar_al_portapapeles", copiar)

    assert menu.copiar_transcripcion(tmp_path / "no existe.txt") is False
    copiar.assert_not_called()


def test_acciones_ofrece_copiar_despues_de_abrir(guion, instalado, con_historial, monkeypatch):
    copiar = MagicMock(return_value=True)
    monkeypatch.setattr(menu.aviso, "copiar_al_portapapeles", copiar)
    guion(
        ("¿Cuál?", 0),
        ("¿Qué hago con entrevista?", "copiar"),
        ("¿Algo más", "salir"),
    )

    assert menu.flujo_mis_transcripciones() is False

    etiquetas_ = [o[0] for o in guion.opciones_de("¿Qué hago con")]
    assert etiquetas_[:3] == ["Abrir la transcripción", "Leer con el audio", "Copiar la transcripción"]
    copiar.assert_called_once()


def test_copiar_transcripcion_con_un_txt_en_cp1252_no_cierra_el_menu(tmp_path, monkeypatch):
    txt = tmp_path / "vieja.blocks.txt"
    txt.write_bytes("[00:00:00] Ana: canción".encode("cp1252"))
    copiado = []
    monkeypatch.setattr(menu.aviso, "copiar_al_portapapeles", lambda t: copiado.append(t) or True)

    assert menu.copiar_transcripcion(txt) is True
    assert copiado[0].startswith("[00:00:00] Ana: canci")
