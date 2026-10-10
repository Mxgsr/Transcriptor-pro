# Ubicación: src/repeticiones.py
# Quita las frases que Whisper repite en bucle ("Un error. Un error. Un error. ...").
# Es una limpieza sin IA: solo junta repeticiones seguidas de las mismas palabras y deja una.
import re
import unicodedata

# Cuántas veces seguidas debe aparecer algo para considerarlo un bucle.
# Una palabra suelta repetida 2 o 3 veces suele ser habla real ("sí, sí, sí"); 4 o más ya no.
MIN_REPETICIONES_PALABRA = 4
MIN_REPETICIONES_FRASE = 3
# Los bucles de Whisper son frases cortas; no se buscan frases más largas que esto
MAX_PALABRAS_FRASE = 12


def _clave(palabra: str) -> str:
    """La palabra sin tildes, mayúsculas ni puntuación: "¿Qué" y "que," cuentan como la misma."""
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", palabra) if unicodedata.category(c) != "Mn")
    return "".join(re.findall(r"\w", sin_tildes.lower())) or palabra


def _minimo(largo_frase: int) -> int:
    return MIN_REPETICIONES_PALABRA if largo_frase == 1 else MIN_REPETICIONES_FRASE


def _veces_seguidas(claves: list, inicio: int, largo: int) -> int:
    """Cuántas veces seguidas aparece la frase claves[inicio:inicio+largo] a partir de inicio."""
    frase = claves[inicio:inicio + largo]
    veces = 1
    while claves[inicio + veces * largo:inicio + (veces + 1) * largo] == frase:
        veces += 1
    return veces


def quitar_repeticiones(texto: str) -> str:
    """
    Deja una sola vez cada frase repetida en bucle:
    "Gracias. Gracias. Gracias. Gracias. Pero..." -> "Gracias. Pero...".
    Entre varias lecturas posibles se queda con la que más texto repetido quita.
    """
    palabras = texto.split()
    claves = [_clave(p) for p in palabras]
    resultado = []
    i = 0
    while i < len(palabras):
        mejor_largo, mejor_veces = 1, 1
        for largo in range(1, min(MAX_PALABRAS_FRASE, (len(palabras) - i) // 2) + 1):
            veces = _veces_seguidas(claves, i, largo)
            if veces >= _minimo(largo) and largo * veces > mejor_largo * mejor_veces:
                mejor_largo, mejor_veces = largo, veces
        resultado.extend(palabras[i:i + mejor_largo])
        i += mejor_largo * mejor_veces
    return " ".join(resultado)


def limpiar_segmentos(segmentos: list) -> list:
    """
    Limpia los segmentos de Whisper antes de agruparlos: quita los bucles dentro de cada uno y,
    cuando el mismo texto sale en varios segmentos seguidos (un bucle repartido en trozos),
    deja solo el primero. Retorna copias; los originales no cambian.
    """
    limpios = []
    racha = []  # segmentos seguidos con el mismo texto

    def cerrar_racha():
        largo_frase = len(racha[0]["text"].split())
        limpios.extend(racha[:1] if len(racha) >= _minimo(largo_frase) else racha)

    for seg in segmentos:
        texto = quitar_repeticiones(seg["text"].strip())
        nuevo = {**seg, "text": texto}
        if texto != seg["text"].strip():
            # Las palabras sueltas ya no coinciden con el texto: se descartan
            nuevo.pop("words", None)
        if racha and _clave_texto(texto) != _clave_texto(racha[0]["text"]):
            cerrar_racha()
            racha = []
        racha.append(nuevo)
    if racha:
        cerrar_racha()
    return limpios


def _clave_texto(texto: str) -> str:
    return " ".join(_clave(p) for p in texto.split())


def limpiar_parrafos(parrafos: list, guardar_original: bool = False) -> list:
    """
    Quita los bucles del texto de cada párrafo. Retorna copias.
    Con guardar_original=True, cada párrafo que cambió guarda su texto anterior en "texto_original".
    """
    limpios = []
    for parrafo in parrafos:
        texto = quitar_repeticiones(parrafo["text"].strip())
        nuevo = {**parrafo, "text": texto}
        if guardar_original and texto != parrafo["text"].strip():
            nuevo.setdefault("texto_original", parrafo["text"])
        limpios.append(nuevo)
    return limpios
