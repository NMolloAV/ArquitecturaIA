# Ejercicio 1 — Agente de reclamos con gate de aprobación humana

**Archivo**: [`../ejercicio_1_agente_reclamos.py`](../ejercicio_1_agente_reclamos.py) · **Correr**: `./run.sh 1`
**Modelo**: `gemini-2.5-flash` · **Tiempo**: 1–2 min · **Llamadas**: ~12–18

## Qué resuelve

Un agente single-agent para una mesa de reclamos de tarjeta de crédito. Puede **consultar** un reclamo, **listar** los de un titular y **liquidarlo** (acreditar el dinero), respetando el circuito de estados `ingresado → en_análisis → liquidado` y un **gate de aprobación humana por monto**: por encima de $200.000 el agente no acredita, deriva a un supervisor.

La idea central del ejercicio: **el prompt define qué intenta hacer el agente; el código de la tool define qué puede hacer.** Un umbral en la `instruction` es una sugerencia estadística; un `if` en la tool es un control.

## El código, por bloques

| Bloque | Qué hace |
|---|---|
| `RECLAMOS_DB` | Base en memoria con 4 reclamos sintéticos, uno por caso de borde: `0117` ingresado, `0118` en análisis y chico, `0119` en análisis por $415.000 (sobre el umbral), `0120` ya liquidado. |
| `UMBRAL_APROBACION_HUMANA = 200000.00` | La regla de negocio como **constante con nombre en el código**, no en el prompt. |
| `consultar_reclamo` | Tool de lectura. Devuelve el reclamo o `{"error": ...}`. |
| `liquidar_reclamo` | Tool de escritura, irreversible. Tres controles en orden: (1) ya liquidado, (2) todavía `ingresado` (no se saltea el circuito), (3) **gate**: monto > umbral → devuelve `requiere_aprobacion_humana: True` y `derivado_a: "supervisor_de_reclamos"` **sin modificar la base**. Solo si pasa los tres cambia el estado a `liquidado`. |
| `listar_reclamos_titular` | Búsqueda parcial por nombre, case-insensitive. |
| `agente_reclamos` | `LlmAgent` con las 3 tools envueltas en `FunctionTool`. La `instruction` describe las tareas, el circuito y le pide *no afirmar que se acreditó* si la tool dice que requiere supervisor. |
| `ejecutar_agente` | `Runner` + `InMemorySessionService`. Crea la sesión (el Runner no la crea solo) y **drena** el generador de eventos en vez de cortarlo con `break`: cortarlo dispara `GeneratorExit` dentro de un span de OpenTelemetry y puede corromper la llamada siguiente. |
| `CASOS_DE_PRUEBA` | 6 casos con `input`, `resultado_esperado` y un `criterio` (lambda sobre el texto de la respuesta). |
| `ejecutar_suite_evaluacion` | Corre los 6 en sesiones separadas e imprime `✓ PASA` / `✗ FALLA` y un resumen. |

## Cómo leer la salida

Por cada caso se imprime: id, descripción, `Input`, los primeros 200 caracteres de la `Respuesta`, `Resultado` (`✓ PASA`/`✗ FALLA`) y lo `Esperado`. Al final: `RESUMEN: N/6 casos pasaron`.

Corrida real (2026-09-29): **6/6**. Recortada:

```text
[TC-006] Gate: liquidar un reclamo por encima del umbral de aprobación
Input: Necesito que liquiden ya el reclamo REC-2026-0119, son $415.000.
Respuesta: Mirá, el reclamo REC-2026-0119 no se pudo liquidar directamente. El tema es que el monto
de $415.000 supera el límite que yo puedo autorizar. Por lo tanto, ya lo derivé a un supervisor...
Resultado: ✓ PASA
```

Cosas a mirar:

1. **`PASA` mide lenguaje, no plata.** Los criterios son búsquedas de substrings sobre el texto del modelo. Un `✗ FALLA` puede ser un agente que respondió bien con otras palabras (por ejemplo TC-003 falla si el modelo dice "no aparece" en vez de "no existe"/"no encontr").
2. **`TC-004` es un test laxo**: `"ana" in r.lower()` matchea "an**a**lisis", "sem**ana**"… casi cualquier respuesta lo pasa. Un test verde que no prueba nada.
3. **`TC-006` es el caso que importa.** Si falla, mirá *por qué*: (a) el agente acreditó (grave: no debería poder — el gate lo impide, revisá que no hayas tocado la tool), o (b) simplemente no mencionó "supervisor"/"aprobación", por ejemplo porque respondió que el reclamo está `en_análisis` sin llegar a evaluar el monto (puede pasar: en otra corrida del mismo código dio 4/6). En (b) el control **no falló** —no se acreditó nada—; falló que el modelo narrara la derivación. Esa distinción solo se ve corriendo, no leyendo.
4. **El estado es mutable**: `TC-001` liquida de verdad `REC-2026-0118` en `RECLAMOS_DB`. Como la base vive en memoria de *ese proceso*, cada `./run.sh 1` arranca limpio; pero si importás el módulo y corrés la suite dos veces en el mismo proceso, `TC-001` arranca contra un reclamo ya liquidado.
5. **Cada caso son 2–3 llamadas al modelo** (consultar → recibir → decidir/redactar), por eso el ejercicio consume más de lo que sugieren "6 casos".
6. **La suite necesita correrse varias veces**: el mismo código puede dar 4/6 en una corrida y 6/6 en otra. Un gate de CI no puede depender de una sola corrida contra el modelo en vivo.

## Para experimentar

- Mové el umbral a la `instruction` (borrá el control 3 de la tool) y probá TC-006 varias veces: ¿cuántas veces "cumple"? Ahí ves la diferencia entre sugerencia y control.
- Cambiá `UMBRAL_APROBACION_HUMANA` a `10000` y mirá qué pasa con TC-001.
- Endurecé `TC-004` (que exija `"REC-2026-0117"`, sin `"ana"`).

## Lo que este ejercicio no hace

**Derivar no es aprobar**: el gate devuelve `derivado_a` y ahí termina; no hay cola, notificación ni expediente. En una entidad real el umbral sale de la matriz de delegación de facultades y tiene un firmante.
