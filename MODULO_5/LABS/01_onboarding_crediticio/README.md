# Caso 1: Onboarding y Scoring Crediticio

**Topología ADK2:** Graph Workflow (Centralizada / Dirigida)
**Arquetipos Integrados:** Reflex + Planner-Executor

---

## Arquitectura del Flujo

```
                     [Entrada: Solicitud de Crédito]
                                   │
                                   ▼
     [Reflex: validar_kyc_reflex_node (Código, $0 tokens, 1 sola pasada)]
                                   │
       ┌───────────────────────────┴───────────────────────────┐
       ▼ (CUIT_VALIDO)                                          ▼ (CUIT_INVALIDO)
[Fan-out paralelo: fetch_veraz / fetch_afip / fetch_crm]   [FIN: Rechazo Directo]
       │              │                │
       └──────────────┴────────────────┘
                       ▼
        [JoinNode: join_credit_data ($0 tokens)]
                       ▼
     [Router determinista: route_credit_risk (Código, $0 tokens)]
                       │
      ┌────────────────┼─────────────────────────────┐
      ▼ RECHAZO_DIRECTO ▼ APROBACION_STANDARD          ▼ AUDITORIA_AVANZADA
 [FIN: Rechazo]   [aprobador_standard (LLM, 1 call)]   [Planner-Executor real — ver abajo]
                       │                                          │
                       └──────────────────┬───────────────────────┘
                                          ▼
                            [DictamenCredito (tipado)]
```

**Detalle del Planner-Executor real (rama `AUDITORIA_AVANZADA`):**

```
      [route_credit_risk: AUDITORIA_AVANZADA]
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
[planner_auditoria (LLM)]   [passthrough_datos_auditoria (código)]
   Planifica, NO ejecuta         Re-emite BundledCreditData
         │                           │
         └─────────────┬─────────────┘
                       ▼
        [JoinNode: join_plan_datos ($0 tokens)]
                       ▼
   [validar_plan_auditoria_node (Guardrail, código, $0 tokens)]
                       │
        ┌──────────────┴──────────────┐
        ▼ PLAN_OK                     ▼ PLAN_RECHAZADO
[executor_auditoria_node          [FIN: Auditoría Cancelada]
 (Executor, código, $0 tokens,
 recorre el plan paso a paso)]
        │
        ▼
[sintesis_auditoria (LLM, 1 call)]
        │
        ▼
[DictamenCredito]
```

---

## Componentes Clave

1. **Reflex (`validar_kyc_reflex_node`):**
   Nodo de código puro que corre **antes** del fan-out: percibe el CUIT, decide si el formato es válido (regex) y actúa enrutando (`CUIT_VALIDO` / `CUIT_INVALIDO`) — percepción → decisión → acción en una sola pasada, $0 tokens. Si el CUIT es inválido, el flujo corta ahí mismo: `fetch_veraz`, `fetch_afip`, `fetch_crm` y el `JoinNode` **nunca se disparan**.
   > Nota técnica: este nodo se agregó deliberadamente antes del fan-out y no como una ruta condicional *dentro* de uno de los tres `fetch_*`, porque `JoinNode` en ADK 2.0 espera a que **todos** sus predecesores declarados terminen en estado `COMPLETED` — sin importar qué ruta hayan tomado. Poner la validación en un nodo previo al fan-out evita la carrera de ejecutar ambas ramas en paralelo.

2. **Fetch nodes (`fetch_veraz`, `fetch_afip`, `fetch_crm`):**
   Consultas deterministas a fuentes externas (Veraz/BCRA, AFIP, CRM), disparadas en paralelo solo si el Reflex de KYC aprobó el CUIT. Código puro, $0 tokens. El perfil mock tiene **1 incidente previo en CRM** a propósito — no 0 — para que el caso canónico ejercite la rama `AUDITORIA_AVANZADA` por defecto.

3. **Planner-Executor real (`planner_auditoria_agent` → `validar_plan_auditoria_node` → `executor_auditoria_node` → `sintesis_auditoria_agent`):**
   Implementa el patrón completo, no un único call disfrazado:
   * **Planner** (`planner_auditoria_agent`, LLM): recibe `BundledCreditData` y produce un **artefacto de plan explícito** (`PlanAuditoria`, con 1-4 `PasoAuditoria` tipados) — **no ejecuta nada**, solo decide qué verificar y por qué.
   * **Guardrail** (`validar_plan_auditoria_node`, código): valida que el plan no exceda `MAX_PASOS_PLAN_AUDITORIA` (límite regulatorio de pasos). Si lo excede, corta a `PLAN_RECHAZADO` → `FIN: Auditoría Cancelada`, sin llamar al Executor ni gastar otro LLM call.
   * **Executor** (`executor_auditoria_node`, código puro, $0 tokens): recorre el plan aprobado paso a paso e invoca una función determinista por cada `tipo` de paso (`verificar_garantia`, `consultar_historial_judicial`, `recalcular_capacidad_pago`) — llamadas reales, no alucinadas por el LLM.
   * **Síntesis** (`sintesis_auditoria_agent`, LLM): recién acá, con los hallazgos concretos del Executor en mano, un segundo LLM redacta el `DictamenCredito` final citando esos hallazgos.

4. **Camino directo (`aprobador_standard_agent`):**
   Para el perfil claramente aprobable (`APROBACION_STANDARD`), un único call LLM con `input_schema`/`output_schema` alcanza — no todo caso necesita el patrón completo de Planner-Executor. Este camino sigue existiendo en el grafo, pero la corrida por defecto (con 1 incidente previo en CRM) no lo ejercita: ver "Camino directo" más abajo.

---

## Archivo Ejecutable

* [`onboarding_workflow.py`](onboarding_workflow.py)

---

## Tabla de Mapeo Técnico de Arquetipos y Primitivas ADK 2.0

| Técnica / Primitiva ADK 2.0 | Rol en la Arquitectura | Mapeo al [Tutorial](https://github.com/cuppibla/adk2-tutorial) (`adk2-tutorial`) | Valor Técnico y FinOps |
|---|---|---|---|
| **Reflex previo al fan-out (`validar_kyc_reflex_node`)** | Validación de formato de CUIT en una sola pasada, antes de disparar cualquier fetch. | `L2b_router` (Dict-Edge desde un nodo de código) | **Corto-circuito real:** si el CUIT es inválido, ni los 3 fetches ni el `JoinNode` llegan a ejecutarse — $0 tokens, 0 llamadas de red. |
| **Nodos de Función Deterministas** (`fetch_veraz`, `fetch_afip`, `fetch_crm`) | Ingesta de fuentes externas en paralelo (solo si el Reflex de KYC aprobó). | `L1_graph_basics` (`fetch_conditions`) | **$0 Tokens.** Extrae información estructurada en código sin costo de LLM. |
| **`JoinNode` (`join_credit_data`)** | Sincronización y empaquetado de ramas concurrentes. | `L2a_parallel_join` (`JoinNode`) | **Fan-In Estructurado:** Consolida las 3 fuentes en un objeto único `BundledCreditData`. |
| **Deterministic Router (`route_credit_risk`)** | Bifurcación basada en reglas duras de riesgo (Score $\ge 750$, incidentes CRM). | `L2b_router` (`route_by_weather` + Dict-Edge) | **Enrutamiento Determinista:** Asigna la rama de aprobación, auditoría o rechazo en $0$ ms. |
| **Planner (`planner_auditoria_agent`)** | LLM que produce un **artefacto de plan** tipado, sin ejecutar nada. | `L3` (patrón Planner, análogo a ReWOO) | **Plan inspeccionable:** el plan es un objeto Pydantic separado de la ejecución — se podría aprobar por un humano antes de correr. |
| **Guardrail de plan (`validar_plan_auditoria_node`) + fan-out en tupla (`(planner_auditoria_agent, passthrough_datos_auditoria)`)** | Código valida el plan contra un límite regulatorio antes de ejecutar cualquier paso. | `L2b_router` (Dict-Edge) | **$0 Tokens.** Puede rechazar el plan (`PLAN_RECHAZADO`) sin gastar el LLM call del Executor/Síntesis. |
| **Executor (`executor_auditoria_node`)** | Código puro que recorre el plan aprobado y ejecuta una función por paso. | `L3` (patrón Executor) | **$0 Tokens.** Es determinista: mismo plan, mismos hallazgos, siempre — auditable. |
| **Contratos Pydantic** (`BundledCreditData`, `PlanAuditoria`, `AuditoriaEjecutada`, `DictamenCredito`) | Tipado estricto en cada frontera LLM↔código. | `L1` y `L2b` (`Conditions`, `RaceStrategy`) | **Confiabilidad:** ningún JSON mal formado o campo faltante llega al core bancario. |

## Salida de Ejemplo de la Ejecución Canónica

Corrida vía `./run_ejemplo.sh 1`, camino `AUDITORIA_AVANZADA` (score 780, 1 incidente previo en CRM):

**1. Reflex de KYC — valida el CUIT antes de cualquier otra cosa**

```text
[validar_kyc_reflex_node] (0 tokens) CUIT=30-71122334-9, formato_valido=True -> Route: CUIT_VALIDO
```

**2. Fan-out paralelo — 3 consultas deterministas, $0 tokens**

```text
[fetch_veraz] -> Score: 780, Sit BCRA: 1
[fetch_afip]  -> Categoría: Responsable Inscripto, Facturación: $18.000.000
[fetch_crm]   -> Antigüedad: 24 meses, Incidentes: 1
```

**3. Router determinista**

```text
[Router Determinista] Score=780, SitBCRA=1 -> Route: AUDITORIA_AVANZADA
```

**4. Planner — produce un plan, no ejecuta nada**

```text
PlanAuditoria:
  1. consultar_historial_judicial
     "El perfil presenta 'incidentes_previos': 1 en el CRM, lo que indica un antecedente que
     requiere una investigación profunda. Aunque 'tiene_embargos': false en Veraz, es crucial
     consultar el historial judicial para descartar demandas, litigios, concursos [...]"
  2. recalcular_capacidad_pago
     "A pesar de la facturación anual de $18.000.000 y la situación BCRA 1, la existencia de
     1 incidente previo en el CRM justifica una revisión manual y detallada de la capacidad
     de pago [...]"
```

**5. Guardrail — valida el plan contra el límite regulatorio**

```text
[validar_plan_auditoria_node] Plan con 2 paso(s), dentro del límite -> Route: PLAN_OK
```

**6. Executor — recorre el plan aprobado, ejecuta una función real por paso**

```text
[executor_auditoria_node] ejecuta 'consultar_historial_judicial'
  -> Sin juicios ni concursos preventivos registrados a nombre del solicitante ni de la sociedad.
[executor_auditoria_node] ejecuta 'recalcular_capacidad_pago'
  -> Relación cuota/ingreso proyectada: 28%, dentro del límite prudencial (35%).
```

**7. Síntesis — segundo LLM, con los hallazgos concretos en mano**

```json
{
  "veredicto": "OBSERVADO",
  "monto_maximo_sugerido": 950000.0,
  "tasa_interes_anual_pct": 78.0,
  "fundamento": "Se observa el crédito por 1 incidente previo en CRM, aunque el score Veraz es 780, la facturación anual alcanza ARS 18,000,000, la capacidad de pago es del 28% y el historial judicial está limpio (\"Sin juicios ni concursos preventivos registrados\"), lo que permite un monto conservador con tasa ajustada."
}
```

**Tiempo total: 47.22s** (Reflex KYC + 3 fetches en paralelo + Planner-Executor: 2 LLM calls)

> El planner decide cuántos pasos incluir según el perfil — en esta corrida eligió 2 (no consultó garantía porque el caso no la ameritaba); en otras corridas puede elegir 2, 3 o hasta 4. Eso es esperable: es el LLM planificando, no un guion fijo.

### Camino de guardrail: `PLAN_RECHAZADO` — forzando `MAX_PASOS_PLAN_AUDITORIA = 0`

```text
[validar_plan_auditoria_node] Plan con 2 pasos excede el límite (0) -> Route: PLAN_RECHAZADO

-> {"veredicto": "CANCELADO", "motivo": "Plan de auditoría con 2 pasos excede el límite regulatorio de 0."}
```

El Executor y el segundo LLM call (síntesis) **nunca corren** — el guardrail cortó antes.

### Camino directo: `APROBACION_STANDARD` — con un perfil sin incidentes (`incidentes_previos=0`)

```text
[Router Determinista] Score=780, SitBCRA=1 -> Route: APROBACION_STANDARD
```

Con `incidentes_previos=0`, el router devuelve `APROBACION_STANDARD` y el caso se resuelve con un único call LLM, sin Planner-Executor.

### Camino de corte del Reflex: `CUIT_INVALIDO` — con `CUIT_SOLICITANTE = "CUIT-MAL-FORMADO"`

```text
[validar_kyc_reflex_node] CUIT=CUIT-MAL-FORMADO, formato_valido=False -> Route: CUIT_INVALIDO

-> {"veredicto": "RECHAZADO", "motivo": "Score crediticio insuficiente o situación BCRA irregular."}

Tiempo total: 0.01s
```

Ningún `fetch_*` ni el `JoinNode` aparecen en la traza: el Reflex cortó el flujo antes de que se dispararan.
