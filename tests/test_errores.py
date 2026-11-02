# Ubicación: tests/test_errores.py
# Pruebas de «errores con salida» (src/errores.py, cli._mostrar_error, menu._ejecutar) y de la
# conexión con src/aviso.py (no dormir, confirmar Ctrl+C y notificar al terminar) en cli.ejecutar_transcripcion.
import errno
import socket
import sys
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from src import aviso, cli, config, errores, historial, menu, procesador

runner = CliRunner()


def _encadenado(causa, mensaje="falló"):
    try:
        try:
            raise causa
        except Exception as c:
            raise RuntimeError(mensaje) from c
    except RuntimeError as e:
        return e


# --- Mensajes simples ----------------------------------------------------------

def test_falta_token():
    e = ValueError("Falta HF_TOKEN. Pon tu clave en .env")
    assert errores.mensaje_simple(e) == errores.MENSAJE_FALTA_TOKEN


class ConnectionError(Exception):  # como el de requests/urllib3/httpx: se detecta por el nombre del tipo
    pass


@pytest.mark.parametrize("error", [
    ConnectionError("boom"),
    socket.gaierror(8, "nodename nor servname provided"),
    urllib.error.URLError("algo"),
    OSError("[Errno -3] Temporary failure in name resolution"),
    RuntimeError("HTTPSConnectionPool: Max retries exceeded with url"),
    RuntimeError("getaddrinfo failed"),
    RuntimeError("Failed to resolve 'huggingface.co'"),
    RuntimeError("Network is unreachable"),
    RuntimeError("No address associated with hostname"),
])
def test_sin_internet(error):
    assert errores.mensaje_simple(error) == errores.MENSAJE_SIN_INTERNET


def test_sin_internet_en_una_causa_encadenada():
    assert errores.mensaje_simple(_encadenado(ConnectionError("x"))) == errores.MENSAJE_SIN_INTERNET


@pytest.mark.parametrize("texto", [
    "Invalid data found when processing input", "Output file does not contain any stream",
    "Could not find codec parameters", "Failed to load audio: ffmpeg", "moov atom not found",
])
def test_no_es_audio(texto):
    assert errores.mensaje_simple(RuntimeError(texto)) == errores.MENSAJE_NO_ES_AUDIO
    assert errores.mensaje_simple(_encadenado(RuntimeError(texto))) == errores.MENSAJE_NO_ES_AUDIO


def test_disco_lleno():
    e = _encadenado(OSError(errno.ENOSPC, "No space left on device"))
    assert errores.mensaje_simple(e) == errores.MENSAJE_DISCO_LLENO


def test_archivo_no_encontrado_con_ruta():
    e = FileNotFoundError(errno.ENOENT, "No such file", "/x/clase.mp3")
    assert errores.mensaje_simple(e) == "No encuentro el archivo: /x/clase.mp3"


def test_error_desconocido_no_tiene_mensaje_simple():
    assert errores.mensaje_simple(RuntimeError("boom")) is None
    assert errores.mensaje_simple(FileNotFoundError("sin ruta")) is None


def test_cadena_no_cae_en_ciclos():
    a, b = RuntimeError("a"), RuntimeError("b")
    a.__cause__, b.__cause__ = b, a
    assert errores.cadena(a) == [a, b]


# --- Archivo con el detalle ----------------------------------------------------

def test_guardar_detalle_contenido(monkeypatch):
    monkeypatch.setenv("SECRETO_DEL_ENTORNO", "valor-privado-123")
    monkeypatch.setattr(config, "HF_TOKEN", "hf_abc123")
    monkeypatch.setattr(sys, "argv", ["transcriptor", "transcribir", "a.mp3"])
    e = _encadenado(ValueError("token hf_abc123 inválido"), "falló con hf_abc123")

    ruta = errores.guardar_detalle(e)

    assert ruta.parent == historial.carpeta() / "errores"
    assert len(ruta.stem) == len("2026-10-30_101500")
    texto = ruta.read_text(encoding="utf-8")
    for esperado in ("Fecha:", "Versión del programa:", "Sistema:", sys.platform, "Python:",
                     "transcriptor transcribir a.mp3", "RuntimeError", "ValueError", "Traceback",
                     "direct cause"):
        assert esperado in texto
    assert "hf_abc123" not in texto and "***" in texto
    assert "valor-privado-123" not in texto and "SECRETO_DEL_ENTORNO" not in texto


def test_guardar_detalle_conserva_solo_30(monkeypatch):
    carpeta = historial.carpeta() / "errores"
    carpeta.mkdir(parents=True)
    for i in range(35):
        (carpeta / f"2020-01-01_{i:06d}.txt").write_text("viejo")

    nueva = errores.guardar_detalle(RuntimeError("x"))

    archivos = sorted(carpeta.glob("*.txt"))
    assert len(archivos) == 30
    assert nueva in archivos
    assert not (carpeta / "2020-01-01_000000.txt").exists()


def test_guardar_detalle_dos_errores_en_el_mismo_segundo():
    a = errores.guardar_detalle(RuntimeError("1"))
    b = errores.guardar_detalle(RuntimeError("2"))
    assert a != b and a.exists() and b.exists()


def test_guardar_detalle_sin_permiso_no_rompe(monkeypatch, tmp_path):
    bloqueo = tmp_path / "archivo"
    bloqueo.write_text("no soy una carpeta")
    monkeypatch.setenv("TRANSCRIPTOR_HOME", str(bloqueo))
    assert errores.guardar_detalle(RuntimeError("x")) is None


def test_ruta_corta_usa_tilde(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert errores.ruta_corta(tmp_path / "a" / "b.txt") == str(Path("~") / "a" / "b.txt")
    assert errores.ruta_corta(Path("/otra/cosa.txt")) == str(Path("/otra/cosa.txt"))


# --- El recuadro de error ------------------------------------------------------

def test_recuadro_muestra_mensaje_simple_y_ruta(monkeypatch):
    monkeypatch.setattr(procesador, "procesar_entrada", MagicMock(side_effect=OSError(errno.ENOSPC, "lleno")))

    resultado = runner.invoke(cli.app, ["transcribir", "clase.mp3"])

    assert resultado.exit_code == 1
    assert "El disco está lleno" in resultado.output
    assert "El detalle quedó guardado en" in resultado.output
    assert "-v" not in resultado.output
    assert cli.ultimo_error.exists()


def test_sin_internet_activado_tiene_prioridad(monkeypatch):
    class LocalEntryNotFoundError(FileNotFoundError):
        pass

    def falla(*a, **k):
        raise _encadenado(LocalEntryNotFoundError("Cannot find"), "getaddrinfo failed")

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setattr(procesador, "procesar_entrada", falla)

    resultado = runner.invoke(cli.app, ["transcribir", "clase.mp3"])

    assert "Sin internet" in resultado.output
    assert "No hay conexión" not in resultado.output


def test_ultimo_error_se_limpia_al_empezar(monkeypatch):
    cli.ultimo_error = Path("/viejo.txt")
    monkeypatch.setattr(procesador, "procesar_entrada", MagicMock(side_effect=RuntimeError("boom")))
    runner.invoke(cli.app, ["transcribir", "clase.mp3"])
    assert cli.ultimo_error != Path("/viejo.txt")

    monkeypatch.setattr(procesador, "procesar_entrada", lambda *a, **k: procesador.Resultado(
        audio_path=Path("a.mp3"), txt_path=Path("a.blocks.txt"), json_path=None, parrafos=[], duracion=1.0))
    runner.invoke(cli.app, ["transcribir", "clase.mp3", "--sin-preguntas"])
    assert cli.ultimo_error is None


def test_detalle_sigue_imprimiendo_el_traceback(monkeypatch):
    monkeypatch.setattr(procesador, "procesar_entrada", MagicMock(side_effect=RuntimeError("boom")))
    resultado = runner.invoke(cli.app, ["transcribir", "clase.mp3", "-v"])
    assert "Traceback" in resultado.output


# --- Menú: ¿Qué hago? ----------------------------------------------------------

class Respuestas:
    """Falso menu.elegir: responde en orden; None = Esc (Atras)."""

    def __init__(self, monkeypatch, *respuestas):
        self.respuestas = list(respuestas)
        self.preguntas = []
        monkeypatch.setattr(menu, "elegir", self.elegir)

    def elegir(self, mensaje, opciones, *a, **k):
        self.preguntas.append((mensaje, opciones, k))
        r = self.respuestas.pop(0)
        if r is None:
            raise menu.Atras
        return r


def _comando_que_falla(codigo, archivo):
    def comando(**kw):
        cli.ultimo_error = archivo
        raise typer.Exit(codigo)
    return comando


def test_menu_ver_copiar_y_volver(monkeypatch, tmp_path, capsys):
    archivo = tmp_path / "e.txt"
    archivo.write_text("DETALLE-DEL-ERROR", encoding="utf-8")
    copiado = []
    monkeypatch.setattr(aviso, "copiar_al_portapapeles", lambda t: copiado.append(t) or True)
    r = Respuestas(monkeypatch, "ver", "copiar", None)

    assert menu._ejecutar(_comando_que_falla(1, archivo)) is None

    assert [p[0] for p in r.preguntas] == ["¿Qué hago?"] * 3
    assert [o[0] for o in r.preguntas[0][1]] == ["Ver el detalle", "Copiar el error"]
    assert r.preguntas[0][2]["texto_volver"] == "Volver al menú"
    assert copiado == ["DETALLE-DEL-ERROR"]
    salida = capsys.readouterr().out
    assert "DETALLE-DEL-ERROR" in salida and "✓ Copiado" in salida


def test_menu_copiar_que_falla_avisa(monkeypatch, tmp_path, capsys):
    archivo = tmp_path / "e.txt"
    archivo.write_text("x", encoding="utf-8")
    monkeypatch.setattr(aviso, "copiar_al_portapapeles", lambda t: False)
    Respuestas(monkeypatch, "copiar", None)

    menu._ejecutar(_comando_que_falla(1, archivo))

    assert "No pude copiarlo" in capsys.readouterr().err


def test_menu_cancelar_no_pregunta(monkeypatch, tmp_path):
    archivo = tmp_path / "e.txt"
    archivo.write_text("x", encoding="utf-8")
    r = Respuestas(monkeypatch)
    menu._ejecutar(_comando_que_falla(130, archivo))
    assert r.preguntas == []


def test_menu_sin_error_guardado_no_pregunta(monkeypatch):
    def comando(**kw):
        raise typer.Exit(1)
    r = Respuestas(monkeypatch)
    menu._ejecutar(comando)
    assert r.preguntas == []


# --- No dormir y avisar al terminar -------------------------------------------

@pytest.fixture
def aviso_falso(monkeypatch):
    """Anota cómo se usa aviso desde cli; el reloj avanza con el trabajo simulado."""
    eventos = []
    reloj = {"extra": 0.0}

    @contextmanager
    def sin_dormir():
        eventos.append("sin_dormir")
        yield

    @contextmanager
    def confirmar_cancelar(despues_de=60, avisar=None, **k):
        eventos.append(("confirmar", despues_de))
        avisar("hola")
        yield

    monkeypatch.setattr(aviso, "sin_dormir", sin_dormir)
    monkeypatch.setattr(aviso, "confirmar_cancelar", confirmar_cancelar)
    monkeypatch.setattr(aviso, "notificar", lambda t, m: eventos.append(("notificar", t, m)))
    real = cli.time.monotonic
    monkeypatch.setattr(cli.time, "monotonic", lambda: real() + reloj["extra"])
    monkeypatch.setattr(cli, "_es_interactivo", lambda: True)
    monkeypatch.setattr(cli, "_quiere_poner_nombres", lambda m, c: eventos.append("pregunta_nombres") or False)

    def procesar(segundos, diarizar=False):
        def fake(entrada, modelo, **kw):
            reloj["extra"] += segundos
            return procesador.Resultado(
                audio_path=Path("/t/reunion.mp3"), txt_path=Path("/t/2026-10-30 Reunión.blocks.txt"),
                json_path=Path("/t/x.blocks.json") if diarizar else None,
                parrafos=[{"start": 0, "end": 5, "text": "Hola", "speaker": "Ana"}] if diarizar else [],
                duracion=108.0)
        monkeypatch.setattr(procesador, "procesar_entrada", fake)

    return eventos, procesar


def test_sin_dormir_siempre_incluso_sin_preguntas(aviso_falso):
    eventos, procesar = aviso_falso
    procesar(100)
    cli.ejecutar_transcripcion("a.mp3", "turbo", sin_preguntas=True)
    assert "sin_dormir" in eventos


def test_sin_preguntas_no_confirma_ni_notifica(aviso_falso):
    eventos, procesar = aviso_falso
    procesar(100)
    cli.ejecutar_transcripcion("a.mp3", "turbo", sin_preguntas=True)
    assert not any(isinstance(x, tuple) for x in eventos)


def test_sin_terminal_no_confirma_ni_notifica(aviso_falso, monkeypatch):
    eventos, procesar = aviso_falso
    monkeypatch.setattr(cli, "_es_interactivo", lambda: False)
    procesar(100)
    cli.ejecutar_transcripcion("a.mp3", "turbo")
    assert not any(isinstance(x, tuple) for x in eventos)


def test_interactivo_confirma_ctrl_c_y_notifica_antes_de_los_nombres(aviso_falso, capsys):
    eventos, procesar = aviso_falso
    procesar(100, diarizar=True)

    cli.ejecutar_transcripcion("a.mp3", "turbo", hablantes=True)

    assert ("confirmar", 60) in eventos
    assert ("notificar", "Transcripción lista", "Listo: 2026-10-30 Reunión, 1 min 48 s") in eventos
    assert eventos.index(("notificar", "Transcripción lista", "Listo: 2026-10-30 Reunión, 1 min 48 s")) \
        < eventos.index("pregunta_nombres")
    assert "hola" in capsys.readouterr().out  # el aviso sale por la consola de Rich


def test_no_notifica_si_tardo_un_minuto_o_menos(aviso_falso):
    eventos, procesar = aviso_falso
    procesar(30, diarizar=True)
    cli.ejecutar_transcripcion("a.mp3", "turbo", hablantes=True)
    assert not any(isinstance(x, tuple) and x[0] == "notificar" for x in eventos)


def test_no_notifica_si_falla(aviso_falso, monkeypatch):
    eventos, _ = aviso_falso
    monkeypatch.setattr(procesador, "procesar_entrada", MagicMock(side_effect=RuntimeError("boom")))
    with pytest.raises(typer.Exit):
        cli.ejecutar_transcripcion("a.mp3", "turbo")
    assert not any(isinstance(x, tuple) and x[0] == "notificar" for x in eventos)


# --- Permisos: el detalle trae rutas y comandos; solo lo lee quien usa el programa ---

@pytest.mark.skipif(sys.platform == "win32", reason="en Windows no hay permisos POSIX")
def test_detalle_de_error_queda_privado():
    import os
    import stat
    anterior = os.umask(0o022)
    try:
        ruta = errores.guardar_detalle(RuntimeError("x"))
    finally:
        os.umask(anterior)
    assert stat.S_IMODE(os.stat(ruta).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(ruta.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(historial.carpeta()).st_mode) == 0o700


def test_detalle_mismo_contenido_que_armar_detalle(monkeypatch):
    from datetime import datetime
    momento = datetime(2026, 10, 30, 10, 15, 0)

    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return momento

    monkeypatch.setattr(errores, "datetime", Reloj)
    e = RuntimeError("x")
    ruta = errores.guardar_detalle(e)
    assert ruta.read_bytes() == errores.armar_detalle(e, momento).encode("utf-8")


def test_detalle_en_windows_no_lanza(monkeypatch):
    from utils import archivos
    monkeypatch.setattr(archivos, "_es_windows", lambda: True)
    monkeypatch.delattr(archivos.os, "getuid", raising=False)
    monkeypatch.setattr(archivos.os, "chmod", lambda *a, **k: None)
    ruta = errores.guardar_detalle(RuntimeError("x"))
    assert ruta is not None and ruta.exists()
