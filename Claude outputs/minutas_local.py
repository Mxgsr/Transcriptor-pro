#!/usr/bin/env python3
"""
Genera minutas a partir de transcripciones usando LM Studio (API local).

Uso:
    python minutas_local.py "C:/ruta/a/carpeta_transcripciones"

Requisitos:
  - LM Studio con el servidor local activo (pestaña "Developer" > Start Server)
    y Gemma 4 12B cargado.
  - Python 3.9+. No necesita instalar librerías.

Por cada .txt / .md / .vtt / .srt de la carpeta crea "<nombre>_minuta.md"
en una subcarpeta "minutas". No toca los originales ni reprocesa los que ya
tienen minuta.
"""
import json
import sys
import urllib.request
from pathlib import Path

BASE_URL = "http://localhost:1234/v1"   # puerto por defecto de LM Studio
MODEL = None                            # None = usa el primer modelo cargado
TEMPERATURE = 0.2                       # bajo = más fiel a la transcripción
CHUNK_CHARS = 20000                     # reuniones más largas se procesan por bloques
EXTENSIONES = {".txt"}                  # Transcriptor Pro guarda "<nombre>.blocks.txt"

SYSTEM_PROMPT = """Eres un asistente que redacta minutas de reunión en español \
formal y claro, a partir de transcripciones automáticas.

Reglas:
- Usa SOLO información presente en la transcripción. No inventes nombres, cifras, \
fechas ni compromisos.
- La transcripción puede tener errores de reconocimiento de voz. Si un nombre, \
cifra o término es dudoso, déjalo y márcalo con [verificar].
- Si algo no queda claro (por ejemplo, quién es responsable de una tarea), \
escribe "No especificado".
- Sé conciso: frases breves, sin relleno ni saludos."""

MINUTA_PROMPT = """Redacta la minuta de esta reunión con exactamente esta estructura \
en Markdown:

# Minuta de reunión
**Fecha:** (si aparece en la transcripción; si no, "No especificada")
**Participantes:** (lista separada por comas)

## Objetivo de la reunión
(1-2 frases)

## Temas tratados
(un subtítulo por tema, con 2-4 viñetas de lo discutido)

## Acuerdos y decisiones
(viñetas)

## Tareas y responsables
| Tarea | Responsable | Plazo |
|---|---|---|

## Pendientes y próximos pasos
(viñetas; incluir fecha de próxima reunión si se mencionó)

Transcripción:
\"\"\"
{texto}
\"\"\""""

RESUMEN_BLOQUE_PROMPT = """Esta es una parte de una reunión más larga. Extrae en \
viñetas: participantes que hablan, temas tratados, acuerdos, tareas (con \
responsable y plazo si se mencionan) y datos relevantes. No inventes nada; \
marca con [verificar] lo dudoso.

Parte de la transcripción:
\"\"\"
{texto}
\"\"\""""


def api(path, payload=None):
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode() if payload else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def modelo():
    if MODEL:
        return MODEL
    return api("/models")["data"][0]["id"]


def chat(model, user_prompt):
    out = api("/chat/completions", {
        "model": model,
        "temperature": TEMPERATURE,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    })
    return out["choices"][0]["message"]["content"].strip()


def trocear(texto, n):
    """Corta en bloques de ~n caracteres, respetando saltos de línea."""
    bloques, actual = [], ""
    for linea in texto.splitlines(keepends=True):
        if len(actual) + len(linea) > n and actual:
            bloques.append(actual)
            actual = ""
        actual += linea
    if actual.strip():
        bloques.append(actual)
    return bloques


def generar_minuta(model, texto):
    if len(texto) <= CHUNK_CHARS:
        return chat(model, MINUTA_PROMPT.format(texto=texto))
    # Reunión larga: resumir por bloques y luego armar la minuta final
    parciales = []
    for i, b in enumerate(trocear(texto, CHUNK_CHARS), 1):
        print(f"    bloque {i}...")
        parciales.append(chat(model, RESUMEN_BLOQUE_PROMPT.format(texto=b)))
    return chat(model, MINUTA_PROMPT.format(texto="\n\n".join(parciales)))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    carpeta = Path(sys.argv[1])
    salida = carpeta / "minutas"
    salida.mkdir(exist_ok=True)
    try:
        model = modelo()
    except Exception as e:
        sys.exit(f"No pude conectar con LM Studio en {BASE_URL}: {e}\n"
                 "¿Está activo el servidor local y hay un modelo cargado?")
    print(f"Modelo: {model}")

    archivos = sorted(p for p in carpeta.iterdir()
                      if p.suffix.lower() in EXTENSIONES and p.is_file())
    for p in archivos:
        nombre = p.name.split(".blocks")[0] if ".blocks" in p.name else p.stem
        destino = salida / f"{nombre}_minuta.md"
        if destino.exists():
            continue
        print(f"Procesando {p.name}")
        texto = p.read_text(encoding="utf-8", errors="ignore")
        destino.write_text(generar_minuta(model, texto), encoding="utf-8")
        print(f"  -> {destino}")


if __name__ == "__main__":
    main()
