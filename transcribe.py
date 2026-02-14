import os
import subprocess
from pathlib import Path
import math
import sys
from urllib.parse import urlparse
import whisper
import torch


# ------------------------------------------
# Utilidades
# ------------------------------------------

def es_url(s: str) -> bool:
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://")


def es_url_valida(url: str) -> bool:
    """Valida que la URL sea legítima y segura."""
    try:
        result = urlparse(url)
        # Verificar que tenga scheme y netloc válidos
        if not all([result.scheme in ('http', 'https'), result.netloc]):
            return False
        # Lista blanca de dominios permitidos para descargas
        dominios_permitidos = [
            'youtube.com', 'youtu.be', 'youtube-nocookie.com',
            'vimeo.com', 'dailymotion.com', 'twitch.tv'
        ]
        if not any(dominio in result.netloc.lower() for dominio in dominios_permitidos):
            print(f"⚠️ Advertencia: dominio no está en la lista blanca: {result.netloc}")
            print("Continuando de todas formas (puedes cancelar con Ctrl+C)...")
        return True
    except:
        return False


def descargar_audio(url: str, output_dir: str = "downloads") -> Path:
    # Validar URL antes de procesar
    if not es_url_valida(url):
        raise ValueError(f"URL inválida o insegura: {url}")

    os.makedirs(output_dir, exist_ok=True)
    template = "%(title)s.%(ext)s"

    cmd = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "-x",
        "--audio-format", "mp3",
        "-o", str(Path(output_dir) / template),
        url,
    ]

    print("Descargando audio desde YouTube…")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error descargando audio: código {e.returncode}") from e

    mp3_files = sorted(Path(output_dir).glob("*.mp3"), key=os.path.getmtime)
    if not mp3_files:
        raise FileNotFoundError("No se encontró ningún archivo .mp3 después de la descarga.")

    audio_path = mp3_files[-1]
    print(f"✔ Audio descargado en: {audio_path}")
    return audio_path


def _format_timestamp_hhmmss(seconds: float) -> str:
    seconds = max(0, seconds)
    total_seconds = int(round(seconds))
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_timestamp_srt(seconds: float) -> str:
    seconds = max(0, seconds)
    ms = int(round((seconds - math.floor(seconds)) * 1000))
    total_seconds = int(math.floor(seconds))
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ------------------------------------------
# Transcripción
# ------------------------------------------

def transcribir_local_con_segmentos(audio_path: Path, model_name: str, language: str = "es"):
    """
    Transcribe usando CPU (estable) incluso si MPS está disponible.
    En Apple Silicon M3/M4 MPS produce NaNs con Whisper.
    Esta versión es estable y segura.
    """

    device = "cpu"  # ← fuerza CPU porque MPS da NaNs en M3/M4 con Whisper
    print(f"➡ Usando dispositivo: {device}")
    print(f"Cargando modelo Whisper '{model_name}'...")

    model = whisper.load_model(model_name, device=device)

    print(f"Transcribiendo archivo: {audio_path}")

    result = model.transcribe(
        str(audio_path),
        language=language,
        verbose=False
    )

    segments = result.get("segments", [])
    if not segments:
        return [{"start": 0.0, "end": 0.0, "text": result.get("text", "").strip()}]

    return segments

def agrupar_segmentos_en_parrafos(
    segments,
    pause_threshold: float = 2.0,
    max_chars: int = 600,
    min_chars_for_pause_break: int = 150
):
    if not segments:
        return []

    paragrafos = []
    current_start = segments[0]["start"]
    current_end = segments[0]["end"]
    current_texts = [segments[0]["text"].strip()]

    def current_text():
        return " ".join(t for t in current_texts if t)

    for prev, seg in zip(segments, segments[1:]):
        seg_start = seg["start"]
        seg_end = seg["end"]
        seg_text = seg["text"].strip()

        gap = seg_start - prev["end"]
        texto_actual = current_text()
        largo_actual = len(texto_actual)

        termina_en_punto = texto_actual.endswith((".", "?", "!", "¿", "¡"))

        corte_por_pausa = gap >= pause_threshold and largo_actual >= min_chars_for_pause_break
        corte_por_largo = largo_actual >= max_chars and termina_en_punto

        if corte_por_pausa or corte_por_largo:
            paragrafos.append({
                "start": current_start,
                "end": current_end,
                "text": texto_actual
            })
            current_start = seg_start
            current_end = seg_end
            current_texts = [seg_text] if seg_text else []
        else:
            current_end = seg_end
            if seg_text:
                current_texts.append(seg_text)

    texto_final = current_text()
    if texto_final:
        paragrafos.append({
            "start": current_start,
            "end": current_end,
            "text": texto_final
        })

    return paragrafos


def guardar_txt_con_timestamps(segments_agrupados, output_path: Path):
    lines = []
    for seg in segments_agrupados:
        ts = _format_timestamp_hhmmss(seg["start"])
        text = seg["text"].strip()
        if text:
            lines.append(f"[{ts}] {text}")

    output_path = Path(output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(lines))

    print(f"✔ TXT guardado en: {output_path}")


def guardar_srt(segments_agrupados, output_path: Path):
    blocks = []
    for i, seg in enumerate(segments_agrupados, start=1):
        start = _format_timestamp_srt(seg["start"])
        end = _format_timestamp_srt(seg["end"])
        text = seg["text"].strip()
        if not text:
            continue
        blocks.append(f"{i}\n{start} --> {end}\n{text}\n")

    output_path = Path(output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))

    print(f"✔ SRT guardado en: {output_path}")


# ------------------------------------------
# Parser de argumentos
# ------------------------------------------

def parse_args(raw_args):
    """
    Ejemplos válidos:
    transcribe archivo.mp4
    transcribe --model small archivo.mp4
    transcribe --model tiny "https://youtu.be/..."
    """

    # Defaults
    model_name = "medium"
    entrada = None

    args = list(raw_args)

    while args:
        token = args.pop(0)
        if token == "--model":
            if not args:
                raise ValueError("Debes especificar un modelo después de --model")
            model_name = args.pop(0).lower()

            # Validar modelo
            modelos_validos = {"tiny", "base", "small", "medium", "large"}
            if model_name not in modelos_validos:
                raise ValueError(f"Modelo no válido: {model_name}. Opciones: {modelos_validos}")

        else:
            entrada = token

    if entrada is None:
        raise ValueError("Debes pasar un archivo local o una URL de YouTube.")

    return entrada, model_name


# ------------------------------------------
# Transcribir desde entrada (URL o archivo)
# ------------------------------------------

def transcribir_desde_entrada(entrada: str, model_name: str):
    entrada = entrada.strip()

    if es_url(entrada):
        audio_path = descargar_audio(entrada)
    else:
        posible = Path(entrada).expanduser()
        if not posible.is_file():
            raise FileNotFoundError(f"No encontré el archivo local: {posible}")
        audio_path = posible
        print(f"Usando archivo local: {audio_path}")

    segments = transcribir_local_con_segmentos(audio_path, model_name=model_name)
    parrafos = agrupar_segmentos_en_parrafos(segments)

    txt_path = audio_path.with_suffix(".blocks.txt")
    srt_path = audio_path.with_suffix(".blocks.srt")

    guardar_txt_con_timestamps(parrafos, txt_path)
    guardar_srt(parrafos, srt_path)


# ------------------------------------------
# main
# ------------------------------------------

if __name__ == "__main__":
    try:
        entrada, modelo = parse_args(sys.argv[1:])
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    print(f"➡ Usando modelo: {modelo}")
    transcribir_desde_entrada(entrada, model_name=modelo)
