"""puente/tools_adk.py — las herramientas de AcaQuant como `FunctionTool` de ADK.

Para un agente ReAct (`Agent(tools=[...])`): el modelo elige qué pedir. Son
`async` porque ADK corre en asyncio y en modo `mcp` la llamada es de red.
Cada docstring es lo que el modelo lee para decidir cuándo usarla: corto y
en los términos del mercado, no del código.
"""
from __future__ import annotations

from puente.acaquant import llamar


async def curva_renta_fija(curva: str = "tasa_fija") -> dict:
    """Bonos de una curva en pesos con precio, TEA, TEM, duration y volumen del
    día. `curva`: tasa_fija (LECAP/BONCAP), cer, tamar, soberanos, dolar_linked, dual."""
    return await llamar("rf_curva", curva=curva)


async def carry_roll_down(curva: str = "tasa_fija", horizonte_meses: int = 3) -> dict:
    """Ranking de carry + roll-down de los bonos de una curva si la curva de hoy
    no se mueve. `horizonte_meses`: 1, 3 o 6. Devuelve `mejor` y la auditoría."""
    return await llamar("trading_carry", curva=curva, horizonte_meses=horizonte_meses)


async def breakevens_inflacion() -> dict:
    """Inflación mensual breakeven que iguala una LECAP con el bono CER de
    vencimiento parecido, por par."""
    return await llamar("rf_breakevens")


async def panel_dolar() -> dict:
    """MEP, CCL, canje, oficial, riesgo país y cauciones con retornos del día,
    7 días, mes y año."""
    return await llamar("dolar_panel")


async def caucion(moneda: str = "ARS") -> dict:
    """Caución (tasa de pesos a 1 día) en vivo: TNA y volumen. `moneda`: ARS o USD."""
    return await llamar("caucion", moneda=moneda)


async def serie_macro(variable: str, ventana_dias: int = 90) -> dict:
    """Serie diaria y estadísticas (z-score, percentil) de una variable:
    riesgo_pais, mep, ccl, canje, tamar, cer, badlar, dolar_oficial, ipc,
    ipc_interanual, caucion_ars, caucion_usd."""
    return await llamar("macro_serie", variable=variable, ventana_dias=ventana_dias)


async def medias_moviles(ticker: str | None = None) -> dict:
    """Acciones (subyacentes de CEDEARs) contra sus medias de 50 y 200 ruedas
    con el último cruce. Sin `ticker`, el universo; con uno (ej. AAPL), su serie."""
    return await llamar("trading_medias", ticker=ticker)


TODAS = [curva_renta_fija, carry_roll_down, breakevens_inflacion, panel_dolar,
         caucion, serie_macro, medias_moviles]
