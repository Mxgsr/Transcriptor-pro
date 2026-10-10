# Ubicación: src/corrector.py
# Corrige una transcripción ya hecha con un modelo de lenguaje local (mlx-lm).
# Solo el texto de cada párrafo pasa por el modelo: las marcas de tiempo y los
# hablantes se quedan en Python, así que el modelo no puede perderlos ni cambiarlos.
import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from src.diarizer import aplicar_nombres
from utils.formatters import cargar_transcripcion, guardar_json, guardar_txt_con_timestamps

logger = logging.getLogger(__name__)

# Nombres cortos de --modelo -> modelos de mlx-community en Hugging Face (4 bits)
MODELOS_CORRECTOR = {
    "qwen3-4b": "mlx-community/Qwen3-4B-4bit",          # ~2,3 GB, el más rápido
    "qwen3-8b": "mlx-community/Qwen3-8B-4bit",          # ~4,6 GB, buen equilibrio
    "gemma4-e4b": "mlx-community/gemma-4-e4b-it-4bit",  # ~3 GB, alternativa rápida
}

# Por debajo de este número de letras cambiadas, un párrafo nunca se rechaza
# (en un párrafo corto, arreglar una sola palabra ya es un porcentaje alto)
MIN_LETRAS_PERMITIDAS = 8

INSTRUCCIONES = (
    "Eres un corrector de transcripciones automáticas de audio en español.\n"
    "Corrige solo:\n"
    "- ortografía y tildes;\n"
    "- puntuación y mayúsculas;\n"
    "- palabras claramente mal transcritas porque suenan parecido (por ejemplo, \"haber\" por \"a ver\").\n"
    "No cambies el estilo ni el registro, no resumas, no añadas ni quites información, "
    "y conserva las muletillas y repeticiones: es lenguaje hablado.\n"
    "Responde únicamente con el texto corregido, sin comillas, títulos ni comentarios."
)

# Estados de cada párrafo tras la corrección
SIN_CAMBIOS = "sin cambios"
APLICADA = "aplicada"
RECHAZADA = "rechazada"    # la salvaguarda la descartó por cambiar demasiado
DESCARTADA = "descartada"  # la descartaste tú al revisar

# (texto del párrafo, contexto anterior) -> respuesta del modelo
Generador = Callable[[str, str], str]


@dataclass
class Correccion:
    """Lo que pasó con un párrafo: el texto original, lo que propuso el modelo y si se aplicó."""
    original: str
    propuesta: str
    cambio: float  # fracción del texto que cambió (0 a 1), sin contar tildes, mayúsculas, puntuación ni espacios
    estado: str

    @property
    def texto_final(self) -> str:
        return self.propuesta if self.estado == APLICADA else self.original


def resolver_modelo(nombre: str) -> str:
    """Convierte un nombre corto (qwen3-8b) en su repo de Hugging Face; un repo se usa tal cual."""
    if nombre in MODELOS_CORRECTOR:
        return MODELOS_CORRECTOR[nombre]
    if "/" in nombre:
        return nombre
    disponibles = ", ".join(MODELOS_CORRECTOR)
    raise ValueError(f"Modelo desconocido: '{nombre}'. Usa uno de {disponibles}, o un repo de Hugging Face (mlx-community/...).")


def modelo_descargado(repo: str) -> bool:
    """True si el modelo ya está en la caché de Hugging Face (para avisar de la descarga la primera vez)."""
    try:
        from huggingface_hub import try_to_load_from_cache
        return isinstance(try_to_load_from_cache(repo, "config.json"), str)
    except Exception:
        return False


def armar_mensajes(texto: str, contexto: str) -> list:
    """Todo va en un único mensaje de usuario: algunas plantillas (Gemma) no admiten mensaje de sistema."""
    partes = [INSTRUCCIONES]
    if contexto:
        partes.append(f"Contexto anterior (solo para entender, no lo corrijas ni lo repitas):\n{contexto}")
    partes.append(f"Texto a corregir:\n{texto}")
    return [{"role": "user", "content": "\n\n".join(partes)}]


def cargar_generador(repo: str, silencioso: bool = True) -> Generador:
    """
    Carga (y la primera vez descarga) el modelo con mlx-lm.
    Retorna una función que corrige un párrafo y devuelve la respuesta cruda del modelo.
    """
    try:
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler
    except ImportError:
        raise RuntimeError('Falta mlx-lm para corregir. Instálalo con: uv pip install -e ".[correccion]"') from None

    if silencioso:
        # Las barras de descarga de Hugging Face se pisan con las nuestras
        from huggingface_hub.utils import disable_progress_bars
        disable_progress_bars()

    logger.info(f"Cargando el modelo de corrección {repo}. La primera vez se descarga de Hugging Face.")
    modelo, tokenizer = load(repo)
    # Temperatura 0: siempre la respuesta más probable, sin creatividad
    sampler = make_sampler(temp=0.0)

    def generar(texto: str, contexto: str) -> str:
        # enable_thinking=False: los modelos que "piensan" (Qwen 3) tardarían varias veces más
        prompt = tokenizer.apply_chat_template(
            armar_mensajes(texto, contexto), add_generation_prompt=True, enable_thinking=False)
        # La corrección mide casi lo mismo que el original; el margen evita cortarla
        max_tokens = 2 * len(tokenizer.encode(texto)) + 64
        return generate(modelo, tokenizer, prompt, max_tokens=max_tokens, sampler=sampler)

    return generar


def limpiar_respuesta(respuesta: str, original: str) -> str:
    """Quita lo que el modelo añade alrededor del texto: razonamiento, títulos, comillas, saltos de línea."""
    texto = re.sub(r"<think>.*?</think>", "", respuesta, flags=re.DOTALL)
    texto = texto.split("</think>")[-1].strip()
    texto = re.sub(r"^(texto corregido|corrección|corregido)\s*:\s*", "", texto, flags=re.IGNORECASE)
    for apertura, cierre in (('"', '"'), ("«", "»"), ("“", "”")):
        if (texto.startswith(apertura) and texto.endswith(cierre) and len(texto) > 1
                and not original.startswith(apertura)):
            texto = texto[1:-1].strip()
    # Un párrafo es una sola línea en el .txt
    return " ".join(texto.split())


def _letras(texto: str) -> str:
    """
    Solo letras y números, sin tildes, mayúsculas, puntuación ni espacios: corregir eso no
    cuenta como cambio, y así "por que" -> "porque" tampoco.
    """
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return "".join(re.findall(r"\w", sin_tildes.lower()))


def contar_letras_cambiadas(original: str, propuesta: str) -> tuple:
    """Retorna (letras cambiadas, añadidas o quitadas; letras del original)."""
    a, b = _letras(original), _letras(propuesta)
    comparador = difflib.SequenceMatcher(None, a, b, autojunk=False)
    cambiadas = sum(max(i2 - i1, j2 - j1)
                    for operacion, i1, i2, j1, j2 in comparador.get_opcodes() if operacion != "equal")
    return cambiadas, len(a)


def evaluar(original: str, propuesta: str, max_cambio: float) -> Correccion:
    """
    Salvaguarda: si el modelo cambia más de max_cambio (fracción) del texto del párrafo,
    se queda el original. Tildes, mayúsculas, puntuación y espacios no cuentan como cambio.
    """
    if not propuesta:
        return Correccion(original, propuesta, 1.0, RECHAZADA)
    if propuesta == original:
        return Correccion(original, propuesta, 0.0, SIN_CAMBIOS)
    cambiadas, total = contar_letras_cambiadas(original, propuesta)
    estado = RECHAZADA if cambiadas > max(MIN_LETRAS_PERMITIDAS, max_cambio * total) else APLICADA
    return Correccion(original, propuesta, cambiadas / max(total, 1), estado)


def corregir_parrafos(parrafos: list, generar: Generador, max_cambio: float = 0.15) -> Iterator[Correccion]:
    """
    Corrige los párrafos uno a uno y entrega cada resultado en cuanto está listo
    (así la CLI muestra el avance y, si se interrumpe, se guarda lo hecho).
    Cada párrafo lleva como contexto el anterior ya corregido.
    """
    contexto = ""
    for parrafo in parrafos:
        original = parrafo["text"].strip()
        if not original:
            yield Correccion(original, original, 0, SIN_CAMBIOS)
            continue
        correccion = evaluar(original, limpiar_respuesta(generar(original, contexto), original), max_cambio)
        if correccion.estado == RECHAZADA:
            logger.info(f"Corrección rechazada (cambiaba un {correccion.cambio:.0%}): {original[:60]}...")
        contexto = correccion.texto_final
        yield correccion


def completar(parrafos: list, correcciones: list) -> list:
    """Si la corrección se interrumpió, los párrafos que faltan quedan como estaban."""
    resto = [Correccion(p["text"].strip(), p["text"].strip(), 0.0, SIN_CAMBIOS) for p in parrafos[len(correcciones):]]
    return correcciones + resto


# --- Archivos ---

_MARCA_DE_TIEMPO = re.compile(r"^\[(\d+):(\d{2}):(\d{2})\]\s*(.*)$", re.DOTALL)
# "Ana: ...", "Hablante 2: ...", "Luis García: ..." (hasta 3 palabras, empieza en mayúscula)
_ETIQUETA = re.compile(r"^([A-ZÁÉÍÓÚÑ][^\s:,.;¿?¡!]*(?: [^\s:,.;¿?¡!]+){0,2}):\s+(.*)$", re.DOTALL)


def leer_entrada(ruta: Path) -> dict:
    """
    Lee la transcripción a corregir: {"origen": Path, "audio", "nombres": dict, "parrafos": list}.
    Prefiere el .blocks.json (hablantes y tiempos exactos); si le pasan el .txt y existe
    el .json al lado, usa el .json. Si solo hay .txt, lo interpreta.
    """
    ruta = Path(ruta).expanduser()
    if ruta.suffix == ".txt" and ruta.with_suffix(".json").exists():
        ruta = ruta.with_suffix(".json")
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {ruta}")
    if ruta.suffix == ".json":
        datos = cargar_transcripcion(ruta)
    elif ruta.suffix == ".txt":
        datos = {"audio": None, "nombres": {}, "parrafos": leer_txt(ruta)}
    else:
        raise ValueError(f"Necesito el .blocks.json o el .blocks.txt de una transcripción, no {ruta.name}.")
    if not datos["parrafos"]:
        raise ValueError(f"La transcripción está vacía: {ruta}")
    return {"origen": ruta, **datos}


def leer_txt(ruta: Path) -> list:
    """
    Convierte un .blocks.txt ("[hh:mm:ss] Hablante: texto", párrafos separados por una línea
    en blanco) en párrafos. Las etiquetas cuentan como hablantes solo si las lleva la mayoría
    de los párrafos (una transcripción con hablantes las lleva todos), para no confundir
    con un hablante un "Mira: ..." suelto en una transcripción sin ellos.
    """
    bloques = [b.strip() for b in re.split(r"\n\s*\n", Path(ruta).read_text(encoding="utf-8")) if b.strip()]
    leidos = []
    for bloque in bloques:
        coincide = _MARCA_DE_TIEMPO.match(bloque)
        if not coincide:
            raise ValueError(f"{Path(ruta).name} no parece una transcripción de Transcriptor "
                             f"(cada párrafo empieza con [hh:mm:ss]). No entiendo: {bloque[:60]}")
        h, m, s, texto = coincide.groups()
        texto = " ".join(texto.split())
        etiqueta = _ETIQUETA.match(texto)
        leidos.append((int(h) * 3600 + int(m) * 60 + int(s), texto, etiqueta.groups() if etiqueta else None))

    con_hablantes = 2 * sum(1 for _, _, etiqueta in leidos if etiqueta) > len(leidos)

    parrafos = []
    for i, (inicio, texto, etiqueta) in enumerate(leidos):
        fin = leidos[i + 1][0] if i + 1 < len(leidos) else inicio
        if etiqueta and con_hablantes:
            parrafos.append({"start": inicio, "end": fin, "text": etiqueta[1], "speaker": etiqueta[0]})
        else:
            parrafos.append({"start": inicio, "end": fin, "text": texto})
    return parrafos


def rutas_de_salida(origen: Path) -> tuple:
    """'Episodio.blocks.json' -> ('Episodio.corregido.blocks.txt', 'Episodio.corregido.blocks.json')."""
    nombre = origen.name
    for sufijo in (".blocks.json", ".blocks.txt", ".json", ".txt"):
        if nombre.endswith(sufijo):
            nombre = nombre[:-len(sufijo)]
            break
    return (origen.with_name(f"{nombre}.corregido.blocks.txt"),
            origen.with_name(f"{nombre}.corregido.blocks.json"))


def guardar_correccion(datos: dict, correcciones: list) -> tuple:
    """
    Guarda la versión corregida junto a la original, sin tocar la original.
    En el .json, cada párrafo corregido guarda su "texto_original", y los no aplicados
    (por la salvaguarda o porque los descartaste) guardan la "correccion_no_aplicada".
    Retorna (ruta del .txt, ruta del .json).
    """
    txt_path, json_path = rutas_de_salida(datos["origen"])
    parrafos = []
    for parrafo, correccion in zip(datos["parrafos"], correcciones):
        nuevo = {**parrafo, "text": correccion.texto_final}
        if correccion.estado == APLICADA:
            # Si antes se quitaron repeticiones, el original es el de antes de quitarlas
            nuevo["texto_original"] = parrafo.get("texto_original", parrafo["text"])
        elif correccion.estado in (RECHAZADA, DESCARTADA):
            nuevo["correccion_no_aplicada"] = correccion.propuesta
        parrafos.append(nuevo)

    # El .json conserva las etiquetas genéricas (así funciona `transcriptor nombres` sobre él)
    guardar_json(parrafos, json_path, audio=datos["audio"], nombres=datos["nombres"])
    guardar_txt_con_timestamps(aplicar_nombres(parrafos, datos["nombres"]), txt_path)
    return txt_path, json_path
