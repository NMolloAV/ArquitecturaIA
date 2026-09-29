#!/usr/bin/env bash
# Verifica que el entorno esté listo: paquetes, API key y acceso a los modelos.
#
#     ./check.sh
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
fail() { echo "  ✗ $*" >&2; exit 1; }

echo "[1/3] Entorno Python"
[ -x .venv/bin/python ] || fail ".venv no existe — corré ./setup.sh"
.venv/bin/python -c "import google.adk, google.genai" 2>/dev/null || fail "faltan paquetes — corré ./setup.sh"
echo "  ✓ venv y paquetes"

echo "[2/3] API key"
# shellcheck disable=SC1091
source ./env.sh >/dev/null || fail "completá GOOGLE_API_KEY en .env"
echo "  ✓ GOOGLE_API_KEY definida"

echo "[3/3] Acceso a los modelos (una llamada mínima a cada uno)"
.venv/bin/python - <<'PY' || exit 1
import logging, sys
logging.getLogger("google_genai.models").setLevel(logging.ERROR)
from google import genai
c = genai.Client()
bad = 0
for m in ("gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"):
    try:
        r = c.models.generate_content(model=m, contents="Respondé solo: ok")
        print(f"  ✓ {m}: {(r.text or '').strip()[:20]!r}")
    except Exception as e:
        bad += 1
        print(f"  ✗ {m}: {type(e).__name__}: {str(e)[:140]}", file=sys.stderr)
        if "429" in str(e):
            print("    (429 = cuota gratuita agotada: esperá un minuto o ver README, 'Errores frecuentes' #1)", file=sys.stderr)
sys.exit(1 if bad else 0)
PY
echo
echo "Todo listo. Corré: ./run.sh 1"
