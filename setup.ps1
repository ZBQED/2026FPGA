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
$wheelRoot = Join-Path $projectRoot 'install/wheels'
if (Test-Path -LiteralPath $wheelRoot) {
    & $venvPython -B (Join-Path $projectRoot 'install/check_wheels.py')
    if ($LASTEXITCODE -ne 0) { throw 'Offline dependency cache check failed' }
    & $venvPython -B -m pip install --disable-pip-version-check --no-index --find-links $wheelRoot --only-binary=:all: --no-deps --require-hashes -r (Join-Path $projectRoot 'install/requirements-offline.txt')
} else {
    throw 'The bundled install/wheels directory is required'
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $venvPython -B (Join-Path $projectRoot 'runtime/run.py') --help
if ($LASTEXITCODE -ne 0) { throw 'Runtime entry check failed' }
Write-Output 'Setup complete. Start host_monitor/launch_monitor.py; target inference requires the declared licensed target inputs.'
