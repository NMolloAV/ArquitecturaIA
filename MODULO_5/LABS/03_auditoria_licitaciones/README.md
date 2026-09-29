# Caso 3: Auditoría Masiva de Licitaciones y Contratos Públicos

**Topología ADK2:** Dynamic Workflow (Code-First / Programática / `asyncio.gather`)  
**Arquetipos Integrados:** Query Decomposition + Deep Research + Human-in-the-Loop real (gate de código)

---

## Arquitectura del Flujo Dinámico

```
                    [Entrada: Licitación / Pliego]
                                 │
                                 ▼
     [decompose: extrae el monto en código (regex, $0) + Query
      Decomposition (LLM) — 2-4 subconsultas en tiempo de ejecución]
     ┌───────────────────────────┼───────────────────────────┐
     ▼ (Subconsulta A)           ▼ (Subconsulta B)            ▼ (Subconsulta C)
[research_topic d=1]        [research_topic d=1]        [research_topic d=1]
 @node(parallel_worker)      @node(parallel_worker)      @node(parallel_worker)
     │ needs_deeper=True?         │                            │
     ▼ (recursión, d=2)           ▼                            ▼
[research_topic d=2, d<MAX_DEPTH] ...                          ...
     └───────────────────────────┼───────────────────────────┘
                                 ▼
              [synthesize (LLM): fan-in del árbol completo]
                                 │
                                 ▼
        [evaluar_umbral_node (código, $0): monto > USD $100.000?]
                     ┌───────────┴───────────┐
                     │ Sí                    │ No
                     ▼                       ▼
        [Pausa HITL: TaskAPI]      [Aprobación Automática /
         (suspensión)                Reporte Final Auditoría]
```

---

## Componentes Clave

1. **Query Decomposition en tiempo de ejecución (`decompose`):**
   Toma la consulta del pliego y la divide en 2-4 subconsultas atómicas (precio, garantías/SLA, antecedentes del proveedor) vía `decompose_agent` (LLM). La cantidad de subconsultas no está fija de antemano — la decide el modelo según el pliego concreto.

2. **Deep Research recursivo (`research_topic`, `@node(parallel_worker=True)`):**
   Cada subconsulta corre en paralelo nativo de ADK 2.0. Si el hallazgo detecta una brecha (`needs_deeper=True`), el propio nodo se llama a sí mismo (`ctx.run_node(research_topic, ...)`) generando ramas hijas más profundas, acotado por `MAX_DEPTH=2`. Los hallazgos se acumulan en el árbol de retorno de cada rama, no en un estado global compartido.

3. **Fan-in y síntesis (`synthesize`):**
   Consolida el árbol completo de hallazgos (todas las ramas, todos los niveles) en un `BriefingLicitacion` final vía `synthesize_agent`. El campo `veredicto` de ese esquema es **solo una evaluación de contenido** (`APROBADO_AUTOMATICO` / `OBSERVADO`) — no decide si hace falta aprobación humana.

4. **Gate de Human-in-the-Loop real (`evaluar_umbral_node`):**
   `decompose` extrae el monto de la licitación del texto de entrada con una expresión regular (código puro, $0 tokens) y lo guarda en `ctx.state`. Después de `synthesize`, `evaluar_umbral_node` (también código puro) compara ese monto contra `UMBRAL_APROBACION_HUMANA` y bifurca a `PAUSADO_HITL` o `AUTO` — el LLM no participa de esta decisión, igual que el guardrail del Caso 1.

5. **Resiliencia (`RetryConfig`):**
   Cada worker de investigación tiene reintentos aislados (`max_attempts=3, backoff_factor=2.0`) ante rate limits o fallos transitorios, sin voltear las ramas hermanas.

---

## Archivo Ejecutable

* [`auditoria_dynamic_workflow.py`](auditoria_dynamic_workflow.py)

---

## Tabla de Mapeo Técnico de Arquetipos y Primitivas ADK 2.0

| Técnica / Primitiva ADK 2.0 | Rol en la Arquitectura | Mapeo al [Tutorial](https://github.com/cuppibla/adk2-tutorial) (`adk2-tutorial`) | Valor Técnico y FinOps |
|---|---|---|---|
| **Query Decomposition (`decompose_agent`)** | Genera subconsultas atómicas e independientes en tiempo de ejecución. | `L4a_flat_research` / `L4b` (`decompose_agent`) | **Desacoplamiento:** Permite analizar cláusulas de precios, SLAs y antecedentes en ramas independientes. |
| **`@node(parallel_worker=True)`** | Ejecución paralela nativa en el grafo de ADK 2.0. | `L4a` y `L4b` (`@node(parallel_worker=True)`) | **Tracing & Checkpointing:** A diferencia de llamadas asíncronas crudas, preserva el seguimiento nativo del framework. |
| **`RetryConfig(max_attempts=3, backoff_factor=2.0)`** | Blindaje y tolerancia a fallos por worker individual. | `L4b_recursion` (`RESEARCH_RETRY`) | **Resiliencia Operativa:** Si una rama sufre rate limit (429) o micro-corte, reintenta de forma aislada sin voltear el resto del pipeline. |
| **Recursión Agéntica (`ctx.run_node(research_topic, ...)`)** | El worker evalúa lagunas (`needs_deeper=True`) y se llama a sí mismo. | `L4b_recursion/deep_research.py` (`research_topic`) | **Profundización Dinámica:** La profundidad del árbol se adapta a la complejidad del caso acotada por `MAX_DEPTH = 2`. |
| **Extracción determinista de monto (`_extraer_monto_usd`, regex en `decompose`) + `ctx.state`** | Percibe el texto de entrada y decide el monto en USD, sin LLM — es un Reflex. Lo guarda en `ctx.state` para que un nodo posterior lo use. | — (patrón Reflex + estado de sesión) | **$0 Tokens.** El monto no depende de que el LLM lo transcriba bien. |
| **Gate de umbral (`evaluar_umbral_node`)** | Código puro que compara el monto contra `UMBRAL_APROBACION_HUMANA` y bifurca con Dict-Edge a `PAUSADO_HITL` / `AUTO`. | `L2b_router` (mismo patrón que el router del Caso 1) | **HITL real:** el LLM nunca decide si hace falta aprobación humana — lo decide una comparación numérica. |
| **Esquemas Tipados Pydantic** | `DecomposerOutput`, `ResearchFinding`, `BriefingLicitacion`. | `L4b` (`DecomposerOutput`, `ResearchFinding`, etc.) | **Consistencia Estructural:** Todo el árbol de investigación y el dictamen final mantienen contratos tipados. |

## Salida de Ejemplo de la Ejecución Canónica

Corrida vía `./run_ejemplo.sh 3`, sobre la licitación LIC-2026-002 (USD $250.000, GlobalServices SRL):

**1. Extracción del monto (código, $0 tokens) + Query Decomposition — 3 subconsultas**

```text
[decompose] (0 tokens) monto detectado en el pliego: USD $250,000
[decompose] 3 subconsultas generadas en tiempo de ejecución:
  • ¿Qué condiciones de precio y posibles cláusulas de reajuste se establecen para el...
  • ¿Cuáles son los detalles del SLA requerido del 99.99%, la garantía de oferta de...
  • ¿Cuáles son los antecedentes y la experiencia de GlobalServices SRL como proveedor...
```

**2. Fan-out paralelo (nivel 1) — `@node(parallel_worker=True)`**

```text
[research parallel d=1] ¿Qué condiciones de precio y posibles cláusulas de reajuste...
[research parallel d=1] ¿Cuáles son los detalles del SLA requerido del 99.99%...
[research parallel d=1] ¿Cuáles son los antecedentes y la experiencia de GlobalServices SRL...
```

**3. Recursión dinámica (nivel 2) — las 3 ramas detectaron brechas y profundizaron**

```text
[research d=1] Generando 2 ramas recursivas más profundas...
[research parallel d=2] ¿Cuál es el límite máximo de la penalidad por caída de servicio...?
[research parallel d=2] ¿Cómo se define específicamente la 'caída de servicio'...?

[research d=1] Generando 2 ramas recursivas más profundas...
[research parallel d=2] ¿El pliego incluye alguna sección que detalle la forma de pago...?
[research parallel d=2] ¿Existen anexos o adendas al pliego que establezcan la política...?

[research d=1] Generando 2 ramas recursivas más profundas...
[research parallel d=2] ¿Se han solicitado y evaluado las certificaciones, cartera de clientes...?
[research parallel d=2] ¿Se han contactado referencias de clientes anteriores de GlobalServices...?
```

6 ramas hijas en total (2 por cada rama de nivel 1) — el árbol creció según lo que cada rama encontró, no según un plan fijo.

**4. Síntesis + gate de umbral (código, no el LLM)**

```text
[synthesize] Consolidando 3 ramas de investigación...
[evaluar_umbral_node] (0 tokens) monto=USD $250,000, umbral=USD $100,000 -> Route: PAUSADO_HITL
[fin_pausa_hitl] (0 tokens) Auditoría suspendida: requiere firma ejecutiva antes de continuar (Task API).
```

> **Dictamen Final:** Auditoría Licitación LIC-2026-002: Deficiencias Críticas en Definiciones Contractuales y Evaluación de Proveedores
> **Veredicto de contenido (LLM): OBSERVADO**
> **💰 Monto: USD $250.000** (umbral de aprobación humana: USD $100.000)
> **🔒 Estado (decidido en código): PAUSADO — requiere firma ejecutiva (Task API)**
>
> - El pliego establece USD $250.000 para el mantenimiento del Data Center, pero omite condiciones de precio, modalidad de pago y cláusulas de reajuste ante fluctuaciones.
> - El SLA del 99.99% y la penalidad del 0.5%/hora no tienen una definición precisa de "caída de servicio" ni un tope máximo acumulado — riesgo financiero no cuantificado.
> - No se documenta la verificación de certificaciones, cartera de clientes ni referencias de GlobalServices SRL para un servicio de esta criticidad.
>
> **⚠️ Alertas Clave:**
> - Ausencia de definición clara de "caída de servicio" en las cláusulas de penalidad.
> - Falta de un límite máximo explícito para las penalidades acumuladas.
> - Inexistencia de cláusulas de reajuste de precio en moneda extranjera.
> - Falta de detalle sobre la modalidad de pago y el desglose del presupuesto.
> - Falta de verificación documentada de la experiencia y referencias del proveedor.

**Tiempo total: 39.09s**

### El otro camino: `AUTO` (monto bajo el umbral)

El extractor de monto y el gate se pueden probar de forma aislada, sin llamar al LLM:

```text
>>> _extraer_monto_usd("... por USD $50,000.")
50000.0
>>> 50000.0 > UMBRAL_APROBACION_HUMANA
False   # -> Route: AUTO (aprobación automática, sin pausa)
```

Con un monto de USD $50.000 (bajo el umbral de $100.000), `evaluar_umbral_node` bifurca a `fin_aprobacion_automatica` en vez de `fin_pausa_hitl` — podés comprobarlo con una prueba directa sobre `_extraer_monto_usd` y la comparación contra `UMBRAL_APROBACION_HUMANA`, sin correr todo el pipeline de investigación.
