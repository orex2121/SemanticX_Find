param([switch]$SkipModels)

$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

foreach ($name in @('runtime','bootstrap','cache','logs','temp','models','config','indexes')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $name) | Out-Null
}

$env:PYTHONNOUSERSITE = '1'
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot 'cache\pip'
$env:HF_HOME = Join-Path $ProjectRoot 'cache\huggingface'
$env:TORCH_HOME = Join-Path $ProjectRoot 'cache\torch'
$env:TEMP = Join-Path $ProjectRoot 'temp'
$env:TMP = $env:TEMP
$env:PYTORCH_CUDA_ALLOC_CONF = 'expandable_segments:True'

$PythonExe = Join-Path $ProjectRoot 'runtime\python.exe'
$PythonArchive = Join-Path $ProjectRoot 'bootstrap\python-3.12.10-embed-amd64.zip'
$PythonUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'
$PythonSha256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'

try {
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        Write-Host 'Downloading portable Python 3.12.10...'
        Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonArchive
        $actualHash = (Get-FileHash -LiteralPath $PythonArchive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $PythonSha256) { throw 'Portable Python checksum mismatch.' }
        Expand-Archive -LiteralPath $PythonArchive -DestinationPath (Join-Path $ProjectRoot 'runtime') -Force
        "python312.zip`r`n.`r`nLib\site-packages`r`n..`r`nimport site`r`n" | Set-Content -LiteralPath (Join-Path $ProjectRoot 'runtime\python312._pth') -Encoding ASCII
    }

    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'runtime\Lib\site-packages\pip'))) {
        Write-Host 'Installing pip...'
        $GetPip = Join-Path $ProjectRoot 'bootstrap\get-pip.py'
        Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $GetPip
        & $PythonExe $GetPip --no-warn-script-location
        if ($LASTEXITCODE -ne 0) { throw 'pip installation failed.' }
    }

    & $PythonExe -m pip install --upgrade --no-warn-script-location pip
    if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }

    $HasNvidia = $null -ne (Get-Command 'nvidia-smi.exe' -ErrorAction SilentlyContinue)
    $TorchIndex = if ($HasNvidia) { 'https://download.pytorch.org/whl/cu130' } else { 'https://download.pytorch.org/whl/cpu' }
    Write-Host ($(if ($HasNvidia) { 'NVIDIA GPU detected. Installing CUDA PyTorch...' } else { 'NVIDIA GPU not detected. Installing CPU PyTorch...' }))
    & $PythonExe -m pip install --upgrade --no-warn-script-location torch torchvision --index-url $TorchIndex
    if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed.' }

    Write-Host 'Installing SemanticX Find libraries...'
    & $PythonExe -m pip install --upgrade --no-warn-script-location -r (Join-Path $ProjectRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Application dependency installation failed.' }

    $SettingsPath = Join-Path $ProjectRoot 'config\settings.json'
    if (-not (Test-Path -LiteralPath $SettingsPath)) {
        $InitialSettings = '{"language":"en","performance_preset":"basic","index_workers":4,"batch_size":64,"index_queue_size":32,"provider":"gemma","vision":true,"ocr":true}'
        [System.IO.File]::WriteAllText($SettingsPath, $InitialSettings, [System.Text.UTF8Encoding]::new($false))
    }

    if (-not $SkipModels) {
        Write-Host 'Downloading and verifying EmbeddingGemma 2...'
        & $PythonExe -m semanticx.cli download-model
        if ($LASTEXITCODE -ne 0) { throw 'EmbeddingGemma 2 download failed.' }

        Write-Host 'Downloading and verifying OCR models...'
        & $PythonExe -c "from semanticx.paths import bootstrap; bootstrap(); from semanticx.ocr import OCRManager; OCRManager().download(print)"
        if ($LASTEXITCODE -ne 0) { throw 'OCR model download failed.' }
    }

    Write-Host 'Validating the installation...'
    & $PythonExe -c "from semanticx.paths import bootstrap; bootstrap(); import PySide6, torch, sentence_transformers, rapidocr; print('SemanticX Find runtime is ready. PyTorch:', torch.__version__, 'CUDA:', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) { throw 'Installation validation failed.' }
}
catch {
    Write-Host ''
    Write-Host $_ -ForegroundColor Red
    exit 1
}
