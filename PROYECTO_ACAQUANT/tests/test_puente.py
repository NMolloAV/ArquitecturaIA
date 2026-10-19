"""El puente en modo fixtures: sin red, sin keys."""

import pytest

from puente import acaquant


@pytest.fixture(autouse=True)
def _modo_fixtures(monkeypatch):
    monkeypatch.setenv("ACAQUANT_MODO", "fixtures")


def test_clave_no_depende_del_orden_ni_de_los_none():
    assert acaquant.clave_fixture("rf_curva", {"curva": "cer"}) == "rf_curva__curva-cer"
    assert acaquant.clave_fixture("trading_carry", {"horizonte_meses": 3, "curva": "tasa_fija"}) == \
        "trading_carry__curva-tasa_fija_horizonte_meses-3"
    assert acaquant.clave_fixture("trading_medias", {"ticker": None}) == "trading_medias"


@pytest.mark.parametrize("nombre,args,chequeo", [
    ("rf_curva", {"curva": "tasa_fija"}, lambda d: d["total"] == 10 and d["filas"][0]["ticker_corto"] == "S30O6"),
    ("rf_curva", {"curva": "cer"}, lambda d: all(f["emisor_tipo"] == "soberano" for f in d["filas"])),
    ("trading_carry", {"curva": "tasa_fija", "horizonte_meses": 3}, lambda d: d["mejor"] == "S29E7"),
    ("rf_breakevens", {}, lambda d: len(d["filas"][0]["pares"]) == 2),
    ("dolar_panel", {}, lambda d: {f["label"] for f in d["filas"]} >= {"DOLAR MEP", "DOLAR CCL", "RIESGO PAÍS"}),
    ("caucion", {"moneda": "ARS"}, lambda d: d["filas"][0]["plazo_dias"] == 1),
    ("macro_serie", {"variable": "riesgo_pais", "ventana_dias": 60}, lambda d: d["n_observaciones"] == len(d["serie"])),
    ("trading_medias", {}, lambda d: {"AAPL", "GGAL", "MELI"} <= {f["ticker"] for f in d["filas"]}),
])
def test_cada_fixture_tiene_la_forma_de_la_herramienta(nombre, args, chequeo):
    assert chequeo(acaquant.llamar_sync(nombre, **args))


def test_fixture_faltante_dice_como_capturarlo():
    with pytest.raises(acaquant.FixtureFaltante, match="--capturar rf_curva curva=dual"):
        acaquant.llamar_sync("rf_curva", curva="dual")


def test_modo_invalido_explota_antes_de_llamar(monkeypatch):
    monkeypatch.setenv("ACAQUANT_MODO", "prod")
    with pytest.raises(ValueError):
        acaquant.modo()
