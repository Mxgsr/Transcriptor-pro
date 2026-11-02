# Ubicación: tests/test_actualizar.py
# Pruebas de src/actualizar.py sin red ni instalaciones reales: urlopen, subprocess, sys.platform,
# sys.prefix y shutil.which están simulados. Los zips «de GitHub» se arman en memoria.
import io
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from src import actualizar, ajustes, historial
from src.actualizar import Novedad, SinConexion


# ---------------------------------------------------------------------------
# comparar / es_beta
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("a,b,esperado", [
    ("1.0.0", "1.0.0", 0),
    ("1.0.0", "1.0.1", -1),
    ("1.10.0", "1.9.0", 1),
    ("2.0", "2.0.0", 0),
    ("2.0.0b1", "2.0.0", -1),
    ("2.0.0b1", "2.0.0b2", -1),
    ("2.0.0b2", "2.0.0rc1", -1),
    ("2.0.0rc1", "2.0.0", -1),
    ("2.0.0a3", "2.0.0b1", -1),
    ("2.0.0b10", "2.0.0b9", 1),
    ("2.0.0b1", "1.9.9", 1),
    ("raro", "0", 0),
    ("raro", "1.0.0", -1),
    ("", "0", 0),
    (None, "0.0.1", -1),
])
def test_comparar(a, b, esperado):
    assert actualizar.comparar(a, b) == esperado
    assert actualizar.comparar(b, a) == -esperado


def test_es_beta():
    assert actualizar.es_beta("2.0.0b1")
    assert actualizar.es_beta("2.0.0rc1")
    assert not actualizar.es_beta("2.0.0")
    assert not actualizar.es_beta("raro")


def test_version_instalada_del_proyecto(monkeypatch):
    from importlib import metadata

    def no_instalado(nombre):
        raise metadata.PackageNotFoundError(nombre)

    monkeypatch.setattr(metadata, "version", no_instalado)
    assert actualizar.version_instalada() == "2.0.0b2" or actualizar.comparar(actualizar.version_instalada(), "2.0.0b1") >= 0


def test_version_instalada_del_paquete(monkeypatch):
    from importlib import metadata

    monkeypatch.setattr(metadata, "version", lambda nombre: "3.1.4")
    assert actualizar.version_instalada() == "3.1.4"


# ---------------------------------------------------------------------------
# version_en_github
# ---------------------------------------------------------------------------
class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _simular_github(monkeypatch, versiones, pedidas=None):
    """versiones: {rama: texto del pyproject o Exception}."""
    def urlopen(peticion, timeout=None):
        url = peticion.full_url if hasattr(peticion, "full_url") else peticion
        if pedidas is not None:
            pedidas.append((url, timeout, getattr(peticion, "headers", {})))
        rama = url.split("/Transcriptor-pro/")[1].split("/")[0]
        valor = versiones[rama]
        if isinstance(valor, Exception):
            raise valor
        return _Respuesta(valor.encode("utf-8"))

    monkeypatch.setattr(actualizar.urllib.request, "urlopen", urlopen)


def _pyproject(version):
    return f'[build-system]\nrequires = ["x"]\n\n[project]\nname = "transcriptor-pro"\nversion = "{version}"\n\n[tool.x]\nversion = "9.9.9"\n'


def test_version_en_github_ok(monkeypatch):
    pedidas = []
    _simular_github(monkeypatch, {"main": _pyproject("1.2.3")}, pedidas)
    assert actualizar.version_en_github("main", timeout=5) == "1.2.3"
    url, timeout, cabeceras = pedidas[0]
    assert url == "https://raw.githubusercontent.com/Mxgsr/Transcriptor-pro/main/pyproject.toml"
    assert timeout == 5
    assert any(k.lower() == "user-agent" for k in cabeceras)


def test_version_en_github_error_de_red(monkeypatch):
    _simular_github(monkeypatch, {"main": OSError("sin internet")})
    assert actualizar.version_en_github("main") is None


def test_version_en_github_sin_linea_de_version(monkeypatch):
    _simular_github(monkeypatch, {"main": '[project]\nname = "x"\n\n[tool.x]\nversion = "9.9.9"\n'})
    assert actualizar.version_en_github("main") is None


# ---------------------------------------------------------------------------
# buscar / aviso_guardado
# ---------------------------------------------------------------------------
def _instalada(monkeypatch, version):
    monkeypatch.setattr(actualizar, "version_instalada", lambda: version)


def test_buscar_estable(monkeypatch):
    _instalada(monkeypatch, "1.0.0")
    _simular_github(monkeypatch, {"main": _pyproject("1.1.0"), "v2": _pyproject("9.0.0")})
    # Instalada estable: v2 ni se mira.
    assert actualizar.buscar() == Novedad("1.1.0", "main")


def test_buscar_beta_prefiere_la_mayor(monkeypatch):
    _instalada(monkeypatch, "2.0.0b1")
    _simular_github(monkeypatch, {"main": _pyproject("1.5.0"), "v2": _pyproject("2.0.0b2")})
    assert actualizar.buscar() == Novedad("2.0.0b2", "v2")


def test_buscar_empate_gana_main(monkeypatch):
    _instalada(monkeypatch, "2.0.0b1")
    _simular_github(monkeypatch, {"main": _pyproject("2.0.0"), "v2": _pyproject("2.0.0")})
    assert actualizar.buscar() == Novedad("2.0.0", "main")


def test_buscar_nada_nuevo(monkeypatch):
    _instalada(monkeypatch, "2.0.0b2")
    _simular_github(monkeypatch, {"main": _pyproject("1.0.0"), "v2": _pyproject("2.0.0b2")})
    assert actualizar.buscar() is None
    preferencias = historial.preferencias()
    assert preferencias["actualizacion_nueva"] is None
    assert preferencias["actualizacion_rama"] is None
    assert preferencias["actualizacion_buscada"] > 0


def test_buscar_sin_conexion(monkeypatch):
    _instalada(monkeypatch, "2.0.0b1")
    _simular_github(monkeypatch, {"main": OSError("x"), "v2": OSError("x")})
    with pytest.raises(SinConexion):
        actualizar.buscar()
    assert "actualizacion_buscada" not in historial.preferencias()


def test_buscar_con_una_rama_caida_usa_la_otra(monkeypatch):
    _instalada(monkeypatch, "2.0.0b1")
    _simular_github(monkeypatch, {"main": OSError("x"), "v2": _pyproject("2.0.0b2")})
    assert actualizar.buscar() == Novedad("2.0.0b2", "v2")


def test_buscar_guarda_preferencias(monkeypatch):
    _instalada(monkeypatch, "1.0.0")
    _simular_github(monkeypatch, {"main": _pyproject("1.1.0")})
    antes = time.time()
    actualizar.buscar()
    preferencias = historial.preferencias()
    assert preferencias["actualizacion_nueva"] == "1.1.0"
    assert preferencias["actualizacion_rama"] == "main"
    assert preferencias["actualizacion_buscada"] >= antes


def test_aviso_guardado(monkeypatch):
    _instalada(monkeypatch, "1.0.0")
    assert actualizar.aviso_guardado() is None
    historial.guardar_preferencias(actualizacion_nueva="1.1.0", actualizacion_rama="main")
    assert actualizar.aviso_guardado() == Novedad("1.1.0", "main")


def test_aviso_guardado_ya_instalada_la_nueva(monkeypatch):
    historial.guardar_preferencias(actualizacion_nueva="1.1.0", actualizacion_rama="main")
    _instalada(monkeypatch, "1.1.0")
    assert actualizar.aviso_guardado() is None
    _instalada(monkeypatch, "2.0.0")
    assert actualizar.aviso_guardado() is None


# ---------------------------------------------------------------------------
# buscar_en_segundo_plano
# ---------------------------------------------------------------------------
@pytest.fixture
def buscar_falso(monkeypatch):
    llamadas = []

    def falso(timeout=8):
        llamadas.append(timeout)
        return None

    monkeypatch.setattr(actualizar, "buscar", falso)
    return llamadas


def test_segundo_plano_nunca_buscado(buscar_falso):
    hilo = actualizar.buscar_en_segundo_plano()
    assert hilo is not None and hilo.daemon
    hilo.join(2)
    assert buscar_falso == [3]


def test_segundo_plano_no_busca_si_fue_hace_poco(buscar_falso):
    historial.guardar_preferencias(actualizacion_buscada=time.time() - 3600)
    assert actualizar.buscar_en_segundo_plano() is None
    assert buscar_falso == []


def test_segundo_plano_busca_si_fue_hace_mucho(buscar_falso):
    historial.guardar_preferencias(actualizacion_buscada=time.time() - 8 * 86400)
    hilo = actualizar.buscar_en_segundo_plano()
    hilo.join(2)
    assert buscar_falso == [3]


def test_segundo_plano_respeta_sin_internet(buscar_falso, monkeypatch):
    monkeypatch.setattr(ajustes, "valor", lambda clave: True if clave == "sin_internet" else None)
    assert actualizar.buscar_en_segundo_plano() is None
    assert buscar_falso == []


def test_segundo_plano_no_propaga_errores(monkeypatch):
    def roto(timeout=8):
        raise RuntimeError("fallo")

    monkeypatch.setattr(actualizar, "buscar", roto)
    hilo = actualizar.buscar_en_segundo_plano()
    hilo.join(2)
    assert not hilo.is_alive()


# ---------------------------------------------------------------------------
# como_se_instalo / buscar_uv
# ---------------------------------------------------------------------------
def test_como_se_instalo_uv_tool_por_defecto(monkeypatch):
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/ana")))
    monkeypatch.setattr(sys, "prefix", "/home/ana/.local/share/uv/tools/transcriptor-pro")
    assert actualizar.como_se_instalo() == "uv_tool"


def test_como_se_instalo_con_uv_tool_dir(monkeypatch):
    monkeypatch.setenv("UV_TOOL_DIR", "/opt/herramientas")
    monkeypatch.setattr(sys, "prefix", "/opt/herramientas/transcriptor-pro")
    assert actualizar.como_se_instalo() == "uv_tool"


def test_como_se_instalo_windows(monkeypatch):
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    monkeypatch.setenv("APPDATA", r"C:\Users\Ana\AppData\Roaming")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "prefix", r"C:\Users\Ana\AppData\Roaming\uv\tools\transcriptor-pro")
    assert actualizar.como_se_instalo() == "uv_tool"


def test_como_se_instalo_respaldo_por_ruta(monkeypatch):
    monkeypatch.setenv("UV_TOOL_DIR", "/otra/parte")
    monkeypatch.setattr(sys, "prefix", "/x/uv/tools/transcriptor-pro")
    assert actualizar.como_se_instalo() == "uv_tool"


def test_como_se_instalo_otro(monkeypatch):
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    monkeypatch.setattr(sys, "prefix", "/home/ana/proyecto/.venv")
    assert actualizar.como_se_instalo() == "otro"


def test_buscar_uv(monkeypatch, tmp_path):
    monkeypatch.setattr(actualizar.shutil, "which", lambda nombre: "/usr/bin/uv")
    assert actualizar.buscar_uv() == "/usr/bin/uv"

    monkeypatch.setattr(actualizar.shutil, "which", lambda nombre: None)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert actualizar.buscar_uv() is None
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    (tmp_path / ".local" / "bin" / "uv").write_text("")
    assert actualizar.buscar_uv() == str(tmp_path / ".local" / "bin" / "uv")


# ---------------------------------------------------------------------------
# actualizar
# ---------------------------------------------------------------------------
_SHA = "0123456789abcdef0123456789abcdef01234567"
_URL_API_V2 = "https://api.github.com/repos/Mxgsr/Transcriptor-pro/commits/v2"
_URL_ZIP = f"https://github.com/Mxgsr/Transcriptor-pro/archive/{_SHA}.zip"


def _zip(version="2.0.0b2", raiz=f"Transcriptor-pro-{_SHA}", con_pyproject=True, extras=()):
    """Un zip como el que da GitHub: todo dentro de una carpeta raíz."""
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as zip_:
        zip_.writestr(f"{raiz}/", "")
        zip_.writestr(f"{raiz}/src/__init__.py", "")
        if con_pyproject:
            zip_.writestr(f"{raiz}/pyproject.toml", _pyproject(version))
        for nombre in extras:
            zip_.writestr(nombre, "x")
    return memoria.getvalue()


class _RespuestaConCabeceras(_Respuesta):
    def __init__(self, datos, cabeceras):
        super().__init__(datos)
        self.headers = cabeceras


def _simular_descarga(monkeypatch, api=None, zip_bytes=None, pedidas=None):
    """api: JSON (dict), bytes crudos o Exception; zip_bytes: bytes, respuesta o Exception."""
    if api is None:
        api = {"sha": _SHA, "commit": {"message": "x"}}
    if zip_bytes is None:
        zip_bytes = _zip()

    def urlopen(peticion, timeout=None):
        url = peticion.full_url
        if pedidas is not None:
            pedidas.append((url, timeout, dict(peticion.header_items())))
        valor = api if url.startswith("https://api.github.com/") else zip_bytes
        if isinstance(valor, Exception):
            raise valor
        if isinstance(valor, dict):  # la API responde solo el SHA en texto (Accept: vnd.github.sha)
            return _Respuesta(str(valor.get("sha", "")).encode("utf-8"))
        if isinstance(valor, bytes):
            return _Respuesta(valor)
        return valor

    monkeypatch.setattr(actualizar.urllib.request, "urlopen", urlopen)


@pytest.fixture
def como_uv_tool(monkeypatch):
    monkeypatch.setattr(actualizar, "como_se_instalo", lambda: "uv_tool")
    monkeypatch.setattr(actualizar, "buscar_uv", lambda: "/ruta/uv")
    _instalada(monkeypatch, "2.0.0b1")


@pytest.fixture
def run_falso(monkeypatch):
    """Simula uv en Mac/Linux: guarda el comando, el entorno y lo que había en el zip al instalar."""
    monkeypatch.setattr(sys, "platform", "linux")
    ejecutadas = []

    def run(comando, **kwargs):
        zip_ = Path(comando[-1].split(" @ file://")[1])
        ejecutadas.append({"comando": comando, "kwargs": kwargs, "zip": zip_, "bytes": zip_.read_bytes()})
        return subprocess.CompletedProcess(comando, 0)

    monkeypatch.setattr(actualizar.subprocess, "run", run)
    return ejecutadas


def test_actualizar_unix(monkeypatch, como_uv_tool, run_falso):
    monkeypatch.delenv("UV_HTTP_TIMEOUT", raising=False)
    monkeypatch.setenv("HF_TOKEN", "hf_secreto")
    pedidas = []
    _simular_descarga(monkeypatch, pedidas=pedidas)
    mensajes = []

    assert actualizar.actualizar(Novedad("2.0.0b2", "v2"), salida=mensajes.append) == "listo"
    # Primero se fija el commit y luego se baja ESE commit, no la rama
    assert [p[0] for p in pedidas] == [_URL_API_V2, _URL_ZIP]
    cabeceras_api = {k.lower(): v for k, v in pedidas[0][2].items()}
    assert cabeceras_api["accept"] == "application/vnd.github.sha"
    assert cabeceras_api["user-agent"]
    assert pedidas[0][1] and pedidas[1][1] >= 60
    assert not any("refs/heads" in p[0] for p in pedidas)

    llamada = run_falso[0]
    comando, kwargs = llamada["comando"], llamada["kwargs"]
    assert comando[:-1] == ["/ruta/uv", "tool", "install", "--force", "--upgrade",
                            "--reinstall-package", "transcriptor-pro", "--python", "3.11"]
    assert comando[-1] == f"transcriptor-pro[diarizacion] @ {llamada['zip'].as_uri()}"
    assert llamada["bytes"] == _zip()  # el zip ya estaba bajado y es el revisado
    assert kwargs["env"]["UV_HTTP_TIMEOUT"] == "300"
    assert "HF_TOKEN" not in kwargs["env"]
    assert not kwargs.get("capture_output") and not kwargs.get("shell")
    assert not llamada["zip"].parent.exists()  # borró la carpeta temporal
    assert mensajes


def test_actualizar_unix_respeta_uv_http_timeout(monkeypatch, como_uv_tool, run_falso):
    monkeypatch.setenv("UV_HTTP_TIMEOUT", "99")
    _simular_descarga(monkeypatch)
    actualizar.actualizar(Novedad("2.0.0b2", "v2"), salida=lambda *_: None)
    assert run_falso[0]["kwargs"]["env"]["UV_HTTP_TIMEOUT"] == "99"


def test_actualizar_unix_uv_falla(monkeypatch, como_uv_tool):
    monkeypatch.setattr(sys, "platform", "linux")
    _simular_descarga(monkeypatch)
    monkeypatch.setattr(actualizar.subprocess, "run", lambda c, **k: subprocess.CompletedProcess(c, 1))
    assert actualizar.actualizar(Novedad("2.0.0b2", "v2"), salida=lambda *_: None) == "error"


def test_actualizar_unix_sin_red_no_lanza(monkeypatch, como_uv_tool):
    monkeypatch.setattr(sys, "platform", "linux")

    def sin_red(*args, **kwargs):
        raise OSError("sin internet")

    monkeypatch.setattr(actualizar.urllib.request, "urlopen", sin_red)
    monkeypatch.setattr(actualizar.subprocess, "run", lambda *a, **k: pytest.fail("no debía instalar"))
    assert actualizar.actualizar(Novedad("2.0.0b2", "v2"), salida=lambda *_: None) == "error"


def test_actualizar_zip_falla_tras_resolver_el_commit(monkeypatch, como_uv_tool):
    monkeypatch.setattr(sys, "platform", "linux")
    _simular_descarga(monkeypatch, zip_bytes=OSError("se cortó"))
    monkeypatch.setattr(actualizar.subprocess, "run", lambda *a, **k: pytest.fail("no debía instalar"))
    assert actualizar.actualizar(Novedad("2.0.0b2", "v2"), salida=lambda *_: None) == "error"


def _sin_instalar(monkeypatch, caplog, novedad=Novedad("2.0.0b2", "v2"), plataforma="linux", **simulacion):
    """Corre actualizar() esperando que rechace: devuelve «error», no instala ni lanza nada y lo registra."""
    monkeypatch.setattr(sys, "platform", plataforma)
    pedidas = []
    _simular_descarga(monkeypatch, pedidas=pedidas, **simulacion)

    def prohibido(*args, **kwargs):
        pytest.fail("no debía instalar ni lanzar nada")

    monkeypatch.setattr(actualizar.subprocess, "run", prohibido)
    monkeypatch.setattr(actualizar.subprocess, "Popen", prohibido)
    carpetas = []
    mkdtemp_real = actualizar.tempfile.mkdtemp
    monkeypatch.setattr(actualizar.tempfile, "mkdtemp",
                        lambda **k: carpetas.append(mkdtemp_real(**k)) or carpetas[-1])
    with caplog.at_level("WARNING", logger="src.actualizar"):
        assert actualizar.actualizar(novedad, salida=lambda *_: None) == "error"
    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert all(not Path(c).exists() for c in carpetas)  # no deja la descarga tirada
    return pedidas


def test_actualizar_api_falla_no_cae_a_la_rama(monkeypatch, como_uv_tool, caplog):
    pedidas = _sin_instalar(monkeypatch, caplog, api=OSError("API caída"))
    assert [p[0] for p in pedidas] == [_URL_API_V2]  # ni siquiera intenta bajar la rama


def test_actualizar_api_responde_basura(monkeypatch, como_uv_tool, caplog):
    _sin_instalar(monkeypatch, caplog, api=b"<html>no es json</html>")


@pytest.mark.parametrize("sha", [None, "", "abc123", "g" * 40, _SHA + "0", "../" + _SHA[:37], 12345])
def test_actualizar_sha_con_formato_raro(monkeypatch, como_uv_tool, caplog, sha):
    pedidas = _sin_instalar(monkeypatch, caplog, api={"sha": sha})
    assert len(pedidas) == 1


def test_actualizar_rama_desconocida(monkeypatch, como_uv_tool, caplog):
    pedidas = _sin_instalar(monkeypatch, caplog, novedad=Novedad("2.0.0b2", "../../otra"))
    assert pedidas == []


def test_actualizar_sha_en_mayusculas_se_normaliza(monkeypatch, como_uv_tool, run_falso):
    pedidas = []
    _simular_descarga(monkeypatch, api={"sha": _SHA.upper()}, pedidas=pedidas)
    assert actualizar.actualizar(Novedad("2.0.0b2", "v2"), salida=lambda *_: None) == "listo"
    assert pedidas[1][0] == _URL_ZIP


def test_actualizar_version_del_zip_distinta_de_la_anunciada(monkeypatch, como_uv_tool, caplog):
    _sin_instalar(monkeypatch, caplog, zip_bytes=_zip(version="2.0.0b3"))
    assert "2.0.0b3" in caplog.text


@pytest.mark.parametrize("version", ["2.0.0b1", "2.0.0a9", "1.9.0"])
def test_actualizar_version_del_zip_no_es_mas_nueva(monkeypatch, como_uv_tool, caplog, version):
    # Aunque coincida con lo anunciado, nunca se instala la misma versión ni una anterior
    _sin_instalar(monkeypatch, caplog, novedad=Novedad(version, "main"), zip_bytes=_zip(version=version))


@pytest.mark.parametrize("ruta", [
    f"Transcriptor-pro-{_SHA}/../../fuera.txt",
    "/etc/fuera.txt",
    "C:/Windows/fuera.txt",
    f"Transcriptor-pro-{_SHA}\\..\\fuera.txt",
])
def test_actualizar_zip_con_rutas_peligrosas(monkeypatch, como_uv_tool, caplog, ruta):
    _sin_instalar(monkeypatch, caplog, zip_bytes=_zip(extras=[ruta]))


def test_actualizar_zip_sin_pyproject(monkeypatch, como_uv_tool, caplog):
    _sin_instalar(monkeypatch, caplog, zip_bytes=_zip(con_pyproject=False))


def test_actualizar_zip_con_pyproject_solo_en_subcarpeta(monkeypatch, como_uv_tool, caplog):
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as zip_:
        zip_.writestr(f"Transcriptor-pro-{_SHA}/otra/pyproject.toml", _pyproject("2.0.0b2"))
    _sin_instalar(monkeypatch, caplog, zip_bytes=memoria.getvalue())


def test_actualizar_zip_con_varias_raices(monkeypatch, como_uv_tool, caplog):
    _sin_instalar(monkeypatch, caplog, zip_bytes=_zip(extras=["otra-raiz/pyproject.toml"]))


def test_actualizar_zip_roto(monkeypatch, como_uv_tool, caplog):
    _sin_instalar(monkeypatch, caplog, zip_bytes=b"esto no es un zip")


def test_actualizar_zip_demasiado_grande(monkeypatch, como_uv_tool, caplog):
    monkeypatch.setattr(actualizar, "_TAMANO_MAXIMO_ZIP", 100)
    _sin_instalar(monkeypatch, caplog, zip_bytes=_zip())  # pesa más de 100 bytes


def test_actualizar_zip_anuncia_tamano_excesivo(monkeypatch, como_uv_tool, caplog):
    leido = []

    class Enorme(_RespuestaConCabeceras):
        def read(self, *args):
            leido.append(True)
            return super().read(*args)

    respuesta = Enorme(_zip(), {"Content-Length": str(300 * 1024 * 1024)})
    _sin_instalar(monkeypatch, caplog, zip_bytes=respuesta)
    assert not leido  # ni empieza a bajarlo


def test_actualizar_windows(monkeypatch, como_uv_tool):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setenv("HF_TOKEN", "hf_secreto")
    pedidas, lanzados = [], []
    _simular_descarga(monkeypatch, pedidas=pedidas)

    def popen(comando, **kwargs):
        contenido = Path(comando[-1]).read_bytes()  # leer antes de que alguien lo borre
        zip_ = Path(kwargs["env"]["TRANSCRIPTOR_ZIP"])
        lanzados.append((comando, kwargs, contenido, zip_.read_bytes()))

    monkeypatch.setattr(actualizar.subprocess, "Popen", popen)
    monkeypatch.setattr(actualizar.subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
    monkeypatch.setattr(actualizar.subprocess, "run",
                        lambda *a, **k: pytest.fail("en Windows no se corre uv desde aquí"))

    assert actualizar.actualizar(Novedad("2.0.0b2", "v2"), salida=lambda *_: None) == "reiniciar_aparte"
    # La descarga y la revisión se hicieron aquí, antes de abrir la ventana
    assert [p[0] for p in pedidas] == [_URL_API_V2, _URL_ZIP]
    comando, kwargs, contenido, zip_bytes = lanzados[0]
    assert zip_bytes == _zip()
    # Ruta completa: un powershell.exe en la carpeta actual no se usa
    assert comando[:5] == [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                           "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    assert comando[5].endswith(".ps1")
    texto = contenido.decode("ascii")  # solo ASCII: no lanza
    assert "Wait-Process" in texto and "TRANSCRIPTOR_PID" in texto and "TRANSCRIPTOR_ZIP" in texto
    assert "Read-Host" in texto
    assert "& $env:TRANSCRIPTOR_UV tool install --force --upgrade --reinstall-package transcriptor-pro --python 3.11 $Paquete" in texto
    # El script ya no descarga nada por su cuenta
    assert "Invoke-WebRequest" not in texto and "archive/refs/heads" not in texto
    assert "TRANSCRIPTOR_RAMA" not in texto and "TRANSCRIPTOR_REPO" not in texto
    # Los datos no van pegados en el script.
    assert "v2" not in texto and "/ruta/uv" not in texto and _SHA not in texto
    entorno = kwargs["env"]
    zip_ruta = Path(entorno["TRANSCRIPTOR_ZIP"])
    assert zip_ruta.parent == Path(comando[5]).parent  # en la misma carpeta temporal que el script
    assert zip_ruta.parent.name.startswith("transcriptor-actualizar-")  # la que el script puede borrar
    assert entorno["TRANSCRIPTOR_UV"] == "/ruta/uv"
    assert entorno["TRANSCRIPTOR_PID"] == str(os.getpid())
    assert "TRANSCRIPTOR_RAMA" not in entorno and "TRANSCRIPTOR_REPO" not in entorno
    assert "HF_TOKEN" not in entorno
    assert kwargs["creationflags"] == 0x10
    shutil.rmtree(zip_ruta.parent)  # en Windows la borra el script; aquí, la prueba


def test_actualizar_windows_rechazo_no_abre_la_ventana(monkeypatch, como_uv_tool, caplog):
    _sin_instalar(monkeypatch, caplog, plataforma="win32", zip_bytes=_zip(version="9.9.9"))


def test_actualizar_windows_sin_constante_usa_respaldo(monkeypatch, como_uv_tool):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(actualizar.subprocess, "CREATE_NEW_CONSOLE", raising=False)
    _simular_descarga(monkeypatch)
    banderas = []

    def popen(comando, **kwargs):
        banderas.append(kwargs["creationflags"])
        shutil.rmtree(Path(comando[-1]).parent)

    monkeypatch.setattr(actualizar.subprocess, "Popen", popen)
    assert actualizar.actualizar(Novedad("2.0.0b2", "v2"), salida=lambda *_: None) == "reiniciar_aparte"
    assert banderas == [0x10]


def test_actualizar_otra_instalacion_no_ejecuta_nada(monkeypatch):
    monkeypatch.setattr(actualizar, "como_se_instalo", lambda: "otro")
    monkeypatch.setattr(actualizar, "buscar_uv", lambda: "/ruta/uv")

    def prohibido(*args, **kwargs):
        pytest.fail("no debía ejecutar nada")

    monkeypatch.setattr(actualizar.subprocess, "run", prohibido)
    monkeypatch.setattr(actualizar.subprocess, "Popen", prohibido)
    monkeypatch.setattr(actualizar.urllib.request, "urlopen", prohibido)
    assert actualizar.actualizar(Novedad("1.0.0", "main"), salida=lambda *_: None) == "error"


def test_actualizar_sin_uv(monkeypatch):
    monkeypatch.setattr(actualizar, "como_se_instalo", lambda: "uv_tool")
    monkeypatch.setattr(actualizar, "buscar_uv", lambda: None)
    monkeypatch.setattr(actualizar.subprocess, "run", lambda *a, **k: pytest.fail("no debía correr"))
    monkeypatch.setattr(actualizar.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no debía bajar"))
    assert actualizar.actualizar(Novedad("1.0.0", "main"), salida=lambda *_: None) == "error"


def test_buscar_conserva_las_preferencias_guardadas_por_otro_mientras_consulta(monkeypatch):
    historial.guardar_preferencias(modelo="small")
    monkeypatch.setattr(actualizar, "version_instalada", lambda: "1.0.0")

    def consulta_lenta(rama, timeout=8):
        # Mientras la red responde, el menú guarda otra preferencia
        historial.guardar_preferencias(idioma="es", modelo="large")
        return "1.1.0"

    monkeypatch.setattr(actualizar, "version_en_github", consulta_lenta)
    actualizar.buscar()

    prefs = historial.preferencias()
    assert prefs["idioma"] == "es" and prefs["modelo"] == "large"
    assert prefs["actualizacion_nueva"] == "1.1.0"
    assert isinstance(prefs["actualizacion_buscada"], float)
