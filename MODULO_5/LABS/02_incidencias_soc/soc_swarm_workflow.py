"""Caso 2: Mesa de Respuesta a Incidentes SOC (Ciberseguridad)

Topología: Collaborative / Swarm Workflow Canónico (ADK 2.0)
Técnicas ADK 2.0 Integradas:
1. mode="single_turn" (L3a): Especialistas forense y firewall como herramientas tipadas de una sola pasada.
2. ReAct real (Action -> Observation): forense_logs y especialista_firewall tienen tools=[...]
   de verdad — no se les pide que "simulen" el resultado, llaman a una función Python real
   (_consultar_logs_raw, _aplicar_regla_firewall) y razonan sobre su observación antes de
   responder. ADK combina tools= y output_schema= en el mismo call vía un workaround interno
   (ver _output_schema_processor.py) cuando el modelo no soporta ambos nativamente.
3. disallow_transfer_* (L3a): Previene transferencias de sesión parásitas forzando auto-retorno al coordinador.
4. mode="task" (L3b): Subagente interactivo de Oficial de Seguridad con finish_task y output_schema.
5. Schemas Pydantic: SpecialistInput, SpecialistResponse, AutorizacionBloqueo.
"""
import asyncio
import json
import logging
import os
import sys
import time
import warnings
from typing import Literal
from pydantic import BaseModel, Field

# Silencia avisos de features experimentales de ADK, el deprecation de authlib y el
# log de partes no-texto (function_call) de google-genai. Debe ir antes de importar google.adk.
warnings.filterwarnings("ignore", message=r"\[EXPERIMENTAL\]", category=UserWarning)
try:
    import authlib.deprecate  # registra su filtro "always"; hay que importarlo antes del nuestro
except ImportError:
    pass
warnings.filterwarnings("ignore", message=r"authlib\.jose module is deprecated")
logging.getLogger("google_genai.types").setLevel(logging.ERROR)

# Autenticación: API key de Google AI Studio (https://aistudio.google.com/apikey).
# Se fuerza el modo "API key" (no Vertex AI) aunque tengas otra configuración en el shell.
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"
if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
    sys.exit(
        "Falta la API key de Google AI Studio.\n"
        "  Generala en https://aistudio.google.com/apikey y exportala con:\n"
        "    export GOOGLE_API_KEY=\"tu-api-key\"\n"
        "  (o corré `source setup_env.sh`, que te la pide)."
    )

from google.adk import Agent, Runner
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps import App
from google.adk.sessions import InMemorySessionService
from google.genai import types

MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")

# -------------------------------------------------------------------
# 1. ESQUEMAS PYDANTIC (Contratos Tipados de Entrada / Salida)
# -------------------------------------------------------------------
class SpecialistInput(BaseModel):
    ip_origen: str = Field(description="Dirección IP sospechosa a auditar o bloquear")
    accion_requerida: str = Field(description="Descripción de la tarea forense o de mitigación")

class DiagnosticoAmenaza(BaseModel):
    nivel_riesgo: Literal["BAJO", "MEDIO", "ALTO", "CRITICO"] = Field(description="Nivel de severidad")
    hallazgo: str = Field(description="Resumen del patrón de ataque detectado en logs")
    requiere_bloqueo: bool = Field(description="Indica si debe bloquearse en Firewall")

class BloqueoConfirmado(BaseModel):
    regla_id: str = Field(description="Identificador de la regla creada en Firewall")
    ip_bloqueada: str = Field(description="IP aislada en el perímetro")
    ttl_horas: int = Field(description="Tiempo de vida en horas del bloqueo (expiración)")

class AutorizacionBloqueo(BaseModel):
    oficial_firmante: str = Field(description="Nombre o ID del oficial SOC que autoriza")
    motivo_aprobacion: str = Field(description="Justificación formal de la contención")
    confirmado: bool = Field(description="True si la acción de bloqueo fue autorizada")

# -------------------------------------------------------------------
# 2. SUBAGENTE 1: FORENSE DE LOGS (L3a - mode="single_turn" + ReAct real)
# -------------------------------------------------------------------
def _consultar_logs_raw(ip: str) -> str:
    """Consulta el log crudo de accesos fallidos de una IP en el endpoint de login.

    Usá esta herramienta para obtener la evidencia real antes de emitir un
    diagnóstico — no inventes el resultado de la consulta.
    """
    return f"LOG_403: 1,450 peticiones fallidas desde {ip} hacia /api/v1/login en últimos 5 min."

forense_agent = Agent(
    name="forense_logs",
    model=MODEL,
    mode="single_turn",                       # ★ L3a: El subagente actúa como herramienta tipada
    tools=[_consultar_logs_raw],              # ★ ReAct real: Action -> Observation antes de responder
    input_schema=SpecialistInput,
    output_schema=DiagnosticoAmenaza,
    disallow_transfer_to_parent=True,         # ★ L3a: Evita handoff accidental al parent
    disallow_transfer_to_peers=True,          # ★ L3a: Evita handoff accidental a peers
    description="Especialista forense de logs. Audita eventos sospechosos de una IP y determina el nivel de riesgo.",
    instruction=(
        "Sos un analista forense SOC. Para la IP dada, llamá SIEMPRE a la herramienta "
        "_consultar_logs_raw con esa IP para obtener el registro real de accesos fallidos — "
        "nunca inventes ni simules ese resultado. Con la observación de la herramienta en mano, "
        "razoná el nivel de riesgo y emití un DiagnosticoAmenaza estructurado citando la cifra "
        "exacta de peticiones fallidas que devolvió la herramienta."
    )
)

# -------------------------------------------------------------------
# 3. SUBAGENTE 2: ESPECIALISTA FIREWALL (L3a - mode="single_turn" + ReAct real)
# -------------------------------------------------------------------
def _aplicar_regla_firewall(ip: str, ttl_horas: int) -> str:
    """Aplica una regla de bloqueo perimetral real sobre una IP en el firewall.

    Usá esta herramienta para ejecutar el bloqueo — no inventes el ID de regla
    ni confirmes el bloqueo sin haberla llamado.
    """
    regla_id = f"FW-RULE-{abs(hash(ip)) % 9000 + 1000}"
    return f"Regla {regla_id} aplicada: IP {ip} bloqueada perimetralmente por {ttl_horas}h."

firewall_agent = Agent(
    name="especialista_firewall",
    model=MODEL,
    mode="single_turn",                       # ★ L3a: El subagente actúa como herramienta tipada
    tools=[_aplicar_regla_firewall],          # ★ ReAct real: Action -> Observation antes de responder
    input_schema=SpecialistInput,
    output_schema=BloqueoConfirmado,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    description="Especialista de firewall. Aplica reglas perimetrales con TTL explícito.",
    instruction=(
        "Sos un administrador de firewall. Llamá SIEMPRE a la herramienta _aplicar_regla_firewall "
        "con la IP indicada y ttl_horas=24 para ejecutar el bloqueo real — nunca inventes el "
        "regla_id ni confirmes el bloqueo sin haber llamado a la herramienta. Con la observación "
        "de la herramienta en mano, emití un BloqueoConfirmado citando el regla_id exacto que "
        "devolvió."
    )
)

# -------------------------------------------------------------------
# 4. SUBAGENTE 3: OFICIAL DE SEGURIDAD (L3b - mode="task")
# -------------------------------------------------------------------
oficial_seguridad_task = Agent(
    name="oficial_seguridad_task",
    model=MODEL,
    mode="task",                              # ★ L3b: Subrutina conversacional con finish line tipada
    output_schema=AutorizacionBloqueo,        # ★ L3b: Obliga a llamar a finish_task(AutorizacionBloqueo)
    description="Oficial de seguridad responsable de autorizar bloqueos perimetrales.",
    instruction=(
        "Sos el Oficial de Seguridad del SOC. Tu rol es registrar la autorización formal de bloqueo.\n"
        "Cuando recibas la solicitud con el motivo de bloqueo, finalizá la tarea llamando a finish_task "
        "con AutorizacionBloqueo(oficial_firmante='SecOps_Lead_01', motivo_aprobacion=..., confirmado=True)."
    )
)

# -------------------------------------------------------------------
# 5. COORDINADOR SWARM: COMANDANTE DE INCIDENTES (Root Orchestrator)
# -------------------------------------------------------------------
root_supervisor = Agent(
    name="comandante_incidente_soc",
    model=MODEL,
    sub_agents=[forense_agent, firewall_agent, oficial_seguridad_task],
    instruction=(
        "Sos el Comandante de Incidentes del SOC. Tu misión es liderar la respuesta operativa ante alertas "
        "coordinando a tus especialistas según la gravedad del incidente.\n\n"
        "Especialistas disponibles:\n"
        "- forense_logs: Audita eventos de acceso y determina el nivel de riesgo técnico.\n"
        "- oficial_seguridad_task: Valida y autoriza formalmente bloqueos perimetrales ante amenazas críticas.\n"
        "- especialista_firewall: Aplica reglas de bloqueo en el firewall perimetral una vez autorizado.\n\n"
        "Protocolo operativo:\n"
        "• Evaluá la alerta y consultá a forense_logs para auditar el tráfico sospechoso.\n"
        "• Si el diagnóstico confirma una amenaza crítica que requiere bloqueo, solicitá la autorización formal a oficial_seguridad_task.\n"
        "• Con la autorización confirmada, instruí a especialista_firewall para aplicar el bloqueo con TTL.\n"
        "• Al concluir, presentá una síntesis ejecutiva del incidente indicando diagnóstico, autorización y estado de contención."
    )
)

# -------------------------------------------------------------------
# 6. EJECUCIÓN
# -------------------------------------------------------------------
# El swarm transfiere el control entre comandante y especialistas (single_turn,
# task). Cada transferencia cambia system_instruction + tool set, así que sin
# context_cache_config ADK re-envía el prefijo completo sin cachear en cada
# salto. La App declara el cache una vez para que cada agente tenga el suyo.
soc_app = App(
    name="soc_app",
    root_agent=root_supervisor,
    context_cache_config=ContextCacheConfig(),
)

async def main():
    session_service = InMemorySessionService()
    runner = Runner(app=soc_app, session_service=session_service)
    await session_service.create_session(app_name="soc_app", user_id="analista_soc", session_id="incidente_2026")
    
    msg = types.Content(
        role="user",
        parts=[types.Part(text="Alerta urgente: Posible ataque de fuerza bruta detectado desde la IP 192.168.1.105.")]
    )
    
    print("=== CASO 2: MESA SOC (COLLABORATIVE SWARM: single_turn + task mode) ===")
    t0 = time.perf_counter()
    
    async for event in runner.run_async(user_id="analista_soc", session_id="incidente_2026", new_message=msg):
        if event.content and event.content.parts:
            for p in event.content.parts:
                if p.function_call:
                    print(f"  [Dispatch Tool Call] {p.function_call.name}({dict(p.function_call.args)})")
                elif p.function_response:
                    print(f"  [Response Recibida de {p.function_response.name}]")
                elif p.text and not p.text.startswith("{"):
                    print(f"\n[Comandante SOC Síntesis]:\n{p.text.strip()}\n")
                    
    print(f"  Tiempo total de ejecución: {time.perf_counter() - t0:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
