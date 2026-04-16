#!/usr/bin/env bash
# Construye build/lambda_bundle.zip para AWS Lambda (Linux x86_64).
# En macOS, pip por defecto instala wheels de Darwin; numpy/pandas fallan en Lambda con ImportError.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
rm -rf build/package build/lambda_bundle.zip
mkdir -p build/package
pip3 install -r requirements.txt -t build/package \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --no-cache-dir
cp -R src build/package/src
( cd build/package && zip -qr ../lambda_bundle.zip . )
ls -la build/lambda_bundle.zip
