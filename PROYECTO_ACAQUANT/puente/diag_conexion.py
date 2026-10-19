"""Prueba la conexión EN VIVO al MCP de mercado de AcaQuant y, si se pide,
captura una herramienta como fixture. Salida compartible: conteos y veredictos.

  python -m puente.diag_conexion
  python -m puente.diag_conexion --capturar rf_curva curva=cer
  python -m puente.diag_conexion --capturar trading_carry curva=cer horizonte_meses=6

Qué tiene que pasar la primera vez: se abre el navegador, Cloudflare Access
pide el email + código, y vuelve a http://127.0.0.1:8765/callback. Para eso
la app `acaquant-mcp` de Access tiene que tener prendido «Allow localhost /
loopback clients» (docs/MCP.md del backend) y el email tiene que ser ADMIN de
AcaQuant (si no, el backend contesta 403). Si algo falla, el error llega acá.

OJO con `--capturar`: guarda lo que devuelva CUALQUIER herramienta del MCP en
puente/fixtures/ y eso se commitea. El MCP no tiene datos de clientes, pero sí
cálculos propios de AcaQuant y texto libre de la mesa (trading_ideas): antes
de commitear un fixture nuevo, abrilo y decidí si puede ir a un repo.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback

from dotenv import load_dotenv

load_dotenv()
os.environ["ACAQUANT_MODO"] = "mcp"

from puente.acaquant import ARCHIVO_TOKENS, URL_MCP, SesionMCP, guardar_fixture  # noqa: E402


def _valor(v: str):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    for tipo in (int, float):
        try:
            return tipo(v)
        except ValueError:
            pass
    return v


def _parsear_args(pares: list[str]) -> dict:
    out = {}
    for p in pares:
        k, _, v = p.partition("=")
        out[k] = _valor(v)
    return out


async def main(argv: list[str]) -> int:
    print(f"[1] URL: {URL_MCP}")
    print(f"[2] tokens guardados: {'sí' if ARCHIVO_TOKENS.exists() else 'no (va a abrir el navegador)'} ({ARCHIVO_TOKENS})")
    t0 = time.perf_counter()
    try:
        async with SesionMCP() as s:
            print(f"[3] sesión MCP inicializada en {time.perf_counter() - t0:.1f}s")
            nombres = await s.herramientas()
            print(f"[4] herramientas: {len(nombres)} (ej. {', '.join(nombres[:5])}…)")
            if "--capturar" in argv:
                i = argv.index("--capturar")
                nombre, args = argv[i + 1], _parsear_args(argv[i + 2:])
                datos = await s.llamar(nombre, **args)
                ruta = guardar_fixture(nombre, args, datos)
                print(f"[5] capturado {nombre} {args} -> {ruta.name} ({ruta.stat().st_size:,} bytes). "
                      "Revisalo antes de commitearlo.")
            else:
                curva = await s.llamar("rf_curva", curva="tasa_fija")
                print(f"[5] rf_curva(tasa_fija): {curva.get('total')} filas, truncado={curva.get('truncado')}")
    except Exception as e:  # el diag existe para ver ESTE error
        print(f"[X] falló: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1
    print("[OK] la conexión viva anda: podés correr los labs con ACAQUANT_MODO=mcp")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
