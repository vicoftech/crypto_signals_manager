# CURSOR PROMPT — Fixes del sistema de trading (estrategias + contexto de mercado)

## Contexto

Este proyecto es un bot de detección de oportunidades de trading en Binance Spot.
El código vive en `src/strategies/` y `src/core/market_context.py`.
El scanner usa velas **30m**, **150 barras**, con indicadores calculados en `src/core/indicators.py`.

Se detectaron **8 bugs y mejoras** en el análisis del sistema actual.
Hay que aplicarlos **todos** sin romper la interfaz existente:
- Cada estrategia sigue siendo una clase con método `analyze(df, pair, ctx) -> Opportunity | None`
- El helper `simple_long_opportunity` en `base.py` sigue siendo el constructor de `Opportunity`
- Los nombres de clases y archivos no cambian
- Todos los cambios deben tener tests unitarios en `tests/`

---

## FIX 1 — ORB: usa velas incorrectas (🔴 CRÍTICO)

**Archivo:** `src/strategies/orb.py`

**Problema actual:**
```python
# head(4) toma las 4 velas MÁS ANTIGUAS del DataFrame
# Con 150 velas de 30m eso son velas de hace ~75 horas
# No tiene nada que ver con el rango de apertura del día
opening_high = df.head(4)["high"].max()
signal = close > opening_high
```

**Fix requerido:**
```python
import pandas as pd

def analyze(self, df: pd.DataFrame, pair: str, ctx) -> Opportunity | None:
    if not ctx.tradeable:
        return None

    # 1. Ventana horaria — solo válida entre 00:00 y 06:00 UTC
    hora_utc = pd.Timestamp.now(tz="UTC").hour
    if hora_utc >= 6:
        return None

    # 2. Filtrar velas del día UTC actual
    hoy_utc = pd.Timestamp.now(tz="UTC").normalize()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df_hoy = df[df["timestamp"] >= hoy_utc].copy()

    # Necesitamos al menos 4 velas del día para definir el rango
    if len(df_hoy) < 4:
        return None

    # 3. Opening Range = máximo y mínimo de las primeras 4 velas del día
    rango_apertura = df_hoy.head(4)
    opening_high = rango_apertura["high"].max()
    opening_low  = rango_apertura["low"].min()

    # 4. Vela actual (última del df completo) cierra por encima del rango
    close_actual = df["close"].iloc[-1]
    if close_actual <= opening_high:
        return None

    # 5. Volumen de confirmación en la ruptura
    vol_actual = df["volume"].iloc[-1]
    vol_avg_20 = df["volume"].rolling(20).mean().iloc[-1]
    if vol_actual < vol_avg_20 * 1.3:
        return None

    # SL = mínimo del rango de apertura
    sl_price = opening_low
    return self.simple_long_opportunity(df, pair, ctx, sl_lookback=4, sl_override=sl_price)
```

**Tests requeridos en `tests/test_strategies.py`:**
- `test_orb_fuera_de_ventana_horaria` — retorna None si hora_utc >= 6
- `test_orb_sin_velas_del_dia` — retorna None si no hay velas del día actual
- `test_orb_sin_ruptura` — retorna None si close <= opening_high
- `test_orb_sin_volumen` — retorna None si volumen < 1.3× promedio
- `test_orb_señal_valida` — retorna Opportunity con los niveles correctos

---

## FIX 2 — SupportBounce: detecta caídas en vez de rebotes (🔴 CRÍTICO)

**Archivo:** `src/strategies/support_bounce.py`

**Problema actual:**
```python
# Calcula soporte como media de los 2 mínimos más bajos de 50 velas
# Señal si close <= support * 1.003
# Esto detecta precio CAYENDO al soporte, no rebotando desde él
# No hay confirmación alcista, no hay RSI, no hay mecha inferior
support = df["low"].nsmallest(2).mean()
signal = close <= support * 1.003
```

**Fix requerido — lógica completa de rebote:**
```python
def analyze(self, df: pd.DataFrame, pair: str, ctx) -> Opportunity | None:
    if not ctx.tradeable:
        return None

    # 1. Identificar zona de soporte horizontal
    # Soporte = mínimo significativo con al menos 2 toques en las últimas 50 velas
    lows_50 = df["low"].iloc[-50:]
    support = self._calcular_soporte(lows_50)
    if support is None:
        return None

    # 2. El precio tocó el soporte en las últimas 3 velas (algún low rozó la zona)
    margen_toque = support * 1.003
    toco_soporte = df["low"].iloc[-3:].min() <= margen_toque
    if not toco_soporte:
        return None

    # 3. La vela actual CERRÓ POR ENCIMA del soporte (rebotó, no sigue cayendo)
    close_actual = df["close"].iloc[-1]
    if close_actual <= support:
        return None

    # 4. RSI en zona de sobreventa — confirmación de agotamiento bajista
    rsi = df["RSI_14"].iloc[-1]
    if rsi >= 40:
        return None

    # 5. Vela de confirmación alcista con mecha inferior larga
    vela = df.iloc[-1]
    cuerpo_min = min(vela["open"], vela["close"])
    rango_total = vela["high"] - vela["low"] + 1e-10
    mecha_inferior = (cuerpo_min - vela["low"]) / rango_total
    if mecha_inferior < 0.35:   # mecha inferior ocupa al menos 35% del rango
        return None

    # SL = 0.2% por debajo del soporte identificado
    sl_price = support * 0.998
    return self.simple_long_opportunity(df, pair, ctx, sl_lookback=5, sl_override=sl_price)

def _calcular_soporte(self, lows: pd.Series) -> float | None:
    """
    Identifica zona de soporte con al menos 2 toques.
    Agrupa mínimos dentro de un rango del 0.5% entre sí.
    Retorna el nivel promedio del cluster más tocado, o None si no hay zona válida.
    """
    if len(lows) < 10:
        return None

    # Ordenar mínimos y buscar clusters
    sorted_lows = lows.sort_values().values
    clusters = []
    cluster_actual = [sorted_lows[0]]

    for low in sorted_lows[1:]:
        if (low - cluster_actual[0]) / cluster_actual[0] <= 0.005:  # dentro del 0.5%
            cluster_actual.append(low)
        else:
            if len(cluster_actual) >= 2:
                clusters.append(cluster_actual)
            cluster_actual = [low]

    if len(cluster_actual) >= 2:
        clusters.append(cluster_actual)

    if not clusters:
        return None

    # Tomar el cluster con más toques
    mejor_cluster = max(clusters, key=len)
    return sum(mejor_cluster) / len(mejor_cluster)
```

**Tests requeridos:**
- `test_supportbounce_sin_soporte_valido` — retorna None si no hay zona con 2+ toques
- `test_supportbounce_precio_cayendo` — retorna None si close <= support (sigue cayendo)
- `test_supportbounce_rsi_alto` — retorna None si RSI >= 40
- `test_supportbounce_sin_mecha` — retorna None si mecha inferior < 35%
- `test_supportbounce_señal_valida` — retorna Opportunity correcta
- `test_calcular_soporte_sin_cluster` — retorna None si no hay 2 mínimos agrupados

---

## FIX 3 — EMAPullback: no verifica el pullback (🔴 CRÍTICO)

**Archivo:** `src/strategies/ema_pullback.py`

**Problema actual:**
```python
# Solo verifica tendencia — duplica exactamente el evaluador de contexto
# Si el par pasó el contexto, esta estrategia siempre da señal
# No busca un pullback real a la EMA21
signal = ema21 > ema50 and close > ema21
```

**Fix requerido:**
```python
def analyze(self, df: pd.DataFrame, pair: str, ctx) -> Opportunity | None:
    if not ctx.tradeable:
        return None

    ema21 = df["EMA_21"]
    close = df["close"]
    open_ = df["open"]

    # 1. Tendencia alcista confirmada (ya lo garantiza el contexto, pero lo verificamos)
    if not (ema21.iloc[-1] > df["EMA_50"].iloc[-1]):
        return None

    # 2. EL PULLBACK — alguna de las últimas 3 velas tocó la EMA21 por debajo
    # El low de esa vela debe haber llegado hasta la EMA21 o cruzado levemente
    toco_ema = False
    for i in [-3, -2, -1]:
        low_vela  = df["low"].iloc[i]
        ema_vela  = ema21.iloc[i]
        close_ant = close.iloc[i]
        # Toque: el low bajó hasta la EMA21 (con margen 0.1%)
        if low_vela <= ema_vela * 1.001:
            toco_ema = True
            break

    if not toco_ema:
        return None

    # 3. Vela de confirmación — la última vela cerró por encima de EMA21
    if close.iloc[-1] <= ema21.iloc[-1]:
        return None

    # 4. La vela de confirmación es alcista (cierre > apertura)
    if close.iloc[-1] <= open_.iloc[-1]:
        return None

    # 5. El cuerpo de la vela de confirmación es sólido (> 40% del rango)
    vela = df.iloc[-1]
    cuerpo = abs(vela["close"] - vela["open"])
    rango  = vela["high"] - vela["low"] + 1e-10
    if cuerpo / rango < 0.4:
        return None

    return self.simple_long_opportunity(df, pair, ctx, sl_lookback=3)
```

**Tests requeridos:**
- `test_emapullback_sin_pullback` — retorna None si ninguna vela tocó EMA21
- `test_emapullback_cierre_bajo_ema` — retorna None si close <= EMA21
- `test_emapullback_vela_bajista` — retorna None si close <= open
- `test_emapullback_cuerpo_debil` — retorna None si cuerpo < 40% del rango
- `test_emapullback_señal_valida` — retorna Opportunity con SL en mínimo de 3 velas

---

## FIX 4 — MACDCross: demasiado restrictivo (🟡 MODERADO)

**Archivo:** `src/strategies/macd_cross.py`

**Problema actual:**
```python
# Exige MACD < 0 — elimina cruces válidos en zona cero y positiva baja
# En recuperaciones el cruce puede ocurrir justo en 0 y es la señal más fuerte
# Además no verifica que sea un cruce REAL (vela anterior estaba por debajo)
signal = macd > signal_line and macd < 0
```

**Fix requerido:**
```python
def analyze(self, df: pd.DataFrame, pair: str, ctx) -> Opportunity | None:
    if not ctx.tradeable:
        return None

    macd   = df["MACD_12_26_9"]
    signal = df["MACDs_12_26_9"]
    close  = df["close"].iloc[-1]

    macd_actual   = macd.iloc[-1]
    signal_actual = signal.iloc[-1]
    macd_anterior = macd.iloc[-2]
    signal_anterior = signal.iloc[-2]

    # 1. Verificar que es un cruce REAL (la vela anterior estaba por debajo de la señal)
    fue_cruce = macd_anterior <= signal_anterior and macd_actual > signal_actual
    if not fue_cruce:
        return None

    # 2. Aceptar cruces en tres zonas:
    #    a) Bajo cero (momentum inicial — señal más fuerte)
    #    b) Zona cero (±0.1% del precio) — señal de continuación en recuperación
    #    c) Levemente positivo pero histograma acelerando
    umbral_zona_cero = close * 0.001

    cruce_bajo_cero   = macd_actual < 0
    cruce_zona_cero   = abs(macd_actual) <= umbral_zona_cero
    histograma_actual   = df["MACDh_12_26_9"].iloc[-1]
    histograma_anterior = df["MACDh_12_26_9"].iloc[-2]
    cruce_acelerando  = macd_actual > 0 and histograma_actual > histograma_anterior > 0

    if not (cruce_bajo_cero or cruce_zona_cero or cruce_acelerando):
        return None

    # 3. EMA50 alcista como confirmación de tendencia de fondo
    if df["EMA_50"].iloc[-1] < df["EMA_50"].iloc[-5]:
        return None

    return self.simple_long_opportunity(df, pair, ctx, sl_lookback=5)
```

**Tests requeridos:**
- `test_macdc_sin_cruce_real` — retorna None si macd ya estaba por encima en vela anterior
- `test_macdc_macd_positivo_sin_aceleracion` — retorna None si macd > 0 sin histograma creciente
- `test_macdc_cruce_bajo_cero` — retorna Opportunity (caso original)
- `test_macdc_cruce_zona_cero` — retorna Opportunity (caso nuevo: recuperación)
- `test_macdc_cruce_acelerando` — retorna Opportunity (caso nuevo: momentum)
- `test_macdc_ema50_bajista` — retorna None si EMA50 está cayendo

---

## FIX 5 — RangeBreakout: sin confirmación de volumen (🟡 MODERADO)

**Archivo:** `src/strategies/range_breakout.py`

**Problema actual:**
```python
# Solo verifica precio — sin volumen el 40% de las rupturas son falsas
resistencia = df["high"].iloc[-10:].max()
signal = close >= resistencia
```

**Fix requerido:**
```python
def analyze(self, df: pd.DataFrame, pair: str, ctx) -> Opportunity | None:
    if not ctx.tradeable:
        return None

    # 1. Detectar rango lateral previo — ATR de las últimas 10 velas debe ser bajo
    atr_rango    = df["ATRr_14"].iloc[-11:-1].mean()  # ATR promedio del rango (sin la última)
    atr_total    = df["ATRr_14"].rolling(20).mean().iloc[-1]
    # Si el ATR del rango no es más bajo que el promedio general, no era un rango lateral
    if atr_rango > atr_total * 0.9:
        return None

    # 2. Resistencia = máximo de las últimas 10 velas (sin incluir la actual)
    resistencia = df["high"].iloc[-11:-1].max()
    close_actual = df["close"].iloc[-1]
    if close_actual < resistencia:
        return None

    # 3. Volumen de confirmación en la vela de ruptura
    vol_actual = df["volume"].iloc[-1]
    vol_avg_20 = df["volume"].rolling(20).mean().iloc[-1]
    if vol_actual < vol_avg_20 * 1.3:
        return None

    # 4. La vela de ruptura cierra en la mitad superior de su rango (fuerza real)
    vela = df.iloc[-1]
    mitad_rango = (vela["high"] + vela["low"]) / 2
    if vela["close"] < mitad_rango:
        return None

    return self.simple_long_opportunity(df, pair, ctx, sl_lookback=10)
```

**Tests requeridos:**
- `test_rangebreakout_sin_rango_lateral` — retorna None si ATR del rango >= 90% del ATR general
- `test_rangebreakout_sin_ruptura` — retorna None si close < resistencia
- `test_rangebreakout_sin_volumen` — retorna None si volumen < 1.3× promedio
- `test_rangebreakout_cierre_debil` — retorna None si close < mitad del rango de la vela
- `test_rangebreakout_señal_valida` — retorna Opportunity correcta

---

## FIX 6 — Momentum: no verifica tamaño ni calidad del impulso (🟡 MODERADO)

**Archivo:** `src/strategies/momentum.py`

**Problema actual:**
```python
# Solo verifica que las 3 velas sean verdes (close > open)
# Tres microvelas verdes de 0.01% activan la señal
# No hay verificación de tamaño de cuerpo, RSI, ni pullback
c1 = df["close"].iloc[-1] > df["open"].iloc[-1]
c2 = df["close"].iloc[-2] > df["open"].iloc[-2]
c3 = df["close"].iloc[-3] > df["open"].iloc[-3]
signal = c1 and c2 and c3
```

**Fix requerido:**
```python
def analyze(self, df: pd.DataFrame, pair: str, ctx) -> Opportunity | None:
    if not ctx.tradeable:
        return None

    # 1. Las últimas 3 velas son alcistas Y con cuerpo sólido
    for i in [-3, -2, -1]:
        vela   = df.iloc[i]
        cuerpo = abs(vela["close"] - vela["open"])
        rango  = vela["high"] - vela["low"] + 1e-10
        es_alcista    = vela["close"] > vela["open"]
        cuerpo_solido = (cuerpo / rango) >= 0.4  # cuerpo ocupa >= 40% del rango

        if not es_alcista or not cuerpo_solido:
            return None

    # 2. El impulso tiene magnitud real — el conjunto de 3 velas subió >= 0.5%
    precio_inicio  = df["open"].iloc[-3]
    precio_fin     = df["close"].iloc[-1]
    magnitud_impulso = (precio_fin - precio_inicio) / precio_inicio
    if magnitud_impulso < 0.005:
        return None

    # 3. RSI entre 50 y 70 — momentum sin sobrecompra
    rsi = df["RSI_14"].iloc[-1]
    if not (50 <= rsi <= 70):
        return None

    # 4. Volumen creciente a lo largo del impulso (cada vela con más volumen que la anterior)
    vol_1 = df["volume"].iloc[-3]
    vol_2 = df["volume"].iloc[-2]
    vol_3 = df["volume"].iloc[-1]
    if not (vol_3 >= vol_2 >= vol_1):
        # Si el volumen no es estrictamente creciente, al menos que la última vela tenga volumen activo
        vol_avg = df["volume"].rolling(20).mean().iloc[-1]
        if vol_3 < vol_avg * 1.0:
            return None

    return self.simple_long_opportunity(df, pair, ctx, sl_lookback=3)
```

**Tests requeridos:**
- `test_momentum_vela_bajista` — retorna None si alguna vela es bajista
- `test_momentum_cuerpo_debil` — retorna None si cuerpo < 40% del rango en alguna vela
- `test_momentum_impulso_chico` — retorna None si el movimiento total < 0.5%
- `test_momentum_rsi_alto` — retorna None si RSI > 70
- `test_momentum_rsi_bajo` — retorna None si RSI < 50
- `test_momentum_sin_volumen` — retorna None si volumen bajo
- `test_momentum_señal_valida` — retorna Opportunity correcta

---

## FIX 7 — MarketContext: umbral de volumen demasiado estricto (🟢 MEJORA)

**Archivo:** `src/core/market_context.py`

**Problema actual:**
```python
# Exige volumen > 110% del promedio
# En rebotes y recuperaciones el volumen inicial es moderado pero real
volume_state = "ACTIVE" if vol_current > vol_avg * 1.1 else "QUIET"
```

**Fix requerido:**
```python
# Bajar umbral a 90% — captura recuperaciones con volumen moderado
volume_state = "ACTIVE" if vol_current > vol_avg * 0.9 else "QUIET"
```

---

## FIX 8 — MarketContext: no detecta reversiones tempranas (🟢 MEJORA)

**Archivo:** `src/core/market_context.py`

**Problema actual:**
```python
# Exige tendencia completamente establecida: EMA21 > EMA50 Y close > EMA21
# En las primeras horas de un rebote el precio ya subió pero las EMAs
# tardan varios períodos en cruzarse — el par se descarta aunque el movimiento sea real
trend == "BULLISH"  # solo si EMA21 > EMA50 AND close > EMA21
```

**Fix requerido — agregar detección de reversión temprana:**
```python
ema21       = df["EMA_21"].iloc[-1]
ema50       = df["EMA_50"].iloc[-1]
close       = df["close"].iloc[-1]
ema21_hace3 = df["EMA_21"].iloc[-4]  # EMA21 hace 3 velas (1.5 horas en 30m)

# Tendencia establecida (criterio original)
tendencia_establecida = ema21 > ema50 and close > ema21

# Reversión temprana — precio ya sobre EMA50 y EMA21 girando hacia arriba
ema21_subiendo = ema21 > ema21_hace3
reversion_temprana = close > ema50 and ema21_subiendo and close > ema21

if tendencia_establecida or reversion_temprana:
    trend = "BULLISH"
elif ema21 < ema50 and close < ema21:
    trend = "BEARISH"
else:
    trend = "SIDEWAYS"
```

**Tests requeridos en `tests/test_market_context.py`:**
- `test_contexto_tendencia_establecida` — BULLISH cuando EMA21 > EMA50 y close > EMA21
- `test_contexto_reversion_temprana` — BULLISH cuando close > EMA50 y EMA21 subiendo
- `test_contexto_reversion_temprana_ema21_plana` — SIDEWAYS si EMA21 no está subiendo
- `test_contexto_volumen_moderado_activo` — ACTIVE con volumen al 95% del promedio
- `test_contexto_volumen_muy_bajo_quieto` — QUIET con volumen al 80% del promedio

---

## Instrucciones generales para Cursor

1. **Leer primero** los archivos actuales antes de modificar:
   - `src/strategies/orb.py`
   - `src/strategies/support_bounce.py`
   - `src/strategies/ema_pullback.py`
   - `src/strategies/macd_cross.py`
   - `src/strategies/range_breakout.py`
   - `src/strategies/momentum.py`
   - `src/core/market_context.py`

2. **No romper** la interfaz de `simple_long_opportunity` en `src/strategies/base.py`.
   Si necesita un `sl_override` para pasar un SL calculado externamente (ORB, SupportBounce),
   agregar ese parámetro opcional: `sl_override: float | None = None`.
   Si `sl_override` está presente, usarlo en lugar del `min(low[-sl_lookback:])`.

3. **Orden de implementación recomendado:**
   1. Fix `base.py` — agregar `sl_override` a `simple_long_opportunity`
   2. Fix `market_context.py` — Fixes 7 y 8 (más simples, no rompen nada)
   3. Fix `ema_pullback.py` — Fix 3
   4. Fix `macd_cross.py` — Fix 4
   5. Fix `range_breakout.py` — Fix 5
   6. Fix `momentum.py` — Fix 6
   7. Fix `support_bounce.py` — Fix 2 (requiere `_calcular_soporte`)
   8. Fix `orb.py` — Fix 1 (requiere columna `timestamp` en el DataFrame)

4. **Verificar que el DataFrame tiene columna `timestamp`** en UTC antes de aplicar Fix 1.
   Si no existe, agregarla en `src/core/indicators.py` o en el scanner al descargar las velas.

5. **Correr todos los tests** al final: `pytest tests/ -v`
   Todos deben pasar en verde antes de considerar el trabajo terminado.

6. **No cambiar** `src/config.py`, `src/lambdas/scanner/handler.py`,
   ni `src/core/indicators.py` salvo para agregar `timestamp` al DataFrame si falta.

---

## Resultado esperado

Antes de los fixes: **2 oportunidades detectadas** en un día de mercado activo (+4.3%).
Después de los fixes: **8 a 15 oportunidades** en condiciones similares.

Las mejoras provienen de:
- ORB funcionando correctamente en ventana horaria real
- SupportBounce detectando rebotes reales, no caídas
- EMAPullback buscando pullbacks reales, no duplicando el contexto
- MACDCross capturando cruces en recuperaciones (zona cero)
- RangeBreakout con confirmación de volumen y rango lateral previo
- Momentum con impulso real verificado
- Contexto capturando reversiones tempranas antes de que las EMAs se crucen
