"""Lab 01 — Comité de inversión en pesos sobre datos de AcaQuant.

Qué combina:
  · LIBRO cap. 8 (Multi-Agent Investment Committee, LangGraph): analistas en
    paralelo -> Portfolio Manager sintetiza -> Risk Officer con reglas duras.
  · CURSO módulo 5 (ADK 2, Graph Workflow): el mismo comité como grafo
    determinista con JoinNode, router por reglas y agentes con contrato
    Pydantic (input_schema / output_schema).
  · ACAQUANT como proveedor de datos: curva tasa fija, carry, breakevens,
    dólar, caución y riesgo país, por `puente.acaquant` (fixtures o MCP vivo).

Topología:
  START -> cargar_mesa (0 tokens, 6 llamadas al puente en paralelo)
        -> [analista_curva, analista_macro, mesa_a]  (2 LLM en paralelo)
        -> join_informes -> distribuir -> [portfolio_manager, mesa_b]  (1 LLM)
        -> join_propuesta -> oficial_riesgo (0 tokens, labs/comite_reglas.revisar)
        -> APROBADA | VETADA

Correr: ./run.sh 1   (o: python -m labs.01_comite_renta_fija, desde PROYECTO_ACAQUANT)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import warnings
from typing import Literal

from pydantic import BaseModel, Field

warnings.filterwarnings("ignore", message=r"\[EXPERIMENTAL\]", category=UserWarning)
try:
    import authlib.deprecate  # noqa: F401  (registra su filtro antes del nuestro)
except ImportError:
    pass
warnings.filterwarnings("ignore", message=r"authlib\.jose module is deprecated")
logging.getLogger("google_genai.types").setLevel(logging.ERROR)

from google.adk import Agent, Event, Runner, Workflow  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.adk.workflow import START, JoinNode  # noqa: E402

from labs.comite_reglas import LIMITES, armar_mesa, revisar  # noqa: E402
from puente.acaquant import llamar, modo  # noqa: E402

MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")


# ---------------------------------------------------------------------------
# 1. Contratos (lo que cada agente recibe y lo que tiene que devolver)
# ---------------------------------------------------------------------------
class Bono(BaseModel):
    ticker: str
    vencimiento: str
    meses: float
    tea: float
    tem: float
    mod_duration: float
    monto_dia_usd: float


class Carry(BaseModel):
    ticker: str
    carry_anual: float
    roll: float
    tea_futura: float


class Breakeven(BaseModel):
    lecap: str
    cer: str
    meses: float
    inflacion_mensual_breakeven: float


class Dolar(BaseModel):
    mep: float | None = None
    ccl: float | None = None
    oficial: float | None = None
    canje_pct: float | None = None
    mep_ret_7d_pct: float | None = None
    mep_ret_mes_pct: float | None = None


class RiesgoPais(BaseModel):
    bps: float | None = None
    zscore_60d: float | None = None
    percentil_60d: float | None = None
    cambio_mes_pct: float | None = None
    clasificacion: str | None = None


class Mesa(BaseModel):
    """Lo que ve el comité: los números, calculados por AcaQuant, no por el modelo."""
    fecha_datos: str | None = None
    curva: str
    bonos: list[Bono]
    carry_3m: list[Carry]
    mejor_carry: str | None = None
    breakevens: list[Breakeven]
    dolar: Dolar
    caucion_1d_tna: float | None = None
    riesgo_pais: RiesgoPais


class Informe(BaseModel):
    sesgo: Literal["ALCISTA", "NEUTRAL", "BAJISTA"] = Field(description="Sesgo del analista sobre su área")
    resumen: str = Field(description="Máximo 120 palabras, citando números concretos de la mesa")
    puntos: list[str] = Field(description="2 a 4 puntos clave, uno por línea")


class Informes(BaseModel):
    analista_curva: Informe
    analista_macro: Informe
    mesa_a: Mesa


class Propuesta(BaseModel):
    accion: Literal["COMPRAR", "ESPERAR"] = Field(description="COMPRAR un bono de la curva o ESPERAR")
    bono: str | None = Field(default=None, description="Ticker exacto de la mesa si COMPRAR; null si ESPERAR")
    tamano_pct: float = Field(description="% del patrimonio: 0 si ESPERAR, 0.5-5.0 si COMPRAR")
    conviccion: int = Field(description="0 a 100")
    tesis: str = Field(description="Máximo 200 palabras: por qué ese bono y ese tamaño, con números")


class PropuestaYMesa(BaseModel):
    portfolio_manager: Propuesta
    mesa_b: Mesa


# ---------------------------------------------------------------------------
# 2. Nodo de datos (0 tokens): el puente trae las 6 respuestas en paralelo
# ---------------------------------------------------------------------------
async def cargar_mesa(node_input) -> Event:
    t0 = time.perf_counter()
    try:
        curva, carry, bes, dolar, cau, rp = await asyncio.gather(
            llamar("rf_curva", curva="tasa_fija"),
            llamar("trading_carry", curva="tasa_fija", horizonte_meses=3),
            llamar("rf_breakevens"),
            llamar("dolar_panel"),
            llamar("caucion", moneda="ARS"),
            llamar("macro_serie", variable="riesgo_pais", ventana_dias=60),
        )
    except Exception as e:  # sin datos no hay comité: se corta antes de gastar tokens
        print(f"  [cargar_mesa] falló el puente ({modo()}): {type(e).__name__}: {e}")
        return Event(output={"motivo": str(e)}, route="SIN_DATOS")
    mesa = armar_mesa(curva, carry, bes, dolar, cau, rp)
    print(f"  [cargar_mesa] (0 tokens, modo {modo()}) {len(mesa['bonos'])} bonos, mejor carry {mesa['mejor_carry']}, "
          f"riesgo país {mesa['riesgo_pais']['bps']} bps (z={mesa['riesgo_pais']['zscore_60d']}) en {time.perf_counter() - t0:.2f}s")
    return Event(output=mesa, route="DATOS_OK")


def mesa_a(node_input) -> Event:
    """Re-emite la mesa en paralelo a los analistas, para que el JoinNode la junte con los informes."""
    return Event(output=node_input)


def mesa_b(node_input) -> Event:
    """Lo mismo, del join de informes hacia el join de la propuesta."""
    return Event(output=node_input["mesa_a"])


# ---------------------------------------------------------------------------
# 3. Analistas (LLM, en paralelo) — cada uno mira SU parte de la mesa
# ---------------------------------------------------------------------------
analista_curva = Agent(
    name="analista_curva",
    model=MODEL,
    input_schema=Mesa,
    output_schema=Informe,
    instruction=(
        "Sos analista de renta fija en pesos de una mesa argentina. Recibís la curva de tasa fija "
        "(LECAP/BONCAP) con TEA, TEM, duration y volumen; el ranking de carry + roll-down a 3 meses; "
        "y los breakevens de inflación LECAP vs CER.\n"
        "Escribí un Informe corto: forma de la curva (¿dónde se empina?), dónde está el mejor carry "
        "y por qué, qué inflación mensual descuenta el mercado, y si la tasa real que paga la curva "
        "contra ese breakeven es atractiva. Citá tickers y números exactos de la mesa; no inventes datos."
    ),
)

analista_macro = Agent(
    name="analista_macro",
    model=MODEL,
    input_schema=Mesa,
    output_schema=Informe,
    instruction=(
        "Sos el estratega macro de la mesa. Recibís dólar MEP/CCL/oficial con sus retornos, el canje, "
        "la caución a 1 día y el riesgo país con su z-score y percentil de 60 días.\n"
        "Escribí un Informe corto sobre el régimen (¿estrés o calma?): presión cambiaria, costo del "
        "dinero a un día vs la curva, y qué dice el riesgo país. Terminá con qué implica para tomar "
        "duration en pesos hoy. Citá números exactos de la mesa; no inventes datos."
    ),
)

join_informes = JoinNode(name="join_informes")


def distribuir(node_input) -> Event:
    """Router trivial: del join de informes al PM y al passthrough de la mesa."""
    return Event(output=node_input, route="PM")


# ---------------------------------------------------------------------------
# 4. Portfolio Manager (LLM): sintetiza y propone
# ---------------------------------------------------------------------------
portfolio_manager = Agent(
    name="portfolio_manager",
    model=MODEL,
    input_schema=Informes,
    output_schema=Propuesta,
    instruction=(
        "Sos el Portfolio Manager. Recibís los informes del analista de curva y del macro, y la mesa "
        "con los datos. Sintetizá en una Propuesta: COMPRAR un bono concreto de la curva (ticker "
        "exacto de `mesa_a.bonos`) o ESPERAR.\n"
        "Tamaño como % del patrimonio total, puramente por convicción y sin anticipar la revisión "
        "de riesgo: 0 si ESPERAR; 0.5-1.0 posición inicial con convicción mixta; 1.0-2.0 compra "
        "estándar (convicción 50-70); 2.0-3.0 convicción alta (70+); más de 3 solo para un setup "
        "excepcional donde los dos analistas coinciden y el macro acompaña. "
        "COMPRAR con tamaño 0 es incoherente: elegí ESPERAR."
    ),
)

join_propuesta = JoinNode(name="join_propuesta")


# ---------------------------------------------------------------------------
# 5. Oficial de Riesgo (0 tokens): reglas duras, en código
# ---------------------------------------------------------------------------
def oficial_riesgo(node_input) -> Event:
    propuesta = node_input["portfolio_manager"]
    mesa = node_input["mesa_b"]
    veredicto, motivos = revisar(propuesta, mesa)
    print(f"  [oficial_riesgo] (0 tokens) {propuesta.get('accion')} {propuesta.get('bono') or ''} "
          f"{propuesta.get('tamano_pct')}% conv={propuesta.get('conviccion')} -> {veredicto}")
    for m in motivos:
        print(f"      · {m}")
    return Event(output={"veredicto": veredicto, "motivos": motivos, "propuesta": propuesta}, route=veredicto)


def fin_aprobada(node_input) -> Event:
    return Event(output={"decision": "EJECUTAR", **node_input})


def fin_vetada(node_input) -> Event:
    return Event(output={"decision": "ESPERAR (veto de riesgo)", **node_input})


def fin_sin_datos(node_input) -> Event:
    return Event(output={"decision": "SIN COMITÉ: no hubo datos", **node_input})


# ---------------------------------------------------------------------------
# 6. El grafo
# ---------------------------------------------------------------------------
comite = Workflow(
    name="comite_renta_fija",
    description="Comité de inversión en pesos: datos de AcaQuant, 2 analistas en paralelo, PM y riesgo en código.",
    edges=[
        (START, cargar_mesa),
        (cargar_mesa, {
            "DATOS_OK": (analista_curva, analista_macro, mesa_a),
            "SIN_DATOS": fin_sin_datos,
        }),
        (analista_curva, join_informes),
        (analista_macro, join_informes),
        (mesa_a, join_informes),
        (join_informes, distribuir),
        (distribuir, {"PM": (portfolio_manager, mesa_b)}),
        (portfolio_manager, join_propuesta),
        (mesa_b, join_propuesta),
        (join_propuesta, oficial_riesgo),
        (oficial_riesgo, {"APROBADA": fin_aprobada, "VETADA": fin_vetada}),
    ],
)


# ---------------------------------------------------------------------------
# 7. Ejecución
# ---------------------------------------------------------------------------
async def main() -> None:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"
    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        sys.exit("Falta GOOGLE_API_KEY (https://aistudio.google.com/apikey): copiá .env.example a .env y completala.")

    sesiones = InMemorySessionService()
    runner = Runner(node=comite, app_name="comite_app", session_service=sesiones)
    await sesiones.create_session(app_name="comite_app", user_id="mesa", session_id="comite_1")

    print(f"=== LAB 01: COMITÉ DE RENTA FIJA EN PESOS (ADK 2 Graph Workflow · datos AcaQuant, modo {modo()}) ===")
    print(f"    límites del oficial de riesgo: {LIMITES}")
    t0 = time.perf_counter()
    async for event in runner.run_async(user_id="mesa", session_id="comite_1", new_message=None):
        autor = getattr(event, "author", "") or ""
        if event.content and event.content.parts:
            for p in event.content.parts:
                if p.text:
                    print(f"\n[{autor}]\n{p.text}")
        elif event.output and isinstance(event.output, dict) and "decision" in event.output:
            print(f"\n[DECISIÓN FINAL] {event.output['decision']}")
            for m in event.output.get("motivos", []):
                print(f"   · {m}")
    print(f"\n  Tiempo total: {time.perf_counter() - t0:.1f}s (3 llamadas al modelo: 2 analistas en paralelo + PM; riesgo en código)")


if __name__ == "__main__":
    asyncio.run(main())
