# 🎙️ Transcriptor Pro

Un sistema robusto y modular para transcribir audio y video (YouTube o archivos locales) utilizando la inteligencia artificial de **OpenAI Whisper**. 

Este proyecto fue refactorizado siguiendo principios de arquitectura limpia, manejo de errores avanzado y configuración mediante variables de entorno.

## ✨ Características

- **Soporte Dual:** Transcribe archivos locales (`.mp3`, `.wav`, `.mp4`, etc.) y enlaces de YouTube.
- **Arquitectura Modular:** Lógica separada en módulos de descarga, transcripción y formateo.
- **Párrafos Inteligentes:** Agrupa el texto basado en pausas y longitud para una lectura cómoda.
- **Múltiples Formatos:** Genera archivos `.txt` con marcas de tiempo y archivos `.srt` para subtítulos.
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

📂 Estructura del Proyecto
`src/`: Lógica central (descarga, transcripción, configuración).

`utils/`: Validadores y formateadores de texto.

`downloads/`: Carpeta por defecto para archivos procesados.

`main.py`: Punto de entrada principal y orquestador.

⚖️ Licencia
MIT