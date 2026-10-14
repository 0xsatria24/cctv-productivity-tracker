param(
    [string]$Config,
    [string]$License,
    [string]$PublicKey,
    [string]$TokenFile
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Install the headless runtime first; see docs/runtime/HEADLESS.md' }
$localSetup = Join-Path $PSScriptRoot 'runtime/headless-local'
$setupRoot = if (Test-Path -LiteralPath (Join-Path $localSetup 'config.json')) { $localSetup } else { $PSScriptRoot }
if (-not $Config) { $Config = Join-Path $setupRoot 'config.json' }
if (-not $License) { $License = Join-Path $setupRoot 'license.json' }
if (-not $PublicKey) { $PublicKey = Join-Path $setupRoot 'vendor-public.pem' }
if (-not $TokenFile) { $TokenFile = Join-Path $setupRoot 'token.txt' }
foreach ($requiredFile in @($Config, $License, $PublicKey)) {
    if (-not (Test-Path -LiteralPath $requiredFile)) { throw "File setup belum tersedia: $requiredFile. Minta config.json, license.json, dan vendor-public.pem dari administrator." }
}
if (-not $env:CCTV_HEADLESS_TOKEN) {
    if (-not (Test-Path -LiteralPath $TokenFile)) {
        & $python -c 'import pathlib,secrets,sys; pathlib.Path(sys.argv[1]).write_text(secrets.token_urlsafe(32))' $TokenFile
        if ($LASTEXITCODE -ne 0) { throw 'Gagal membuat token lokal.' }
    }
    $env:CCTV_HEADLESS_TOKEN = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
    Write-Host "File token untuk halaman koneksi: $TokenFile"
} else {
    Write-Host 'Menggunakan token dari CCTV_HEADLESS_TOKEN. Masukkan token tersebut pada halaman koneksi.'
}
$settings = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
$port = if ($settings.port) { $settings.port } else { 8766 }
$address = "http://127.0.0.1:$port"
Write-Host "Halaman koneksi: $address/"
try {
    $running = Invoke-RestMethod -Uri "$address/api/v1/status" -Headers @{ Authorization = "Bearer $env:CCTV_HEADLESS_TOKEN" } -TimeoutSec 2
} catch { $running = $null }
if ($running -and $running.edition -eq 'headless') {
    Write-Host 'Engine sudah aktif. Buka halaman koneksi dan pilih file token.'
    exit 0
}
Write-Host 'Menjalankan engine. Biarkan jendela ini terbuka; tekan Ctrl+C untuk berhenti.'
$Config = (Resolve-Path -LiteralPath $Config).Path
$License = (Resolve-Path -LiteralPath $License).Path
$PublicKey = (Resolve-Path -LiteralPath $PublicKey).Path
Set-Location -LiteralPath $PSScriptRoot
& $python -m editions.headless --config $Config --license $License --public-key $PublicKey
exit $LASTEXITCODE
