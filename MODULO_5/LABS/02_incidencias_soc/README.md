# Caso 2: Mesa de Respuesta a Incidentes SOC (Ciberseguridad)

**Topología ADK 2.0:** Collaborative / Swarm Workflow (*Hub-and-Spoke Gobernado*)  
**Arquetipos Integrados:** ReAct real (Action → Observation, memoria aislada) + Human-in-the-Loop tipado (`finish_task`)  
**Tutorial Base:** `L3a_collaborative` y `L3b_task_desk`

---

## 1. Fundamento Arquitectural: ¿Por qué es un Swarm Colaborativo y no un Grafo?

A primera vista, una traza de ejecución de respuesta a incidentes puede parecer una secuencia lineal (Forense $\rightarrow$ Autorización $\rightarrow$ Firewall). Sin embargo, **arquitecturalmente difiere de un Grafo en aspectos estructurales:**

```text
               DIFERENCIA ESTRUCTURAL: GRAFO vs. SWARM COLABORATIVO

      [1. GRAPH WORKFLOW (Caso 1)]                [2. COLLABORATIVE SWARM (Caso 2)]
  Bifurcaciones cableadas en diseño           Orquestación Conversacional Emergente
       
      ┌─────────────────────────┐                   ┌─────────────────────────────┐
      │     edges = [...]       │                   │    sub_agents = [A, B, C]   │
      │  JoinNode ──► Router    │                   │   Comandante (Supervisor)   │
      └────────────┬────────────┘                   └──────────────┬──────────────┘
                   │                                               │
         (Rutas predefinidas)                          (Decisión autónoma por turno)
                   ▼                                               ▼
      ┌────────────┴────────────┐                   ┌──────────────┴──────────────┐
      │  Ruta A   │   Ruta B    │                   │ ¿Amenaza? ──► Autorizar     │
      └─────────────────────────┘                   │ ¿Falso +? ──► Cerrar Caso   │
                                                    └─────────────────────────────┘
```

### Principales diferencias con un Graph Workflow:
1. **Sin aristas rígidas (`edges=[...]`):** El supervisor recibe un *pool* abierto de especialistas (`sub_agents=[forense_logs, oficial_seguridad_task, especialista_firewall]`). El LLM decide en cada turno a quién convocar según la evidencia descubierta.
2. **Evaluación de Gravedad en Tiempo de Ejecución:**
   * Si `forense_logs` determina que la IP corresponde a un *Falso Positivo* o *Riesgo Bajo*, el Comandante **cierra el caso inmediatamente** sin escalar al Oficial de Seguridad ni tocar el Firewall.
   * Si el diagnóstico confirma un *Ataque Crítico*, el protocolo activa la solicitud de autorización.
3. **Instrucción de Gobernanza vs. Script Rígido:**
   * La instrucción del Comandante no es un código paso-a-paso imperativo, sino un **protocolo de gobernanza y delegación** (análogo al `race_concierge` de `L3a`): le define las capacidades de sus especialistas y las condiciones bajo las cuales debe escalar o mitigar.

---

## 2. Primitivas Canónicas de ADK 2.0 Utilizadas

### A. Especialistas Atómicos: `mode="single_turn"` + ReAct real (`L3a_collaborative`)
* **Problema:** Si cada subagente conversa libremente con el usuario o con sus pares, se producen bifurcaciones descontroladas (*Session Drift*) y se contamina la memoria del orquestador con miles de líneas de logs.
* **Solución:** `mode="single_turn"` transforma al subagente en una **herramienta tipada de un solo turno**. Ejecuta su ciclo ReAct en su propio espacio y devuelve un esquema (`DiagnosticoAmenaza`, `BloqueoConfirmado`) retornando el control de inmediato al supervisor.
* **Aislamiento Estricto:** `disallow_transfer_to_parent=True` y `disallow_transfer_to_peers=True` blindan al enjambre de transferencias accidentales.
* **El ciclo ReAct es real, no instruido a simular:** `forense_logs` tiene `tools=[_consultar_logs_raw]` y `especialista_firewall` tiene `tools=[_aplicar_regla_firewall]`. Cada uno hace una llamada de herramienta real (Action), recibe una Observation concreta, y razona sobre ella antes de emitir el esquema tipado — no se le pide al modelo que "simule" o "invente" el resultado. ADK combina `tools=` y `output_schema=` en el mismo agente vía un workaround interno (`_output_schema_processor.py`) cuando el modelo no soporta ambos nativamente en la misma llamada.

### B. Autorización Humana Tipada: `mode="task"` + `finish_task` (`L3b_task_desk`)
* **Problema:** En ciberseguridad, un agente autónomo no debe bloquear infraestructura crítica sin aval formal.
* **Solución:** `oficial_seguridad_task` opera en `mode="task"`. ADK 2.0 inyecta automáticamente la herramienta `finish_task` y exige el esquema `AutorizacionBloqueo`. La subrutina se valida y concluye únicamente cuando el oficial emite su firma formal.

---

## 3. Diagrama de Interacción Hub-and-Spoke

```text
                             [Alerta SOC: IP Sospechosa]
                                          │
                                          ▼
                       ┌─────────────────────────────────────┐
                       │  Supervisor: Comandante de Incidentes│
                       └────────┬───────────────────▲────────┘
                                │                   │
       ┌────────────────────────┼───────────────────┼────────────────────────┐
       │ (1. Dispatch)          │ (2. Dispatch)     │ (3. Dispatch)          │
       ▼                        ▼                   ▼                        │
┌───────────────┐      ┌─────────────────┐ ┌──────────────────┐              │
│ forense_logs  │      │ oficial_seguri- │ │ especialista_    │              │
│               │      │ dad_task (HITL) │ │ firewall         │              │
│ (single_turn) │      │ (mode="task")   │ │ (single_turn)    │              │
└───────┬───────┘      └────────┬────────┘ └────────┬─────────┘              │
        │                       │                   │                        │
        │ DiagnosticoAmenaza    │ finish_task(...)  │ BloqueoConfirmado      │
        └───────────────────────┴───────────────────┴────────────────────────┘
                                          │
                                          ▼
                       ┌─────────────────────────────────────┐
                       │    Síntesis Ejecutiva Consolidada    │
                       └─────────────────────────────────────┘
```

---

## 4. Archivo Ejecutable y Ejecución

* **Script Python:** [`soc_swarm_workflow.py`](soc_swarm_workflow.py)

Para ejecutar con tu API key de Google AI Studio (ver el [README principal](../README.md)):
```bash
export GOOGLE_API_KEY="tu-api-key"
python3 02_incidencias_soc/soc_swarm_workflow.py   # desde la raíz de MODULO5_labs/
```

---

## 5. Tabla de Mapeo Técnico de Arquetipos y Primitivas ADK 2.0

| Técnica / Primitiva ADK 2.0 | Rol en la Arquitectura | Mapeo al [Tutorial](https://github.com/cuppibla/adk2-tutorial) (`adk2-tutorial`) | Valor Técnico y FinOps |
|---|---|---|---|
| **`mode="single_turn"` + `tools=[...]`** (`forense_logs`, `especialista_firewall`) | Especialistas aislados que actúan como herramientas estructuradas — y llaman a una herramienta real antes de responder. | `L3a_collaborative/concierge.py` (`_specialist`) + `L0_first_agent` (patrón `tools=[fn]`) | **ReAct genuino:** Action (`_consultar_logs_raw`/`_aplicar_regla_firewall`) → Observation → razonamiento → `output_schema`. |
| **`disallow_transfer_to_parent=True` y `disallow_transfer_to_peers=True`** | Evita bifurcaciones o cascadas no deseadas de transferencia. | `L3a_collaborative` (`kwargs` en subagentes) | **Control Estricto de Flujo:** Garantiza que el control siempre retorne de inmediato al Supervisor. |
| **`mode="task"` + `finish_task` (`oficial_seguridad_task`)** | Subrutina conversacional de autorización con fin tipado. | `L3b_task_desk/desk.py` (`gear_fitter`) | **Línea de Llegada Tipada:** El agente interactúa hasta validar y emitir `finish_task(AutorizacionBloqueo)`. |
| **Supervisor Swarm (`comandante_incidente_soc`)** | Coordinador central que elige y despacha especialistas según la alerta. | `L3a` (`race_concierge`) | **Síntesis Ejecutiva:** Consolida diagnósticos, autorizaciones y acciones en un informe final unificado. |

## 6. Salida de Ejemplo de la Ejecución Canónica

Corrida de ejemplo vía `./run_ejemplo.sh 2`:

**Paso 1 — Dispatch a Forense (`mode="single_turn"`, ReAct real)**

```text
[Dispatch Tool Call] forense_logs({'ip_origen': '192.168.1.105', 'accion_requerida': 'Auditar tráfico por posible ataque de fuerza bruta'})
[Dispatch Tool Call] _consultar_logs_raw({'ip': '192.168.1.105'})     ← Action real
[Response Recibida de _consultar_logs_raw]                            ← Observation real
[Response Recibida de forense_logs]: DiagnosticoAmenaza(nivel_riesgo='CRITICO', requiere_bloqueo=True)
```

**Paso 2 — Dispatch a Oficial de Seguridad (`mode="task"`, HITL)**

```text
[Dispatch Tool Call] oficial_seguridad_task({'request': 'Se requiere autorización para bloquear la IP 192.168.1.105 debido a un ataque de fuerza bruta crítico. El análisis forense de logs detectó 1,450 peticiones fallidas en el endpoint de login en los últimos 5 minutos.'})
[Dispatch Tool Call] finish_task({
  'confirmado': True,
  'oficial_firmante': 'SecOps_Lead_01',
  'motivo_aprobacion': 'Se autoriza el bloqueo de la IP 192.168.1.105 debido a un ataque de fuerza bruta crítico...'
})
[Response Recibida de oficial_seguridad_task]: AutorizacionBloqueo(confirmado=True)
```

**Paso 3 — Dispatch a Firewall (`mode="single_turn"`, ReAct real)**

```text
[Dispatch Tool Call] especialista_firewall({'ip_origen': '192.168.1.105', 'accion_requerida': 'Bloquear IP 192.168.1.105 por ataque de fuerza bruta con TTL de 24 horas'})
[Dispatch Tool Call] _aplicar_regla_firewall({'ip': '192.168.1.105', 'ttl_horas': 24})   ← Action real
[Response Recibida de _aplicar_regla_firewall]                                            ← Observation real
[Response Recibida de especialista_firewall]: BloqueoConfirmado(regla_id='FW-RULE-4710', ttl_horas=24)
```

**Síntesis ejecutiva del comandante**

> **Diagnóstico:** Se detectó un ataque de fuerza bruta crítico desde la IP 192.168.1.105, evidenciado por 1,450 peticiones fallidas en el endpoint de login en los últimos 5 minutos.
>
> **Autorización:** El bloqueo de la IP 192.168.1.105 ha sido autorizado por SecOps_Lead_01 debido a la criticidad del ataque de fuerza bruta.
>
> **Estado de Contención:** La IP 192.168.1.105 ha sido bloqueada en el firewall perimetral mediante la regla FW-RULE-4710, con un Tiempo de Vida (TTL) de 24 horas.

**Tiempo total: 29.13s**

> `regla_id` se calcula a partir de la IP en `_aplicar_regla_firewall`, así que varía entre corridas (acá `FW-RULE-4710`, en otra corrida puede salir otro valor) — es determinista respecto de la IP de entrada, no un valor fijo.
