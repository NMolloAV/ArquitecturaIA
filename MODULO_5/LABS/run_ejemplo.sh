#!/usr/bin/env bash
# Ejecuta uno de los 3 ejemplos integradores de ADK 2.0, mostrando la salida
# de consola completa y con separadores claros.
#
# Uso:
#   ./run_ejemplo.sh                # menú interactivo
#   ./run_ejemplo.sh 1              # corre directo el Caso 1
#   ./run_ejemplo.sh onboarding     # también acepta nombre corto
#
# Antes de correr, configurá tu API key de Google AI Studio (ver README.md):
#   export GOOGLE_API_KEY="tu-api-key"
#   source setup_env.sh

set -euo pipefail
cd "$(dirname "$0")"

CASOS=(
  "01_onboarding_crediticio/onboarding_workflow.py:Caso 1 · Onboarding y Scoring Crediticio (Graph Workflow)"
  "02_incidencias_soc/soc_swarm_workflow.py:Caso 2 · Mesa de Respuesta a Incidentes SOC (Collaborative/Swarm)"
  "03_auditoria_licitaciones/auditoria_dynamic_workflow.py:Caso 3 · Auditoría de Licitaciones (Dynamic Workflow)"
)

elegir_por_alias() {
  case "$1" in
    1|onboarding|credito|crediticio) echo 0 ;;
    2|soc|incidencias|incidentes) echo 1 ;;
    3|auditoria|licitaciones) echo 2 ;;
    *) echo -1 ;;
  esac
}

mostrar_menu() {
  echo "" >&2
  echo "===================================================================" >&2
  echo " Ejemplos completos ADK 2.0 — Módulo 5" >&2
  echo "===================================================================" >&2
  local i=1
  for entrada in "${CASOS[@]}"; do
    echo "  $i) ${entrada#*:}" >&2
    i=$((i + 1))
  done
  echo "  0) Salir" >&2
  echo "===================================================================" >&2
  read -rp "Elegí un caso [0-3]: " opcion
  echo "$opcion"
}

correr_caso() {
  local idx="$1"
  local entrada="${CASOS[$idx]}"
  local script="${entrada%%:*}"
  local titulo="${entrada#*:}"

  # Si no hay API key en el entorno, cargamos setup_env.sh (que la pide por
  # teclado) para que esto funcione sin ese paso manual.
  if [ -z "${GOOGLE_API_KEY:-}" ] && [ -z "${GEMINI_API_KEY:-}" ]; then
    echo "⚠️  No detecté GOOGLE_API_KEY — cargando setup_env.sh..."
    # shellcheck disable=SC1091
    source ./setup_env.sh || return 1
    echo ""
  fi

  echo ""
  echo "###################################################################"
  echo "### $titulo"
  echo "### Script: $script"
  echo "###################################################################"
  echo ""

  # authlib re-registra su propio filtro "always" al importarse, así que
  # PYTHONWARNINGS no alcanza para silenciarlo: se filtra por texto, junto
  # con el aviso informativo de google-genai sobre automatic function calling.
  python3 -u "$script" 2>&1 | grep -v \
    -e "AuthlibDeprecationWarning" \
    -e "It will be compatible before version 2.0.0." \
    -e "from authlib.jose import ECKey" \
    -e "Direct use of automatic function calling (AFC)" || true
  local status=${PIPESTATUS[0]}

  echo ""
  echo "-------------------------------------------------------------------"
  if [ $status -eq 0 ]; then
    echo "✅ $titulo — finalizó OK"
  else
    echo "❌ $titulo — terminó con error (código $status)"
  fi
  echo "-------------------------------------------------------------------"
  return $status
}

# Modo directo: ./run_ejemplo.sh 1 | onboarding | etc.
if [ $# -ge 1 ]; then
  idx=$(elegir_por_alias "$1")
  if [ "$idx" -lt 0 ]; then
    echo "No reconozco '$1'. Usá 1/2/3 o onboarding/soc/auditoria."
    exit 1
  fi
  correr_caso "$idx"
  exit $?
fi

# Modo interactivo: menú en loop
while true; do
  opcion=$(mostrar_menu)
  if [ "$opcion" = "0" ]; then
    echo "Chau 👋"
    exit 0
  fi
  idx=$(elegir_por_alias "$opcion")
  if [ "$idx" -lt 0 ]; then
    echo "Opción inválida."
    continue
  fi
  correr_caso "$idx" || true
done
