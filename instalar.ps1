# Instala Transcriptor Pro en Windows. Abre PowerShell y pega:
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/Mxgsr/Transcriptor-pro/main/instalar.ps1 | iex"
#
# Para actualizar a la última versión, vuelve a pegar la misma línea.
# Instala uv (el gestor de Python) si falta, y con él Transcriptor y todo lo que necesita.
# ffmpeg viene incluido. No hace falta clonar el proyecto ni crear un .venv.
$ErrorActionPreference = "Stop"

$Paquete = "transcriptor-pro[diarizacion,correccion] @ https://github.com/Mxgsr/Transcriptor-pro/archive/refs/heads/main.zip"
$Config = Join-Path $HOME ".transcriptor\.env"

function Paso($texto) {
    Write-Host ""
    Write-Host "==> $texto" -ForegroundColor Magenta
}

# 1. uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $env:Path = "$HOME\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Paso "Instalando uv (el gestor de Python)"
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    }
}

# 2. Transcriptor. Los extras que no sirven en Windows (la corrección con IA) se saltan solos.
Paso "Instalando Transcriptor Pro (la primera vez tarda unos minutos)"
uv tool install --force --upgrade --reinstall-package transcriptor-pro --python 3.11 $Paquete
if ($LASTEXITCODE -ne 0) {
    Write-Host "No se pudo instalar Transcriptor Pro (ver el error de arriba)." -ForegroundColor Red
    return
}

# 3. Que el comando `transcriptor` se encuentre en las ventanas nuevas
# (try: en Windows PowerShell, redirigir lo que escribe un programa puede contar como error)
try { uv tool update-shell *> $null } catch { }

# 4. Token de Hugging Face, para identificar quién habla (opcional)
$TieneToken = (Test-Path $Config) -and (Select-String -Path $Config -Pattern '^HF_TOKEN=' -Quiet)
if (-not $TieneToken) {
    Paso "Identificar quién habla (opcional)"
    Write-Host "Necesita un token gratuito de Hugging Face: https://huggingface.co/settings/tokens"
    Write-Host "y aceptar las condiciones del modelo en: https://huggingface.co/pyannote/speaker-diarization-community-1"
    $Token = Read-Host "Pega tu token (o Enter para saltarlo)"
    if ($Token) {
        New-Item -ItemType Directory -Force -Path (Split-Path $Config) | Out-Null
        # Sin BOM: python-dotenv no leería bien la primera línea
        [System.IO.File]::AppendAllText($Config, "HF_TOKEN=$($Token.Trim())`n")
        Write-Host "Guardado en $Config"
    }
}

Paso "Listo"
Write-Host "Abre una ventana nueva de PowerShell y escribe: transcriptor"
