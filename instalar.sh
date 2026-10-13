#!/bin/sh
# Instala Transcriptor Pro en un Mac (también sirve en Linux). En la Terminal, pega:
#
#   curl -LsSf https://raw.githubusercontent.com/Mxgsr/Transcriptor-pro/main/instalar.sh | sh
#
# Para actualizar a la última versión, vuelve a pegar la misma línea.
# Instala uv (el gestor de Python) si falta, y con él Transcriptor y todo lo que necesita.
# ffmpeg viene incluido. No hace falta clonar el proyecto ni crear un .venv.
set -eu

ZIP="https://github.com/Mxgsr/Transcriptor-pro/archive/refs/heads/main.zip"
CONFIG="$HOME/.transcriptor/.env"

paso() { printf '\n\033[1;35m==>\033[0m \033[1m%s\033[0m\n' "$1"; }

# 1. uv
if ! command -v uv >/dev/null 2>&1; then
    if [ -x "$HOME/.local/bin/uv" ]; then
        PATH="$HOME/.local/bin:$PATH"
    else
        paso "Instalando uv (el gestor de Python)"
        curl -LsSf https://astral.sh/uv/install.sh | sh
        PATH="$HOME/.local/bin:$PATH"
    fi
fi

# 2. Transcriptor. Los extras que no sirven en este computador se saltan solos
#    (la corrección con IA solo se instala en Mac con chip Apple).
#    El proyecto lo baja curl (el mismo que bajó este instalador, así que sabemos que llega a GitHub)
#    y uv lo instala desde ese archivo. Más tiempo de espera que el de fábrica (30 s), por si la
#    conexión es lenta: después vienen paquetes grandes como PyTorch.
paso "Descargando Transcriptor Pro"
TEMPORAL="$(mktemp -d)"
trap 'rm -rf "$TEMPORAL"' EXIT
curl -LsSf --retry 3 --connect-timeout 30 -o "$TEMPORAL/transcriptor-pro.zip" "$ZIP"

paso "Instalando Transcriptor Pro (la primera vez tarda unos minutos)"
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}"
if ! uv tool install --force --upgrade --reinstall-package transcriptor-pro --python 3.11 \
        "transcriptor-pro[diarizacion,correccion] @ file://$TEMPORAL/transcriptor-pro.zip"; then
    echo ""
    echo "No se pudo instalar: uv no logró descargar lo que necesita (mira el error de arriba)."
    echo "Revisa la conexión a internet (si usas una VPN, prueba sin ella) y vuelve a pegar"
    echo "la misma línea: lo que ya se descargó no se vuelve a bajar."
    exit 1
fi

# 3. Que el comando `transcriptor` se encuentre en las terminales nuevas
uv tool update-shell >/dev/null 2>&1 || true

# 4. Token de Hugging Face, para identificar quién habla (opcional)
es_mac_intel=false
if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" != "arm64" ]; then
    es_mac_intel=true
fi
if [ "$es_mac_intel" = false ] && ! grep -qs '^HF_TOKEN=' "$CONFIG" && (: </dev/tty) 2>/dev/null; then
    paso "Identificar quién habla (opcional)"
    echo "Necesita un token gratuito de Hugging Face: https://huggingface.co/settings/tokens"
    echo "y aceptar las condiciones del modelo en: https://huggingface.co/pyannote/speaker-diarization-community-1"
    printf "Pega tu token (o Enter para saltarlo): "
    TOKEN=""
    read -r TOKEN </dev/tty || TOKEN=""
    if [ -n "$TOKEN" ]; then
        mkdir -p "$(dirname "$CONFIG")"
        printf 'HF_TOKEN=%s\n' "$TOKEN" >>"$CONFIG"
        chmod 600 "$CONFIG"
        echo "Guardado en $CONFIG"
    fi
fi

paso "Listo"
echo "Cierra la Terminal por completo (Cmd+Q), ábrela de nuevo y escribe: transcriptor"
