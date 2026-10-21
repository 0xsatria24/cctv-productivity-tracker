param(
    [ValidateRange(0.016666667,72)][double]$DurationHours = 24,
    [string]$Url = 'http://127.0.0.1:8767',
    [string]$OutputDirectory = '',
    [ValidateRange(0,2147483647)][int]$ProcessId = 0,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Project .venv not found. Create the Python 3.12 environment and install .[vision,openvino,performance] first.'
}
if (-not $OutputDirectory) {
    $runStamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss-fff')
    $OutputDirectory = Join-Path $projectRoot "runtime/manual-soak-$runStamp"
}
$savedPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    $runnerArguments = @((Join-Path $PSScriptRoot 'soak_dashboard.py'), '--url', $Url,
                        '--output', $OutputDirectory, '--hours', $DurationHours.ToString([Globalization.CultureInfo]::InvariantCulture))
    if ($ProcessId -gt 0) { $runnerArguments += @('--pid', "$ProcessId") }
    if ($ValidateOnly) { $runnerArguments += '--dry-run' }
    & $pythonExecutable @runnerArguments
    if ($LASTEXITCODE -ne 0) { throw "Manual test ended with exit code $LASTEXITCODE. Inspect result.json in $OutputDirectory." }
} finally {
    $env:PYTHONPATH = $savedPythonPath
}
