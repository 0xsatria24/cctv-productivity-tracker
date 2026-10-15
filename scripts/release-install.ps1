param([string]$DataDirectory = (Join-Path $env:LOCALAPPDATA 'CCTVTracker'), [switch]$Offline)
$ErrorActionPreference = 'Stop'
$releaseRoot = $PSScriptRoot
$manifest = Get-Content -Raw -LiteralPath (Join-Path $releaseRoot 'SHA256SUMS.json') | ConvertFrom-Json
foreach ($property in $manifest.PSObject.Properties) {
    $member = [System.IO.Path]::GetFullPath((Join-Path $releaseRoot $property.Name))
    if (-not $member.StartsWith($releaseRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid release manifest path' }
    if ((Get-FileHash -LiteralPath $member -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) { throw "Release file checksum mismatch: $($property.Name)" }
}
$pythonExecutable = Join-Path $releaseRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $pythonExecutable) {
    $deploymentFile = Join-Path $releaseRoot 'deployment.json'
    if (Test-Path -LiteralPath $deploymentFile) {
        $existing = Get-Content -Raw -LiteralPath $deploymentFile | ConvertFrom-Json
        if (Test-Path -LiteralPath $existing.database) {
            & $pythonExecutable -m cctv_tracker.maintenance --database $existing.database backup
            if ($LASTEXITCODE -ne 0) { throw 'Pre-upgrade backup failed; installation stopped' }
        }
    }
} else {
    & py -3.12 -m venv (Join-Path $releaseRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 x64 before running this installer.' }
}
$pipOptions = @('--no-deps')
if ($Offline) { $pipOptions += @('--no-index', '--find-links', (Join-Path $releaseRoot 'wheelhouse')) }
& $pythonExecutable -m pip install @pipOptions -r (Join-Path $releaseRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Runtime installation failed' }
$wheels = @(Get-ChildItem -LiteralPath $releaseRoot -Filter '*.whl')
if ($wheels.Count -ne 1) { throw 'Expected exactly one application wheel' }
& $pythonExecutable -m pip install --no-deps --force-reinstall $wheels[0].FullName
if ($LASTEXITCODE -ne 0) { throw 'Application installation failed' }
if (Test-Path -LiteralPath (Join-Path $releaseRoot 'ui')) {
    $deploymentFile = Join-Path $releaseRoot 'deployment.json'
    if (-not (Test-Path -LiteralPath $deploymentFile)) {
        $dataRoot = [System.IO.Path]::GetFullPath($DataDirectory)
        New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
        $deployment = @{database=(Join-Path $dataRoot 'dashboard-pilot.sqlite3');model_dir=(Join-Path $releaseRoot 'models');ui_dir=(Join-Path $releaseRoot 'ui');port=8765;detector='yolox-openvino';device='GPU'}
        [System.IO.File]::WriteAllText($deploymentFile, ($deployment | ConvertTo-Json), (New-Object System.Text.UTF8Encoding $false))
    }
}
Write-Output 'Installation complete. Place the verified model in models, then launch run.ps1. Configure deployment.json for CPU if no Intel GPU is available.'
