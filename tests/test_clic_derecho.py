# Ubicación: tests/test_clic_derecho.py
# Pruebas del clic derecho: el comando oculto `en-fila` (con la transcripción simulada) y la
# instalación en Mac (Automator) y Windows (acceso directo en Enviar a), simuladas con sys.platform y carpetas
# temporales, y la fila (el candado con bloqueo del sistema; el de Windows con un msvcrt falso).
import base64
import json
import os
import plistlib
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from src import ajustes, aviso, clic_derecho, cli, config, historial, plataforma
from src.cli import app


@pytest.fixture
def audios(tmp_path):
    carpeta = tmp_path / "audios"
    carpeta.mkdir()
    lista = []
    for nombre in ("a.m4a", "b.mp3"):
        ruta = carpeta / nombre
        ruta.write_bytes(b"")
        lista.append(ruta)
    return lista


@pytest.fixture
def entorno(monkeypatch):
    """Notificaciones y transcripción simuladas; devuelve (transcribir, notificar)."""
    notificar = MagicMock()
    monkeypatch.setattr(aviso, "notificar", notificar)
    transcribir = MagicMock(side_effect=lambda *a, **k: SimpleNamespace(duracion=65))
    monkeypatch.setattr(cli, "ejecutar_transcripcion", transcribir)
    monkeypatch.setattr(cli, "_hablantes_para_clic_derecho", lambda: False)
    return transcribir, notificar


def lanzar(*archivos):
    return CliRunner().invoke(app, ["en-fila", *map(str, archivos)])


def test_en_fila_esta_oculto():
    salida = CliRunner().invoke(app, ["--help"]).output
    assert "en-fila" not in salida


def test_usa_la_configuracion_y_el_titulo(audios, entorno, tmp_path):
    transcribir, notificar = entorno
    ajustes.guardar(modelo="small", idioma="en", carpeta_salida=str(tmp_path / "salida"))
    resultado = lanzar(audios[0])
    assert resultado.exit_code == 0, resultado.output
    args, kwargs = transcribir.call_args
    assert args[0] == str(audios[0]) and args[1] == "small"
    assert kwargs["idioma"] == "en"
    assert kwargs["salida"] == tmp_path / "salida"
    assert kwargs["sin_preguntas"] is True and kwargs["desde_menu"] is True
    assert kwargs["titulo"] == "a"
    assert isinstance(kwargs["fecha"], date)
    assert kwargs["hablantes"] is False
    notificar.assert_called_once_with("Transcripción lista", "Listo: a, 1 min 05 s")


def test_con_una_persona_en_la_ventana_pregunta_como_el_menu(audios, entorno, monkeypatch):
    # El clic derecho abre una ventana: ahí se ve el avance y se ponen nombres al terminar
    transcribir, notificar = entorno
    monkeypatch.setattr(cli, "_es_interactivo", lambda: True)
    resultado = lanzar(*audios[:2])
    assert resultado.exit_code == 0, resultado.output
    assert all(llamada.kwargs["sin_preguntas"] is False for llamada in transcribir.call_args_list)
    notificar.assert_not_called()  # el aviso de «lista» ya lo da ejecutar_transcripcion si tardó
    assert "Archivo 1 de 2" in resultado.output and "Archivo 2 de 2" in resultado.output
    assert "Ya puedes cerrar esta ventana" in resultado.output


def test_salta_inexistentes_y_lo_que_no_es_audio(audios, entorno, tmp_path):
    transcribir, notificar = entorno
    texto = tmp_path / "nota.txt"
    texto.write_text("hola")
    resultado = lanzar(tmp_path / "no_existe.mp3", texto, audios[0])
    assert resultado.exit_code == 0
    assert transcribir.call_count == 1


def test_un_nombre_con_corchetes_se_muestra_tal_cual(audios, entorno, tmp_path):
    # Rich leía «[final]» del nombre como una etiqueta de estilo y la borraba del aviso
    transcribir, _ = entorno
    raro = tmp_path / "notas [final].txt"
    raro.write_text("hola")
    resultado = lanzar(raro, audios[0])
    assert resultado.exit_code == 0, resultado.output
    assert transcribir.call_count == 1
    assert "notas [final].txt" in resultado.output


def test_sigue_tras_un_fallo_y_sale_con_1(audios, entorno):
    transcribir, notificar = entorno
    transcribir.side_effect = [typer.Exit(1), SimpleNamespace(duracion=5)]
    resultado = lanzar(*audios)
    assert resultado.exit_code == 1
    assert transcribir.call_count == 2
    assert notificar.call_args_list[0].args == (
        "No pude transcribir", "a.m4a. Abre Transcriptor para ver el detalle.")
    assert notificar.call_args_list[1].args[0] == "Transcripción lista"


def test_hablantes_segun_configuracion(monkeypatch):
    import importlib.util
    monkeypatch.setattr(config, "HF_TOKEN", "hf_x")
    monkeypatch.setattr(plataforma, "hablantes_disponible", lambda: True)
    monkeypatch.setattr(importlib.util, "find_spec", lambda nombre: object())
    assert cli._hablantes_para_clic_derecho() is True
    ajustes.guardar(modo_hablantes=ajustes.NUNCA)
    assert cli._hablantes_para_clic_derecho() is False
    ajustes.guardar(modo_hablantes=ajustes.SIEMPRE)
    monkeypatch.setattr(config, "HF_TOKEN", None)
    assert cli._hablantes_para_clic_derecho() is False


# --- La fila --------------------------------------------------------------------

def test_el_candado_se_borra_siempre(audios, entorno):
    transcribir, _ = entorno
    transcribir.side_effect = RuntimeError("explotó")
    lanzar(audios[0])
    assert not (historial.carpeta() / "fila.lock").exists()


def _otro_lanzamiento():
    """Simula otro `en-fila` que ya tiene el candado: un open() aparte del mismo archivo, bloqueado.
    En Linux flock excluye entre dos open() distintos aunque sean del mismo proceso."""
    import fcntl
    candado = historial.carpeta() / "fila.lock"
    candado.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(candado, os.O_RDWR | os.O_CREAT)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return candado, descriptor


@pytest.mark.skipif(sys.platform == "win32", reason="usa fcntl")
def test_espera_mientras_otro_lanzamiento_tiene_el_candado():
    candado, otro = _otro_lanzamiento()
    esperas, avisos = [], []

    def esperar(segundos):
        esperas.append(segundos)
        if len(esperas) == 2:  # el otro terminó: suelta (como soltar_candado: borra y desbloquea)
            candado.unlink()
            os.close(otro)

    ruta = clic_derecho.tomar_candado(esperar=esperar, al_esperar=lambda: avisos.append(1))
    assert esperas == [5, 5]
    assert avisos == [1]  # se avisa una sola vez aunque espere varias
    assert ruta == candado and ruta.read_text() == str(os.getpid())
    clic_derecho.soltar_candado(ruta)
    assert not candado.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="usa fcntl")
def test_entra_al_soltarse_aunque_el_archivo_siga_ahi():
    # El otro desbloquea sin borrar el archivo (p. ej. murió: el sistema suelta el bloqueo)
    candado, otro = _otro_lanzamiento()

    def esperar(segundos):
        os.close(otro)

    ruta = clic_derecho.tomar_candado(esperar=esperar)
    assert ruta == candado
    clic_derecho.soltar_candado(ruta)


@pytest.mark.skipif(sys.platform == "win32", reason="usa fcntl")
def test_dos_tomas_en_el_mismo_proceso_se_excluyen():
    # El primero lo tiene; el segundo espera hasta que el primero lo suelta
    primero = clic_derecho.tomar_candado(esperar=MagicMock())
    soltado = []

    def esperar(segundos):
        soltado.append(1)
        clic_derecho.soltar_candado(primero)

    segundo = clic_derecho.tomar_candado(esperar=esperar)
    assert soltado == [1]
    clic_derecho.soltar_candado(segundo)
    assert not segundo.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="usa fcntl")
def test_no_entra_con_el_archivo_que_acaban_de_borrar(monkeypatch):
    # Carrera: abrimos fila.lock justo antes de que quien lo soltaba lo borrara y otro creara uno nuevo.
    # Nuestro bloqueo sería sobre el archivo viejo: hay que darse cuenta y volver a intentarlo.
    candado = historial.carpeta() / "fila.lock"
    candado.parent.mkdir(parents=True, exist_ok=True)
    original = clic_derecho._bloquear
    veces = []

    def bloquear(descriptor):
        veces.append(1)
        if len(veces) == 1:
            candado.unlink()
            candado.write_text("")  # otro archivo con el mismo nombre
        return original(descriptor)

    monkeypatch.setattr(clic_derecho, "_bloquear", bloquear)
    esperar = MagicMock()
    ruta = clic_derecho.tomar_candado(esperar=esperar)
    assert len(veces) == 2 and esperar.call_count == 0
    assert os.fstat(clic_derecho._abiertos[ruta]).st_ino == candado.stat().st_ino
    clic_derecho.soltar_candado(ruta)


def test_un_candado_del_formato_antiguo_no_bloquea():
    # Antes el candado era un archivo con un PID: si quedó tirado, ya no debe hacer esperar
    candado = historial.carpeta() / "fila.lock"
    candado.parent.mkdir(parents=True, exist_ok=True)
    candado.write_text("4242")
    esperar = MagicMock()
    ruta = clic_derecho.tomar_candado(esperar=esperar)
    esperar.assert_not_called()
    # Se lee por el mismo descriptor: en Windows el byte bloqueado no se puede leer desde otro
    descriptor = clic_derecho._abiertos[ruta]
    os.lseek(descriptor, 0, os.SEEK_SET)
    assert os.read(descriptor, 20) == str(os.getpid()).encode()
    clic_derecho.soltar_candado(ruta)


def test_soltar_dos_veces_o_uno_desconocido_no_lanza(tmp_path):
    ruta = clic_derecho.tomar_candado(esperar=MagicMock())
    clic_derecho.soltar_candado(ruta)
    clic_derecho.soltar_candado(ruta)
    clic_derecho.soltar_candado(tmp_path / "otro.lock")
    assert not ruta.exists()


def test_windows_usa_msvcrt(monkeypatch):
    # msvcrt solo existe en Windows: un módulo falso que registra las llamadas y simula que otro lo tiene
    llamadas = []
    ocupado = [True]

    def locking(descriptor, modo, cuantos):
        llamadas.append((modo, cuantos, os.lseek(descriptor, 0, os.SEEK_CUR)))
        if modo == falso.LK_NBLCK and ocupado[0]:
            raise PermissionError(13, "Permission denied")

    falso = SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0, locking=locking)
    monkeypatch.setitem(sys.modules, "msvcrt", falso)
    monkeypatch.setitem(sys.modules, "fcntl", None)  # que no se use por error
    monkeypatch.setattr("sys.platform", "win32")

    def esperar(segundos):
        ocupado[0] = False

    avisos = []
    ruta = clic_derecho.tomar_candado(esperar=esperar, al_esperar=lambda: avisos.append(1))
    assert avisos == [1]
    assert llamadas == [(2, 1, 0), (2, 1, 0)]  # siempre el byte 0, sin esperar (LK_NBLCK)
    assert ruta.read_text() == str(os.getpid())
    clic_derecho.soltar_candado(ruta)
    assert llamadas[-1] == (0, 1, 0)  # LK_UNLCK sobre el mismo byte
    assert not ruta.exists()  # en Windows se borra tras cerrarlo
    clic_derecho.soltar_candado(ruta)  # dos veces no lanza


# --- Mac ------------------------------------------------------------------------

def test_mac_crea_el_workflow_y_se_quita(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(clic_derecho.subprocess, "run", MagicMock())
    monkeypatch.setattr(clic_derecho, "comando_del_programa", lambda: ["/opt/mi programa/transcriptor"])
    assert clic_derecho.disponible() and not clic_derecho.instalado()
    assert clic_derecho.instalar() is True and clic_derecho.instalado()

    base = tmp_path / "Library/Services/Transcribir con Transcriptor.workflow/Contents"
    info = plistlib.loads((base / "Info.plist").read_bytes())
    servicio = info["NSServices"][0]
    assert servicio["NSMenuItem"] == {"default": "Transcribir con Transcriptor"}
    assert servicio["NSMessage"] == "runWorkflowAsService"
    assert servicio["NSRequiredContext"] == {"NSApplicationIdentifier": "com.apple.finder"}
    assert "public.audio" in servicio["NSSendFileTypes"]

    flujo = plistlib.loads((base / "document.wflow").read_bytes())
    accion = flujo["actions"][0]["action"]
    parametros = accion["ActionParameters"]
    assert accion["BundleIdentifier"] == "com.apple.RunShellScript"
    assert parametros["shell"] == "/bin/zsh" and parametros["inputMethod"] == 1
    script = parametros["COMMAND_STRING"]
    # Abre una ventana de Terminal con un .command que lleva el programa y los archivos entre comillas
    assert "'/opt/mi programa/transcriptor'" in script and "en-fila" in script
    assert "${(q)@}" in script and 'open -a Terminal "$f"' in script
    assert flujo["workflowMetaData"]["workflowTypeIdentifier"] == "com.apple.Automator.servicesMenu"

    assert clic_derecho.quitar() is True
    assert not clic_derecho.instalado()


# --- Windows --------------------------------------------------------------------

@pytest.fixture
def windows(tmp_path, monkeypatch):
    """Simula Windows: carpetas temporales y un PowerShell falso que «crea» el .lnk. Devuelve sus llamadas."""
    perfil = tmp_path / "José O'Brien"
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", str(perfil / "AppData/Roaming"))
    monkeypatch.setenv("USERPROFILE", str(perfil))
    monkeypatch.setenv("HOME", str(perfil))  # Path.home() en Linux
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    llamadas = []

    def run(argumentos, **kwargs):
        llamadas.append(SimpleNamespace(argumentos=argumentos, **kwargs))
        Path(kwargs["env"]["TRANSCRIPTOR_LNK"]).write_bytes(b"L\0\0\0")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(clic_derecho.subprocess, "run", run)
    envio = perfil / "AppData/Roaming/Microsoft/Windows/SendTo"
    return SimpleNamespace(perfil=perfil, envio=envio, llamadas=llamadas)


def _script(llamada) -> str:
    argumentos = llamada.argumentos
    return base64.b64decode(argumentos[argumentos.index("-EncodedCommand") + 1]).decode("utf-16-le")


def test_windows_crea_un_acceso_directo_sin_cmd(windows, monkeypatch):
    programa = str(windows.perfil / ".local/bin/transcriptor.exe")
    monkeypatch.setattr(clic_derecho, "comando_del_programa", lambda: [programa])
    assert clic_derecho.instalar() is True and clic_derecho.instalado()
    assert (windows.envio / "Transcriptor.lnk").exists()  # «Transcriptor» en el menú Enviar a

    [llamada] = windows.llamadas
    assert llamada.argumentos[0] == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    entorno = llamada.env
    assert entorno["TRANSCRIPTOR_LNK"] == str(windows.envio / "Transcriptor.lnk")
    assert entorno["TRANSCRIPTOR_DESTINO"] == programa
    assert entorno["TRANSCRIPTOR_ARGUMENTOS"] == "en-fila"
    assert entorno["TRANSCRIPTOR_CARPETA"] == str(windows.perfil)  # la carpeta personal, no la del audio

    script = _script(llamada)
    assert "WScript.Shell" in script and "CreateShortcut" in script and ".Save()" in script
    assert "WindowStyle = 1" in script
    # Nada del usuario va pegado en el script: solo por variables de entorno
    for dato in ("José", "O'Brien", "transcriptor.exe", "Transcriptor.lnk", "en-fila"):
        assert dato not in script
    assert "cmd" not in " ".join(llamada.argumentos).lower()

    assert clic_derecho.quitar() is True
    assert not clic_derecho.instalado()


def test_powershell_y_pbs_no_heredan_el_token(windows, monkeypatch):
    # El acceso directo de Windows conserva sus variables TRANSCRIPTOR_*, pero no el token
    monkeypatch.setenv("HF_TOKEN", "hf_secreto")
    monkeypatch.setenv("VARIABLE_NORMAL", "se_queda")
    monkeypatch.setattr(clic_derecho, "comando_del_programa", lambda: [str(windows.perfil / "t.exe")])
    assert clic_derecho.instalar() is True
    [llamada] = windows.llamadas
    assert "HF_TOKEN" not in llamada.env and llamada.env["VARIABLE_NORMAL"] == "se_queda"
    assert "TRANSCRIPTOR_LNK" in llamada.env

    # En Mac, pbs -update al instalar y al quitar
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("HOME", str(windows.perfil / "mac"))
    run = MagicMock()
    monkeypatch.setattr(clic_derecho.subprocess, "run", run)
    assert clic_derecho.instalar() is True and clic_derecho.quitar() is True
    assert run.call_count == 2
    for llamada in run.call_args_list:
        assert llamada.args[0][0] == "/System/Library/CoreServices/pbs"
        assert "HF_TOKEN" not in llamada.kwargs["env"]


def test_windows_con_python_y_main_py_van_como_argumentos(windows, monkeypatch):
    monkeypatch.setattr(clic_derecho, "comando_del_programa",
                        lambda: [r"C:\Py 3\python.exe", r"C:\Mis cosas\main.py"])
    assert clic_derecho.instalar() is True
    entorno = windows.llamadas[0].env
    assert entorno["TRANSCRIPTOR_DESTINO"] == r"C:\Py 3\python.exe"
    assert entorno["TRANSCRIPTOR_ARGUMENTOS"] == r'"C:\Mis cosas\main.py" en-fila'


def test_windows_borra_el_cmd_antiguo_al_instalar(windows, monkeypatch):
    monkeypatch.setattr(clic_derecho, "comando_del_programa", lambda: ["transcriptor.exe"])
    windows.envio.mkdir(parents=True)
    antiguo = windows.envio / "Transcriptor.cmd"
    antiguo.write_text('@echo off\r\n"transcriptor.exe" en-fila %*\r\n')
    assert clic_derecho.instalar() is True
    assert not antiguo.exists() and (windows.envio / "Transcriptor.lnk").exists()


def test_windows_un_cmd_antiguo_cuenta_como_instalado_y_se_quita(windows):
    windows.envio.mkdir(parents=True)
    antiguo = windows.envio / "Transcriptor.cmd"
    antiguo.write_text("@echo off")
    assert clic_derecho.instalado() is True
    assert clic_derecho.quitar() is True
    assert not antiguo.exists() and not clic_derecho.instalado()


def test_windows_si_powershell_falla_devuelve_false(windows, monkeypatch):
    monkeypatch.setattr(clic_derecho, "comando_del_programa", lambda: ["transcriptor.exe"])
    monkeypatch.setattr(clic_derecho.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stderr=b"bloqueado"))
    assert clic_derecho.instalar() is False
    assert not clic_derecho.instalado()

    def explota(*a, **k):
        raise FileNotFoundError("powershell.exe")

    monkeypatch.setattr(clic_derecho.subprocess, "run", explota)
    assert clic_derecho.instalar() is False


def test_en_linux_no_hay_clic_derecho(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert not clic_derecho.disponible()
    assert clic_derecho.instalar() is False and clic_derecho.quitar() is False
    assert clic_derecho.instalado() is False


@pytest.mark.skipif(shutil.which("zsh") is None, reason="hace falta zsh (el del Mac)")
def test_script_mac_pasa_los_nombres_raros_tal_cual(tmp_path, monkeypatch):
    # Ejecuta el script de la acción con zsh real, cambiando «open -a Terminal» por ejecutar el .command
    falso = tmp_path / "falso.py"
    falso.write_text("import sys, json; print(json.dumps(sys.argv[1:]))")
    monkeypatch.setattr(clic_derecho, "comando_del_programa", lambda: [sys.executable, str(falso)])
    script = clic_derecho._script_mac().replace('open -a Terminal "$f"', 'zsh "$f"')
    nombres = ["/x/Reunión equipo.m4a", "/x/it's $HOME & [v2] \"q\".m4a", "/x/a;b`c`.mp3"]
    salida = subprocess.run(["zsh", "-c", script, "zsh", *nombres], capture_output=True, text=True,
                            env={**os.environ, "TMPDIR": str(tmp_path)})
    assert json.loads(salida.stdout) == ["en-fila", *nombres]
    assert not list(tmp_path.glob("*.command"))  # el .command se borra solo


def test_ctrl_c_detiene_la_fila_sin_avisar_de_fallo(audios, entorno):
    # ejecutar_transcripcion convierte Ctrl+C en Exit(130): no es un fallo ni hay que seguir con el siguiente
    transcribir, notificar = entorno
    transcribir.side_effect = [typer.Exit(130), SimpleNamespace(duracion=5)]
    resultado = lanzar(*audios)
    assert resultado.exit_code == 130
    assert transcribir.call_count == 1
    notificar.assert_not_called()
    assert not (historial.carpeta() / "fila.lock").exists()


def test_keyboard_interrupt_tambien_detiene_la_fila(audios, entorno):
    transcribir, notificar = entorno
    transcribir.side_effect = KeyboardInterrupt
    resultado = lanzar(*audios)
    assert resultado.exit_code == 130
    assert transcribir.call_count == 1
    notificar.assert_not_called()
    assert not (historial.carpeta() / "fila.lock").exists()


def test_sin_persona_la_fila_sigue_pasando_continuar_sin_hablantes(audios, entorno):
    # El flag de procesador lo decide ejecutar_transcripcion según sin_preguntas, que aquí es True
    transcribir, _ = entorno
    lanzar(audios[0])
    assert transcribir.call_args.kwargs["sin_preguntas"] is True


def test_el_candado_se_suelta_antes_de_las_preguntas_y_se_toma_por_archivo(audios, entorno, monkeypatch):
    transcribir, _ = entorno
    candado = historial.carpeta() / "fila.lock"
    estados = []

    def transcribir_falso(*a, **k):
        estados.append(("trabajo", candado.exists()))
        k["al_terminar_trabajo"]()  # lo que hace ejecutar_transcripcion antes de preguntar
        estados.append(("preguntas", candado.exists()))
        return SimpleNamespace(duracion=5)

    transcribir.side_effect = transcribir_falso
    monkeypatch.setattr(cli, "_es_interactivo", lambda: True)
    resultado = lanzar(*audios)
    assert resultado.exit_code == 0, resultado.output
    assert estados == [("trabajo", True), ("preguntas", False)] * 2
    assert not candado.exists()


def test_ejecutar_transcripcion_llama_al_terminar_trabajo_antes_de_preguntar(monkeypatch, tmp_path):
    from src import menu, procesador
    orden = []
    monkeypatch.setattr(cli, "_es_interactivo", lambda: True)
    monkeypatch.setattr(procesador, "procesar_entrada", lambda *a, **k: orden.append("trabajo") or procesador.Resultado(
        audio_path=tmp_path / "a.mp3", txt_path=tmp_path / "a.blocks.txt", json_path=tmp_path / "a.blocks.json",
        parrafos=[{"start": 0, "end": 5, "text": "Hola", "speaker": "Hablante 1"}], duracion=5.0))
    monkeypatch.setattr(cli, "_quiere_poner_nombres", lambda *a: orden.append("pregunta") or False)
    monkeypatch.setattr(cli, "_ofrecer_revision_dudosas", lambda *a: None)
    cli.ejecutar_transcripcion("a.mp3", "small", hablantes=True, al_terminar_trabajo=lambda: orden.append("suelta"))
    assert orden == ["trabajo", "suelta", "pregunta"]


def test_migra_el_cmd_antiguo_al_acceso_directo(windows, monkeypatch):
    monkeypatch.setattr(clic_derecho, "comando_del_programa", lambda: [str(windows.perfil / "transcriptor.exe")])
    (windows.envio).mkdir(parents=True, exist_ok=True)
    (windows.envio / "Transcriptor.cmd").write_text("@echo off\r\n")
    assert clic_derecho.migrar_si_hace_falta() is True
    assert not (windows.envio / "Transcriptor.cmd").exists()
    assert (windows.envio / "Transcriptor.lnk").exists()
    # Ya migrado (o sin .cmd): no hace nada más
    assert clic_derecho.migrar_si_hace_falta() is False


def test_no_migra_fuera_de_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    assert clic_derecho.migrar_si_hace_falta() is False


def test_un_bat_no_sirve_de_destino_del_acceso_directo(monkeypatch, tmp_path):
    # Un transcriptor.bat/.cmd obligaría a pasar otra vez por cmd con los nombres de archivo sin comillas
    monkeypatch.setattr(clic_derecho.rutas_windows, "buscar_programa", lambda nombre: str(tmp_path / "transcriptor.cmd"))
    assert clic_derecho.comando_del_programa()[0] == sys.executable
