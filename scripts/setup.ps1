param(
    [string]$RuntimeDirectory = (Join-Path $env:LOCALAPPDATA 'bbuddy/runtime/0.2.0'),
    [string]$DataDirectory = (Join-Path $env:LOCALAPPDATA 'bbuddy/data'),
    [string]$Python = 'py',
    [switch]$Upgrade
)
$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = [System.IO.Path]::GetFullPath($RuntimeDirectory)
$dataDirectory = [System.IO.Path]::GetFullPath($DataDirectory)
$runtimePython = Join-Path $runtimeRoot 'Scripts/python.exe'

if (-not (Test-Path -LiteralPath $runtimePython)) {
    if ($Python -eq 'py') {
        & $Python -3.11 -m venv $runtimeRoot
    } else {
        & $Python -m venv $runtimeRoot
    }
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 is required to create the runtime.' }
}

& $runtimePython -c 'import sys,platform; assert sys.version_info[:2] == (3,11) and platform.system() == "Windows" and platform.machine().lower() in ("amd64","x86_64"), "BBuddy 0.2.0 supports Windows x64 and Python 3.11"'
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python environment.' }

$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$dependencyArguments = @('-m', 'pip', 'install', '-r', (Join-Path $packageRoot 'requirements-runtime.lock'))
if ($Upgrade) { $dependencyArguments += '--upgrade' }
& $runtimePython @dependencyArguments
if ($LASTEXITCODE -ne 0) { throw 'Runtime dependency installation failed.' }

$runtimePackages = @(Get-ChildItem -LiteralPath (Join-Path $packageRoot 'runtime-package') -Filter 'blackboard_lecture_companion-0.2.0-*.whl')
if ($runtimePackages.Count -ne 1) { throw 'Expected exactly one BBuddy 0.2.0 runtime wheel.' }
& $runtimePython -m pip install --no-deps --force-reinstall $runtimePackages[0].FullName
if ($LASTEXITCODE -ne 0) { throw 'BBuddy runtime installation failed.' }

$record = @{
    python = $runtimePython
    version = '0.2.0'
    contract_version = '1.0'
    data_dir = $dataDirectory
}
$record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $packageRoot 'runtime.json') -Encoding utf8
& $runtimePython -m blackboard_companion.cli doctor --json --data-dir $dataDirectory
if ($LASTEXITCODE -ne 0) { throw 'Installed runtime failed doctor.' }
Write-Host 'BBuddy runtime installed. Start a new Codex task if the plugin was just installed or updated.'
