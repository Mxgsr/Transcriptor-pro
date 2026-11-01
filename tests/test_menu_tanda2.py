# Ubicación: tests/test_menu_tanda2.py
# Pruebas de lo que el menú conectó de los módulos nuevos: leer con el audio, buscar y paginar en
# «Mis transcripciones», revisar frases dudosas, clave de Hugging Face, modelos, «Preparar la app»,
# clic derecho y actualizaciones. Los módulos (vista, buscar, modelos, actualizar...) están simulados.
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src import actualizar, ajustes, buscar, cli, clic_derecho, historial, menu, modelos, vista
from tests.test_menu import Guion

pytestmark = pytest.mark.usefixtures("sin_red_ni_modelos_en_el_menu")


@pytest.fixture
def guion(monkeypatch):
    g = Guion(monkeypatch)
    yield g
    assert not g.pendientes, f"Quedaron respuestas sin usar: {g.pendientes}"


@pytest.fixture(autouse=True)
def modelo_turbo():
    ajustes.guardar(modelo="turbo")


@pytest.fixture
def instalado(monkeypatch):
    modulos = {"pyannote.audio": True}
    monkeypatch.setattr(menu, "_instalado", lambda modulo: modulos[modulo])
    return modulos


# --- Leer con el audio --------------------------------------------------------------

@pytest.fixture
def vista_falsa(monkeypatch, tmp_path):
    ruta = tmp_path / "vista.html"
    falsa = SimpleNamespace(
        crear=MagicMock(return_value=ruta),
        abrir=MagicMock(return_value=True),
        audio=tmp_path / "a.mp3",
    )
    monkeypatch.setattr(vista, "crear_vista", falsa.crear)
    monkeypatch.setattr(vista, "abrir_en_navegador", falsa.abrir)
    monkeypatch.setattr(vista, "datos_de_vista", lambda *a, **k: {"audio": falsa.audio})
    return falsa


def test_leer_con_el_audio_va_justo_despues_de_abrir(guion, vista_falsa, tmp_path, capsys):
    txt, json_path = tmp_path / "r.blocks.txt", tmp_path / "r.blocks.json"
    guion(("¿Y ahora?", "leer"), ("¿Algo más", "menu"))

    assert menu.acciones_sobre(txt, json_path, "¿Y ahora?") is True

    etiquetas = [o[0] for o in guion.opciones_de("¿Y ahora?")]
    assert etiquetas[:2] == ["Abrir la transcripción", "Leer con el audio"]
    vista_falsa.crear.assert_called_once_with(txt, json_path, None, ir_a=None)
    vista_falsa.abrir.assert_called_once_with(tmp_path / "vista.html")
    assert "La abrí en el navegador. Haz clic en un párrafo para escucharlo." in capsys.readouterr().out


def test_leer_si_no_se_pudo_abrir_dice_donde_quedo(guion, vista_falsa, tmp_path, capsys):
    vista_falsa.abrir.return_value = False
    guion(("¿Y ahora?", "leer"), ("¿Algo más", "menu"))

    menu.acciones_sobre(tmp_path / "r.blocks.txt", None, "¿Y ahora?")

    err = capsys.readouterr().err
    assert "No pude abrir la vista. Está guardada en" in err and "vista.html" in err


def test_leer_sin_audio_avisa_que_se_vera_sin_audio(guion, vista_falsa, tmp_path, capsys):
    vista_falsa.audio = None
    guion(("¿Y ahora?", "leer"), ("¿Algo más", "menu"))

    menu.acciones_sobre(tmp_path / "r.blocks.txt", None, "¿Y ahora?")

    salida = capsys.readouterr().out
    assert "se verá sin audio" in salida and "La abrí en el navegador" in salida


def test_leer_si_falla_crear_la_vista_no_rompe_el_menu(guion, vista_falsa, tmp_path, capsys):
    vista_falsa.crear.side_effect = OSError("disco")
    guion(("¿Y ahora?", "leer"), ("¿Algo más", "menu"))

    menu.acciones_sobre(tmp_path / "r.blocks.txt", None, "¿Y ahora?")

    assert "No pude preparar la lectura" in capsys.readouterr().err
    vista_falsa.abrir.assert_not_called()


# --- Mis transcripciones: lista sin límite y búsqueda ---------------------------------

def _entradas(cuantas, tmp_path):
    return [{"txt": tmp_path / f"t{i:02d}.blocks.txt", "json": None, "fecha": 1_700_000_000 - i, "duracion": 60,
             "audio": None} for i in range(cuantas)]


@pytest.fixture
def veinte(monkeypatch, tmp_path):
    entradas = _entradas(20, tmp_path)
    monkeypatch.setattr(historial, "listar", lambda: entradas)
    monkeypatch.setattr(menu, "etiquetas", lambda lista: [f"{e['txt'].name[:3]}" for e in lista])
    return entradas


def test_ver_mas_antiguas_y_ver_mas_recientes(guion, veinte):
    guion(
        ("¿Cuál?", "antiguas"),
        ("¿Cuál?", "recientes"),
        ("¿Cuál?", menu.Atras),
    )

    with pytest.raises(menu.Atras):
        menu.flujo_mis_transcripciones()

    primera, segunda, tercera = [o for m, o, _ in guion.hechas]
    assert [t for t, _ in primera][0] == "Buscar en todas…"
    assert len([1 for _, v in primera if isinstance(v, int)]) == menu.MAX_EN_LISTA
    assert [t for t, _ in primera][-1] == "Ver más antiguas…"
    assert "Ver más recientes…" not in [t for t, _ in primera]
    # La segunda página: las 5 restantes, «Ver más recientes…» al principio y sin «Ver más antiguas…»
    assert [t for t, _ in segunda] == ["Buscar en todas…", "Ver más recientes…", "t15", "t16", "t17", "t18", "t19"]
    assert tercera == primera


def test_elegir_en_la_segunda_pagina_abre_esa_transcripcion(guion, veinte, monkeypatch):
    abierta = MagicMock(return_value=True)
    monkeypatch.setattr(menu, "acciones_sobre", abierta)
    guion(("¿Cuál?", "antiguas"), ("¿Cuál?", 2))

    assert menu.flujo_mis_transcripciones() is True

    assert abierta.call_args.args[0] == veinte[17]["txt"]


def _coincidencia(tmp_path, n, inicio=12.0):
    return buscar.Coincidencia(txt=tmp_path / f"c{n}.blocks.txt", json=tmp_path / f"c{n}.blocks.json",
                               audio=tmp_path / f"c{n}.mp3", titulo=f"Reunión {n}", fecha="2026-11-01",
                               inicio=inicio + n, hablante="Ana", fragmento="el presupuesto")


def test_buscar_sin_resultados_vuelve_a_preguntar(guion, veinte, monkeypatch, capsys):
    monkeypatch.setattr(buscar, "buscar", MagicMock(return_value=[]))
    guion(
        ("¿Cuál?", "buscar"),
        ("¿Qué busco?", "xyz"),
        ("¿Qué busco?", menu.Atras),
        ("¿Cuál?", menu.Atras),
    )

    with pytest.raises(menu.Atras):
        menu.flujo_mis_transcripciones()

    assert "No encontré «xyz» en tus transcripciones." in capsys.readouterr().out


def test_buscar_y_abrir_un_resultado_con_ir_a(guion, veinte, vista_falsa, monkeypatch, tmp_path):
    resultados = [_coincidencia(tmp_path, n) for n in range(3)]
    monkeypatch.setattr(buscar, "buscar", MagicMock(return_value=resultados))
    guion(
        ("¿Cuál?", "buscar"),
        ("¿Qué busco?", "presupuesto"),
        ("¿Cuál abro?", 1),
        ("¿Cuál abro?", 2),      # vuelve a la lista de resultados para abrir otro
        ("¿Cuál abro?", menu.Atras),
        ("¿Qué busco?", menu.Atras),
        ("¿Cuál?", menu.Atras),
    )

    with pytest.raises(menu.Atras):
        menu.flujo_mis_transcripciones()

    llamadas = vista_falsa.crear.call_args_list
    c1, c2 = resultados[1], resultados[2]
    assert llamadas[0].args == (c1.txt, c1.json, c1.audio) and llamadas[0].kwargs == {"ir_a": c1.inicio}
    assert llamadas[1].args == (c2.txt, c2.json, c2.audio) and llamadas[1].kwargs == {"ir_a": c2.inicio}
    etiquetas = [t for t, _ in guion.opciones_de("¿Cuál abro?")]
    assert etiquetas == [buscar.etiqueta(c) for c in resultados]


def test_buscar_muestra_como_mucho_50(guion, veinte, vista_falsa, monkeypatch, tmp_path, capsys):
    resultados = [_coincidencia(tmp_path, n) for n in range(70)]
    monkeypatch.setattr(buscar, "buscar", MagicMock(return_value=resultados))
    guion(
        ("¿Cuál?", "buscar"),
        ("¿Qué busco?", "presupuesto"),
        ("¿Cuál abro?", menu.Atras),
        ("¿Qué busco?", menu.Atras),
        ("¿Cuál?", menu.Atras),
    )

    with pytest.raises(menu.Atras):
        menu.flujo_mis_transcripciones()

    assert len(guion.opciones_de("¿Cuál abro?")) == 50
    assert "Muestro las primeras 50: prueba con más palabras." in capsys.readouterr().out


# --- Revisar frases dudosas desde las acciones ------------------------------------------

def test_acciones_ofrece_revisar_dudosas_despues_de_cambiar_nombres(guion, monkeypatch, tmp_path):
    json_path = tmp_path / "r.blocks.json"
    monkeypatch.setattr(cli, "_contar_dudosas", lambda ruta: 3)
    revisar = MagicMock(return_value=1)
    monkeypatch.setattr(cli, "_revisar_dudosas", revisar)
    guion(("¿Y ahora?", "dudosas"), ("¿Algo más", "menu"))

    menu.acciones_sobre(tmp_path / "r.blocks.txt", json_path, "¿Y ahora?")

    etiquetas = [o[0] for o in guion.opciones_de("¿Y ahora?")]
    assert etiquetas.index("Revisar frases dudosas (3)") == etiquetas.index("Cambiar nombres de hablantes") + 1
    assert revisar.call_args.args[0] == json_path and revisar.call_args.args[1] is menu


def test_acciones_no_ofrece_dudosas_si_no_hay(guion, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_contar_dudosas", lambda ruta: 0)
    guion(("¿Y ahora?", "menu"))

    menu.acciones_sobre(tmp_path / "r.blocks.txt", tmp_path / "r.blocks.json", "¿Y ahora?")

    assert not any("dudosas" in o[0] for o in guion.opciones_de("¿Y ahora?"))


# --- Clave de Hugging Face ----------------------------------------------------------

CLAVE = "hf_SECRETA1234567890"


@pytest.fixture
def clave_fixture(monkeypatch):
    """Simula pegar la clave y los efectos de modelos.* y del navegador; registra lo que se imprime."""
    estado = SimpleNamespace(
        pegadas=[CLAVE], resultado="ok", guardada=[], abiertas=[],
        comprobar=MagicMock(side_effect=lambda token: estado.resultado),
    )
    monkeypatch.setattr(menu, "clave_secreta", lambda mensaje, volver=True: estado.pegadas.pop(0))
    monkeypatch.setattr(modelos, "comprobar_token", estado.comprobar)
    monkeypatch.setattr(modelos, "guardar_token", lambda token: estado.guardada.append(token))
    monkeypatch.setattr(menu, "_abrir_pagina", lambda url: estado.abiertas.append(url))
    return estado


def _salida_completa(capsys):
    c = capsys.readouterr()
    return c.out + c.err


def test_clave_ok_se_guarda_y_nunca_se_imprime(guion, clave_fixture, capsys):
    guion(("¿Qué hago?", "pegar"))

    assert menu._configurar_clave() is True

    salida = _salida_completa(capsys)
    assert "La clave funciona. La guardé solo en este computador." in salida
    assert clave_fixture.guardada == [CLAVE]
    assert CLAVE not in salida


def test_clave_explica_y_abre_las_dos_paginas(guion, clave_fixture, capsys):
    guion(("¿Qué hago?", "paginas"), ("¿Qué hago?", "pegar"))

    menu._configurar_clave()

    assert clave_fixture.abiertas == [modelos.PAGINA_TOKENS, modelos.PAGINA_MODELO]
    assert "identificar quién habla" in capsys.readouterr().out


def test_clave_invalida_no_se_guarda(guion, clave_fixture, capsys):
    clave_fixture.resultado = "invalida"
    guion(("¿Qué hago?", "pegar"), ("¿Qué hago?", menu.Atras))

    with pytest.raises(menu.Atras):
        menu._configurar_clave()

    salida = _salida_completa(capsys)
    assert "Esa clave no sirve. Revisa que la copiaste completa." in salida
    assert clave_fixture.guardada == [] and CLAVE not in salida


def test_clave_sin_acceso_ofrece_abrir_la_pagina_del_modelo(guion, clave_fixture, capsys):
    clave_fixture.resultado = "sin_acceso"
    guion(("¿Qué hago?", "pegar"), ("¿Abro la página del modelo?", True), ("¿Qué hago?", menu.Atras))

    with pytest.raises(menu.Atras):
        menu._configurar_clave()

    assert "falta aceptar las condiciones del modelo" in _salida_completa(capsys)
    assert clave_fixture.abiertas == [modelos.PAGINA_MODELO]
    assert clave_fixture.guardada == []


@pytest.mark.parametrize("resultado", ["sin_internet", "desconocido"])
def test_clave_que_no_se_pudo_comprobar_pregunta_si_guardar(guion, clave_fixture, capsys, resultado):
    clave_fixture.resultado = resultado
    guion(("¿Qué hago?", "pegar"), ("No pude comprobarla (¿hay internet?). ¿La guardo igual?", True))

    assert menu._configurar_clave() is True

    assert clave_fixture.guardada == [CLAVE]
    assert CLAVE not in _salida_completa(capsys)


def test_clave_que_no_se_pudo_comprobar_y_no_guardar(guion, clave_fixture):
    clave_fixture.resultado = "sin_internet"
    guion(("¿Qué hago?", "pegar"),
          ("No pude comprobarla", False),
          ("¿Qué hago?", menu.Atras))

    with pytest.raises(menu.Atras):
        menu._configurar_clave()

    assert clave_fixture.guardada == []


def test_clave_con_espacios_no_se_comprueba(guion, clave_fixture, capsys):
    clave_fixture.pegadas = ["hf_ abc def"]
    guion(("¿Qué hago?", "pegar"), ("¿Qué hago?", menu.Atras))

    with pytest.raises(menu.Atras):
        menu._configurar_clave()

    clave_fixture.comprobar.assert_not_called()
    assert "hf_ abc def" not in _salida_completa(capsys)


def test_clave_value_error_al_guardar_da_mensaje_simple(guion, clave_fixture, monkeypatch, capsys):
    def mal(token):
        raise ValueError("La clave está vacía o tiene espacios.")

    monkeypatch.setattr(modelos, "guardar_token", mal)
    guion(("¿Qué hago?", "pegar"), ("¿Qué hago?", menu.Atras))

    with pytest.raises(menu.Atras):
        menu._configurar_clave()

    assert "Revisa que la copiaste completa" in _salida_completa(capsys)


def test_configuracion_muestra_el_estado_de_la_clave(guion, monkeypatch):
    for token, esperado in (("hf_x", "Clave de Hugging Face: guardada"), (None, "Clave de Hugging Face: falta")):
        monkeypatch.setattr(modelos, "token_guardado", lambda token=token: token)
        guion(("¿Qué quieres cambiar?", menu.Atras))
        menu.flujo_configuracion()
        assert esperado in [t for t, _ in guion.hechas[-1][1]]


def test_configuracion_sin_hablantes_no_muestra_la_clave(guion, monkeypatch):
    from src import plataforma
    monkeypatch.setattr(plataforma, "hablantes_disponible", lambda: False)
    guion(("¿Qué quieres cambiar?", menu.Atras))

    menu.flujo_configuracion()

    assert not any("Clave" in t for t, _ in guion.hechas[-1][1])


# --- Modelos --------------------------------------------------------------------------

def _estado_modelos(**descargados):
    return [
        modelos.EstadoModelo("turbo", "turbo", "r/turbo", descargados.get("turbo", True), 1_600_000_000),
        modelos.EstadoModelo("large", "large", "r/large", descargados.get("large", False), None),
        modelos.EstadoModelo(modelos.HABLANTES, "Identificar hablantes", "r/h", descargados.get("hablantes", True),
                             30_000_000),
    ]


def test_modelos_lista_con_etiquetas_simples(guion, monkeypatch):
    monkeypatch.setattr(modelos, "estado", lambda: _estado_modelos())
    guion(("Modelos (se guardan", menu.Atras))

    with pytest.raises(menu.Atras):
        menu._gestionar_modelos()

    etiquetas = [t for t, _ in guion.hechas[0][1]]
    assert "turbo                 · descargado · 1,6 GB · el que usas" in etiquetas
    assert "large                 · sin descargar (≈ 3,1 GB)" in etiquetas
    assert "Identificar hablantes · descargado · 30 MB" in etiquetas


def test_modelos_descargar(guion, monkeypatch):
    monkeypatch.setattr(modelos, "estado", lambda: _estado_modelos())
    bajado = MagicMock(return_value=True)
    monkeypatch.setattr(menu, "_descargar_modelo", bajado)
    guion(("Modelos (se guardan", "large"), ("large", True), ("Modelos (se guardan", menu.Atras))
    with pytest.raises(menu.Atras):
        menu._gestionar_modelos()

    bajado.assert_called_once_with("large")
    assert [t for t, _ in guion.hechas[1][1]] == ["Descargar (≈ 3,1 GB)"]


def test_modelos_eliminar_pide_confirmacion_y_avisa_si_es_el_que_usas(guion, monkeypatch, capsys):
    monkeypatch.setattr(modelos, "estado", lambda: _estado_modelos())
    eliminar = MagicMock(return_value=1_600_000_000)
    monkeypatch.setattr(modelos, "eliminar", eliminar)
    guion(
        ("Modelos (se guardan", "turbo"), ("turbo", True), ("¿Elimino turbo?", False),   # dice que no
        ("Modelos (se guardan", "turbo"), ("turbo", True), ("¿Elimino turbo?", True),
        ("Modelos (se guardan", menu.Atras),
    )
    with pytest.raises(menu.Atras):
        menu._gestionar_modelos()

    eliminar.assert_called_once_with("turbo")
    assert "Eliminar (libera 1,6 GB)" in [t for t, _ in guion.hechas[1][1]]
    assert "se volverá a descargar al transcribir" in guion.hechas[2][0]
    assert "Eliminé turbo" in capsys.readouterr().out


def test_modelos_hablantes_sin_clave_ofrece_configurarla_primero(guion, monkeypatch):
    monkeypatch.setattr(modelos, "estado", lambda: _estado_modelos(hablantes=False))
    monkeypatch.setattr(modelos, "token_guardado", lambda: None)
    configurar = MagicMock(return_value=True)
    bajado = MagicMock(return_value=True)
    monkeypatch.setattr(menu, "_configurar_clave", configurar)
    monkeypatch.setattr(menu, "_descargar_modelo", bajado)
    guion(("Modelos (se guardan", modelos.HABLANTES), ("Identificar hablantes", True),
          ("hace falta la clave", True), ("Modelos (se guardan", menu.Atras))
    with pytest.raises(menu.Atras):
        menu._gestionar_modelos()

    configurar.assert_called_once()
    bajado.assert_called_once_with(modelos.HABLANTES)


def test_descargar_modelo_muestra_avance_y_exito(monkeypatch, capsys):
    def descargar(clave, progreso):
        progreso(10, 100)
        progreso(100, 100)

    monkeypatch.setattr(modelos, "descargar", descargar)
    assert menu._descargar_modelo("large") is True
    assert "Descargué el modelo large" in capsys.readouterr().out


def test_descargar_modelo_con_error_simple_no_cierra_el_programa(monkeypatch, capsys):
    def descargar(clave, progreso):
        raise RuntimeError(modelos.MENSAJE_SIN_INTERNET)

    monkeypatch.setattr(modelos, "descargar", descargar)
    assert menu._descargar_modelo("large") is False
    assert modelos.MENSAJE_SIN_INTERNET in capsys.readouterr().err


def test_descargar_modelo_con_otro_error_guarda_el_detalle(monkeypatch, capsys):
    def descargar(clave, progreso):
        raise ValueError("algo raro")

    monkeypatch.setattr(modelos, "descargar", descargar)
    assert menu._descargar_modelo("large") is False
    assert "algo raro" in capsys.readouterr().err
    assert cli.ultimo_error is not None


def test_descargar_con_sin_internet_lo_dice(monkeypatch, capsys):
    monkeypatch.setattr(modelos, "descargar", lambda clave, progreso: None)
    monkeypatch.setattr(ajustes, "sin_internet_activo", lambda: True)
    menu._descargar_modelo("tiny")
    assert "me conecto solo durante la descarga" in capsys.readouterr().out


# --- Preparar la app ------------------------------------------------------------------

def test_el_menu_principal_ofrece_preparar_solo_si_hace_falta(guion, monkeypatch):
    necesita = {"valor": True}
    monkeypatch.setattr(modelos, "necesita_preparacion", lambda: necesita["valor"])
    preparar = MagicMock(side_effect=lambda: necesita.update(valor=False) or True)
    monkeypatch.setattr(menu, "flujo_preparar", preparar)
    guion(("¿Qué quieres hacer?", "preparar"), ("¿Qué quieres hacer?", "salir"))

    menu.iniciar()

    primera, segunda = [o for m, o, _ in guion.hechas]
    assert primera[0] == ("Preparar la app (falta descargar lo necesario)", "preparar")
    assert "preparar" not in [v for _, v in segunda]
    preparar.assert_called_once()


def test_preparar_no_se_ofrece_si_todo_esta_listo(guion):
    guion(("¿Qué quieres hacer?", "salir"))
    menu.iniciar()
    assert "preparar" not in [v for _, v in guion.hechas[0][1]]


def test_preparar_sin_clave_descarga_los_modelos_y_avisa(guion, instalado, monkeypatch, capsys):
    descargados = set()
    monkeypatch.setattr(modelos, "descargado", lambda clave: clave in descargados)
    monkeypatch.setattr(modelos, "token_guardado", lambda: "hf_x")
    bajados = []

    def bajar(clave):
        bajados.append(clave)
        descargados.add(clave)
        return True

    monkeypatch.setattr(menu, "_descargar_modelo", bajar)

    assert menu.flujo_preparar() is True

    assert bajados == [ajustes.valor("modelo"), modelos.HABLANTES]
    assert "Todo listo para transcribir." in capsys.readouterr().out


def test_preparar_sin_clave_ofrece_configurarla_y_se_puede_dejar_para_despues(guion, instalado, monkeypatch, capsys):
    descargados = set()
    monkeypatch.setattr(modelos, "descargado", lambda clave: clave in descargados)
    monkeypatch.setattr(modelos, "token_guardado", lambda: None)
    configurar = MagicMock()
    monkeypatch.setattr(menu, "_configurar_clave", configurar)
    bajados = []
    monkeypatch.setattr(menu, "_descargar_modelo", lambda clave: bajados.append(clave) or True)
    guion(("¿Qué hago?", menu.Atras))   # «Ahora no (transcribir sin identificar hablantes)»

    menu.flujo_preparar()

    textos = [t for t, _ in guion.hechas[0][1]]
    assert textos == ["Configurarla ahora"]
    configurar.assert_not_called()
    assert bajados == [ajustes.valor("modelo")]   # el de hablantes necesita la clave
    assert "Falta: la clave para identificar hablantes" in capsys.readouterr().out
    # «Ahora no» queda recordado: «Preparar la app» deja de insistir en el menú principal
    assert historial.preferencias().get(modelos.SIN_CLAVE_ELEGIDO) is True


def test_preparar_con_clave_nueva_sigue_con_el_modelo_de_hablantes(guion, instalado, monkeypatch):
    descargados = {ajustes.valor("modelo")}
    token = {"valor": None}
    monkeypatch.setattr(modelos, "descargado", lambda clave: clave in descargados)
    monkeypatch.setattr(modelos, "token_guardado", lambda: token["valor"])
    monkeypatch.setattr(menu, "_configurar_clave", lambda: token.update(valor="hf_x") or True)
    bajados = []
    monkeypatch.setattr(menu, "_descargar_modelo", lambda clave: bajados.append(clave) or True)
    guion(("¿Qué hago?", True))

    menu.flujo_preparar()

    assert bajados == [modelos.HABLANTES]


def test_preparar_si_falla_una_descarga_dice_que_falto(guion, instalado, monkeypatch, capsys):
    monkeypatch.setattr(modelos, "descargado", lambda clave: False)
    monkeypatch.setattr(modelos, "token_guardado", lambda: "hf_x")
    monkeypatch.setattr(menu, "_descargar_modelo", lambda clave: False)

    menu.flujo_preparar()

    salida = capsys.readouterr().out
    assert "Falta:" in salida and "Todo listo" not in salida


# --- Antes de empezar a transcribir ---------------------------------------------------------

@pytest.fixture
def transcribir_falso(monkeypatch, tmp_path):
    txt = tmp_path / "r.blocks.txt"
    txt.write_text("[00:00:00] Hola\n", encoding="utf-8")
    ejecutar = MagicMock(return_value=SimpleNamespace(txt_path=txt, json_path=None))
    monkeypatch.setattr(cli, "ejecutar_transcripcion", ejecutar)
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"x")
    return SimpleNamespace(ejecutar=ejecutar, audio=audio)


def _responder_transcribir(guion, t, *final):
    guion(
        ("Arrastra el archivo", str(t.audio)),
        ("¿Cómo se llama esta reunión?", "Reunión"),
        *final,
    )


def test_resumen_avisa_que_la_primera_vez_descarga_el_modelo(guion, instalado, transcribir_falso, monkeypatch, capsys):
    ajustes.guardar(modo_hablantes=ajustes.NUNCA)
    monkeypatch.setattr(modelos, "descargado", lambda clave: False)
    monkeypatch.setattr(ajustes, "sin_internet_activo", lambda: False)
    _responder_transcribir(guion, transcribir_falso, ("¿Empiezo?", "empezar"), ("¿Y ahora?", "menu"))

    menu.flujo_transcribir()

    salida = capsys.readouterr().out
    assert "La primera vez descargo el modelo turbo (≈ 1,6 GB); puede tardar unos minutos." in " ".join(salida.split())
    transcribir_falso.ejecutar.assert_called_once()


def test_con_modelo_descargado_el_resumen_no_avisa(guion, instalado, transcribir_falso, capsys):
    ajustes.guardar(modo_hablantes=ajustes.NUNCA)
    _responder_transcribir(guion, transcribir_falso, ("¿Empiezo?", "cancelar"))

    menu.flujo_transcribir()

    assert "La primera vez descargo" not in capsys.readouterr().out


def test_sin_internet_y_modelo_faltante_ofrece_descargarlo_antes_de_empezar(
        guion, instalado, transcribir_falso, monkeypatch):
    ajustes.guardar(modo_hablantes=ajustes.NUNCA)
    monkeypatch.setattr(modelos, "descargado", lambda clave: False)
    monkeypatch.setattr(ajustes, "sin_internet_activo", lambda: True)
    bajado = MagicMock(return_value=True)
    monkeypatch.setattr(menu, "_descargar_modelo", bajado)
    _responder_transcribir(guion, transcribir_falso,
                           ("¿Empiezo?", "empezar"),
                           ("Falta descargar el modelo turbo y está activado «Sin internet».", True),
                           ("¿Y ahora?", "menu"))   # ya había dicho «Sí, empezar»: no se vuelve a preguntar

    menu.flujo_transcribir()

    bajado.assert_called_once_with("turbo")
    transcribir_falso.ejecutar.assert_called_once()


def test_sin_internet_volver_regresa_a_empiezo_sin_transcribir(guion, instalado, transcribir_falso, monkeypatch):
    ajustes.guardar(modo_hablantes=ajustes.NUNCA)
    monkeypatch.setattr(modelos, "descargado", lambda clave: False)
    monkeypatch.setattr(ajustes, "sin_internet_activo", lambda: True)
    bajado = MagicMock()
    monkeypatch.setattr(menu, "_descargar_modelo", bajado)
    _responder_transcribir(guion, transcribir_falso,
                           ("¿Empiezo?", "empezar"),
                           ("Falta descargar", menu.Atras),
                           ("¿Empiezo?", "cancelar"))

    menu.flujo_transcribir()

    bajado.assert_not_called()
    transcribir_falso.ejecutar.assert_not_called()


def test_sin_internet_y_modelo_de_hablantes_faltante(guion, instalado, transcribir_falso, monkeypatch):
    ajustes.guardar(modo_hablantes=ajustes.SIEMPRE)
    monkeypatch.setattr(modelos, "descargado", lambda clave: clave != modelos.HABLANTES)
    monkeypatch.setattr(ajustes, "sin_internet_activo", lambda: True)
    bajado = MagicMock(return_value=True)
    monkeypatch.setattr(menu, "_descargar_modelo", bajado)
    guion(
        ("Arrastra el archivo", str(transcribir_falso.audio)),
        ("¿Cuántas personas hablan?", "2"),
        ("¿Cómo se llama esta reunión?", "Reunión"),
        ("¿Empiezo?", "empezar"),
        ("Falta descargar el modelo para identificar hablantes y está activado «Sin internet».", True),
        ("¿Y ahora?", "menu"),
    )

    menu.flujo_transcribir()

    bajado.assert_called_once_with(modelos.HABLANTES)


def test_sin_internet_y_todo_descargado_empieza_directo(guion, instalado, transcribir_falso, monkeypatch):
    ajustes.guardar(modo_hablantes=ajustes.NUNCA)
    monkeypatch.setattr(ajustes, "sin_internet_activo", lambda: True)
    _responder_transcribir(guion, transcribir_falso, ("¿Empiezo?", "empezar"), ("¿Y ahora?", "menu"))

    menu.flujo_transcribir()

    transcribir_falso.ejecutar.assert_called_once()


# --- Clic derecho ---------------------------------------------------------------------

def test_configuracion_clic_derecho_activar_y_quitar(guion, monkeypatch, capsys):
    puesto = {"si": False}
    instalar = MagicMock(side_effect=lambda: puesto.update(si=True) or True)
    quitar = MagicMock(side_effect=lambda: puesto.update(si=False) or True)
    monkeypatch.setattr(clic_derecho, "disponible", lambda: True)
    monkeypatch.setattr(clic_derecho, "instalado", lambda: puesto["si"])
    monkeypatch.setattr(clic_derecho, "instalar", instalar)
    monkeypatch.setattr(clic_derecho, "quitar", quitar)
    guion(
        ("¿Qué quieres cambiar?", "clic_derecho"), ("¿Transcribir con clic derecho?", True),
        ("¿Algo más?", "clic_derecho"), ("¿Transcribir con clic derecho?", False),
        ("¿Algo más?", menu.Atras),
    )

    menu.flujo_configuracion()

    instalar.assert_called_once()
    quitar.assert_called_once()
    assert "Transcribir con clic derecho: no" in [t for t, _ in guion.hechas[0][1]]
    assert "Transcribir con clic derecho: sí" in [t for t, _ in guion.hechas[2][1]]
    assert " ".join(clic_derecho.TEXTO_DONDE.split()) in " ".join(capsys.readouterr().out.split())


def test_clic_derecho_que_falla_lo_dice(guion, monkeypatch, capsys):
    monkeypatch.setattr(clic_derecho, "disponible", lambda: True)
    monkeypatch.setattr(clic_derecho, "instalado", lambda: False)
    monkeypatch.setattr(clic_derecho, "instalar", lambda: False)
    guion(("¿Qué quieres cambiar?", "clic_derecho"), ("¿Transcribir con clic derecho?", True),
          ("¿Algo más?", menu.Atras))

    menu.flujo_configuracion()

    assert "No pude activarlo en este computador." in capsys.readouterr().err


def test_clic_derecho_no_aparece_donde_no_esta_disponible(guion, monkeypatch):
    monkeypatch.setattr(clic_derecho, "disponible", lambda: False)
    guion(("¿Qué quieres cambiar?", menu.Atras))

    menu.flujo_configuracion()

    assert not any("clic derecho" in t for t, _ in guion.hechas[0][1])


# --- Actualizaciones --------------------------------------------------------------------

@pytest.fixture
def act(monkeypatch):
    f = SimpleNamespace(
        novedad=actualizar.Novedad("2.1.0", "main"),
        instalacion="uv_tool", uv="/usr/bin/uv", resultado="listo",
        actualizar=MagicMock(side_effect=lambda n, salida=print: f.resultado),
    )
    monkeypatch.setattr(actualizar, "version_instalada", lambda: "2.0.0b1")
    monkeypatch.setattr(actualizar, "buscar", lambda: f.novedad)
    monkeypatch.setattr(actualizar, "como_se_instalo", lambda: f.instalacion)
    monkeypatch.setattr(actualizar, "buscar_uv", lambda: f.uv)
    monkeypatch.setattr(actualizar, "actualizar", f.actualizar)
    return f


def test_actualizaciones_se_ofrece_con_la_version(guion, act):
    guion(("¿Qué quieres cambiar?", menu.Atras))
    menu.flujo_configuracion()
    assert "Buscar actualizaciones (tienes la versión 2.0.0b1)" in [t for t, _ in guion.hechas[0][1]]


def test_actualizaciones_sin_conexion(act, monkeypatch, capsys):
    def sin_red():
        raise actualizar.SinConexion()

    monkeypatch.setattr(actualizar, "buscar", sin_red)
    assert menu._buscar_actualizaciones() is False
    assert "No pude revisar: no hay conexión a internet." in capsys.readouterr().err


def test_actualizaciones_ya_tienes_la_ultima(act, capsys):
    act.novedad = None
    assert menu._buscar_actualizaciones() is False
    assert "Tienes la última versión (2.0.0b1)." in capsys.readouterr().out


def test_actualizaciones_ahora_no(guion, act, capsys):
    guion(("¿Qué hago?", menu.Atras))
    assert menu._buscar_actualizaciones() is False
    assert "Hay una versión nueva: 2.1.0 (tienes 2.0.0b1)." in capsys.readouterr().out
    act.actualizar.assert_not_called()


def test_actualizaciones_otra_instalacion(guion, act, capsys):
    act.instalacion = "otro"
    guion(("¿Qué hago?", True))
    assert menu._buscar_actualizaciones() is False
    assert actualizar.MENSAJE_OTRA_INSTALACION in " ".join(capsys.readouterr().err.replace("│", " ").split())
    act.actualizar.assert_not_called()


def test_actualizaciones_sin_uv(guion, act, capsys):
    act.uv = None
    guion(("¿Qué hago?", True))
    assert menu._buscar_actualizaciones() is False
    assert "uv" in capsys.readouterr().err
    act.actualizar.assert_not_called()


def test_actualizaciones_error(guion, act, capsys):
    act.resultado = "error"
    guion(("¿Qué hago?", True))
    assert menu._buscar_actualizaciones() is False
    assert "No se pudo actualizar. Inténtalo más tarde o vuelve a ejecutar el instalador." in " ".join(
        capsys.readouterr().err.replace("│", " ").split())


def test_actualizar_bien_cierra_el_programa(guion, act, capsys):
    guion(("¿Qué quieres hacer?", "configuracion"),
          ("¿Qué quieres cambiar?", "actualizaciones"),
          ("¿Qué hago?", True))     # y no vuelve a preguntar nada: el programa se cierra

    menu.iniciar()

    salida = capsys.readouterr().out
    assert "Actualizado. Abre Transcriptor de nuevo para usar la nueva versión." in salida
    assert "Hasta luego" in salida
    act.actualizar.assert_called_once()
    assert act.actualizar.call_args.kwargs["salida"] == menu.consola.print


def test_actualizar_en_otra_ventana_tambien_cierra(guion, act, capsys):
    act.resultado = "reiniciar_aparte"
    guion(("¿Qué quieres hacer?", "configuracion"),
          ("¿Qué quieres cambiar?", "actualizaciones"),
          ("¿Qué hago?", True))

    menu.iniciar()

    salida = " ".join(capsys.readouterr().out.split())
    assert "Se abrió una ventana que termina la actualización. Transcriptor se cerrará ahora." in salida
    assert "Hasta luego" in salida


def test_configuracion_devuelve_false_al_cerrar_y_true_si_no(guion, act):
    guion(("¿Qué quieres cambiar?", "actualizaciones"), ("¿Qué hago?", True))
    assert menu.flujo_configuracion() is False


# --- Aviso de versión nueva al abrir ----------------------------------------------------------

def test_al_abrir_avisa_si_hay_version_nueva(guion, monkeypatch, capsys):
    buscado = MagicMock()
    monkeypatch.setattr(actualizar, "buscar_en_segundo_plano", buscado)
    monkeypatch.setattr(actualizar, "aviso_guardado", lambda: actualizar.Novedad("2.1.0", "main"))
    guion(("¿Qué quieres hacer?", "salir"))

    menu.iniciar()

    buscado.assert_called_once()
    assert ("Hay una versión nueva (2.1.0). Puedes instalarla en Configuración › Buscar actualizaciones."
            in " ".join(capsys.readouterr().out.split()))


def test_al_abrir_sin_novedad_no_avisa(guion, capsys):
    guion(("¿Qué quieres hacer?", "salir"))
    menu.iniciar()
    assert "versión nueva" not in capsys.readouterr().out


def test_un_fallo_en_las_actualizaciones_nunca_impide_abrir_el_menu(guion, monkeypatch):
    def falla(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(actualizar, "buscar_en_segundo_plano", falla)
    guion(("¿Qué quieres hacer?", "salir"))

    menu.iniciar()
