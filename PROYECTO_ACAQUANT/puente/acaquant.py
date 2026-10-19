"""puente/acaquant.py — AcaQuant como PROVEEDOR DE DATOS de los labs.

Una sola puerta: `llamar(nombre_de_herramienta, **argumentos)`. Devuelve el
MISMO JSON que la herramienta del MCP de mercado de AcaQuant (`/mcp`,
docs/MCP.md del backend), con dos modos elegidos por ACAQUANT_MODO:

  fixtures  (default) lee `puente/fixtures/<clave>.json`: una captura REAL
            del MCP del 2026-10-19, fuera de rueda (último cierre). Sin red,
            sin login, sin tokens: es el modo de los labs y de los tests.
  mcp       llama en vivo a https://api.acaquant.com/mcp con el SDK oficial
            `mcp` (Streamable HTTP) y el OAuth de Cloudflare Access: la
            primera vez abre el navegador para loguearse; el token queda en
            ~/.config/acaquant_mcp/tokens.json. Probar primero con
            `python -m puente.diag_conexion`.

El lab no sabe en qué modo corre: misma función, misma forma de respuesta.
El MCP de mercado es SOLO LECTURA y no tiene nada del negocio de la mesa
(clientes, carteras, operaciones): acá no puede entrar un dato privado.
"""
from __future__ import annotations

import asyncio
import json
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).parent / "fixtures"
URL_MCP = os.environ.get("ACAQUANT_MCP_URL", "https://api.acaquant.com/mcp/")
PUERTO_CALLBACK = int(os.environ.get("ACAQUANT_OAUTH_PUERTO", "8765"))
ARCHIVO_TOKENS = Path(os.environ.get(
    "ACAQUANT_TOKENS", Path.home() / ".config" / "acaquant_mcp" / "tokens.json"))


class FixtureFaltante(FileNotFoundError):
    """No hay captura para esa herramienta con esos argumentos."""


def modo() -> str:
    m = os.environ.get("ACAQUANT_MODO", "fixtures").strip().lower()
    if m not in ("fixtures", "mcp"):
        raise ValueError(f"ACAQUANT_MODO={m!r}: tiene que ser 'fixtures' o 'mcp'")
    return m


def clave_fixture(nombre: str, args: dict[str, Any]) -> str:
    """`rf_curva` + {curva: cer} -> `rf_curva__curva-cer`. Los argumentos van
    ordenados por nombre para que la clave no dependa del orden de llamada."""
    usados = {k: v for k, v in sorted(args.items()) if v is not None}
    if not usados:
        return nombre
    return nombre + "__" + "_".join(f"{k}-{v}" for k, v in usados.items())


# ----------------------------------------------------------------------------
# Modo fixtures
# ----------------------------------------------------------------------------
def _leer_fixture(nombre: str, args: dict[str, Any]) -> Any:
    ruta = FIXTURES / f"{clave_fixture(nombre, args)}.json"
    if not ruta.exists():
        disponibles = ", ".join(sorted(p.stem for p in FIXTURES.glob("*.json")))
        raise FixtureFaltante(
            f"No hay fixture {ruta.name}. Disponibles: {disponibles}. Para capturarlo "
            f"en vivo: python -m puente.diag_conexion --capturar {nombre} "
            + " ".join(f"{k}={v}" for k, v in args.items() if v is not None))
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)


def guardar_fixture(nombre: str, args: dict[str, Any], datos: Any) -> Path:
    ruta = FIXTURES / f"{clave_fixture(nombre, args)}.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return ruta


# ----------------------------------------------------------------------------
# Modo mcp: OAuth (Cloudflare Access, Managed OAuth) + Streamable HTTP
# ----------------------------------------------------------------------------
class _TokensEnArchivo:
    """Donde el SDK guarda el registro del cliente y los tokens, para no
    loguearse en cada corrida. Implementa `mcp.client.auth.TokenStorage`."""

    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta

    def _leer(self) -> dict:
        if not self.ruta.exists():
            return {}
        return json.loads(self.ruta.read_text(encoding="utf-8"))

    def _escribir(self, clave: str, valor: dict | None) -> None:
        datos = self._leer()
        datos[clave] = valor
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(json.dumps(datos), encoding="utf-8")
        self.ruta.chmod(0o600)

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken
        t = self._leer().get("tokens")
        return OAuthToken.model_validate(t) if t else None

    async def set_tokens(self, tokens) -> None:
        self._escribir("tokens", tokens.model_dump(mode="json"))

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull
        c = self._leer().get("cliente")
        return OAuthClientInformationFull.model_validate(c) if c else None

    async def set_client_info(self, info) -> None:
        self._escribir("cliente", info.model_dump(mode="json"))


async def _abrir_navegador(url: str) -> None:
    print(f"[oauth] Abrí esta URL en el navegador y logueate con tu email de AcaQuant:\n  {url}")
    webbrowser.open(url)


def _esperar_codigo_en_localhost(puerto: int) -> dict:
    """Levanta un servidor HTTP de UNA sola respuesta en 127.0.0.1:<puerto> y
    espera el redirect del login con `?code=...&state=...`."""
    recibido: dict = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (nombre que exige http.server)
            q = parse_qs(urlparse(self.path).query)
            recibido.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h3>Listo: ya podés volver a la terminal.</h3>".encode())

        def log_message(self, *_):  # silencio
            pass

    with HTTPServer(("127.0.0.1", puerto), _Handler) as srv:
        while "code" not in recibido and "error" not in recibido:
            srv.handle_request()
    return recibido


async def _esperar_callback():
    from mcp.client.auth import AuthorizationCodeResult
    r = await asyncio.to_thread(_esperar_codigo_en_localhost, PUERTO_CALLBACK)
    if "error" in r:
        raise RuntimeError(f"OAuth rechazado: {r.get('error')} {r.get('error_description', '')}")
    return AuthorizationCodeResult(code=r["code"], state=r.get("state"))


def _proveedor_oauth():
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata
    return OAuthClientProvider(
        server_url=URL_MCP,
        client_metadata=OAuthClientMetadata(
            client_name="labs-arquitectura-ia",
            redirect_uris=[f"http://127.0.0.1:{PUERTO_CALLBACK}/callback"],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=_TokensEnArchivo(ARCHIVO_TOKENS),
        redirect_handler=_abrir_navegador,
        callback_handler=_esperar_callback,
    )


class SesionMCP:
    """`async with SesionMCP() as s: await s.llamar("rf_curva", curva="cer")`.
    Una conexión para varias llamadas (el lab abre una por corrida)."""

    def __init__(self) -> None:
        self._pila = None
        self._sesion = None

    async def __aenter__(self):
        import httpx
        from contextlib import AsyncExitStack
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        self._pila = AsyncExitStack()
        http = create_mcp_http_client(auth=_proveedor_oauth(), timeout=httpx.Timeout(90.0))
        await self._pila.enter_async_context(http)
        lectura, escritura = await self._pila.enter_async_context(
            streamable_http_client(URL_MCP, http_client=http))
        self._sesion = await self._pila.enter_async_context(ClientSession(lectura, escritura))
        await self._sesion.initialize()
        return self

    async def __aexit__(self, *exc):
        await self._pila.aclose()

    async def herramientas(self) -> list[str]:
        r = await self._sesion.list_tools()
        return sorted(t.name for t in r.tools)

    async def llamar(self, nombre: str, **args: Any) -> Any:
        args = {k: v for k, v in args.items() if v is not None}
        r = await self._sesion.call_tool(nombre, args)
        if getattr(r, "isError", False):
            raise RuntimeError(f"{nombre}: " + " ".join(
                getattr(c, "text", "") for c in getattr(r, "content", [])))
        estructurado = getattr(r, "structuredContent", None)
        if estructurado is not None:
            return estructurado
        texto = "".join(getattr(c, "text", "") for c in r.content)
        return json.loads(texto)


# ----------------------------------------------------------------------------
# La puerta única
# ----------------------------------------------------------------------------
async def llamar(nombre: str, **args: Any) -> Any:
    """La misma herramienta del MCP, en el modo que diga ACAQUANT_MODO."""
    if modo() == "fixtures":
        return _leer_fixture(nombre, args)
    async with SesionMCP() as s:
        return await s.llamar(nombre, **args)


def llamar_sync(nombre: str, **args: Any) -> Any:
    """Para scripts y tests sin asyncio. Dentro de un loop (ADK, notebooks)
    usar `await llamar(...)`."""
    if modo() == "fixtures":
        return _leer_fixture(nombre, args)
    return asyncio.run(llamar(nombre, **args))
