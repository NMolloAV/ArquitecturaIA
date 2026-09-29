# Ejercicio 2 — Pipeline multiagente con procesamiento paralelo

**Archivo**: [`../ejercicio_2_pipeline_paralelo.py`](../ejercicio_2_pipeline_paralelo.py) · **Correr**: `./run.sh 2`
**Modelo**: `gemini-2.5-flash` (los 4 agentes) · **Tiempo**: ~30 s · **Llamadas**: ~18

## Qué resuelve

Analizar el mensaje de un titular desde **tres dimensiones a la vez** (sentimiento, urgencia, tema) y medir cuánto se gana corriéndolas en paralelo en vez de una por una. Es una demostración de **latencia**, no de costo: el paralelismo hace las mismas 3 llamadas, consume los mismos tokens y cuesta lo mismo; solo cambia cuánto espera el usuario.

## El código, por bloques

| Bloque | Qué hace |
|---|---|
| `analizador_sentimiento` | `LlmAgent` que devuelve un JSON `{sentimiento, intensidad, indicadores}`. Escribe en `state["analisis_sentimiento"]` vía `output_key`. Agnóstico de dominio. |
| `analizador_urgencia` | JSON `{nivel_urgencia, requiere_humano, tiempo_respuesta_sugerido}` → `state["analisis_urgencia"]`. Agnóstico de dominio. |
| `clasificador_tema` | JSON con una de 7 categorías de reclamos de tarjeta → `state["clasificacion_tema"]`. **Único específico del dominio financiero.** |
| `agregador` | Lee los tres resultados del estado de sesión y produce `{prioridad_atencion, ruta_sugerida, resumen_situacion, acciones_inmediatas}`. |
| `pipeline_analisis` | `ParallelAgent` con los 3 analizadores como `sub_agents`. |
| `pipeline_completo` | `SequentialAgent`: primero `pipeline_analisis`, después `agregador`. |
| `benchmark_paralelo_vs_secuencial` | Corre **los mismos 3 analizadores** dos veces: una con `pipeline_analisis` (paralelo) y otra con un `InMemoryRunner` por agente, uno tras otro (secuencial). Mide con `time.time()` e imprime tiempos, speedup y % de ahorro. |
| `_drenar` | Corre el runner hasta el final sin `break` (mismo motivo que en el Ejercicio 1). |
| `main` | Repite el benchmark con 3 mensajes de `MENSAJES_TEST` y promedia el speedup. |

**Ojo**: el benchmark usa `pipeline_analisis`, **no** `pipeline_completo`. Por eso en la salida **nunca aparece `ruta_sugerida`**: el agregador está definido pero este script no lo ejecuta. Para verlo, corré `pipeline_completo` con un `InMemoryRunner` y revisá el estado de la sesión (ver "Para experimentar").

## Cómo leer la salida

```text
BENCHMARK — Mensaje: '¡Necesito que frenen el reclamo REC-2026-0119! Ya pasaron 32...'
Tiempo paralelo:    3.80s
Tiempo secuencial:  6.40s
Speedup:            1.7×
Ahorro de tiempo:   41%
...
SPEEDUP PROMEDIO: 1.8×
```

(corrida real, 2026-09-29: 1,7× / 2,4× / 1,2× → promedio 1,8×.)

- **Speedup = tiempo secuencial ÷ tiempo paralelo.** El techo teórico con 3 agentes es 3×; **nunca lo vas a ver**.
- **Por qué queda por debajo de 3× (Ley de Amdahl):** hay una parte serial irreducible (armar el fan-out, deserializar los 3 eventos) y la rama paralela tarda lo que tarda **el más lento** de los tres, no el promedio.
- **La varianza es real, no un bug.** El mismo mensaje da distinto en cada corrida por latencia de red y de servicio. Un speedup de 1,2× en un mensaje y 2,4× en otro son normales. El paralelismo ayuda **en promedio**, no en cada corrida puntual; si en una corrida el paralelo sale más lento, mostralo tal cual.
- **Esto no ahorra plata.** El ahorro de costo es el Ejercicio 3.
- Las primeras llamadas de cada corrida pagan un arranque en frío; por eso los tiempos absolutos de la primera medición suelen ser algo peores.

## Para experimentar

- Dejá un solo mensaje en `MENSAJES_TEST` (baja de ~18 a ~6 llamadas; útil si te da `429` en modo AI Studio).
- Ver la síntesis completa: reemplazá `pipeline_analisis` por `pipeline_completo` en un runner y, al terminar, leé `session.state["recomendacion_final"]`.
- Meté un cuarto analizador y ver si el speedup se sostiene.

## Lo que hay que llevarse

`ruta_sugerida` y `requiere_humano` son **recomendaciones producidas por un modelo**, no controles: nada en el código impide que el flujo siga de largo si nadie las lee. Un gate de HITL real bloquea la acción antes de ejecutarla (en ADK2, un `before_tool_callback`, o un `if` en la tool como en el Ejercicio 1).

> Nota: ADK avisa que `ParallelAgent`/`SequentialAgent` están *deprecados a favor de `Workflow`*. Siguen funcionando; `run.sh` silencia el warning. La migración a `Workflow` es contenido de módulos posteriores.
