#!/usr/bin/env bash
# Configura las variables de entorno para correr los ejemplos con una API key de
# Google AI Studio (Gemini API).
#
# Uso (con `source`, para que las variables queden en tu shell):
#   export GOOGLE_API_KEY="tu-api-key"   # opcional: si no está, te la pide
#   source setup_env.sh
#
# Generá tu API key gratis en: https://aistudio.google.com/apikey
# La key nunca se guarda en disco: solo vive en las variables de tu sesión de shell.

export GOOGLE_GENAI_USE_VERTEXAI=FALSE
export ADK_MODEL="${ADK_MODEL:-gemini-2.5-flash}"

if [ -z "${GOOGLE_API_KEY:-}" ] && [ -n "${GEMINI_API_KEY:-}" ]; then
  export GOOGLE_API_KEY="$GEMINI_API_KEY"
fi

if [ -z "${GOOGLE_API_KEY:-}" ]; then
  if [ -t 0 ]; then
    read -rsp "Pegá tu API key de Google AI Studio (no se muestra al escribir): " GOOGLE_API_KEY
    echo ""
    export GOOGLE_API_KEY
  fi
fi

if [ -z "${GOOGLE_API_KEY:-}" ]; then
  echo "❌ Falta GOOGLE_API_KEY. Generala en https://aistudio.google.com/apikey y corré:"
  echo "   export GOOGLE_API_KEY=\"tu-api-key\""
  return 1 2>/dev/null || exit 1
fi

echo "✅ Variables de entorno configuradas:"
echo "   GOOGLE_GENAI_USE_VERTEXAI = $GOOGLE_GENAI_USE_VERTEXAI"
echo "   GOOGLE_API_KEY            = ${GOOGLE_API_KEY:0:4}…(oculta)"
echo "   ADK_MODEL                 = $ADK_MODEL"
