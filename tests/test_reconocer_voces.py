# Ubicación: tests/test_reconocer_voces.py
# Pruebas de la interfaz de «reconocer al equipo por la voz»: las propuestas al poner nombres,
# el guardado de huellas tras nombrar y el ajuste en Configuración.
# El motor (src/voces.py) ya se prueba en test_voces.py; aquí se simulan las preguntas y el audio.
# conftest.py apunta TRANSCRIPTOR_HOME a una carpeta temporal: cada test empieza sin voces ni ajustes.
import pytest
from typer.testing import CliRunner

from src import ajustes, cli, menu, procesador, voces
from src.cli import app
from utils.formatters import guardar_json

runner = CliRunner()

# Huellas de juguete (las reales tienen 256 valores): perpendiculares entre sí
ANA = [1.0, 0.0, 0.0, 0.0]
LUIS = [0.0, 1.0, 0.0, 0.0]
HUELLAS = {"Hablante 1": ANA, "Hablante 2": LUIS}

PARRAFOS = [
    {"start": 0, "end": 30, "text": "Bienvenidos al programa.", "speaker": "Hablante 1"},
    {"start": 30, "end": 40, "text": "Gracias por invitarme.", "speaker": "Hablante 2"},
]


def _json(tmp_path, nombres=None, huellas=HUELLAS):
    audio = tmp_path / "charla.mp3"
    audio.write_bytes(b"")
    ruta = tmp_path / "charla.blocks.json"
    guardar_json(PARRAFOS, ruta, audio=audio, nombres=nombres, huellas=huellas)
    return ruta


@pytest.fixture
def escuchar(monkeypatch):
    """Simula _escuchar_y_nombrar: anota lo que recibe y devuelve lo que se le diga en .respuesta."""
    class Falso:
        llamadas = []
        respuesta = {}
        error = None

    falso = Falso()
    falso.llamadas = []

    def fake(parrafos, nombres_actuales, audio, sugerencias=None):
        falso.llamadas.append({"nombres": dict(nombres_actuales), "sugerencias": sugerencias})
        if falso.error:
            raise falso.error
        return dict(falso.respuesta)

    monkeypatch.setattr(cli, "_escuchar_y_nombrar", fake)
    monkeypatch.setattr(cli, "_es_interactivo", lambda: True)
    return falso


@pytest.fixture
def procesar(monkeypatch, tmp_path):
    """Simula procesar_entrada con dos hablantes y sus huellas."""
    def fake(entrada, modelo, **kwargs):
        json_path = _json(tmp_path)
        return procesador.Resultado(
            audio_path=tmp_path / "charla.mp3", txt_path=tmp_path / "charla.blocks.txt", json_path=json_path,
            parrafos=PARRAFOS, duracion=40.0, huellas=HUELLAS)

    monkeypatch.setattr(procesador, "procesar_entrada", fake)


@pytest.fixture
def si_quiere(monkeypatch):
    monkeypatch.setattr(cli, "_quiere_poner_nombres", lambda menu_, cuantos: True)


# --- Propuestas al poner nombres ---

def test_propone_a_quien_ya_conoce_al_transcribir(procesar, escuchar, si_quiere):
    voces.recordar("Ana", ANA)
    escuchar.respuesta = {"Hablante 1": "Ana"}

    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d"])

    assert resultado.exit_code == 0, resultado.output
    assert escuchar.llamadas[0]["sugerencias"] == {"Hablante 1": "Ana"}
    assert "Reconocí por la voz a: Ana. Confírmalo al escuchar a cada uno." in " ".join(resultado.output.split())


def test_no_propone_nada_si_el_ajuste_esta_apagado(procesar, escuchar, si_quiere):
    voces.recordar("Ana", ANA)
    ajustes.guardar(reconocer_voces=False)

    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d"])

    assert resultado.exit_code == 0, resultado.output
    assert escuchar.llamadas[0]["sugerencias"] == {}
    assert "Reconocí" not in resultado.output


def test_no_propone_nada_sin_voces_guardadas_o_sin_huellas(monkeypatch, tmp_path, procesar, escuchar, si_quiere):
    # Sin voces guardadas
    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d"])
    assert resultado.exit_code == 0, resultado.output
    assert escuchar.llamadas[0]["sugerencias"] == {}

    # Con voces pero un .json antiguo, sin huellas
    voces.recordar("Ana", ANA)
    json_path = _json(tmp_path, huellas={})
    resultado = runner.invoke(app, ["nombres", str(json_path), "-e"])
    assert resultado.exit_code == 0, resultado.output
    assert escuchar.llamadas[1]["sugerencias"] == {}


def test_nombres_con_e_propone_solo_a_los_que_siguen_sin_nombre(tmp_path, escuchar):
    voces.recordar("Ana", ANA)
    voces.recordar("Luis", LUIS)
    # El Hablante 2 ya se llama Eva: no se le propone Luis
    json_path = _json(tmp_path, nombres={"Hablante 2": "Eva"})

    resultado = runner.invoke(app, ["nombres", str(json_path), "-e"])

    assert resultado.exit_code == 0, resultado.output
    assert escuchar.llamadas[0]["sugerencias"] == {"Hablante 1": "Ana"}
    assert escuchar.llamadas[0]["nombres"] == {"Hablante 2": "Eva"}


def test_con_sin_preguntas_no_propone_ni_pregunta(procesar, escuchar, monkeypatch):
    voces.recordar("Ana", ANA)
    preguntado = []
    monkeypatch.setattr(cli, "_quiere_poner_nombres", lambda *a: preguntado.append(1) or True)

    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d", "--sin-preguntas"])

    assert resultado.exit_code == 0, resultado.output
    assert preguntado == [] and escuchar.llamadas == []
    assert "Reconocí" not in resultado.output


# --- Guardar huellas tras nombrar ---

def test_guarda_las_huellas_de_lo_nombrado_al_transcribir(procesar, escuchar, si_quiere):
    escuchar.respuesta = {"Hablante 1": "Ana"}

    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d"])

    assert resultado.exit_code == 0, resultado.output
    assert voces.conocidas() == ["Ana"]


def test_ctrl_c_a_mitad_de_nombrar_no_guarda_nada(procesar, escuchar, si_quiere):
    escuchar.error = KeyboardInterrupt()

    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d"])

    assert resultado.exit_code == 0, resultado.output
    assert voces.conocidas() == []


def test_dejar_todo_como_esta_no_guarda_nada(procesar, escuchar, si_quiere):
    escuchar.respuesta = {}

    runner.invoke(app, ["transcribir", "charla.mp3", "-d"])

    assert voces.conocidas() == []


def test_ahora_no_no_guarda_nada(procesar, escuchar, monkeypatch):
    monkeypatch.setattr(cli, "_quiere_poner_nombres", lambda *a: False)

    runner.invoke(app, ["transcribir", "charla.mp3", "-d"])

    assert escuchar.llamadas == [] and voces.conocidas() == []


def test_con_el_ajuste_apagado_no_guarda(procesar, escuchar, si_quiere):
    ajustes.guardar(reconocer_voces=False)
    escuchar.respuesta = {"Hablante 1": "Ana"}

    runner.invoke(app, ["transcribir", "charla.mp3", "-d"])

    assert voces.conocidas() == []


def test_nombres_con_e_guarda_los_del_json_y_los_nuevos(tmp_path, escuchar):
    json_path = _json(tmp_path, nombres={"Hablante 2": "Luis"})
    escuchar.respuesta = {"Hablante 1": "Ana"}

    resultado = runner.invoke(app, ["nombres", str(json_path), "-e"])

    assert resultado.exit_code == 0, resultado.output
    assert voces.conocidas() == ["Ana", "Luis"]


def test_nombres_con_lista_guarda_las_huellas(tmp_path):
    json_path = _json(tmp_path)

    resultado = runner.invoke(app, ["nombres", str(json_path), "Ana,Luis"])

    assert resultado.exit_code == 0, resultado.output
    assert voces.conocidas() == ["Ana", "Luis"]
    assert voces.parecidos({"X": ANA}) == {"X": ("Ana", 1.0)}


def test_nombres_sin_lista_no_guarda_nada(tmp_path):
    json_path = _json(tmp_path, nombres={"Hablante 1": "Ana"})

    resultado = runner.invoke(app, ["nombres", str(json_path)])

    assert resultado.exit_code == 0, resultado.output
    assert voces.conocidas() == []


def test_con_nombres_guarda_las_huellas_aun_con_sin_preguntas(procesar, escuchar):
    resultado = runner.invoke(app, ["transcribir", "charla.mp3", "-d", "--sin-preguntas", "-n", "Ana,Luis"])

    assert resultado.exit_code == 0, resultado.output
    assert voces.conocidas() == ["Ana", "Luis"]
    assert escuchar.llamadas == []


def test_misma_persona_en_dos_etiquetas_promedia_las_dos_huellas(tmp_path):
    json_path = _json(tmp_path)

    resultado = runner.invoke(app, ["nombres", str(json_path), "1=Ana,2=Ana"])

    assert resultado.exit_code == 0, resultado.output
    assert voces.conocidas() == ["Ana"]
    # Quedó la mezcla de las dos: se parece a las dos por igual
    assert voces._cargar()["Ana"]["veces"] == 2
    assert voces.similitud(voces._cargar()["Ana"]["huella"], ANA) == pytest.approx(0.7071, abs=1e-3)


def test_un_fallo_al_guardar_voces_no_rompe_nada(monkeypatch, tmp_path):
    def falla(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(voces, "recordar_nombrados", falla)
    json_path = _json(tmp_path)

    resultado = runner.invoke(app, ["nombres", str(json_path), "Ana,Luis"])

    assert resultado.exit_code == 0, resultado.output


def test_un_fallo_al_reconocer_no_rompe_nada(monkeypatch, tmp_path, escuchar):
    def falla(*a, **k):
        raise OSError("voces.json ilegible")

    monkeypatch.setattr(voces, "parecidos", falla)
    json_path = _json(tmp_path)

    resultado = runner.invoke(app, ["nombres", str(json_path), "-e"])

    assert resultado.exit_code == 0, resultado.output
    assert escuchar.llamadas[0]["sugerencias"] == {}


# --- Configuración ---

class Guion:
    """Respuestas en cola para menu.elegir / menu.si_no; anota cada pregunta y sus opciones."""

    def __init__(self, monkeypatch):
        self.cola, self.hechas = [], []
        monkeypatch.setattr(menu, "elegir", self._elegir)
        monkeypatch.setattr(menu, "si_no", lambda m, defecto=True, volver=True: self._elegir(m, [True, False], defecto))

    def __call__(self, *respuestas):
        self.cola.extend(respuestas)

    def _elegir(self, mensaje, opciones, defecto=None, volver=True, texto_volver=None):
        self.hechas.append((mensaje, [o[0] if isinstance(o, tuple) else o for o in opciones], defecto))
        esperada, respuesta = self.cola.pop(0)
        assert esperada in mensaje, f"Esperaba «{esperada}» y preguntó «{mensaje}»"
        if respuesta is menu.Atras:
            raise menu.Atras
        return respuesta


@pytest.fixture
def guion(monkeypatch):
    g = Guion(monkeypatch)
    yield g
    assert not g.cola, f"Quedaron respuestas sin usar: {g.cola}"


def _textos_de_la_lista(guion):
    return next(op for m, op, _ in guion.hechas if m.startswith("¿Qué quieres cambiar?"))


def test_reconocer_voces_viene_encendido_de_fabrica():
    assert ajustes.valor("reconocer_voces") is True


def test_configuracion_apagar_y_encender_el_reconocimiento(guion):
    guion(("¿Qué quieres cambiar?", "reconocer_voces"), ("¿Reconozco por la voz", False),
          ("¿Algo más?", "reconocer_voces"), ("¿Reconozco por la voz", True),
          ("¿Algo más?", menu.Atras))

    menu.flujo_configuracion()

    assert ajustes.valor("reconocer_voces") is True
    assert "Reconocer voces: sí" in _textos_de_la_lista(guion)
    apagar = next(op for m, op, _ in guion.hechas if m.startswith("¿Reconozco"))
    # Al apagar, el texto aclara que las voces ya guardadas no se borran
    assert any("no se borran" in t for t in apagar)
    assert any("solo en este computador" in t for t in apagar)


def test_apagar_el_reconocimiento_no_borra_las_voces(guion):
    voces.recordar("Ana", ANA)
    guion(("¿Qué quieres cambiar?", "reconocer_voces"), ("¿Reconozco por la voz", False),
          ("¿Algo más?", menu.Atras))

    menu.flujo_configuracion()

    assert ajustes.valor("reconocer_voces") is False
    assert voces.conocidas() == ["Ana"]


def test_sin_voces_guardadas_no_aparece_la_entrada(guion):
    guion(("¿Qué quieres cambiar?", menu.Atras))

    menu.flujo_configuracion()

    assert not any(t.startswith("Voces guardadas") for t in _textos_de_la_lista(guion))


def test_configuracion_olvidar_una_voz(guion):
    voces.recordar("Ana", ANA)
    voces.recordar("Luis", LUIS)
    guion(("¿Qué quieres cambiar?", "voces_guardadas"), ("Voces guardadas", "Ana"),
          ("¿Olvido la voz de Ana", True), ("Voces guardadas", menu.Atras),
          ("¿Algo más?", menu.Atras))

    menu.flujo_configuracion()

    assert voces.conocidas() == ["Luis"]
    assert "Voces guardadas: 2" in _textos_de_la_lista(guion)


def test_olvidar_una_voz_pide_confirmacion(guion):
    voces.recordar("Ana", ANA)
    guion(("¿Qué quieres cambiar?", "voces_guardadas"), ("Voces guardadas", "Ana"),
          ("¿Olvido la voz de Ana", False), ("Voces guardadas", menu.Atras),
          ("¿Algo más?", menu.Atras))

    menu.flujo_configuracion()

    assert voces.conocidas() == ["Ana"]


def test_configuracion_olvidar_todas_con_confirmacion(guion):
    voces.recordar("Ana", ANA)
    voces.recordar("Luis", LUIS)
    guion(("¿Qué quieres cambiar?", "voces_guardadas"),
          ("Voces guardadas", menu._OLVIDAR_TODAS), ("¿Seguro que olvido todas", False),
          ("Voces guardadas", menu._OLVIDAR_TODAS), ("¿Seguro que olvido todas", True),
          ("¿Algo más?", menu.Atras))

    menu.flujo_configuracion()

    assert voces.conocidas() == []
