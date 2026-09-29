#!/usr/bin/env bash
# Carga .env en la shell actual y activa el venv. Se usa con `source`:
#
#     source ./env.sh
_D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$_D/.env" ]; then
  echo "No existe .env — corré ./setup.sh y pegá tu GOOGLE_API_KEY." >&2
  return 1 2>/dev/null || exit 1
fi
set -a
# shellcheck disable=SC1091
source "$_D/.env"
set +a
[ -f "$_D/.venv/bin/activate" ] && source "$_D/.venv/bin/activate"
if [ -z "${GOOGLE_API_KEY:-}" ] || [ "$GOOGLE_API_KEY" = "tu-api-key" ]; then
  echo "GOOGLE_API_KEY sin completar en .env" >&2
  unset _D; return 1 2>/dev/null || exit 1
fi
echo "Entorno: AI Studio (API key cargada)"
unset _D
