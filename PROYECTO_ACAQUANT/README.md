# PROYECTO_ACAQUANT — el curso, el libro y AcaQuant en un solo lugar

Acá se juntan las tres cosas que estoy haciendo en paralelo:

| Fuente | Rol en este proyecto | Qué aporta |
|---|---|---|
| **Curso UTDT** (este repo, `MODULO_*`) | el **cómo**: la herramienta | Google ADK 2 (Workflow, JoinNode, agentes tipados, MCP, RAG, memoria), Gemini con key gratuita |
| **Libro** *Building AI Agents for Finance* (repo hermano `../AI-Agents-for-FINANCE`) | el **qué**: los patrones de finanzas | comité de inversión, debate adversarial, deep search, agentic RAG, guardrails, observabilidad, evaluación |
| **AcaQuant** (`../acaquant-backend`, prod en `api.acaquant.com`) | el **con qué**: los datos | mercado argentino real por MCP (`/mcp`, solo lectura): curvas, carry, breakevens, dólar, caución, riesgo país, CEDEARs, opciones, agro, MAV |

La regla de este proyecto: **AcaQuant es proveedor de datos, no el objetivo.** Nada de lo que
se arma acá toca el backend ni la base; se le pide datos por la puerta que ya existe (el MCP de
mercado) y se experimenta afuera. Si algún experimento demuestra valor, recién ahí se piensa cómo
entra a AcaQuant (y eso es otra conversación, con sus reglas).

## Cómo está armado

```
PROYECTO_ACAQUANT/
  puente/                 AcaQuant como proveedor de datos (UNA sola puerta: `llamar`)
    acaquant.py           dos modos: fixtures (captura real, offline) | mcp (vivo, OAuth de Cloudflare Access)
    fixtures/*.json       captura REAL del MCP del 2026-10-19 (fuera de rueda = último cierre)
    tools_adk.py          las mismas herramientas como FunctionTool de ADK, para agentes ReAct
    diag_conexion.py      prueba la conexión viva y captura fixtures nuevos
  labs/
    comite_reglas.py      lo del comité que es CÓDIGO: compactar la mesa y el oficial de riesgo (testeado)
    01_comite_renta_fija.py   Lab 01 (ver abajo)
  tests/                  offline: sin red, sin keys
```

### El puente, en una frase

`await llamar("rf_curva", curva="tasa_fija")` devuelve **el mismo JSON** que la herramienta
`rf_curva` del MCP de AcaQuant, y el lab no sabe si vino de un archivo o de prod:

| `ACAQUANT_MODO` | De dónde salen los datos | Para qué |
|---|---|---|
| `fixtures` (default) | `puente/fixtures/<herramienta>__<args>.json`, capturados en vivo | desarrollar, correr los labs mil veces, tests, CI |
| `mcp` | `https://api.acaquant.com/mcp` con el SDK oficial `mcp` + login de Cloudflare Access en el navegador | ver el comité opinar sobre el mercado de HOY |

Por diseño, el MCP de mercado **no tiene nada del negocio de la mesa** (clientes, carteras,
operaciones, P&L): acá no puede entrar un dato privado, y los fixtures se pueden commitear.

## Setup (una vez)

```bash
cd PROYECTO_ACAQUANT
./setup.sh                 # .venv + requirements + .env desde .env.example + corre los tests
# editá .env y pegá tu GOOGLE_API_KEY (https://aistudio.google.com/apikey)
./run.sh 1                 # Lab 01 con los fixtures
```

Python 3.10+ (probado con 3.13), `google-adk==2.9.1` (la versión del Módulo 5) y `mcp>=2.3`.

### Modo vivo (opcional)

```bash
./run.sh diag              # abre el navegador, logueate con tu email de AcaQuant, y prueba rf_curva
./run.sh diag --capturar trading_carry curva=cer horizonte_meses=6   # guarda un fixture nuevo
ACAQUANT_MODO=mcp ./run.sh 1
```

**PENDIENTE (lo tiene que hacer el admin de Cloudflare, una sola vez):** en la app `acaquant-mcp`
de Access, Advanced settings → Managed OAuth → **Allow localhost / loopback clients: ON**. Sin eso
el login no puede volver a `http://127.0.0.1:8765/callback` y `./run.sh diag` lo va a mostrar como
error. Hasta correr el diag, el modo vivo es **hipótesis sin medir**: el cliente está escrito contra
la API del SDK `mcp` 2.3 y el flujo OAuth documentado en `docs/MCP.md` del backend, pero no se probó
de punta a punta. El modo fixtures sí está verificado (los tests corren sobre la captura real).

## Lab 01 — Comité de inversión en pesos

Es el **Investment Committee del libro (cap. 8)** —analistas en paralelo → Portfolio Manager →
Risk Officer con reglas duras— implementado con la **topología del Módulo 5 del curso** (Graph
Workflow de ADK 2: `JoinNode`, router por reglas, agentes con `input_schema`/`output_schema`), y
mirando la **curva de tasa fija argentina** en vez de un ticker de Yahoo.

```
START → cargar_mesa (0 tokens: 6 llamadas al puente en paralelo, compactadas por comite_reglas.armar_mesa)
      → [analista_curva, analista_macro]   (2 LLM en paralelo, cada uno un Informe tipado)
      → join → portfolio_manager            (1 LLM: Propuesta tipada: COMPRAR <bono> / ESPERAR, tamaño, convicción)
      → join → oficial_riesgo               (0 tokens: comite_reglas.revisar)
      → APROBADA | VETADA
```

Qué enseña, y dónde se ve:

- **Los números los calcula AcaQuant, no el modelo.** TEA, duration, carry, breakevens, z-score
  del riesgo país llegan hechos. El modelo *lee* y *argumenta*; si inventa un número, el contrato
  Pydantic y el oficial de riesgo lo frenan (un ticker que no está en la mesa = veto).
- **El veto vive en código y es auditable** (`labs/comite_reglas.py::revisar`): tope por nombre,
  convicción mínima, liquidez mínima en USD y «con riesgo país en máximo no se estira duration».
  Los límites son didácticos, no una política de riesgo real, y cada veto dice exactamente por qué.
- **Cuánto cuesta**: 3 llamadas al modelo por corrida (los dos analistas van en paralelo), todo lo
  demás es código. Con la key gratuita de AI Studio alcanza de sobra.
- **Reproducible**: con `fixtures` los datos son siempre los mismos (2026-10-19); lo único que
  cambia entre corridas es lo que dice el modelo, igual que en los labs del Módulo 2.

Diferencias a propósito con el libro: dos analistas en vez de cuatro (no hay noticias ni
fundamentals de un bono; curva y macro es lo que mira una mesa de pesos), un solo modelo (Gemini
Flash) en vez de tres familias, y **sin backtest** — el `backtest.py` del cap. 8 admite que sus
fetchers no son point-in-time, y acá tampoco: los fixtures son una foto.

## Hoja de ruta (los próximos labs, en orden)

| Lab | Patrón del libro | Técnica del curso | Datos de AcaQuant |
|---|---|---|---|
| 02 Analista ReAct | cap. 6 ReAct · cap. 2 tools | `Agent(tools=puente.tools_adk.TODAS)`, `adk web` (Mód. 4) | el modelo elige qué pedir: curva, carry, dólar, medias |
| 03 Debate adversarial | cap. 8 Bull / Bear / Juez | Collaborative/Swarm (Mód. 5 caso 2), dos modelos distintos vía LiteLLM (Tutorial 0) | la propuesta aprobada del Lab 01 como input |
| 04 Deep search de un bono | cap. 5 planner → researcher → validator → synthesizer | Dynamic Workflow con `@node` y recursión (Mód. 5 caso 3) | `rf_bono`, `rf_fair_value`, `macro_serie`, breakevens |
| 05 RAG sobre research | cap. 10 agentic RAG | FAISS + BM25 híbrido, GraphRAG (Mód. 6) | la auditoría que ya traen las herramientas (`auditoria`) + research propio |
| 06 Guardrails y trazas | cap. 12 guardrails, observabilidad, costo | callbacks de ADK (Tutorial 0), `session.state` (Mód. 6) | el Lab 01 instrumentado: tokens, latencia, qué herramienta pidió cada agente |
| 07 Evaluación | cap. 11 harness de evaluación | eval set con casos de veto esperados, igual que `evals/` del backend | las mismas fixtures, con propuestas conocidas |

Cada lab nuevo agrega lo mínimo: una herramienta al puente si falta (`./run.sh diag --capturar …`
para el fixture) y un archivo en `labs/`. El puente no se duplica.
