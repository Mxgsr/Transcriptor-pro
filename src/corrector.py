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

from src import plataforma
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
    "Si no estás seguro de qué palabra se dijo, déjala como está.\n"
    "\"Qué\" y \"cómo\" en una exclamación (\"qué bonito\", \"qué bueno que viniste\") llevan tilde, "
    "pero no son preguntas: no les pongas signos de interrogación.\n"
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


def preparar_vocabulario(texto: str) -> str:
    """
    "COSAM, OSL ,, señorita Catalina" -> "COSAM, OSL, señorita Catalina".
    Acepta palabras separadas por comas, punto y coma o saltos de línea, y quita las repetidas.
    """
    palabras = []
    for palabra in re.split(r"[,;\n]", texto or ""):
        palabra = palabra.strip().rstrip(".")
        if palabra and palabra.lower() not in (p.lower() for p in palabras):
            palabras.append(palabra)
    return ", ".join(palabras)


def armar_mensajes(texto: str, contexto: str, vocabulario: str = "") -> list:
    """Todo va en un único mensaje de usuario: algunas plantillas (Gemma) no admiten mensaje de sistema."""
    partes = [INSTRUCCIONES]
    if vocabulario:
        partes.append("Nombres y siglas que aparecen en esta conversación. Si una palabra mal transcrita "
                      f"corresponde a uno de ellos, escríbelo exactamente así: {vocabulario}.")
    if contexto:
        partes.append(f"Contexto anterior (solo para entender, no lo corrijas ni lo repitas):\n{contexto}")
    partes.append(f"Texto a corregir:\n{texto}")
    return [{"role": "user", "content": "\n\n".join(partes)}]


def cargar_generador(repo: str, silencioso: bool = True, vocabulario: str = "") -> Generador:
    """
    Carga (y la primera vez descarga) el modelo con mlx-lm.
    Retorna una función que corrige un párrafo y devuelve la respuesta cruda del modelo.
    vocabulario son los nombres y siglas del audio, que se le dan al modelo para que los escriba bien.
    """
    try:
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler
    except ImportError:
        if not plataforma.correccion_disponible():
            raise RuntimeError(plataforma.SIN_CORRECCION) from None
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
            armar_mensajes(texto, contexto, vocabulario), add_generation_prompt=True, enable_thinking=False)
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


# "¿Qué bonito?" casi siempre es "¡Qué bonito!": tras "qué", estas palabras son exclamación
_EXCLAMATIVAS = {
    "bonito", "bonita", "lindo", "linda", "bueno", "buena", "rico", "rica", "bien", "mal", "malo", "mala",
    "horrible", "terrible", "lata", "pena", "rabia", "miedo", "vergüenza", "maravilla", "increíble", "genial",
    "raro", "rara", "loco", "loca", "triste", "fome", "bacán", "entretenido", "entretenida", "difícil", "fácil",
    "lindura", "suerte", "alegría", "emoción", "susto", "asco", "horror", "bacano", "chévere", "chistoso",
    "chistosa", "gracioso", "graciosa", "fuerte", "heavy", "tremendo", "tremenda", "interesante", "importante",
}
_PREGUNTA_CON_QUE = re.compile(r"¿\s*([Qq]u[ée])\s+(\w+)([^¿?.!]*)[?.!]")


def _exclamar_en_vez_de_preguntar(propuesta: str, original: str) -> str:
    """
    "¿Qué bonito?" -> "¡Qué bonito!" cuando el modelo convirtió en pregunta una exclamación
    (también "¿Qué bueno.", a medio camino). Si el original ya la escribía como pregunta, se respeta.
    """
    def cambiar(m):
        palabra = m.group(2).lower()
        if palabra not in _EXCLAMATIVAS or re.search(rf"¿\s*qu[ée]\s+{re.escape(palabra)}\b", original, re.IGNORECASE):
            return m.group(0)
        # "¿Qué bonito, no?" sí pregunta (busca que le den la razón)
        if re.search(r"\b(no|cierto|verdad)\s*$", m.group(3), re.IGNORECASE):
            return m.group(0)
        return f"¡{m.group(1)} {m.group(2)}{m.group(3)}!"
    return _PREGUNTA_CON_QUE.sub(cambiar, propuesta)


def _como_suena(texto: str) -> str:
    """
    Una clave de cómo suena en español: "haber" y "a ver" dan lo mismo, y también "vaya" y "valla",
    "hacer" y "aser", "llorar" y "yorar". Sirve para saber si el modelo arregló una palabra mal oída
    (suena igual o casi) o la cambió por otra ("lloro" -> "llamo").
    """
    t = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    t = "".join(re.findall(r"[a-z]", t))
    for antes, despues in (("ch", "C"), ("ll", "y"), ("qu", "k"), ("gue", "ge"), ("gui", "gi"), ("ge", "je"),
                           ("gi", "ji"), ("ce", "se"), ("ci", "si"), ("c", "k"), ("z", "s"), ("v", "b"),
                           ("w", "b"), ("h", ""), ("rr", "r")):
        t = t.replace(antes, despues)
    return re.sub(r"y$", "i", t)


def _suenan_parecido(a: str, b: str) -> bool:
    """Iguales, o del mismo largo con un solo sonido distinto ("Cozán" y "COSAM")."""
    a, b = _como_suena(a), _como_suena(b)
    return a == b or (len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 1)


def _con_signos_de(palabras: list, modelo: list) -> list:
    """Las palabras originales con la mayúscula inicial y los signos de alrededor que les puso el modelo."""
    palabras = list(palabras)
    inicio = re.match(r"^\W*", modelo[0]).group(0)
    fin = re.search(r"\W*$", modelo[-1]).group(0)
    palabras[0] = inicio + re.sub(r"^\W*", "", palabras[0])
    palabras[-1] = re.sub(r"\W*$", "", palabras[-1]) + fin
    letra = re.search(r"\w", modelo[0])
    if letra and letra.group(0).isupper():
        palabras[0] = re.sub(r"\w", lambda m: m.group(0).upper(), palabras[0], count=1)
    return palabras


def _deshacer_cambios_dudosos(propuesta: str, original: str, vocabulario: str = "",
                              en_minuscula: frozenset = frozenset()) -> str:
    """
    Deshace lo que el modelo no debía tocar, palabra a palabra:
    - las palabras que cambió por otras que no suenan igual ("lloro" -> "Llamo", "verla" -> "Vérala"):
      Whisper se equivoca entre palabras que suenan parecido, así que un cambio que suena distinto
      casi siempre empeora el texto. Se respetan los que solo ponen palabras del vocabulario,
      y nunca se quita una del vocabulario;
    - las palabras que borró ("Qué bonito escucharla" -> "¿Bonito escucharla?");
    - las mayúsculas que quitó al inicio de una frase ("Yo fui" -> "yo fui", "¿Y cómo" -> "¿y cómo"),
      o a una palabra que en toda la transcripción nunca va en minúscula (un nombre: "Pasán" -> "pasán").
      en_minuscula: las palabras (según _letras) que la transcripción escribe alguna vez en minúscula.
    Se conservan la puntuación y las mayúsculas que puso el modelo.
    """
    del_vocabulario = {_letras(p) for p in vocabulario.replace(",", " ").split()}
    antes, despues = original.split(), propuesta.split()
    comparador = difflib.SequenceMatcher(None, [_letras(p) for p in antes], [_letras(p) for p in despues],
                                         autojunk=False)
    resultado = []
    for operacion, i1, i2, j1, j2 in comparador.get_opcodes():
        nuevas = despues[j1:j2]
        puestas = {_letras(p) for p in nuevas} - {_letras(p) for p in antes[i1:i2]}
        quitadas = {_letras(p) for p in antes[i1:i2]} - {_letras(p) for p in nuevas}
        if operacion == "replace" and (quitadas & del_vocabulario or (
                not _suenan_parecido("".join(antes[i1:i2]), "".join(nuevas))
                and not (puestas and puestas <= del_vocabulario))):
            nuevas = _con_signos_de(antes[i1:i2], nuevas)
        elif operacion == "delete":
            nuevas = _devolver_borradas(antes, i1, i2, despues, j1)
        elif operacion == "equal":
            nuevas = [_con_mayuscula_de(a, n, resultado + nuevas[:k], en_minuscula) for k, (a, n) in
                      enumerate(zip(antes[i1:i2], nuevas))]
        resultado.extend(nuevas)
    return " ".join(resultado)


def _devolver_borradas(antes: list, i1: int, i2: int, despues: list, j1: int) -> list:
    """
    Las palabras originales que el modelo borró. Los signos con que el modelo abrió la frase
    ("¿", "¡") y la mayúscula pasan de la palabra siguiente a la devuelta:
    "Qué bonito" -> "¿Bonito" queda "¿Qué bonito". Cambia despues[j1] en el lugar.
    """
    devueltas = list(antes[i1:i2])
    if j1 >= len(despues) or i2 >= len(antes):
        return devueltas
    siguiente = despues[j1]
    abre = re.match(r"^[¿¡\"«“(]*", siguiente).group(0)
    if abre and not devueltas[0].startswith(abre):
        devueltas[0] = abre + devueltas[0]
        siguiente = siguiente[len(abre):]
    letra, original = re.search(r"\w", siguiente), re.search(r"\w", antes[i2])
    if letra and original and letra.group(0).isupper() and original.group(0).islower():
        siguiente = siguiente[:letra.start()] + letra.group(0).lower() + siguiente[letra.end():]
        devueltas[0] = re.sub(r"\w", lambda m: m.group(0).upper(), devueltas[0], count=1)
    despues[j1] = siguiente
    return devueltas


def _con_mayuscula_de(original: str, nueva: str, previas: list, en_minuscula: frozenset = frozenset()) -> str:
    """
    Si el original la tenía con mayúscula, la mayúscula se queda cuando la palabra empieza una frase
    o cuando es un nombre (la transcripción nunca la escribe en minúscula).
    """
    letra, antes = re.search(r"\w", nueva), re.search(r"\w", original)
    if not (letra and antes and antes.group(0).isupper() and letra.group(0).islower()):
        return nueva
    empieza_frase = not previas or _cierra_frase(previas[-1]) or nueva[:1] in "¿¡"
    if not empieza_frase and (not en_minuscula or _letras(original) in en_minuscula):
        return nueva
    return nueva[:letra.start()] + letra.group(0).upper() + nueva[letra.end():]


def _seguir_la_frase(propuesta: str, original: str, contexto: str) -> str:
    """
    Si el párrafo anterior quedó sin terminar la frase y el original seguía en minúscula,
    el modelo no debe empezar con mayúscula: "...y fuimos al" + "centro" no es "Centro".
    """
    if not contexto or contexto.rstrip().endswith((".", "?", "!", "…", ":")):
        return propuesta
    if not (original[:1].islower() and propuesta[:1].isupper() and propuesta[:1].lower() == original[:1]):
        return propuesta
    return propuesta[0].lower() + propuesta[1:]


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


def corregir_parrafos(parrafos: list, generar: Generador, max_cambio: float = 0.15,
                      vocabulario: str = "") -> Iterator[Correccion]:
    """
    Corrige los párrafos uno a uno y entrega cada resultado en cuanto está listo
    (así la CLI muestra el avance y, si se interrumpe, se guarda lo hecho).
    Cada párrafo lleva como contexto el anterior ya corregido.
    vocabulario: los cambios que solo ponen esas palabras se respetan aunque no suenen igual.
    """
    contexto, hablante_anterior = "", None
    en_minuscula = _palabras_en_minuscula(parrafos)
    sueltos = [t for t in preparar_vocabulario(vocabulario).split(", ") if t and " " not in t]
    _, veces_en_minuscula = _contar_palabras(parrafos)
    for parrafo in parrafos:
        original = parrafo["text"].strip()
        if not original:
            yield Correccion(original, original, 0, SIN_CAMBIOS)
            continue
        propuesta = limpiar_respuesta(generar(original, contexto), original)
        if evaluar(original, propuesta, max_cambio).estado != RECHAZADA:
            # Si cambiaba demasiado se rechaza entero (y se avisa); si no, se revisa palabra a palabra
            propuesta = _deshacer_cambios_dudosos(propuesta, original, vocabulario, en_minuscula)
        if sueltos:
            # La IA a veces deja un nombre a medio arreglar ("fosi" -> "FOSI")
            palabras = propuesta.split()
            if _cambiar_nombres(palabras, sueltos, veces_en_minuscula):
                propuesta = " ".join(palabras)
        propuesta = _exclamar_en_vez_de_preguntar(propuesta, original)
        if parrafo.get("speaker") == hablante_anterior:
            # Con otro hablante empieza una frase nueva aunque la anterior quedara sin punto
            propuesta = _seguir_la_frase(propuesta, original, contexto)
        hablante_anterior = parrafo.get("speaker")
        correccion = evaluar(original, propuesta, max_cambio)
        if correccion.estado == RECHAZADA:
            logger.info(f"Corrección rechazada (cambiaba un {correccion.cambio:.0%}): {original[:60]}...")
        contexto = correccion.texto_final
        yield correccion


def _cierra_frase(palabra: str) -> bool:
    """Termina en punto, ? o !. Los puntos suspensivos no: muchas veces la frase sigue."""
    return bool(re.search(r"(?<!\.)[.?!]$", palabra))


def _palabras_en_minuscula(parrafos: list) -> frozenset:
    """Las palabras (según _letras) que la transcripción escribe alguna vez empezando en minúscula."""
    return frozenset(_letras(p) for parrafo in parrafos for p in parrafo["text"].split()
                     if (letra := re.search(r"\w", p)) and letra.group(0).islower())


# ---- Vocabulario sin IA ---------------------------------------------------------------------
# La IA casi nunca cambia un nombre mal oído por el del vocabulario ("Cozán" no lo ve como "COSAM"),
# así que antes de la IA se cambian aquí los que suenan casi igual. Para no tocar palabras
# normales ("cosas"), solo cuentan las que Whisper escribió como nombre (con mayúscula a media
# frase, o en mayúsculas) y que casi nunca aparecen en minúscula.

_PALABRA = re.compile(r"^(\W*)(.*?)(\W*)$", re.DOTALL)
# "nací en Santa Catalina" es un lugar, no "señorita Catalina"
_NO_CAMBIAR = {"san", "santa", "santo"}


def _distancia(a: str, b: str) -> int:
    """Cuántas letras hay que cambiar, poner o quitar para pasar de a a b."""
    anterior = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        actual = [i]
        for j, y in enumerate(b, 1):
            actual.append(min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (x != y)))
        anterior = actual
    return anterior[-1]


def _suena_como(palabra: str, termino: str) -> bool:
    """Igual sonido, o casi: un sonido distinto en nombres cortos, dos en los largos."""
    a, b = _como_suena(palabra), _como_suena(termino)
    if not a or not b:
        return False
    return a == b or _distancia(a, b) <= (1 if len(b) <= 6 else 2)


def _parece_nombre(token: str, previo: str) -> bool:
    """Whisper la escribió como nombre: con mayúscula a media frase, o toda en mayúsculas ("ASL")."""
    letras = re.sub(r"\W", "", token)
    if len(letras) > 1 and letras.isupper():
        return True
    return bool(letras) and letras[0].isupper() and bool(previo) and not previo.endswith((".", "?", "!", "…", ":"))


def _cambiar_nombres(palabras: list, terminos: list, veces_en_minuscula: dict) -> int:
    """Cambia en el lugar las palabras sueltas que son un término del vocabulario mal oído."""
    cambios = 0
    for i, token in enumerate(palabras):
        abre, nucleo, cierra = _PALABRA.match(token).groups()
        clave = _letras(nucleo)
        if not clave or any(clave == _letras(t) for t in terminos):
            continue
        parecidos = [t for t in terminos if _como_suena(nucleo) == _como_suena(t)]
        if not parecidos and (_parece_nombre(token, palabras[i - 1] if i else "")
                              and veces_en_minuscula.get(clave, 0) < 3):
            parecidos = [t for t in terminos if _suena_como(nucleo, t)]
        if len(parecidos) == 1:
            palabras[i] = abre + parecidos[0] + cierra
            cambios += 1
    return cambios


def _cambiar_frases(palabras: list, termino: list, veces: dict) -> int:
    """
    "la suyenta Catalina" -> "la señorita Catalina": en un término de varias palabras, si todas
    menos una están tal cual, la otra se cambia si es rara (sale 2 veces o menos en toda la
    transcripción) y empieza con el mismo sonido.
    """
    cambios, claves, n = 0, [_letras(t) for t in termino], len(termino)
    for i in range(len(palabras) - n + 1):
        trozo = palabras[i:i + n]
        distintas = [k for k in range(n) if _letras(trozo[k]) != claves[k]]
        if len(distintas) != 1:
            continue
        k = distintas[0]
        abre, nucleo, cierra = _PALABRA.match(trozo[k]).groups()
        clave, sonido, sonido_termino = _letras(nucleo), _como_suena(nucleo), _como_suena(termino[k])
        if (not clave or clave in _NO_CAMBIAR or veces.get(clave, 0) > 2 or not sonido
                or sonido[0] != sonido_termino[0]):
            continue
        nueva = termino[k]
        if k == 0 and not nueva.isupper():
            # "Señorita Catalina" en el vocabulario, pero "y la señorita Catalina" a media frase
            inicio = i == 0 or _cierra_frase(palabras[i - 1])
            nueva = (nueva[0].upper() if inicio else nueva[0].lower()) + nueva[1:]
        # "Sra. Catalina": el punto de la abreviatura no va dentro de la frase
        palabras[i + k] = abre + nueva + ("" if k < n - 1 else cierra)
        cambios += 1
    return cambios


def _contar_palabras(parrafos: list) -> tuple:
    """Cuántas veces sale cada palabra (según _letras) en la transcripción: (en total, en minúscula)."""
    veces, veces_en_minuscula = {}, {}
    for parrafo in parrafos:
        for token in parrafo["text"].split():
            clave = _letras(token)
            veces[clave] = veces.get(clave, 0) + 1
            if (letra := re.search(r"\w", token)) and letra.group(0).islower():
                veces_en_minuscula[clave] = veces_en_minuscula.get(clave, 0) + 1
    return veces, veces_en_minuscula


def aplicar_vocabulario(parrafos: list, vocabulario: str, guardar_original: bool = False) -> tuple:
    """
    Escribe bien los nombres del vocabulario que Whisper oyó mal ("Cozán" -> "COSAM",
    "la suyenta Catalina" -> "la señorita Catalina"), sin IA. Retorna (copias de los párrafos,
    cuántas palabras cambió). Con guardar_original=True, cada párrafo que cambió guarda su
    texto anterior en "texto_original".
    """
    terminos = [t.split() for t in preparar_vocabulario(vocabulario).split(", ") if t]
    if not terminos:
        return [dict(p) for p in parrafos], 0
    veces, veces_en_minuscula = _contar_palabras(parrafos)
    sueltos = [t[0] for t in terminos if len(t) == 1]
    nuevos, total = [], 0
    for parrafo in parrafos:
        palabras = parrafo["text"].split()
        cambios = _cambiar_nombres(palabras, sueltos, veces_en_minuscula) if sueltos else 0
        for termino in terminos:
            if len(termino) > 1:
                cambios += _cambiar_frases(palabras, termino, veces)
        nuevo = dict(parrafo)
        if cambios:
            nuevo["text"] = " ".join(palabras)
            if guardar_original:
                nuevo.setdefault("texto_original", parrafo["text"])
        nuevos.append(nuevo)
        total += cambios
    return nuevos, total


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
