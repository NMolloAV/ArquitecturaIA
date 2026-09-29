"""Caso 1: Onboarding y Scoring Crediticio

Topología: Graph Workflow Canónico (ADK 2.0)
Técnicas ADK 2.0 Integradas:
1. Reflex previo al fan-out: nodo de validación KYC en código puro con bifurcación
   real (percepción -> decisión -> acción en una sola pasada, $0 tokens) que corta
   el flujo ANTES de disparar las 3 consultas paralelas si el CUIT es inválido.
2. JoinNode (L2a): Paralelización determinista de consultas Veraz, AFIP y CRM ($0 tokens).
3. Deterministic Router (L2b): Función if-statement con Event(route=...) para bifurcación.
4. Schemas Tipados (input_schema / output_schema): Contratos Pydantic estrictos (L1/L2).
5. Planner-Executor real (rama AUDITORIA_AVANZADA): un LLM planifica un plan de
   verificación explícito (artefacto tipado, no ejecuta nada), un guardrail de
   código lo valida contra un límite regulatorio de pasos, un Executor de
   código lo recorre invocando una función por paso, y recién con esos
   resultados concretos un segundo LLM redacta el dictamen final.
6. Arquetipos: Reflex (validación KYC + filtros en código) + Planner-Executor
   (plan -> guardrail -> executor -> síntesis, no un solo call disfrazado).
"""
import asyncio
import json
import logging
import os
import re
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

from google.adk import Agent, Event, Runner, Workflow
from google.adk.workflow import JoinNode, START
from google.adk.sessions import InMemorySessionService
from google.genai import types

MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")

# -------------------------------------------------------------------
# 1. ESQUEMAS PYDANTIC (Contratos Tipados de Entrada / Salida)
# -------------------------------------------------------------------
class SolicitudInput(BaseModel):
    cuit: str
    monto_solicitado: float
    ingreso_mensual: float

class VerazData(BaseModel):
    cuit: str
    score: int
    situacion_bcra: int
    tiene_embargos: bool

class AfipData(BaseModel):
    cuit: str
    categoria: str
    facturacion_anual: float
    estado: str

class CrmHistory(BaseModel):
    cuit: str
    antiguedad_meses: int
    incidentes_previos: int

class BundledCreditData(BaseModel):
    fetch_veraz: VerazData
    fetch_afip: AfipData
    fetch_crm: CrmHistory

class DictamenCredito(BaseModel):
    veredicto: Literal["APROBADO", "OBSERVADO", "RECHAZADO"] = Field(description="Decisión final de crédito")
    monto_maximo_sugerido: float = Field(description="Límite de crédito aprobado en ARS")
    tasa_interes_anual_pct: float = Field(description="Tasa TNA asignada según riesgo")
    fundamento: str = Field(description="Justificación técnica de 1-2 oraciones citando números concretos")

# --- Esquemas del Planner-Executor de auditoría avanzada (ver sección 5b) ---
class PasoAuditoria(BaseModel):
    tipo: Literal["verificar_garantia", "consultar_historial_judicial", "recalcular_capacidad_pago"] = Field(
        description="Tipo de verificación adicional a ejecutar sobre este caso puntual"
    )
    motivo: str = Field(description="Por qué este paso es necesario para este perfil, citando datos concretos")

class PlanAuditoria(BaseModel):
    pasos: list[PasoAuditoria] = Field(
        min_length=1, max_length=4,
        description="Plan de verificación adicional para un perfil con antecedentes o score moderado"
    )

class HallazgoPaso(BaseModel):
    tipo: str
    resultado: str

class AuditoriaEjecutada(BaseModel):
    datos: BundledCreditData
    plan: PlanAuditoria
    hallazgos: list[HallazgoPaso]

# -------------------------------------------------------------------
# 2. NODO REFLEX: VALIDACIÓN KYC PREVIA AL FAN-OUT (percepción -> decisión ->
#    acción en una sola pasada, $0 tokens). Si el CUIT no tiene formato válido,
#    corta el flujo ANTES de disparar fetch_veraz/afip/crm: no arrancan y el
#    JoinNode nunca se activa (evita la carrera de ejecutar ambas ramas).
# -------------------------------------------------------------------
CUIT_SOLICITANTE = "30-71122334-9"
_CUIT_FORMATO_RE = re.compile(r"^\d{2}-\d{8}-\d{1}$")

def validar_kyc_reflex_node(node_input) -> Event:
    """Reflex: percibe el CUIT, decide si el formato es válido, actúa enrutando."""
    cuit = CUIT_SOLICITANTE
    formato_valido = bool(_CUIT_FORMATO_RE.match(cuit))
    route = "CUIT_VALIDO" if formato_valido else "CUIT_INVALIDO"
    print(f"  [validar_kyc_reflex_node] (0 tokens) CUIT={cuit}, formato_valido={formato_valido} -> Route: {route}")
    return Event(output={"cuit": cuit, "formato_valido": formato_valido}, route=route)

# -------------------------------------------------------------------
# 3. NODOS DE FUNCIÓN PARALELOS (Zero-LLM Cost - L2a)
# -------------------------------------------------------------------
async def fetch_veraz(node_input) -> Event:
    """Consulta central de deudores (Veraz/BCRA)."""
    await asyncio.sleep(0.1)
    data = VerazData(cuit=CUIT_SOLICITANTE, score=780, situacion_bcra=1, tiene_embargos=False)
    print(f"  [fetch_veraz] (0 tokens) -> Score: {data.score}, Sit BCRA: {data.situacion_bcra}")
    return Event(output=data.model_dump())

async def fetch_afip(node_input) -> Event:
    """Consulta padrón fiscal de AFIP."""
    await asyncio.sleep(0.1)
    data = AfipData(cuit=CUIT_SOLICITANTE, categoria="Responsable Inscripto", facturacion_anual=18000000.0, estado="ACTIVO")
    print(f"  [fetch_afip] (0 tokens) -> Categoria: {data.categoria}, Facturación: ${data.facturacion_anual:,.0f}")
    return Event(output=data.model_dump())

async def fetch_crm(node_input) -> Event:
    """Consulta historial de cliente en CRM."""
    await asyncio.sleep(0.1)
    # 1 incidente previo (no 0): perfil bueno pero no intachable, a propósito.
    # Es lo que hace que route_credit_risk mande el caso canónico por
    # AUDITORIA_AVANZADA en vez de APROBACION_STANDARD, para que el demo por
    # defecto ejercite el Planner-Executor real (ver sección 5b) y no solo
    # el camino de aprobación directa de un solo call.
    data = CrmHistory(cuit=CUIT_SOLICITANTE, antiguedad_meses=24, incidentes_previos=1)
    print(f"  [fetch_crm] (0 tokens) -> Antigüedad: {data.antiguedad_meses} meses, Incidentes: {data.incidentes_previos}")
    return Event(output=data.model_dump())

join_credit_data = JoinNode(name="join_credit_data")

# -------------------------------------------------------------------
# 4. ROUTER DETERMINISTA (L2b - If-statement, $0 LLM)
# -------------------------------------------------------------------
def route_credit_risk(node_input) -> Event:
    """Evalúa los datos empaquetados del JoinNode con reglas duras."""
    veraz = node_input["fetch_veraz"]
    crm = node_input["fetch_crm"]
    
    if veraz["situacion_bcra"] > 3 or veraz["tiene_embargos"]:
        route = "RECHAZO_DIRECTO"
    elif veraz["score"] >= 750 and crm["incidentes_previos"] == 0:
        route = "APROBACION_STANDARD"
    else:
        route = "AUDITORIA_AVANZADA"
        
    print(f"  [Router Determinista] Score={veraz['score']}, SitBCRA={veraz['situacion_bcra']} -> Route: {route}")
    return Event(output=node_input, route=route)

# -------------------------------------------------------------------
# 5. AGENTES DECISORES CON CONTRATO PYDANTIC (L1/L2 - 1 LLM Call)
# -------------------------------------------------------------------
aprobador_standard_agent = Agent(
    name="aprobador_standard",
    model=MODEL,
    input_schema=BundledCreditData,
    output_schema=DictamenCredito,
    instruction=(
        "Sos el Oficial Senior de Riesgo Crediticio. Evaluás perfiles crediticios con buen score.\n"
        "Recibís BundledCreditData con datos consolidados de Veraz, AFIP y CRM.\n"
        "Emití un DictamenCredito con veredicto='APROBADO', monto sugerido $1,500,000 y tasa 65%.\n"
        "Citá números exactos de score y facturación en el fundamento."
    )
)

# -------------------------------------------------------------------
# 5b. PLANNER-EXECUTOR REAL: AUDITORÍA AVANZADA (score con antecedentes)
#     Planner (LLM) -> Guardrail (código) -> Executor (código, recorre el
#     plan) -> Síntesis (LLM). A diferencia de aprobador_standard_agent
#     (un solo call), acá el LLM NO decide el dictamen directamente: primero
#     planifica qué verificar, el código valida y ejecuta ese plan, y recién
#     con resultados concretos en mano un segundo LLM redacta el dictamen.
# -------------------------------------------------------------------
MAX_PASOS_PLAN_AUDITORIA = 3  # límite regulatorio de pasos de auditoría, en código ($0 tokens)

planner_auditoria_agent = Agent(
    name="planner_auditoria",
    model=MODEL,
    input_schema=BundledCreditData,
    output_schema=PlanAuditoria,
    instruction=(
        "Sos el Auditor de Casos Especiales de Crédito. Recibís un perfil que no calificó para "
        "aprobación estándar automática (score moderado y/o con antecedentes en el CRM).\n"
        "Tu trabajo en este paso es SOLO planificar, no decidir el dictamen todavía: elegí qué "
        "verificaciones adicionales hacer entre verificar_garantia, consultar_historial_judicial "
        "y recalcular_capacidad_pago. Elegí solo las relevantes para este perfil puntual (no pidas "
        "las 3 si no hace falta) y justificá cada una en 'motivo', citando datos concretos del perfil."
    )
)

def passthrough_datos_auditoria(node_input) -> Event:
    """Re-emite BundledCreditData sin cambios, en paralelo al planner, para reunirlos en el JoinNode."""
    return Event(output=node_input)

join_plan_datos = JoinNode(name="join_plan_datos")

def validar_plan_auditoria_node(node_input) -> Event:
    """Guardrail de código: el plan no puede exceder el límite regulatorio de pasos de auditoría."""
    plan = node_input["planner_auditoria"]
    pasos = plan["pasos"]
    if len(pasos) > MAX_PASOS_PLAN_AUDITORIA:
        print(f"  [validar_plan_auditoria_node] (0 tokens) Plan con {len(pasos)} pasos excede el límite ({MAX_PASOS_PLAN_AUDITORIA}) -> Route: PLAN_RECHAZADO")
        return Event(
            output={"motivo": f"Plan de auditoría con {len(pasos)} pasos excede el límite regulatorio de {MAX_PASOS_PLAN_AUDITORIA}."},
            route="PLAN_RECHAZADO",
        )
    print(f"  [validar_plan_auditoria_node] (0 tokens) Plan con {len(pasos)} paso(s), dentro del límite -> Route: PLAN_OK")
    return Event(output=node_input, route="PLAN_OK")

def fin_auditoria_cancelada(node_input) -> Event:
    return Event(output={
        "veredicto": "CANCELADO",
        "motivo": node_input.get("motivo", "Plan de auditoría rechazado por exceder el límite regulatorio de pasos."),
    })

# Herramientas deterministas que ejecuta el Executor ($0 tokens, código puro).
# Igual de simuladas que fetch_veraz/afip/crm, pero reales en el sentido que
# importa acá: el Executor las invoca de verdad, no le pide al LLM que las
# "actúe" o las alucine.
def _verificar_garantia(paso) -> dict:
    return {"tipo": "verificar_garantia", "resultado": "Garantía prendaria sobre vehículo 2022, tasación $2.100.000, cobertura 140% del monto solicitado."}

def _consultar_historial_judicial(paso) -> dict:
    return {"tipo": "consultar_historial_judicial", "resultado": "Sin juicios ni concursos preventivos registrados a nombre del solicitante ni de la sociedad."}

def _recalcular_capacidad_pago(paso) -> dict:
    return {"tipo": "recalcular_capacidad_pago", "resultado": "Relación cuota/ingreso proyectada: 28%, dentro del límite prudencial (35%)."}

_HERRAMIENTAS_AUDITORIA = {
    "verificar_garantia": _verificar_garantia,
    "consultar_historial_judicial": _consultar_historial_judicial,
    "recalcular_capacidad_pago": _recalcular_capacidad_pago,
}

def executor_auditoria_node(node_input) -> Event:
    """Executor: código puro, recorre el plan aprobado y ejecuta cada paso ($0 tokens)."""
    plan = node_input["planner_auditoria"]
    datos = node_input["passthrough_datos_auditoria"]
    hallazgos = []
    for paso in plan["pasos"]:
        tipo = paso["tipo"]
        hallazgo = _HERRAMIENTAS_AUDITORIA[tipo](paso)
        print(f"  [executor_auditoria_node] (0 tokens) ejecuta '{tipo}' -> {hallazgo['resultado'][:70]}...")
        hallazgos.append(hallazgo)
    return Event(output={"datos": datos, "plan": plan, "hallazgos": hallazgos})

sintesis_auditoria_agent = Agent(
    name="sintesis_auditoria",
    model=MODEL,
    input_schema=AuditoriaEjecutada,
    output_schema=DictamenCredito,
    instruction=(
        "Sos el Auditor de Casos Especiales de Crédito. Recibís los datos originales del perfil (datos), "
        "el plan de verificación que se ejecutó (plan) y los hallazgos concretos de cada paso (hallazgos).\n"
        "Emití un DictamenCredito con veredicto='OBSERVADO': monto_maximo_sugerido entre $500,000 y "
        "$1,200,000 ARS (más conservador que la aprobación estándar, nunca $0), y "
        "tasa_interes_anual_pct entre 70 y 85 (mayor a la estándar por el riesgo adicional, nunca 0 ni un "
        "número fuera de ese rango). Citá en el fundamento los hallazgos concretos (garantía, historial, "
        "capacidad de pago) y los números de score/facturación del perfil."
    )
)

def fin_rechazo_directo(node_input) -> Event:
    return Event(output={"veredicto": "RECHAZADO", "motivo": "Score crediticio insuficiente o situación BCRA irregular."})

# -------------------------------------------------------------------
# 6. WORKFLOW GRAPH CANÓNICO: REFLEX KYC -> FAN-OUT -> JOINNODE -> ROUTER
# -------------------------------------------------------------------
workflow_onboarding = Workflow(
    name="onboarding_crediticio_graph",
    description=(
        "Grafo determinista con Reflex de validación KYC previo al fan-out, "
        "JoinNode, Router por reglas y Agente Decisor tipado."
    ),
    edges=[
        (START, validar_kyc_reflex_node),
        (validar_kyc_reflex_node, {
            "CUIT_VALIDO": (fetch_veraz, fetch_afip, fetch_crm),
            "CUIT_INVALIDO": fin_rechazo_directo,
        }),
        (fetch_veraz, join_credit_data),
        (fetch_afip, join_credit_data),
        (fetch_crm, join_credit_data),
        (join_credit_data, route_credit_risk),
        (route_credit_risk, {
            "APROBACION_STANDARD": aprobador_standard_agent,
            "RECHAZO_DIRECTO": fin_rechazo_directo,
            "AUDITORIA_AVANZADA": (planner_auditoria_agent, passthrough_datos_auditoria),
        }),
        # Planner-Executor real: plan (LLM) -> join con los datos originales ->
        # guardrail de código -> executor de código -> síntesis (LLM).
        (planner_auditoria_agent, join_plan_datos),
        (passthrough_datos_auditoria, join_plan_datos),
        (join_plan_datos, validar_plan_auditoria_node),
        (validar_plan_auditoria_node, {
            "PLAN_OK": executor_auditoria_node,
            "PLAN_RECHAZADO": fin_auditoria_cancelada,
        }),
        (executor_auditoria_node, sintesis_auditoria_agent),
    ]
)

# -------------------------------------------------------------------
# 7. EJECUCIÓN
# -------------------------------------------------------------------
async def main():
    session_service = InMemorySessionService()
    runner = Runner(node=workflow_onboarding, app_name="onboarding_app", session_service=session_service)
    await session_service.create_session(app_name="onboarding_app", user_id="cliente_1", session_id="sesion_credito_1")

    print("=== CASO 1: ONBOARDING CREDITICIO (GRAPH WORKFLOW CANÓNICO ADK 2.0) ===")
    t0 = time.perf_counter()
    
    async for event in runner.run_async(user_id="cliente_1", session_id="sesion_credito_1", new_message=None):
        if event.content and event.content.parts:
            for p in event.content.parts:
                if p.text:
                    print(f"\n[Dictamen Tipado DictamenCredito]:\n{p.text}")
        elif event.output:
            print(f"\n[Output Nodo]: {event.output}")
            
    print(f"\n  Tiempo total de ejecución: {time.perf_counter() - t0:.2f}s (Reflex KYC + 3 fetches en paralelo + Planner-Executor: 2 LLM calls)")

if __name__ == "__main__":
    asyncio.run(main())
