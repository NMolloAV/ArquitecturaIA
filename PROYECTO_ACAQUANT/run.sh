#!/usr/bin/env bash
# ./run.sh 1        lab 01, comité de renta fija (modo de datos según .env)
# ./run.sh diag     prueba la conexión viva al MCP de AcaQuant
# ./run.sh test     los tests (sin red ni keys)
set -euo pipefail
cd "$(dirname "$0")"
. .venv/bin/activate
set -a; [ -f .env ] && . ./.env; set +a
FILTRO='AuthlibDeprecationWarning|compatible before version 2.0.0|from authlib.jose import ECKey|automatic function calling \(AFC\)'
case "${1:-}" in
  1|comite) python -u -m labs.01_comite_renta_fija 2>&1 | grep -Ev "$FILTRO" ;;
  diag)     shift; python -m puente.diag_conexion "$@" ;;
  test)     python -m pytest -q tests ;;
  *)        echo "uso: ./run.sh 1 | diag [--capturar herramienta k=v ...] | test"; exit 1 ;;
esac
