# Labs — Módulo 2: Diseño de Sistemas Agénticos

**Curso**: Arquitectura de Agentes IA — UTDT
**Stack**: Google ADK 2 + Gemini, con una API key gratuita de [Google AI Studio](https://aistudio.google.com/apikey). No hace falta cuenta de GCP ni `gcloud`.

Tres ejercicios y un experimento de apoyo, todos ambientados en una mesa de reclamos de tarjeta de crédito (datos sintéticos, sin relación con personas ni operaciones reales):

| Ejercicio | Archivo | Qué muestra | Guía detallada |
|---|---|---|---|
| 1 | [`ejercicio_1_agente_reclamos.py`](ejercicio_1_agente_reclamos.py) | Agente con tools (`FunctionTool`) y gate de aprobación humana por monto | [readmes/ejercicio_1.md](readmes/ejercicio_1.md) |
| 2 | [`ejercicio_2_pipeline_paralelo.py`](ejercicio_2_pipeline_paralelo.py) | `ParallelAgent` + `SequentialAgent` y benchmark paralelo vs. secuencial | [readmes/ejercicio_2.md](readmes/ejercicio_2.md) |
| 3 | [`ejercicio_3_routing_dinamico.py`](ejercicio_3_routing_dinamico.py) | Router que elige el modelo (barato/medio/caro) según la complejidad de la query | [readmes/ejercicio_3.md](readmes/ejercicio_3.md) |
| Bonus | [`demo_dos_modelos.py`](demo_dos_modelos.py) | La misma query en un modelo barato y uno caro, lado a lado | [readmes/demo_dos_modelos.md](readmes/demo_dos_modelos.md) |

Los ejercicios son independientes y se pueden correr en cualquier orden. El bonus es el ejemplo más rápido para entender el problema que resuelve el Ejercicio 3.

## Arranque rápido

```bash
cd labs_mod2_alumnos
./setup.sh        # una sola vez: crea .venv, instala dependencias, crea .env
# editá .env y pegá tu GOOGLE_API_KEY
./check.sh        # verifica paquetes, key y acceso a los 3 modelos
./run.sh 1        # corre el Ejercicio 1
```

> ⚠️ **Nunca subas `.env` ni pegues tu API key en un notebook o repositorio.** Es la fuga de credenciales más común en entregas de cursos. En Colab usá *Secrets* (ícono de llave).

## Scripts

| Script | Para qué |
|---|---|
| `setup.sh` | Crea `.venv`, instala `requirements.txt` y crea `.env` desde `.env.example`. Se puede repetir sin problema. |
| `check.sh` | Diagnóstico: paquetes, API key y una llamada mínima a cada modelo. |
| `env.sh` | `source ./env.sh` carga `.env` y activa el venv en tu shell, para correr `python ...` a mano. |
| `run.sh` | Lanza un ejercicio (tabla siguiente). |

| Comando | Qué corre | Tiempo aprox. | Llamadas al modelo |
|---|---|---|---|
| `./run.sh 1` | Ejercicio 1 (6 casos de prueba) | 1–2 min | ~12–18 |
| `./run.sh 2` | Ejercicio 2 (benchmark ×3 mensajes) | ~30 s | ~18 |
| `./run.sh 3` | Ejercicio 3 (router, 5 queries) | ~2 min (2 casos a `gemini-2.5-pro` tardan ~40 s c/u) | ~10 |
| `./run.sh simple` | Bonus, clasificación | ~10 s | 2 |
| `./run.sh compleja` | Bonus, decisión de negocio | ~30–40 s | 2 |

`run.sh` silencia los warnings de ADK (`ParallelAgent` deprecado a favor de `Workflow`, JSON schema experimental). Para verlos: `source ./env.sh && python ejercicio_2_pipeline_paralelo.py`.

En Google Colab: `!pip install -q "google-adk>=2.8.0" nest_asyncio` y definí `GOOGLE_API_KEY` desde *Secrets* con `os.environ[...]`.

## Cómo leer las salidas — idea general

**Nada de estos labs es determinista.** Gemini no responde igual dos veces: los textos, las latencias, los costos, el speedup y hasta si un caso de prueba pasa o falla cambian entre corridas. Lo que es estable es la **estructura del argumento** que cada ejercicio quiere mostrar; cada guía en `readmes/` dice qué mirar y qué conclusión se sostiene aunque los números cambien. **Si tu corrida sale distinta de los ejemplos de las guías, no es un error: es parte de lo que se aprende.**

Los múltiplos de costo usan los precios de referencia de la [página de precios de Gemini](https://ai.google.dev/gemini-api/docs/pricing); pueden cambiar.

## Cuota

La API key gratuita tiene límites por minuto y por día, distintos para cada modelo. Consumo aproximado:

| Ejercicio | Llamadas | Modelos | Comentario |
|---|---|---|---|
| 1 | ~6–18 | `gemini-2.5-flash` | 6 casos × 1 a 3 turnos con tool calls |
| 2 | **~18** | `gemini-2.5-flash` | el que más rápido agota la cuota: 3 requests simultáneos, ×3 mensajes, ×2 modos |
| 3 | ~10 | `flash-lite` + `flash` + **`pro`** | 2 de 5 queries caen en `pro`, que suele tener la cuota gratuita más ajustada |
| bonus | ~2 | `flash-lite` + `pro` | una corrida por modelo |

No hace falta correr todo el mismo día.

---

## Errores frecuentes

Los problemas que más tiempo hacen perder en estos labs, con el síntoma literal y el arreglo.

### 1. `429 RESOURCE_EXHAUSTED` — se agotó la cuota

**Dónde:** cualquier ejercicio. Con mucha más frecuencia en el Ejercicio 2.

```text
google.genai.errors.ClientError: 429 RESOURCE_EXHAUSTED
```

**No es un bug: es el límite del tier gratuito de AI Studio**, que tiene cuota por minuto y por día, distinta para cada modelo. Qué hacer, en orden:

1. **Esperar.** Si el límite es el de por minuto, se libera solo en menos de sesenta segundos. Si es el diario, hay que esperar al día siguiente.
2. **Recortar las listas.** Son constantes al principio de cada script y bajarlas no cambia nada de lo que el ejercicio enseña:
   - Ejercicio 1 → recortar `CASOS_DE_PRUEBA`.
   - Ejercicio 2 → dejar **un solo** mensaje en `MENSAJES_TEST` (pasa de ~18 llamadas a ~6).
   - Ejercicio 3 → dejar **dos** casos en `QUERIES_EVALUACION`, uno simple y uno complejo (pasa de ~10 llamadas a ~4). Alcanza para ver el contraste de costo, que es el punto.
3. **Espaciar las llamadas.** En el Ejercicio 2, un `await asyncio.sleep(20)` entre mensajes dentro del loop de `main()`; en el Ejercicio 3, un `time.sleep(10)` entre casos. Tarda más y no falla.
4. **Ojo con `gemini-2.5-pro`.** Suele ser el modelo con la cuota gratuita más ajustada, y el Ejercicio 3 lo invoca para las queries que el router clasifica como "complejas". Si solo falla ahí, cambiá `MODELO_MAP["compleja"]` por `"gemini-2.5-flash"` en `ejercicio_3_routing_dinamico.py`: el patrón de routing queda idéntico, solo cambian los números de costo.
5. **No corras los tres ejercicios el mismo día** si estás con la cuota justa.

> Esto también es contenido, no solo un obstáculo: en producción la cuota es un componente de arquitectura que entra en el presupuesto y necesita una política de reintento con backoff. Un agente que se cae con un 429 no es un agente confiable.

### 2. El modelo devuelve el JSON envuelto en un bloque markdown

**Dónde:** Ejercicio 3 (`clasificar_complejidad`). Los agentes de análisis del Ejercicio 2 (`analizador_sentimiento`, `analizador_urgencia`, `clasificador_tema`) también piden JSON, pero ese JSON nunca se parsea en Python — pasa como texto al agente agregador, así que ahí este error no puede ocurrir.

Aunque el prompt diga "respondé ÚNICAMENTE con un JSON válido", el modelo devuelve con frecuencia esto:

````text
```json
{"complejidad": "simple", "justificacion": "Pregunta factual directa."}
```
````

Y entonces `json.loads(contenido)` explota con `json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.

`ejercicio_3_routing_dinamico.py` ya maneja este caso (limpia el bloque markdown antes de parsear, y usa un `try/except` con un valor por defecto si igual falla). **La salida de un LLM es una entrada no confiable**: se valida como se valida cualquier input externo. Si adaptás el código a tu propio dominio y agregás un `json.loads` en algún otro lugar (por ejemplo, para leer de verdad la salida de los analizadores del Ejercicio 2), conservá ese patrón.

### 3. `API key not valid` / el cliente no encuentra la credencial

**Dónde:** cualquier ejercicio, en la primera llamada al modelo.

```text
ValueError: No API key was provided. Please pass a valid API key.
```
```text
google.genai.errors.ClientError: 400 INVALID_ARGUMENT ... API_KEY_INVALID
```

Verificá en este orden:

1. Que `GOOGLE_API_KEY` esté seteada **antes** de correr el script.
2. Que sea una key de **AI Studio** ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)), no un service account de GCP.
3. Que no haya quedado un `GOOGLE_GENAI_USE_VERTEXAI=TRUE` (o `=1`) dando vueltas en el entorno: con esa variable activa el cliente ignora la API key y busca credenciales de Vertex, que no tenés.
4. En Colab, si guardaste la key en *Secrets*, acordate de habilitar el acceso del notebook y de copiarla a `os.environ` — no se inyecta sola.

### 4. `RuntimeError: asyncio.run() cannot be called from a running event loop`

**Dónde:** los tres ejercicios, si los corrés en Colab o Jupyter.

Los tres terminan con `asyncio.run(...)` dentro de un `if __name__ == "__main__":`, correcto para un script `.py` pero no dentro de un notebook (que ya tiene un event loop corriendo). Dos salidas, ambas válidas:

```python
# a) parchear asyncio una vez, al principio del notebook — funciona para
#    los tres ejercicios sin tocar nada más:
import nest_asyncio; nest_asyncio.apply()
asyncio.run(main())  # o asyncio.run(ejecutar_suite_evaluacion()) en el Ejercicio 1

# b) correrlo como script de verdad:
#    python ejercicio_1_agente_reclamos.py
```

El punto de entrada de cada uno cambia de nombre: `ejecutar_suite_evaluacion()` en el Ejercicio 1, `main()` en los Ejercicios 2 y 3.

### 5. `ModuleNotFoundError` después de un `!pip install` en Colab

**Dónde:** cualquier ejercicio, típicamente con `google-adk`.

Colab a veces necesita reiniciar el runtime para ver un paquete recién instalado. Si el `!pip install` terminó bien pero el `import` falla: **Entorno de ejecución → Reiniciar sesión**, y volver a correr desde la primera celda. No hace falta reinstalar, los paquetes siguen ahí.

---

## Adaptar el dominio a tu propio caso

`RECLAMOS_DB` (Ejercicio 1) es una tabla en memoria con 4 casos. Si trabajás en un área con reglas de negocio propias, reemplazala por una tabla de tu proceso y dejá el resto igual: las tools, el gate de aprobación humana y el patrón de evaluación funcional son genéricos.

En el Ejercicio 2, el benchmark de `main()` solo corre los 3 analizadores en paralelo (`pipeline_analisis`) para medir el speedup — no ejecuta el agente agregador. El módulo también define `agregador` y `pipeline_completo` (`ParallelAgent` seguido del agregador vía `SequentialAgent`) por si querés ver la síntesis final de los 3 análisis; para probarlo, corré ese pipeline con un `InMemoryRunner` igual que hace `benchmark_paralelo_vs_secuencial` con `pipeline_analisis`, y revisá el estado de la sesión al final.
