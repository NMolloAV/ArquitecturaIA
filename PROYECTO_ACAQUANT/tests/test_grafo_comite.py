"""El grafo ENTERO del Lab 01 con un modelo FALSO: no gasta tokens, no usa red,
y caza un typo en una clave de join o un contrato Pydantic roto. Es la prueba
que vale: los tests de reglas no ven el Workflow."""
import importlib
import json

import pytest

pytest.importorskip("google.adk")


@pytest.fixture
def comite(monkeypatch):
    monkeypatch.setenv("ACAQUANT_MODO", "fixtures")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    return importlib.import_module("labs.01_comite_renta_fija")


def _modelo_falso(monkeypatch, propuesta: dict, vistos: list):
    from google.adk.models.google_llm import Gemini
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    async def generate(self, req, stream=False):
        schema = getattr(req.config.response_schema, "__name__", "?")
        vistos.append(schema)
        if schema == "Informe":
            out = {"sesgo": "NEUTRAL", "resumen": "r", "puntos": ["a", "b"]}
        else:
            out = propuesta
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(out))]))

    monkeypatch.setattr(Gemini, "generate_content_async", generate)


async def _correr(comite):
    from google.adk import Runner
    from google.adk.sessions import InMemorySessionService
    ss = InMemorySessionService()
    runner = Runner(node=comite.comite, app_name="t", session_service=ss)
    await ss.create_session(app_name="t", user_id="u", session_id="s")
    final = None
    async for ev in runner.run_async(user_id="u", session_id="s", new_message=None):
        if ev.output and isinstance(ev.output, dict) and "decision" in ev.output:
            final = ev.output
    return final


@pytest.mark.asyncio
async def test_compra_sana_llega_a_ejecutar(comite, monkeypatch):
    vistos = []
    _modelo_falso(monkeypatch, {"accion": "COMPRAR", "bono": "S29E7", "tamano_pct": 1.5, "conviccion": 65, "tesis": "t"}, vistos)
    final = await _correr(comite)
    assert final["decision"] == "EJECUTAR la compra" and final["veredicto"] == "APROBADA"
    assert sorted(vistos) == ["Informe", "Informe", "Propuesta"]  # 3 llamadas, ni una más


@pytest.mark.asyncio
async def test_compra_mala_termina_vetada_con_motivos(comite, monkeypatch):
    _modelo_falso(monkeypatch, {"accion": "COMPRAR", "bono": "T30J7", "tamano_pct": 4.0, "conviccion": 65, "tesis": "t"}, [])
    final = await _correr(comite)
    assert final["veredicto"] == "VETADA" and len(final["motivos"]) == 3


@pytest.mark.asyncio
async def test_esperar_no_dice_ejecutar(comite, monkeypatch):
    _modelo_falso(monkeypatch, {"accion": "ESPERAR", "bono": None, "tamano_pct": 0, "conviccion": 40, "tesis": "t"}, [])
    final = await _correr(comite)
    assert final["veredicto"] == "APROBADA" and final["decision"].startswith("ESPERAR")


@pytest.mark.asyncio
async def test_sin_datos_no_gasta_tokens(comite, monkeypatch):
    vistos = []
    _modelo_falso(monkeypatch, {}, vistos)

    async def rompe(*a, **k):
        raise ConnectionError("sin MCP")
    monkeypatch.setattr(comite, "llamar", rompe)
    final = await _correr(comite)
    assert final["decision"].startswith("SIN COMITÉ") and "sin MCP" in final["motivo"]
    assert vistos == []
