"""Las piezas del modo mcp que se pueden probar SIN red: cómo se interpreta un
CallToolResult del SDK 2.3, el archivo de tokens y el servidor de callback."""
import json
import os
import stat
import threading
import urllib.request

import pytest

from puente import acaquant


def _resultado(texto=None, estructurado=None, error=False):
    from mcp import types
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=texto)] if texto is not None else [],
        structured_content=estructurado, is_error=error)


def test_interpretar_resultado_usa_los_campos_del_sdk_2():
    assert acaquant.interpretar_resultado("x", _resultado(estructurado={"total": 1})) == {"total": 1}
    assert acaquant.interpretar_resultado("x", _resultado(texto='{"total": 2}')) == {"total": 2}
    with pytest.raises(acaquant.ErrorHerramienta, match="rf_bono: no existe"):
        acaquant.interpretar_resultado("rf_bono", _resultado(texto="no existe", error=True))
    with pytest.raises(acaquant.ErrorHerramienta, match="no es JSON"):
        acaquant.interpretar_resultado("x", _resultado(texto="<html>"))


@pytest.mark.asyncio
async def test_tokens_en_archivo_privado_y_atados_a_la_url(tmp_path):
    from mcp.shared.auth import OAuthToken
    ruta = tmp_path / "cfg" / "tokens.json"
    st = acaquant._TokensEnArchivo(ruta, "https://a/mcp/", "http://127.0.0.1:1/callback")
    assert await st.get_tokens() is None
    await st.set_tokens(OAuthToken(access_token="t", token_type="Bearer"))
    assert (await st.get_tokens()).access_token == "t"
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600
    assert stat.S_IMODE(ruta.parent.stat().st_mode) == 0o700
    assert not list(ruta.parent.glob(".tokens-*"))  # sin temporales colgados
    # otra URL o redirect: el registro viejo no vale
    otro = acaquant._TokensEnArchivo(ruta, "https://b/mcp/", "http://127.0.0.1:1/callback")
    assert await otro.get_tokens() is None
    ruta.write_text("{corrupto")
    with pytest.raises(RuntimeError, match="corrupto"):
        await st.get_tokens()


def _puerto_libre():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_callback_ignora_otros_paths_y_devuelve_el_codigo():
    puerto = _puerto_libre()
    out = {}
    t = threading.Thread(target=lambda: out.update(acaquant._esperar_codigo_en_localhost(puerto, "/callback", 10)))
    t.start()
    import time
    time.sleep(0.3)
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"http://127.0.0.1:{puerto}/favicon.ico", timeout=5)
    assert e.value.code == 404
    r = urllib.request.urlopen(f"http://127.0.0.1:{puerto}/callback?code=abc&state=xyz&iss=https%3A%2F%2Fx", timeout=5)
    assert r.status == 200
    t.join(5)
    assert out == {"code": "abc", "state": "xyz", "iss": "https://x"}


def test_callback_se_rinde_si_nadie_vuelve():
    with pytest.raises(TimeoutError, match="sin que el login volviera"):
        acaquant._esperar_codigo_en_localhost(_puerto_libre(), "/callback", 1)


def test_oauth_provider_se_construye():
    assert type(acaquant._proveedor_oauth()).__name__ == "OAuthClientProvider"


def test_llamar_sync_en_mcp_no_toca_la_red_si_el_modo_es_fixtures(monkeypatch):
    monkeypatch.setenv("ACAQUANT_MODO", "fixtures")
    assert acaquant.llamar_sync("rf_breakevens")["total"] == 1
    assert os.environ["ACAQUANT_MODO"] == "fixtures" and json  # silencia F401
