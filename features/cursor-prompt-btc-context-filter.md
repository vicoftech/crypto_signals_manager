# CURSOR PROMPT — Filtro de contexto global BTC + trailing agresivo en mercado adverso

---

## Contexto

El evaluador de contexto ya filtra SIDEWAYS y BEARISH por par individualmente.
Lo que falta es:

1. Verificar el contexto global de BTC antes de operar cualquier altcoin
   (el 80% de las altcoins correlacionan fuertemente con BTC)
2. Ajustar el trailing más agresivamente cuando el mercado gira en contra
   durante una posición abierta
3. Alertar cuando un trade está estancado en mercado lateral sin llegar a TP1

Estos cambios NO modifican las estrategias ni el evaluador de contexto individual.
Son capas adicionales de protección.

---

## CAMBIO 1 — Contexto global de BTC para altcoins

**Archivo:** `src/core/market_context.py`

### Nuevo dataclass `BtcContext`

```python
@dataclass
class BtcContext:
    trend: str          # "BULLISH" | "BEARISH" | "SIDEWAYS"
    volatility: str     # "HIGH" | "MEDIUM" | "LOW"
    ema21: float
    ema50: float
    close: float
    atr_ratio: float
    evaluated_at: str   # ISO timestamp — para saber si el caché está vigente
```

### Cache de BTC por ciclo del scanner

BTC se evalúa UNA sola vez por ciclo del scanner y se reutiliza para todos los pares.
No hacer una llamada a Binance por cada altcoin evaluada.

```python
# Variable de módulo — se resetea en cada invocación del Lambda
_btc_context_cache: BtcContext | None = None
_btc_context_cache_scan_id: str | None = None


async def get_btc_context(scan_id: str) -> BtcContext:
    """
    Retorna el contexto de BTC para el ciclo actual.
    Se evalúa una sola vez por ciclo (cacheado por scan_id).
    """
    global _btc_context_cache, _btc_context_cache_scan_id

    # Si ya se evaluó en este ciclo, reutilizar
    if _btc_context_cache is not None and _btc_context_cache_scan_id == scan_id:
        return _btc_context_cache

    # Pedir datos de BTC a Binance (30m, 100 velas)
    btc_df = await binance_client.get_ohlcv("BTCUSDT", "30m", limit=100)
    btc_df = enrich_dataframe(btc_df)

    ema21 = btc_df["EMA_21"].iloc[-1]
    ema50 = btc_df["EMA_50"].iloc[-1]
    close = btc_df["close"].iloc[-1]

    if ema21 > ema50 and close > ema21:
        trend = "BULLISH"
    elif ema21 < ema50 and close < ema21:
        trend = "BEARISH"
    else:
        trend = "SIDEWAYS"

    atr_current = btc_df["ATRr_14"].iloc[-1]
    atr_avg     = btc_df["ATRr_14"].rolling(20).mean().iloc[-1]
    atr_ratio   = atr_current / atr_avg if atr_avg > 0 else 0

    if atr_ratio > 1.3:   volatility = "HIGH"
    elif atr_ratio > 0.7: volatility = "MEDIUM"
    else:                 volatility = "LOW"

    _btc_context_cache = BtcContext(
        trend        = trend,
        volatility   = volatility,
        ema21        = round(ema21, 4),
        ema50        = round(ema50, 4),
        close        = round(close, 4),
        atr_ratio    = round(atr_ratio, 4),
        evaluated_at = datetime.utcnow().isoformat(),
    )
    _btc_context_cache_scan_id = scan_id

    logger.info(json.dumps({
        "event_type": "btc_context",
        "scan_id":    scan_id,
        "timestamp":  datetime.utcnow().isoformat(),
        "trend":      trend,
        "volatility": volatility,
        "ema21":      round(ema21, 4),
        "ema50":      round(ema50, 4),
        "close":      round(close, 4),
        "atr_ratio":  round(atr_ratio, 4),
    }))

    return _btc_context_cache
```

### Modificar `MarketContextEvaluator.evaluate()`

Agregar el filtro de BTC global después de la evaluación individual del par:

```python
@staticmethod
async def evaluate(
    df: pd.DataFrame,
    pair: str,
    pair_config: dict,
    scan_id: str
) -> MarketContext:
    """
    Evalúa el contexto de mercado de un par.
    Para altcoins, verifica adicionalmente el contexto global de BTC.
    """

    # ── 1. Evaluación individual del par (lógica actual sin cambios) ──────
    ema21  = df["EMA_21"].iloc[-1]
    ema50  = df["EMA_50"].iloc[-1]
    close  = df["close"].iloc[-1]

    # Tendencia establecida
    tendencia_establecida = ema21 > ema50 and close > ema21

    # Reversión temprana
    ema21_hace3    = df["EMA_21"].iloc[-4] if len(df) >= 4 else ema21
    ema21_subiendo = ema21 > ema21_hace3
    reversion_temprana = close > ema50 and ema21_subiendo and close > ema21

    if tendencia_establecida or reversion_temprana:
        trend = "BULLISH"
    elif ema21 < ema50 and close < ema21:
        trend = "BEARISH"
    else:
        trend = "SIDEWAYS"

    atr_current  = df["ATRr_14"].iloc[-1]
    atr_avg      = df["ATRr_14"].rolling(20).mean().iloc[-1]
    ratio        = atr_current / atr_avg if atr_avg > 0 else 0
    volatility   = "HIGH" if ratio > 1.3 else "MEDIUM" if ratio > 0.7 else "LOW"
    vol_avg      = df["volume"].rolling(20).mean().iloc[-1]
    volume_state = "ACTIVE" if df["volume"].iloc[-1] > vol_avg * 0.9 else "QUIET"
    atr_viable   = (atr_current * 0.5) <= MAX_SL_PCT
    bb_width     = (df["BBU_20_2.0"] - df["BBL_20_2.0"]) / df["BBM_20_2.0"]
    bb_squeeze   = bb_width.iloc[-1] < bb_width.rolling(20).mean().iloc[-1] * 0.7

    # Tradeable por criterios individuales del par
    tradeable_individual = (
        trend == "BULLISH" and
        volatility in ("MEDIUM", "HIGH") and
        volume_state == "ACTIVE" and
        atr_viable and
        not bb_squeeze
    )

    # Si ya no pasa el filtro individual, retornar directamente
    if not tradeable_individual:
        reason = _build_reason(trend, volatility, volume_state, atr_viable, bb_squeeze)
        return MarketContext(
            pair=pair, tier=pair_config.get("tier", "1"),
            trend=trend, volatility=volatility, volume_state=volume_state,
            atr_viable=atr_viable, bb_squeeze=bb_squeeze,
            tradeable=False, reason=reason,
            btc_trend=None, btc_filter_applied=False
        )

    # ── 2. Filtro global de BTC para altcoins ─────────────────────────────
    es_btc = pair in ("BTCUSDT", "BTCUSDC", "BTCBUSD")
    btc_filter_applied = False
    btc_trend = None

    if not es_btc:
        btc_ctx = await get_btc_context(scan_id)
        btc_trend = btc_ctx.trend
        btc_filter_applied = True

        # BTC bajista → no operar ninguna altcoin
        if btc_ctx.trend == "BEARISH":
            return MarketContext(
                pair=pair, tier=pair_config.get("tier", "1"),
                trend=trend, volatility=volatility, volume_state=volume_state,
                atr_viable=atr_viable, bb_squeeze=bb_squeeze,
                tradeable=False,
                reason=f"BTC BEARISH — altcoins en riesgo de correlación",
                btc_trend=btc_trend, btc_filter_applied=btc_filter_applied
            )

        # BTC lateral + par lateral → doble confirmación de no operar
        if btc_ctx.trend == "SIDEWAYS" and trend == "SIDEWAYS":
            return MarketContext(
                pair=pair, tier=pair_config.get("tier", "1"),
                trend=trend, volatility=volatility, volume_state=volume_state,
                atr_viable=atr_viable, bb_squeeze=bb_squeeze,
                tradeable=False,
                reason=f"BTC SIDEWAYS + {pair} SIDEWAYS — doble lateral, no operar",
                btc_trend=btc_trend, btc_filter_applied=btc_filter_applied
            )

        # BTC lateral pero par alcista → permitir con advertencia en el log
        if btc_ctx.trend == "SIDEWAYS" and trend == "BULLISH":
            logger.info(
                f"[CTX] {pair} BULLISH con BTC SIDEWAYS — "
                f"oportunidad permitida con mayor cautela"
            )

    # ── 3. Tradeable final ────────────────────────────────────────────────
    return MarketContext(
        pair=pair, tier=pair_config.get("tier", "1"),
        trend=trend, volatility=volatility, volume_state=volume_state,
        atr_viable=atr_viable, bb_squeeze=bb_squeeze,
        tradeable=True,
        reason="OK",
        btc_trend=btc_trend,
        btc_filter_applied=btc_filter_applied
    )
```

### Actualizar el dataclass `MarketContext`

```python
@dataclass
class MarketContext:
    pair: str
    tier: str
    trend: str
    volatility: str
    volume_state: str
    atr_viable: bool
    bb_squeeze: bool
    tradeable: bool
    reason: str
    btc_trend: str | None        # tendencia de BTC al momento de la evaluación
    btc_filter_applied: bool     # True si se aplicó el filtro de BTC (es altcoin)
```

### Actualizar log de contexto para incluir BTC

```python
# En market_context.py — log al final de evaluate()
logger.info(json.dumps({
    "event_type":          "market_context",
    "scan_id":             scan_id,
    "timestamp":           datetime.utcnow().isoformat(),
    "pair":                ctx.pair,
    "tier":                ctx.tier,
    "trend":               ctx.trend,
    "volatility":          ctx.volatility,
    "volume_state":        ctx.volume_state,
    "atr_viable":          ctx.atr_viable,
    "bb_squeeze":          ctx.bb_squeeze,
    "tradeable":           ctx.tradeable,
    "btc_trend":           ctx.btc_trend,
    "btc_filter_applied":  ctx.btc_filter_applied,
    "reason":              ctx.reason,
    # valores numéricos para Athena
    "ema21":               round(ema21, 4),
    "ema50":               round(ema50, 4),
    "close":               round(close, 4),
    "atr_current":         round(atr_current, 6),
    "atr_avg":             round(atr_avg, 6),
    "atr_ratio":           round(ratio, 4),
    "vol_actual":          round(df["volume"].iloc[-1], 2),
    "vol_avg":             round(vol_avg, 2),
    "vol_ratio":           round(df["volume"].iloc[-1] / vol_avg if vol_avg > 0 else 0, 4),
    "session":             _session(),
}))
```

---

## CAMBIO 2 — Trailing agresivo cuando el mercado gira en contra

**Archivo:** `src/core/simulator.py`

Cuando el mercado de un par gira a BEARISH o SIDEWAYS mientras hay una
posición abierta, el trailing step se vuelve más agresivo para proteger ganancias.

### Constantes nuevas

```python
# src/core/simulator.py

TRAILING_STEP_NORMAL     = 0.005   # 0.5% — trailing normal
TRAILING_STEP_AGGRESSIVE = 0.003   # 0.3% — trailing cuando mercado gira adverso
TRAILING_STEP_EMERGENCY  = 0.002   # 0.2% — trailing cuando BTC además está bajista

# Umbral de tiempo sin llegar a TP1 en mercado lateral → candidato a cierre
STALL_THRESHOLD_MINUTES  = 120     # 2 horas sin movimiento significativo
STALL_PRICE_THRESHOLD    = 0.001   # movimiento < 0.1% en las últimas 4 velas = estancado
```

### Modificar `evaluate()` del simulador

```python
# src/core/simulator.py

async def evaluate(trade: Trade, current_price: float, scan_id: str) -> None:
    """
    Evalúa el estado de una posición abierta.
    Ahora recibe scan_id para poder consultar el contexto actual del mercado.
    """

    # ── 1. MFE y MAE ─────────────────────────────────────────────────────
    if current_price > trade.max_favorable_excursion:
        trade.max_favorable_excursion = current_price
    if current_price < trade.max_adverse_excursion:
        trade.max_adverse_excursion = current_price

    # ── 2. P&L circunstancial ────────────────────────────────────────────
    pnl_bruto = (current_price - trade.entry_price) / trade.entry_price * trade.position_size_usd
    comision_salida_est = trade.position_size_usd * 0.001
    trade.pnl_usd = round(pnl_bruto - trade.commission_usd - comision_salida_est, 2)

    # ── 3. Evaluar contexto actual del mercado ───────────────────────────
    trailing_step = TRAILING_STEP_NORMAL
    contexto_adverso = False
    razon_adverso = ""

    try:
        # Obtener contexto actual del par
        df_actual = await binance_client.get_ohlcv(trade.pair, "30m", limit=60)
        df_actual = enrich_dataframe(df_actual)
        ctx_actual = await MarketContextEvaluator.evaluate(
            df_actual, trade.pair, {"tier": trade.tier}, scan_id
        )

        # Obtener contexto actual de BTC
        btc_ctx = await get_btc_context(scan_id)

        # Determinar nivel de adversidad del mercado
        if ctx_actual.trend == "BEARISH" and btc_ctx.trend == "BEARISH":
            # Peor caso: par bajista + BTC bajista
            trailing_step = TRAILING_STEP_EMERGENCY
            contexto_adverso = True
            razon_adverso = f"{trade.pair} BEARISH + BTC BEARISH"

        elif ctx_actual.trend == "BEARISH":
            # Par giró bajista
            trailing_step = TRAILING_STEP_AGGRESSIVE
            contexto_adverso = True
            razon_adverso = f"{trade.pair} giró BEARISH"

        elif ctx_actual.trend == "SIDEWAYS" and btc_ctx.trend == "BEARISH":
            # Par lateral pero BTC bajista
            trailing_step = TRAILING_STEP_AGGRESSIVE
            contexto_adverso = True
            razon_adverso = f"{trade.pair} SIDEWAYS con BTC BEARISH"

        if contexto_adverso:
            logger.info(
                f"[SIM] {trade.pair} — contexto adverso detectado: {razon_adverso} "
                f"| trailing agresivo: {trailing_step:.1%}"
            )

    except Exception as e:
        # Si falla la consulta del contexto, continuar con trailing normal
        logger.warning(f"[SIM] No se pudo evaluar contexto actual de {trade.pair}: {e}")
        trailing_step = TRAILING_STEP_NORMAL

    # ── 4. Evaluar SL ────────────────────────────────────────────────────
    sl_activo = trade.trailing_sl_final if trade.trailing_activated else trade.sl_initial

    if current_price <= sl_activo:
        slip = SL_EXECUTION_SLIPPAGE.get(trade.pair, 0.0003)
        precio_ejecucion = sl_activo * (1 - slip)
        razon = "TRAILING_SL" if trade.trailing_activated else "SL"
        await close_trade(trade, precio_ejecucion, razon)
        return

    # ── 5. Alerta zona de peligro ────────────────────────────────────────
    distancia_sl = (current_price - sl_activo) / trade.entry_price
    if distancia_sl < 0.003 and not trade.danger_zone_notified:
        await notify_danger_zone(trade, current_price, sl_activo, contexto_adverso)
        trade.danger_zone_notified = True

    # ── 6. Evaluar TP1 ───────────────────────────────────────────────────
    if not trade.tp1_hit and current_price >= trade.tp1_price:
        trade.tp1_hit = True
        trade.tp1_hit_at = datetime.utcnow().isoformat()
        trade.trailing_activated = True
        # Inicializar trailing SL en la entrada (breakeven)
        trade.trailing_sl_final = trade.entry_price
        await notify_tp1_reached(trade, current_price)

    # ── 7. Actualizar trailing con step dinámico ─────────────────────────
    if trade.trailing_activated:
        updated = update_trailing_sl(trade, current_price, trailing_step)
        if updated:
            trade.trailing_updates_count += 1
            await notify_trailing_update(trade, current_price, trailing_step, contexto_adverso)

    # ── 8. Evaluar TP2 ───────────────────────────────────────────────────
    if trade.tp1_hit and current_price >= trade.tp2_price:
        await close_trade(trade, trade.tp2_price, "TP2")
        return

    # ── 9. Detectar trade estancado ──────────────────────────────────────
    if not trade.tp1_hit:
        await check_stalled_trade(trade, current_price, ctx_actual if 'ctx_actual' in dir() else None)

    # ── 10. Persistir estado ─────────────────────────────────────────────
    await trades_manager.update_trade(trade)
```

### Función `update_trailing_sl` con step dinámico

```python
def update_trailing_sl(
    trade: Trade,
    current_price: float,
    trailing_step: float = TRAILING_STEP_NORMAL
) -> bool:
    """
    Actualiza el trailing SL con el step correspondiente al contexto actual.
    El trailing SL solo sube, nunca baja.
    Nunca puede ser menor al precio de entrada (breakeven garantizado).
    """
    nuevo_sl = current_price * (1 - trailing_step)

    # Piso: nunca por debajo de la entrada
    nuevo_sl = max(nuevo_sl, trade.entry_price)

    if nuevo_sl > trade.trailing_sl_final:
        trade.trailing_sl_final = round(nuevo_sl, 8)
        return True
    return False
```

### Función `check_stalled_trade`

```python
async def check_stalled_trade(
    trade: Trade,
    current_price: float,
    ctx_actual: MarketContext | None
) -> None:
    """
    Detecta si una posición lleva demasiado tiempo sin llegar a TP1.
    Solo alerta — el operador decide si cerrar manualmente.
    No cierra automáticamente.
    """
    if trade.tp1_hit:
        return  # ya llegó a TP1, no es un trade estancado

    # Calcular tiempo abierto
    opened_at = datetime.fromisoformat(trade.started_at)
    minutos_abierto = (datetime.utcnow() - opened_at).total_seconds() / 60

    if minutos_abierto < STALL_THRESHOLD_MINUTES:
        return  # aún no es suficiente tiempo

    # Verificar si el precio se movió poco en el último período
    # (comparando con el precio registrado hace 4 checks = ~1 hora)
    movimiento = abs(current_price - trade.entry_price) / trade.entry_price

    if movimiento < STALL_PRICE_THRESHOLD:
        # Trade estancado — notificar UNA sola vez (evitar spam)
        if not getattr(trade, "stall_notified", False):
            trade.stall_notified = True

            contexto_str = ""
            if ctx_actual:
                contexto_str = f"\nMercado actual: {ctx_actual.trend} | {ctx_actual.volatility}"

            await telegram_client.send_stalled_trade_alert(
                trade, current_price, minutos_abierto, contexto_str
            )
```

### Mensaje de alerta de trade estancado

```
⏸ TRADE ESTANCADO — BTC/USDT

Sin movimiento significativo en 2hs sin llegar a TP1.
Mercado actual: SIDEWAYS | Volatilidad: LOW

📈 Entrada:  $74,200  |  Ahora: $74,310  (+0.15%)
🎯 TP1:      $75,025  (falta +$715 / +0.96%)
🛑 SL:       $73,650  (a -$660 / -0.89%)
⏱ Abierto:  2h 07min

¿Qué hacés?
[ 🔴 CERRAR AHORA ]  [ ⏳ ESPERAR ]
```

Si el operador presiona `CERRAR AHORA`:
- Registrar cierre al precio actual con `close_reason = "MANUAL_STALL"`
- P&L calculado normalmente

Si presiona `ESPERAR`:
- No volver a alertar hasta que pasen otras 2 horas más

---

## CAMBIO 3 — Actualizar `/contexto` para mostrar BTC global

**Archivo:** `src/lambdas/webhook/handler.py`

```python
async def handle_contexto_command(scan_id: str) -> str:
    """
    Muestra el contexto de BTC global + estado de cada par.
    """
    btc_ctx = await get_btc_context(scan_id)
    pares_activos = await pairs_manager.get_active_pairs()

    # Ícono del contexto de BTC
    btc_icon = {"BULLISH": "🟢", "SIDEWAYS": "🟡", "BEARISH": "🔴"}.get(btc_ctx.trend, "⚪")

    lineas = [
        f"{btc_icon} BTC GLOBAL: {btc_ctx.trend} | {btc_ctx.volatility}",
        f"   EMA21: ${btc_ctx.ema21:,.0f} | EMA50: ${btc_ctx.ema50:,.0f} | Close: ${btc_ctx.close:,.0f}",
        "",
        "📊 CONTEXTO POR PAR",
        "─" * 42,
    ]

    for par_config in pares_activos:
        pair = par_config["pair"]
        if pair in ("BTCUSDT", "BTCUSDC"):
            continue  # BTC ya está arriba

        # Evaluar contexto individual
        df = await binance_client.get_ohlcv(pair, "30m", limit=60)
        df = enrich_dataframe(df)
        ctx = await MarketContextEvaluator.evaluate(df, pair, par_config, scan_id)

        if ctx.tradeable:
            estado = "✅ OPERABLE "
        else:
            # Determinar si fue el filtro de BTC o el individual
            if ctx.btc_filter_applied and "BTC" in ctx.reason:
                estado = "🔴 BLOQ BTC "
            else:
                estado = "⏸ EN ESPERA"

        razon_corta = ctx.reason[:25] if len(ctx.reason) > 25 else ctx.reason
        sim_mode = par_config.get("sim_mode", "manual")
        modo_icon = "🤖" if sim_mode == "auto" else "👤" if sim_mode == "manual" else "⛔"

        lineas.append(
            f"{modo_icon} {pair:<10} {estado} "
            f"{ctx.trend:<8} | {ctx.volatility:<6} | {razon_corta}"
        )

    lineas.append("")
    lineas.append(f"Próxima evaluación: ~5 min")

    return "\n".join(lineas)
```

**Formato del comando `/contexto`:**

```
🟢 BTC GLOBAL: BULLISH | MEDIUM
   EMA21: $74,120 | EMA50: $73,800 | Close: $74,350

📊 CONTEXTO POR PAR
──────────────────────────────────────────
🤖 ETHUSDT     ✅ OPERABLE  BULLISH  | MEDIUM | OK
🤖 SOLUSDT     ⏸ EN ESPERA SIDEWAYS | LOW    | volumen bajo
👤 XRPUSDT     ✅ OPERABLE  BULLISH  | HIGH   | OK
👤 BNBUSDT     🔴 BLOQ BTC  BULLISH  | MEDIUM | BTC BEARISH — altcoins en riesgo
👤 AVAXUSDT    ⏸ EN ESPERA BEARISH  | MEDIUM | trend no bullish

Próxima evaluación: ~5 min
```

---

## CAMBIO 4 — Query Athena para analizar impacto del filtro BTC

Agregar en `infra/audit/saved_queries.tf`:

```hcl
resource "aws_athena_named_query" "btc_filter_impact" {
  name        = "11_impacto_filtro_btc"
  description = "Cuántas oportunidades bloquea el filtro de BTC y si mejora el winrate"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- IMPACTO DEL FILTRO DE BTC EN ALTCOINS
    -- Compara winrate de trades cuando BTC estaba alcista vs lateral/bajista
    SELECT
        t.strategy,
        t.pair,
        -- Contexto de BTC al momento de abrir el trade
        mc.btc_trend                                                        AS btc_trend_al_abrir,
        COUNT(*)                                                             AS total_trades,
        ROUND(AVG(CASE WHEN t.net_pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) AS winrate_pct,
        ROUND(AVG(t.r_multiple), 2)                                          AS r_multiple_avg,
        ROUND(SUM(t.net_pnl), 2)                                             AS pnl_total
    FROM trades t
    -- Join con el contexto de mercado al momento de apertura del trade
    JOIN market_context_log mc
        ON t.pair = mc.pair
        AND DATE(t.started_at) = DATE(mc.timestamp)
        AND ABS(
            DATE_DIFF('minute',
                PARSE_DATETIME(t.started_at, '%Y-%m-%dT%H:%i:%s'),
                PARSE_DATETIME(mc.timestamp, '%Y-%m-%dT%H:%i:%s')
            )
        ) <= 10   -- contexto dentro de 10 min de la apertura
    WHERE t.pair != 'BTCUSDT'   -- solo altcoins
        AND mc.btc_filter_applied = true
    GROUP BY t.strategy, t.pair, mc.btc_trend
    ORDER BY t.pair, mc.btc_trend, r_multiple_avg DESC;
  SQL
}

resource "aws_athena_named_query" "btc_sideways_altcoin_performance" {
  name        = "12_altcoins_con_btc_lateral"
  description = "Rendimiento de altcoins cuando BTC está lateral (¿vale operar?)"
  workgroup   = aws_athena_workgroup.audit.name
  database    = aws_glue_catalog_database.audit.name

  query = <<-SQL
    -- ALTCOINS CON BTC LATERAL
    -- Responde: cuando BTC está SIDEWAYS pero el par está BULLISH,
    -- ¿conviene operar o es mejor esperar a que BTC confirme?
    SELECT
        t.strategy,
        COUNT(*)                                                             AS trades,
        ROUND(AVG(CASE WHEN t.net_pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) AS winrate_pct,
        ROUND(AVG(t.r_multiple), 2)                                          AS r_multiple_avg,
        ROUND(AVG(t.duration_minutes), 0)                                    AS duracion_promedio_min,
        ROUND(AVG(t.mae) * 100, 3)                                           AS mae_promedio_pct
    FROM trades t
    JOIN market_context_log mc
        ON t.pair = mc.pair
        AND DATE(t.started_at) = DATE(mc.timestamp)
        AND ABS(DATE_DIFF('minute',
            PARSE_DATETIME(t.started_at, '%Y-%m-%dT%H:%i:%s'),
            PARSE_DATETIME(mc.timestamp, '%Y-%m-%dT%H:%i:%s')
        )) <= 10
    WHERE t.pair != 'BTCUSDT'
        AND mc.btc_trend = 'SIDEWAYS'   -- BTC lateral
        AND mc.trend = 'BULLISH'        -- pero el par alcista
    GROUP BY t.strategy
    ORDER BY r_multiple_avg DESC;
  SQL
}
```

---

## Tests requeridos — `tests/test_btc_context_filter.py`

```python
# test_btc_context_cacheado_por_ciclo
# Verificar que get_btc_context() solo llama a Binance una vez por scan_id
# aunque se llame múltiples veces en el mismo ciclo

# test_btc_bearish_bloquea_todas_las_altcoins
# Con BTC BEARISH, verificar que ninguna altcoin pasa el evaluador
# aunque su tendencia individual sea BULLISH

# test_btc_bullish_no_afecta_evaluacion_individual
# Con BTC BULLISH, verificar que la evaluación individual del par
# sigue siendo el criterio determinante

# test_btc_sideways_altcoin_bullish_permite_con_advertencia
# Con BTC SIDEWAYS y par BULLISH, verificar que tradeable=True
# pero se loguea la advertencia

# test_btc_sideways_altcoin_sideways_bloquea
# Con BTC SIDEWAYS y par SIDEWAYS, verificar que tradeable=False

# test_btc_no_aplica_para_btcusdt
# Verificar que BTCUSDT no aplica el filtro de BTC (no se consulta a sí mismo)

# test_trailing_normal_en_mercado_alcista
# Con mercado BULLISH, verificar que trailing_step = 0.5%

# test_trailing_agresivo_en_mercado_bajista
# Con par BEARISH, verificar que trailing_step = 0.3%

# test_trailing_emergencia_par_bearish_btc_bearish
# Con par BEARISH + BTC BEARISH, verificar que trailing_step = 0.2%

# test_trailing_sl_nunca_baja_con_step_agresivo
# Con trailing agresivo, verificar que el SL nunca baja aunque
# el nuevo valor calculado sea menor al actual

# test_stalled_trade_alerta_a_las_2hs
# Verificar que después de 2hs sin TP1 y sin movimiento se envía alerta
# pero solo una vez (no spam)

# test_stalled_trade_no_alerta_si_hay_movimiento
# Verificar que si el precio se movió > 0.1% no se considera estancado

# test_stalled_trade_no_alerta_si_tp1_alcanzado
# Verificar que si ya llegó a TP1 no se evalúa como estancado

# test_contexto_command_muestra_btc_global
# Verificar que /contexto incluye el estado global de BTC al inicio

# test_contexto_command_muestra_bloq_btc
# Verificar que pares bloqueados por BTC muestran "🔴 BLOQ BTC"
```

---

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `src/core/market_context.py` | `get_btc_context()` con cache, filtro BTC en `evaluate()`, nuevo campo `btc_trend` en `MarketContext` |
| `src/core/simulator.py` | `evaluate()` con contexto dinámico, `update_trailing_sl()` con step dinámico, `check_stalled_trade()` |
| `src/lambdas/scanner/handler.py` | Pasar `scan_id` a `evaluate()`, reset del cache BTC al inicio del ciclo |
| `src/lambdas/webhook/handler.py` | `/contexto` actualizado con BTC global y bloqueos |
| `src/core/telegram_client.py` | `send_stalled_trade_alert()`, `send_trailing_update()` con indicador de agresividad |
| `infra/audit/saved_queries.tf` | 2 queries nuevas para analizar impacto del filtro BTC |
| `tests/test_btc_context_filter.py` | Crear archivo con todos los tests |

## Archivos a NO modificar
- `src/strategies/` — las estrategias no cambian
- `src/core/calculator.py` — la calculadora no cambia
- `src/core/indicators.py` — los indicadores no cambian
- `infra/` salvo `saved_queries.tf`

---

## Orden de implementación

1. `market_context.py` → agregar `BtcContext`, `get_btc_context()` y filtro en `evaluate()`
2. `simulator.py` → trailing dinámico y `check_stalled_trade()`
3. `scanner/handler.py` → pasar `scan_id` al evaluador
4. `webhook/handler.py` → `/contexto` actualizado
5. `telegram_client.py` → nuevos mensajes
6. `saved_queries.tf` → queries de Athena
7. Tests

---

## Comportamiento esperado después del cambio

```
ANTES:
  75 pares evaluados individualmente
  Cada par solo mira su propia tendencia
  Si BTC cae 3%, las altcoins siguen generando señales

DESPUÉS:
  BTC se evalúa UNA vez por ciclo (cache por scan_id)
  Si BTC BEARISH → 0 altcoins operables (protección total)
  Si BTC SIDEWAYS + par SIDEWAYS → bloqueado
  Si BTC SIDEWAYS + par BULLISH → permitido con trailing más atento

  Posiciones abiertas:
  Si el mercado gira adverso → trailing se vuelve más agresivo
  Si la posición lleva 2hs sin TP1 → alerta con opción de cerrar
```

---

*La correlación BTC-altcoins en mercados bajistas es cercana al 0.85.*
*Operar altcoins cuando BTC cae es una de las causas más comunes de pérdidas evitables.*
