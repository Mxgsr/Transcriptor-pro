# Ubicación: src/actualizar.py
# «Buscar actualizaciones» desde el programa, sin volver a pegar la línea del instalador.
# - buscar(): mira la versión que hay en GitHub (rama estable y, si se usa la beta, la beta).
# - buscar_en_segundo_plano(): lo mismo, sin molestar y como mucho una vez por semana.
# - actualizar(): hace lo mismo que instalar.sh / instalar.ps1 (uv tool install sobre el zip de la rama).
# Solo usa la librería estándar. Lo que toca el sistema nunca lanza errores al usuario: devuelve "error".
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src import ajustes, historial

log = logging.getLogger(__name__)

REPO = "Mxgsr/Transcriptor-pro"
RAMA_ESTABLE = "main"
RAMA_BETA = "v2"

MENSAJE_OTRA_INSTALACION = (
    "Esta copia no se instaló con el instalador. Actualízala de la misma forma en que la instalaste."
)
MENSAJE_SIN_UV = (
    "No se encontró uv, la herramienta que instala Transcriptor. "
    "Vuelve a pegar la línea del instalador para actualizar."
)

_USER_AGENT = "Transcriptor-pro-actualizador"
_PAQUETE = "transcriptor-pro"
# Constante de Windows: la ventana nueva solo existe allí; en otros sistemas usamos su valor (0x10).
_CREATE_NEW_CONSOLE = 0x10


class SinConexion(Exception):
    """No se pudo consultar ninguna rama de GitHub."""


@dataclass
class Novedad:
    version: str
    rama: str


# ---------------------------------------------------------------------------
# 1. Versiones
# ---------------------------------------------------------------------------
_PATRON_VERSION = re.compile(r"^(\d+(?:\.\d+)*)(?:(a|b|rc)(\d+))?$")
# Una pre-versión (a < b < rc) va antes de la final, por eso la final vale 3.
_ETAPAS = {"a": 0, "b": 1, "rc": 2}
_ETAPA_FINAL = 3


def _clave(version: str) -> tuple:
    """Convierte «2.0.0b1» en algo comparable. Texto raro cuenta como «0»."""
    coincidencia = _PATRON_VERSION.match(str(version or "").strip().lower())
    if not coincidencia:
        coincidencia = _PATRON_VERSION.match("0")
    numeros = [int(n) for n in coincidencia.group(1).split(".")]
    while len(numeros) > 1 and numeros[-1] == 0:
        numeros.pop()  # «2.0» y «2.0.0» son la misma versión
    etapa = coincidencia.group(2)
    if etapa is None:
        return (numeros, _ETAPA_FINAL, 0)
    return (numeros, _ETAPAS[etapa], int(coincidencia.group(3)))


def comparar(a: str, b: str) -> int:
    """-1 si a es más vieja que b, 0 si son iguales, 1 si a es más nueva."""
    clave_a, clave_b = _clave(a), _clave(b)
    return (clave_a > clave_b) - (clave_a < clave_b)


def es_beta(version: str) -> bool:
    """True si es una pre-versión (b1, rc1...)."""
    coincidencia = _PATRON_VERSION.match(str(version or "").strip().lower())
    return bool(coincidencia and coincidencia.group(2))


def _version_del_texto(texto: str) -> Optional[str]:
    """Saca `version = "..."` de la sección [project] de un pyproject.toml."""
    seccion = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", texto, re.MULTILINE | re.DOTALL)
    if not seccion:
        return None
    version = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', seccion.group(1), re.MULTILINE)
    return version.group(1).strip() if version else None


def version_instalada() -> str:
    """La versión que corre ahora: la del paquete instalado o, en la carpeta del proyecto, la de pyproject.toml."""
    try:
        from importlib import metadata

        return metadata.version(_PAQUETE)
    except Exception:
        pass
    try:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        version = _version_del_texto(pyproject.read_text(encoding="utf-8"))
        if version:
            return version
    except Exception as error:
        log.debug("No se pudo leer la versión del proyecto: %s", error)
    return "0"


def version_en_github(rama: str, timeout: float = 8) -> Optional[str]:
    """La versión que tiene `rama` en GitHub, o None si no se pudo saber (sin internet, 404...)."""
    url = f"https://raw.githubusercontent.com/{REPO}/{rama}/pyproject.toml"
    try:
        peticion = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            texto = respuesta.read().decode("utf-8", errors="replace")
        return _version_del_texto(texto)
    except Exception as error:
        log.debug("No se pudo consultar la rama %s: %s", rama, error)
        return None


# ---------------------------------------------------------------------------
# 2. Buscar
# ---------------------------------------------------------------------------
def buscar(timeout: float = 8) -> Optional[Novedad]:
    """Devuelve la versión más nueva que la instalada (o None). Lanza SinConexion si no consultó nada."""
    instalada = version_instalada()
    ramas = [RAMA_ESTABLE]
    if es_beta(instalada):
        ramas.append(RAMA_BETA)  # quien prueba la beta quiere ver también las betas nuevas

    mejor: Optional[Novedad] = None
    consultadas = 0
    for rama in ramas:
        version = version_en_github(rama, timeout=timeout)
        if version is None:
            continue
        consultadas += 1
        if comparar(version, instalada) <= 0:
            continue
        # En un empate gana la primera rama (main), porque va primero en la lista.
        if mejor is None or comparar(version, mejor.version) > 0:
            mejor = Novedad(version=version, rama=rama)

    if consultadas == 0:
        raise SinConexion("No se pudo consultar GitHub.")

    historial.guardar_preferencias(
        actualizacion_buscada=time.time(),
        actualizacion_nueva=mejor.version if mejor else None,
        actualizacion_rama=mejor.rama if mejor else None,
    )
    return mejor


def aviso_guardado() -> Optional[Novedad]:
    """Lo que encontró la última búsqueda, si sigue siendo más nuevo que lo instalado. No usa la red."""
    try:
        preferencias = historial.preferencias()
        version = preferencias.get("actualizacion_nueva")
        rama = preferencias.get("actualizacion_rama")
        if not version or not rama or comparar(str(version), version_instalada()) <= 0:
            return None
        return Novedad(version=str(version), rama=str(rama))
    except Exception as error:
        log.debug("No se pudo leer el aviso guardado: %s", error)
        return None


def buscar_en_segundo_plano(dias: int = 7) -> Optional[threading.Thread]:
    """Busca en un hilo aparte si hace más de `dias` días que no se busca. Nunca bloquea ni falla."""
    try:
        # «Sin internet» se refiere a Hugging Face, pero se respeta: quien lo activa no quiere salidas a la red.
        if ajustes.valor("sin_internet"):
            return None
        ultima = historial.preferencias().get("actualizacion_buscada")
        if isinstance(ultima, (int, float)) and time.time() - ultima < dias * 86400:
            return None
    except Exception as error:
        log.debug("No se pudo decidir si buscar actualizaciones: %s", error)
        return None

    def trabajo():
        try:
            buscar(timeout=3)
        except Exception as error:  # sin internet, disco de solo lectura...: no importa
            log.debug("Búsqueda de actualizaciones en segundo plano falló: %s", error)

    hilo = threading.Thread(target=trabajo, name="buscar-actualizaciones", daemon=True)
    hilo.start()
    return hilo


# ---------------------------------------------------------------------------
# 3. Cómo se instaló
# ---------------------------------------------------------------------------
def _normalizar(ruta: str) -> str:
    return ruta.replace("\\", "/").rstrip("/").lower()


def _carpeta_herramientas_uv() -> str:
    """Donde uv guarda las herramientas instaladas (UV_TOOL_DIR o la ruta por defecto)."""
    elegida = os.environ.get("UV_TOOL_DIR")
    if elegida:
        return elegida
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return os.path.join(base, "uv", "tools")
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return os.path.join(base, "uv", "tools")


def como_se_instalo() -> str:
    """«uv_tool» si corre desde una instalación del instalador; «otro» (p. ej. un .venv de desarrollo) si no."""
    try:
        prefijo = _normalizar(sys.prefix)
        herramientas = _normalizar(_carpeta_herramientas_uv())
        if prefijo == herramientas or prefijo.startswith(herramientas + "/"):
            return "uv_tool"
        if "uv/tools" in prefijo:  # respaldo si uv usa otra ruta
            return "uv_tool"
    except Exception as error:
        log.debug("No se pudo saber cómo se instaló: %s", error)
    return "otro"


def buscar_uv() -> Optional[str]:
    """La ruta de uv, o None si no se encuentra."""
    encontrado = shutil.which("uv")
    if encontrado:
        return encontrado
    nombre = "uv.exe" if sys.platform == "win32" else "uv"
    candidato = Path.home() / ".local" / "bin" / nombre
    return str(candidato) if candidato.exists() else None


# ---------------------------------------------------------------------------
# 4. Actualizar
# ---------------------------------------------------------------------------
def _url_zip(rama: str) -> str:
    return f"https://github.com/{REPO}/archive/refs/heads/{rama}.zip"


def _comando_uv(uv: str, paquete: str) -> list:
    # El mismo comando que usan instalar.sh e instalar.ps1.
    return [uv, "tool", "install", "--force", "--upgrade", "--reinstall-package", _PAQUETE,
            "--python", "3.11", paquete]


# El script va escrito SOLO con ASCII (por eso los mensajes no llevan tildes): Windows PowerShell 5.1
# lee un .ps1 sin BOM con la página de códigos local y dañaría cualquier tilde. Rama, pid, ruta de uv
# y repositorio llegan por variables de entorno, nunca pegados en el script.
_PS_ACTUALIZAR = r"""
$ErrorActionPreference = "Stop"
$Temporal = $null
try {
    Write-Host "Cerrando Transcriptor para actualizarlo..."
    try { Wait-Process -Id ([int]$env:TRANSCRIPTOR_PID) -ErrorAction Stop } catch { }
    # transcriptor.exe (el lanzador de uv) cierra un instante despues de Python: le damos tiempo
    Start-Sleep -Seconds 3
    Write-Host "Descargando la nueva version..."
    $Temporal = Join-Path ([System.IO.Path]::GetTempPath()) ("transcriptor-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Force -Path $Temporal | Out-Null
    $Archivo = Join-Path $Temporal "transcriptor-pro.zip"
    $Zip = "https://github.com/" + $env:TRANSCRIPTOR_REPO + "/archive/refs/heads/" + $env:TRANSCRIPTOR_RAMA + ".zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -UseBasicParsing -Uri $Zip -OutFile $Archivo
    Write-Host "Instalando (puede tardar unos minutos)..."
    if (-not $env:UV_HTTP_TIMEOUT) { $env:UV_HTTP_TIMEOUT = "300" }
    $Paquete = "transcriptor-pro[diarizacion] @ " + ([System.Uri]$Archivo).AbsoluteUri
    & $env:TRANSCRIPTOR_UV tool install --force --upgrade --reinstall-package transcriptor-pro --python 3.11 $Paquete
    if ($LASTEXITCODE -ne 0) { throw "uv termino con el codigo $LASTEXITCODE" }
    Write-Host ""
    Write-Host "Listo. Ya puedes abrir Transcriptor de nuevo." -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "No se pudo actualizar: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Revisa la conexion a internet y vuelve a intentarlo, o pega de nuevo la linea del instalador."
}
if ($Temporal) { Remove-Item -Recurse -Force $Temporal -ErrorAction SilentlyContinue }
Read-Host "Aprieta Enter para cerrar esta ventana"
Remove-Item -Force -LiteralPath $PSCommandPath -ErrorAction SilentlyContinue
"""


def _actualizar_en_windows(novedad: Novedad, uv: str, salida) -> str:
    # El transcriptor.exe abierto está bloqueado y uv no puede reemplazarlo: un proceso aparte
    # espera a que este programa se cierre y recién entonces instala.
    assert _PS_ACTUALIZAR.isascii()
    carpeta = tempfile.mkdtemp(prefix="transcriptor-actualizar-")
    script = os.path.join(carpeta, "actualizar.ps1")
    with open(script, "w", encoding="ascii", newline="\r\n") as archivo:
        archivo.write(_PS_ACTUALIZAR)
    entorno = {
        **os.environ,
        "TRANSCRIPTOR_PID": str(os.getpid()),
        "TRANSCRIPTOR_UV": uv,
        "TRANSCRIPTOR_RAMA": novedad.rama,
        "TRANSCRIPTOR_REPO": REPO,
    }
    salida("Se abrirá otra ventana que termina la actualización cuando se cierre este programa.")
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
        env=entorno,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", _CREATE_NEW_CONSOLE),
    )
    return "reiniciar_aparte"


def _actualizar_en_unix(novedad: Novedad, uv: str, salida) -> str:
    temporal = tempfile.mkdtemp(prefix="transcriptor-actualizar-")
    try:
        archivo = Path(temporal) / "transcriptor-pro.zip"
        salida("Descargando la nueva versión...")
        peticion = urllib.request.Request(_url_zip(novedad.rama), headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(peticion, timeout=120) as respuesta, open(archivo, "wb") as destino:
            shutil.copyfileobj(respuesta, destino)

        salida("Instalando (puede tardar unos minutos)...")
        entorno = dict(os.environ)
        entorno.setdefault("UV_HTTP_TIMEOUT", "300")  # igual que el instalador: hay paquetes grandes
        paquete = f"{_PAQUETE}[diarizacion] @ {archivo.as_uri()}"
        # Sin capturar la salida: así se ve el avance de uv en la terminal.
        resultado = subprocess.run(_comando_uv(uv, paquete), env=entorno)
        return "listo" if resultado.returncode == 0 else "error"
    finally:
        shutil.rmtree(temporal, ignore_errors=True)


def actualizar(novedad: Novedad, salida=print) -> str:
    """Instala `novedad`. Devuelve «listo», «reiniciar_aparte» (Windows: cerrar el programa ya) o «error»."""
    try:
        if como_se_instalo() != "uv_tool":
            log.info("No se actualiza: no es una instalación de uv tool.")
            return "error"
        uv = buscar_uv()
        if not uv:
            log.info("No se actualiza: no se encontró uv.")
            return "error"
        if sys.platform == "win32":
            return _actualizar_en_windows(novedad, uv, salida)
        return _actualizar_en_unix(novedad, uv, salida)
    except Exception as error:
        log.warning("No se pudo actualizar: %s", error)
        return "error"
