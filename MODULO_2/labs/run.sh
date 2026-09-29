#!/usr/bin/env bash
# Corre los ejercicios del Módulo 2 con el venv y la API key de .env.
# Requiere haber corrido ./setup.sh antes.
#
#     ./run.sh {1|2|3|simple|compleja}
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

[ -d .venv ] || { echo "No existe .venv — corré ./setup.sh primero." >&2; exit 1; }
# shellcheck disable=SC1091
source ./env.sh >/dev/null
export PYTHONWARNINGS="ignore::UserWarning,ignore::DeprecationWarning"  # ruido de ADK

case "${1:-}" in
  1) python ejercicio_1_agente_reclamos.py ;;
  2) python ejercicio_2_pipeline_paralelo.py ;;
  3) python ejercicio_3_routing_dinamico.py ;;
  simple|compleja) python demo_dos_modelos.py "$1" ;;
  *)
    cat >&2 <<USO
Uso: ./run.sh {1|2|3|simple|compleja}

  1         Ejercicio 1 — agente de reclamos con gate de aprobación   (~6-18 llamadas)
  2         Ejercicio 2 — pipeline paralelo vs. secuencial            (~18 llamadas, el que más cuota gasta)
  3         Ejercicio 3 — routing dinámico de modelos                 (~10 llamadas, ~2 min)
  simple    Bonus — barato vs. caro en una clasificación              (2 llamadas)
  compleja  Bonus — barato vs. caro en una decisión de negocio        (2 llamadas)
USO
    exit 1 ;;
esac
