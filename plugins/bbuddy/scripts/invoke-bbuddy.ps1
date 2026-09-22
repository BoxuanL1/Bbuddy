$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$recordPath = Join-Path $packageRoot 'runtime.json'
if (-not (Test-Path -LiteralPath $recordPath)) { throw 'Run the bundled scripts/setup.ps1 before using BBuddy.' }
$runtime = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
if ($runtime.contract_version -ne '1.0' -or $runtime.version -ne '0.2.0') { throw 'Plugin/runtime versions differ. Run setup again.' }
if (-not (Test-Path -LiteralPath $runtime.python)) { throw 'Runtime interpreter not found. Run setup again.' }
$env:PYTHONUTF8 = '1'
& $runtime.python -m blackboard_companion.cli @args
exit $LASTEXITCODE
