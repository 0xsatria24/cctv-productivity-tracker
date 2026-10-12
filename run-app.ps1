param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [string]$DatabasePath = '',
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$workspacePath = $PSScriptRoot
$pythonExecutable = Join-Path $workspacePath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) { throw 'Virtual environment belum tersedia. Ikuti docs/runtime/README.md.' }
if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
    $DatabasePath = Join-Path $env:LOCALAPPDATA 'CCTVTracker\dashboard-pilot.sqlite3'
}
if (-not [System.IO.Path]::IsPathRooted($DatabasePath)) {
    $DatabasePath = Join-Path $workspacePath $DatabasePath
}
$DatabasePath = [System.IO.Path]::GetFullPath($DatabasePath)
if (-not $SkipBuild) {
    Push-Location (Join-Path $workspacePath 'prototype')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Build dashboard gagal.' }
    } finally { Pop-Location }
}
Set-Location -LiteralPath $workspacePath
$env:MPLCONFIGDIR = Join-Path (Split-Path -Parent $DatabasePath) 'matplotlib'
& $pythonExecutable -m cctv_tracker --database $DatabasePath dashboard --port $Port
exit $LASTEXITCODE
