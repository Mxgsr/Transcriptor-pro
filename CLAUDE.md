# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Reglas del dueño del proyecto

- **No hagas commits, pushes ni pull requests.** Deja los cambios sin commitear; Max los revisa y commitea él mismo.
- Todo está en español: código (funciones, variables), comentarios, mensajes de la CLI, README y tests. Los usuarios no son técnicos, así que los mensajes en pantalla y el README usan lenguaje simple.
- Cada archivo empieza con un comentario `# Ubicación: ruta/del/archivo.py` y una explicación corta de qué hace. Los comentarios explican el *porqué*; mantén esa densidad.
- El entorno se maneja con `uv` (Python 3.11 en el `.venv` de Max). Da comandos `uv pip ...`, no `pip ...`.

## Comandos

```bash
# Entorno de desarrollo
uv venv && source .venv/bin/activate
uv pip install -e ".[diarizacion]"              # los extras que no aplican a la plataforma se saltan solos
uv pip install -r requirements-dev.txt          # solo para tests

# Tests (no necesitan red, GPU ni modelos)
python -m pytest
python -m pytest tests/test_diarizer.py
python -m pytest tests/test_repeticiones.py::test_quita_los_bucles
python -m pytest -k hablantes

# Ejecutar
transcriptor                     # menú con flechas (solo en terminal interactiva; si no, muestra la ayuda)
transcriptor transcribir ARCHIVO_O_URL -m small -d
transcriptor nombres audio.blocks.json -e
python main.py ...               # equivalente; main.py solo llama a src.cli:app
```

No hay linter configurado. CI (`.github/workflows/tests.yml`, en cada push y pull request) corre `pytest` en Ubuntu con Python 3.10 y 3.12 instalando **solo** `requirements-dev.txt`: cualquier import de mlx, pyannote, faster-whisper, yt-dlp o numpy pesado a nivel de módulo rompe CI. Esas librerías se importan dentro de las funciones (buscar "Importación diferida").

## Arquitectura

Versión actual: `2.0.0b1` ("V2-beta1", en `pyproject.toml`). Los instaladores bajan `main`; la beta vive en la rama `v2` (la crea y publica Max).

Flujo: entrada (URL o archivo) → descarga (yt-dlp) → Whisper → limpieza de bucles → párrafos → `.blocks.txt` → (opcional) diarización → `.blocks.json` + `.blocks.txt` con hablantes.

Capas:
- `src/cli.py` (Typer + Rich): todo lo que se ve en pantalla, comandos `transcribir` y `nombres`. Barras de progreso en `_Pasos`. `ejecutar_transcripcion` envuelve el trabajo en `aviso.sin_dormir()` (siempre) y `aviso.confirmar_cancelar()` (solo con una persona delante: no `--sin-preguntas` y terminal interactiva), y notifica al terminar si pasó más de `SEGUNDOS_TRABAJO_LARGO` (60 s). `_escuchar_y_nombrar` es el paso de poner nombres con flechas (Ponerle nombre / Escuchar otra vez / Otro fragmento / Es la misma persona que… / Dejar como está; con sugerencia por voz, «Es <nombre>» va primero). `_mostrar_error` traduce el error con `errores.mensaje_simple` y guarda el detalle siempre (ya no hace falta `-v`; `-v` sigue mostrando el traceback y los logs). `cli.ultimo_error` guarda la ruta de ese detalle para el menú.
- `src/menu.py` (questionary): solo hace preguntas y luego llama a las mismas funciones de `cli.py` (p. ej. `cli.ejecutar_transcripcion`). "← Volver"/Esc lanza `Atras`; Ctrl+C vuelve al menú principal. «Transcribir» son 3 pasos encadenados con `seguir_pasos` (entrada: un solo campo que distingue archivo o URL; una sola pregunta de hablantes, que respeta `modo_hablantes`; nombre de la reunión, propuesta `<fecha de grabación> Reunión`) y «¿Empiezo?» con «Más opciones…» (modelo, idioma, carpeta solo para esa vez). Tras un error, `_que_hago_con_el_error` ofrece Ver el detalle / Copiar el error / Volver al menú. «Copiar la transcripción» está en `acciones_sobre` («¿Y ahora?» y «Mis transcripciones»). Ya no existe la opción de menú «Usar los nombres que edité a mano en el .json» (el comando `nombres ARCHIVO` sin lista sigue).
- `src/aviso.py`: cosas del sistema operativo, solo con librería estándar y sin lanzar nunca errores: `sin_dormir()` (Mac `caffeinate -i -w <pid>`; Windows `SetThreadExecutionState` por ctypes), `notificar()` (Mac `osascript`; Windows PowerShell con la API de avisos + `winsound`; Linux `notify-send`), `copiar_al_portapapeles()` (`pbcopy`; Windows `Set-Clipboard` leyendo un archivo temporal UTF-8; Linux `wl-copy`/`xclip`) y `confirmar_cancelar()` (segundo Ctrl+C pasado el primer minuto). El texto del usuario viaja a PowerShell por variables de entorno, nunca pegado en el script. Lo de Windows no se ha probado en un Windows real.
- `src/errores.py`: `mensaje_simple` traduce los errores comunes (falta `HF_TOKEN`, sin internet, archivo que no es audio, disco lleno, archivo no encontrado) y `guardar_detalle` escribe `~/.transcriptor/errores/AAAA-MM-DD_HHMMSS.txt` (versión, sistema, comando, traceback; sin variables de entorno, con el token tapado; se conservan los últimos 30).
- `src/voces.py`: reconocimiento por voz. Guarda en `voces.json` la huella (embedding de pyannote, centroide por hablante) de cada persona nombrada y `parecidos()` compara por similitud coseno contra `UMBRAL` (0.6, **provisional**: hay que ajustarlo con reuniones reales). Python puro, sin numpy. Solo propone: cada sugerencia se confirma al nombrar. Se apaga con el ajuste `reconocer_voces`.
- `src/procesador.py`: orquesta el flujo sin imprimir nada; informa avance con callbacks (`al_avanzar`, `al_progresar`, `al_fallar`) y devuelve un `Resultado`. El TXT se guarda **antes** de diarizar para no perderlo si la diarización falla; si falla, la transcripción queda sin hablantes y no es un error.
- `src/transcriber.py`: dos motores con los mismos nombres de modelo (`MODELOS_MLX` / `MODELOS_FASTER`): mlx-whisper en Mac con chip Apple, faster-whisper en Windows/Linux/Mac Intel. `motor()` decide según si `mlx_whisper` se pudo importar. `AJUSTES_CONTRA_BUCLES` (sin condicionar en texto previo, timestamps por palabra, saltar alucinaciones en silencios) es deliberado.
- `src/repeticiones.py`: quita sin IA las frases que Whisper repite en bucle, en segmentos y en párrafos.
- `src/diarizer.py`: pyannote. `asignar_hablantes` usa los timestamps por palabra para dar cada frase completa al hablante mayoritario. El `.blocks.json` guarda las etiquetas genéricas ("Hablante 1") y el mapa `nombres` aparte, para poder renombrar sin reprocesar (`procesador.renombrar_hablantes`). `diarizar_audio` también saca las huellas de voz (`speaker_embeddings` de pyannote 4) y `traducir_huellas` las pasa de `SPEAKER_00` a "Hablante N"; sin huellas la diarización sigue igual.
- `src/plataforma.py`: qué funciona en cada computador (hablantes: no en Mac Intel). Las mismas restricciones están como marcadores de plataforma en `pyproject.toml`.
- Configuración en tres niveles, de menor a mayor prioridad: `src/config.py` (lee `.env` del proyecto y luego `~/.transcriptor/.env`; también apaga la telemetría de pyannote/HF) → `src/ajustes.py` (menú "Configuración", guardado en `preferencias.json`) → opciones de la línea de comandos. `ajustes.aplicar_sin_internet()` pone `HF_HUB_OFFLINE` y debe correr antes de que se importe `huggingface_hub`.
- `src/historial.py`: historial, preferencias y personas en `~/.transcriptor/` (o `$TRANSCRIPTOR_HOME`). Archivos que viven ahí: `.env`, `historial.json`, `preferencias.json`, `personas.json` (nombres usados, con veces y última vez, para elegirlos de una lista), `voces.json` (huellas de voz; **solo en el computador**, nunca se envían), `errores/` (detalle de cada error) y `bin/` (ffmpeg).
- `src/ffmpeg_local.py`: si no hay `ffmpeg` en el PATH, enlaza el de imageio-ffmpeg en `~/.transcriptor/bin`.
- `utils/formatters.py`: formato de `.blocks.txt` (`[HH:MM:SS] Hablante: texto`) y lectura/escritura del `.blocks.json`.

### Título y encabezado (solo desde el menú)

Con `titulo` (y `fecha`) el procesador nombra el archivo `AAAA-MM-DD Título.blocks.txt` (con `(2)`, `(3)`… si ya existe) y el `.txt` empieza con un encabezado (`# Título`, Fecha, Duración, Participantes; las líneas sin dato se omiten) seguido de una línea en blanco. El `.blocks.json` guarda entonces las claves `titulo`, `fecha` (AAAA-MM-DD) y `duracion`, para rehacer el encabezado al poner nombres (los participantes salen de ahí); las `huellas` ({"Hablante 1": [...]}) se guardan siempre que haya. **Sin título** (línea de comandos, Grabador, `.json` antiguos) esas claves no se escriben, no hay encabezado y el archivo se llama `<nombre del audio>.blocks.txt`, como antes. `cargar_transcripcion` acepta `.json` sin estas claves.

### Contrato con el Grabador (no romper)

La app Grabador de Max llama `transcriptor transcribir <archivo> -d --sin-preguntas -o <carpeta>` y luego lee `<nombre del audio>.blocks.txt`. `tests/test_grabador.py` fija esa llamada de punta a punta: mismo nombre de archivo, formato `[HH:MM:SS] Hablante: texto` separado por líneas en blanco, sin encabezado, sin preguntas ni notificaciones, y sin nombres automáticos por voz. Con `--sin-preguntas` (o sin terminal interactiva) nada debe preguntar ni cambiar. No añadas flags obligatorios ni cambies esos nombres sin hablarlo con Max.

## Tests

`tests/conftest.py` reemplaza `mlx_whisper` en `sys.modules` (usa el fixture `mlx_transcribe` para simular la transcripción), bloquea `yt_dlp` real, apunta `TRANSCRIPTOR_HOME` a una carpeta temporal y hace que todos los tests corran "como en un Mac con chip Apple" (`plataforma.*` devuelve `True`). Para probar otra plataforma, sobrescribe esos `monkeypatch` en el test.

## Instalación para usuarios

`instalar.sh` (Mac/Linux) e `instalar.ps1` (Windows) instalan uv si falta, bajan el zip de `main` (la rama va fija en la constante `ZIP`/`$Zip`; no aceptan otra rama) con curl/PowerShell y hacen `uv tool install` desde ese archivo con el extra `[diarizacion]`; luego piden el `HF_TOKEN` opcional y lo guardan en `~/.transcriptor/.env`. Lo que se sube a `main` es lo que instalan los usuarios. Para probar la beta (rama `v2`) el README explica un `uv tool install` directo desde `.../archive/refs/heads/v2.zip`.
