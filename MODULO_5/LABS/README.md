# Ejemplos Completos — ADK 2.0: Topologías de Orquestación

Tres ejemplos integradores que combinan las **3 topologías de orquestación de ADK 2.0**
(Graph Workflow, Collaborative/Swarm Workflow y Dynamic Workflow) con los **6 arquetipos
agénticos** vistos en el módulo (Reflex, ReAct, Planner-Executor, Query Decomposition,
Reflection y Deep Research), aplicados a casos de negocio realistas.

Cada carpeta contiene un script Python ejecutable y un `README.md` con el diagrama de
arquitectura, la tabla de mapeo técnico contra el
[tutorial de referencia ADK 2.0](https://github.com/cuppibla/adk2-tutorial) y una traza de
ejemplo de ejecución.

## Los 3 ejemplos

| # | Carpeta | Caso | Topología ADK 2.0 | Arquetipos integrados |
|---|---|---|---|---|
| 1 | [`01_onboarding_crediticio/`](01_onboarding_crediticio/) | Onboarding y scoring crediticio bancario | **Graph Workflow** (grafo determinista con `JoinNode` + router) | Reflex + Planner-Executor |
| 2 | [`02_incidencias_soc/`](02_incidencias_soc/) | Mesa de respuesta a incidentes de ciberseguridad (SOC) | **Collaborative / Swarm Workflow** (supervisor + especialistas) | ReAct (`single_turn`) + Human-in-the-Loop (`task` + `finish_task`) |
| 3 | [`03_auditoria_licitaciones/`](03_auditoria_licitaciones/) | Auditoría masiva de licitaciones y contratos públicos | **Dynamic Workflow** (`@node`, paralelismo y recursión nativos) | Query Decomposition + Deep Research |

### Caso 1 — Onboarding y Scoring Crediticio

Un grafo determinista: un nodo Reflex (`validar_kyc_reflex_node`) valida el formato del
CUIT en una sola pasada **antes** de disparar nada — si es inválido, corta el flujo ahí
mismo, sin ejecutar ningún fetch. Si es válido, recién ahí se disparan en paralelo y sin
costo de tokens `fetch_veraz`, `fetch_afip` y `fetch_crm`, se consolidan con un
`JoinNode`, y un router por reglas (`route_credit_risk`) bifurca según el score y los
incidentes en CRM. El caso canónico (1 incidente previo) cae en `AUDITORIA_AVANZADA`,
que dispara un **Planner-Executor real**: un LLM planifica un plan de verificación
explícito (sin ejecutar nada), un guardrail de código lo valida contra un límite
regulatorio de pasos, un Executor de código lo recorre invocando una función por paso, y
recién con esos hallazgos concretos un segundo LLM redacta el dictamen final. El camino
directo de un solo call (`aprobador_standard_agent`) sigue existiendo para el perfil
claramente aprobable. Ilustra **Reflex** (validación KYC + filtros $0 en código)
combinado con **Planner-Executor** (plan → guardrail → executor → síntesis, no un solo
call disfrazado).

### Caso 2 — Mesa de Respuesta a Incidentes SOC

Un supervisor (`comandante_incidente_soc`) coordina de forma emergente —sin aristas
cableadas— a tres especialistas: un forense de logs y un especialista de firewall en
`mode="single_turn"` (herramientas tipadas de una sola pasada, con `disallow_transfer_*`
para evitar handoffs accidentales), cada uno con una herramienta real (`tools=[...]`) que
llaman antes de responder — Action → Observation genuino, no una instrucción de "simular"
el resultado — y un oficial de seguridad en `mode="task"` que exige autorización humana
formal vía `finish_task` antes de habilitar el bloqueo. Ilustra **ReAct real** por
especialista más **Human-in-the-Loop tipado**.

### Caso 3 — Auditoría Masiva de Licitaciones

Un workflow dinámico basado en `@node`: `decompose` extrae el monto de la licitación en
código (regex, $0 tokens) y descompone la consulta en subconsultas en tiempo de
ejecución, `research_topic` las investiga en paralelo nativo (`parallel_worker=True`,
con `RetryConfig` ante rate limits) y puede **recursionar sobre sí mismo** cuando
detecta que necesita profundizar (acotado por `MAX_DEPTH`), `synthesize` arma el
dictamen final, y recién ahí `evaluar_umbral_node` — código puro, no el LLM — compara el
monto contra USD $100.000 y bifurca a pausa Human-in-the-Loop real (vía Task API) o
aprobación automática. Ilustra **Query Decomposition** + **Deep Research** recursivo +
**Human-in-the-Loop** con gate determinista.

## Cómo ejecutarlos

### 1. Conseguir una API key de Google AI Studio

Los tres ejemplos llaman a Gemini a través de la **Gemini API** con una API key de
Google AI Studio. Generá la tuya (el nivel gratuito alcanza) en
<https://aistudio.google.com/apikey> y exportala en tu shell:

```bash
export GOOGLE_API_KEY="tu-api-key"
source setup_env.sh
```

`setup_env.sh` deja `GOOGLE_GENAI_USE_VERTEXAI=FALSE` (modo API key) y define `ADK_MODEL`
(por defecto `gemini-2.5-flash`). Si no exportaste la key antes, te la pide por teclado sin
mostrarla. La key solo vive en las variables de tu sesión de shell: **no la escribas en los
scripts ni la subas a ningún repo**.

Si usás `run_ejemplo.sh` (recomendado, ver abajo) no hace falta que corras `source
setup_env.sh`: el script lo carga solo si no detecta `GOOGLE_API_KEY`. Si corrés un script
directo con `python3` y no hay key, el script termina con un mensaje explicando cómo
configurarla.

> **Cuota del nivel gratuito:** el Caso 3 lanza varias investigaciones en paralelo y puede
> chocar con el límite de requests por minuto. Cada worker reintenta con backoff
> (`RetryConfig`), así que normalmente se recupera solo; si igual ves errores `429`, esperá
> un minuto y volvé a correr. Podés cambiar de modelo con `export ADK_MODEL=<modelo>` (por
> ejemplo, uno de la familia Flash-Lite, con mayor cuota).

### 2. Instalar dependencias

Necesitás Python 3.11+ y `google-adk` (ADK 2.x):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Correr un ejemplo por vez

Usá el script `run_ejemplo.sh`, que ejecuta un solo caso y muestra la salida completa en
consola con separadores claros:

```bash
./run_ejemplo.sh            # menú interactivo: elegís 1, 2 o 3
./run_ejemplo.sh 1          # corre directo el Caso 1
./run_ejemplo.sh soc        # también acepta alias: onboarding | soc | auditoria
```

También podés correr cada script directo con `python3`, por ejemplo:

```bash
python3 01_onboarding_crediticio/onboarding_workflow.py
```

## ¿Se pueden correr con `adk web`?

**Depende del ejemplo, y ninguno funciona apuntando `adk web` directo a esta carpeta tal
cual está:**

- **Caso 2 (SOC)** es el más cercano a "listo": su nodo raíz es un `Agent` normal
  (`root_supervisor`, con `sub_agents=[...]`), igual que los niveles `L3a`/`L3b` del
  tutorial. Alcanza con exponerlo como `root_agent` dentro de un paquete con `__init__.py`
  (por ejemplo copiando el patrón de `webapps/L3a_concierge/` del
  [tutorial de referencia](https://github.com/cuppibla/adk2-tutorial))
  para poder tipear el mensaje en el chat y que dispare el flujo.

- **Casos 1 y 3 (Onboarding y Auditoría)** están construidos como `Workflow` de grafo/
  dinámico, con datos de entrada hardcodeados en `main()` (Caso 1 corre con
  `new_message=None`; Caso 3 arranca siempre con la misma licitación de ejemplo) y toda
  su traza pedagógica va a `print()`, que `adk web` no muestra en el navegador. Si los
  apuntás directo con `adk web`, el cuadro de chat queda decorativo: no importa qué
  escribas, corre siempre el mismo caso fijo, y no ves la traza.

  El propio tutorial de referencia resuelve exactamente este problema con una capa de
  adaptación (`webapps/_bridge.py`): envuelve cada
  `Workflow` en un nodo que sí lee lo que el usuario tipeó, captura el `stdout` de la
  ejecución y lo muestra como mensaje del agente. Para llevar estos dos casos a `adk web`
  habría que escribir un adaptador equivalente (mismo patrón que
  `webapps/L2a_fanout_join/__init__.py` o `L4a_research_flat/__init__.py` en ese repo).

En síntesis: lo más simple y fiel a lo que está pensado es correrlos por consola con
`run_ejemplo.sh`. Si querés una demo clickeable en el navegador, el Caso 2 es
el candidato natural y los Casos 1/3 requieren el mismo trabajo de "bridge" que ya existe
en el tutorial base.

## Estructura de la carpeta

```
MODULO5_labs/
├── README.md                          (este archivo)
├── requirements.txt                   dependencias (google-adk 2.x)
├── run_ejemplo.sh                     script para correr un caso por vez
├── setup_env.sh                       configura la API key de Google AI Studio
├── 01_onboarding_crediticio/
│   ├── README.md
│   └── onboarding_workflow.py
├── 02_incidencias_soc/
│   ├── README.md
│   └── soc_swarm_workflow.py
└── 03_auditoria_licitaciones/
    ├── README.md
    └── auditoria_dynamic_workflow.py
```
