param([string]$Python = "python")

$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & npm run build:frontend
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & $Python -m pip install -r backend/requirements.txt -r packaging/requirements-build.txt
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & $Python -m PyInstaller --noconfirm --clean packaging/Gloss.spec
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Gloss executable: $projectRoot\dist\Gloss.exe"
}
finally {
    Pop-Location
}
