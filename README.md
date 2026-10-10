# 🎙️ Transcriptor Pro

Un sistema robusto y modular para transcribir audio y video (YouTube o archivos locales) utilizando **Whisper** sobre **MLX** (`mlx-whisper`), acelerado en la GPU de los Mac con Apple Silicon. 

Este proyecto fue refactorizado siguiendo principios de arquitectura limpia, manejo de errores avanzado y configuración mediante variables de entorno.

## ✨ Características

- **Soporte Dual:** Transcribe archivos locales (`.mp3`, `.wav`, `.mp4`, etc.) y enlaces de YouTube.
- **Arquitectura Modular:** Lógica separada en módulos de descarga, transcripción y formateo.
- **Párrafos Inteligentes:** Agrupa el texto basado en pausas y longitud para una lectura cómoda.
- **Sin frases en bucle:** Evita y limpia las frases que Whisper a veces repite muchas veces seguidas (ver abajo).
- **Texto con Marcas de Tiempo:** Genera un archivo `.txt` con la hora de inicio de cada párrafo.
- **Identificación de Hablantes (opcional):** Detecta quién habla en cada momento con `pyannote.audio` y permite ponerle nombre a cada hablante.
- **CLI cómoda:** Comando `transcriptor` con progreso de cada paso, resumen final y errores claros (`-v` muestra el detalle interno).

## 🛠️ Instalación

1. **Clonar el repositorio:**
~~~ 
   git clone [https://github.com/Mxgsr/Transcriptor-pro.git](https://github.com/Mxgsr/Transcriptor-pro.git)
   cd Transcriptor-pro
~~~ 

2. Crear y activar el entorno virtual:
~~~ 
uv venv
source .venv/bin/activate
~~~ 

3. Instalar el proyecto (esto crea el comando `transcriptor`):
~~~ 
uv pip install -e .
~~~
_Nota: Requiere un Mac con Apple Silicon (M1 o posterior), porque MLX solo funciona ahí, y tener instalado ffmpeg en el sistema (`brew install ffmpeg`)._

4. Configurar variables de entorno:
Crea un archivo .env en la raíz con el siguiente contenido:
```
DEFAULT_MODEL=medium
DOWNLOAD_DIR=downloads
```
🚀 Uso
Con el entorno virtual activado, escribe solo:
```
transcriptor
```
Se abre un menú: te mueves con ↑ ↓ y eliges con Enter. Para regresar a la pregunta anterior elige "← Volver" o aprieta Esc; Ctrl+C te lleva directo al menú principal. Desde ahí puedes transcribir un archivo o un enlace, corregir una transcripción, cambiar los nombres de los hablantes o ver tus últimas transcripciones. El menú recuerda lo último que elegiste (modelo, hablantes, corrección) y lo ofrece por defecto; el idioma y la carpeta salen de Configuración, y "Más opciones…" los cambia solo para esa transcripción. El historial y esas preferencias se guardan en `~/.transcriptor/`.

En **Configuración** (también en el menú) eliges los valores por defecto: idioma, modelo de transcripción, modelo de IA para corregir, si identificar hablantes y si corregir al terminar (preguntar cada vez, siempre o nunca), la carpeta de las descargas de YouTube y la carpeta donde guardar las transcripciones (junto al audio, o siempre la misma). Valen también para los comandos (`transcriptor transcribir`, `transcriptor corregir`) cuando no indicas esa opción, y mandan sobre `DEFAULT_MODEL`, `DOWNLOAD_DIR` y `CORRECTOR_MODEL` del `.env`, que quedan como valores de fábrica.

Los mismos pasos existen como comandos, útiles en scripts o cuando ya sabes lo que quieres:
```
transcriptor transcribir "URL_O_RUTA_ARCHIVO" -m tiny
```
Verás cada paso con su tiempo y, al final, un resumen con la ruta del `.blocks.txt`. `transcriptor --help` y `transcriptor transcribir --help` muestran todas las opciones. También funciona `python main.py transcribir ...`.

Opciones principales de `transcribir`:
- `-m, --modelo`: modelo de Whisper (ver abajo).
- `-i, --idioma`: idioma del audio (por defecto `es`).
- `-o, --salida`: carpeta donde guardar la transcripción (por defecto, junto al audio).
- `-v, --detalle`: muestra los mensajes internos y la salida de yt-dlp y mlx-whisper.

Whisper a veces entra en bucle en pausas, llantos o cuando hablan dos a la vez, y escribe la misma frase muchas veces ("Gracias. Gracias. Gracias..."). Para evitarlo, cada trozo se transcribe sin usar el texto anterior como pista (así un error no se arrastra) y se saltan los trozos dudosos rodeados de silencio. Lo que aun así se cuele se limpia al final, sin IA: una palabra repetida 4 o más veces seguidas, o una frase 3 o más, queda una sola vez. Las repeticiones normales del habla ("sí, sí, sí") se respetan.

Las descargas de YouTube van a `DOWNLOAD_DIR` (por defecto `downloads/`), relativa a la carpeta desde la que ejecutas el comando.

Modelos disponibles en `--modelo` (o `DEFAULT_MODEL` en el `.env`): `tiny`, `base`, `small`, `medium`, `large` (large-v3), `large-v2` y `turbo` (large-v3-turbo, casi tan preciso como `large` y mucho más rápido). También acepta directamente un repositorio de Hugging Face con un modelo MLX, por ejemplo `--modelo mlx-community/whisper-small-mlx-4bit`. La primera vez que usas un modelo se descarga automáticamente.

🗣️ Diarización (identificar hablantes)

Es opcional: sin `-d` (`--hablantes`) el programa funciona igual que siempre.

1. Instala las dependencias extra:
```
uv pip install -e ".[diarizacion]"
```
2. Crea un token de lectura en https://huggingface.co/settings/tokens.
3. Acepta las condiciones de uso del modelo en https://huggingface.co/pyannote/speaker-diarization-community-1 con la misma cuenta.
4. Añade el token a tu `.env`:
```
HF_TOKEN=hf_xxxxxxxxxxxxxxxx
# Opcional: otro modelo de pyannote
# DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
# Opcional: dónde corre la diarización. Por defecto (auto) usa la GPU del Mac;
# pon cpu si alguna vez da resultados raros o errores.
# DIARIZATION_DEVICE=auto
```

Uso:
```
# Detecta hablantes y los etiqueta como "Hablante 1", "Hablante 2"... (en orden de aparición)
transcriptor transcribir "URL_O_RUTA_ARCHIVO" -d

# Si ya sabes cuántos son, indícalo para mejorar la precisión
transcriptor transcribir "URL_O_RUTA_ARCHIVO" -d --num 2

# Ponles nombre directamente (en orden de aparición, o por número)
transcriptor transcribir "URL_O_RUTA_ARCHIVO" -d --nombres "Ana,Luis"
transcriptor transcribir "URL_O_RUTA_ARCHIVO" -d --nombres "2=Luis,1=Ana"
```

El resultado queda así en el `.blocks.txt`:
```
[00:00:00] Ana: Hola, ¿cómo estás?

[00:00:02] Luis: Bien, gracias.
```

Whisper da la hora de cada palabra, así que el texto se rehace en frases y cada frase va a quien dice la mayoría de sus palabras, aunque Whisper haya escrito a los dos hablantes en el mismo trozo. Una frase larga sin puntuación solo se parte entre dos hablantes si a cada lado quedan al menos 4 palabras: la hora de cada palabra no es exacta, y cortar por menos dejaría frases partidas.

Como normalmente no sabes quién es "Hablante 1" hasta oírlo, al terminar te pregunta si quieres escuchar a cada hablante: muestra lo que dice, reproduce unos segundos de su voz y te pide su nombre (`r` repite el fragmento, `o` pone otro, Enter lo deja como está). Con `--sin-preguntas` no pregunta nada.

Además se guarda un `.blocks.json` (con los párrafos, la ruta del audio y los nombres), así que puedes cambiar los nombres después sin volver a procesar el audio (se re-escribe el `.txt`):
```
# Escuchando de nuevo a cada hablante
transcriptor nombres "downloads/mi_audio.blocks.json" -e

# O directamente con una lista
transcriptor nombres "downloads/mi_audio.blocks.json" "Ana,Luis"
```

Si prefieres editar los nombres directamente en el `.blocks.json` (cambiando `"Hablante 1"` por el nombre en cada `"speaker"`), después rehaz el `.txt` con:
```
transcriptor nombres "downloads/mi_audio.blocks.json"
```

Otras opciones: `--min N` y `--max N` cuando solo conoces un rango. Si usas `--num`, `--min`, `--max` o `--nombres` sin `-d`, la identificación de hablantes se activa sola y te lo avisa.

✍️ Corrección con IA local

Whisper casi nunca comete faltas de ortografía, pero sí confunde palabras que suenan parecido ("haber" por "a ver"), pone mal tildes como solo/tú y puntúa a su manera. `transcriptor corregir` repasa la transcripción con un modelo de lenguaje que corre en tu Mac (mlx-lm), sin enviar nada a internet.

1. Instala las dependencias extra:
```
uv pip install -e ".[correccion]"
```
2. Corrige una transcripción ya hecha (sirve el `.blocks.json` o el `.blocks.txt`):
```
transcriptor corregir "downloads/mi_audio.blocks.json"

# Revisando cada cambio antes de aplicarlo
transcriptor corregir "downloads/mi_audio.blocks.json" -r
```

El resultado se guarda aparte, en `mi_audio.corregido.blocks.txt` (y su `.corregido.blocks.json`); la transcripción original no se toca.

Cómo funciona:
- Antes de la IA, y sin ella, quita las frases repetidas en bucle (igual que al transcribir), así también se limpian las transcripciones hechas antes de este cambio. Los errores de hablante de esas transcripciones solo se arreglan volviendo a transcribir.
- Corrige párrafo a párrafo, dándole al modelo el párrafo anterior como contexto. Solo le pasa el texto: las marcas de tiempo y los hablantes no pasan por el modelo, así que no se pueden perder.
- **Salvaguarda:** si el modelo cambia más de un 15 % del texto de un párrafo (sin contar tildes, mayúsculas ni puntuación), se queda el original. Así no puede resumir ni reescribir. Se ajusta con `--max-cambio 25`.
- Con `-r` ves cada cambio (lo quitado en rojo, lo nuevo en verde) y decides: Enter lo aplica, `n` deja el original, `t` aplica todos los que quedan.
- En el `.corregido.blocks.json`, cada párrafo corregido guarda su `"texto_original"`, y los que no se aplicaron guardan la propuesta en `"correccion_no_aplicada"`.
- Si lo interrumpes con Ctrl+C, se guarda lo corregido hasta ese momento.

Modelos (`-m`, o `CORRECTOR_MODEL` en el `.env`):
- `qwen3-8b` (por defecto, ~4,6 GB): buen equilibrio entre calidad y velocidad en un Mac de 16 GB.
- `qwen3-4b` (~2,3 GB): el doble de rápido, algo menos fino.
- `gemma4-e4b` (~3 GB): alternativa rápida.
- También acepta un repositorio de mlx-community, por ejemplo `-m mlx-community/Qwen3-14B-4bit` si tienes memoria de sobra.

La primera vez se descarga el modelo. Como referencia aproximada, una hora de audio con `qwen3-8b` debería tardar del orden de 10 a 15 minutos en un M4.

🧪 Tests
Los tests simulan mlx-whisper, mlx-lm y yt-dlp (no necesitan un Mac), así que corren en segundos sin red ni modelos:
```
uv pip install -r requirements-dev.txt
python -m pytest
```
GitHub Actions los ejecuta en cada push y pull request.

📂 Estructura del Proyecto
`src/`: Lógica central (descarga, transcripción, diarización, configuración). `src/cli.py` es la interfaz del comando `transcriptor` y `src/procesador.py` orquesta el flujo completo.

`utils/`: Validadores y formateadores de texto.

`downloads/`: Carpeta por defecto para archivos procesados.

`tests/`: Tests con pytest.

`main.py`: Atajo para ejecutar la CLI con `python main.py`.

`pyproject.toml`: Dependencias y definición del comando `transcriptor`.

⚖️ Licencia
MIT