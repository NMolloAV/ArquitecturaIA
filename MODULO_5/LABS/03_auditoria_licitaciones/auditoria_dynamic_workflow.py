"""Caso 3: Auditoría Masiva de Licitaciones y Contratos Públicos

Topología: Dynamic Workflow Canónico (ADK 2.0 - L4a/L4b)
Técnicas ADK 2.0 Integradas:
1. @node(parallel_worker=True) (L4a/L4b): Paralelización nativa con tracing y checkpointing.
2. RetryConfig (L4b): Resiliencia ante fallos transitorios y límites de cuota (429).
3. Recursión Asíncrona (L4b): ctx.run_node(research_topic, ...) con control de profundidad MAX_DEPTH.
4. Schemas Tipados: DecomposerOutput, ResearchFinding, BriefingLicitacion.
5. Human-in-the-Loop real: decompose extrae el monto de la licitación en código (regex,
   $0 tokens) y lo guarda en ctx.state; evaluar_umbral_node lo compara contra
   UMBRAL_APROBACION_HUMANA y bifurca a PAUSADO_HITL o aprobación automática — el monto
   no lo evalúa el LLM, lo evalúa código determinista, igual que el guardrail del Caso 1.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
import warnings
from typing import List
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
from google.adk.workflow import RetryConfig, START, node
from google.adk.sessions import InMemorySessionService
from google.genai import types as gtypes

MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")
MAX_DEPTH = 2
UMBRAL_APROBACION_HUMANA = 100000.0  # USD

# -------------------------------------------------------------------
# 1. ESQUEMAS PYDANTIC (Contratos Tipados de Entrada / Salida)
# -------------------------------------------------------------------
class DecomposerOutput(BaseModel):
    sub_questions: List[str] = Field(
        min_length=2, max_length=4,
        description="Lista de 2 a 3 cláusulas críticas o antecedentes a auditar independientemente"
    )

class ResearchFinding(BaseModel):
    summary: str = Field(description="Resumen de 1-2 oraciones del hallazgo de auditoría")
    key_facts: List[str] = Field(description="2-3 hechos o cifras clave identificadas")
    needs_deeper: bool = Field(description="True si se detectó una irregularidad o riesgo que requiere profundizar")
    deeper_questions: List[str] = Field(default_factory=list, description="1-2 subpreguntas si needs_deeper es True")

class BriefingLicitacion(BaseModel):
    headline: str = Field(description="Título ejecutivo del dictamen de auditoría")
    veredicto: str = Field(
        description=(
            "APROBADO_AUTOMATICO | OBSERVADO — evaluación de CONTENIDO del pliego "
            "(cláusulas, antecedentes). La pausa por monto (PAUSADO_HITL) la decide "
            "un nodo de código aparte, no este campo."
        )
    )
    sections: List[str] = Field(description="3-4 párrafos que combinan los hallazgos de todas las cláusulas")
    key_warnings: List[str] = Field(description="Alertas de cumplimiento identificadas")

# -------------------------------------------------------------------
# 2. AGENTES TIPADOS (L4a / L4b)
# -------------------------------------------------------------------
decompose_agent = Agent(
    name="decompose_agent",
    model=MODEL,
    output_schema=DecomposerOutput,
    instruction=(
        "Sos un auditor de contrataciones públicas. "
        "Dada una licitación, dividila en 2-3 subconsultas atómicas e independientes "
        "(1. Precios y reajuste, 2. Garantías y SLAs, 3. Antecedentes del proveedor)."
    )
)

research_agent = Agent(
    name="research_agent",
    model=MODEL,
    output_schema=ResearchFinding,
    instruction="""Sos un especialista en auditoría legal y financiera.
Dada UNA consulta específica sobre un pliego o proveedor:
- Producí un resumen conciso y 2-3 hechos clave.
- Si detectás cláusulas abusivas o posibles demoras, seteá needs_deeper=True y agregá 1-2 deeper_questions.""",
)

synthesize_agent = Agent(
    name="synthesize_agent",
    model=MODEL,
    output_schema=BriefingLicitacion,
    instruction="""Sos el Auditor General. Sintetizá el árbol de hallazgos en un BriefingLicitacion:
headline, veredicto, sections combinando hechos concretos, y key_warnings.""",
)

# -------------------------------------------------------------------
# 3. HELPER DE COERCIÓN TIPADA (L4b)
# -------------------------------------------------------------------
def _coerce(payload, schema_cls):
    if isinstance(payload, schema_cls):
        return payload
    if isinstance(payload, dict):
        return schema_cls.model_validate(payload)
    if isinstance(payload, str):
        return schema_cls.model_validate_json(payload)
    if hasattr(payload, "parts") and payload.parts:
        text = getattr(payload.parts[0], "text", None)
        if text:
            return schema_cls.model_validate_json(text)
    raise ValueError(f"Cannot coerce {type(payload).__name__} into {schema_cls.__name__}")

def _extract_text(node_input):
    if isinstance(node_input, str):
        return node_input
    if hasattr(node_input, "parts") and node_input.parts:
        return getattr(node_input.parts[0], "text", None) or str(node_input)
    return str(node_input)

# Extracción determinista del monto ($0 tokens) — es un Reflex: percibe el texto,
# decide si hay un monto en USD, lo devuelve. No requiere juicio del LLM.
_MONTO_USD_RE = re.compile(r"USD\s*\$?\s*([\d.,]+)")

def _extraer_monto_usd(texto: str) -> float | None:
    match = _MONTO_USD_RE.search(texto)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))

# -------------------------------------------------------------------
# 4. NODOS DINÁMICOS DEL WORKFLOW (L4b)
# -------------------------------------------------------------------
@node(rerun_on_resume=True)
async def decompose(ctx, node_input):
    user_query = _extract_text(node_input)

    monto_usd = _extraer_monto_usd(user_query)
    ctx.state["monto_licitacion_usd"] = monto_usd  # queda disponible para evaluar_umbral_node más adelante
    if monto_usd is not None:
        print(f"  [decompose] (0 tokens) monto detectado en el pliego: USD ${monto_usd:,.0f}")
    else:
        print("  [decompose] (0 tokens) no se detectó un monto en USD en el pliego")

    plan = _coerce(await ctx.run_node(decompose_agent, node_input=user_query), DecomposerOutput)
    print(f"  [decompose] {len(plan.sub_questions)} subconsultas generadas en tiempo de ejecución:")
    for q in plan.sub_questions:
        print(f"    • {q[:80]}")
    yield Event(output=[{"question": q, "depth": 1, "original_query": user_query} for q in plan.sub_questions])

# Resiliencia con RetryConfig (L4b)
RESEARCH_RETRY = RetryConfig(max_attempts=3, initial_delay=1.0, backoff_factor=2.0)

@node(parallel_worker=True, rerun_on_resume=True, retry_config=RESEARCH_RETRY)
async def research_topic(ctx, node_input):
    """Worker paralelo nativo de ADK 2.0 con soporte de recursión."""
    question = node_input["question"]
    depth = node_input["depth"]
    ctxq = node_input.get("original_query", "")
    print(f"  [research parallel d={depth}] {question[:70]}")
    
    finding = _coerce(await ctx.run_node(
        research_agent,
        node_input=f"PLIEGO GENERAL: {ctxq}\n\nCONSULTA ESPECÍFICA: {question}",
    ), ResearchFinding)

    children = []
    # Recursión dinámica acotada por MAX_DEPTH
    if finding.needs_deeper and finding.deeper_questions and depth < MAX_DEPTH:
        deeper = [{"question": dq, "depth": depth + 1, "original_query": ctxq}
                  for dq in finding.deeper_questions]
        print(f"  [research d={depth}] Generando {len(deeper)} ramas recursivas más profundas...")
        children = await ctx.run_node(research_topic, node_input=deeper)  # ★ Llamada recursiva ADK 2.0

    yield Event(output={
        "question": question, 
        "depth": depth, 
        "summary": finding.summary,
        "key_facts": finding.key_facts, 
        "children": children
    })

@node(rerun_on_resume=True)
async def synthesize(ctx, node_input):
    print(f"\n  [synthesize] Consolidando {len(node_input)} ramas de investigación...")
    briefing = _coerce(await ctx.run_node(
        synthesize_agent, node_input=json.dumps(node_input, indent=2)
    ), BriefingLicitacion)
    yield Event(output={"briefing": briefing.model_dump(), "research_tree": node_input})

# -------------------------------------------------------------------
# 4b. GATE DE HUMAN-IN-THE-LOOP (código, $0 tokens): compara el monto extraído
#     en decompose contra el umbral regulatorio. El LLM no participa de esta
#     decisión — es un guardrail, igual en espíritu al de la rama AUDITORIA_AVANZADA
#     del Caso 1.
# -------------------------------------------------------------------
@node(rerun_on_resume=True)
async def evaluar_umbral_node(ctx, node_input):
    monto_usd = ctx.state.get("monto_licitacion_usd")
    supera_umbral = monto_usd is not None and monto_usd > UMBRAL_APROBACION_HUMANA
    route = "PAUSADO_HITL" if supera_umbral else "AUTO"
    monto_fmt = f"USD ${monto_usd:,.0f}" if monto_usd is not None else "desconocido"
    print(f"  [evaluar_umbral_node] (0 tokens) monto={monto_fmt}, umbral=USD ${UMBRAL_APROBACION_HUMANA:,.0f} -> Route: {route}")
    yield Event(
        output={**node_input, "monto_licitacion_usd": monto_usd, "supera_umbral": supera_umbral},
        route=route,
    )

def fin_pausa_hitl(node_input) -> Event:
    print("  [fin_pausa_hitl] (0 tokens) Auditoría suspendida: requiere firma ejecutiva antes de continuar (Task API).")
    return Event(output={**node_input, "estado_final": "PAUSADO_HITL"})

def fin_aprobacion_automatica(node_input) -> Event:
    print("  [fin_aprobacion_automatica] (0 tokens) Monto bajo el umbral: reporte final sin intervención humana.")
    return Event(output={**node_input, "estado_final": "APROBACION_AUTOMATICA"})

# -------------------------------------------------------------------
# 5. WORKFLOW DINÁMICO CANÓNICO (L4b)
# -------------------------------------------------------------------
workflow_auditoria = Workflow(
    name="auditoria_licitaciones_dynamic",
    description="Decompose -> Recursive Parallel Research (parallel_worker) -> Synthesize -> Gate de umbral (HITL real).",
    edges=[
        (START, decompose, research_topic, synthesize, evaluar_umbral_node),
        (evaluar_umbral_node, {
            "PAUSADO_HITL": fin_pausa_hitl,
            "AUTO": fin_aprobacion_automatica,
        }),
    ],
)

# -------------------------------------------------------------------
# 6. EJECUCIÓN
# -------------------------------------------------------------------
async def main():
    session_service = InMemorySessionService()
    runner = Runner(
        node=workflow_auditoria, 
        app_name="dynamic_app", 
        session_service=session_service,
        auto_create_session=True
    )
    
    consulta = (
        "Licitación LIC-2026-002: Contratación de servicios de mantenimiento de Data Center por USD $250,000. "
        "Proveedor postulado: GlobalServices SRL. SLA requerido: 99.99%. Garantía de oferta: USD $10,000. "
        "Penalidad por caída de servicio: 0.5% por hora."
    )
    
    print("=== CASO 3: AUDITORÍA DE LICITACIONES (DYNAMIC WORKFLOW: L4a/L4b NATIVO) ===")
    t0 = time.perf_counter()
    
    final_output = None
    async for event in runner.run_async(
        user_id="auditor_lead", 
        session_id="sesion_licitacion_99",
        new_message=gtypes.Content(role="user", parts=[gtypes.Part(text=consulta)])
    ):
        out = getattr(event, "output", None)
        if isinstance(out, dict) and "briefing" in out:
            final_output = out
            
    if final_output:
        b = final_output["briefing"]
        tree = final_output["research_tree"]
        monto = final_output.get("monto_licitacion_usd")
        estado_final = final_output.get("estado_final")
        print(f"\n📋 Dictamen Final: {b['headline']}")
        print(f"🚦 Veredicto de contenido: {b['veredicto']}")
        if monto is not None:
            print(f"💰 Monto: USD ${monto:,.0f} (umbral de aprobación humana: USD ${UMBRAL_APROBACION_HUMANA:,.0f})")
        if estado_final:
            etiqueta = "PAUSADO — requiere firma ejecutiva (Task API)" if estado_final == "PAUSADO_HITL" else "Aprobación automática"
            print(f"🔒 Estado (decidido en código, no por el LLM): {etiqueta}")
        for sec in b["sections"]:
            print(f"  • {sec}")
        if b["key_warnings"]:
            print(f"⚠️ Alertas Clave:")
            for w in b["key_warnings"]:
                print(f"    - {w}")
                
    print(f"\n  Tiempo total de ejecución: {time.perf_counter() - t0:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
