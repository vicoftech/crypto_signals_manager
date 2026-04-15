# Las 6 estrategias del scanner: ejecución, datos y cálculos

Este documento describe **cómo se ejecutan** las estrategias en el código actual (`src/strategies/`, `src/lambdas/scanner/handler.py`) y **qué series y fórmulas** intervienen. Todo es **solo LONG** (compras).

---

## Pipeline común (antes de cada estrategia)

1. **Velas**  
   El scanner pide a Binance **OHLCV en timeframe 30m**, **150 velas**, por par activo (`scanner/handler.py`).

2. **Indicadores** (`src/core/indicators.py` — `enrich_dataframe`)  
   Si existe `open_time`, se añade **`timestamp`** (UTC) para estrategias que filtran por día (ORB).  
   Sobre `open`, `high`, `low`, `close`, `volume` se calculan EMA, RSI, MACD, ATR relativo, Bollinger (ver tabla en `docs/contexto-mercado.md` o el código fuente).

3. **Contexto de mercado** (`src/core/market_context.py`)  
   Una sola evaluación por par. Ver **`docs/contexto-mercado.md`** para la regla completa de `tradeable` (incluye reversión temprana y umbral de volumen 90%).

4. **Estrategia**  
   Solo si el par es tradeable, para cada nombre en la lista del par (`PairsManager`) se llama `analyze(df, pair, ctx)`.

5. **Después de una señal** (`calculator.with_risk`, `filters`)  
   Drift de entrada, R/R, filtros `MIN_RR_RATIO` y `MAX_SL_PCT` (sin cambios respecto al diseño original).

---

## Helper común: `simple_long_opportunity` (`src/strategies/base.py`)

- **Entrada:** último `close`.
- **Stop loss:** por defecto mínimo de los últimos `sl_lookback` `low`; si se pasa **`sl_override`**, se usa ese precio (ORB, SupportBounce).
- **Riesgo** `risk = entry − sl`. Si `risk ≤ 0`, no hay oportunidad.
- **TP1** = `entry + 1.5 × risk`, **TP2** = `entry + 3.0 × risk`.

El **DataFrame** del scanner es siempre **30m**.

---

## 1. EMAPullback (`EMAPullback`)

1. `EMA_21` última &gt; `EMA_50` última.  
2. En alguna de las **últimas 3 velas**, el `low` llegó hasta la EMA21 del mismo instante: `low ≤ EMA_21 × 1.001`.  
3. La **última** vela cierra **por encima** de `EMA_21`.  
4. Última vela alcista: `close > open`.  
5. Cuerpo de la última vela ≥ **40%** del rango (`high − low`).

**SL:** mínimo de los últimos 3 `low` (sin override).

---

## 2. RangeBreakout (`RangeBreakout`)

1. **Rango lateral previo:** media de `ATRr_14` en velas `-11` a `-2` (sin la última) **≤** `0.9 ×` media móvil 20 del `ATRr_14` en la última fila (el bloque previo debe ser más “quieto” que el promedio reciente).  
2. **Resistencia** = máximo de `high` en velas `-11` … `-2` (sin incluir la vela actual).  
3. `close` actual **≥** resistencia (ruptura).  
4. `volume` actual **≥** `1.3 ×` media móvil 20 del volumen.  
5. La vela de ruptura cierra en la **mitad superior** del propio rango de esa vela.

**SL:** mínimo de los últimos 10 `low`.

---

## 3. SupportBounce (`SupportBounce`)

1. **Soporte:** sobre los últimos 50 `low`, se agrupan mínimos que distan ≤ **0,5%** entre sí; debe existir un cluster con **al menos 2 toques**; el nivel es la media del cluster con más toques (`_calcular_soporte`).  
2. En las últimas 3 velas, algún `low` rozó la zona: `min(low[-3:]) ≤ support × 1.003`.  
3. `close` actual **>** `support` (reapertura por encima).  
4. `RSI_14` último **&lt; 40**.  
5. **Mecha inferior** de la última vela ≥ **35%** del rango de esa vela.

**SL:** `support × 0.998` (override).

---

## 4. MACDCross (`MACDCross`)

1. **Cruce reciente:** vela anterior `MACD ≤ señal`, vela actual `MACD > señal`.  
2. Zona válida (cualquiera):  
   - cruce **bajo cero** (`MACD < 0`), o  
   - **zona cero:** `|MACD| ≤ 0.1%` del precio actual, o  
   - **aceleración:** `MACD > 0` y histograma `MACDh` creciente y ambos histogramas &gt; 0.  
3. **EMA_50** última **≥** `EMA_50` de hace 5 velas (pendiente de fondo no bajista).

**SL:** mínimo de los últimos 5 `low`.

---

## 5. ORB (`ORB`)

Solo si existe columna **`timestamp`** (UTC).

1. Hora UTC actual **&lt; 6** (ventana 00:00–06:00 UTC).  
2. Velas del **día UTC** actual: `timestamp ≥` inicio del día UTC.  
3. Al menos **4 velas** ese día; **Opening range** = primeras 4 velas del día: `opening_high` / `opening_low` = max/min de esas 4.  
4. `close` actual **>** `opening_high`.  
5. `volume` actual **≥** `1.3 ×` media móvil 20 del volumen.

**SL:** `opening_low` (override).

---

## 6. Momentum (`Momentum`)

1. Últimas **3 velas** alcistas (`close > open`) y cada cuerpo ≥ **40%** del rango de su vela.  
2. Impulso: `(close[-1] − open[-3]) / open[-3] ≥ 0.5%`.  
3. `RSI_14` en **[50, 70]**.  
4. Volumen: o bien `vol[-1] ≥ vol[-2] ≥ vol[-3]`, o si no, al menos `vol[-1] ≥` media móvil 20 del volumen.

**SL:** mínimo de los últimos 3 `low`.

---

## Parámetros globales

`MIN_RR_RATIO`, `MAX_SL_PCT`, `ENTRY_DRIFT_MAX_PCT`, etc.: `src/config.py` y variables de entorno en el despliegue.
