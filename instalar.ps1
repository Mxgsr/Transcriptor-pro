# Instala Transcriptor Pro en Windows. Abre PowerShell y pega:
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/Mxgsr/Transcriptor-pro/main/instalar.ps1 | iex"
#
# Para actualizar a la última versión, vuelve a pegar la misma línea.
# Instala uv (el gestor de Python) si falta, y con él Transcriptor y todo lo que necesita.
# ffmpeg viene incluido. No hace falta clonar el proyecto ni crear un .venv.
$ErrorActionPreference = "Stop"

$Zip = "https://github.com/Mxgsr/Transcriptor-pro/archive/refs/heads/main.zip"
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
#    El proyecto lo baja PowerShell (que ya llegó a GitHub para bajar este instalador) y uv lo
#    instala desde ese archivo. Más tiempo de espera que el de fábrica (30 s), por si la conexión
#    es lenta: después vienen paquetes grandes como PyTorch.
Paso "Descargando Transcriptor Pro"
$Temporal = Join-Path ([System.IO.Path]::GetTempPath()) ("transcriptor-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $Temporal | Out-Null
$Archivo = Join-Path $Temporal "transcriptor-pro.zip"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"  # la barra de progreso hace muy lenta la descarga
Invoke-WebRequest -UseBasicParsing -Uri $Zip -OutFile $Archivo

Paso "Instalando Transcriptor Pro (la primera vez tarda unos minutos)"
if (-not $env:UV_HTTP_TIMEOUT) { $env:UV_HTTP_TIMEOUT = "300" }
$Paquete = "transcriptor-pro[diarizacion,correccion] @ " + ([System.Uri]$Archivo).AbsoluteUri
uv tool install --force --upgrade --reinstall-package transcriptor-pro --python 3.11 $Paquete
$Resultado = $LASTEXITCODE
Remove-Item -Recurse -Force $Temporal -ErrorAction SilentlyContinue
if ($Resultado -ne 0) {
    Write-Host ""
    Write-Host "No se pudo instalar: uv no logró descargar lo que necesita (mira el error de arriba)." -ForegroundColor Red
    Write-Host "Revisa la conexión a internet (si usas una VPN, prueba sin ella) y vuelve a pegar"
    Write-Host "la misma línea: lo que ya se descargó no se vuelve a bajar."
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
Write-Host "Cierra todas las ventanas de PowerShell, abre una nueva y escribe: transcriptor"
