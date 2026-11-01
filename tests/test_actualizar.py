# Ubicación: tests/test_actualizar.py
# Pruebas de src/actualizar.py sin red ni instalaciones reales: urlopen, subprocess, sys.platform,
# sys.prefix y shutil.which están simulados.
import io
import subprocess
import sys
import time
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
@pytest.fixture
def como_uv_tool(monkeypatch):
    monkeypatch.setattr(actualizar, "como_se_instalo", lambda: "uv_tool")
    monkeypatch.setattr(actualizar, "buscar_uv", lambda: "/ruta/uv")


def test_actualizar_unix(monkeypatch, como_uv_tool):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("UV_HTTP_TIMEOUT", raising=False)
    pedidas, ejecutadas, carpetas = [], [], []

    def urlopen(peticion, timeout=None):
        pedidas.append((peticion.full_url, timeout))
        return _Respuesta(b"ZIPFALSO")

    def run(comando, **kwargs):
        zip_ = Path(comando[-1].split(" @ file://")[1])
        carpetas.append(zip_.parent)
        assert zip_.read_bytes() == b"ZIPFALSO"  # el zip ya estaba bajado
        ejecutadas.append((comando, kwargs))
        return subprocess.CompletedProcess(comando, 0)

    monkeypatch.setattr(actualizar.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(actualizar.subprocess, "run", run)
    mensajes = []

    assert actualizar.actualizar(Novedad("2.0.0b2", "v2"), salida=mensajes.append) == "listo"
    assert pedidas[0][0] == "https://github.com/Mxgsr/Transcriptor-pro/archive/refs/heads/v2.zip"
    assert pedidas[0][1] >= 60
    comando, kwargs = ejecutadas[0]
    zip_ruta = Path(comando[-1].split(" @ file://")[1])
    assert comando[:-1] == ["/ruta/uv", "tool", "install", "--force", "--upgrade",
                            "--reinstall-package", "transcriptor-pro", "--python", "3.11"]
    assert comando[-1] == f"transcriptor-pro[diarizacion] @ {zip_ruta.as_uri()}"
    assert kwargs["env"]["UV_HTTP_TIMEOUT"] == "300"
    assert not kwargs.get("capture_output") and not kwargs.get("shell")
    assert not carpetas[0].exists()  # borró la carpeta temporal
    assert mensajes


def test_actualizar_unix_respeta_uv_http_timeout(monkeypatch, como_uv_tool):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("UV_HTTP_TIMEOUT", "99")
    entornos = []
    monkeypatch.setattr(actualizar.urllib.request, "urlopen", lambda p, timeout=None: _Respuesta(b"x"))
    monkeypatch.setattr(actualizar.subprocess, "run",
                        lambda c, **k: entornos.append(k["env"]) or subprocess.CompletedProcess(c, 0))
    actualizar.actualizar(Novedad("1.0.0", "main"), salida=lambda *_: None)
    assert entornos[0]["UV_HTTP_TIMEOUT"] == "99"


def test_actualizar_unix_uv_falla(monkeypatch, como_uv_tool):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(actualizar.urllib.request, "urlopen", lambda p, timeout=None: _Respuesta(b"x"))
    monkeypatch.setattr(actualizar.subprocess, "run", lambda c, **k: subprocess.CompletedProcess(c, 1))
    assert actualizar.actualizar(Novedad("1.0.0", "main"), salida=lambda *_: None) == "error"


def test_actualizar_unix_sin_red_no_lanza(monkeypatch, como_uv_tool):
    monkeypatch.setattr(sys, "platform", "linux")

    def sin_red(*args, **kwargs):
        raise OSError("sin internet")

    monkeypatch.setattr(actualizar.urllib.request, "urlopen", sin_red)
    assert actualizar.actualizar(Novedad("1.0.0", "main"), salida=lambda *_: None) == "error"


def test_actualizar_windows(monkeypatch, como_uv_tool):
    monkeypatch.setattr(sys, "platform", "win32")
    lanzados = []

    def popen(comando, **kwargs):
        contenido = Path(comando[-1]).read_bytes()  # leer antes de que alguien lo borre
        lanzados.append((comando, kwargs, contenido))

    monkeypatch.setattr(actualizar.subprocess, "Popen", popen)
    monkeypatch.setattr(actualizar.subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
    monkeypatch.setattr(actualizar.subprocess, "run",
                        lambda *a, **k: pytest.fail("en Windows no se corre uv desde aquí"))

    assert actualizar.actualizar(Novedad("2.0.0b2", "v2"), salida=lambda *_: None) == "reiniciar_aparte"
    comando, kwargs, contenido = lanzados[0]
    assert comando[:5] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    assert comando[5].endswith(".ps1")
    contenido.decode("ascii")  # solo ASCII: no lanza
    texto = contenido.decode("ascii")
    assert "Wait-Process" in texto and "TRANSCRIPTOR_PID" in texto
    assert "Read-Host" in texto and "Invoke-WebRequest -UseBasicParsing" in texto
    assert "Tls12" in texto and "SilentlyContinue" in texto
    assert "& $env:TRANSCRIPTOR_UV tool install --force --upgrade --reinstall-package transcriptor-pro --python 3.11 $Paquete" in texto
    # Los datos no van pegados en el script.
    assert "v2" not in texto and "/ruta/uv" not in texto
    entorno = kwargs["env"]
    assert entorno["TRANSCRIPTOR_RAMA"] == "v2"
    assert entorno["TRANSCRIPTOR_UV"] == "/ruta/uv"
    assert entorno["TRANSCRIPTOR_PID"] == str(__import__("os").getpid())
    assert entorno["TRANSCRIPTOR_REPO"] == "Mxgsr/Transcriptor-pro"
    assert kwargs["creationflags"] == 0x10


def test_actualizar_windows_sin_constante_usa_respaldo(monkeypatch, como_uv_tool):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(actualizar.subprocess, "CREATE_NEW_CONSOLE", raising=False)
    banderas = []
    monkeypatch.setattr(actualizar.subprocess, "Popen", lambda c, **k: banderas.append(k["creationflags"]))
    assert actualizar.actualizar(Novedad("1.0.0", "main"), salida=lambda *_: None) == "reiniciar_aparte"
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
    assert actualizar.actualizar(Novedad("1.0.0", "main"), salida=lambda *_: None) == "error"
