# Análisis del contexto de mercado (`MarketContext`)

Este documento describe **cómo el bot evalúa el contexto** antes de aplicar las estrategias de entrada. La lógica vive en `src/core/market_context.py` (`MarketContextEvaluator.evaluate`) y usa el mismo **DataFrame de velas 30m** ya enriquecido con indicadores (`src/core/indicators.py`).

---

## Dónde entra en el flujo

1. El scanner descarga velas **30m** (150 barras) y llama a `enrich_dataframe`.
2. Se ejecuta **una sola vez por par**: `MarketContextEvaluator.evaluate(df, pair)`.
3. Si `ctx.tradeable` es **falso**, **no se evalúan** las estrategias para ese par en ese ciclo (se registran como omitidas por mercado en los agregados del scanner).

No hay un segundo paso de “contexto” por estrategia: el filtro es **único y global por par**.

---

## Objeto `MarketContext`

Campos que se rellenan:

| Campo | Significado |
|--------|-------------|
| `pair` | Símbolo (ej. `BTCUSDT`) |
| `trend` | `BULLISH`, `BEARISH` o `SIDEWAYS` |
| `volatility` | `LOW`, `MEDIUM` o `HIGH` |
| `volume_state` | `ACTIVE` o `QUIET` |
| `atr_viable` | `True` si el ATR relativo permite un stop “razonable” respecto a `MAX_SL_PCT` |
| `bb_squeeze` | `True` si las bandas de Bollinger están comprimidas respecto a su reciente |
| `tradeable` | `True` solo si se cumplen **todas** las condiciones listadas abajo |
| `reason` | Cadena de depuración con los flags anteriores (útil en logs) |

---

## 1. Tendencia (`trend`)

Datos: última vela, `EMA_21` y `EMA_50` del **close** (y `EMA_21` de la vela con índice `-4` si hay al menos 4 filas).

- **Tendencia establecida:** `EMA_21 > EMA_50` **y** `close > EMA_21` → cuenta como alcista fuerte.
- **Reversión temprana (también BULLISH):** `close > EMA_50`, `close > EMA_21`, y `EMA_21` actual **>** `EMA_21` de hace 3 velas (`iloc[-4]`) — útil cuando el precio ya recupera pero el cruce de medias aún no está cerrado.
- **BEARISH** si `EMA_21 < EMA_50` **y** `close < EMA_21`.
- **SIDEWAYS** en el resto de casos.

Para **tradeable** hace falta **`trend == BULLISH`** (ya sea por tendencia establecida o por reversión temprana).

---

## 2. Volatilidad (`volatility`)

Se usa el **ATR relativo** `ATRr_14` (en el código: TR medio 14 períodos dividido por `close`; ver `indicators.py`).

- `atr_current` = último `ATRr_14`.
- `atr_avg` = media móvil de **20** períodos del mismo `ATRr_14`, evaluada en la última fila.
- `ratio = atr_current / atr_avg` (si `atr_avg` es 0, se usa ratio 0).

Clasificación:

- **HIGH** si `ratio > 1.3`
- **MEDIUM** si `0.7 < ratio ≤ 1.3`
- **LOW** si `ratio ≤ 0.7`

Para **tradeable** se exige **`volatility` en `MEDIUM` o `HIGH`** (se filtra mercado demasiado quieto).

---

## 3. Volumen (`volume_state`)

- `vol_avg` = media móvil de **20** velas del `volume`, última fila.
- **ACTIVE** si `volume` actual **>** `vol_avg × 0.9` (umbral relajado respecto a 110%).
- **QUIET** en caso contrario.

Para **tradeable** hace falta **`volume_state == ACTIVE`**.

---

## 4. ATR “viable” (`atr_viable`)

Comprueba que la volatilidad no obligue a un stop demasiado ancho en términos relativos:

- `atr_viable = (atr_current × 0.5) ≤ max_sl_pct`

`max_sl_pct` sale de configuración (`Settings.max_sl_pct`, env `MAX_SL_PCT`, **por defecto 0.02 = 2%**).

Interpretación: la mitad del ATR relativo actual no debe superar el máximo de stop permitido; si el mercado es muy expansivo en relación a ese tope, el par **no** se considera tradeable.

---

## 5. Compresión de Bollinger (`bb_squeeze`)

Sobre bandas ya calculadas (`BBU_20_2.0`, `BBL_20_2.0`, `BBM_20_2.0`):

- Ancho relativo por vela: `(BBU − BBL) / BBM`.
- Se compara el ancho **último** con la **media móvil de 20** de ese ancho (última fila).
- **`bb_squeeze = True`** si el ancho actual **< 70%** de esa media (`× 0.7`).

Un squeeze se interpreta como **rango muy apretado**; para **tradeable** se exige **`not bb_squeeze`** (no operar en compresión fuerte según esta regla).

---

## 6. Regla final: `tradeable`

El par es **tradeable** solo si **simultáneamente**:

1. `trend == "BULLISH"`
2. `volatility in ("MEDIUM", "HIGH")`
3. `volume_state == "ACTIVE"`
4. `atr_viable is True`
5. `bb_squeeze is False`

Si falla cualquiera, `tradeable` es `False` y el campo `reason` sigue mostrando el estado de cada componente para diagnóstico (por ejemplo en logs: `skip BTCUSDT: trend=... | ...`).

---

## Relación con las estrategias

- El **contexto** responde a: *“¿Este par, en este momento, tiene estructura alcista, volumen, volatilidad suficiente y sin squeeze extremo?”*
- Las **estrategias** (`EMAPullback`, etc.) responden a: *“¿Hay un patrón de entrada concreto en el precio/indicadores?”*  
  Además, `simple_long_opportunity` vuelve a comprobar `ctx.tradeable` antes de devolver una oportunidad (doble capa coherente con el mismo criterio).

---

## Parámetros configurables relevantes

| Variable / setting | Rol en contexto |
|--------------------|-----------------|
| `MAX_SL_PCT` (`max_sl_pct`) | Umbral usado en `atr_viable` |

El resto (`MIN_RR_RATIO`, `ENTRY_DRIFT_MAX_PCT`, etc.) afecta a **oportunidades ya generadas**, no al cálculo de `MarketContext`.
