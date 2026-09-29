# Ejercicio 3 — Dynamic Model Routing

**Archivo**: [`../ejercicio_3_routing_dinamico.py`](../ejercicio_3_routing_dinamico.py) · **Correr**: `./run.sh 3`
**Modelos**: `gemini-2.5-flash-lite` (clasifica) → `flash-lite` / `flash` / `pro` (ejecuta) · **Tiempo**: ~2 min · **Llamadas**: ~10

> Ojo: hay **dos silencios largos** (~40 s cada uno) cuando una query cae en `gemini-2.5-pro`. No se colgó.

## Qué resuelve

Un **router** que, por cada query, (1) la clasifica como `simple`, `media` o `compleja` con el modelo más barato, y (2) la ejecuta con el modelo que corresponde a esa complejidad. Al final calcula cuánto se ahorró contra mandar todo al modelo caro, y **muestra a propósito un cálculo de ahorro defectuoso** (v1) seguido del corregido (v2).

## El código, por bloques

| Bloque | Qué hace |
|---|---|
| `MODELOS_CONFIG` | Precio por millón de tokens (input/output) de cada modelo. Es lo único específico del proveedor. |
| `MODELO_MAP` | La política de routing: `simple→flash-lite`, `media→flash`, `compleja→pro`. |
| `ejecutar_agente` | Helper genérico: corre un `LlmAgent` y devuelve el texto final (drena el generador, sin `break`). |
| `clasificador_agent` | `LlmAgent` **siempre en el modelo más barato**, con criterios de complejidad en prosa. |
| `clasificar_complejidad` | Llama al clasificador y **parsea su JSON limpiando bloques markdown** (```` ```json ````) aunque el prompt pida "solo JSON". Si no puede parsear, **degrada a `"media"`**. |
| `crear_agente_ejecutor` | Instancia un `LlmAgent` **nuevo** con el modelo elegido en runtime (el `model` queda fijo una vez construido el agente). Este es el patrón del router. |
| `ejecutar_con_modelo_ruteado` | Ejecuta la query, mide latencia y estima tokens (`palabras × 1.3`, no tokens reales) y costo. |
| `QUERIES_EVALUACION` | 5 queries (2 simples, 1 media, 2 complejas) con la complejidad esperada. |
| `analizar_ahorro_costo` (v1) | Línea de base **defectuosa**: asume que el 60 % de los tokens son de output y factura *solo eso* al precio del modelo caro, descartando el input. Compara dos magnitudes calculadas distinto. |
| `analizar_ahorro_costo_v2` | Línea de base correcta: **el mismo tráfico** (mismos tokens de input y output) facturado íntegro al modelo caro. |

### Las 4 decisiones de diseño del clasificador

1. **Siempre corre en el modelo barato.** Si clasificar costara lo mismo que responder, el routing no ahorraría nada.
2. **Los criterios del prompt son la política de routing** escrita en prosa: cambiar esas tres líneas cambia el costo mensual. Se versiona y se revisa.
3. **El parseo asume que el modelo envolverá el JSON en markdown.** Se arregla en código, no insistiendo en el prompt.
4. **El fallback es `"media"`, nunca un extremo.** Degradar a `simple` manda queries difíciles a un modelo que no las resuelve; degradar a `compleja` convierte cualquier inestabilidad en una factura. Es una decisión de negocio.

## Cómo leer la salida

Por cada caso:

```text
[Caso] Evaluación de riesgo con múltiples variables
Complejidad detectada: compleja (✓ esperaba compleja)
Modelo usado:          gemini-2.5-pro
Justificación:         La consulta requiere evaluar múltiples variables...
Latencia:              39622ms
Costo estimado:        $0.016492
```

`✓`/`✗` compara la clasificación del router con la etiqueta esperada. Luego dos reportes sobre **los mismos datos**:

```text
ANÁLISIS DE AHORRO v1 (línea de base con heurística)
Costo total CON routing:  $0.032183
Costo total SIN routing:  $0.024948
Ahorro estimado:          -29.0%          <-- NEGATIVO

ANÁLISIS DE AHORRO v2 — línea de base: todo a gemini-2.5-pro
Costo total CON routing:  $0.032183
Costo total SIN routing:  $0.039890
Ahorro real:              19.3%           <-- POSITIVO
```

(corrida real, 2026-09-29.)

1. **El v1 negativo no es que el routing pierda plata.** La línea de base v1 sub-estima el costo de "sin routing" (ignora el input y aplica una heurística solo de ese lado). El **patrón funciona, la medición no**. El bug está a propósito: es un error real que tenía el material original. Que el v1 salga negativo o apenas positivo varía por corrida; lo estable es que **v1 y v2 discrepan sobre los mismos datos**.
2. **El v2 es el número defendible**, y aun así es el ahorro *de este corpus*, no del routing en abstracto: aquí las 2 queries complejas (a `pro`) concentran ~78 % de los tokens y casi todo el costo. Con una mezcla de producción (80 % simples / 15 % medias / 5 % complejas) el ahorro sería mucho mayor.
3. **El bloque "share de tokens" del v2 imprime una línea por consulta, en el orden de las 5 queries**, no una fila por modelo. Por eso `flash-lite` y `pro` aparecen dos veces. Para agregarlo hay que sumar a mano (`flash-lite` = 1,0 + 13,8 = 14,8 %; `pro` = 41,1 + 36,7 = 77,8 %; `flash` = 7,5 %). Puede sumar 99,9 % por redondeo.
4. **Token share ≠ cost share.** Las queries caras son las que *querés* que resuelva el modelo bueno. El routing no ahorra en lo importante: evita pagar de más por lo trivial.
5. **`Accuracy del router: N/5`** no es evidencia de nada por sí sola: el clasificador es un LLM (temperatura por defecto) y varía entre corridas. Un error de routing cuesta retrabajo, no tokens.
6. **Los costos son estimaciones** (`palabras × 1.3`, no tokens reales de la API): sirven para comparar modelos entre sí, no para conciliar una factura.

## Para experimentar

- Bajá `QUERIES_EVALUACION` a 2 casos (uno simple, uno complejo) si querés una corrida rápida.
- Cambiá `MODELO_MAP["compleja"]` a `gemini-2.5-flash` y mirá cómo cambia el ahorro sin tocar el patrón.
- Corré `v2` con una mezcla 80/15/5: duplicá las queries simples y verás el ahorro subir.
- Rompé el parseo (hacé que el clasificador devuelva texto libre) y confirmá que cae en `media`.

## Sobre LangGraph vs. ADK2

El lab domiciliario (`lab.md`) pide este ejercicio en LangGraph; esta versión lo resuelve en ADK2. El patrón es idéntico: *una función clasifica, otra ejecuta con el modelo elegido*. El router es portable porque en el fondo es una función que devuelve un string.
