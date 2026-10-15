param(
    [ValidateSet('Install','Uninstall')][string]$Action = 'Install',
    [ValidatePattern('^[A-Za-z][A-Za-z0-9_-]{2,60}$')][string]$ServiceName = 'CCTVWorkspace',
    [string]$InstallDirectory = $PSScriptRoot,
    [System.Management.Automation.PSCredential]$Credential
)
$ErrorActionPreference = 'Stop'
$installRoot = (Resolve-Path -LiteralPath $InstallDirectory).Path
if ($Action -eq 'Uninstall') {
    $registered = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
    $expectedPython = Join-Path $installRoot '.venv\Scripts\python.exe'
    if (-not $registered -or -not $registered.PathName.StartsWith(('"' + $expectedPython + '" -m cctv_tracker.windows_service --config '), [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Service does not belong to this installation; no changes made.' }
    $existing = Get-Service -Name $ServiceName -ErrorAction Stop
    if ($existing.Status -ne 'Stopped') { Stop-Service -Name $ServiceName -ErrorAction Stop }
    & sc.exe delete $ServiceName
    if ($LASTEXITCODE -ne 0) { throw 'Service removal failed' }
    Write-Output 'Service removed. Application data and backups were preserved.'
    exit 0
}
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) { throw 'Service already exists. Uninstall it explicitly before replacing.' }
if (-not $Credential) { $Credential = Get-Credential -Message 'Use the same Windows account that owns the camera configuration and DPAPI secrets.' }
$pythonExecutable = Join-Path $installRoot '.venv\Scripts\python.exe'
$deploymentPath = Join-Path $installRoot 'deployment.json'
if (-not (Test-Path -LiteralPath $pythonExecutable) -or -not (Test-Path -LiteralPath $deploymentPath)) { throw 'Run install.ps1 first.' }
$deployment = Get-Content -Raw -LiteralPath $deploymentPath | ConvertFrom-Json
if (-not [System.IO.Path]::IsPathRooted($deployment.database)) { throw 'Deployment database must be an absolute path for service installation.' }
$serviceConfig = Join-Path $installRoot 'service.json'
$config = @{
    name = $ServiceName
    command = @($pythonExecutable, '-m', 'cctv_tracker.deployment', '--config', $deploymentPath)
    state_dir = Join-Path (Split-Path -Parent $deployment.database) 'supervisor'
    health_url = "http://127.0.0.1:$($deployment.port)/health"
    working_directory = $installRoot
}
[System.IO.File]::WriteAllText($serviceConfig, ($config | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding $false))
$binary = '"' + $pythonExecutable + '" -m cctv_tracker.windows_service --config "' + $serviceConfig + '"'
New-Service -Name $ServiceName -DisplayName 'CCTV Workspace Monitoring' -Description 'Local CCTV engine with bounded recovery and persistent camera sessions.' -BinaryPathName $binary -StartupType Automatic -Credential $Credential
Write-Output "Service installed. Stop any manually running dashboard, then run: Start-Service $ServiceName"
Write-Output 'The service account needs Log on as a service permission and access to this installation, model, and data directory.'
