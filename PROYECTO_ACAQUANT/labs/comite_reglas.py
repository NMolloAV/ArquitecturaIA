"""labs/comite_reglas.py — la parte del Comité que es CÓDIGO, no modelo.

Dos funciones puras (sin ADK, sin red, testeables):
  armar_mesa(...)   compacta las 6 respuestas del MCP en lo que los analistas
                    necesitan leer (y nada más: un JSON de 20 KB en el prompt
                    es plata y ruido). TODAS las tasas y variaciones salen en
                    PORCENTAJE y con el sufijo `_pct`: el MCP mezcla fracciones
                    (tea 0.26) con porcentajes (caución 18.6) y un modelo que
                    compara 0.26 con 18.6 razona mal sin que nada falle.
  revisar(...)      el Oficial de Riesgo: reglas duras sobre la propuesta del
                    PM. Es el «hard rules before any LLM call» del Risk
                    Officer del libro (cap. 8), en código y con $0 tokens.

Los LÍMITES son didácticos: están para mostrar que el veto vive en código y
es auditable, no son la política de riesgo de nadie.
"""
from __future__ import annotations

from typing import Any

LIMITES = {
    "tamano_max_pct": 3.0,           # tope por nombre, % del patrimonio (como el libro)
    "conviccion_min": 50,            # una COMPRA con menos convicción no pasa
    "liquidez_min_usd": 1_000_000,   # monto operado en el día, en USD oficial
    "zscore_riesgo_pais_alerta": 1.5,  # riesgo país «en máximo»: no estirar duration
    "mod_duration_max_con_alerta": 0.5,
}


def _f(x: Any, nd: int = 4) -> float | None:
    return None if x is None else round(float(x), nd)


def _pct(x: Any, nd: int = 2) -> float | None:
    """Fracción del MCP (0.2631) -> porcentaje (26.31)."""
    return None if x is None else round(float(x) * 100, nd)


def armar_mesa(curva: dict, carry: dict, breakevens: dict, dolar: dict,
               caucion: dict, riesgo_pais: dict, nombre_curva: str = "tasa_fija") -> dict:
    """Las 6 respuestas crudas del MCP -> un dict chico y plano para el prompt."""
    panel = {f["label"]: f for f in dolar.get("filas", [])}

    def valor(label: str, campo: str = "value"):
        return _f(panel.get(label, {}).get(campo))

    filas = curva.get("filas", [])
    bonos = [
        {
            "ticker": b["ticker_corto"], "vencimiento": b["fecha_vencimiento"],
            "meses": _f(b.get("meses_al_vto"), 1), "tea_pct": _pct(b["tea"]), "tem_pct": _pct(b.get("tem")),
            "mod_duration": _f(b.get("mod_duration")), "monto_dia_usd": _f(b.get("monto_dia_usd"), 0),
        }
        for b in filas if b.get("tea") is not None
    ]
    # Cada fuente tiene su propia fecha: los precios son del último trade, el
    # riesgo país es una serie diaria que puede ir atrás. Se rotulan por separado.
    fechas_trade = sorted(str(b.get("ts_ultimo_trade") or "")[:10] for b in filas if b.get("ts_ultimo_trade"))
    pares = (breakevens.get("filas") or [{}])[0].get("pares", [])
    cau = (caucion.get("filas") or [{}])[0]
    return {
        "fechas": {
            "precios_curva": fechas_trade[-1] if fechas_trade else None,
            "riesgo_pais": riesgo_pais.get("fecha_actual"),
        },
        "unidades": "todas las tasas, retornos y variaciones en % (sufijo _pct); duration en años; montos en USD",
        "curva": nombre_curva,
        "bonos": bonos,
        "carry_3m": [
            {"ticker": c["ticker"], "carry_anual_pct": _pct(c["carry_anual"]), "roll_pct": _pct(c["roll"]),
             "tea_futura_pct": _pct(c["tea_futura"])}
            for c in carry.get("bonos", [])
        ],
        "mejor_carry": carry.get("mejor"),
        "breakevens": [
            {"lecap": p["lecap"], "cer": p["cer"], "meses": _f(p["meses_pendientes"], 1),
             "inflacion_mensual_breakeven_pct": _pct(p["breakeven_mensual"])}
            for p in pares
        ],
        "dolar": {
            "mep": valor("DOLAR MEP"), "ccl": valor("DOLAR CCL"), "oficial": valor("DOLAR OFICIAL"),
            "canje_pct": valor("CANJE"), "mep_ret_7d_pct": valor("DOLAR MEP", "ret_7d"),
            "mep_ret_mes_pct": valor("DOLAR MEP", "ret_mtd"),
        },
        "caucion_1d_tna_pct": _f(cau.get("tna_last"), 2),
        "riesgo_pais": {
            "bps": riesgo_pais.get("actual"), "zscore_60d": _f(riesgo_pais.get("zscore_actual"), 2),
            "percentil_60d": _f(riesgo_pais.get("percentil_actual"), 1),
            "cambio_mes_pct": _f(riesgo_pais.get("cambio_mes_pct"), 2),
            "clasificacion": riesgo_pais.get("clasificacion"),
        },
    }


def revisar(propuesta: dict, mesa: dict) -> tuple[str, list[str]]:
    """Oficial de Riesgo. Devuelve ("APROBADA" | "VETADA", motivos).
    Una propuesta de ESPERAR siempre pasa: no hay riesgo en no hacer nada.
    Un bono sin volumen del día (None o 0: el MCP antes de la apertura) se
    trata como ilíquido: el veto dice «sin dato», no «poco»."""
    L = LIMITES
    motivos: list[str] = []
    accion = str(propuesta.get("accion", "")).upper()
    if accion != "COMPRAR":
        return "APROBADA", ["ESPERAR: sin exposición nueva, nada que vetar"]

    tamano = float(propuesta.get("tamano_pct") or 0)
    conviccion = int(propuesta.get("conviccion") or 0)
    ticker = propuesta.get("bono")
    bono = next((b for b in mesa.get("bonos", []) if b["ticker"] == ticker), None)

    if bono is None:
        motivos.append(f"{ticker!r} no está en la curva de la mesa: no se puede comprar lo que no cotiza")
    if tamano > L["tamano_max_pct"]:
        motivos.append(f"tamaño {tamano:.1f}% supera el tope por nombre ({L['tamano_max_pct']:.1f}%)")
    if tamano <= 0:
        motivos.append("COMPRAR con tamaño 0 es incoherente: tiene que ser ESPERAR")
    if not 0 <= conviccion <= 100:
        motivos.append(f"convicción {conviccion} fuera de 0-100")
    elif conviccion < L["conviccion_min"]:
        motivos.append(f"convicción {conviccion} por debajo del mínimo ({L['conviccion_min']})")
    if bono is not None:
        liq = bono.get("monto_dia_usd")
        if not liq:
            motivos.append(f"{ticker} no tiene volumen del día (sin dato o 0): no se compra a ciegas")
        elif liq < L["liquidez_min_usd"]:
            motivos.append(f"{ticker} operó USD {liq:,.0f} en el día, menos del mínimo de liquidez (USD {L['liquidez_min_usd']:,.0f})")
        z = (mesa.get("riesgo_pais") or {}).get("zscore_60d") or 0
        md = bono.get("mod_duration") or 0
        if z > L["zscore_riesgo_pais_alerta"] and md > L["mod_duration_max_con_alerta"]:
            motivos.append(
                f"riesgo país en máximo (z={z:.2f} > {L['zscore_riesgo_pais_alerta']}) y {ticker} tiene "
                f"mod. duration {md:.2f} > {L['mod_duration_max_con_alerta']}: no se estira duration en estrés")

    return ("VETADA", motivos) if motivos else ("APROBADA", ["dentro de todos los límites"])
