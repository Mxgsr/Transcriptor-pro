# Ubicación: src/historial.py
# Lo que el programa recuerda entre usos: las transcripciones hechas (para "Mis transcripciones"
# del menú) y lo último que elegiste en el menú (modelo, hablantes...), para ofrecerlo por defecto.
# Vive en ~/.transcriptor/ (o en la carpeta que diga TRANSCRIPTOR_HOME).
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ARCHIVO_HISTORIAL = "historial.json"
ARCHIVO_PREFERENCIAS = "preferencias.json"
# Las personas con las que se graba seguido: {"Ana": {"veces": 3, "ultima": <timestamp>}}
ARCHIVO_PERSONAS = "personas.json"
# Más que suficiente para la lista del menú, sin que el archivo crezca para siempre
MAX_ENTRADAS = 200


def carpeta() -> Path:
    return Path(os.getenv("TRANSCRIPTOR_HOME", "~/.transcriptor")).expanduser()


def _leer(nombre: str, defecto):
    """Si el archivo no existe o está dañado, se empieza de cero: nunca debe impedir usar el programa."""
    try:
        datos = json.loads((carpeta() / nombre).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto
    return datos if isinstance(datos, type(defecto)) else defecto


def _escribir(nombre: str, datos):
    try:
        carpeta().mkdir(parents=True, exist_ok=True)
        destino = carpeta() / nombre
        # Escribimos aparte y reemplazamos, para no dejar el archivo a medias si algo falla
        temporal = destino.with_name(destino.name + ".tmp")
        temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        temporal.replace(destino)
    except OSError as e:
        logger.warning(f"No se pudo guardar {nombre} en {carpeta()}: {e}")


def registrar(txt_path: Path, json_path: Optional[Path] = None, audio_path: Optional[Path] = None,
              duracion: Optional[float] = None):
    """Anota (o pone primera) una transcripción en el historial."""
    txt = str(Path(txt_path).expanduser().resolve())
    entradas = [e for e in _leer(ARCHIVO_HISTORIAL, []) if isinstance(e, dict)]
    anterior = next((e for e in entradas if e.get("txt") == txt), {})
    entrada = {
        "txt": txt,
        "json": str(Path(json_path).expanduser().resolve()) if json_path else anterior.get("json"),
        "audio": str(Path(audio_path).expanduser().resolve()) if audio_path else anterior.get("audio"),
        "duracion": duracion if duracion is not None else anterior.get("duracion"),
        "fecha": time.time(),
    }
    resto = [e for e in entradas if e.get("txt") != txt]
    _escribir(ARCHIVO_HISTORIAL, [entrada, *resto][:MAX_ENTRADAS])


def listar() -> list:
    """
    Las transcripciones del historial que todavía existen, de la más reciente a la más antigua.
    Cada una: {"txt": Path, "json": Path o None, "audio": Path o None, "duracion": float o None, "fecha": float}.
    """
    entradas = []
    for e in _leer(ARCHIVO_HISTORIAL, []):
        if not isinstance(e, dict) or not e.get("txt"):
            continue
        txt = Path(e["txt"])
        if not txt.exists():
            continue
        json_path = Path(e["json"]) if e.get("json") else None
        entradas.append({
            "txt": txt,
            "json": json_path if json_path and json_path.exists() else None,
            "audio": Path(e["audio"]) if e.get("audio") else None,
            "duracion": e.get("duracion"),
            "fecha": e.get("fecha") or txt.stat().st_mtime,
        })
    return sorted(entradas, key=lambda e: e["fecha"], reverse=True)


def preferencias() -> dict:
    """Lo último que se eligió en el menú ({} la primera vez)."""
    return _leer(ARCHIVO_PREFERENCIAS, {})


def guardar_preferencias(**cambios):
    _escribir(ARCHIVO_PREFERENCIAS, {**preferencias(), **cambios})


def _es_nombre_de_persona(nombre) -> bool:
    """Un nombre real: no vacío y no una etiqueta genérica como "Hablante 1"."""
    # Importación diferida: así este módulo no depende del diarizador al cargarse
    from src.diarizer import ETIQUETA_GENERICA

    if not isinstance(nombre, str) or not nombre.strip():
        return False
    return not re.fullmatch(rf"{re.escape(ETIQUETA_GENERICA)} \d+", nombre.strip())


def personas() -> list:
    """Los nombres guardados: primero los más usados y, a igual uso, los más recientes."""
    datos = _leer(ARCHIVO_PERSONAS, {})
    validos = [(n, d) for n, d in datos.items() if isinstance(d, dict) and _es_nombre_de_persona(n)]

    def numero(d, clave):
        valor = d.get(clave)
        return valor if isinstance(valor, (int, float)) else 0

    validos.sort(key=lambda par: (numero(par[1], "veces"), numero(par[1], "ultima")), reverse=True)
    return [n for n, _ in validos]


def recordar_personas(nombres):
    """Suma un uso a cada nombre (una vez por nombre aunque se repita). Ignora vacíos y etiquetas genéricas."""
    nuevos = []
    for n in nombres:
        n = n.strip() if isinstance(n, str) else n
        if _es_nombre_de_persona(n) and n not in nuevos:
            nuevos.append(n)
    if not nuevos:
        return
    datos = _leer(ARCHIVO_PERSONAS, {})
    ahora = time.time()
    for n in nuevos:
        anterior = datos.get(n) if isinstance(datos.get(n), dict) else {}
        veces = anterior.get("veces") if isinstance(anterior.get("veces"), int) else 0
        datos[n] = {"veces": veces + 1, "ultima": ahora}
    _escribir(ARCHIVO_PERSONAS, datos)
