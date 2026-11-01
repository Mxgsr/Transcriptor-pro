# 🎙️ Transcriptor Pro

Convierte en texto un audio, un video o un enlace de YouTube. Puede reconocer quién habla en cada momento.

> **Versión de prueba (beta).** Esta es la versión 2.0.0b2 ("V2-beta2"). Los instaladores de abajo instalan siempre la versión estable (la de la rama `main`), así que **no** instalan la beta. Para probar la beta, mira más abajo la sección «Probar la versión beta».

## 🛠️ Instalación paso a paso

No necesitas instalar nada antes: el instalador trae todo lo necesario.

### En Mac

1. Abre la **Terminal** (aprieta `Cmd + Espacio`, escribe `Terminal` y aprieta Enter).
2. Copia esta línea, pégala en la Terminal y aprieta Enter:
   ```
   curl -LsSf https://raw.githubusercontent.com/Mxgsr/Transcriptor-pro/main/instalar.sh | sh
   ```
3. Espera a que termine. La primera vez tarda unos minutos.
4. Al final puede pedirte un token de Hugging Face, que sirve para reconocer quién habla. Es opcional: aprieta Enter para saltarlo (más abajo dice cómo conseguirlo).
5. Cierra la Terminal, abre una nueva y escribe:
   ```
   transcriptor
   ```

### En Windows

1. Abre **PowerShell** (aprieta la tecla Windows, escribe `PowerShell` y aprieta Enter).
2. Copia esta línea, pégala en PowerShell y aprieta Enter:
   ```
   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/Mxgsr/Transcriptor-pro/main/instalar.ps1 | iex"
   ```
3. Espera a que termine. La primera vez tarda unos minutos.
4. Al final puede pedirte un token de Hugging Face, que sirve para reconocer quién habla. Es opcional: aprieta Enter para saltarlo (más abajo dice cómo conseguirlo).
5. Cierra PowerShell, abre una ventana nueva y escribe:
   ```
   transcriptor
   ```

### Actualizar o desinstalar

- **Actualizar:** vuelve a pegar la misma línea de instalación.
- **Desinstalar:** escribe `uv tool uninstall transcriptor-pro`.

## 🧪 Probar la versión beta

Primero haz la instalación normal de arriba (así queda instalado `uv`, el programa que instala todo). Después copia esta línea en la misma ventana donde hiciste la instalación y aprieta Enter. Es una sola línea larga: pégala entera.

```
uv tool install --force --reinstall-package transcriptor-pro --python 3.11 "transcriptor-pro[diarizacion] @ https://github.com/Mxgsr/Transcriptor-pro/archive/refs/heads/v2.zip"
```

Tus transcripciones, tu configuración y tu token se conservan. Desde esta versión, **Configuración › Buscar actualizaciones** sirve para pasar a las versiones nuevas sin pegar esta línea otra vez (si tienes la beta 1, que aún no lo tiene, pega la línea una vez más). Para volver a la versión estable, pega otra vez la línea de instalación normal. Si tienes dudas, pídele a Max el comando.

## 🗣️ Reconocer quién habla (opcional)

Para que la transcripción diga quién habla en cada parte necesitas un token gratuito de Hugging Face:

1. Crea una cuenta en [huggingface.co](https://huggingface.co/join).
2. Acepta las condiciones del modelo en [esta página](https://huggingface.co/pyannote/speaker-diarization-community-1).
3. Crea un token de tipo **Read** en [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) y cópialo.
4. Vuelve a pegar la línea de instalación y, cuando te lo pida, pega el token.

## 🚀 Uso

Escribe `transcriptor` y se abre un menú. Te mueves con las flechas ↑ ↓ y eliges con Enter; Esc vuelve atrás.

Desde el menú puedes:
- Transcribir un archivo o un enlace de YouTube.
- Cambiar los nombres de los hablantes.
- Ver tus transcripciones, leerlas con el audio y buscar en todas.
- Cambiar la configuración (idioma, modelo, carpetas, clave, actualizaciones…).

### Transcribir, en 3 pasos

1. **Arrastra el archivo o pega el enlace.** Es un solo campo: sirve para las dos cosas.
2. **¿Identifico quién habla?** Eliges: *No identificar*, *Sí, no sé cuántos*, o cuántas personas son (2, 3, 4, 5 o más). Si en Configuración elegiste *Siempre* o *Nunca*, esta pregunta cambia o no aparece. Si no tienes el componente para identificar hablantes, tampoco aparece.
3. **¿Cómo se llama esta reunión?** Te propone la fecha de grabación y "Reunión" (por ejemplo `2026-11-01 Reunión`). Aprieta Enter para aceptar o escribe otro nombre.

Al final, **¿Empiezo?** Si quieres cambiar el modelo, el idioma o la carpeta solo para esta vez, entra a **Más opciones…**.

La transcripción se guarda como `AAAA-MM-DD Nombre.blocks.txt` (por ejemplo `2026-11-01 Reunión.blocks.txt`). Arriba lleva el título, la fecha, la duración y los participantes; debajo, el texto con la hora de cada párrafo. Si ya existe un archivo con ese nombre, no lo pisa: agrega `(2)`, `(3)`… La primera vez que usas un modelo se descarga solo, así que necesitas internet.

### Ponerles nombre a los hablantes

Después de identificar a los hablantes, el programa te ofrece escucharlos uno por uno. Con las flechas eliges:
- **Ponerle nombre:** escoges a alguien de la lista de personas que ya nombraste antes, o escribes uno nuevo.
- **Escuchar otra vez** o **Otro fragmento:** para reconocer mejor la voz.
- **Es la misma persona que…:** si un mismo hablante quedó dividido en dos, los unes.
- **Dejar como está:** no le cambias el nombre.

También puedes hacerlo después con **Cambiar nombres de hablantes**.

### Revisar frases dudosas

Al identificar hablantes, el programa marca las frases en las que dudó de quién habla. Después de ponerles nombre (y en **¿Y ahora?**) aparece **Revisar frases dudosas (N)**: te muestra la frase con la anterior y la siguiente, y eliges **Escuchar**, **Es de…** otra persona, **Está bien** o **Terminar la revisión**. Al mover una frase, la transcripción se rehace sola. Es opcional.

### Reconocer voces

Cuando le pones nombre a alguien, el programa guarda su "huella de voz" **solo en tu computador** (en `~/.transcriptor/voces.json`; no se envía a ningún lado). La próxima vez te propone "Es Ana" y tú lo confirmas: nunca pone un nombre solo. En **Configuración** puedes apagar esta función, ver las voces guardadas y olvidar una o todas.

### Copiar la transcripción

En **¿Y ahora?** (al terminar) y en **Mis transcripciones** está **Copiar la transcripción**. Copia el texto con su encabezado, listo para pegarlo en Claude y pedirle la minuta.

### Leer con el audio

En **¿Y ahora?** y en **Mis transcripciones** está **Leer con el audio**: abre en tu navegador una página con la transcripción, un color por hablante y un reproductor. Haz clic en un párrafo y suena desde ahí; el párrafo que suena se resalta. Arriba hay un buscador que resalta y cuenta las coincidencias. La página se guarda en `~/.transcriptor/vistas/` (no ensucia la carpeta de la reunión) y funciona sin internet. Si el audio ya no está, se lee igual, sin reproductor.

### Buscar en todas

En **Mis transcripciones**, **Buscar en todas…** busca una palabra o frase en todas tus transcripciones, sin importar mayúsculas ni tildes. Cada resultado dice la reunión, el minuto, quién lo dijo y un trozo de la frase; al elegirlo se abre la lectura en ese momento. La lista muestra las más recientes y **Ver más antiguas…** muestra el resto.

### Configuración

- **Clave de Hugging Face:** te guía paso a paso, abre las páginas necesarias, comprueba la clave que pegues y la guarda.
- **Modelos:** muestra qué modelos están en tu computador y cuánto pesan, y deja **Descargar** o **Eliminar** cada uno.
- **Preparar la app:** deja lista la clave y descarga el modelo por defecto y el de hablantes. Aparece en el menú principal mientras falte algo.
- **Transcribir con clic derecho:** agrega «Transcribir con Transcriptor» al clic derecho de un audio o video. Transcribe con tu configuración, sin preguntas, uno tras otro si son varios, y avisa al terminar cada uno.
- **Buscar actualizaciones:** compara tu versión con la última y, si hay una nueva, **Actualizar ahora** la instala sin volver a pegar la línea del instalador. Si el programa está abierto y tu computador no permite reemplazarlo, se abre una ventana aparte que actualiza cuando lo cierras.

### Mientras trabaja

- El computador no se duerme mientras transcribe.
- Si la transcripción tardó más de un minuto, al terminar te avisa con una notificación y un sonido.
- Si aprietas `Ctrl + C` después del primer minuto, te pide apretarlo otra vez para cancelar, así no pierdes el trabajo por accidente.

### Si algo falla

Verás un mensaje simple (por ejemplo, que falta tu clave de Hugging Face, que no hay internet, que el archivo no es de audio o que el disco está lleno). Desde el menú puedes elegir **Ver el detalle**, **Copiar el error** (para pegarlo en un mensaje y pedir ayuda) o **Volver al menú**. El detalle de cada error también queda guardado en la carpeta `~/.transcriptor/errores/`.

## 🔒 Privacidad e internet

El audio y el texto nunca salen de tu computador: todo se procesa ahí. Internet solo se usa para instalar, para descargar cada modelo la primera vez, para bajar videos de YouTube, para revisar si hay versiones nuevas de los modelos y para buscar actualizaciones del programa (solo cuando tú lo pides o, como aviso discreto, una vez por semana). Para que no se conecte ni siquiera para eso, activa **Sin internet** en Configuración (necesitas tener ya descargados los modelos que uses).

## ✅ Qué funciona en cada computador

Transcribir funciona en todos. Reconocer quién habla funciona en casi todos; si tu computador no puede, el programa te lo dice en Configuración. En algunos computadores la transcripción es más lenta: ahí los modelos `small` o `turbo` son una buena opción.

## ⌨️ Comandos (para usuarios avanzados)

Todo lo del menú también se puede hacer con comandos:

```
transcriptor transcribir "ENLACE_O_ARCHIVO"           # transcribir
transcriptor transcribir "ENLACE_O_ARCHIVO" -d        # y reconocer quién habla
transcriptor nombres "mi_audio.blocks.json" -e        # cambiar nombres escuchando a cada hablante
transcriptor nombres "mi_audio.blocks.json" "Ana,Luis"  # cambiar nombres escribiéndolos en orden
```

Con los comandos el archivo se llama como el audio (`mi_audio.blocks.txt`) y no lleva encabezado, igual que antes; el título solo se pide desde el menú. Con `--sin-preguntas` no se hace ninguna pregunta ni se aplica ningún nombre automático (es lo que usan otros programas, como el Grabador).

`transcriptor --help` muestra todas las opciones de cada comando.

La configuración (por ejemplo el token `HF_TOKEN`) se guarda en la carpeta `.transcriptor` dentro de tu carpeta de usuario (`~/.transcriptor/.env`). En esa misma carpeta quedan tu historial, las personas que has nombrado, las voces guardadas, las páginas de lectura (`vistas/`) y los detalles de los errores.

## 👩‍💻 Para trabajar en el código

```
git clone https://github.com/Mxgsr/Transcriptor-pro.git
cd Transcriptor-pro
uv venv
source .venv/bin/activate
uv pip install -e ".[diarizacion]"
```

Para correr los tests (no necesitan red ni modelos):

```
uv pip install -r requirements-dev.txt
python -m pytest
```

## ⚖️ Licencia

MIT
