Primera versión estable de Transcriptor Pro (1 de noviembre de 2026).

Qué incluye:
- Transcribe archivos de audio o video y enlaces de YouTube con Whisper (mlx-whisper en Mac con chip Apple; faster-whisper en Windows y Mac con Intel).
- Identifica quién habla (pyannote) y permite ponerles nombre escuchando a cada uno.
- Menú con flechas, Configuración y Mis transcripciones.
- Limpieza de las frases que Whisper repite en bucle.
- Instaladores de una línea para Mac y Windows.
- Telemetría apagada y opción Sin internet.

Ya no incluye la corrección con IA local.

Para instalar exactamente esta versión:
uv tool install --force --python 3.11 "transcriptor-pro[diarizacion] @ https://github.com/Mxgsr/Transcriptor-pro/archive/refs/tags/v1.0.0.zip"
