param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$taskCache = Join-Path $projectRoot '.cache'
$taskTemp = Join-Path $taskCache 'tmp'
New-Item -ItemType Directory -Force -Path $taskTemp | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
$env:PIP_CACHE_DIR = Join-Path $taskCache 'pip'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
& $Python -B (Join-Path $projectRoot 'build/verify_package.py')
if ($LASTEXITCODE -ne 0) { throw 'Package integrity check failed' }
$venvPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $venvPython)) {
    & $Python -B -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
& $venvPython -B -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $projectRoot 'runtime/requirements-pc.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $venvPython -B (Join-Path $projectRoot 'runtime/run.py') --help
if ($LASTEXITCODE -ne 0) { throw 'Runtime entry check failed' }
Write-Output 'Setup complete. Start host_monitor/launch_monitor.py; target inference requires the declared licensed target inputs.'
