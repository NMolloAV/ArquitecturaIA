"""puente/acaquant.py — AcaQuant como PROVEEDOR DE DATOS de los labs.

Una sola puerta: `llamar(nombre_de_herramienta, **argumentos)`. Devuelve el
MISMO JSON que la herramienta del MCP de mercado de AcaQuant (`/mcp`,
docs/MCP.md del backend), con dos modos elegidos por ACAQUANT_MODO:

  fixtures  (default) lee `puente/fixtures/<clave>.json`: una captura REAL
            del MCP, fuera de rueda (último cierre). Sin red, sin login, sin
            tokens: es el modo de los labs y de los tests. VERIFICADO.
  mcp       llama en vivo a https://api.acaquant.com/mcp con el SDK oficial
            `mcp` (Streamable HTTP) y el OAuth de Cloudflare Access: la
            primera vez abre el navegador para loguearse (hace falta ser
            ADMIN de AcaQuant: el backend contesta 403 a cualquier otro rol);
            el token queda en ~/.config/acaquant_mcp/tokens.json.
            HIPÓTESIS SIN MEDIR: está escrito contra las firmas del SDK
            `mcp` 2.3 y contra docs/MCP.md, pero nunca se corrió de punta a
            punta. Probarlo con `python -m puente.diag_conexion`.

El lab no sabe en qué modo corre: misma función, misma forma de respuesta.
En modo mcp se abre UNA sesión por proceso y se comparte (varias llamadas en
paralelo no disparan varios logins).
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).parent / "fixtures"
URL_MCP = os.environ.get("ACAQUANT_MCP_URL", "https://api.acaquant.com/mcp/")
PUERTO_CALLBACK = int(os.environ.get("ACAQUANT_OAUTH_PUERTO", "8765"))
RUTA_CALLBACK = "/callback"
ESPERA_LOGIN_SEG = int(os.environ.get("ACAQUANT_OAUTH_ESPERA_SEG", "300"))
ARCHIVO_TOKENS = Path(os.environ.get(
    "ACAQUANT_TOKENS", Path.home() / ".config" / "acaquant_mcp" / "tokens.json"))


class FixtureFaltante(FileNotFoundError):
    """No hay captura para esa herramienta con esos argumentos."""


class ErrorHerramienta(RuntimeError):
    """La herramienta del MCP contestó con error (is_error)."""


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
def _escribir_privado(ruta: Path, texto: str) -> None:
    """Archivo 0600 desde que nace (no después), en un directorio 0700, y
    escritura atómica: nunca queda un JSON a medias."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.parent.chmod(0o700)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=".tokens-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
        os.replace(tmp, ruta)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class _TokensEnArchivo:
    """Donde el SDK guarda el registro del cliente y los tokens, para no
    loguearse en cada corrida. Implementa `mcp.client.auth.TokenStorage`.
    Guarda también a qué URL y redirect corresponden: si cambian, se descarta
    el registro viejo en vez de fallar de forma confusa."""

    def __init__(self, ruta: Path, url: str, redirect: str) -> None:
        self.ruta, self.url, self.redirect = ruta, url, redirect

    def _leer(self) -> dict:
        if not self.ruta.exists():
            return {}
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"{self.ruta} está corrupto ({e}); borralo y volvé a loguearte") from e
        if datos.get("url") != self.url or datos.get("redirect") != self.redirect:
            return {}
        return datos

    def _escribir(self, clave: str, valor: dict | None) -> None:
        datos = self._leer()
        datos.update({"url": self.url, "redirect": self.redirect, clave: valor})
        _escribir_privado(self.ruta, json.dumps(datos))

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
    print(f"[oauth] Abrí esta URL en el navegador y logueate con tu email de AcaQuant (rol admin):\n  {url}")
    webbrowser.open(url)


def _esperar_codigo_en_localhost(puerto: int, ruta: str, espera_seg: int) -> dict:
    """Servidor HTTP en 127.0.0.1:<puerto> que espera el redirect del login en
    <ruta> con `?code=...&state=...`. Cualquier otro pedido (favicon, prefetch)
    recibe 404 y no cuenta. Se rinde a los `espera_seg` segundos."""
    recibido: dict = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (nombre que exige http.server)
            u = urlparse(self.path)
            if u.path != ruta:
                self.send_response(404)
                self.end_headers()
                return
            q = parse_qs(u.query)
            recibido.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h3>Listo: ya podés volver a la terminal.</h3>".encode())

        def log_message(self, *_):  # silencio
            pass

    with HTTPServer(("127.0.0.1", puerto), _Handler) as srv:
        srv.timeout = 1  # cada handle_request() vuelve al segundo: así se puede contar
        for _ in range(espera_seg):
            srv.handle_request()
            if "code" in recibido or "error" in recibido:
                return recibido
    raise TimeoutError(f"pasaron {espera_seg}s sin que el login volviera a http://127.0.0.1:{puerto}{ruta}")


async def _esperar_callback():
    from mcp.client.auth import AuthorizationCodeResult
    r = await asyncio.to_thread(_esperar_codigo_en_localhost, PUERTO_CALLBACK, RUTA_CALLBACK, ESPERA_LOGIN_SEG)
    if "error" in r:
        raise RuntimeError(f"OAuth rechazado: {r.get('error')} {r.get('error_description', '')}")
    return AuthorizationCodeResult(code=r["code"], state=r.get("state"), iss=r.get("iss"))


def _proveedor_oauth():
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata
    redirect = f"http://127.0.0.1:{PUERTO_CALLBACK}{RUTA_CALLBACK}"
    return OAuthClientProvider(
        server_url=URL_MCP,
        client_metadata=OAuthClientMetadata(
            client_name="labs-arquitectura-ia",
            redirect_uris=[redirect],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=_TokensEnArchivo(ARCHIVO_TOKENS, URL_MCP, redirect),
        redirect_handler=_abrir_navegador,
        callback_handler=_esperar_callback,
    )


def interpretar_resultado(nombre: str, r: Any) -> Any:
    """`CallToolResult` del SDK 2.3 -> el JSON de la herramienta. Separado
    para poder testearlo con un resultado armado a mano."""
    if getattr(r, "is_error", False):
        raise ErrorHerramienta(f"{nombre}: " + " ".join(
            getattr(c, "text", "") for c in getattr(r, "content", [])))
    estructurado = getattr(r, "structured_content", None)
    if estructurado is not None:
        return estructurado
    texto = "".join(getattr(c, "text", "") for c in getattr(r, "content", []))
    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        raise ErrorHerramienta(f"{nombre}: la respuesta no es JSON: {texto[:200]!r}") from e


class SesionMCP:
    """`async with SesionMCP() as s: await s.llamar("rf_curva", curva="cer")`.
    Una conexión para muchas llamadas. `llamar()` (abajo) la abre una vez por
    proceso y la comparte."""

    def __init__(self) -> None:
        self._pila = None
        self._sesion = None

    async def __aenter__(self):
        import httpx2  # el SDK `mcp` 2.x usa httpx2, no httpx: el Timeout tiene que ser de esa librería
        from contextlib import AsyncExitStack
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        self._pila = AsyncExitStack()
        try:
            http = create_mcp_http_client(auth=_proveedor_oauth(), timeout=httpx2.Timeout(90.0))
            await self._pila.enter_async_context(http)
            lectura, escritura = await self._pila.enter_async_context(
                streamable_http_client(URL_MCP, http_client=http))
            self._sesion = await self._pila.enter_async_context(ClientSession(lectura, escritura))
            await self._sesion.initialize()
        except BaseException:
            await self._pila.aclose()  # si falla a mitad, no quedan conexiones colgadas
            raise
        return self

    async def __aexit__(self, *exc):
        await self._pila.aclose()

    async def herramientas(self) -> list[str]:
        r = await self._sesion.list_tools()
        return sorted(t.name for t in r.tools)

    async def llamar(self, nombre: str, **args: Any) -> Any:
        args = {k: v for k, v in args.items() if v is not None}
        return interpretar_resultado(nombre, await self._sesion.call_tool(nombre, args))


# Una sesión por proceso (y por event loop): 6 llamadas en paralelo = 1 login.
_compartida: dict[str, Any] = {"loop": None, "sesion": None, "lock": None}


async def _sesion_compartida() -> SesionMCP:
    loop = asyncio.get_running_loop()
    if _compartida["loop"] is not loop:
        _compartida.update({"loop": loop, "sesion": None, "lock": asyncio.Lock()})
    async with _compartida["lock"]:
        if _compartida["sesion"] is None:
            _compartida["sesion"] = await SesionMCP().__aenter__()
    return _compartida["sesion"]


async def cerrar() -> None:
    """Cierra la sesión compartida (el lab la llama al terminar)."""
    s = _compartida["sesion"]
    if s is not None and _compartida["loop"] is asyncio.get_running_loop():
        _compartida["sesion"] = None
        await s.__aexit__(None, None, None)


# ----------------------------------------------------------------------------
# La puerta única
# ----------------------------------------------------------------------------
async def llamar(nombre: str, **args: Any) -> Any:
    """La misma herramienta del MCP, en el modo que diga ACAQUANT_MODO."""
    if modo() == "fixtures":
        return _leer_fixture(nombre, args)
    s = await _sesion_compartida()
    return await s.llamar(nombre, **args)


def llamar_sync(nombre: str, **args: Any) -> Any:
    """Para scripts y tests sin asyncio. Dentro de un loop (ADK, notebooks)
    usar `await llamar(...)`. En modo mcp abre y cierra una sesión por llamada."""
    if modo() == "fixtures":
        return _leer_fixture(nombre, args)

    async def _una():
        async with SesionMCP() as s:
            return await s.llamar(nombre, **args)
    return asyncio.run(_una())
