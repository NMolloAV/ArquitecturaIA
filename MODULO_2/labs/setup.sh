#!/usr/bin/env bash
# Prepara el entorno de los labs del Módulo 2 (una sola vez):
# crea .venv, instala dependencias y crea .env si no existe.
#
#     ./setup.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -d .venv ]; then
  echo "Creando entorno virtual (.venv)..."
  python3 -m venv .venv
fi

echo "Instalando dependencias..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env creado. Editalo y pegá tu GOOGLE_API_KEY (https://aistudio.google.com/apikey)."
else
  echo ".env ya existe — no se tocó."
fi

echo
echo "Setup listo. Siguiente paso:  ./check.sh"
