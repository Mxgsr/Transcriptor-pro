# Ubicación: src/actualizar.py
# «Buscar actualizaciones» desde el programa, sin volver a pegar la línea del instalador.
# - buscar(): mira la versión que hay en GitHub (rama estable y, si se usa la beta, la beta).
# - buscar_en_segundo_plano(): lo mismo, sin molestar y como mucho una vez por semana.
# - actualizar(): hace lo mismo que instalar.sh / instalar.ps1 (uv tool install), pero sobre el zip del
#   último commit de la rama, y solo si trae la versión anunciada y es más nueva que la instalada.
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
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src import ajustes, historial, plataforma, rutas_windows
from src.entorno import sin_secretos as entorno_sin_secretos

logger = logging.getLogger(__name__)

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
        logger.debug("No se pudo leer la versión del proyecto: %s", error)
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
        logger.debug("No se pudo consultar la rama %s: %s", rama, error)
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
        logger.debug("No se pudo leer el aviso guardado: %s", error)
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
        logger.debug("No se pudo decidir si buscar actualizaciones: %s", error)
        return None

    def trabajo():
        try:
            buscar(timeout=3)
        except Exception as error:  # sin internet, disco de solo lectura...: no importa
            logger.debug("Búsqueda de actualizaciones en segundo plano falló: %s", error)

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
    if plataforma.es_windows():
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
        logger.debug("No se pudo saber cómo se instaló: %s", error)
    return "otro"


def buscar_uv() -> Optional[str]:
    """La ruta de uv, o None si no se encuentra."""
    encontrado = rutas_windows.buscar_programa("uv")
    if encontrado:
        return encontrado
    nombre = "uv.exe" if plataforma.es_windows() else "uv"
    candidato = Path.home() / ".local" / "bin" / nombre
    return str(candidato) if candidato.exists() else None


# ---------------------------------------------------------------------------
# 4. Actualizar
# ---------------------------------------------------------------------------
# No hay firma ni hash publicados por el dueño, así que esto no protege de alguien con permiso para
# subir cambios a la rama. Sí evita instalar algo distinto de lo que se anunció: se fija el commit
# (el contenido de un commit no cambia, el de una rama sí) y se comprueba la versión del zip antes de
# instalarlo, para no instalar nunca otra versión, la misma o una más vieja.
_TAMANO_MAXIMO_ZIP = 200 * 1024 * 1024  # el proyecto pesa unos pocos MB: esto ya es absurdo
_TAMANO_MAXIMO_API = 1024  # la respuesta es solo un SHA de 40 caracteres
_TAMANO_MAXIMO_PYPROJECT = 1024 * 1024
_PATRON_SHA = re.compile(r"[0-9a-f]{40}")
_BLOQUE = 1024 * 1024


class _Rechazo(Exception):
    """La actualización no es la que se anunció o no se pudo comprobar: no se instala nada."""


def _url_api_commit(rama: str) -> str:
    return f"https://api.github.com/repos/{REPO}/commits/{rama}"


def _url_zip(sha: str) -> str:
    return f"https://github.com/{REPO}/archive/{sha}.zip"


def _leer_con_limite(respuesta, limite: int, destino=None) -> bytes:
    """Lee `respuesta` por partes y corta si pasa de `limite`. Con `destino` escribe allí en vez de devolver."""
    largo = respuesta.headers.get("Content-Length") if getattr(respuesta, "headers", None) else None
    if largo and str(largo).isdigit() and int(largo) > limite:
        raise _Rechazo(f"la descarga anuncia {largo} bytes, más que el máximo ({limite})")
    partes, total = [], 0
    while True:
        bloque = respuesta.read(_BLOQUE)
        if not bloque:
            break
        total += len(bloque)
        # Content-Length puede faltar o mentir: se cuenta lo que llega de verdad
        if total > limite:
            raise _Rechazo(f"la descarga pasa del máximo ({limite} bytes)")
        if destino is None:
            partes.append(bloque)
        else:
            destino.write(bloque)
    return b"".join(partes)


def _resolver_commit(rama: str, timeout: float = 20) -> str:
    """El SHA del último commit de `rama`. Si no se puede saber, se rechaza: nunca se cae a la rama."""
    if rama not in (RAMA_ESTABLE, RAMA_BETA):
        # La rama sale de preferencias.json: solo se aceptan las dos que publica el dueño
        raise _Rechazo(f"rama desconocida: {rama!r}")
    peticion = urllib.request.Request(
        _url_api_commit(rama),
        # Con este Accept GitHub responde solo el SHA, en texto: sin la lista de archivos del commit
        # (que puede pesar varios MB y haría fallar la actualización si no cabe en el tope).
        headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github.sha"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            sha = _leer_con_limite(respuesta, _TAMANO_MAXIMO_API).decode("ascii").strip()
    except _Rechazo:
        raise
    except Exception as error:
        raise _Rechazo(f"no se pudo saber el commit de la rama {rama}: {error}") from error
    if not _PATRON_SHA.fullmatch(sha.lower()):
        raise _Rechazo(f"la respuesta de GitHub no trae un commit válido: {sha[:60]!r}")
    return sha.lower()


def _descargar_zip(sha: str, archivo: Path, timeout: float = 120) -> None:
    peticion = urllib.request.Request(_url_zip(sha), headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta, open(archivo, "wb") as destino:
        _leer_con_limite(respuesta, _TAMANO_MAXIMO_ZIP, destino)


def _ruta_peligrosa(nombre: str) -> bool:
    """True si la ruta de una entrada del zip podría escribir fuera de la carpeta donde se extrae."""
    ruta = nombre.replace("\\", "/")
    if ruta.startswith("/") or re.match(r"^[A-Za-z]:", ruta):
        return True
    return ".." in ruta.split("/")


def _version_del_zip(archivo: Path) -> str:
    """Revisa el zip y devuelve la versión de su pyproject.toml raíz. Rechaza lo que no cuadre."""
    try:
        with zipfile.ZipFile(archivo) as zip_:
            nombres = zip_.namelist()
            # uv lo extrae él mismo, pero por si acaso no se acepta nada que salga de su carpeta
            peligrosas = [n for n in nombres if _ruta_peligrosa(n)]
            if peligrosas:
                raise _Rechazo(f"el zip trae rutas peligrosas: {peligrosas[:3]}")
            # GitHub mete todo en una carpeta raíz (Transcriptor-pro-<sha>/)
            raices = {n.replace("\\", "/").split("/")[0] for n in nombres}
            if len(raices) != 1:
                raise _Rechazo(f"el zip no tiene una sola carpeta raíz: {sorted(raices)[:3]}")
            raiz = raices.pop()
            ruta_pyproject = f"{raiz}/pyproject.toml"
            if ruta_pyproject not in nombres:
                raise _Rechazo("el zip no trae pyproject.toml en su carpeta raíz")
            if zip_.getinfo(ruta_pyproject).file_size > _TAMANO_MAXIMO_PYPROJECT:
                raise _Rechazo("el pyproject.toml del zip es demasiado grande")
            texto = zip_.read(ruta_pyproject).decode("utf-8", errors="replace")
    except _Rechazo:
        raise
    except Exception as error:  # zip roto o que no es zip
        raise _Rechazo(f"el zip descargado no se pudo leer: {error}") from error
    version = _version_del_texto(texto)
    if not version:
        raise _Rechazo("el pyproject.toml del zip no dice su versión")
    return version


def _comprobar_version(version_zip: str, novedad: "Novedad") -> None:
    if comparar(version_zip, novedad.version) != 0:
        # Desfase (alguien subió otra cosa entre la búsqueda y la descarga) o algo raro: no se instala
        raise _Rechazo(f"el zip trae la versión {version_zip} y se anunció la {novedad.version}")
    instalada = version_instalada()
    if comparar(version_zip, instalada) <= 0:
        raise _Rechazo(f"el zip trae la versión {version_zip}, que no es más nueva que la instalada ({instalada})")


def _preparar_zip(novedad: "Novedad", carpeta: str, salida) -> Path:
    """Fija el commit, descarga su zip en `carpeta` y lo comprueba. Devuelve la ruta del zip verificado."""
    sha = _resolver_commit(novedad.rama)
    logger.info("Actualizando a %s desde el commit %s de %s.", novedad.version, sha, novedad.rama)
    archivo = Path(carpeta) / "transcriptor-pro.zip"
    salida("Descargando la nueva versión...")
    _descargar_zip(sha, archivo)
    salida("Revisando lo descargado...")
    _comprobar_version(_version_del_zip(archivo), novedad)
    return archivo


def _comando_uv(uv: str, paquete: str) -> list:
    # El mismo comando que usan instalar.sh e instalar.ps1.
    return [uv, "tool", "install", "--force", "--upgrade", "--reinstall-package", _PAQUETE,
            "--python", "3.11", paquete]


# El script va escrito SOLO con ASCII (por eso los mensajes no llevan tildes): Windows PowerShell 5.1
# lee un .ps1 sin BOM con la página de códigos local y dañaría cualquier tilde. El pid, la ruta de uv y
# la del zip (ya descargado y revisado por Python) llegan por variables de entorno, nunca pegados en el
# script. El script no descarga nada: así instala exactamente lo que se revisó.
_PS_ACTUALIZAR = r"""
$ErrorActionPreference = "Stop"
$Archivo = $env:TRANSCRIPTOR_ZIP
$Temporal = $null
if ($Archivo) {
    $Carpeta = Split-Path -Parent $Archivo
    # Solo se borra la carpeta temporal que creo Transcriptor, nunca otra
    if ((Split-Path -Leaf $Carpeta) -like "transcriptor-actualizar-*") { $Temporal = $Carpeta }
}
try {
    Write-Host "Cerrando Transcriptor para actualizarlo..."
    try { Wait-Process -Id ([int]$env:TRANSCRIPTOR_PID) -ErrorAction Stop } catch { }
    # transcriptor.exe (el lanzador de uv) cierra un instante despues de Python: le damos tiempo
    Start-Sleep -Seconds 3
    if (-not $Archivo -or -not (Test-Path -LiteralPath $Archivo -PathType Leaf)) {
        throw "no se encontro la nueva version descargada"
    }
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
Read-Host "Aprieta Enter para cerrar esta ventana"
# PowerShell ya leyo el script entero: se puede borrar su carpeta (zip y script) aunque siga abierto
if ($Temporal) { Remove-Item -Recurse -Force -LiteralPath $Temporal -ErrorAction SilentlyContinue }
Remove-Item -Force -LiteralPath $PSCommandPath -ErrorAction SilentlyContinue
"""


def _actualizar_en_windows(novedad: Novedad, uv: str, salida) -> str:
    # El transcriptor.exe abierto está bloqueado y uv no puede reemplazarlo: un proceso aparte
    # espera a que este programa se cierre y recién entonces instala. La descarga y la revisión se
    # hacen aquí, antes, para que esa ventana solo instale un zip ya comprobado.
    assert _PS_ACTUALIZAR.isascii()
    carpeta = tempfile.mkdtemp(prefix="transcriptor-actualizar-")
    try:
        archivo = _preparar_zip(novedad, carpeta, salida)
        script = os.path.join(carpeta, "actualizar.ps1")
        with open(script, "w", encoding="ascii", newline="\r\n") as escrito:
            escrito.write(_PS_ACTUALIZAR)
        entorno = entorno_sin_secretos({
            **os.environ,
            "TRANSCRIPTOR_PID": str(os.getpid()),
            "TRANSCRIPTOR_UV": uv,
            "TRANSCRIPTOR_ZIP": str(archivo),
        })
        salida("Se abrirá otra ventana que termina la actualización cuando se cierre este programa.")
        subprocess.Popen(
            # Ruta completa: sin ella Windows usaría un powershell.exe que esté en la carpeta actual
            [rutas_windows.powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
            env=entorno,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", _CREATE_NEW_CONSOLE),
        )
    except BaseException:
        # Si no se lanzó la ventana, nadie más va a borrar la carpeta
        shutil.rmtree(carpeta, ignore_errors=True)
        raise
    return "reiniciar_aparte"


def _actualizar_en_unix(novedad: Novedad, uv: str, salida) -> str:
    temporal = tempfile.mkdtemp(prefix="transcriptor-actualizar-")
    try:
        archivo = _preparar_zip(novedad, temporal, salida)
        salida("Instalando (puede tardar unos minutos)...")
        entorno = entorno_sin_secretos()
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
            logger.info("No se actualiza: no es una instalación de uv tool.")
            return "error"
        uv = buscar_uv()
        if not uv:
            logger.info("No se actualiza: no se encontró uv.")
            return "error"
        if plataforma.es_windows():
            return _actualizar_en_windows(novedad, uv, salida)
        return _actualizar_en_unix(novedad, uv, salida)
    except _Rechazo as motivo:
        logger.warning("No se instaló la actualización: %s", motivo)
        return "error"
    except Exception as error:
        logger.warning("No se pudo actualizar: %s", error)
        return "error"
