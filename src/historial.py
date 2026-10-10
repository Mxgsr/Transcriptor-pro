# Ubicación: src/historial.py
# Lo que el programa recuerda entre usos: las transcripciones hechas (para "Mis transcripciones"
# del menú) y lo último que elegiste en el menú (modelo, hablantes...), para ofrecerlo por defecto.
# Vive en ~/.transcriptor/ (o en la carpeta que diga TRANSCRIPTOR_HOME).
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ARCHIVO_HISTORIAL = "historial.json"
ARCHIVO_PREFERENCIAS = "preferencias.json"
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
