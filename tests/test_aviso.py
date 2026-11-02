# Ubicación: tests/test_aviso.py
# Pruebas de src/aviso.py: todo se simula (no hay Mac ni Windows aquí), se revisan comandos exactos.
import base64
import ctypes
import signal
import subprocess
import sys
import types

import pytest

from src import aviso

# Ruta completa del PowerShell de Windows: por nombre, Windows usaría uno de la carpeta actual
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


class Registro:
    """Falso subprocess.run/Popen que anota las llamadas."""

    def __init__(self, codigo=0):
        self.llamadas = []
        self.codigo = codigo
        self.procesos = []

    def run(self, comando, **kw):
        self.llamadas.append((comando, kw))
        return types.SimpleNamespace(returncode=self.codigo)

    def popen(self, comando, **kw):
        self.llamadas.append((comando, kw))
        p = types.SimpleNamespace(terminado=False)
        p.terminate = lambda: setattr(p, "terminado", True)
        p.wait = lambda timeout=None: 0
        self.procesos.append(p)
        return p


@pytest.fixture
def reg(monkeypatch):
    r = Registro()
    monkeypatch.setattr(subprocess, "run", r.run)
    monkeypatch.setattr(subprocess, "Popen", r.popen)
    return r


def decodificar(comando):
    return base64.b64decode(comando[comando.index("-EncodedCommand") + 1]).decode("utf-16-le")


@pytest.fixture
def windll(monkeypatch):
    llamadas = []
    k = types.SimpleNamespace(SetThreadExecutionState=lambda v: llamadas.append(v))
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=k), raising=False)
    return llamadas


# --- sin_dormir -------------------------------------------------------------
def test_sin_dormir_mac_lanza_y_cierra_caffeinate(monkeypatch, reg):
    monkeypatch.setattr(sys, "platform", "darwin")
    with aviso.sin_dormir():
        assert reg.llamadas[0][0][:3] == ["caffeinate", "-i", "-w"]
        assert reg.llamadas[0][0][3] == str(__import__("os").getpid())
        assert not reg.procesos[0].terminado
    assert reg.procesos[0].terminado


def test_sin_dormir_windows_pide_y_suelta(monkeypatch, windll):
    monkeypatch.setattr(sys, "platform", "win32")
    with aviso.sin_dormir():
        assert windll == [0x80000000 | 0x00000001]
    assert windll == [0x80000001, 0x80000000]


def test_sin_dormir_linux_no_hace_nada(monkeypatch, reg):
    monkeypatch.setattr(sys, "platform", "linux")
    with aviso.sin_dormir():
        pass
    assert reg.llamadas == []


def test_sin_dormir_con_fallos_no_rompe_el_bloque(monkeypatch):
    def falla(*a, **k):
        raise OSError("no existe")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "Popen", falla)
    ejecutado = []
    with aviso.sin_dormir():
        ejecutado.append(1)
    assert ejecutado == [1]


def test_sin_dormir_no_traga_errores_del_bloque(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ValueError):
        with aviso.sin_dormir():
            raise ValueError("x")


# --- notificar --------------------------------------------------------------
def test_notificar_mac_pasa_texto_como_argumentos(monkeypatch, reg):
    monkeypatch.setattr(sys, "platform", "darwin")
    titulo, mensaje = 'Reunión "final" \\ año', 'Listo "ya" ñandú 🎉'
    aviso.notificar(titulo, mensaje)
    comando = reg.llamadas[0][0]
    assert comando[0] == "osascript"
    assert comando[-2:] == [titulo, mensaje]
    codigo = " ".join(comando[:-2])
    assert "Reunión" not in codigo and "ñandú" not in codigo
    assert 'sound name "Glass"' in codigo and "on run argv" in codigo


def test_notificar_windows_no_interpola_el_texto(monkeypatch, reg):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("SystemRoot", raising=False)  # sin la variable: C:\Windows
    monkeypatch.setitem(sys.modules, "winsound", types.SimpleNamespace(MessageBeep=lambda: None))
    titulo, mensaje = "'; Remove-Item -Recurse C:\\ #", '"$(calc)" ñ'
    aviso.notificar(titulo, mensaje)
    comando, kw = reg.llamadas[0]
    assert comando[:6] == [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand"]
    script = decodificar(comando)
    assert "Remove-Item" not in script and "calc" not in script
    assert "$env:AVISO_TITULO" in script and "ToastText02" in script
    assert r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe" in script
    assert kw["env"]["AVISO_TITULO"] == titulo and kw["env"]["AVISO_MENSAJE"] == mensaje
    assert "timeout" in kw


def test_notificar_windows_suena_aunque_falle_el_aviso(monkeypatch):
    sonidos = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winsound", types.SimpleNamespace(MessageBeep=lambda: sonidos.append(1)))

    def falla(*a, **k):
        raise subprocess.TimeoutExpired("powershell", 10)

    monkeypatch.setattr(subprocess, "run", falla)
    aviso.notificar("a", "b")  # no lanza
    assert sonidos == [1]


def test_notificar_linux_usa_notify_send_si_existe(monkeypatch, reg):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/notify-send")
    aviso.notificar("T", "M")
    assert reg.llamadas[0][0] == ["notify-send", "T", "M"]


def test_notificar_linux_sin_notify_send_no_hace_nada(monkeypatch, reg):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("shutil.which", lambda n: None)
    aviso.notificar("T", "M")
    assert reg.llamadas == []


def test_notificar_nunca_lanza(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    aviso.notificar("T", "M")


# --- portapapeles -----------------------------------------------------------
def test_portapapeles_mac_usa_utf8_y_lang(monkeypatch, reg):
    monkeypatch.setattr(sys, "platform", "darwin")
    texto = "Canción ñandú 🎉"
    assert aviso.copiar_al_portapapeles(texto) is True
    comando, kw = reg.llamadas[0]
    assert comando == ["pbcopy"]
    assert kw["input"] == texto.encode("utf-8")
    assert kw["env"]["LANG"] == "en_US.UTF-8" and kw["env"]["LC_ALL"] == "en_US.UTF-8"


def test_portapapeles_windows_archivo_utf8_y_borra_temporal(monkeypatch):
    import os

    monkeypatch.setattr(sys, "platform", "win32")
    visto = {}

    def run(comando, **kw):
        ruta = kw["env"]["AVISO_ARCHIVO"]
        with open(ruta, "rb") as f:
            visto["contenido"] = f.read()
        visto["ruta"] = ruta
        visto["script"] = decodificar(comando)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    texto = "Canción ñandú 🎉 ' $x"
    assert aviso.copiar_al_portapapeles(texto) is True
    assert visto["contenido"] == texto.encode("utf-8")
    assert visto["script"] == "Get-Content -Raw -Encoding UTF8 -LiteralPath $env:AVISO_ARCHIVO | Set-Clipboard"
    assert not os.path.exists(visto["ruta"])


def test_portapapeles_windows_falla_devuelve_false_y_borra(monkeypatch):
    import os

    monkeypatch.setattr(sys, "platform", "win32")
    rutas = []

    def run(comando, **kw):
        rutas.append(kw["env"]["AVISO_ARCHIVO"])
        raise subprocess.TimeoutExpired("powershell", 15)

    monkeypatch.setattr(subprocess, "run", run)
    assert aviso.copiar_al_portapapeles("hola") is False
    assert not os.path.exists(rutas[0])


def test_portapapeles_linux_prefiere_wl_copy_luego_xclip(monkeypatch, reg):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("shutil.which", lambda n: "/x/" + n)
    assert aviso.copiar_al_portapapeles("á") is True
    assert reg.llamadas[0][0] == ["wl-copy"]
    monkeypatch.setattr("shutil.which", lambda n: "/x/xclip" if n == "xclip" else None)
    aviso.copiar_al_portapapeles("á")
    assert reg.llamadas[1][0] == ["xclip", "-selection", "clipboard"]
    assert reg.llamadas[1][1]["input"] == "á".encode("utf-8")


def test_portapapeles_linux_sin_herramientas_es_false(monkeypatch, reg):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("shutil.which", lambda n: None)
    assert aviso.copiar_al_portapapeles("a") is False


def test_portapapeles_mac_sin_pbcopy_es_false(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert aviso.copiar_al_portapapeles("a") is False


# --- confirmar_cancelar -----------------------------------------------------
class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_antes_del_minuto_cancela_directo():
    reloj, avisos = Reloj(), []
    with aviso.confirmar_cancelar(60, avisos.append, 5, reloj=reloj):
        manejador = signal.getsignal(signal.SIGINT)
        reloj.t += 59
        with pytest.raises(KeyboardInterrupt):
            manejador(signal.SIGINT, None)
    assert avisos == []


def test_despues_del_minuto_pide_confirmar_y_el_segundo_cancela():
    reloj, avisos = Reloj(), []
    with aviso.confirmar_cancelar(60, avisos.append, 5, reloj=reloj):
        manejador = signal.getsignal(signal.SIGINT)
        reloj.t += 61
        manejador(signal.SIGINT, None)  # no lanza
        assert avisos == ["¿Seguro? Aprieta Ctrl+C otra vez para cancelar."]
        reloj.t += 4
        with pytest.raises(KeyboardInterrupt):
            manejador(signal.SIGINT, None)


def test_si_pasa_la_ventana_vuelve_a_pedir_confirmacion():
    reloj, avisos = Reloj(), []
    with aviso.confirmar_cancelar(60, avisos.append, 5, reloj=reloj):
        manejador = signal.getsignal(signal.SIGINT)
        reloj.t += 100
        manejador(signal.SIGINT, None)
        reloj.t += 6
        manejador(signal.SIGINT, None)  # ventana vencida: de nuevo solo avisa
        assert len(avisos) == 2
        reloj.t += 1
        with pytest.raises(KeyboardInterrupt):
            manejador(signal.SIGINT, None)


def test_restaura_el_manejador_anterior():
    antes = signal.getsignal(signal.SIGINT)
    with aviso.confirmar_cancelar(reloj=Reloj()):
        assert signal.getsignal(signal.SIGINT) is not antes
    assert signal.getsignal(signal.SIGINT) is antes


def test_fuera_del_hilo_principal_no_toca_nada():
    import threading

    antes = signal.getsignal(signal.SIGINT)
    resultado = []

    def trabajo():
        with aviso.confirmar_cancelar(reloj=Reloj()):
            resultado.append(signal.getsignal(signal.SIGINT) is antes)

    h = threading.Thread(target=trabajo)
    h.start()
    h.join()
    assert resultado == [True]


def test_sin_avisar_no_falla():
    reloj = Reloj()
    with aviso.confirmar_cancelar(0, None, 5, reloj=reloj):
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)


def test_powershell_va_con_la_ruta_de_systemroot(monkeypatch, reg):
    # Windows instalado en otra unidad: la ruta sale de SystemRoot, no se adivina
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", r"D:\WINDOWS")
    monkeypatch.setitem(sys.modules, "winsound", types.SimpleNamespace(MessageBeep=lambda: None))
    aviso.notificar("Listo", "Terminó")
    assert reg.llamadas[0][0][0] == r"D:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"


def test_portapapeles_windows_usa_la_ruta_completa(monkeypatch, reg):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("SystemRoot", raising=False)
    assert aviso.copiar_al_portapapeles("hola") is True
    assert reg.llamadas[0][0][0] == POWERSHELL


# --- Sin el token de Hugging Face en los programas que lanzamos -------------------
@pytest.fixture
def con_token(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_secreto")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "hf_secreto")
    monkeypatch.setenv("VARIABLE_NORMAL", "se_queda")


def _sin_token(kw):
    env = kw["env"]
    assert "HF_TOKEN" not in env and "HUGGING_FACE_HUB_TOKEN" not in env
    assert env["VARIABLE_NORMAL"] == "se_queda"  # el resto del entorno se hereda igual
    return env


def test_caffeinate_no_hereda_el_token(monkeypatch, reg, con_token):
    monkeypatch.setattr(sys, "platform", "darwin")
    with aviso.sin_dormir():
        pass
    _sin_token(reg.llamadas[0][1])


def test_notificar_no_hereda_el_token_en_ningun_sistema(monkeypatch, reg, con_token):
    monkeypatch.setitem(sys.modules, "winsound", types.SimpleNamespace(MessageBeep=lambda: None))
    monkeypatch.setattr(aviso.shutil, "which", lambda c: "/usr/bin/" + c)
    for plataforma in ("darwin", "win32", "linux"):
        monkeypatch.setattr(sys, "platform", plataforma)
        aviso.notificar("Listo", "Terminó")
    assert len(reg.llamadas) == 3
    for _, kw in reg.llamadas:
        _sin_token(kw)
    # PowerShell conserva sus variables propias
    assert reg.llamadas[1][1]["env"]["AVISO_TITULO"] == "Listo"


def test_portapapeles_no_hereda_el_token_en_ningun_sistema(monkeypatch, reg, con_token):
    monkeypatch.setattr(aviso.shutil, "which", lambda c: "/usr/bin/" + c)
    for plataforma in ("darwin", "win32", "linux"):
        monkeypatch.setattr(sys, "platform", plataforma)
        assert aviso.copiar_al_portapapeles("hola") is True
    mac, windows, linux = (kw for _, kw in reg.llamadas)
    assert _sin_token(mac)["LANG"] == "en_US.UTF-8"
    assert "AVISO_ARCHIVO" in _sin_token(windows)
    _sin_token(linux)
