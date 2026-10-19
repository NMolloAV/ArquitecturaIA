"""El Oficial de Riesgo y la compactación de la mesa, sobre los fixtures reales."""
import pytest

from labs.comite_reglas import LIMITES, armar_mesa, revisar
from puente.acaquant import llamar_sync


@pytest.fixture
def mesa(monkeypatch):
    monkeypatch.setenv("ACAQUANT_MODO", "fixtures")
    return armar_mesa(
        llamar_sync("rf_curva", curva="tasa_fija"),
        llamar_sync("trading_carry", curva="tasa_fija", horizonte_meses=3),
        llamar_sync("rf_breakevens"),
        llamar_sync("dolar_panel"),
        llamar_sync("caucion", moneda="ARS"),
        llamar_sync("macro_serie", variable="riesgo_pais", ventana_dias=60),
    )


def test_la_mesa_es_chica_y_tiene_lo_que_leen_los_analistas(mesa):
    assert [b["ticker"] for b in mesa["bonos"]][:3] == ["S30O6", "TZXO6", "TX26"]
    assert mesa["mejor_carry"] == "S29E7"
    assert mesa["dolar"]["mep"] == 1540.3109 and mesa["dolar"]["oficial"] == 1524.5
    assert mesa["caucion_1d_tna_pct"] == 18.6
    assert mesa["riesgo_pais"]["bps"] == 648 and mesa["riesgo_pais"]["zscore_60d"] == 1.87
    assert mesa["breakevens"][0]["lecap"] == "S29E7"


def test_todo_en_porcentaje_y_cada_fuente_con_su_fecha(mesa):
    s29 = next(b for b in mesa["bonos"] if b["ticker"] == "S29E7")
    assert s29["tea_pct"] == 26.31 and s29["tem_pct"] == 1.97          # el MCP da 0.263098 / 0.019655
    assert mesa["carry_3m"][0]["carry_anual_pct"] == 33.49               # 0.334938
    assert mesa["breakevens"][0]["inflacion_mensual_breakeven_pct"] == 1.74
    assert mesa["fechas"] == {"precios_curva": "2026-10-19", "riesgo_pais": "2026-10-16"}
    assert "_pct" in mesa["unidades"]


def test_armar_mesa_aguanta_bonos_sin_metricas():
    curva = {"filas": [
        {"ticker_corto": "X", "fecha_vencimiento": "2027-01-01", "tea": 0.2},   # sin tem, duration ni monto
        {"ticker_corto": "Y", "fecha_vencimiento": "2027-01-01", "tea": None},  # sin tea: afuera
    ]}
    mesa = armar_mesa(curva, {}, {}, {}, {}, {})
    assert [b["ticker"] for b in mesa["bonos"]] == ["X"]
    assert mesa["bonos"][0]["monto_dia_usd"] is None and mesa["fechas"]["precios_curva"] is None


def test_esperar_siempre_pasa(mesa):
    assert revisar({"accion": "ESPERAR", "tamano_pct": 0, "conviccion": 30}, mesa)[0] == "APROBADA"


def test_compra_sana_corta_y_liquida_pasa(mesa):
    v, motivos = revisar({"accion": "COMPRAR", "bono": "S29E7", "tamano_pct": 1.5, "conviccion": 65}, mesa)
    assert v == "APROBADA", motivos


def test_veta_tamano_y_conviccion(mesa):
    v, motivos = revisar({"accion": "COMPRAR", "bono": "S29E7", "tamano_pct": 4.0, "conviccion": 40}, mesa)
    assert v == "VETADA"
    assert any("tope" in m for m in motivos) and any("convicción" in m for m in motivos)
    assert "fuera de 0-100" in revisar({"accion": "COMPRAR", "bono": "S29E7", "tamano_pct": 1, "conviccion": 150}, mesa)[1][0]


def test_veta_bono_iliquido_y_sin_volumen(mesa):
    # T30J7 operó USD 304k en el día del fixture: menos del mínimo
    v, motivos = revisar({"accion": "COMPRAR", "bono": "T30J7", "tamano_pct": 1.0, "conviccion": 70}, mesa)
    assert v == "VETADA" and any("liquidez" in m for m in motivos)
    sin_vol = {"bonos": [{"ticker": "Z", "monto_dia_usd": None, "mod_duration": 0.1}], "riesgo_pais": {}}
    v, motivos = revisar({"accion": "COMPRAR", "bono": "Z", "tamano_pct": 1.0, "conviccion": 70}, sin_vol)
    assert v == "VETADA" and "sin dato" in motivos[0]


def test_veta_duration_larga_con_riesgo_pais_en_maximo(mesa):
    # z=1.87 en el fixture y T30J7 tiene mod. duration 0.544 > 0.5
    assert mesa["riesgo_pais"]["zscore_60d"] > LIMITES["zscore_riesgo_pais_alerta"]
    _, motivos = revisar({"accion": "COMPRAR", "bono": "T30J7", "tamano_pct": 1.0, "conviccion": 70}, mesa)
    assert any("duration" in m for m in motivos)


def test_veta_bono_que_no_esta_en_la_mesa(mesa):
    v, motivos = revisar({"accion": "COMPRAR", "bono": "AL30", "tamano_pct": 1.0, "conviccion": 80}, mesa)
    assert v == "VETADA" and "no está en la curva" in motivos[0]
