# 🎙️ Transcriptor Pro

Un sistema robusto y modular para transcribir audio y video (YouTube o archivos locales) utilizando la inteligencia artificial de **OpenAI Whisper**. 

Este proyecto fue refactorizado siguiendo principios de arquitectura limpia, manejo de errores avanzado y configuración mediante variables de entorno.

## ✨ Características

- **Soporte Dual:** Transcribe archivos locales (`.mp3`, `.wav`, `.mp4`, etc.) y enlaces de YouTube.
- **Arquitectura Modular:** Lógica separada en módulos de descarga, transcripción y formateo.
- **Párrafos Inteligentes:** Agrupa el texto basado en pausas y longitud para una lectura cómoda.
- **Múltiples Formatos:** Genera archivos `.txt` con marcas de tiempo y archivos `.srt` para subtítulos.
- **Identificación de Hablantes (opcional):** Detecta quién habla en cada momento con `pyannote.audio` y permite ponerle nombre a cada hablante.
- **Sistema de Logs:** Registro detallado de cada paso para facilitar la depuración.

## 🛠️ Instalación

1. **Clonar el repositorio:**
~~~ 
   git clone [https://github.com/Mxgsr/Transcriptor-pro.git](https://github.com/Mxgsr/Transcriptor-pro.git)
   cd Transcriptor-pro
~~~ 

2. Crear y activar el entorno virtual:
~~~ 
python3 -m venv venv
source venv/bin/activate
~~~ 

3. Instalar dependencias:
~~~ 
pip install -r requirements.txt
~~~
_Nota: Requiere tener instalado ffmpeg en el sistema._

4. Configurar variables de entorno:
Crea un archivo .env en la raíz con el siguiente contenido:
```
DEFAULT_MODEL=medium
DOWNLOAD_DIR=downloads
```
🚀 Uso
Puedes ejecutar el programa directamente con Python:
```
python main.py "URL_O_RUTA_ARCHIVO" --model tiny
```

🗣️ Diarización (identificar hablantes)

Es opcional: sin `--diarizar` el programa funciona igual que siempre.

1. Instala las dependencias extra:
```
pip install -r requirements-diarizacion.txt
```
2. Crea un token de lectura en https://huggingface.co/settings/tokens.
3. Acepta las condiciones de uso del modelo en https://huggingface.co/pyannote/speaker-diarization-community-1 con la misma cuenta.
4. Añade el token a tu `.env`:
```
HF_TOKEN=hf_xxxxxxxxxxxxxxxx
# Opcional: otro modelo de pyannote
# DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
```

Uso:
```
# Detecta hablantes y los etiqueta como "Hablante 1", "Hablante 2"... (en orden de aparición)
python main.py "URL_O_RUTA_ARCHIVO" --diarizar

# Si ya sabes cuántos son, indícalo para mejorar la precisión
python main.py "URL_O_RUTA_ARCHIVO" --diarizar --hablantes 2

# Ponles nombre directamente (en orden de aparición, o por número)
python main.py "URL_O_RUTA_ARCHIVO" --nombres "Ana,Luis"
python main.py "URL_O_RUTA_ARCHIVO" --nombres "2=Luis,1=Ana"
```

El resultado queda así en el `.blocks.txt` (y con el mismo prefijo en el `.srt`):
```
[00:00:00] Ana: Hola, ¿cómo estás?

[00:00:02] Luis: Bien, gracias.
```

Además se guarda un `.blocks.json`. Como normalmente no sabes quién es "Hablante 1" hasta leer la transcripción, puedes asignar los nombres después sin volver a procesar el audio:
```
python main.py "downloads/mi_audio.blocks.json" --nombres "Ana,Luis"
```

Otras opciones: `--min-hablantes N` y `--max-hablantes N` cuando solo conoces un rango.

📂 Estructura del Proyecto
`src/`: Lógica central (descarga, transcripción, configuración).

`utils/`: Validadores y formateadores de texto.

`downloads/`: Carpeta por defecto para archivos procesados.

`main.py`: Punto de entrada principal y orquestador.

⚖️ Licencia
MIT