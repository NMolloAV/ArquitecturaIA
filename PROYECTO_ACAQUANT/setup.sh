#!/usr/bin/env bash
# Crea el .venv, instala requirements.txt y arma .env desde .env.example (una sola vez).
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo "Creé .env: pegá tu GOOGLE_API_KEY ahí."; }
python -m pytest -q tests && echo "✅ listo: ./run.sh 1"
