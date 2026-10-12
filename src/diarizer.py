# Ubicación: src/diarizer.py
# Identifica quién habla y cuándo (diarización) usando pyannote.audio,
# y cruza ese resultado con los segmentos de Whisper.
import logging
import os
from pathlib import Path

from src import plataforma

logger = logging.getLogger(__name__)

ETIQUETA_GENERICA = "Hablante"

# pyannote viene con lotes de 1 por defecto; con lotes más grandes la GPU trabaja mucho mejor
TAMANO_LOTE = 32


def elegir_dispositivo(preferido: str = "auto"):
    """
    Decide dónde corre pyannote: "auto" usa la GPU del Mac (MPS) si está disponible,
    o una GPU NVIDIA (cuda); si no, la CPU. También acepta "mps", "cuda" o "cpu".
    """
    import torch

    preferido = (preferido or "auto").lower()
    if preferido != "auto":
        return torch.device(preferido)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _preparar_para_rendimiento(pipeline, dispositivo: str):
    """Mueve el pipeline a la GPU (si hay) y agranda los lotes. Si la GPU falla, sigue en CPU."""
    import torch

    for atributo in ("embedding_batch_size", "segmentation_batch_size"):
        valor = getattr(pipeline, atributo, None)
        if isinstance(valor, int) and valor < TAMANO_LOTE:
            setattr(pipeline, atributo, TAMANO_LOTE)

    destino = elegir_dispositivo(dispositivo)
    if destino.type == "cpu":
        logger.info("La diarización correrá en la CPU.")
        return
    try:
        pipeline.to(destino)
        logger.info(f"La diarización correrá en: {destino}")
    except Exception as e:
        logger.warning(f"No se pudo usar {destino} para la diarización ({e}). Se usará la CPU.")
        pipeline.to(torch.device("cpu"))


def cargar_pipeline(hf_token: str, modelo: str, dispositivo: str = "auto"):
    """
    Carga el pipeline de diarización desde Hugging Face y lo prepara para la GPU si la hay.
    Se hace antes de transcribir para fallar rápido si falta el token
    o no se aceptaron las condiciones del modelo.
    """
    # 1. Filtro de entrada: sin token no hay descarga del modelo
    if not hf_token:
        raise ValueError(
            "Falta HF_TOKEN en el archivo .env (el del proyecto o ~/.transcriptor/.env). "
            "La diarización necesita un token de Hugging Face (ver README, sección Diarización)."
        )

    # Si alguna operación no existe en la GPU del Mac (MPS), torch la hace en CPU en vez de fallar.
    # Debe definirse antes de importar torch (pyannote lo importa).
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    # Importación diferida: pyannote es pesado y solo se necesita con --diarizar
    try:
        from pyannote.audio import Pipeline
    except ImportError as e:
        if not plataforma.hablantes_disponible():
            raise ImportError(plataforma.SIN_HABLANTES) from e
        raise ImportError(
            "pyannote.audio no está instalado. Ejecuta: pip install -r requirements-diarizacion.txt"
        ) from e

    logger.info(f"Cargando modelo de diarización: {modelo}")
    try:
        pipeline = Pipeline.from_pretrained(modelo, token=hf_token)
    except Exception as e:
        logger.error(f"No se pudo cargar el modelo de diarización '{modelo}'. Detalles: {e}")
        raise

    # pyannote devuelve None cuando el modelo es privado y no se aceptaron sus condiciones
    if pipeline is None:
        raise RuntimeError(
            f"No se pudo descargar '{modelo}'. Acepta sus condiciones de uso en "
            f"https://huggingface.co/{modelo} con la cuenta dueña del token."
        )

    _preparar_para_rendimiento(pipeline, dispositivo)
    return pipeline


# Peso aproximado de cada etapa de pyannote en el tiempo total, para una sola barra de progreso.
# Las demás etapas son casi instantáneas.
ETAPAS_DIARIZACION = {"segmentation": (0.0, 0.25), "embeddings": (0.25, 1.0)}


def _hook_de_progreso(progreso):
    """Traduce los avisos de pyannote (por etapa) a un único avance de 0 a 1."""
    def hook(etapa, artefacto=None, file=None, total=None, completed=None):
        if etapa not in ETAPAS_DIARIZACION or not total or completed is None:
            return
        inicio, fin = ETAPAS_DIARIZACION[etapa]
        progreso(inicio + (fin - inicio) * min(completed / total, 1.0), 1.0, None)
    return hook


def diarizar_audio(pipeline, audio_path: Path, num_hablantes: int = None,
                   min_hablantes: int = None, max_hablantes: int = None, progreso=None) -> list:
    """
    Ejecuta la diarización sobre el audio.
    Retorna una lista de turnos: [{"start": float, "end": float, "speaker": str}, ...]
    progreso(fraccion, 1.0, None) se llama a medida que avanza.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"No se encontró el audio en: {audio_path}")

    import torch
    from src.transcriber import SAMPLE_RATE, cargar_audio

    # Decodificamos igual que Whisper (16 kHz, mono) y le pasamos la onda ya cargada
    # a pyannote, así no dependemos de su propio decodificador.
    audio = cargar_audio(audio_path)
    entrada = {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": SAMPLE_RATE}

    def _ejecutar():
        return pipeline(
            entrada,
            num_speakers=num_hablantes,
            min_speakers=min_hablantes,
            max_speakers=max_hablantes,
            **({"hook": _hook_de_progreso(progreso)} if progreso is not None else {}),
        )

    logger.info(f"Comienza la diarización del archivo: {audio_path}")
    try:
        try:
            resultado = _ejecutar()
        except Exception as e:
            # Si falla en la GPU, lo intentamos una vez más en la CPU (más lento, pero seguro)
            dispositivo = getattr(pipeline, "device", None)
            if getattr(dispositivo, "type", "cpu") == "cpu":
                raise
            logger.warning(f"La diarización falló en {dispositivo} ({e}). Reintentando en la CPU...")
            pipeline.to(torch.device("cpu"))
            resultado = _ejecutar()
    except Exception as e:
        logger.error(f"El motor de diarización falló: {e}")
        raise

    # La versión "exclusive" no tiene voces solapadas: es la indicada para alinear con texto
    anotacion = getattr(resultado, "exclusive_speaker_diarization", resultado)

    turnos = [
        {"start": turno.start, "end": turno.end, "speaker": hablante}
        for turno, _, hablante in anotacion.itertracks(yield_label=True)
    ]
    logger.info(f"Diarización completa: {len({t['speaker'] for t in turnos})} hablante(s) detectado(s).")
    return turnos


# Una frase solo se parte entre dos hablantes si cada parte tiene al menos estas palabras.
# Un trozo más corto suele ser un error de los tiempos: ni la hora de cada palabra ni los
# bordes de cada turno son exactos, y cortar ahí deja frases partidas ("de a poco y").
MIN_PALABRAS_POR_TURNO = 4
# Un silencio así de largo entre dos palabras también separa frases (Whisper no siempre puntúa)
PAUSA_ENTRE_FRASES = 0.5


def asignar_hablantes(segmentos: list, turnos: list) -> list:
    """
    Asigna un hablante a cada frase.
    Si los segmentos traen la hora de cada palabra ("words"), el texto se rehace en frases
    (aunque una frase quede repartida entre dos segmentos de Whisper) y cada frase va al
    hablante de la mayoría de sus palabras. Una frase larga sin puntuación solo se parte
    donde cambia el hablante si a cada lado quedan al menos MIN_PALABRAS_POR_TURNO palabras.
    Un segmento sin palabras va entero al hablante con más tiempo solapado; si no se solapa
    con ningún turno, al turno más cercano.
    Los hablantes se renombran como "Hablante 1", "Hablante 2"... en orden de aparición.
    Retorna una lista nueva de segmentos, uno por frase.
    """
    if not turnos:
        logger.warning("La diarización no detectó hablantes. Se omiten las etiquetas.")
        return segmentos

    resultado = []
    palabras = []  # palabras pendientes, de uno o varios segmentos seguidos
    for seg in segmentos:
        propias = [p for p in seg.get("words") or [] if p.get("word", "").strip()]
        if propias:
            palabras.extend(propias)
            continue
        resultado.extend(_frases_con_hablante(palabras, turnos))
        palabras = []
        resultado.append({**seg, "speaker": _hablante_en(seg["start"], seg["end"], turnos)})
    resultado.extend(_frases_con_hablante(palabras, turnos))

    # Etiquetas legibles y estables: el primero que habla es "Hablante 1"
    etiquetas = {}
    for seg in resultado:
        if seg["speaker"] not in etiquetas:
            etiquetas[seg["speaker"]] = f"{ETIQUETA_GENERICA} {len(etiquetas) + 1}"
        seg["speaker"] = etiquetas[seg["speaker"]]

    return resultado


def _hablante_en(inicio: float, fin: float, turnos: list):
    """El hablante con más tiempo solapado con [inicio, fin]; sin solape, el del turno más cercano."""
    solapes = {}
    for turno in turnos:
        solape = min(fin, turno["end"]) - max(inicio, turno["start"])
        if solape > 0:
            solapes[turno["speaker"]] = solapes.get(turno["speaker"], 0.0) + solape
    if solapes:
        return max(solapes, key=solapes.get)
    centro = (inicio + fin) / 2
    return min(turnos, key=lambda t: _distancia(centro, t))["speaker"]


def _frases_con_hablante(palabras: list, turnos: list) -> list:
    """Convierte las palabras en segmentos de una frase (o parte de frase) con su hablante."""
    segmentos = []
    for frase in _partir_en_frases(palabras):
        hablantes = [_hablante_en(p["start"], p["end"], turnos) for p in frase]
        for hablante, tramo in _tramos_por_hablante(frase, hablantes):
            segmentos.append({
                "start": tramo[0]["start"],
                "end": tramo[-1]["end"],
                # mlx-whisper deja el espacio delante de cada palabra (" hola")
                "text": "".join(p["word"] for p in tramo).strip(),
                "speaker": hablante,
            })
    return segmentos


def _partir_en_frases(palabras: list) -> list:
    """Corta después de . ? ! …, antes de ¿ ¡, y en los silencios largos entre palabras."""
    frases, actual = [], []
    for palabra in palabras:
        abre_frase = palabra["word"].strip().startswith(("¿", "¡"))
        if actual and (abre_frase or palabra["start"] - actual[-1]["end"] >= PAUSA_ENTRE_FRASES):
            frases.append(actual)
            actual = []
        actual.append(palabra)
        if _cierra_frase(palabra):
            frases.append(actual)
            actual = []
    if actual:
        frases.append(actual)
    return frases


def _tramos_por_hablante(frase: list, hablantes: list) -> list:
    """
    Agrupa las palabras de una frase en tramos seguidos del mismo hablante, y suma cada tramo
    de menos de MIN_PALABRAS_POR_TURNO palabras a su vecino más largo, empezando por el más corto.
    Retorna [(hablante, [palabras]), ...].
    """
    tramos = []
    for palabra, hablante in zip(frase, hablantes):
        if tramos and tramos[-1][0] == hablante:
            tramos[-1][1].append(palabra)
        else:
            tramos.append((hablante, [palabra]))

    while len(tramos) > 1:
        i = min(range(len(tramos)), key=lambda k: (len(tramos[k][1]), _duracion(tramos[k][1])))
        if len(tramos[i][1]) >= MIN_PALABRAS_POR_TURNO:
            break
        vecinos = [j for j in (i - 1, i + 1) if 0 <= j < len(tramos)]
        j = max(vecinos, key=lambda k: (len(tramos[k][1]), _duracion(tramos[k][1])))
        hablante, palabras = tramos[j]
        palabras = palabras + tramos[i][1] if j < i else tramos[i][1] + palabras
        tramos[j] = (hablante, palabras)
        del tramos[i]
        # Al quitar un tramo, sus dos vecinos pueden quedar con el mismo hablante: se juntan
        unidos = []
        for hablante, palabras in tramos:
            if unidos and unidos[-1][0] == hablante:
                unidos[-1] = (hablante, unidos[-1][1] + palabras)
            else:
                unidos.append((hablante, palabras))
        tramos = unidos
    return tramos


def _duracion(palabras: list) -> float:
    return sum(p["end"] - p["start"] for p in palabras)


def _cierra_frase(palabra: dict) -> bool:
    return palabra["word"].strip().endswith((".", "?", "!", "…"))


def _distancia(punto: float, turno: dict) -> float:
    if turno["start"] <= punto <= turno["end"]:
        return 0.0
    return min(abs(punto - turno["start"]), abs(punto - turno["end"]))


def parsear_nombres(texto: str) -> dict:
    """
    Convierte el texto de --nombres en un mapa {"Hablante N": "Nombre"}.
    Acepta nombres en orden de aparición ("Ana,Luis") o por número ("2=Luis,1=Ana").
    """
    nombres = {}
    if not texto:
        return nombres

    for posicion, item in enumerate(texto.split(","), start=1):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            numero, nombre = (parte.strip() for parte in item.split("=", 1))
            if not numero.isdigit():
                raise ValueError(f"En --nombres, '{numero}' debe ser el número del hablante (ej: 2=Luis).")
            posicion = int(numero)
        else:
            nombre = item
        if not nombre:
            raise ValueError(f"En --nombres, falta el nombre para el hablante {posicion}.")
        nombres[f"{ETIQUETA_GENERICA} {posicion}"] = nombre

    return nombres


def aplicar_nombres(parrafos: list, nombres: dict) -> list:
    """Retorna una copia de los párrafos con los hablantes renombrados. Los que no estén en el mapa conservan su etiqueta."""
    return [
        {**p, "speaker": nombres.get(p["speaker"], p["speaker"])} if "speaker" in p else dict(p)
        for p in parrafos
    ]
