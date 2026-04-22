# Construye build/lambda_bundle.zip para AWS Lambda (wheels manylinux).
# Requiere pip con soporte --platform (Python 3.12).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
Remove-Item -Recurse -Force build/package, build/lambda_bundle.zip -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path build/package -Force | Out-Null
pip install -r requirements.txt -t build/package `
  --platform manylinux2014_x86_64 `
  --implementation cp `
  --python-version 3.12 `
  --only-binary=:all: `
  --no-cache-dir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Copy-Item -Recurse -Force src build/package/src
Get-ChildItem -Path build/package -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path build/lambda_bundle.zip) { Remove-Item build/lambda_bundle.zip -Force }
Push-Location build/package
# tar evita problemas de bloqueo de Compress-Archive con .pyc bajo carga
tar -a -c -f ../lambda_bundle.zip *
if ($LASTEXITCODE -ne 0) { Pop-Location; exit $LASTEXITCODE }
Pop-Location
Get-Item build/lambda_bundle.zip | Format-List Name, Length
