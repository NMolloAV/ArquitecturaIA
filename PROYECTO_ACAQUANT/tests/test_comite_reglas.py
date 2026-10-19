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
    assert mesa["caucion_1d_tna"] == 18.6
    assert mesa["riesgo_pais"]["bps"] == 648 and mesa["riesgo_pais"]["zscore_60d"] == 1.87
    assert mesa["breakevens"][0]["lecap"] == "S29E7"


def test_esperar_siempre_pasa(mesa):
    assert revisar({"accion": "ESPERAR", "tamano_pct": 0, "conviccion": 30}, mesa)[0] == "APROBADA"


def test_compra_sana_corta_y_liquida_pasa(mesa):
    v, motivos = revisar({"accion": "COMPRAR", "bono": "S29E7", "tamano_pct": 1.5, "conviccion": 65}, mesa)
    assert v == "APROBADA", motivos


def test_veta_tamano_y_conviccion(mesa):
    v, motivos = revisar({"accion": "COMPRAR", "bono": "S29E7", "tamano_pct": 4.0, "conviccion": 40}, mesa)
    assert v == "VETADA"
    assert any("tope" in m for m in motivos) and any("convicción" in m for m in motivos)


def test_veta_bono_iliquido(mesa):
    # T30J7 operó USD 304k en el día del fixture: menos del mínimo
    v, motivos = revisar({"accion": "COMPRAR", "bono": "T30J7", "tamano_pct": 1.0, "conviccion": 70}, mesa)
    assert v == "VETADA" and any("liquidez" in m for m in motivos)


def test_veta_duration_larga_con_riesgo_pais_en_maximo(mesa):
    # z=1.87 en el fixture y T30J7 tiene mod. duration 0.544 > 0.5
    assert mesa["riesgo_pais"]["zscore_60d"] > LIMITES["zscore_riesgo_pais_alerta"]
    v, motivos = revisar({"accion": "COMPRAR", "bono": "T30J7", "tamano_pct": 1.0, "conviccion": 70}, mesa)
    assert any("duration" in m for m in motivos)


def test_veta_bono_que_no_esta_en_la_mesa(mesa):
    v, motivos = revisar({"accion": "COMPRAR", "bono": "AL30", "tamano_pct": 1.0, "conviccion": 80}, mesa)
    assert v == "VETADA" and "no está en la curva" in motivos[0]
