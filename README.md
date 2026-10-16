# 🎙️ Transcriptor Pro

Convierte en texto un audio, un video o un enlace de YouTube. Puede reconocer quién habla en cada momento y corregir la transcripción con una IA que corre en tu computador, sin enviar nada a internet.

Funciona en Mac y en Windows.

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
- Corregir una transcripción con IA.
- Cambiar los nombres de los hablantes.
- Ver tus últimas transcripciones.
- Cambiar la configuración (idioma, modelo, carpetas…).

La transcripción se guarda como un archivo `.blocks.txt`, con la hora de cada párrafo. La primera vez que usas un modelo se descarga solo, así que necesitas internet.

## 🔒 Privacidad e internet

El audio y el texto nunca salen de tu computador: todo se procesa ahí. Internet solo se usa para instalar, para descargar cada modelo la primera vez, para bajar videos de YouTube y para revisar si hay versiones nuevas de los modelos. Para que no se conecte ni siquiera para eso, activa **Sin internet** en Configuración (necesitas tener ya descargados los modelos que uses).

## ✅ Qué funciona en cada computador

| | Mac con chip Apple (M1 o posterior) | Windows | Mac con Intel |
|---|---|---|---|
| Transcribir | ✅ | ✅ | ✅ |
| Reconocer quién habla | ✅ | ✅ | ❌ |
| Corregir con IA | ✅ | ❌ | ❌ |

En Windows y en Mac con Intel la transcripción es más lenta: los modelos `small` o `turbo` son una buena opción.

## ⌨️ Comandos (para usuarios avanzados)

Todo lo del menú también se puede hacer con comandos:

```
transcriptor transcribir "ENLACE_O_ARCHIVO"           # transcribir
transcriptor transcribir "ENLACE_O_ARCHIVO" -d        # y reconocer quién habla
transcriptor corregir "mi_audio.blocks.json"          # corregir con IA
transcriptor nombres "mi_audio.blocks.json" -e        # cambiar nombres escuchando a cada hablante
```

`transcriptor --help` muestra todas las opciones de cada comando.

La configuración (por ejemplo el token `HF_TOKEN`) se guarda en `~/.transcriptor/.env` (en Windows, `C:\Users\TU_USUARIO\.transcriptor\.env`).

## 👩‍💻 Para trabajar en el código

```
git clone https://github.com/Mxgsr/Transcriptor-pro.git
cd Transcriptor-pro
uv venv
source .venv/bin/activate
uv pip install -e ".[diarizacion,correccion]"
```

Para correr los tests (no necesitan red ni modelos):

```
uv pip install -r requirements-dev.txt
python -m pytest
```

## ⚖️ Licencia

MIT
