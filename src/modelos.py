# Ubicación: src/modelos.py
# Los modelos que el programa baja de Hugging Face (Whisper para transcribir, pyannote para
# identificar hablantes): cuáles ya están en este computador, cuánto pesan, descargarlos con
# avance, borrarlos, y la clave (token) de Hugging Face que pyannote necesita.
# Antes todo esto pasaba sin avisar la primera vez que se usaba (parecía colgado) y fallaba con
# «Sin internet». Aquí se descarga a propósito, a la caché estándar de huggingface_hub.
# huggingface_hub y faster_whisper se importan dentro de las funciones ("Importación diferida"):
# CI no los instala y no deben cargarse al arrancar el programa.
import contextlib
import inspect
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src import ajustes, config, errores, historial, plataforma, transcriber

logger = logging.getLogger(__name__)

MODELOS_TRANSCRIPCION = ["turbo", "large", "medium", "small", "base", "tiny"]
HABLANTES = "hablantes"

# Peso aproximado en bytes, para mostrarlo ANTES de descargar (el real se ve ya descargado).
# Son cifras redondas, no exactas: cambian un poco según la versión del modelo.
PESO_APROXIMADO = {
    "turbo": 1_600_000_000,
    "large": 3_100_000_000,
    "medium": 1_500_000_000,
    "small": 480_000_000,
    "base": 150_000_000,
    "tiny": 80_000_000,
    HABLANTES: 30_000_000,
}

# Respaldo de faster_whisper.utils._MODELS (faster-whisper >= 1.1), por si esa tabla privada
# cambia de nombre o lugar. Fuente: faster_whisper/utils.py de esa versión.
_REPOS_FASTER = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large": "Systran/faster-whisper-large-v3",
    "large-v3": "Systran/faster-whisper-large-v3",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}

PAGINA_TOKENS = "https://huggingface.co/settings/tokens"
# Preferencia que se guarda al elegir «Ahora no» a la clave en «Preparar la app»
SIN_CLAVE_ELEGIDO = "preparar_sin_clave"
PAGINA_MODELO = f"https://huggingface.co/{config.DIARIZATION_MODEL}"

MENSAJE_SIN_INTERNET = "No hay conexión a internet para descargar el modelo."
MENSAJE_TOKEN_NO_SIRVE = "La clave de Hugging Face no sirve o falta aceptar las condiciones del modelo."


@dataclass
class EstadoModelo:
    clave: str
    nombre: str          # texto visible
    repo: str
    descargado: bool
    bytes: Optional[int]  # lo que ocupa de verdad si está descargado; si no, None


# --- Qué repo es cada modelo --------------------------------------------------

def repo_de(clave: str) -> str:
    """El repo de Hugging Face de un modelo (el que de verdad queda en la caché)."""
    if clave == HABLANTES:
        return config.DIARIZATION_MODEL
    if transcriber.motor() == transcriber.MOTOR_MLX:
        return transcriber.resolver_modelo(clave)
    nombre = transcriber.MODELOS_FASTER.get(clave, clave)
    # Primero la tabla propia: importar faster_whisper carga ctranslate2 y tarda segundos al abrir el menú
    if nombre in _REPOS_FASTER or clave in _REPOS_FASTER:
        return _REPOS_FASTER.get(nombre) or _REPOS_FASTER[clave]
    try:
        from faster_whisper.utils import _MODELS
        if nombre in _MODELS:
            return _MODELS[nombre]
    except Exception:
        pass
    return nombre


def _nombre_visible(clave: str) -> str:
    return "Identificar hablantes" if clave == HABLANTES else clave


# --- Qué hay descargado -------------------------------------------------------

def _repos_en_cache() -> dict:
    """{repo_id: info del repo} de la caché; vacío si no hay huggingface_hub o la caché no existe."""
    try:
        from huggingface_hub import scan_cache_dir
        informe = scan_cache_dir()
        return {r.repo_id: r for r in informe.repos if getattr(r, "repo_type", "model") == "model"}
    except Exception as e:
        logger.debug(f"No se pudo leer la caché de modelos: {type(e).__name__}")
        return {}


def estado(claves: Optional[list] = None) -> list:
    """El estado de cada modelo. Hablantes solo aparece si funciona en este computador."""
    claves = list(MODELOS_TRANSCRIPCION + [HABLANTES] if claves is None else claves)
    if not plataforma.hablantes_disponible():
        claves = [c for c in claves if c != HABLANTES]
    cache = _repos_en_cache()
    lista = []
    for clave in claves:
        try:
            repo = repo_de(clave)
        except Exception:  # un nombre que el motor no reconoce
            continue
        info = cache.get(repo)
        lista.append(EstadoModelo(clave, _nombre_visible(clave), repo, info is not None,
                                  int(info.size_on_disk) if info is not None else None))
    return lista


def descargado(clave: str) -> bool:
    return any(m.clave == clave and m.descargado for m in estado([clave]))


def texto_peso(bytes_: int) -> str:
    """'1,6 GB', '480 MB' (unidades de 1000, como las muestra Hugging Face; coma decimal)."""
    if bytes_ >= 1_000_000_000:
        return f"{bytes_ / 1e9:.1f}".replace(".", ",") + " GB"
    if bytes_ >= 1_000_000:
        return f"{round(bytes_ / 1e6)} MB"
    return f"{max(1, round(bytes_ / 1e3))} KB"


# --- Descargar y borrar -------------------------------------------------------

@contextlib.contextmanager
def con_internet():
    """
    Apaga «Sin internet» mientras dura el bloque y lo deja como estaba al salir (también si hay
    error): descargar un modelo necesita red aunque el resto del tiempo se trabaje sin ella.
    """
    estaba = ajustes.sin_internet_activo()
    if estaba:
        ajustes.aplicar_sin_internet(False)
    try:
        yield
    finally:
        if estaba:
            ajustes.aplicar_sin_internet(True)


def _clase_tqdm(progreso: Callable[[int, int], None]):
    """
    Una barra tqdm que no dibuja nada: cuenta bytes y avisa a progreso(hecho, total).
    huggingface_hub (2.x) NO crea una barra por archivo con esta clase: crea dos barras de bytes de
    toda la descarga (bytes recibidos y bytes escritos), que empiezan con total=0 y van subiendo el
    total a medida que conoce cada archivo (asignando .total, no al crearlas). Por eso:
    - el total se sigue también cuando se asigna después (propiedad), y
    - se informa la barra más avanzada, no la suma: sumar las dos contaría cada byte dos veces.
    La barra por cantidad de archivos (sin unidad "B") se ignora.
    """
    try:
        from tqdm.auto import tqdm as base
    except Exception:
        class base:  # sin tqdm instalado: lo mínimo que huggingface_hub usa de una barra
            def __init__(self, *args, **kwargs):
                self.total = kwargs.get("total")

            def update(self, n=1):
                return True

            def refresh(self, *args, **kwargs):
                pass

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()
    barras = []  # las barras de bytes creadas en esta descarga

    def avisar():
        if not barras:
            return
        guia = max(barras, key=lambda b: (b.total or 0, b._hecho))
        try:
            progreso(guia._hecho, int(guia.total or 0))
        except Exception:
            logger.debug("El aviso de progreso falló", exc_info=True)

    class BarraSilenciosa(base):
        def __init__(self, *args, **kwargs):
            self._bytes = kwargs.get("unit") == "B"
            self._hecho = int(kwargs.get("initial") or 0)
            kwargs["disable"] = True  # no dibujar; solo contar
            super().__init__(*args, **kwargs)
            if self._bytes:
                barras.append(self)
                avisar()

        @property
        def total(self):
            return self.__dict__.get("_total_barra")

        @total.setter
        def total(self, valor):
            self.__dict__["_total_barra"] = valor
            # Por identidad: tqdm compara barras por su posición en pantalla, no por quién es
            if getattr(self, "_bytes", False) and any(b is self for b in barras):
                avisar()

        def update(self, n=1):
            if self._bytes and n:
                self._hecho += int(n)
                avisar()
            return super().update(n)

    return BarraSilenciosa


def _traducir_error(e: BaseException, clave: str) -> Optional[str]:
    cadena = errores.cadena(e)
    if errores.sin_internet(cadena):
        return MENSAJE_SIN_INTERNET
    if clave == HABLANTES and _es_acceso_denegado(cadena):
        return MENSAJE_TOKEN_NO_SIRVE
    return None


def _estado_http(e: BaseException) -> Optional[int]:
    respuesta = getattr(e, "response", None)
    codigo = getattr(respuesta, "status_code", None)
    return codigo if isinstance(codigo, int) else None


def _es_acceso_denegado(cadena: list) -> bool:
    for x in cadena:
        if type(x).__name__ in ("GatedRepoError", "RepositoryNotFoundError"):
            return True
        if _estado_http(x) in (401, 403):
            return True
    texto = errores._textos(cadena)
    return any(t in texto for t in ("gated", "401 client error", "403 client error", "access to model"))


def descargar(clave: str, progreso: Optional[Callable[[int, int], None]] = None) -> None:
    """
    Descarga el modelo a la caché. progreso(completado, total) recibe bytes cuando se puede medir.
    Los errores típicos (sin internet, clave que no sirve) suben como RuntimeError con un texto simple.
    """
    repo = repo_de(clave)
    try:
        with con_internet():
            if clave != HABLANTES and transcriber.motor() == transcriber.MOTOR_FASTER:
                _descargar_faster(clave, repo)
            else:
                _descargar_repo(repo, progreso, token_guardado() if clave == HABLANTES else None)
    except Exception as e:
        mensaje = _traducir_error(e, clave)
        if mensaje:
            raise RuntimeError(mensaje) from e
        raise


def _descargar_repo(repo: str, progreso, token: Optional[str]):
    from huggingface_hub import snapshot_download
    kwargs = {}
    if token:
        kwargs["token"] = token
    if progreso is not None:
        try:
            acepta = "tqdm_class" in inspect.signature(snapshot_download).parameters
        except (TypeError, ValueError):
            acepta = False
        clase = _clase_tqdm(progreso) if acepta else None
        if clase is not None:
            kwargs["tqdm_class"] = clase
    snapshot_download(repo, **kwargs)


def _descargar_faster(clave: str, repo: str):
    """faster-whisper baja solo los archivos que usa (no todo el repo): se deja que él lo haga."""
    try:
        from faster_whisper.utils import download_model
    except Exception:
        download_model = None
    if download_model is not None:
        download_model(transcriber.MODELOS_FASTER.get(clave, clave))
    else:
        _descargar_repo(repo, None, None)


def eliminar(clave: str) -> int:
    """Borra el modelo de la caché (todas sus revisiones). Devuelve los bytes liberados (0 si no estaba)."""
    from huggingface_hub import scan_cache_dir
    repo = repo_de(clave)
    try:
        informe = scan_cache_dir()
    except Exception as e:  # sin caché todavía (CacheNotFound) o ilegible: no hay nada que borrar
        logger.info(f"No se pudo leer la caché de modelos: {e}")
        return 0
    for r in informe.repos:
        if r.repo_id == repo and getattr(r, "repo_type", "model") == "model":
            hashes = [rev.commit_hash for rev in r.revisions]
            if not hashes:
                return 0
            estrategia = informe.delete_revisions(*hashes)
            liberado = int(estrategia.expected_freed_size)
            estrategia.execute()
            return liberado
    return 0


# --- La clave (token) de Hugging Face ----------------------------------------

def token_guardado() -> Optional[str]:
    """La clave vigente ahora (se lee en el momento: guardar_token la cambia sin reiniciar)."""
    return os.environ.get("HF_TOKEN") or None


def comprobar_token(token: str) -> str:
    """
    'ok', 'invalida', 'sin_acceso' (no aceptó las condiciones del modelo), 'sin_internet' o 'desconocido'.
    Nunca escribe el token en pantalla ni en el registro.
    """
    repo = config.DIARIZATION_MODEL
    etapa = "clave"
    try:
        with con_internet():
            from huggingface_hub import HfApi
            api = HfApi()
            api.whoami(token=token)
            etapa = "modelo"
            try:
                from huggingface_hub import auth_check
            except ImportError:
                auth_check = None
            if auth_check is not None:
                auth_check(repo, token=token)
            else:
                api.model_info(repo, token=token)
        return "ok"
    except Exception as e:
        cadena = errores.cadena(e)
        logger.info(f"Comprobar la clave de Hugging Face falló: {type(e).__name__}")
        if errores.sin_internet(cadena):
            return "sin_internet"
        for x in cadena:
            codigo = _estado_http(x)
            nombre = type(x).__name__
            if nombre in ("GatedRepoError", "RepositoryNotFoundError"):
                return "sin_acceso" if etapa == "modelo" else "invalida"
            if codigo == 401:
                return "invalida"
            if codigo == 403:
                return "sin_acceso" if etapa == "modelo" else "invalida"
        return "desconocido"


def guardar_token(token: str) -> Path:
    """
    Guarda HF_TOKEN en ~/.transcriptor/.env (reemplaza la línea si existe; conserva las demás) y
    lo deja vigente en esta ejecución. Ojo: si el .env del proyecto (carpeta de trabajo) define
    HF_TOKEN, ese manda al reiniciar, porque así lo carga src/config.py.
    """
    token = token.strip()
    if not token or any(c.isspace() for c in token):
        raise ValueError("La clave está vacía o tiene espacios.")  # sin incluir la clave
    ruta = historial.carpeta() / ".env"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    try:
        lineas = ruta.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        lineas = []
    nueva, puesta = f"HF_TOKEN={token}", False
    resultado = []
    for linea in lineas:
        if linea.strip().startswith("HF_TOKEN="):
            if not puesta:
                resultado.append(nueva)
                puesta = True
        else:
            resultado.append(linea)
    if not puesta:
        resultado.append(nueva)
    ruta.write_text("\n".join(resultado) + "\n", encoding="utf-8")
    try:
        ruta.chmod(0o600)
    except OSError:
        logger.debug("No se pudo restringir el permiso del .env")
    os.environ["HF_TOKEN"] = token
    config.HF_TOKEN = token
    logger.info("Clave de Hugging Face guardada")
    return ruta


# --- Antes de usar el programa por primera vez --------------------------------

def necesita_preparacion() -> bool:
    """True si falta bajar el modelo por defecto, o (si hablantes está instalado) su clave o su modelo."""
    try:
        if not descargado(ajustes.valor("modelo")):
            return True
        if (plataforma.hablantes_disponible() and _pyannote_instalado()
                and ajustes.valor("modo_hablantes") != ajustes.NUNCA):
            if not token_guardado():
                # Quien dijo «Ahora no» a la clave no quiere ver «Preparar la app» para siempre
                return not historial.preferencias().get(SIN_CLAVE_ELEGIDO)
            return not descargado(HABLANTES)
    except Exception:
        logger.debug("No se pudo saber si falta preparar la app", exc_info=True)
    return False


def _pyannote_instalado() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("pyannote.audio") is not None
    except (ImportError, ValueError):
        return False
