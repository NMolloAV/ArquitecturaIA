# Bonus — La misma query, dos modelos

**Archivo**: [`../demo_dos_modelos.py`](../demo_dos_modelos.py) · **Correr**: `./run.sh simple` y `./run.sh compleja`
**Modelos**: `gemini-2.5-flash-lite` (barato) vs. `gemini-2.5-pro` (caro) · **Tiempo**: ~10 s / ~30–40 s · **Llamadas**: 2 por corrida

No es un ejercicio del lab: es un experimento chico para instalar la idea del Ejercicio 3 antes de automatizarla.

## Qué hace

Toma una query (`simple` o `compleja`, según el argumento), la manda a los dos modelos con `genai.Client().models.generate_content` (sin ADK, llamada directa) y los imprime uno debajo del otro con respuesta, latencia y costo estimado. Al final muestra cuántas veces más caro salió el grande.

- **`simple`**: clasificar un mensaje en una de 7 categorías cerradas ("Me cobraron dos veces el mismo consumo…").
- **`compleja`**: el reclamo `REC-2026-0119` — $415.000, 32 días en análisis, amenaza de denuncia — con pedido de redactar la respuesta al titular **y decidir si escalar, justificando**.

## El código

| Bloque | Qué hace |
|---|---|
| `MODELOS_CONFIG` | Precio por millón de tokens de cada modelo (`flash-lite` 0,10/0,40; `pro` 1,25/10,00). |
| `QUERIES` | Las dos consignas. |
| `correr` | Una llamada, mide latencia y estima tokens (`palabras × 1.3`) y costo. |
| `comparar` | Corre `correr` para los dos modelos, imprime y calcula el múltiplo. `genai.Client()` toma la API key de `.env`. |

## Cómo leer la salida

**Simple** (2026-09-29):

```text
--- gemini-2.5-flash-lite ---
cobro_duplicado
  latencia 2455ms | tokens ~45 | costo $0.00000494
--- gemini-2.5-pro ---
cobro_duplicado
  latencia 5221ms | tokens ~45 | costo $0.00006825
  El caro costó 13.8x más que el barato para ESTA query.
```

- **Las dos respuestas son la misma palabra.** En una tarea cerrada (7 opciones, una respuesta) el modelo grande no tiene dónde usar su capacidad extra, y encima tardó ~2× más. En una mesa de reclamos esta clasificación corre en *cada* mensaje entrante.
- **El múltiplo (13,8×) es casi el cociente de precios** porque las dos respuestas tienen el mismo largo. Con los precios de este lab sale ~12,5× en input / 25× en output; la guía de demo muestra 16,7× porque usa una tabla de precios anterior.

**Compleja** (2026-09-29): el barato mezcló carta y justificación en un bloque (438 tokens est.); el caro **separó** "Respuesta para el titular" de "Decisión de escalamiento" y nombró cuatro riesgos (regulatorio, financiero/umbral, incumplimiento de SLA, fuga de cliente) (886 tokens est.). Ambos deciden escalar. Costo: **54×**, latencia 24 s vs. 3,9 s.

- **Los dos "aciertan" pero de forma distinta**: el caro entrega una estructura de análisis de riesgo, no solo una carta más larga.
- **El múltiplo de costo depende del precio por token *y* de cuánto decide escribir cada modelo**; por eso puede variar mucho (20×, 34×, 54×) entre corridas sin cambiar código. No fuerces el contraste si en tu corrida sale distinto: mostralo tal cual.

## La conclusión

> Ninguno de los dos modelos decidió nada sobre la plata: eso lo decidió `UMBRAL_APROBACION_HUMANA` en el Ejercicio 1, una constante de Python, sin consumir un token.

La calidad del razonamiento y el control sobre la acción son cosas distintas y se compran en mercados distintos: pagar el modelo caro mejora lo primero y no toca lo segundo.
